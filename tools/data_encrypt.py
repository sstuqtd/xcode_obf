#!/usr/bin/env python3
"""
Data/Raw 文件加密/解密工具
加密 Xcode/Unity 工程中 Data/Raw 下的文件，生成运行时解密加载器。
"""

import argparse
import os
import re
import secrets
import sys
from pathlib import Path


def xor_encrypt(data: bytes, key: bytes) -> bytes:
    """XOR 加密/解密（对称）"""
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def encrypt_file(input_path: Path, output_path: Path, key: bytes) -> None:
    """加密单个文件"""
    data = input_path.read_bytes()
    encrypted = xor_encrypt(data, key)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encrypted)


def decrypt_file(input_path: Path, output_path: Path, key: bytes) -> None:
    """解密单个文件（XOR 对称）"""
    encrypt_file(input_path, output_path, key)


def generate_key_hex(key: bytes) -> str:
    return ", ".join(f"0x{b:02X}" for b in key)


_DATA_RAW_HOOK_HEADER = '''#import <Foundation/Foundation.h>

#ifdef __cplusplus
extern "C" {
#endif
void DataRawHookInstall(void);
#ifdef __cplusplus
}
#endif
'''


def generate_objc_loader(key: bytes, key_name: str = "kDataEncryptKey") -> str:
    """生成 ObjC 解密加载器"""
    key_hex = generate_key_hex(key)
    return f'''
#import <Foundation/Foundation.h>

static unsigned char {key_name}[] = {{{key_hex}}};
static const int {key_name}Len = sizeof({key_name});

NSData *DecryptedDataFromBundle(NSString *relativePath) {{
    NSString *path = [[NSBundle mainBundle] pathForResource:relativePath ofType:nil inDirectory:nil];
    if (!path) {{
        path = [[[NSBundle mainBundle] resourcePath] stringByAppendingPathComponent:relativePath];
    }}
    NSData *encrypted = [NSData dataWithContentsOfFile:path];
    if (!encrypted || encrypted.length == 0) return nil;
    NSMutableData *decrypted = [NSMutableData dataWithLength:encrypted.length];
    unsigned char *dst = decrypted.mutableBytes;
    const unsigned char *src = encrypted.bytes;
    for (NSUInteger i = 0; i < encrypted.length; i++) {{
        dst[i] = src[i] ^ {key_name}[i % {key_name}Len];
    }}
    return decrypted;
}}
'''


def generate_objc_hook(key: bytes, key_name: str = "kDataEncryptKey") -> str:
    """生成 ObjC Hook 解密加载器（替换 NSData dataWithContentsOfFile:，Data/Raw 路径先解密再返回）"""
    key_hex = generate_key_hex(key)
    return f'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>

static unsigned char {key_name}[] = {{{key_hex}}};
static const int {key_name}Len = sizeof({key_name});

static NSData* (*original_dataWithContentsOfFile)(id, SEL, NSString*) = nil;

static NSData* hooked_dataWithContentsOfFile(id self, SEL _cmd, NSString* path) {{
    if (!path || path.length == 0)
        return original_dataWithContentsOfFile ? original_dataWithContentsOfFile(self, _cmd, path) : nil;

    NSString* p = [path stringByStandardizingPath];
    if ([p containsString:@"Data/Raw"] || [p rangeOfString:@"/Raw/"].location != NSNotFound) {{
        NSData* encrypted = original_dataWithContentsOfFile(self, _cmd, path);
        if (!encrypted || encrypted.length == 0) return nil;
        NSMutableData* decrypted = [NSMutableData dataWithLength:encrypted.length];
        unsigned char* dst = decrypted.mutableBytes;
        const unsigned char* src = encrypted.bytes;
        for (NSUInteger i = 0; i < encrypted.length; i++)
            dst[i] = src[i] ^ {key_name}[i % {key_name}Len];
        return decrypted;
    }}
    return original_dataWithContentsOfFile(self, _cmd, path);
}}

void DataRawHookInstall(void) {{
    if (original_dataWithContentsOfFile) return;
    Method m = class_getClassMethod([NSData class], @selector(dataWithContentsOfFile:));
    if (!m) return;
    original_dataWithContentsOfFile = (void*)method_getImplementation(m);
    method_setImplementation(m, (IMP)hooked_dataWithContentsOfFile);
}}
'''


def generate_swift_loader(key: bytes) -> str:
    """生成 Swift 解密加载器"""
    key_hex = generate_key_hex(key)
    return f'''
import Foundation

private let _dataEncryptKey: [UInt8] = [{key_hex}]

func decryptedDataFromBundle(relativePath: String) -> Data? {{
    guard let url = Bundle.main.url(forResource: relativePath, withExtension: nil)
        ?? Bundle.main.resourceURL?.appendingPathComponent(relativePath),
        let encrypted = try? Data(contentsOf: url) else {{ return nil }}
    return Data(encrypted.enumerated().map {{ $0.element ^ _dataEncryptKey[$0.offset % _dataEncryptKey.count] }})
}}
'''


def _gen_uuid() -> str:
    """生成 24 位 hex UUID（Xcode pbxproj 格式）"""
    return secrets.token_hex(12).upper()


def _add_data_raw_hook_to_pbxproj(project_root: Path, classes_dir: Path) -> bool:
    """将 DataRawHook.m/.h 添加到 Xcode 工程，返回是否成功"""
    xcodeproj = next(project_root.glob("*.xcodeproj"), None)
    if not xcodeproj:
        return False
    pbx = xcodeproj / "project.pbxproj"
    if not pbx.is_file():
        return False

    content = pbx.read_text(encoding="utf-8", errors="replace")
    if "DataRawHook.m" in content:
        return True  # 已添加

    ref_m = _gen_uuid()
    ref_h = _gen_uuid()
    build_m = _gen_uuid()

    # PBXFileReference
    file_ref_m = f'{ref_m} /* DataRawHook.m */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.c.objc; path = DataRawHook.m; sourceTree = "<group>"; }};'
    file_ref_h = f'{ref_h} /* DataRawHook.h */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.c.h; path = DataRawHook.h; sourceTree = "<group>"; }};'

    # PBXBuildFile
    build_file = f'{build_m} /* DataRawHook.m in Sources */ = {{isa = PBXBuildFile; fileRef = {ref_m} /* DataRawHook.m */; }};'

    # 插入 PBXFileReference
    fr_match = re.search(r'(/\* Begin PBXFileReference section \*/\n)', content)
    if fr_match:
        content = content[: fr_match.end()] + f"\t\t{file_ref_m}\n\t\t{file_ref_h}\n" + content[fr_match.end() :]

    # 插入 PBXBuildFile
    bf_match = re.search(r'(/\* Begin PBXBuildFile section \*/\n)', content)
    if bf_match:
        content = content[: bf_match.end()] + f"\t\t{build_file}\n" + content[bf_match.end() :]

    # 添加到 Classes 组的 children（匹配 path = Classes 或 name = Classes）
    classes_pattern = r'([a-fA-F0-9]{24} /\* Classes \*\/ = \{\s+isa = PBXGroup;\s+children = \()(.*?)(\);)'
    classes_alt = r'(\/\* Classes \*\/ = \{\s+isa = PBXGroup;\s+children = \()(.*?)(\);)'
    new_refs = f"\n\t\t\t{ref_m} /* DataRawHook.m */,\n\t\t\t{ref_h} /* DataRawHook.h */,"

    def add_to_classes(m):
        prefix, children, suffix = m.groups()
        return prefix + new_refs + children + suffix

    content = re.sub(classes_pattern, add_to_classes, content, flags=re.DOTALL)
    if "DataRawHook.m" not in content:
        content = re.sub(classes_alt, add_to_classes, content, flags=re.DOTALL)

    # 添加到 PBXSourcesBuildPhase 的 files（优先添加到含 UnityAppController 的 target）
    sources_pattern = r'([a-fA-F0-9]{24} /\* Sources \*\/ = \{\s+isa = PBXSourcesBuildPhase;\s+buildActionMask = [^;]+;\s+files = \()(.*?)(\);)'
    added = False

    def add_to_sources(m):
        nonlocal added
        prefix, files, suffix = m.groups()
        if added:
            return m.group(0)
        if "UnityAppController" in files or ".mm" in files or ".m " in files:
            new_file = f"\n\t\t\t{build_m} /* DataRawHook.m in Sources */,"
            added = True
            return prefix + new_file + files + suffix
        return m.group(0)

    content = re.sub(sources_pattern, add_to_sources, content, flags=re.DOTALL)
    if not added:
        m = re.search(r'([a-fA-F0-9]{24} /\* Sources \*\/ = \{\s+isa = PBXSourcesBuildPhase;\s+buildActionMask = [^;]+;\s+files = \()(.*?)(\);)', content, re.DOTALL)
        if m:
            prefix, files, suffix = m.groups()
            new_file = f"\n\t\t\t{build_m} /* DataRawHook.m in Sources */,"
            content = content[: m.start()] + prefix + new_file + files + suffix + content[m.end() :]

    pbx.write_text(content, encoding="utf-8")
    return True


def _inject_data_raw_hook_into_unity_app_controller(classes_dir: Path) -> bool:
    """在 UnityAppController.mm 的 didFinishLaunchingWithOptions 中注入 DataRawHookInstall()"""
    uac = classes_dir / "UnityAppController.mm"
    if not uac.is_file():
        return False

    content = uac.read_text(encoding="utf-8", errors="replace")
    if "DataRawHookInstall" in content:
        return True  # 已注入

    # 添加 #import（在第一个 #import 后，若无则在文件开头）
    if '#import "DataRawHook.h"' not in content:
        import_match = re.search(r'(#import\s+[^\n]+\n)', content)
        if import_match:
            content = content[: import_match.end()] + '#import "DataRawHook.h"\n' + content[import_match.end() :]
        else:
            content = '#import "DataRawHook.h"\n' + content

    # 在 didFinishLaunchingWithOptions 方法体开头添加 DataRawHookInstall();
    # 匹配 - (BOOL)application:...didFinishLaunchingWithOptions: 后的 { 及换行
    pattern = r'(didFinishLaunchingWithOptions:\s*\([^)]*\)[^\n]*\n\s*\{)\s*\n'
    replacement = r'\1\n\tDataRawHookInstall();\n'
    new_content = re.sub(pattern, replacement, content, count=1)

    if new_content != content:
        uac.write_text(new_content, encoding="utf-8")
        return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Data/Raw 文件加密/解密，生成运行时加载器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", help="子命令")

    # 加密
    p_enc = sub.add_parser("encrypt", help="加密文件")
    p_enc.add_argument("input", help="Data/Raw 目录或文件")
    p_enc.add_argument("-o", "--output", help="输出路径（默认直接修改原工程文件）")
    p_enc.add_argument("--key", help="16 进制密钥，如 1A2B3C（默认随机生成）")
    p_enc.add_argument("--key-out", help="密钥输出文件（供解密和加载器使用）")

    # 解密
    p_dec = sub.add_parser("decrypt", help="解密文件")
    p_dec.add_argument("input", help="加密后的目录或文件")
    p_dec.add_argument("-o", "--output", help="输出路径")
    p_dec.add_argument("--key", required=True, help="16 进制密钥（与加密时一致）")

    # 生成加载器
    p_gen = sub.add_parser("gen-loader", help="生成解密加载器代码")
    p_gen.add_argument("--key", required=True, help="16 进制密钥")
    p_gen.add_argument("-o", "--output", help="输出文件路径")
    p_gen.add_argument("--lang", choices=["objc", "swift"], default="objc")

    # 生成 Hook 加载器（Method Swizzling 拦截 NSData dataWithContentsOfFile:）
    p_hook = sub.add_parser("gen-hook", help="生成 Hook 解密加载器（自动拦截 Data/Raw 读取）")
    p_hook.add_argument("--key", required=True, help="16 进制或文本密钥")
    p_hook.add_argument("-o", "--output", help="输出 .m 文件路径（默认 DataRawHook.m）")

    # 一键完成：加密 Data/Raw + 生成 Hook 加载器
    p_setup = sub.add_parser("setup-raw", help="一键加密 Data/Raw 并生成 Hook 加载器（Unity Xcode 工程）")
    p_setup.add_argument("project", nargs="?", default=".", help="工程根目录（默认当前目录）")
    p_setup.add_argument("--key", help="密钥（默认随机生成，支持十六进制或文本如 xwlkey）")
    p_setup.add_argument("--key-out", default="key.bin", help="密钥输出文件（默认 key.bin）")

    args = parser.parse_args()

    def parse_key(s: str) -> bytes:
        s = s.replace(" ", "").replace("0x", "").replace(",", "")
        try:
            return bytes.fromhex(s)
        except ValueError:
            return s.encode("utf-8")

    if args.cmd == "encrypt":
        key = parse_key(args.key) if args.key else secrets.token_bytes(16)
        input_path = Path(args.input)
        output_path = Path(args.output) if args.output else input_path

        if input_path.is_file():
            encrypt_file(input_path, output_path / input_path.name, key)
            count = 1
        else:
            count = 0
            for f in input_path.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(input_path)
                    out = output_path / rel
                    encrypt_file(f, out, key)
                    count += 1

        if args.key_out:
            Path(args.key_out).write_bytes(key)
            Path(str(args.key_out) + ".hex").write_text(key.hex())
            print(f"密钥已保存: {args.key_out}（hex: {args.key_out}.hex）")

        print(f"加密完成: {count} 个文件")
        print(f"密钥(hex): {key.hex()}")
        print("生成加载器: python3 data_encrypt.py gen-loader --key", key.hex(), "-o DecryptedDataLoader.m")

    elif args.cmd == "decrypt":
        key = parse_key(args.key)
        input_path = Path(args.input)
        output_path = Path(args.output or "decrypted")

        if input_path.is_file():
            decrypt_file(input_path, output_path / input_path.name, key)
            count = 1
        else:
            count = 0
            for f in input_path.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(input_path)
                    out = output_path / rel
                    decrypt_file(f, out, key)
                    count += 1

        print(f"解密完成: {count} 个文件")

    elif args.cmd == "gen-loader":
        key = parse_key(args.key)
        if args.lang == "objc":
            code = generate_objc_loader(key)
            ext = ".m"
        else:
            code = generate_swift_loader(key)
            ext = ".swift"

        out_path = Path(args.output or f"DecryptedDataLoader{ext}")
        out_path.write_text(code, encoding="utf-8")
        print(f"加载器已生成: {out_path}")

    elif args.cmd == "gen-hook":
        key = parse_key(args.key)
        code = generate_objc_hook(key)
        out_m = Path(args.output or "DataRawHook.m")
        out_m.write_text(code, encoding="utf-8")
        out_h = out_m.with_suffix(".h")
        out_h.write_text(_DATA_RAW_HOOK_HEADER, encoding="utf-8")
        print(f"Hook 加载器已生成: {out_m}, {out_h}")
        print("集成: 在 application:didFinishLaunchingWithOptions 最早处调用 DataRawHookInstall();")

    elif args.cmd == "setup-raw":
        project_root = Path(args.project).resolve()
        data_raw = project_root / "Data" / "Raw"
        classes_dir = project_root / "Classes"
        if not data_raw.is_dir():
            print(f"错误: 未找到 Data/Raw 目录: {data_raw}", file=sys.stderr)
            sys.exit(1)
        key = parse_key(args.key) if args.key else secrets.token_bytes(16)
        key_out = project_root / args.key_out
        key_out.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        for f in data_raw.rglob("*"):
            if f.is_file():
                encrypt_file(f, f, key)
                count += 1

        key_out.write_bytes(key)
        (Path(str(key_out) + ".hex")).write_text(key.hex())
        print(f"加密完成: Data/Raw 下 {count} 个文件")
        print(f"密钥已保存: {key_out}")

        classes_dir.mkdir(parents=True, exist_ok=True)
        code = generate_objc_hook(key)
        out_m = classes_dir / "DataRawHook.m"
        out_h = classes_dir / "DataRawHook.h"
        out_m.write_text(code, encoding="utf-8")
        out_h.write_text(_DATA_RAW_HOOK_HEADER, encoding="utf-8")
        print(f"Hook 加载器已生成: {out_m}, {out_h}")

        if _add_data_raw_hook_to_pbxproj(project_root, classes_dir):
            print("已自动添加到 Xcode 工程 (Classes)")
        else:
            print("提示: 请手动将 DataRawHook.m、DataRawHook.h 加入 Xcode Classes 组")

        if _inject_data_raw_hook_into_unity_app_controller(classes_dir):
            print("已在 UnityAppController.mm 中注入 DataRawHookInstall()")
        else:
            print("提示: 请在 UnityAppController.mm 的 didFinishLaunchingWithOptions 中手动调用 DataRawHookInstall();")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

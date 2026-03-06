#!/usr/bin/env python3
"""
Data/Raw 文件加密/解密工具
加密 Xcode/Unity 工程中 Data/Raw 下的文件，生成运行时解密加载器。
"""

import argparse
import os
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
    p_hook.add_argument("--key", required=True, help="16 进制密钥")
    p_hook.add_argument("-o", "--output", help="输出 .m 文件路径（默认 DataRawHook.m）")

    args = parser.parse_args()

    def parse_key(s: str) -> bytes:
        s = s.replace(" ", "").replace("0x", "").replace(",", "")
        return bytes.fromhex(s)

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
        out_h.write_text(
            "#import <Foundation/Foundation.h>\n\nvoid DataRawHookInstall(void);\n",
            encoding="utf-8",
        )
        print(f"Hook 加载器已生成: {out_m}, {out_h}")
        print("集成: 在 application:didFinishLaunchingWithOptions 最早处调用 DataRawHookInstall();")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

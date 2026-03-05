#!/usr/bin/env python3
"""
字符串自动加密/解密工具
扫描 Swift/ObjC 源文件中的字符串字面量，自动加密并生成运行时解密代码。
"""

import argparse
import re
import secrets
import sys
from pathlib import Path


def xor_obfuscate(s: str, key: int | None = None) -> tuple[list[int], int]:
    """XOR 加密，返回 (加密字节列表, key)"""
    key = key or secrets.randbelow(256)
    data = s.encode("utf-8")
    return [b ^ key for b in data], key


def extract_strings_from_content(content: str, lang: str) -> list[tuple[int, int, str]]:
    """
    提取字符串字面量，返回 [(start, end, string), ...]
    lang: "swift" | "objc"
    """
    results = []
    if lang == "objc":
        # ObjC: @"..." 和 @"...\"
        for m in re.finditer(r'@"([^"\\]*(?:\\.[^"\\]*)*)"', content):
            results.append((m.start(), m.end(), m.group(1)))
    else:
        # Swift: "..." 排除 #"..." 等
        for m in re.finditer(r'(?<![#\\])"([^"\\]*(?:\\.[^"\\]*)*)"', content):
            results.append((m.start(), m.end(), m.group(1)))
    return results


def process_file_encrypt(
    content: str,
    lang: str,
    min_len: int = 3,
    exclude_pattern: re.Pattern | None = None,
) -> tuple[str, dict[str, tuple[list[int], int]]]:
    """
    加密文件中的字符串，返回 (替换后的内容, {ident: (bytes, key)})
    """
    strings = extract_strings_from_content(content, lang)
    replacements = {}
    result = content
    offset = 0

    for start, end, s in sorted(strings, key=lambda x: x[0]):
        if len(s) < min_len:
            continue
        if exclude_pattern and exclude_pattern.search(s):
            continue
        if not s.strip() or s.isdigit():
            continue
        ident = "s" + secrets.token_hex(3)
        bytes_list, key = xor_obfuscate(s)
        replacements[ident] = (bytes_list, key)
        if lang == "objc":
            new_text = f"[ObfuscatedStrings {ident}]"
        else:
            new_text = f"ObfuscatedStrings.{ident}"
        orig_len = end - start
        result = result[: start + offset] + new_text + result[end + offset :]
        offset += len(new_text) - orig_len

    return result, replacements


def generate_objc_decoder(encrypted: dict[str, tuple[list[int], int]]) -> tuple[str, str]:
    """生成 ObjC 解密类，返回 (header, implementation)"""
    h_lines = [
        "#import <Foundation/Foundation.h>",
        "",
        "@interface ObfuscatedStrings : NSObject",
        "",
    ]
    for ident, _ in encrypted.items():
        h_lines.append(f"+ (NSString *){ident};")
    h_lines.append("")
    h_lines.append("@end")

    m_lines = [
        '#import "ObfuscatedStrings.h"',
        "",
        "@implementation ObfuscatedStrings",
    ]
    for ident, (bytes_list, key) in encrypted.items():
        hex_bytes = ", ".join(f"0x{b:02X}" for b in bytes_list)
        m_lines.append(f"+ (NSString *){ident} {{")
        m_lines.append(f"    unsigned char bytes[] = {{{hex_bytes}}};")
        m_lines.append(f"    unsigned char key = 0x{key:02X};")
        m_lines.append(f"    NSMutableData *data = [NSMutableData dataWithLength:sizeof(bytes)];")
        m_lines.append(f"    unsigned char *ptr = data.mutableBytes;")
        m_lines.append(f"    for (int i = 0; i < sizeof(bytes); i++) ptr[i] = bytes[i] ^ key;")
        m_lines.append(f"    return [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];")
        m_lines.append("}")
        m_lines.append("")
    m_lines.append("@end")
    return "\n".join(h_lines), "\n".join(m_lines)


def generate_swift_decoder(encrypted: dict[str, tuple[list[int], int]]) -> str:
    """生成 Swift 解密枚举"""
    lines = [
        "import Foundation",
        "",
        "enum ObfuscatedStrings {",
    ]
    for ident, (bytes_list, key) in encrypted.items():
        hex_bytes = ", ".join(f"0x{b:02X}" for b in bytes_list)
        lines.append(f"    static var {ident}: String {{ [UInt8]([{hex_bytes}])._obfDecode(key: 0x{key:02X}) }}")
    lines.append("}")
    lines.append("")
    lines.append("private extension Array where Element == UInt8 {")
    lines.append("    func _obfDecode(key: UInt8) -> String {")
    lines.append("        String(decoding: map { $0 ^ key }, as: UTF8.self)")
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="字符串自动加密/解密，生成运行时解码代码",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", nargs="+", help="源文件或目录")
    parser.add_argument("-o", "--output-dir", help="输出目录（默认直接修改原工程文件）")
    parser.add_argument("--decoder-output", help="解密器输出路径（自动生成 ObfuscatedStrings）")
    parser.add_argument("--min-len", type=int, default=3, help="最小字符串长度")
    parser.add_argument("--exclude", default=r"^\d+$|^[a-fA-F0-9]{8,}$", help="排除的正则")
    parser.add_argument("--dry-run", action="store_true", help="仅预览")

    args = parser.parse_args()

    exclude_pattern = re.compile(args.exclude) if args.exclude else None
    all_encrypted = {}
    files_to_write = []

    for inp in args.input:
        path = Path(inp)
        if not path.exists():
            print(f"跳过不存在: {path}", file=sys.stderr)
            continue
        if path.is_file():
            paths = [path]
        else:
            paths = list(path.rglob("*.m")) + list(path.rglob("*.mm")) + list(path.rglob("*.swift"))

        for p in paths:
            if "Pods" in str(p) or "DerivedData" in str(p):
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                lang = "objc" if p.suffix in (".m", ".mm") else "swift"
                new_content, encrypted = process_file_encrypt(
                    content, lang, args.min_len, exclude_pattern
                )
                if encrypted:
                    all_encrypted.update(encrypted)
                    if lang == "objc" and '#import "ObfuscatedStrings.h"' not in new_content:
                        new_content = '#import "ObfuscatedStrings.h"\n' + new_content
                    out_path = Path(args.output_dir or p.parent) / p.name if args.output_dir else p
                    files_to_write.append((out_path, new_content, p))
            except Exception as e:
                print(f"处理失败 {p}: {e}", file=sys.stderr)

    if not all_encrypted:
        print("未找到可加密的字符串")
        return

    if not args.dry_run:
        for out_path, new_content, _ in files_to_write:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(new_content, encoding="utf-8")
            print(f"已写入: {out_path}")

        decoder_base = Path(args.decoder_output or Path(args.input[0]).parent / "ObfuscatedStrings")
        decoder_base = decoder_base.parent / decoder_base.stem if decoder_base.suffix else decoder_base
        if any(str(p).endswith(".swift") for _, _, p in files_to_write):
            decoder_path = decoder_base.with_suffix(".swift")
            decoder_path.write_text(generate_swift_decoder(all_encrypted), encoding="utf-8")
            print(f"解密器: {decoder_path}")
        else:
            h_path = decoder_base.with_suffix(".h")
            m_path = decoder_base.with_suffix(".m")
            h_content, m_content = generate_objc_decoder(all_encrypted)
            h_path.write_text(h_content, encoding="utf-8")
            m_path.write_text(m_content, encoding="utf-8")
            print(f"解密器: {h_path}, {m_path}")
    else:
        print(f"将加密 {len(all_encrypted)} 个字符串，涉及 {len(files_to_write)} 个文件（dry-run）")


if __name__ == "__main__":
    main()

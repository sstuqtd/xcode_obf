#!/usr/bin/env python3
"""
字符串字面量混淆工具
将敏感字符串（URL、API Key 等）转为 XOR 混淆的 Swift/ObjC 代码，运行时解码。
"""

import argparse
import re
import secrets
import sys
from pathlib import Path


def xor_obfuscate(s: str, key: int | None = None) -> tuple[list[int], int]:
    """XOR 混淆，返回 (混淆后的字节列表, 使用的 key)"""
    key = key or secrets.randbelow(256)
    data = s.encode("utf-8")
    return [b ^ key for b in data], key


def generate_swift_decoder() -> str:
    """生成 Swift 解码器扩展代码"""
    return '''
// 由 literal_obfuscator.py 生成 - 运行时解码混淆字符串
extension Array where Element == UInt8 {
    func _obfDecode(key: UInt8) -> String {
        String(decoding: map { $0 ^ key }, as: UTF8.self)
    }
}
'''


def generate_swift_obfuscated(identifier: str, s: str, key: int | None = None) -> str:
    """生成单个混淆字符串的 Swift 代码"""
    bytes_list, k = xor_obfuscate(s, key)
    hex_bytes = ", ".join(f"0x{b:02X}" for b in bytes_list)
    return f'    static var {identifier}: String {{ [UInt8]([{hex_bytes}])._obfDecode(key: 0x{k:02X}) }}'


def generate_objc_obfuscated(identifier: str, s: str, key: int | None = None) -> str:
    """生成 ObjC 的解码函数"""
    bytes_list, k = xor_obfuscate(s, key)
    hex_bytes = ", ".join(f"0x{b:02X}" for b in bytes_list)
    return f'''
+ (NSString *){identifier} {{
    unsigned char bytes[] = {{{hex_bytes}}};
    unsigned char key = 0x{k:02X};
    NSMutableData *data = [NSMutableData dataWithLength:sizeof(bytes)];
    unsigned char *ptr = data.mutableBytes;
    for (int i = 0; i < sizeof(bytes); i++) ptr[i] = bytes[i] ^ key;
    return [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
}}
'''


def parse_config(config_content: str) -> list[tuple[str, str]]:
    """
    解析配置，格式：
    identifier = "string value"
    或
    identifier = 'string value'
    支持 # 开头的注释行
    """
    result = []
    for line in config_content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 匹配 identifier = "value" 或 identifier = 'value'
        m = re.match(r"(\w+)\s*=\s*([\"'])(.+?)\2\s*$", line)
        if m:
            result.append((m.group(1), m.group(3)))
    return result


def scan_swift_for_strings(path: str, pattern: re.Pattern | None = None) -> list[tuple[str, str]]:
    """
    扫描 Swift 文件中的字符串字面量。
    pattern: 可选，只匹配符合的字符串（如 URL、含 api 的）
    """
    path = Path(path)
    content = path.read_text(encoding="utf-8", errors="replace")
    # 匹配 "..." 和 """...""" 多行字符串
    matches = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', content)
    result = []
    seen = set()
    for s in matches:
        if len(s) < 4 or s in seen:
            continue
        if pattern and not pattern.search(s):
            continue
        seen.add(s)
        # 生成合法标识符
        ident = "s" + secrets.token_hex(3)
        result.append((ident, s))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="生成 XOR 混淆的字符串字面量代码，降低 IPA 相似度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", help="子命令")

    # 从配置文件生成
    p_config = sub.add_parser("config", help="从配置文件生成")
    p_config.add_argument("config", help="配置文件路径，格式: key = \"value\"")
    p_config.add_argument("-o", "--output", required=True, help="输出 Swift 文件路径")
    p_config.add_argument("--objc", action="store_true", help="生成 ObjC 而非 Swift")

    # 从 Swift 文件扫描并生成
    p_scan = sub.add_parser("scan", help="扫描 Swift 文件中的字符串并生成")
    p_scan.add_argument("source", help="Swift 源文件路径")
    p_scan.add_argument("-o", "--output", required=True, help="输出 Swift 文件路径")
    p_scan.add_argument(
        "--pattern",
        default=r"https?://|api|key|token|secret|password",
        help="只匹配包含此正则的字符串",
    )

    args = parser.parse_args()

    if args.cmd == "config":
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"配置文件不存在: {config_path}", file=sys.stderr)
            sys.exit(1)
        entries = parse_config(config_path.read_text(encoding="utf-8"))
        if not entries:
            print("未解析到有效配置", file=sys.stderr)
            sys.exit(1)

        if args.objc:
            lines = ["#import <Foundation/Foundation.h>", "@interface ObfuscatedStrings : NSObject"]
            for ident, s in entries:
                lines.append(generate_objc_obfuscated(ident, s))
            lines.append("@end")
            output = "\n".join(lines)
        else:
            lines = ["import Foundation", "", generate_swift_decoder().strip(), "", "enum Obfuscated {"]
            for ident, s in entries:
                lines.append(generate_swift_obfuscated(ident, s))
            lines.append("}")
            output = "\n".join(lines)

        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"已生成: {out_path} ({len(entries)} 个字符串)")

    elif args.cmd == "scan":
        src_path = Path(args.source)
        if not src_path.exists():
            print(f"源文件不存在: {src_path}", file=sys.stderr)
            sys.exit(1)
        pat = re.compile(args.pattern, re.I)
        entries = scan_swift_for_strings(str(src_path), pat)
        if not entries:
            print("未找到匹配的字符串", file=sys.stderr)
            sys.exit(1)

        lines = ["import Foundation", "", generate_swift_decoder().strip(), "", "enum Obfuscated {"]
        for ident, s in entries:
            lines.append(generate_swift_obfuscated(ident, s))
        lines.append("}")

        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"已生成: {out_path} ({len(entries)} 个字符串)")
        for ident, s in list(entries)[:5]:
            print(f"  {ident}: {s[:40]}...")
        if len(entries) > 5:
            print("  ...")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

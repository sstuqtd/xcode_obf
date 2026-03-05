#!/usr/bin/env python3
"""
Localizable.strings 混淆工具
将键名混淆为无意义字符串，生成映射表供运行时还原。
"""

import argparse
import json
import re
import secrets
import sys
from pathlib import Path


def parse_strings_file(path: str) -> list[tuple[str, str, str]]:
    """
    解析 .strings 文件，返回 [(key, value, raw_line), ...]
    保留注释和空行结构。
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # 匹配 "key" = "value"; 格式
    pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*=\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*;', re.MULTILINE)
    result = []
    for m in pattern.finditer(content):
        key = m.group(1).encode().decode("unicode_escape") if "\\" in m.group(1) else m.group(1)
        val = m.group(2).encode().decode("unicode_escape") if "\\" in m.group(2) else m.group(2)
        result.append((m.group(1), m.group(2), m.group(0)))  # 原始 key, 原始 value, 原始整行
    return result


def escape_string(s: str) -> str:
    """转义字符串用于 .strings 格式"""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


def obfuscate_key(original: str, mapping: dict[str, str]) -> str:
    """生成或复用混淆后的键"""
    if original in mapping:
        return mapping[original]
    obf = "o" + secrets.token_hex(4)
    mapping[original] = obf
    return obf


def obfuscate_strings_file(
    input_path: str,
    output_path: str | None = None,
    mapping_path: str | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, str]:
    """
    混淆 .strings 文件键名。
    返回 original_key -> obfuscated_key 映射。
    """
    input_path = Path(input_path)
    output_path = Path(output_path or input_path)
    mapping: dict[str, str] = {}

    entries = parse_strings_file(input_path)
    if not entries:
        return {}

    content = input_path.read_text(encoding="utf-8", errors="replace")

    for orig_key, orig_val, raw in entries:
        obf_key = obfuscate_key(orig_key, mapping)
        # 只替换作为键出现的 "key" = ，避免误替换注释中的相同文本
        escaped = re.escape(f'"{orig_key}"')
        content = re.sub(escaped + r'\s*=', f'"{obf_key}" =', content, count=1)

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

        if mapping_path:
            Path(mapping_path).parent.mkdir(parents=True, exist_ok=True)
            with open(mapping_path, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)

    return mapping


def main():
    parser = argparse.ArgumentParser(
        description="混淆 Localizable.strings 键名，降低 IPA 相似度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="输入的 .strings 文件路径")
    parser.add_argument("-o", "--output", help="输出路径（默认覆盖输入）")
    parser.add_argument("-m", "--mapping", help="键映射 JSON 输出路径（供运行时还原）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印映射，不写入")

    args = parser.parse_args()

    try:
        mapping = obfuscate_strings_file(
            args.input,
            output_path=args.output,
            mapping_path=args.mapping,
            dry_run=args.dry_run,
        )
        if mapping:
            print(f"混淆了 {len(mapping)} 个键")
            for orig, obf in list(mapping.items())[:10]:
                print(f"  {orig!r} -> {obf!r}")
            if len(mapping) > 10:
                print("  ...")
            if args.mapping and not args.dry_run:
                print(f"映射已写入: {args.mapping}")
        else:
            print("未找到可混淆的键")
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

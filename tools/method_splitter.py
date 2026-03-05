#!/usr/bin/env python3
"""
方法拆分工具
将 Swift/ObjC 中的长方法拆分为 2-5 个较小方法，改变二进制结构以降低 IPA 相似度。
"""

import argparse
import re
import secrets
import sys
from pathlib import Path


def find_matching_brace(text: str, start: int, open_c: str = "{", close_c: str = "}") -> int:
    """从 start 位置找到匹配的闭合括号，返回闭合括号位置"""
    depth = 0
    i = start
    while i < len(text):
        if text[i] == open_c:
            depth += 1
        elif text[i] == close_c:
            depth -= 1
            if depth == 0:
                return i
        elif text[i] in '"\'':
            quote = text[i]
            i += 1
            while i < len(text) and (text[i] != quote or text[i - 1] == "\\"):
                i += 1
        i += 1
    return -1


def extract_swift_methods(content: str) -> list[tuple[str, int, int, str, str]]:
    """
    提取 Swift 方法，返回 [(name, start, end, signature, body), ...]
    """
    results = []
    # 匹配 func 或 static func 或 private func 等
    pattern = re.compile(
        r"((?:static\s+|final\s+|override\s+|private\s+|fileprivate\s+|internal\s+|public\s+)*func\s+(\w+)\s*\([^)]*\)(?:\s*->\s*[^{]+)?)\s*\{",
        re.MULTILINE,
    )
    for m in pattern.finditer(content):
        sig_end = m.end()
        brace_start = sig_end - 1  # 即 { 的位置
        brace_end = find_matching_brace(content, brace_start)
        if brace_end < 0:
            continue
        body = content[brace_start + 1 : brace_end].strip()
        # 跳过空方法或过短
        if len(body) < 20:
            continue
        results.append((m.group(2), m.start(), brace_end + 1, m.group(1), body))
    return results


def _extract_declared_vars(block: str) -> set[str]:
    """提取块内声明的局部变量名（let/var）"""
    vars_set = set()
    for m in re.finditer(r"\b(?:let|var)\s+(\w+)", block):
        vars_set.add(m.group(1))
    return vars_set


def _extract_used_identifiers(block: str) -> set[str]:
    """提取块内使用的标识符（排除关键字、self、数字等）"""
    keywords = {"self", "super", "true", "false", "nil", "return", "if", "else", "for", "while", "switch", "case", "default", "guard", "let", "var", "func", "in", "as", "try", "catch", "throw"}
    ids = set()
    for m in re.finditer(r"\b([a-zA-Z_]\w*)\b", block):
        if m.group(1) not in keywords and not m.group(1)[0].isdigit():
            ids.add(m.group(1))
    return ids


def split_body_into_blocks(body: str, num_parts: int) -> list[str]:
    """
    将方法体按逻辑块拆分为 num_parts 部分。
    优先按空行分隔的段落拆分；若后块依赖前块变量，则合并避免作用域错误。
    """
    paragraphs = re.split(r"\n\s*\n", body)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    # 合并有依赖的段落
    merged = [paragraphs[0]]
    declared_so_far = _extract_declared_vars(paragraphs[0])

    for para in paragraphs[1:]:
        used = _extract_used_identifiers(para)
        if used & declared_so_far:
            # 当前段使用前面声明的变量，合并到上一块
            merged[-1] = merged[-1] + "\n\n" + para
        else:
            merged.append(para)
        declared_so_far |= _extract_declared_vars(para)

    if len(merged) >= num_parts:
        return merged[:num_parts]

    # 合并后仅 1 块说明存在跨块变量依赖，不再按行拆分（避免作用域错误）
    return merged


def generate_helper_name() -> str:
    return f"_obf_{secrets.token_hex(3)}"


def split_swift_method(
    signature: str,
    body: str,
    num_parts: int,
) -> tuple[str, list[tuple[str, str]]]:
    """
    将方法体拆分为 num_parts 个 helper，返回 (新主方法体, [(helper_name, helper_body), ...])
    """
    blocks = split_body_into_blocks(body, num_parts)
    if len(blocks) < 2:
        return body, []

    helpers = []
    calls = []
    for block in blocks:
        name = generate_helper_name()
        helpers.append((name, block))
        calls.append(f"        {name}()")

    new_body = "\n".join(calls)
    return new_body, helpers


def process_swift_file(
    content: str,
    min_lines: int = 15,
    num_parts: tuple[int, int] = (2, 5),
) -> tuple[str, int]:
    """
    处理 Swift 文件，拆分长方法。
    返回 (新内容, 拆分的方法数)
    """
    methods = extract_swift_methods(content)
    if not methods:
        return content, 0

    # 从后往前替换，避免偏移错乱
    methods.sort(key=lambda x: x[1], reverse=True)

    result = content
    count = 0
    for name, start, end, signature, body in methods:
        line_count = len([l for l in body.splitlines() if l.strip()])
        if line_count < min_lines:
            continue

        n = min(num_parts[1], max(num_parts[0], min(5, line_count // 4)))
        new_body, helpers = split_swift_method(signature, body, n)
        if not helpers:
            continue

        # 构建替换内容：原方法改为调用 helpers + 插入 helper 方法
        indent = "    "
        helper_methods = []
        for hname, hbody in helpers:
            helper_methods.append(
                f"{indent}private func {hname}() {{\n{indent}    "
                + hbody.replace("\n", f"\n{indent}    ")
                + f"\n{indent}}}"
            )

        new_method = (
            f"{signature} {{\n{indent}"
            + new_body.replace("\n", f"\n{indent}")
            + f"\n{indent}}}\n\n"
            + "\n\n".join(helper_methods)
        )

        result = result[:start] + new_method + result[end:]
        count += 1

    return result, count


def main():
    parser = argparse.ArgumentParser(
        description="将 Swift 长方法拆分为 2-5 个小方法，降低 IPA 相似度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="Swift 源文件路径")
    parser.add_argument("-o", "--output", help="输出路径（默认覆盖输入）")
    parser.add_argument(
        "--min-lines",
        type=int,
        default=15,
        help="仅拆分超过此行数的方法（默认 15）",
    )
    parser.add_argument(
        "--parts",
        default="2-5",
        help="拆分数量范围，如 2-5（默认 2-5）",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅打印将拆分的方法，不写入")

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        lo, hi = 2, 5
        if "-" in args.parts:
            a, b = args.parts.split("-", 1)
            lo, hi = int(a.strip()), int(b.strip())
        else:
            lo = hi = int(args.parts)

        content = input_path.read_text(encoding="utf-8", errors="replace")
        new_content, count = process_swift_file(content, args.min_lines, (lo, hi))

        if count > 0:
            if args.dry_run:
                print(f"将拆分 {count} 个方法（dry-run，未写入）")
            else:
                out_path = Path(args.output or input_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(new_content, encoding="utf-8")
                print(f"已拆分 {count} 个方法，写入: {out_path}")
        else:
            print("未找到可拆分的方法")
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

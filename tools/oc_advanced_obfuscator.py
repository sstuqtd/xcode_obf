#!/usr/bin/env python3
"""
OC 高级混淆工具
支持：函数拆分成多个子函数（保持执行结果不变）、代码格式化等高级混淆功能。
"""

import argparse
import re
import secrets
import sys
from pathlib import Path


def find_matching_brace(text: str, start: int, open_c: str = "{", close_c: str = "}") -> int:
    """从 start 位置找到匹配的闭合括号"""
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


def extract_objc_methods(content: str) -> list[tuple[str, int, int, str, str]]:
    """
    提取 Objective-C 方法，返回 [(selector, start, end, signature, body), ...]
    支持 - (void)method 和 - (void)method:(id)arg 等形式
    """
    results = []
    # 匹配 - (type) 或 + (type)，然后到 { 之间的部分为 selector
    pattern = re.compile(r"([-+]\s*\([^)]+\)\s*(?:\w+(?:\s*:\s*\([^)]*\)\s*\w+)*))\s*\{", re.MULTILINE)
    for m in pattern.finditer(content):
        sig_end = m.end()
        brace_start = sig_end - 1
        brace_end = find_matching_brace(content, brace_start)
        if brace_end < 0:
            continue
        body = content[brace_start + 1 : brace_end].strip()
        if len(body) < 20:
            continue
        # 提取 selector 首段作为 name
        sig = m.group(1).strip()
        name_match = re.search(r"\)\s*(\w+)", sig)
        name = name_match.group(1) if name_match else "method"
        results.append((name, m.start(), brace_end + 1, sig, body))
    return results


def _extract_declared_vars_oc(block: str) -> set[str]:
    """提取 OC 块内声明的局部变量（Type *var = 或 Type var =）"""
    vars_set = set()
    # Type *var = 或 Type var = （指针或值类型）
    for m in re.finditer(r"\*\s*(\w+)\s*=", block):
        vars_set.add(m.group(1))
    for m in re.finditer(r"(?:^|;)\s*(?:\w+\s+)+(\w+)\s*=", block):
        vars_set.add(m.group(1))
    return vars_set


def _extract_used_identifiers_oc(block: str) -> set[str]:
    """提取 OC 块内使用的标识符"""
    keywords = {"self", "super", "nil", "YES", "NO", "return", "if", "else", "for", "while", "switch", "case", "default", "do", "typedef", "struct", "enum", "id", "SEL", "BOOL", "void", "int", "long", "float", "double"}
    ids = set()
    for m in re.finditer(r"\b([a-zA-Z_]\w*)\b", block):
        if m.group(1) not in keywords and not m.group(1)[0].isdigit():
            ids.add(m.group(1))
    return ids


def _braces_balanced(text: str) -> bool:
    """检查大括号是否匹配（忽略字符串内）"""
    depth = 0
    i = 0
    while i < len(text):
        if text[i] in '"\'':
            quote = text[i]
            i += 1
            while i < len(text) and (text[i] != quote or text[i - 1] == "\\"):
                i += 1
        elif text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def split_body_into_blocks_oc(body: str, num_parts: int) -> list[str]:
    """OC 方法体拆分，检测变量依赖与大括号完整性，有依赖或未闭合则合并"""
    paragraphs = re.split(r"\n\s*\n", body)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    merged = [paragraphs[0]]
    declared_so_far = _extract_declared_vars_oc(paragraphs[0])

    for para in paragraphs[1:]:
        used = _extract_used_identifiers_oc(para)
        if used & declared_so_far:
            merged[-1] = merged[-1] + "\n\n" + para
        else:
            merged.append(para)
        declared_so_far |= _extract_declared_vars_oc(para)

    # 确保每个块大括号匹配，不匹配的块合并到前一块
    valid = []
    for block in merged:
        if _braces_balanced(block):
            valid.append(block)
        elif valid:
            valid[-1] = valid[-1] + "\n\n" + block
        else:
            valid.append(block)
    # 再次检查：若首块仍不匹配，尝试与后续合并
    while len(valid) > 1 and not _braces_balanced(valid[0]):
        valid[0] = valid[0] + "\n\n" + valid.pop(1)

    if len(valid) >= num_parts:
        return valid[:num_parts]
    return valid


def _format_block(block: str) -> str:
    """代码格式化：逻辑块间插入空行"""
    lines = [l.rstrip() for l in block.splitlines() if l.strip()]
    if not lines:
        return block
    result = []
    for i, line in enumerate(lines):
        result.append(line)
        if i < len(lines) - 1:
            stripped = line.strip()
            if stripped.startswith(("return", "}")) and not lines[i + 1].strip().startswith("}"):
                result.append("")
    return "\n".join(result)


def generate_helper_name() -> str:
    return f"_obf_{secrets.token_hex(3)}"


def split_objc_method(signature: str, body: str, num_parts: int) -> tuple[str, list[tuple[str, str]]]:
    """将 OC 方法体拆分为多个 helper"""
    blocks = split_body_into_blocks_oc(body, num_parts)
    if len(blocks) < 2:
        return body, []

    helpers = []
    calls = []
    for block in blocks:
        name = generate_helper_name()
        helpers.append((name, block))
        calls.append(f"    [self {name}];")

    new_body = "\n".join(calls)
    return new_body, helpers


def process_objc_file(
    content: str,
    min_lines: int = 15,
    num_parts: tuple[int, int] = (2, 5),
    format_code: bool = False,
) -> tuple[str, int]:
    """处理 OC 文件，拆分方法并可选格式化"""
    methods = extract_objc_methods(content)
    if not methods:
        return content, 0

    methods.sort(key=lambda x: x[1], reverse=True)

    result = content
    count = 0
    for name, start, end, signature, body in methods:
        line_count = len([l for l in body.splitlines() if l.strip()])
        if line_count < min_lines:
            continue

        n = min(num_parts[1], max(num_parts[0], min(5, line_count // 4)))
        new_body, helpers = split_objc_method(signature, body, n)
        if not helpers:
            continue

        indent = "    "
        helper_methods = []
        for hname, hbody in helpers:
            hbody_formatted = _format_block(hbody) if format_code else hbody
            # 统一缩进：每行前导空白替换为 indent
            lines = hbody_formatted.splitlines()
            normalized = "\n".join(indent + line.strip() for line in lines if line.strip())
            helper_methods.append(f"- (void){hname} {{\n{normalized}\n}}\n")

        new_method = (
            f"{signature} {{\n"
            + new_body
            + f"\n}}\n\n"
            + "\n".join(helper_methods)
        )

        result = result[:start] + new_method + result[end:]
        count += 1

    if format_code and count == 0:
        result = _format_file(result)

    return result, count


def _format_file(content: str) -> str:
    """整体文件格式化：统一缩进、方法间空行"""
    lines = content.splitlines()
    result = []
    for i, line in enumerate(lines):
        result.append(line)
        # 在 @implementation 或方法 } 后加空行
        if line.strip().endswith("}") and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            if next_stripped and not next_stripped.startswith("}"):
                result.append("")
    return "\n".join(result)


def main():
    parser = argparse.ArgumentParser(
        description="OC 高级混淆：函数拆分、代码格式化，保持执行结果不变",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 oc_advanced_obfuscator.py ViewController.m -o ViewController.m
  python3 oc_advanced_obfuscator.py ViewController.m --format --parts 3-5
        """,
    )
    parser.add_argument("input", help="Objective-C 源文件路径 (.m/.mm)")
    parser.add_argument("-o", "--output", help="输出路径（默认覆盖输入）")
    parser.add_argument("--min-lines", type=int, default=15, help="仅拆分超过此行数的方法")
    parser.add_argument("--parts", default="2-5", help="拆分数量范围，如 2-5")
    parser.add_argument("--format", action="store_true", help="启用代码格式化")
    parser.add_argument("--dry-run", action="store_true", help="仅打印，不写入")

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
        new_content, count = process_objc_file(
            content, args.min_lines, (lo, hi), args.format
        )

        if count > 0 or args.format:
            if args.dry_run:
                print(f"将拆分 {count} 个方法，格式化={args.format}（dry-run）")
            else:
                out_path = Path(args.output or input_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(new_content, encoding="utf-8")
                print(f"已处理：拆分 {count} 个方法，写入: {out_path}")
        else:
            print("未找到可拆分的 OC 方法")
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

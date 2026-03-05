#!/usr/bin/env python3
"""
基于 Clang AST 的 OC 方法拆分工具
使用 libclang 解析 AST，在语句边界安全拆分，避免破坏控制流和括号匹配。

依赖: pip install libclang
Mac: 若找不到 libclang，可设置 LIBCLANG_LIBRARY_PATH 指向 Xcode 的 libclang.dylib
"""

import argparse
import re
import secrets
import sys
from pathlib import Path


def _ensure_libclang():
    """确保 libclang 可用，Mac 上尝试 Xcode 路径"""
    try:
        import clang.cindex
        return clang.cindex
    except (ImportError, OSError):
        pass
    # Mac: 尝试 Xcode 自带的 libclang
    xcode_paths = [
        "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/libclang.dylib",
        "/Library/Developer/CommandLineTools/usr/lib/libclang.dylib",
    ]
    import os
    for p in xcode_paths:
        if Path(p).exists():
            os.environ.setdefault("LIBCLANG_LIBRARY_PATH", p)
            break
    try:
        import clang.cindex
        return clang.cindex
    except (ImportError, OSError) as e:
        print("错误: 需要 libclang。请执行: pip install libclang", file=sys.stderr)
        print("Mac 可设置: export LIBCLANG_LIBRARY_PATH=/path/to/libclang.dylib", file=sys.stderr)
        raise SystemExit(1) from e


def parse_and_split(
    file_path: str,
    min_statements: int = 5,
    num_parts: tuple[int, int] = (2, 4),
) -> tuple[str, int]:
    """
    使用 Clang AST 解析并拆分 OC 方法。
    返回 (新内容, 拆分的方法数)
    """
    cindex = _ensure_libclang()
    path = Path(file_path)
    content = path.read_text(encoding="utf-8", errors="replace")

    index = cindex.Index.create()
    args = ["-x", "objective-c"]
    sdk = "/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"
    if Path(sdk).exists():
        args.extend(["-isysroot", sdk, "-fobjc-arc"])
    try:
        tu = index.parse(str(path), args=args, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
    except Exception:
        tu = index.parse(str(path), args=["-x", "objective-c"])

    if tu.diagnostics:
        for d in tu.diagnostics:
            if d.severity >= 3:  # Error
                print(f"解析警告: {d.spelling}", file=sys.stderr)

    replacements = []  # (start, end, new_text)

    def visit(cursor, depth=0):
        if cursor.kind in (cindex.CursorKind.OBJC_INSTANCE_METHOD_DECL, cindex.CursorKind.OBJC_CLASS_METHOD_DECL):
            try:
                start_off = cursor.extent.start.offset
                end_off = cursor.extent.end.offset
                if start_off >= 0 and end_off > start_off and end_off <= len(content):
                    _process_method(cursor, content, replacements, min_statements, num_parts)
            except (AttributeError, TypeError) as e:
                import os
                if os.environ.get("OC_AST_DEBUG") == "1":
                    print(f"  [debug] skip {getattr(cursor, 'spelling', '?')}: {e}", file=sys.stderr)
        for child in cursor.get_children():
            visit(child, depth + 1)

    visit(tu.cursor)

    if not replacements:
        return content, 0

    # 按 start 倒序应用，避免偏移错乱
    replacements.sort(key=lambda r: r[0], reverse=True)
    result = content
    for start, end, new_text in replacements:
        result = result[:start] + new_text + result[end:]

    return result, len(replacements)


def _process_method(cursor, content, replacements, min_statements, num_parts):
    """处理单个 OC 方法，若可拆分则加入 replacements"""
    import os
    debug = os.environ.get("OC_AST_DEBUG") == "1"
    cindex = _ensure_libclang()

    # 仅处理 (void) 方法
    sig = _get_extent_text(content, cursor.extent)
    if debug and cursor.spelling:
        print(f"  [debug] {cursor.spelling} sig_len={len(sig)} void={('void)' in sig)}", file=sys.stderr)
    if "(void)" not in sig and "( void )" not in sig.replace(" ", ""):
        return
    if "void)" not in sig:
        return

    # 查找方法体 (CompoundStmt)
    body_cursor = None
    for child in cursor.get_children():
        if child.kind == cindex.CursorKind.COMPOUND_STMT:
            body_cursor = child
            break

    if not body_cursor:
        return

    # 获取顶层语句（排除空语句）
    stmts = []
    for child in body_cursor.get_children():
        if child.kind == cindex.CursorKind.NULL_STMT:
            continue
        try:
            if child.extent.start.offset >= 0:
                stmts.append(child)
        except (AttributeError, TypeError):
            pass

    if debug:
        print(f"  [debug] {cursor.spelling} stmts={len(stmts)} min={min_statements}", file=sys.stderr)
    if len(stmts) < min_statements:
        return

    n = min(num_parts[1], max(num_parts[0], min(4, len(stmts) // 2)))
    chunk_size = (len(stmts) + n - 1) // n
    if chunk_size < 2:
        return

    # 按语句分组
    groups = []
    for i in range(0, len(stmts), chunk_size):
        group = stmts[i : i + chunk_size]
        if len(group) >= 1:
            groups.append(group)

    if len(groups) < 2:
        return

    # 生成 helper 方法（按语句边界精确提取）
    helper_names = [f"_obf_{secrets.token_hex(3)}" for _ in groups]
    calls = "\n".join(f"    [self {name}];" for name in helper_names)

    # 原方法体替换为调用
    body_start = body_cursor.extent.start.offset
    body_end = body_cursor.extent.end.offset
    new_body = " {\n" + calls + "\n}"
    new_method = content[cursor.extent.start.offset:body_start] + new_body + content[body_end:cursor.extent.end.offset]

    # 生成 helper 方法，确保语句以 ; 结尾（extent 可能不包含分号）
    helpers = []
    for name, group in zip(helper_names, groups):
        first = group[0]
        last = group[-1]
        stmt_start = first.extent.start.offset
        stmt_end = last.extent.end.offset
        helper_body = content[stmt_start:stmt_end]
        # extent 可能不包含语句末尾的 ;，向后查找补全
        while stmt_end < len(content) and content[stmt_end] in " \t\n":
            stmt_end += 1
        if stmt_end < len(content) and content[stmt_end] == ";":
            stmt_end += 1
            helper_body = content[stmt_start:stmt_end]
        helpers.append(f"- (void){name} {{\n{helper_body}\n}}")

    full_replacement = new_method + "\n\n" + "\n\n".join(helpers)
    try:
        start_off = cursor.extent.start.offset
        end_off = cursor.extent.end.offset
        if 0 <= start_off < end_off <= len(content):
            replacements.append((start_off, end_off, full_replacement))
    except (AttributeError, TypeError):
        pass


def _get_extent_text(content: str, extent) -> str:
    """从 extent 获取文本（libclang extent 可能用不同编码）"""
    try:
        return content[extent.start.offset:extent.end.offset]
    except (TypeError, AttributeError):
        return ""


def main():
    parser = argparse.ArgumentParser(
        description="基于 Clang AST 的 OC 方法拆分（语句边界安全）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="OC 源文件路径")
    parser.add_argument("-o", "--output", help="输出路径（默认覆盖）")
    parser.add_argument("--min-stmts", type=int, default=5, help="最少语句数才拆分")
    parser.add_argument("--parts", default="2-4", help="拆分数量范围")
    parser.add_argument("--dry-run", action="store_true", help="仅预览")
    parser.add_argument("--debug", action="store_true", help="调试输出")

    args = parser.parse_args()
    if args.debug:
        import os
        os.environ["OC_AST_DEBUG"] = "1"
    path = Path(args.input)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(1)

    lo, hi = 2, 4
    if "-" in args.parts:
        a, b = args.parts.split("-", 1)
        lo, hi = int(a.strip()), int(b.strip())
    else:
        lo = hi = int(args.parts)

    try:
        new_content, count = parse_and_split(
            str(path), args.min_stmts, (lo, hi)
        )
        if count > 0:
            if args.dry_run:
                print(f"将拆分 {count} 个方法（dry-run）")
            else:
                out = Path(args.output or path)
                out.write_text(new_content, encoding="utf-8")
                print(f"已拆分 {count} 个方法: {out}")
        else:
            print("未找到可拆分的方法")
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
基于 Clang AST 的 OC/C/C++ 方法/函数拆分工具
使用 libclang 解析 AST，在语句边界安全拆分，避免破坏控制流和括号匹配。

支持: .m/.mm (Objective-C), .c (C), .cpp/.cc/.cxx (C++)
依赖: pip install libclang
Mac: 若找不到 libclang，可设置 LIBCLANG_LIBRARY_PATH 指向 Xcode 的 libclang.dylib
"""

import argparse
import re
import secrets
import sys
from pathlib import Path

# 支持的文件扩展与语言
C_LANG_EXTS = {".c": "c", ".cpp": "c++", ".cc": "c++", ".cxx": "c++"}
OC_LANG_EXTS = {".m": "objective-c", ".mm": "objective-c++"}


def _lang_from_path(path: Path) -> str:
    """根据扩展返回语言: objective-c, objective-c++, c, c++"""
    ext = path.suffix.lower()
    if ext in OC_LANG_EXTS:
        return OC_LANG_EXTS[ext]
    if ext in C_LANG_EXTS:
        return C_LANG_EXTS[ext]
    return "objective-c"  # 默认


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
    使用 Clang AST 解析并拆分 OC 方法 / C/C++ 函数。
    返回 (新内容, 拆分的数量)
    """
    cindex = _ensure_libclang()
    path = Path(file_path)
    content = path.read_text(encoding="utf-8", errors="replace")
    lang = _lang_from_path(path)

    index = cindex.Index.create()
    args = ["-x", lang]
    sdk = "/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"
    if Path(sdk).exists():
        args.extend(["-isysroot", sdk])
        if "objective-c" in lang:
            args.append("-fobjc-arc")
    if "c++" in lang:
        args.extend(["-std=c++11"])
    try:
        tu = index.parse(str(path), args=args, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
    except Exception:
        tu = index.parse(str(path), args=["-x", lang])

    if tu.diagnostics:
        for d in tu.diagnostics:
            if d.severity >= 3:  # Error
                print(f"解析警告: {d.spelling}", file=sys.stderr)

    replacements = []  # (start, end, new_text)  start/end 为字节偏移
    content_bytes = content.encode("utf-8")
    is_oc = "objective-c" in lang

    def visit(cursor, depth=0):
        if is_oc and cursor.kind in (
            cindex.CursorKind.OBJC_INSTANCE_METHOD_DECL,
            cindex.CursorKind.OBJC_CLASS_METHOD_DECL,
        ):
            try:
                start_off = cursor.extent.start.offset
                end_off = cursor.extent.end.offset
                if start_off >= 0 and end_off > start_off and end_off <= _content_byte_len(content):
                    _process_oc_method(cursor, content, content_bytes, replacements, min_statements, num_parts)
            except (AttributeError, TypeError) as e:
                import os
                if os.environ.get("OC_AST_DEBUG") == "1":
                    print(f"  [debug] skip {getattr(cursor, 'spelling', '?')}: {e}", file=sys.stderr)
        elif not is_oc and cursor.kind in (
            cindex.CursorKind.FUNCTION_DECL,
            cindex.CursorKind.CXX_METHOD,
        ):
            try:
                start_off = cursor.extent.start.offset
                end_off = cursor.extent.end.offset
                if start_off >= 0 and end_off > start_off and end_off <= _content_byte_len(content):
                    _process_c_function(cursor, content, content_bytes, replacements, min_statements, num_parts, lang)
                elif start_off >= 0 and end_off > start_off:
                    import os
                    if os.environ.get("OC_AST_DEBUG") == "1":
                        print(f"  [debug] skip {cursor.spelling}: end_off={end_off} > len={_content_byte_len(content)}", file=sys.stderr)
            except (AttributeError, TypeError) as e:
                import os
                if os.environ.get("OC_AST_DEBUG") == "1":
                    print(f"  [debug] skip {getattr(cursor, 'spelling', '?')}: {e}", file=sys.stderr)
        for child in cursor.get_children():
            visit(child, depth + 1)

    visit(tu.cursor)

    if not replacements:
        return content, 0

    # 按 start 倒序应用，避免偏移错乱（start/end 为字节偏移）
    replacements.sort(key=lambda r: r[0], reverse=True)
    result = content_bytes
    for start, end, new_text in replacements:
        result = result[:start] + new_text.encode("utf-8") + result[end:]

    return result.decode("utf-8", errors="replace"), len(replacements)


def _process_oc_method(cursor, content, content_bytes, replacements, min_statements, num_parts):
    """处理单个 OC 方法，若可拆分则加入 replacements"""
    import os
    debug = os.environ.get("OC_AST_DEBUG") == "1"
    cindex = _ensure_libclang()

    # 仅处理 (void) 且无参数的方法（带参数的方法拆分后辅助方法无法访问 task/response 等）
    name = cursor.spelling or ""
    if ":" in name:
        return
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

    # 获取顶层语句（排除空语句），按源码顺序排序
    stmts = []
    for child in body_cursor.get_children():
        if child.kind == cindex.CursorKind.NULL_STMT:
            continue
        try:
            if child.extent.start.offset >= 0:
                stmts.append(child)
        except (AttributeError, TypeError):
            pass
    stmts.sort(key=lambda s: s.extent.start.offset)

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
    new_method = (
        _slice_bytes(content, cursor.extent.start.offset, body_start)
        + new_body
        + _slice_bytes(content, body_end, cursor.extent.end.offset)
    )

    # 生成 helper 方法，确保语句以 ; 结尾（extent 可能不包含分号）
    helpers = []
    for name, group in zip(helper_names, groups):
        first = group[0]
        last = group[-1]
        stmt_start = first.extent.start.offset
        stmt_end = _find_stmt_end(content_bytes, last.extent.start.offset)
        helper_body = _slice_bytes(content, stmt_start, stmt_end)
        helpers.append(f"- (void){name} {{\n{helper_body}\n}}")

    full_replacement = new_method + "\n\n" + "\n\n".join(helpers)
    try:
        start_off = cursor.extent.start.offset
        end_off = cursor.extent.end.offset
        if 0 <= start_off < end_off <= len(content_bytes):
            replacements.append((start_off, end_off, full_replacement))
    except (AttributeError, TypeError):
        pass


def _process_c_function(cursor, content, content_bytes, replacements, min_statements, num_parts, lang: str):
    """处理 C/C++ 函数，若可拆分则加入 replacements"""
    import os
    debug = os.environ.get("OC_AST_DEBUG") == "1"
    cindex = _ensure_libclang()

    # 仅处理 void 返回
    try:
        result_type = cursor.type.get_result().spelling
        if "void" not in result_type:
            return
    except (AttributeError, TypeError):
        return

    # 跳过 main
    name = cursor.spelling or ""
    if name == "main":
        return

    # 跳过无定义（仅声明）
    body_cursor = None
    for child in cursor.get_children():
        if child.kind == cindex.CursorKind.COMPOUND_STMT:
            body_cursor = child
            break
    if not body_cursor:
        return

    # 获取顶层语句，按源码顺序排序，过滤超出函数体的节点
    body_end = body_cursor.extent.end.offset
    stmts = []
    for child in body_cursor.get_children():
        if child.kind == cindex.CursorKind.NULL_STMT:
            continue
        try:
            so = child.extent.start.offset
            eo = child.extent.end.offset
            if so >= 0 and eo <= body_end:
                stmts.append(child)
        except (AttributeError, TypeError):
            pass
    stmts.sort(key=lambda s: s.extent.start.offset)

    if debug:
        print(f"  [debug] {name} stmts={len(stmts)} min={min_statements}", file=sys.stderr)
    if len(stmts) < min_statements:
        return

    n = min(num_parts[1], max(num_parts[0], min(4, len(stmts) // 2)))
    chunk_size = (len(stmts) + n - 1) // n
    if chunk_size < 2:
        return

    groups = []
    for i in range(0, len(stmts), chunk_size):
        group = stmts[i : i + chunk_size]
        if len(group) >= 1:
            groups.append(group)

    if len(groups) < 2:
        return

    helper_names = [f"_obf_{secrets.token_hex(3)}" for _ in groups]
    is_cxx_method = cursor.kind == cindex.CursorKind.CXX_METHOD

    if is_cxx_method:
        # C++ 成员函数：用 lambda 包装，避免修改头文件
        calls = "\n".join(f"    {name}();" for name in helper_names)
        lambdas = []
        for name, group in zip(helper_names, groups):
            first, last = group[0], group[-1]
            stmt_start = first.extent.start.offset
            stmt_end = _find_stmt_end(content_bytes, last.extent.start.offset)
            helper_body = _slice_bytes(content, stmt_start, stmt_end)
            lambdas.append(f"    auto {name} = [this]() {{\n{helper_body}\n    }};")
        new_body = " {\n" + "\n".join(lambdas) + "\n" + calls + "\n}"
    else:
        # C / C++ 自由函数：static void _obf_xxx(void) { ... }
        calls = "\n".join(f"    {name}();" for name in helper_names)
        new_body = " {\n" + calls + "\n}"

        # 生成 static 辅助函数
        helpers = []
        for name, group in zip(helper_names, groups):
            first, last = group[0], group[-1]
            stmt_start = first.extent.start.offset
            stmt_end = _find_stmt_end(content_bytes, last.extent.start.offset)
            helper_body = _slice_bytes(content, stmt_start, stmt_end)
            helpers.append(f"static void {name}(void) {{\n{helper_body}\n}}")

    body_start = body_cursor.extent.start.offset
    body_end_off = body_cursor.extent.end.offset
    new_func = (
        _slice_bytes(content, cursor.extent.start.offset, body_start)
        + new_body
        + _slice_bytes(content, body_end_off, cursor.extent.end.offset)
    )

    if is_cxx_method:
        full_replacement = new_func
    else:
        full_replacement = new_func + "\n\n" + "\n\n".join(helpers)

    try:
        start_off = cursor.extent.start.offset
        end_off = cursor.extent.end.offset
        if 0 <= start_off < end_off <= len(content_bytes):
            replacements.append((start_off, end_off, full_replacement))
    except (AttributeError, TypeError):
        pass


def _get_extent_text(content: str, extent) -> str:
    """从 extent 获取文本（libclang extent 使用字节偏移）"""
    try:
        return _slice_bytes(content, extent.start.offset, extent.end.offset)
    except (TypeError, AttributeError):
        return ""


def _slice_bytes(content: str, start: int, end: int) -> str:
    """按字节偏移切片（libclang 使用 UTF-8 字节偏移）"""
    b = content.encode("utf-8")
    return b[start:end].decode("utf-8", errors="replace")


def _content_byte_len(content: str) -> int:
    """内容字节长度（用于与 libclang 偏移比较）"""
    return len(content.encode("utf-8"))


def _find_stmt_end(content_bytes: bytes, stmt_start: int) -> int:
    """从语句起始位置向后查找分号，返回分号后一字节（避免 extent 跨语句）"""
    pos = stmt_start
    while pos < len(content_bytes):
        if content_bytes[pos : pos + 1] == b";":
            return pos + 1
        pos += 1
    return stmt_start


def main():
    parser = argparse.ArgumentParser(
        description="基于 Clang AST 的 OC/C/C++ 方法/函数拆分（语句边界安全）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="源文件路径 (.m/.mm/.c/.cpp/.cc/.cxx)")
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
                print(f"将拆分 {count} 个方法/函数（dry-run）")
            else:
                out = Path(args.output or path)
                out.write_text(new_content, encoding="utf-8")
                print(f"已拆分 {count} 个方法/函数: {out}")
        else:
            print("未找到可拆分的方法/函数")
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

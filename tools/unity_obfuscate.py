#!/usr/bin/env python3
"""
Unity 导出 Xcode 工程自动混淆
针对 Unity 2020.3+ 导出的 Xcode 工程，自动执行：
- Plist 混淆、Localizable.strings 混淆
- OC 方法拆分（Clang AST，对整个工程）
- 字符串自动加密/解密
- Data/Raw 文件加密/解密

使用时机：Unity 导出 Xcode 工程后、Xcode 构建前执行。默认直接修改原工程文件。
"""

import argparse
import subprocess
import sys
from pathlib import Path

# 脚本所在目录
TOOLS_DIR = Path(__file__).resolve().parent


def find_unity_xcode_project(root: Path) -> Path:
    """查找 Unity 导出的 Xcode 工程根目录（含 .xcodeproj）"""
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"路径不存在: {root}")

    # 当前目录或子目录中的 .xcodeproj
    xcodeproj = list(root.rglob("*.xcodeproj"))
    if not xcodeproj:
        raise FileNotFoundError(f"未找到 .xcodeproj: {root}")

    # 取第一个，通常为 Unity-iPhone.xcodeproj
    return xcodeproj[0].parent


def _run_string_encrypt(project_root: Path, dry_run: bool) -> int:
    """字符串加密，返回处理文件数"""
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "string_encrypt.py"),
                str(project_root),
                "--decoder-output", str(project_root / "ObfuscatedStrings"),
            ] + (["--dry-run"] if dry_run else []),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            out = result.stdout or ""
            if dry_run and "将加密" in out:
                return 1  # 有可加密内容
            return out.count("已写入")
    except Exception:
        pass
    return 0


def _run_data_encrypt(project_root: Path, dry_run: bool) -> int:
    """Data/Raw 加密，返回文件数（dry_run 时跳过，避免误加密）"""
    if dry_run:
        return 0
    data_dir = project_root / "Data" / "Raw"
    if not data_dir.exists():
        data_dir = project_root / "Data"
    if not data_dir.exists():
        return 0
    key_out = project_root / "Data" / ".encrypt_key"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "data_encrypt.py"),
                "encrypt",
                str(data_dir),
                "--key-out", str(key_out),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            out = result.stdout or ""
            count = 0
            for line in out.splitlines():
                if "加密完成" in line:
                    try:
                        count = int(line.split(":")[1].strip().split()[0])
                        break
                    except (IndexError, ValueError):
                        count = 1
            if count > 0:
                key_hex_path = Path(str(key_out) + ".hex")
                if key_hex_path.exists():
                    key_hex = key_hex_path.read_text().strip()
                    subprocess.run(
                        [
                            sys.executable,
                            str(TOOLS_DIR / "data_encrypt.py"),
                            "gen-loader", "--key", key_hex,
                            "-o", str(project_root / "DecryptedDataLoader.m"),
                        ],
                        capture_output=True,
                        timeout=10,
                    )
                return count
    except Exception:
        pass
    return 0


def collect_unity_project_files(project_root: Path) -> dict:
    """
    收集 Unity Xcode 工程中需混淆的文件。
    Unity 2020.3 结构：Classes/, MainApp/, UnityFramework/ 等
    """
    files = {
        "plist": [],
        "objc": [],
        "strings": [],
    }

    # Info.plist
    for plist in project_root.rglob("Info.plist"):
        if "Pods" in str(plist) or "DerivedData" in str(plist):
            continue
        files["plist"].append(plist)

    # Objective-C / C / C++：.m, .mm, .c, .cpp, .cc, .cxx（用于 AST 方法/函数拆分）
    for ext in ("*.m", "*.mm", "*.c", "*.cpp", "*.cc", "*.cxx"):
        for f in project_root.rglob(ext):
            if "Pods" in str(f) or "DerivedData" in str(f):
                continue
            if f.stat().st_size < 10 * 1024 * 1024:
                files["objc"].append(f)

    # Localizable.strings
    for f in project_root.rglob("*.strings"):
        if "Pods" in str(f) or "DerivedData" in str(f):
            continue
        if "Localizable" in f.name or f.suffix == ".strings":
            files["strings"].append(f)

    return files


def _run_oc_ast_split(project_root: Path, files: dict, dry_run: bool, min_stmts: int) -> int:
    """对整个 Unity Xcode 工程执行 Clang AST 方法/函数拆分（OC/C/C++）"""
    count = 0
    for oc_path in files.get("objc", []):
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS_DIR / "oc_ast_splitter.py"),
                    str(oc_path),
                    "-o", str(oc_path),
                    "--min-stmts", str(min_stmts),
                ] + (["--dry-run"] if dry_run else []),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and "已拆分" in (result.stdout or ""):
                count += 1
        except Exception:
            pass
    return count


def run_obfuscation(
    project_root: Path,
    *,
    plist: bool = True,
    oc_ast: bool = False,
    strings: bool = False,
    str_encrypt: bool = False,
    data_encrypt: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    min_stmts: int = 5,
) -> tuple[dict[str, int], dict[str, int]]:
    """执行混淆，返回 (counts, totals)"""
    counts = {"plist": 0, "oc_ast": 0, "strings": 0, "str_encrypt": 0, "data_encrypt": 0}
    files = collect_unity_project_files(project_root)

    if verbose:
        print(f"扫描到: Plist={len(files['plist'])}, OC/C/C++={len(files['objc'])}, Strings={len(files['strings'])}")

    # 1. Plist 混淆
    if plist and files["plist"]:
        for plist_path in files["plist"]:
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(TOOLS_DIR / "plist_obfuscator.py"),
                        str(plist_path),
                        "--keys", "CFBundleName,CFBundleExecutable,CFBundleVersion",
                        "--dummy-keys", "2",
                    ] + (["--dry-run"] if dry_run else []),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and "修改内容" in (result.stdout or "") and "->" in (result.stdout or ""):
                    counts["plist"] += 1
            except Exception:
                pass

    # 2. OC 方法拆分（Clang AST，对整个工程，需 pip install libclang）
    if oc_ast and files["objc"]:
        counts["oc_ast"] = _run_oc_ast_split(project_root, files, dry_run, min_stmts)

    # 3. Localizable.strings 混淆（可选，会改变键名需运行时映射）
    if strings and files["strings"]:
        for s_path in files["strings"]:
            try:
                mapping_path = s_path.with_suffix(s_path.suffix + ".mapping.json")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(TOOLS_DIR / "strings_obfuscator.py"),
                        str(s_path),
                        "-o", str(s_path),
                        "-m", str(mapping_path),
                    ] + (["--dry-run"] if dry_run else []),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    counts["strings"] += 1
            except Exception:
                pass

    # 4. 字符串加密
    if str_encrypt:
        counts["str_encrypt"] = _run_string_encrypt(project_root, dry_run)

    # 5. Data/Raw 文件加密
    if data_encrypt:
        counts["data_encrypt"] = _run_data_encrypt(project_root, dry_run)

    totals = {
        "plist": len(files["plist"]),
        "oc_ast": len(files["objc"]),
        "strings": len(files["strings"]),
        "str_encrypt": counts["str_encrypt"],
        "data_encrypt": counts["data_encrypt"],
    }
    return counts, totals


def main():
    parser = argparse.ArgumentParser(
        description="Unity 导出 Xcode 工程自动混淆，降低 IPA 相似度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 unity_obfuscate.py /path/to/Unity-iPhone
  python3 unity_obfuscate.py . --oc-ast
  python3 unity_obfuscate.py . --no-plist
  python3 unity_obfuscate.py . --dry-run
        """,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Unity 导出的 Xcode 工程路径（含 .xcodeproj 的目录）",
    )
    parser.add_argument("--no-plist", action="store_true", help="跳过 Plist 混淆")
    parser.add_argument("--oc-ast", action="store_true", help="启用 OC 方法拆分（Clang AST，需 pip install libclang）")
    parser.add_argument("--min-stmts", type=int, default=5, help="OC AST 拆分最少语句数（默认 5）")
    parser.add_argument("--strings", action="store_true", help="启用 Localizable.strings 混淆")
    parser.add_argument("--str-encrypt", action="store_true", help="启用字符串自动加密")
    parser.add_argument("--data-encrypt", action="store_true", help="启用 Data/Raw 文件加密")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示扫描到的文件列表")

    args = parser.parse_args()

    try:
        project_root = find_unity_xcode_project(Path(args.path))
        print(f"工程路径: {project_root}")

        counts, totals = run_obfuscation(
            project_root,
            plist=not args.no_plist,
            oc_ast=args.oc_ast,
            strings=args.strings,
            str_encrypt=args.str_encrypt,
            data_encrypt=args.data_encrypt,
            dry_run=args.dry_run,
            verbose=args.verbose,
            min_stmts=args.min_stmts,
        )

        parts_out = [f"Plist={counts['plist']}/{totals['plist']}", f"Strings={counts['strings']}/{totals['strings']}"]
        if args.oc_ast:
            parts_out.append(f"OC-AST={counts['oc_ast']}/{totals['oc_ast']}")
        if args.str_encrypt:
            parts_out.append(f"StrEnc={counts['str_encrypt']}")
        if args.data_encrypt:
            parts_out.append(f"DataEnc={counts['data_encrypt']}")
        print(f"处理完成: {', '.join(parts_out)}")
        if args.dry_run:
            print("(dry-run，未写入)")
    except FileNotFoundError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

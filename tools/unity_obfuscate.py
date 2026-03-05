#!/usr/bin/env python3
"""
Unity 导出 Xcode 工程自动混淆
针对 Unity 2020.3+ 导出的 Xcode 工程，自动执行 Plist、OC 方法拆分等混淆，降低 IPA 相似度。

使用时机：Unity 导出 Xcode 工程后、Xcode 构建前执行。
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

    # Info.plist：主工程、MainApp、UnityFramework 等
    for plist in project_root.rglob("Info.plist"):
        # 排除 Pods、DerivedData 等
        if "Pods" in str(plist) or "DerivedData" in str(plist):
            continue
        files["plist"].append(plist)

    # Objective-C：Classes/, MainApp/, UnityFramework/
    for ext in ("*.m", "*.mm"):
        for f in project_root.rglob(ext):
            if "Pods" in str(f) or "DerivedData" in str(f):
                continue
            # 跳过第三方/系统生成的大文件（可选）
            if f.stat().st_size > 2 * 1024 * 1024:  # 跳过 >2MB
                continue
            files["objc"].append(f)

    # Localizable.strings
    for f in project_root.rglob("*.strings"):
        if "Pods" in str(f) or "DerivedData" in str(f):
            continue
        if "Localizable" in f.name or f.suffix == ".strings":
            files["strings"].append(f)

    return files


def run_obfuscation(
    project_root: Path,
    *,
    plist: bool = True,
    objc: bool = True,
    strings: bool = False,
    min_lines: int = 15,
    parts: str = "2-5",
    format_code: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """执行混淆，返回各类型处理数量"""
    counts = {"plist": 0, "objc": 0, "strings": 0}
    files = collect_unity_project_files(project_root)

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

    # 2. OC 方法拆分
    if objc and files["objc"]:
        for oc_path in files["objc"]:
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(TOOLS_DIR / "oc_advanced_obfuscator.py"),
                        str(oc_path),
                        "-o", str(oc_path),
                        "--min-lines", str(min_lines),
                        "--parts", parts,
                    ] + (["--format"] if format_code else []) + (["--dry-run"] if dry_run else []),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                out = result.stdout or ""
                if result.returncode == 0 and ("已处理" in out or "将拆分" in out) and "拆分" in out:
                    counts["objc"] += 1
            except Exception:
                pass

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

    return counts


def main():
    parser = argparse.ArgumentParser(
        description="Unity 导出 Xcode 工程自动混淆，降低 IPA 相似度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 unity_obfuscate.py /path/to/Unity-iPhone
  python3 unity_obfuscate.py . --no-objc
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
    parser.add_argument("--no-objc", action="store_true", help="跳过 OC 方法拆分")
    parser.add_argument("--strings", action="store_true", help="启用 Localizable.strings 混淆")
    parser.add_argument("--min-lines", type=int, default=15, help="OC 方法拆分最小行数")
    parser.add_argument("--parts", default="2-5", help="OC 拆分数量范围")
    parser.add_argument("--format", action="store_true", help="OC 代码格式化")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")

    args = parser.parse_args()

    try:
        project_root = find_unity_xcode_project(Path(args.path))
        print(f"工程路径: {project_root}")

        counts = run_obfuscation(
            project_root,
            plist=not args.no_plist,
            objc=not args.no_objc,
            strings=args.strings,
            min_lines=args.min_lines,
            parts=args.parts,
            format_code=args.format,
            dry_run=args.dry_run,
        )

        print(f"处理完成: Plist={counts['plist']}, OC={counts['objc']}, Strings={counts['strings']}")
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

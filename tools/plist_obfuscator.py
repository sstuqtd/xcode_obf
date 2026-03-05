#!/usr/bin/env python3
"""
Plist 混淆工具
修改 Info.plist 等 plist 文件，注入随机后缀以降低 IPA 相似度。
"""

import argparse
import plistlib
import secrets
import sys
from pathlib import Path


# 可注入随机后缀的键（不改变功能，仅降低相似度）
SAFE_KEYS_FOR_SUFFIX = [
    "CFBundleName",
    "CFBundleExecutable",
    "CFBundleVersion",  # Build 号，每次可不同
]

# 可添加随机键（用于增加差异化，应用不会读取）
DUMMY_KEY_PREFIX = "_obf_"


def add_random_suffix(value: str, length: int = 4) -> str:
    """在值后添加随机十六进制后缀"""
    suffix = secrets.token_hex(length)
    return f"{value}_{suffix}"


def obfuscate_plist(
    plist_path: str,
    *,
    suffix_keys: list[str] | None = None,
    add_dummy_keys: int = 0,
    dry_run: bool = False,
) -> dict[str, str]:
    """
    混淆 plist 文件。
    返回修改的键值对（用于日志）。
    """
    plist_path = Path(plist_path)
    if not plist_path.exists():
        raise FileNotFoundError(f"Plist 不存在: {plist_path}")

    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    if not isinstance(plist, dict):
        raise ValueError("仅支持字典类型的 plist 根节点")

    suffix_keys = suffix_keys or SAFE_KEYS_FOR_SUFFIX
    changes = {}

    for key in suffix_keys:
        if key in plist and isinstance(plist[key], str):
            old_val = plist[key]
            new_val = add_random_suffix(old_val)
            plist[key] = new_val
            changes[key] = f"{old_val} -> {new_val}"

    for i in range(add_dummy_keys):
        dummy_key = f"{DUMMY_KEY_PREFIX}{secrets.token_hex(4)}"
        plist[dummy_key] = secrets.token_hex(8)
        changes[dummy_key] = "(新增)"

    if not dry_run and changes:
        with open(plist_path, "wb") as f:
            plistlib.dump(plist, f)

    return changes


def main():
    parser = argparse.ArgumentParser(
        description="混淆 Plist 文件，降低 IPA 相似度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("plist", help="Plist 文件路径（如 Info.plist）")
    parser.add_argument(
        "--keys",
        default=",".join(SAFE_KEYS_FOR_SUFFIX),
        help="要注入随机后缀的键，逗号分隔",
    )
    parser.add_argument(
        "--dummy-keys",
        type=int,
        default=2,
        help="添加的随机冗余键数量（默认 2）",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅打印修改，不写入文件")

    args = parser.parse_args()

    keys = [k.strip() for k in args.keys.split(",") if k.strip()]

    try:
        changes = obfuscate_plist(
            args.plist,
            suffix_keys=keys,
            add_dummy_keys=args.dummy_keys,
            dry_run=args.dry_run,
        )
        if changes:
            print("修改内容:")
            for k, v in changes.items():
                print(f"  {k}: {v}")
            if args.dry_run:
                print("(dry-run，未写入)")
        else:
            print("无匹配键可修改")
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

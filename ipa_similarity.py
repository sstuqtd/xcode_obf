#!/usr/bin/env python3
"""
IPA 相似度计算工具 (Mac)
比较两个 .ipa 文件的相似度，基于提取的字符串集合。
"""

import tempfile
import argparse
from pathlib import Path

from ipa_string_extractor import (
    extract_ipa,
    collect_all_strings,
    deduplicate_and_filter,
)


def get_string_sets(payload_path: str, min_binary_length: int = 4) -> dict[str, set[str]]:
    """从 Payload 目录收集各类字符串集合"""
    results = collect_all_strings(payload_path, min_binary_length)

    return {
        "plist": set(deduplicate_and_filter(results["plist_strings"])),
        "localizable": set(deduplicate_and_filter(results["localizable_strings"])),
        "binary": set(deduplicate_and_filter(results["binary_strings"], min_len=4)),
    }


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard 相似度：|A ∩ B| / |A ∪ B|，范围 [0, 1]"""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def dice_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Dice 系数：2|A ∩ B| / (|A| + |B|)，范围 [0, 1]"""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    return 2 * intersection / (len(set_a) + len(set_b))


def overlap_coefficient(set_a: set[str], set_b: set[str]) -> float:
    """重叠系数：|A ∩ B| / min(|A|, |B|)，范围 [0, 1]"""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    return intersection / min(len(set_a), len(set_b))


def compute_similarity(
    sets_a: dict[str, set[str]],
    sets_b: dict[str, set[str]],
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """
    计算两个 IPA 的加权相似度。
    weights: 各类型权重，默认 plist=0.3, localizable=0.3, binary=0.4
    """
    if weights is None:
        weights = {"plist": 0.3, "localizable": 0.3, "binary": 0.4}

    scores = {}
    weighted_sum = 0.0
    weight_total = 0.0

    for key in ("plist", "localizable", "binary"):
        j = jaccard_similarity(sets_a.get(key, set()), sets_b.get(key, set()))
        scores[f"{key}_jaccard"] = j
        w = weights.get(key, 0)
        weighted_sum += j * w
        weight_total += w

    scores["weighted_jaccard"] = weighted_sum / weight_total if weight_total else 0.0

    # 合并所有字符串计算整体 Jaccard
    all_a = sets_a.get("plist", set()) | sets_a.get("localizable", set()) | sets_a.get("binary", set())
    all_b = sets_b.get("plist", set()) | sets_b.get("localizable", set()) | sets_b.get("binary", set())
    scores["overall_jaccard"] = jaccard_similarity(all_a, all_b)
    scores["overall_dice"] = dice_similarity(all_a, all_b)

    return scores


def main():
    parser = argparse.ArgumentParser(
        description="计算两个 .ipa 文件的相似度（Mac 适用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 ipa_similarity.py app1.ipa app2.ipa
  python3 ipa_similarity.py app1.ipa app2.ipa -o report.txt
  python3 ipa_similarity.py app1.ipa app2.ipa --weights plist=0.5,localizable=0.3,binary=0.2
        """,
    )
    parser.add_argument("ipa1", help="第一个 .ipa 文件路径")
    parser.add_argument("ipa2", help="第二个 .ipa 文件路径")
    parser.add_argument("-o", "--output", help="输出报告文件路径")
    parser.add_argument("-n", "--min-length", type=int, default=4, help="二进制字符串最小长度")
    parser.add_argument(
        "--weights",
        default="plist=0.3,localizable=0.3,binary=0.4",
        help="权重: plist,localizable,binary（逗号分隔 key=value）",
    )
    parser.add_argument("--no-cleanup", action="store_true", help="保留解压目录")

    args = parser.parse_args()

    # 解析权重
    weights = {}
    for part in args.weights.split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                weights[k.strip()] = float(v.strip())
            except ValueError:
                pass

    extract_dirs = []
    try:
        dir1 = tempfile.mkdtemp(prefix="ipa_sim_1_")
        dir2 = tempfile.mkdtemp(prefix="ipa_sim_2_")
        extract_dirs = [dir1, dir2]

        payload1 = extract_ipa(args.ipa1, dir1)
        payload2 = extract_ipa(args.ipa2, dir2)

        sets1 = get_string_sets(payload1, args.min_length)
        sets2 = get_string_sets(payload2, args.min_length)

        scores = compute_similarity(sets1, sets2, weights or None)

        # 统计信息
        stats1 = {k: len(v) for k, v in sets1.items()}
        stats2 = {k: len(v) for k, v in sets2.items()}

        lines = [
            "=" * 60,
            "IPA 相似度报告",
            "=" * 60,
            f"IPA 1: {args.ipa1}",
            f"  - plist: {stats1['plist']}, localizable: {stats1['localizable']}, binary: {stats1['binary']}",
            f"IPA 2: {args.ipa2}",
            f"  - plist: {stats2['plist']}, localizable: {stats2['localizable']}, binary: {stats2['binary']}",
            "",
            "--- 相似度得分 ---",
            f"  plist Jaccard:        {scores['plist_jaccard']:.4f}",
            f"  localizable Jaccard:  {scores['localizable_jaccard']:.4f}",
            f"  binary Jaccard:      {scores['binary_jaccard']:.4f}",
            f"  加权 Jaccard:         {scores['weighted_jaccard']:.4f}",
            f"  整体 Jaccard:         {scores['overall_jaccard']:.4f}",
            f"  整体 Dice:            {scores['overall_dice']:.4f}",
            "=" * 60,
        ]

        report = "\n".join(lines)

        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"报告已写入: {args.output}")

        print(report)

    finally:
        if not args.no_cleanup and extract_dirs:
            import shutil
            for d in extract_dirs:
                try:
                    shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass


if __name__ == "__main__":
    main()

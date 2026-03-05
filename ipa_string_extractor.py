#!/usr/bin/env python3
"""
IPA 字符提取工具 (Mac)
从 .ipa 文件中提取可读字符串，包括：
- 二进制可执行文件中的字符串
- Info.plist 等 plist 文件内容
- Localizable.strings 等本地化字符串
"""

import os
import re
import zipfile
import subprocess
import tempfile
import argparse
from pathlib import Path


def extract_ipa(ipa_path: str, output_dir: str) -> str:
    """解压 .ipa 文件到指定目录，返回 Payload 路径"""
    ipa_path = Path(ipa_path).resolve()
    if not ipa_path.exists():
        raise FileNotFoundError(f"IPA 文件不存在: {ipa_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(ipa_path, "r") as zf:
        zf.extractall(output_path)

    payload_path = output_path / "Payload"
    if not payload_path.exists():
        raise ValueError(f"IPA 结构异常，未找到 Payload 目录: {ipa_path}")

    return str(payload_path)


def extract_strings_from_binary(file_path: str, min_length: int = 4) -> list[str]:
    """使用 macOS 自带的 strings 命令从二进制文件提取可读字符串"""
    try:
        result = subprocess.run(
            ["strings", "-n", str(min_length), file_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return []


def convert_plist_to_readable(plist_path: str) -> str:
    """使用 plutil 将 plist 转为可读格式（XML 或 JSON）"""
    try:
        result = subprocess.run(
            ["plutil", "-convert", "xml1", "-o", "-", plist_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def extract_strings_from_plist(plist_path: str) -> list[str]:
    """从 plist 文件提取字符串内容"""
    content = convert_plist_to_readable(plist_path)
    if not content:
        return []

    # 简单提取 <string>...</string> 中的内容
    pattern = re.compile(r"<string>([^<]*)</string>")
    return [m.group(1).strip() for m in pattern.finditer(content) if m.group(1).strip()]


def extract_strings_from_strings_file(file_path: str) -> list[str]:
    """从 .strings 文件提取键值对（可能是二进制格式）"""
    content = convert_plist_to_readable(file_path)
    if content:
        pattern = re.compile(r"<string>([^<]*)</string>")
        return [m.group(1).strip() for m in pattern.finditer(content) if m.group(1).strip()]

    # 若 plutil 失败，尝试按文本解析
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        result = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("/*") and "=" in line:
                result.append(line)
        return result
    except OSError:
        return []


def collect_all_strings(payload_path: str, min_binary_length: int = 4) -> dict[str, list[str]]:
    """遍历 Payload 目录，收集所有可提取的字符串"""
    payload = Path(payload_path)
    results = {
        "binary_strings": [],
        "plist_strings": [],
        "localizable_strings": [],
        "raw_text": [],
    }

    for root, dirs, files in os.walk(payload):
        # 跳过 _CodeSignature 等大目录以加速
        dirs[:] = [d for d in dirs if d not in ("_CodeSignature", "__MACOSX")]

        for name in files:
            file_path = Path(root) / name

            # 二进制可执行文件（无扩展名或常见二进制扩展名）
            if name in ("Info.plist", "embedded.mobileprovision"):
                continue  # 单独处理 plist

            if not any(name.lower().endswith(ext) for ext in (".plist", ".strings", ".json", ".xml", ".txt", ".html", ".css", ".js")):
                # 可能是二进制
                try:
                    if os.path.getsize(file_path) > 0 and os.path.getsize(file_path) < 100 * 1024 * 1024:  # 小于 100MB
                        strings_list = extract_strings_from_binary(str(file_path), min_binary_length)
                        if strings_list:
                            results["binary_strings"].extend(strings_list[:5000])  # 限制单文件数量
                except OSError:
                    pass

            elif name.endswith(".plist") or name == "Info.plist":
                try:
                    results["plist_strings"].extend(extract_strings_from_plist(str(file_path)))
                except OSError:
                    pass

            elif name.endswith(".strings"):
                try:
                    results["localizable_strings"].extend(extract_strings_from_strings_file(str(file_path)))
                except OSError:
                    pass

            elif name.lower().endswith((".json", ".xml", ".txt", ".html", ".css", ".js")):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    if text.strip():
                        results["raw_text"].append(f"--- {file_path.relative_to(payload)} ---\n{text[:5000]}")
                except OSError:
                    pass

    return results


def deduplicate_and_filter(strings: list[str], min_len: int = 2, max_len: int = 500) -> list[str]:
    """去重并过滤无效字符串"""
    seen = set()
    result = []
    for s in strings:
        s = s.strip()
        if min_len <= len(s) <= max_len and s not in seen and not s.isdigit():
            seen.add(s)
            result.append(s)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="从 .ipa 文件中提取可读字符串（Mac 适用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 ipa_string_extractor.py app.ipa
  python3 ipa_string_extractor.py app.ipa -o output.txt
  python3 ipa_string_extractor.py app.ipa --extract-dir ./extracted
        """,
    )
    parser.add_argument("ipa", help=".ipa 文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径（默认打印到控制台）")
    parser.add_argument("--extract-dir", help="解压目录（默认使用临时目录）")
    parser.add_argument("-n", "--min-length", type=int, default=4, help="二进制字符串最小长度（默认 4）")
    parser.add_argument("--no-cleanup", action="store_true", help="保留解压目录不删除")

    args = parser.parse_args()

    extract_dir = args.extract_dir
    if not extract_dir:
        extract_dir = tempfile.mkdtemp(prefix="ipa_extract_")

    try:
        payload_path = extract_ipa(args.ipa, extract_dir)
        results = collect_all_strings(payload_path, args.min_length)

        # 合并并去重
        all_strings = []
        all_strings.extend(results["plist_strings"])
        all_strings.extend(results["localizable_strings"])
        all_strings.extend(deduplicate_and_filter(results["binary_strings"], min_len=4))

        # 添加原始文本片段
        output_lines = []
        output_lines.append("=" * 60)
        output_lines.append(f"IPA 字符提取结果: {args.ipa}")
        output_lines.append("=" * 60)

        output_lines.append("\n--- Plist / 配置字符串 ---")
        for s in deduplicate_and_filter(results["plist_strings"]):
            output_lines.append(s)

        output_lines.append("\n--- 本地化字符串 ---")
        for s in deduplicate_and_filter(results["localizable_strings"]):
            output_lines.append(s)

        output_lines.append("\n--- 二进制提取字符串（部分） ---")
        for s in deduplicate_and_filter(results["binary_strings"])[:2000]:
            output_lines.append(s)

        if results["raw_text"]:
            output_lines.append("\n--- 文本文件内容 ---")
            output_lines.extend(results["raw_text"])

        output_text = "\n".join(output_lines)

        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_text)
            print(f"已写入: {args.output}")
        else:
            print(output_text)

    finally:
        if not args.no_cleanup and not args.extract_dir:
            import shutil
            try:
                shutil.rmtree(extract_dir, ignore_errors=True)
            except OSError:
                pass


if __name__ == "__main__":
    main()

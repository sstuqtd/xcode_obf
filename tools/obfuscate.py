#!/usr/bin/env python3
"""
IPA 相似度降低工具 - 统一入口
参考 docs/降低IPA相似度指南.md
"""

import argparse
import sys
from pathlib import Path

# 确保可导入同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))


def cmd_plist(args):
    from plist_obfuscator import main as plist_main
    sys.argv = ["plist_obfuscator"] + args.extra
    plist_main()


def cmd_strings(args):
    from strings_obfuscator import main as strings_main
    sys.argv = ["strings_obfuscator"] + args.extra
    strings_main()


def cmd_literal(args):
    from literal_obfuscator import main as literal_main
    sys.argv = ["literal_obfuscator"] + args.extra
    literal_main()


def cmd_split(args):
    from method_splitter import main as split_main
    sys.argv = ["method_splitter"] + args.extra
    split_main()


def cmd_oc(args):
    from oc_advanced_obfuscator import main as oc_main
    sys.argv = ["oc_advanced_obfuscator"] + args.extra
    oc_main()


def cmd_unity(args):
    from unity_obfuscate import main as unity_main
    sys.argv = ["unity_obfuscate"] + args.extra
    unity_main()


def cmd_string_encrypt(args):
    from string_encrypt import main as encrypt_main
    sys.argv = ["string_encrypt"] + args.extra
    encrypt_main()


def cmd_data_encrypt(args):
    from data_encrypt import main as data_main
    sys.argv = ["data_encrypt"] + args.extra
    data_main()


def cmd_oc_ast(args):
    from oc_ast_splitter import main as ast_main
    sys.argv = ["oc_ast_splitter"] + args.extra
    ast_main()


def main():
    parser = argparse.ArgumentParser(
        description="IPA 相似度降低工具集（参考 降低IPA相似度指南.md）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令:
  plist     混淆 Info.plist 等 plist 文件
  strings   混淆 Localizable.strings 键名
  literal   生成字符串字面量混淆代码（Swift/ObjC）
  split     将长方法拆分为 2-5 个小方法（Swift）
  oc        OC 高级混淆：方法拆分、代码格式化（Objective-C）
  unity     Unity 导出 Xcode 工程自动混淆
  str-enc  字符串自动加密/解密
  data-enc Data/Raw 文件加密/解密
  oc-ast   OC 方法拆分（Clang AST，语句边界安全）

示例:
  python3 obfuscate.py plist path/to/Info.plist
  python3 obfuscate.py strings en.lproj/Localizable.strings -m mapping.json
  python3 obfuscate.py literal config secrets.txt -o Obfuscated.swift
  python3 obfuscate.py split MyViewController.swift -o MyViewController.swift
  python3 obfuscate.py oc ViewController.m --format --parts 3-5
  python3 obfuscate.py unity /path/to/Unity-iPhone
  python3 obfuscate.py str-enc Classes/
  python3 obfuscate.py data-enc encrypt Data/Raw -o Data/Raw.enc
  python3 obfuscate.py oc-ast ViewController.m
        """,
    )
    parser.add_argument("cmd", choices=["plist", "strings", "literal", "split", "oc", "oc-ast", "unity", "str-enc", "data-enc"], help="子命令")
    parser.add_argument("extra", nargs=argparse.REMAINDER, help="传递给子命令的参数")

    args = parser.parse_args()

    handlers = {
        "plist": cmd_plist, "strings": cmd_strings, "literal": cmd_literal,
        "split": cmd_split, "oc": cmd_oc, "unity": cmd_unity,
        "str-enc": cmd_string_encrypt, "data-enc": cmd_data_encrypt,
        "oc-ast": cmd_oc_ast,
    }
    if args.cmd in handlers:
        handlers[args.cmd](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

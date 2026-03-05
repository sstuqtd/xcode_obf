#!/bin/bash
#
# Xcode Build Phase Run Script
# 在编译前自动混淆 Plist 和 .strings，降低 IPA 相似度
#
# 使用方法：
# 1. 在 Xcode 中选中 Target -> Build Phases -> + -> New Run Script Phase
# 2. 将本脚本内容复制进去，或设置: "${SRCROOT}/path/to/xcode_run_script.sh"
# 3. 调整下方变量
#

set -e

# === 配置（请根据项目修改）===
TOOLS_DIR="${SRCROOT}/path/to/tools"   # 指向 tools 目录的绝对路径
OBFUSCATE_PY="${TOOLS_DIR}/obfuscate.py"

# 仅在 Release 构建时混淆（可选）
if [ "${CONFIGURATION}" = "Release" ]; then

    # 1. 混淆 Info.plist
    if [ -n "${INFOPLIST_FILE}" ] && [ -f "${SRCROOT}/${INFOPLIST_FILE}" ]; then
        echo "Obfuscating Info.plist..."
        python3 "${OBFUSCATE_PY}" plist "${SRCROOT}/${INFOPLIST_FILE}" --keys "CFBundleName,CFBundleExecutable" --dummy-keys 2
    fi

    # 2. 混淆各语言的 Localizable.strings（可选）
    # for f in "${SRCROOT}"/**/*.lproj/Localizable.strings; do
    #   [ -f "$f" ] || continue
    #   echo "Obfuscating $f..."
    #   python3 "${OBFUSCATE_PY}" strings "$f" -m "${f}.mapping.json"
    # done

fi

echo "Obfuscation done."

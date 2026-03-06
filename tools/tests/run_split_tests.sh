#!/bin/bash
# 对 10 个测试文件运行 oc_ast_splitter，输出拆分结果
cd "$(dirname "$0")/.."
OUT=./tests/out
mkdir -p "$OUT"

echo "=== OC/C/C++ 方法拆分测试（10 个文件）==="
for f in tests/test_oc_01.m tests/test_oc_02.m tests/test_oc_03.m tests/test_oc_04.m \
         tests/test_c_01.c tests/test_c_02.c tests/test_c_03.c \
         tests/test_cpp_01.cpp tests/test_cpp_02.cpp tests/test_cpp_03.cpp; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    echo ""
    echo "--- $name ---"
    cp "$f" "$OUT/${name}.before"
    python3 oc_ast_splitter.py "$f" -o "$OUT/$name" --min-stmts 3 2>&1 | grep -E "已拆分|未找到"
done
echo ""
echo "输出目录: $OUT"
echo "查看对比: diff tests/out/test_oc_01.m.before tests/out/test_oc_01.m"

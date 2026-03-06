# OC/C/C++ 方法拆分测试

10 个测试文件，用于验证 `oc_ast_splitter.py` 的拆分效果。

## 测试文件

| 文件 | 语言 | 说明 |
|------|------|------|
| test_oc_01.m | Objective-C | 无参数 void 方法 processData（应拆分） |
| test_oc_02.m | Objective-C | 带参数 handleResponse:task:（不拆）+ 无参数 setupUI（应拆分） |
| test_oc_03.m | Objective-C | initConfig、cleanup 两个无参数方法 |
| test_oc_04.m | Objective-C | createUI 无参数方法 |
| test_c_01.c | C | process_buffer 自由函数 |
| test_c_02.c | C | init_storage、reset_storage 两个函数 |
| test_c_03.c | C | run_calculation 函数 |
| test_cpp_01.cpp | C++ | fill_vector、clear_cache 自由函数 |
| test_cpp_02.cpp | C++ | DataProcessor 类，process、validate 成员函数（lambda 拆分） |
| test_cpp_03.cpp | C++ | build_string 自由函数 + Logger 类 flush 成员 |

## 运行测试

```bash
cd tools
./tests/run_split_tests.sh   # 从 tools/ 目录运行
```

或逐个测试：

```bash
python3 oc_ast_splitter.py tests/test_oc_01.m -o tests/out/test_oc_01.m --min-stmts 3
```

## 预期行为

- **OC 无参数 (void) 方法**：拆分为 `[self _obf_xxx];` 调用 + `- (void)_obf_xxx { ... }` 辅助方法
- **OC 带参数方法**：不拆分（避免 undeclared identifier）
- **C 自由函数**：拆分为 `static void _obf_xxx(void) { ... }` 辅助函数
- **C++ 自由函数**：同 C
- **C++ 成员函数**：拆分为 `auto _obf_xxx = [this]() { ... };` lambda

输出目录：`tools/tests/out/`

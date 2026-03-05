# IPA 相似度降低工具

参考 [降低IPA相似度指南.md](../docs/降低IPA相似度指南.md) 实现的自动化工具集。

## 工具列表

| 工具 | 说明 |
|------|------|
| `plist_obfuscator.py` | 混淆 Info.plist，注入随机后缀 |
| `strings_obfuscator.py` | 混淆 Localizable.strings 键名 |
| `literal_obfuscator.py` | 生成 XOR 混淆的字符串字面量代码 |
| `method_splitter.py` | 将长方法拆分为 2-5 个小方法（Swift） |
| `oc_advanced_obfuscator.py` | OC 高级混淆：方法拆分、代码格式化 |
| `obfuscate.py` | 统一 CLI 入口 |
| `xcode_run_script.sh` | Xcode Build Phase 集成脚本 |

## 用法

### 1. Plist 混淆

```bash
# 混淆 Info.plist
python3 plist_obfuscator.py path/to/Info.plist

# 指定要修改的键
python3 plist_obfuscator.py Info.plist --keys CFBundleName,CFBundleExecutable,CFBundleVersion

# 添加随机冗余键
python3 plist_obfuscator.py Info.plist --dummy-keys 3

# 预览（不写入）
python3 plist_obfuscator.py Info.plist --dry-run
```

### 2. Localizable.strings 混淆

```bash
# 混淆并覆盖原文件
python3 strings_obfuscator.py en.lproj/Localizable.strings

# 输出到新文件并生成映射
python3 strings_obfuscator.py en.lproj/Localizable.strings -o en.lproj/Localizable.obf.strings -m mapping.json
```

**运行时还原**：需在 App 中根据 `mapping.json` 将逻辑键映射回混淆键后再调用 `NSLocalizedString`。

### 3. 字符串字面量混淆

**方式 A：配置文件**

创建 `secrets.txt`：
```
apiURL = "https://api.example.com"
apiKey = "sk-xxxx"
```

生成 Swift 代码：
```bash
python3 literal_obfuscator.py config secrets.txt -o Obfuscated.swift
```

在代码中使用：`Obfuscated.apiURL`、`Obfuscated.apiKey`

**方式 B：扫描源文件**

```bash
python3 literal_obfuscator.py scan MyApp/NetworkManager.swift -o Obfuscated.swift --pattern "https?://|api|key"
```

### 4. 方法拆分

将长方法拆分为 2-5 个小方法，改变二进制结构以降低相似度。会自动检测跨块变量依赖，避免作用域错误。

```bash
# 拆分超过 15 行的方法
python3 method_splitter.py MyViewController.swift -o MyViewController.swift

# 自定义行数阈值和拆分数量
python3 method_splitter.py MyViewController.swift --min-lines 10 --parts 3-5 --dry-run
```

### 5. OC 高级混淆

Objective-C 方法拆分，保持执行结果不变（依赖检测），支持代码格式化：

```bash
# 拆分 OC 方法
python3 oc_advanced_obfuscator.py ViewController.m -o ViewController.m

# 启用代码格式化
python3 oc_advanced_obfuscator.py ViewController.m --format --parts 3-5
```

### 6. 统一入口

```bash
python3 obfuscate.py plist Info.plist
python3 obfuscate.py strings en.lproj/Localizable.strings -m mapping.json
python3 obfuscate.py literal config secrets.txt -o Obfuscated.swift
python3 obfuscate.py split MyViewController.swift -o MyViewController.swift
python3 obfuscate.py oc ViewController.m --format
```

### 7. Xcode 集成

将 `xcode_run_script.sh` 中的 `TOOLS_DIR` 改为本仓库 `tools` 目录路径，然后在 Xcode Build Phases 中添加 Run Script 执行该脚本。建议仅在 Release 配置下启用。

## 验证

混淆后重新打包 IPA，用相似度工具验证：

```bash
python3 ipa_similarity.py original.ipa obfuscated.ipa -o report.txt
```

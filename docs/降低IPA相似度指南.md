# 降低 IPA 相似度指南

针对 `ipa_similarity.py` 的相似度指标（plist、localizable、binary），可通过以下方式修改 Xcode 工程以降低两个 IPA 的相似度。

---

## 1. Plist 字符串（权重约 0.3）

### 1.1 Info.plist

| 可修改项 | 说明 | 注意 |
|---------|------|------|
| `CFBundleIdentifier` | Bundle ID | 上架需唯一，可加后缀如 `.v2` |
| `CFBundleDisplayName` | 显示名称 | 可加版本后缀 |
| `CFBundleShortVersionString` | 版本号 | 每次发布递增 |
| `CFBundleVersion` | Build 号 | 每次构建递增 |
| `CFBundleName` | 内部名称 | 可随机化 |
| `UILaunchStoryboardName` | 启动图名称 | 可重命名 |
| `UISupportedInterfaceOrientations` 等 | 配置键值 | 顺序、冗余键可微调 |

### 1.2 其他 Plist

- 重命名 `*.plist` 文件名
- 调整键值顺序（对 XML 结构有轻微影响）
- 在非关键 plist 中添加随机注释或空键（若格式允许）

### 1.3 自动化

在 Build Phase 中添加 Run Script，用 `PlistBuddy` 或 `sed` 在编译时注入随机后缀：

```bash
# 示例：给 CFBundleName 加随机后缀
/usr/libexec/PlistBuddy -c "Set :CFBundleName \"MyApp_$(openssl rand -hex 4)\"" "$INFOPLIST_FILE"
```

---

## 2. 本地化字符串（权重约 0.3）

### 2.1 Localizable.strings

- **键名混淆**：将 `"login_button"` 改为 `"a1b2c3"` 等无意义键，运行时通过映射表还原
- **值混淆**：对非用户可见字符串做 Base64/XOR 编码，运行时解码
- **文件拆分**：按模块拆成多个 `.strings` 文件，减少单文件特征

### 2.2 自动化

- 使用脚本在 Pre-build 阶段生成混淆后的 `.strings`
- 或使用 [SwiftGen](https://github.com/SwiftGen/SwiftGen) 等工具生成类型安全的访问代码，间接改变字符串布局

---

## 3. 二进制字符串（权重约 0.4，影响最大）

### 3.1 字符串字面量混淆

**问题**：`"https://api.example.com"` 等字符串会直接出现在二进制中。

**方案**：

| 方案 | 说明 | 参考 |
|------|------|------|
| **ObfuscateMacro** | Swift 宏，编译时 XOR/Base64 等混淆 | [p-x9/ObfuscateMacro](https://github.com/p-x9/ObfuscateMacro) |
| **Obfuscator-iOS** | 将字符串转为十六进制 C 数组，运行时解码 | [pjebs/Obfuscator-iOS](https://github.com/pjebs/Obfuscator-iOS) |
| **手写 XOR** | 自定义 `String(decoding: xor(key, data))` 等 | Apple 论坛 [114721](https://developer.apple.com/forums/thread/114721) |

示例（ObfuscateMacro）：

```swift
let url = #ObfuscatedString("https://api.example.com", method: .bitXOR)
```

### 3.2 方法拆分

将长方法拆分为 2-5 个小方法，改变二进制中的符号布局，**保持执行结果不变**。

| 工具 | 语言 | 说明 |
|------|------|------|
| `method_splitter.py` | Swift | 按空行段落拆分，依赖检测避免作用域错误 |
| `oc_ast_splitter.py` | **OC/C/C++** | **Clang AST 语句边界拆分**（推荐，支持 .m/.mm/.c/.cpp） |
| `oc_advanced_obfuscator.py` | Objective-C | 正则拆分，支持 `--format` 代码格式化 |

- 自动检测跨块变量依赖，有依赖则合并，不拆分
- 生成 `_obf_xxx` 形式的 private 辅助方法

### 3.3 符号名混淆（类名、方法名、变量名）

| 方案 | 说明 | 限制 |
|------|------|------|
| **SwiftShield** | 使用 SourceKit 全工程混淆符号 | 需 100% 纯代码 UI，无 Storyboard/XIB |
| **手动重命名** | 将 `UserManager` → `A1B2` 等 | 工作量大，需避免与反射/序列化冲突 |

### 3.4 其他二进制特征

- **日志字符串**：用 `#if DEBUG` 包裹，Release 不编译
- **错误信息**：避免硬编码 `"Error: xxx"`，改为错误码 + 运行时查表
- **URL、API Key**：务必混淆或从服务端下发

---

## 4. 构建配置差异化

### 4.1 每次构建引入随机性

在 Build Settings 或 Run Script 中：

```bash
# 生成随机后缀
RAND_SUFFIX=$(openssl rand -hex 4)
# 写入到预编译头或 xcconfig，供代码使用
```

### 4.2 条件编译

用不同的 `Active Compilation Conditions` 或 `#if` 分支，让不同构建产物包含不同字符串集合。

---

## 5. 实施优先级建议

| 优先级 | 措施 | 预期效果 |
|--------|------|----------|
| 高 | 字符串字面量混淆（API URL、Key 等） | 显著降低 binary 相似度 |
| 高 | Info.plist 版本号、Build 号、Bundle 相关字段 | 降低 plist 相似度 |
| 中 | 本地化键名混淆 | 降低 localizable 相似度 |
| 中 | 符号名混淆（若工程结构允许） | 进一步降低 binary 相似度 |
| 低 | 文件名、plist 键顺序等微调 | 小幅降低 |

---

## 6. 验证

修改后重新打包 IPA，用本仓库工具验证：

```bash
python3 ipa_similarity.py original.ipa obfuscated.ipa -o report.txt
```

对比 `plist_jaccard`、`localizable_jaccard`、`binary_jaccard` 和 `weighted_jaccard` 的变化。

---

## 7. Unity 2020.3+ 导出工程自动混淆

针对 Unity 导出的 Xcode 工程，可使用 `unity_obfuscate.py` 一键执行：

```bash
# Unity 导出后，在工程目录执行
python3 tools/unity_obfuscate.py /path/to/Unity-iPhone

# 或使用 obfuscate 入口
python3 tools/obfuscate.py unity /path/to/Unity-iPhone
```

**流程**：Unity 导出 → 运行 `unity_obfuscate` → Xcode 构建 IPA

会自动处理：Info.plist、Classes/*.m、Classes/*.mm 等。

---

## 8. 参考链接

- [ObfuscateMacro - Swift 字符串混淆宏](https://github.com/p-x9/ObfuscateMacro)
- [SwiftShield - 符号混淆](https://github.com/rockbruno/swiftshield)
- [Obfuscator-iOS - 字符串编码](https://github.com/pjebs/Obfuscator-iOS)
- [Apple - Managing Info.plist](https://developer.apple.com/documentation/bundleresources/managing-your-app-s-information-property-list)

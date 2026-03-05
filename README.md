# xcode_obf
xcode_obf

## IPA 字符提取工具 (Mac)

从 `.ipa` 文件中提取可读字符串，适用于 Mac 系统。

### 依赖

- Python 3.6+
- macOS 自带命令：`strings`、`plutil`、`unzip`（通过 Python zipfile）

无需额外 pip 依赖。

### 用法

```bash
# 提取并打印到控制台
python3 ipa_string_extractor.py your_app.ipa

# 输出到文件
python3 ipa_string_extractor.py your_app.ipa -o output.txt

# 指定解压目录并保留
python3 ipa_string_extractor.py your_app.ipa --extract-dir ./extracted --no-cleanup

# 调整二进制字符串最小长度
python3 ipa_string_extractor.py your_app.ipa -n 6
```

### 提取内容

- **Plist 字符串**：Info.plist、配置 plist 中的键值
- **本地化字符串**：`*.lproj/Localizable.strings` 等
- **二进制字符串**：可执行文件中的可读文本（通过 `strings` 命令）
- **文本文件**：JSON、XML、HTML 等

### 两个 IPA 相似度计算

```bash
# 计算 app1.ipa 与 app2.ipa 的相似度
python3 ipa_similarity.py app1.ipa app2.ipa

# 输出到报告文件
python3 ipa_similarity.py app1.ipa app2.ipa -o report.txt

# 自定义权重（plist/localizable/binary）
python3 ipa_similarity.py app1.ipa app2.ipa --weights plist=0.5,localizable=0.3,binary=0.2
```

**相似度指标**：
- **Jaccard**：交集/并集，范围 [0, 1]
- **Dice**：2×交集/(A+B)
- **加权 Jaccard**：按 plist、localizable、binary 加权

### 降低 IPA 相似度

- **指南**：[docs/降低IPA相似度指南.md](docs/降低IPA相似度指南.md)
- **工具**：[tools/](tools/) 目录提供自动化混淆工具：
  - `plist_obfuscator.py` - Plist 混淆
  - `strings_obfuscator.py` - Localizable.strings 键名混淆
  - `literal_obfuscator.py` - 字符串字面量混淆（生成 Swift/ObjC 代码）
  - `method_splitter.py` - 将长方法拆分为 2-5 个小方法（Swift）
  - `oc_advanced_obfuscator.py` - OC 高级混淆：方法拆分、代码格式化，保持执行结果不变
  - `unity_obfuscate.py` - **Unity 导出 Xcode 工程自动混淆**（Plist、字符串加密、Data 加密）
  - `string_encrypt.py` - 字符串自动加密/解密
  - `data_encrypt.py` - Data/Raw 文件加密/解密
  - `obfuscate.py` - 统一入口
  - `xcode_run_script.sh` - Xcode Build Phase 集成

详见 [tools/README.md](tools/README.md)

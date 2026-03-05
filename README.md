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

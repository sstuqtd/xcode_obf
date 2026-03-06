# Unity Data/Raw Hook 解密方案

通过 **Hook 技术** 拦截 Unity 的文件读取接口，在读取 Data/Raw 目录下文件时先解密再返回，无需修改 C# 业务代码。

## 原理

Unity iOS 构建后，StreamingAssets 被复制到 `xxx.app/Data/Raw/`。当 C# 使用 `File.ReadAllBytes`、`UnityWebRequest`、`WWW` 等读取时，底层会调用：

- **NSData dataWithContentsOfFile:**（Objective-C）
- **fopen** / **fread**（C 层，IL2CPP 可能走此路径）

通过 **Method Swizzling** 替换 `[NSData dataWithContentsOfFile:]`，在路径包含 `Data/Raw` 时先读文件、XOR 解密、再返回解密后的 `NSData`，其余路径走原始实现。

## 流程

```
Unity C# 读取 Data/Raw/xxx
    ↓
NSData dataWithContentsOfFile:path
    ↓
[Hook] 检测 path 含 "Data/Raw"
    ↓ 是
读文件 → XOR 解密 → 返回 NSData
    ↓ 否
调用原始 dataWithContentsOfFile: 返回
```

## 使用步骤

### 方式一：一键完成（推荐）

```bash
cd /path/to/Unity-iPhone
python3 tools/data_encrypt.py setup-raw
```

或指定密钥、工程路径：

```bash
python3 tools/data_encrypt.py setup-raw /path/to/Unity-iPhone --key xwlkey
```

会完成：加密 Data/Raw、生成 DataRawHook.m、DataRawHook.h、保存 key.bin。

### 方式二：分步执行

```bash
python3 tools/data_encrypt.py encrypt Data/Raw --key-out key.bin
python3 tools/data_encrypt.py gen-hook --key $(cat key.bin.hex) -o DataRawHook.m
```

### 3. 集成到 Xcode

- 将 `DataRawHook.m` 加入 Unity 导出的 Xcode 工程
- 在 `UnityAppController.mm` 或 `main.m` 的 `application:didFinishLaunchingWithOptions:` 最早处调用 `DataRawHookInstall()`，确保在 Unity 初始化前完成 Hook

### 4. 调用时机示例

```objc
// UnityAppController.mm 或 main.m
#import "DataRawHook.h"

- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)launchOptions
{
    DataRawHookInstall();  // 最先执行
    // ... 原有 Unity 初始化
}
```

## 路径匹配

Hook 会检查路径是否包含以下任一子串：

- `Data/Raw`
- `/Raw/`（兼容部分 Unity 版本）

仅匹配时进行解密，其他路径（如 Documents、Library）不受影响。

## 与手动调用的区别

| 方式 | 优点 | 缺点 |
|------|------|------|
| **DecryptedDataFromBundle**（手动） | 精确控制、无全局影响 | 需改 C# 或 native 调用点 |
| **Hook**（自动） | 零侵入、自动解密 | 影响所有 Data/Raw 读取，需尽早安装 |

## 参考

- [fishhook - Facebook](https://github.com/facebook/fishhook)（若需 hook fopen，可选用）
- [Objective-C Method Swizzling](https://developer.apple.com/documentation/objectivec/objective-c_runtime)
- [Unity StreamingAssets](https://docs.unity3d.com/Manual/StreamingAssets.html)

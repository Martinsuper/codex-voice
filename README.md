# Codex 语音提醒

一个运行在 Mac 菜单栏里的本地语音提醒应用。Codex 有结果、需要回答或等待人工审批时，喊一声“老板”，直到你接手。

第三方工具，与 OpenAI 官方产品无隶属关系。

[下载测试版 DMG](https://github.com/superslash-rico/codex-voice/releases/download/v0.5.0-beta.1/CodexVoice-0.5.0-beta.1-universal.dmg) · [全部发行文件](https://github.com/superslash-rico/codex-voice/releases/tag/v0.5.0-beta.1)

## 安装与重新打开

1. 下载 DMG，将 **Codex 语音提醒.app** 拖到 **Applications / 应用程序**。
2. 从应用程序打开，或按 `⌘ Space` 搜索 **Codex 语音提醒**。
3. 点击菜单栏波形图标打开面板。底部设备名可以选择播报扬声器。
4. 在设置里点击 **连接 Codex**，阅读说明后安装本地观察器。
5. 在 Codex CLI 的 `/hooks` 中审阅并信任这 5 个提醒观察器。

误退出后，再次从应用程序或 Spotlight 打开即可。设置中的 **登录后自动启动** 可在每次登录 Mac 时启动应用。关闭面板只收起窗口，**退出应用** 才结束本次运行。

应用内已包含 Python 运行环境，使用者无需安装 Python、Homebrew 或填写 API Key。

### 当前测试版边界

- macOS 13 及以上，安装包含 `arm64` 与 `x86_64` 两种架构。
- Apple 芯片 Mac 实机验证；Intel 和较旧 macOS 版本仍需实机验收。
- 尚未完成 Apple Developer ID 签名与公证。首次打开可能受到系统提示或阻止；请核对来源与校验值后，按 macOS 自身的安全提示处理。安装包不关闭 Gatekeeper，也不移除隔离属性。
- 需要支持 Hooks 的本地 Codex。若 `/hooks` 不可用，请检查 Codex 版本与功能设置；受管环境也可能禁止用户观察器。
- 当前适配本机同一用户的本地聊天。云端、远程执行、连接器特殊审批和纯文字提问不保证覆盖。Codex 内部本地事件格式升级后可能需要更新适配。

## 日常操作

- **已接手 / 知道了**：停止这一条提醒；审批仍由你在原聊天中处理。
- **全部已接手**：停止全部当前提醒，面板自动收起。新提醒到来时再次出现。
- **稍后**：选择 5、15 或 30 分钟后再提醒。
- **暂停 15 分钟**：保留事项，暂时静音；也可提前恢复。
- **扬声器按钮**：再次播报当前事项。
- **试听一下**：创建测试提醒，按 5、10、15 秒间隔重复，点“已接手”停止。
- **提醒总开关**：关闭后立即停喊并清空当前提醒，重新开启只接收新事项。

普通提醒第一次播报后，依次间隔 30 秒、60 秒，再每隔 3 分钟重复。不同聊天分别接手，审批与提问优先。

### 扬声器选择

点击底部设备名，或 **设置 → 切换**。可选择 Mac 内置扬声器、已经连接的蓝牙 / USB / AirPlay 设备、虚拟音频输出，以及 **跟随系统输出**。

指定设备的选择会立即保存，按设备身份识别重连后的设备编号。设备断开、静音或音量为零时暂停，不自动换到其他扬声器。选择“跟随系统输出”时，使用 macOS 当前选择的设备。未显示的设备请先在系统中连接。

使用 macOS 屏幕共享时，声音路径还受共享模式影响。若声音转到远端电脑，请在客户端检查共享连接的声音与显示模式，并重新试听。

## 本地数据与权限

设置和运行数据保存在 `~/Library/Application Support/CodexVoice/`。应用读取当前用户的本地 Codex 事件，观察器仅转发提醒所需元数据。应用不上传聊天记录、音频设备列表或日志，不作审批决定。

连接安装器只增加本应用的 5 个观察器，备份原 `hooks.json`，保留其他观察器与审批策略；不写入 Hook 信任记录。新定义仍需用户在 Codex 中审核。可在 Codex 的 `/hooks` 中禁用或移除观察器。

删除应用前，可先关闭登录自启并退出。需要清理连接时，在 `/hooks` 中移除本应用的观察器；运行数据可自行备份后删除。

## 从源码构建

需要 macOS、Xcode Command Line Tools 和用于构建脚本的 Python 3.9 及以上。运行环境下载自 Python 官方网站，版本与 SHA-256 固定在 `scripts/python-runtime.json`。

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/build.py --package
python3 scripts/verify_app.py '.build/Codex 语音提醒.app'
```

应用位于 `.build/`，DMG、ZIP 和校验值位于 `dist/`。构建仅解包官方 Python 安装器，不向系统安装 Python。默认使用临时签名；有 Developer ID 证书时可传 `--identity`，正式分发还需要按 Apple 流程完成签名、公证与验证。

## 参考与第三方运行环境

- [OpenAI Docs：Hooks 与信任审核](https://learn.chatgpt.com/docs/hooks)
- [Apple：Developer ID 与分发签名](https://developer.apple.com/developer-id/)
- [Python 3.14.8 官方运行环境](https://www.python.org/downloads/release/python-3148/)

Python 及其所含第三方组件的许可证随安装包保留在应用的 `Contents/Resources/ThirdPartyLicenses/`。本仓库公开源码，尚未指定本项目代码的开源许可证。

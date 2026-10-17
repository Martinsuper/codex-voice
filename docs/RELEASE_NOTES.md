# Codex 语音提醒 v0.5.0-beta.1

首个可分享的 macOS 独立测试安装包。

- 轻巧菜单栏面板：需要时出现，全部接手后自动收起。
- 任务结果、结构化提问与人工审批的本地语音提醒；已接手仅停止喊话。
- 可选择 Mac、蓝牙、USB、已连接的 AirPlay、虚拟音频或跟随系统输出，选择自动保存。
- 支持稍后提醒、暂停、总开关、登录后启动、试听与再次播报。
- 应用内包含 Python 3.14.8，使用者无需安装 Python / Homebrew / API Key。
- 安装到应用程序后，可通过 Spotlight 搜索“Codex 语音提醒”重新打开。

## 下载与安装

下载 universal.dmg，拖入 Applications；也提供 ZIP 和 SHA-256 校验文件。
详细步骤见 [README](https://github.com/superslash-rico/codex-voice#安装与重新打开)。

首次连接时，在设置里安装 5 个本地观察器，再在 Codex CLI 的 `/hooks` 中由你审阅并信任。应用不自动信任 Hook、不作审批决定，不上传聊天记录或设备信息。

## 测试版边界

面向 macOS 13+，含 Apple 芯片与 Intel 两种架构。已在 Apple 芯片 Mac 实机验证，Intel 与旧版 macOS 尚未实机验收。

**此包尚未完成 Apple Developer ID 签名与公证。** 首次打开可能被 macOS 提示或阻止。请先核对仓库来源和校验值，再按系统自身提示处理；安装包不关闭 Gatekeeper 或移除隔离属性。

仅保证已验证的本地适配范围，远程 / 云端任务、受管环境和特殊连接器审批不保证覆盖。

31 项单元检查、移动目录独立运行、嵌入运行环境、Hook 隔离安装、退出重开及安装包完整性检查已通过。完整范围见 [验证记录](https://github.com/superslash-rico/codex-voice/blob/main/docs/VALIDATION.md)。

# Codex 语音提醒 v0.6.0-beta.2

免费语音提醒工具新增「订阅与充值」入口，方便查看第三方 ChatGPT / Codex 订阅服务。

## 本次更新

- **主面板新增入口**：在 Codex 剩余用量下方点击「订阅与充值」，通过默认浏览器打开 [slashx.shop](https://slashx.shop/)。
- **用量详情新增服务卡片**：查看套餐及购买、兑换说明，提醒服务离线时入口仍可使用。
- **清楚标注免费和第三方服务**：提醒工具免费使用，订阅为可选服务；套餐、价格及适用条件以网站为准，网站非 OpenAI 官方网站。
- **主动点击才跳转**：打开固定网址，链接不附加 Codex 账号、邮箱、用量或登录凭据。
- **适配较矮屏幕**：调整提醒列表高度，为新增入口保留空间。

保留 v0.6.0-beta.1 的声音配置、扬声器选择、额度显示与语音提醒、后台自动恢复、分类规则和定时免打扰。

## 下载与升级

推荐下载 **CodexVoice-0.6.0-beta.2-universal.dmg**，拖入 Applications。也提供 ZIP、`SHA256SUMS.txt` 和可单独下载的 `CHANGELOG.md`。

旧用户先在设置中退出旧版，再替换 `/Applications/Codex 语音提醒.app` 并重新打开。保持同一路径可保留设置、已有 Hook 连接及登录自启。

首次使用需在应用设置中连接 Codex，再到 Codex CLI 的 `/hooks` 审阅并信任 5 个观察器。应用内含 Python，无需安装 Python、Homebrew 或填写 API Key。用量显示需要支持相关接口的官方 Codex 和 ChatGPT 登录。

完整历史见 [更新日志](https://github.com/superslash-rico/codex-voice/blob/v0.6.0-beta.2/CHANGELOG.md)，本版检查见 [验证记录](https://github.com/superslash-rico/codex-voice/blob/v0.6.0-beta.2/docs/VALIDATION.md)。

## 测试版说明

158 项既有检查通过；两个入口完成原生点击及浅色、深色、小屏、离线状态检查。安装包通过完整性与签名校验，且与本机已安装版本一致。

面向 macOS 13+，包含 arm64 / x86_64，实际运行验证为 Apple 芯片 Mac。Intel 和旧 macOS 尚未实机验收。

**尚未完成 Apple Developer ID 签名与公证。** 首次打开可能被 macOS 提示或阻止，请核对来源和 SHA-256 后按系统「隐私与安全性」提示处理。

任务提醒当前适配本机 Codex；远程、云端、受管环境和特殊审批仍有兼容限制。

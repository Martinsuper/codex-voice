# Codex 语音提醒 v0.9.1-beta.1

把电脑提醒、用量查看和 AI Passport 配件整合为一个 Mac 软件。没有硬件也可使用；有工牌时可以同步任务与宠物、独立播报，并按住确认键向电脑听写。

## 本次更新

- 全新 SwiftUI 面板：扬声器、提醒与待处理、小圆环用量、完整订阅卡片、AI Passport 的首页顺序；大圆环和周期详情集中在用量详情。
- 首页保留一个提醒总开关，电脑播报移入“声音输出”；AI Passport 可单独开关播报或与电脑同时播报。
- 显眼的蓝色收起按钮，点击外部或切换应用后自动收起，后台继续工作。
- 一个软件管理 AI Passport：加密蓝牙配对、自动重连、任务/用量同步、实体键接手与独立设置。
- 自动同步 Codex 宠物，先完整传输和校验再切换；新用户昵称默认 Codex，支持修改，升级保留已有昵称。
- macOS 26+ 本机中文听写：开始单音后讲话，松手识别，完成双音表示文字已填入目标输入框；不自动发送，成功时不弹保留面板。
- 处理听写输入适配、提示音杂音与中英文输入法卡顿问题，保留已有声音规则、暂停、免打扰、额度提醒及后台恢复能力。
- 同一仓库公开 Mac 与配套 0.3.0-pets 固件源码，新增给新手的刷写、配对、听写和 Codex 协助构建指南。
- README 顶部和软件首页突出展示 [slashx.shop](https://slashx.shop/) 订阅与充值入口，工具免费，第三方服务可选。

## 下载

- `CodexVoice-0.9.1-beta.1-universal.dmg`：推荐的 Mac 安装包，拖入 Applications。
- `CodexVoice-0.9.1-beta.1-universal.zip`：相同应用的 ZIP。
- `AI-Passport-Codex-0.3.0-pets-full.bin`：AI Passport 完整镜像，从 `0x0` 写入。
- `AI-Passport-Codex-0.3.0-pets.zip`：完整/分段固件、分区布局、校验及刷写说明。
- `SHA256SUMS.txt`：发行资产的校验值；源码也可直接在本 tag 浏览或下载 GitHub 源码归档。

## 安装与升级

退出旧版，替换 `/Applications/Codex 语音提醒.app`，重新打开。保持路径保留原设置、昵称、观察器和登录自启。听写升级后若不能落字，在系统“设备控制和数据访问/辅助功能”中移除旧授权项，重新添加当前同名应用。

首次安装需连接 Codex，并在 `/hooks` 审阅五项观察器；启用硬件另需蓝牙配对。普通功能面向 macOS 13+；听写需要 macOS 26+、简体中文本机模型和输入权限。用户无需安装 Python、Homebrew 或填写 API Key。

## 工牌用户必读

仅适配 FoloToy AI Passport（ESP32-C3、8 MB Flash、无 PSRAM）。完整刷写替换原程序，可能清除配对及设置；不应例行整片擦除。分段升级需先确认分区兼容。本次发布提供固件，不会自动改写你 USB 上的设备。

[手把手安装/刷写/连接指南](https://github.com/superslash-rico/codex-voice/blob/v0.9.1-beta.1/docs/AI_PASSPORT.md) · [全部功能与使用方法](https://github.com/superslash-rico/codex-voice/blob/v0.9.1-beta.1/README.md) · [验证记录](https://github.com/superslash-rico/codex-voice/blob/v0.9.1-beta.1/docs/VALIDATION.md)

## 测试版边界

Mac 包含 arm64 / x86_64，实际硬件验证为 Apple 芯片 Mac 和一张 AI Passport；Intel、旧系统、长时间续航及远程/云端特殊任务仍需验证。本工具依赖 Codex 的本地事件与宠物资源格式，后续客户端变更可能需要适配。

**尚未完成 Apple Developer ID 签名与公证。** 请先核对来源与 SHA-256，再按 macOS 系统安全提示处理首次打开。

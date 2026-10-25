<p align="right"><strong>简体中文</strong> · <a href="README.md">English</a></p>

# AI Passport：Codex 语音提醒配件固件

这是 [Codex 语音提醒](../../README.md) 可选 AI Passport 配件的完整源码快照，不是上游演示固件。固件版本 **0.3.0-pets**，配套 Mac 发布版 **0.9.1-beta.1**。

下载、刷写、配对、按键、听写和排错请先看 [手把手工牌指南](../../docs/AI_PASSPORT.md)。项目主指南目前为简体中文；此目录的工程文档提供中英文配对版本。

## 硬件与功能

适配 FoloToy AI Passport：ESP32-C3、**8 MB Flash、无 PSRAM**，使用原板载屏幕、麦克风、扬声器和三个按钮。任务卡片、用量圆环、宠物屏保、实体键接手和加密 BLE 均为本工具单独实现，不能刷到任意 ESP32 开发板。

电脑和工牌可分别播报。宠物跟随本机 Codex 选择，资源完整校验后切换。本机中文听写需要 macOS 26+ 和已安装模型，在 Mac 上识别，不自动发送。首次连接由 Mac 应用写入默认昵称 Codex，升级保留已有昵称。

## 构建

先读 [AGENTS.md](AGENTS.md)，按 [环境准备](docs/development/engineering/environment-setup.zh_CN.md) 准备 **ESP-IDF 5.5.3** 和依赖。

```sh
source /path/to/esp-idf-v5.5.3/export.sh
idf.py --version
./tools/validate.sh
```

完整 gate 检查文档/源码、运行主机测试、在隔离目录编译并验证合并镜像，生成 `build/FoloToy-AI-Passport-full.bin` 和 `build/firmware/` 内的匹配归档，不会操作 USB。仅 `idf.py build` 不能代替完整镜像交付验证。

发布包的 `AI-Passport-Codex-0.3.0-pets-full.bin` 从 **`0x0`** 写入；应用单独镜像不能写到该地址。完整刷写可能重置 NVS 和配对，保留设置的分段升级要先核对分区兼容，不应例行整片擦除。详见 [布局与存储数据](docs/development/engineering/firmware-layout.zh_CN.md)。

本配件 factory 应用为 `0x10000` / `0x5F0000`，宠物区为 `0x600000` / `0x200000`，内部两个资源槽校验后切换。NVS、PHY 地址仍为 `0x9000`、`0xF000`。

## 来源与许可

基于 [FoloToy/ai-passport](https://github.com/FoloToy/ai-passport) 提交 `006c2279852e352a8433b2c21e5e09be2ca36f77`，导入范围和变更见 [provenance.json](provenance.json)。源码直接放在本仓库，无需配置 Git submodule。

本项目新增独立 Codex UI、任务/用量、认证 BLE 控制/音频/图像通道、干净听写音效、宠物 A/B 存储、中文资源、音频恢复、电量读取行为与测试。构建缓存、设备日志、个人配置、配对信息和本地调试符号不公开。

上游 MIT 许可见 [LICENSE](LICENSE)，字体许可见 [OFL](assets/fonts/NotoSansSC-OFL.txt)。自定义宠物形象不由 FoloToy 许可证覆盖，也不授予第三方角色或 OpenAI 标识权利。资源来源保留在 [assets](assets/README.zh_CN.md)。`docs/codex-*` 的历史设计/验收记录反映当时开发阶段，当前安装操作以项目主指南和本次发行验证为准。

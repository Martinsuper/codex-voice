# 项目目录与后续开发

本目录是项目的 Git 仓库根目录，也是后续开发、提交和推送的位置。

| 目录 | 用途 | GitHub 同步方式 |
| --- | --- | --- |
| `src/` | 应用、播报引擎和提醒连接源码 | 跟随 Git 提交 |
| `tests/` | 自动检查 | 跟随 Git 提交 |
| `scripts/` | 构建、图标生成、独立运行验证 | 跟随 Git 提交 |
| `docs/` | 安装、发行与验证说明、隔离演示截图 | 跟随 Git 提交 |
| `firmware/ai-passport/` | 工牌完整固件源码、BSP、资源与开发技能 | 跟随 Git 提交；生成固件只上传 Releases |
| `dist/` | DMG、ZIP 与校验文件 | 上传到 GitHub Releases |
| `.build/` | 生成的应用与构建中间文件 | 本地生成，已忽略 |
| `.build-cache/` | 已校验的官方运行环境下载缓存 | 本地保留，已忽略 |
| `local/legacy-v1/` | 早期实现和验收记录 | 本地资料，已忽略 |
| `local/work/` | 调试、协议、安装与迁移资料 | 本地资料，已忽略 |
| `local/design/` | 交互设计稿和界面参考 | 本地资料，已忽略 |
| `local/cache-before-move/` | 迁移前的编译缓存 | 本地归档，已忽略 |

`local/` 中可能包含本机路径、设备信息或私有测试记录；它完整保留在开发目录中，不参与公开仓库同步。历史的一次性安装脚本仅作记录，后续构建请使用根目录下的 `scripts/build.py`。

在仓库根目录运行：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/build.py --package
python3 scripts/verify_app.py '.build/Codex 语音提醒.app'
```

本地新功能开发完成后，先构建并验证，再备份旧版与设置，更新本机“应用程序”中的应用并启动，供用户测试。提交、推送到 `origin/main` 和通过 Releases 发行按用户的明确要求执行；现有 `.gitignore` 保留构建产物和本地资料的排除规则。

已安装的应用继续位于 macOS 的“应用程序”，运行设置位于 `~/Library/Application Support/CodexVoice/`，与源码目录分开。移动开发目录不会要求移动已安装应用。

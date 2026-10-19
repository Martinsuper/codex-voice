# 本地开发与升级验证

本轮开发始于 2026-10-17，发布为 v0.6.0-beta.1（内部构建号 8）。用户可见变更见 [更新日志](../CHANGELOG.md)，本版验收范围见 [验证记录](VALIDATION.md)。

## 可复现检查

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/build.py --package
python3 scripts/verify_app.py '.build/Codex 语音提醒.app'
```

构建脚本仅从明确的源码列表复制资源，不收集本机设置、Hook 配置、账号数据或 `local/` 内容。Python 官方运行环境的版本与校验值固定在 `scripts/python-runtime.json`。

`verify_app.py` 在含空格的临时目录复制应用，使用干净 PATH 和独立配置，验证内嵌 Python、伴随模块、架构、签名、Hook 入口及各项配置保存与重启。它不写入个人 Codex 的配置、信任记录或运行数据。

原生界面与故障恢复检查使用隔离配置和测试程序自行创建的服务，不向真实账号制造额度变动。测试样例、界面截图、一次性调试程序与安装备份位于已忽略的 `local/work/`；它们不作为发行内容。

## 本机升级原则

构建与验证完成后，先备份旧应用和运行数据，再正常退出、替换同名应用并重新打开。核对安装二进制与构建一致、服务和音频就绪、原设置及已有 Codex 连接保持。

运行数据固定在 `~/Library/Application Support/CodexVoice/`，与应用包、源码目录分开。替换应用不会删除设置；观察器和登录自启依赖应用安装路径，保持 `/Applications/Codex 语音提醒.app` 可复用原连接。

发布前审查 Git 的已暂存、未暂存与新增文件，只提交源码、测试和公开文档。DMG、ZIP 和校验值通过 GitHub Releases 发布；私有记录与安装备份不提交。

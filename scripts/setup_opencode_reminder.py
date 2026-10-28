#!/usr/bin/env python3
"""Backfill Codex Voice reminders for older released app builds.

New app builds cover all of this automatically: the built-in installer
(设置 → OpenCode 连接, src/opencode_setup.py) now writes tui.js AND the
server part index.js, registers tui.js in cli.json (+ an existing tui.json)
and registers the plugin directory in the global opencode.json(c) `plugins`
array — which is what makes the OpenCode server process (the home of
permission.asked and session.* events) run the plugin.

Run this script only on machines whose installed Codex 语音提醒.app predates
that installer. It calls the app's own installer first (so the template always
comes from the app bundle), then applies the two idempotent extra steps:

  1. add the plugin directory as a file:// entry in the global
     opencode.json(c) `plugins` array
  2. link server.js → tui.js when the directory has no server/index part

Both steps only ever touch this integration's own entries; other plugins and
settings are preserved. `python3 scripts/setup_opencode_reminder.py --remove`
undoes exactly these two steps; the app-side uninstall keeps working through
the 设置 → OpenCode 连接 dialog or `opencode_setup.py --remove`.

Examples:
  python3 scripts/setup_opencode_reminder.py             # install or repair
  python3 scripts/setup_opencode_reminder.py --status    # print status report
  python3 scripts/setup_opencode_reminder.py --remove    # undo the 2 steps
  python3 scripts/setup_opencode_reminder.py --app "/Applications/Codex 语音提醒.app"

OpenCode hot-reloads plugins after opencode.json is saved; OpenCode does not
need to be restarted, but the app must be running for reminders to fire.
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_APP = "/Applications/Codex 语音提醒.app"
DEFAULT_CONFIG = Path.home() / ".config" / "opencode"
STATE_DIR_NOTE = "~/Library/Application Support/CodexVoice"
PLUGIN_DIR_REL = Path("plugins") / "codex-voice"
SERVER_PART_NAMES = ("server.js", "server.ts", "index.js", "index.ts")


def default_state_dir():
    return Path.home() / "Library" / "Application Support" / "CodexVoice"


def default_config_dir():
    custom = os.environ.get("OPENCODE_CONFIG_DIR")
    if custom:
        return Path(custom)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "opencode"
    return DEFAULT_CONFIG


def app_resources(app):
    resources = Path(app).expanduser() / "Contents" / "Resources"
    for name in ("opencode_setup.py", "opencode_plugin.js"):
        if not (resources / name).is_file():
            raise SystemExit(
                f"{app!r} 内缺少 {name}；请安装完整的 Codex 语音提醒.app，"
                "或用 --app 指定正式的安装路径。")
    return resources


def run_installer(resources, arguments):
    result = subprocess.run(
        [sys.executable, str(resources / "opencode_setup.py"), *arguments],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("应用内安装器执行失败：\n" + (result.stdout or result.stderr or ""))
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {"message": result.stdout.strip()}


def same_file(entry, target):
    expected = target.resolve()
    if entry == expected.as_uri():
        return True
    if not entry.startswith("file://"):
        return False
    try:
        return Path(unquote(urlparse(entry).path)).resolve() == expected
    except OSError:
        return False


def read_json(path):
    try:
        return json.loads(path.read_text())
    except ValueError as error:
        raise SystemExit(
            f"{path} 含注释或无法解析（{error}）。请手工维护其中的全局插件数组：\n"
            f'  "plugins": [\n    "{path.parent / PLUGIN_DIR_REL}".as_uri() 或绝对目录 URI\n  ]')


def backup(path):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.codex-voice-setup-{stamp}.bak")
    shutil.copy2(path, target)
    target.chmod(0o600)
    return target


def write_json(path, data):
    handle = path.with_suffix(path.suffix + ".codex-voice-setup.tmp")
    handle.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    handle.chmod(0o600)
    os.replace(handle, path)


def global_config_path(config_dir):
    path = config_dir / "opencode.json"
    if path.exists():
        return path
    jsonc = config_dir / "opencode.jsonc"
    if jsonc.exists():
        return jsonc
    return path


def update_global_plugins(config_dir, plugin_dir, remove):
    path = global_config_path(config_dir)
    entry = plugin_dir.resolve().as_uri()
    if not path.exists():
        if remove:
            return None
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json(path, {"$schema": "https://opencode.ai/config.json",
                          "plugins": [entry]})
        return {"file": str(path), "added": entry, "backup": None}
    data = read_json(path)
    if not isinstance(data, dict):
        raise SystemExit(f"{path} 的根不是对象，请手工处理全局插件数组。")
    entries = data.get("plugins") or []
    if entries and not isinstance(entries, list):
        raise SystemExit(
            f"{path} 的 plugins 不是数组，请手工核对后处理。")
    if remove:
        kept = [item for item in entries
                if not (isinstance(item, str) and same_file(item, plugin_dir))]
        if kept == entries:
            return None
        data["plugins"] = kept
    else:
        if any(isinstance(item, str) and same_file(item, plugin_dir)
               for item in entries):
            return None
        data["plugins"] = entries + [entry]
    saved = backup(path)
    write_json(path, data)
    return {"file": str(path), "removed": bool(remove), "backup": str(saved) if saved else None}


def server_part(plugin_dir):
    real = None
    link = None
    for name in SERVER_PART_NAMES:
        candidate = plugin_dir / name
        if not candidate.is_file():
            continue
        if candidate.is_symlink():
            link = link or candidate
        else:
            real = real or candidate
    return real or link or None


def update_server_link(plugin_dir, plugin_file, remove):
    link = plugin_dir / "server.js"
    if plugin_dir.is_file() or not plugin_dir.is_dir() or not plugin_file.is_file():
        return None
    if remove:
        if link.is_symlink():
            link.unlink()
            return {"removed": True}
        return None
    existing = server_part(plugin_dir)
    if existing:
        if existing.resolve() == plugin_file.resolve():
            return None  # already this template's part; nothing to do
        return None  # a real server/index part lives here; leave it alone
    link.unlink(missing_ok=True)
    link.symlink_to(plugin_file.name)
    link.chmod(0o644)
    return {"created": str(link)}


def collect_status(config_dir, state_dir, app):
    plugin_dir = config_dir / PLUGIN_DIR_REL
    status = {"opencodeConfigured": False}
    resources = app_resources(app)
    status["app_status"] = run_installer(resources, ["--status",
        "--config-dir", str(config_dir), "--state-dir", str(state_dir),
        "--plugin-source", str(resources / "opencode_plugin.js")])
    status["opencodeConfigured"] = bool(status["app_status"].get("configured"))
    path = global_config_path(config_dir)
    if path.exists():
        try:
            data = read_json(path)
            status["globalRegistered"] = any(
                isinstance(item, str) and same_file(item, plugin_dir)
                for item in (data.get("plugins") or []))
            status["globalPluginsFile"] = str(path)
        except SystemExit:
            status["globalRegistered"] = "未知：全局配置无法解析"
    else:
        status["globalRegistered"] = False
        status["globalPluginsFile"] = None
    status["serverPart"] = str(server_part(plugin_dir) or "") or None
    return status


def main():
    parser = argparse.ArgumentParser(
        description="把 OpenCode 接入 Codex 语音提醒：应用内安装 + 服务端进程注册。")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true", help="只打印连接状态报告")
    modes.add_argument("--remove", action="store_true",
                       help="撤销全局注册与 server.js 软链；应用内注册请用设置对话框移除")
    parser.add_argument("--app", default=DEFAULT_APP, help="Codex 语音提醒.app 路径")
    parser.add_argument("--config-dir", default=None,
                        help="OpenCode 配置目录，默认 OPENCODE_CONFIG_DIR/XDG_CONFIG_HOME 或 ~/.config/opencode")
    parser.add_argument("--state-dir", default=None,
                        help=f"应用状态目录，默认 {STATE_DIR_NOTE}")
    arguments = parser.parse_args()

    config_dir = Path(arguments.config_dir or default_config_dir())
    state_dir = Path(arguments.state_dir or default_state_dir())
    plugin_dir = config_dir / PLUGIN_DIR_REL
    plugin_file = plugin_dir / "tui.js"
    resources = app_resources(arguments.app)
    installer_common = ["--config-dir", str(config_dir), "--state-dir", str(state_dir),
                        "--plugin-source", str(resources / "opencode_plugin.js")]
    report = {}

    if arguments.remove:
        result = update_global_plugins(config_dir, plugin_dir, remove=True)
        if result:
            report["globalPlugins"] = result
        result = update_server_link(plugin_dir, plugin_file, remove=True)
        if result:
            report["serverLink"] = result
        if plugin_file.is_file():
            report["appRemove"] = run_installer(resources, ["--remove", *installer_common])
        report["removed"] = True
    elif arguments.status:
        report["status"] = collect_status(config_dir, state_dir, arguments.app)
    else:
        report["appInstall"] = run_installer(resources, ["--install", *installer_common])
        if not plugin_file.is_file():
            raise SystemExit("安装步骤未生成插件文件；请检查应用版本后重试。")
        result = update_global_plugins(config_dir, plugin_dir, remove=False)
        if result:
            report["globalPlugins"] = result
        result = update_server_link(plugin_dir, plugin_file, remove=False)
        if result:
            report["serverLink"] = result
        report["status"] = collect_status(config_dir, state_dir, arguments.app)
        configured = report["status"]["opencodeConfigured"]
        registered = report["status"]["globalRegistered"] is True
        report["message"] = (
            "OpenCode 服务端事件观察已启用；OpenCode 保存配置时自动热加载，无需重启。"
            if configured and registered else
            "已尽量完成安装，但仍有步骤未确认，请查看 status 字段或按提示手工处理。")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

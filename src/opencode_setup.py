"""Install the OpenCode CLI observer plugin. Never changes OpenCode policy."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
from urllib.parse import unquote, urlparse

MARKER = "codex-voice-opencode-v1"
PLUGIN_REL = Path("plugins") / "codex-voice" / "tui.js"
CONFIG_KEYS = (("cli.json", "plugins"), ("tui.json", "plugin"))


def load(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} 的格式不受支持，请先检查原文件。")
    return data


def entries(data, key):
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{key} 必须是字符串数组，请先检查配置文件。")
    return list(value)


def same_file(entry, target):
    target = target.resolve()
    if entry == target.as_uri():
        return True
    if not entry.startswith("file://"):
        return False
    try:
        return Path(unquote(urlparse(entry).path)).resolve() == target
    except OSError:
        return False


def update_config(path, key, plugin, remove):
    data = load(path)
    if not path.exists() and remove:
        return None
    current = entries(data, key)
    kept = [entry for entry in current if not same_file(entry, plugin)]
    if remove:
        updated = kept
    else:
        updated = kept + [plugin.resolve().as_uri()]
    if updated == current:
        return None
    data[key] = updated
    return data


def backup(path, state_dir):
    if not path.exists():
        return None
    folder = Path(state_dir) / "hook-backups"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = folder / f"{stamp}-{path.name}.backup"
    shutil.copy2(path, target)
    target.chmod(0o600)
    return str(target)


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".codex-voice.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def render_plugin(source, state_dir):
    content = source.read_text()
    placeholder = "__CODEX_VOICE_STATE_DIR__"
    if placeholder not in content:
        raise ValueError("插件模板缺少状态目录占位符，请重新安装完整应用。")
    content = content.replace(placeholder, json.dumps(str(state_dir)))
    if MARKER not in content:
        content = f"// {MARKER}\n" + content
    return content


def status(plugin, config_dir):
    installed = plugin.is_file() and MARKER in plugin.read_text(errors="ignore")
    registered = False
    try:
        cli = load(config_dir / "cli.json")
        registered = any(same_file(entry, plugin) for entry in entries(cli, "plugins"))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {
        "configured": bool(installed and registered),
        "installed": bool(installed),
        "registered": bool(registered),
        "opencodeFound": config_dir.exists(),
        "plugin": str(plugin),
        "message": ("OpenCode 插件已安装；重启 OpenCode 后生效"
                    if installed and registered else
                    "连接后增加审批、提问与完成提醒"),
    }


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ["status", "install", "remove"]:
        modes.add_argument("--" + name, action="store_true")
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--plugin-source", required=True)
    args = parser.parse_args()

    config_dir = Path(args.config_dir).expanduser()
    state_dir = Path(args.state_dir).expanduser()
    plugin = config_dir / PLUGIN_REL
    source = Path(args.plugin_source)

    if args.status:
        print(json.dumps(status(plugin, config_dir), ensure_ascii=False))
        return

    backups = []
    if args.install:
        if not source.is_file():
            raise ValueError("应用内缺少 OpenCode 插件模板，请重新安装完整应用。")
        config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        plugin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        content = render_plugin(source, state_dir)
        temporary = plugin.with_suffix(".js.tmp")
        temporary.write_text(content)
        temporary.chmod(0o600)
        os.replace(temporary, plugin)
        for name, key in CONFIG_KEYS:
            path = config_dir / name
            # tui.json is optional: only keep it in sync when it already exists.
            if name == "tui.json" and not path.exists():
                continue
            data = update_config(path, key, plugin, remove=False)
            if data is not None:
                saved = backup(path, state_dir)
                if saved:
                    backups.append(saved)
                write_json(path, data)
        print(json.dumps({
            "configured": True,
            "opencodeFound": True,
            "plugin": str(plugin),
            "backups": backups,
            "needsReload": True,
            "message": "OpenCode 插件已安装；重启 OpenCode 后生效。已保留其他插件与配置。",
        }, ensure_ascii=False))
        return

    for name, key in CONFIG_KEYS:
        path = config_dir / name
        if not path.exists():
            continue
        data = update_config(path, key, plugin, remove=True)
        if data is not None:
            saved = backup(path, state_dir)
            if saved:
                backups.append(saved)
            write_json(path, data)
    if plugin.exists():
        plugin.unlink()
    try:
        plugin.parent.rmdir()
    except OSError:
        pass
    print(json.dumps({
        "configured": False,
        "removed": True,
        "backups": backups,
        "message": "已移除 OpenCode 插件；其他插件与配置保留。",
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(1)

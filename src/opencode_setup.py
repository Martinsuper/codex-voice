"""Install the OpenCode CLI observer plugin. Never changes OpenCode policy.

One install run sets up everything the reminders need:

1. Render the plugin template into ~/.config/opencode/plugins/codex-voice/
   twice: as `tui.js` (the cli.json/TUI contract) and as `index.js` (the
   server part name OpenCode resolves at a plugin directory root).
2. Register `tui.js` in cli.json (+ an already-existing tui.json), as before,
   so TUI-only hosts keep working.
3. Register the plugin DIRECTORY in the global opencode.json(c) `plugins`
   array: OpenCode 2 loads cli.json plugins as TUI-only parts, so the server
   process — where permission and session events live — only runs the
   plugin through the global array. OpenCode hot-reloads plugins after that
   file changes; no restart is needed.

All edits are idempotent, leave unrelated plugins and settings intact, and
back up every file that already existed (state_dir/hook-backups). Plain-JSON
configs are merged with json round-tripping; files with comments get a
strictly additive line insertion. Anything the script cannot merge safely
produces a precise manual instruction instead of touching the file.
"""
import argparse
import datetime
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

MARKER = "codex-voice-opencode-v1"
# PLUGIN_REL stays the TUI part file (the cli.json contract); the plugin
# directory OpenCode loads as a server part is PLUGIN_DIR_REL.
PLUGIN_REL = Path("plugins") / "codex-voice" / "tui.js"
PLUGIN_DIR_REL = PLUGIN_REL.parent
CONFIG_KEYS = (("cli.json", "plugins"), ("tui.json", "plugin"))
SERVER_FILE = "index.js"
SERVER_PART_ALTERNATIVES = ("server.js", "server.ts", "index.ts")
GLOBAL_NAMES = ("opencode.json", "opencode.jsonc")


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


def plugin_dir(config_dir):
    return config_dir / PLUGIN_DIR_REL


def plugin_file(config_dir):
    return config_dir / PLUGIN_REL


def plugin_uri(config_dir):
    return plugin_dir(config_dir).resolve().as_uri()


def global_config_path(config_dir):
    for name in GLOBAL_NAMES:
        path = config_dir / name
        if path.exists():
            return path
    return config_dir / "opencode.json"


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
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def write_text(path, text):
    temporary = path.with_suffix(path.suffix + ".codex-voice.tmp")
    temporary.write_text(text)
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


def manual_edit_hint(path, uri, action):
    verb = "添加" if action == "install" else "移除"
    return f"{path} 无法自动合并，请手工{verb}（可作为 plugins 数组的一项）：{uri}"


# --- global opencode.json(c) handling -------------------------------------

def _array_span(raw, opener):
    """End index (inclusive) of the array whose '[' is at `opener`."""
    in_string = escape = False
    depth = 0
    for index in range(opener, len(raw)):
        char = raw[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("plugins 数组未闭合")


def _without_comments(text):
    """Strip JSONC comments, leaving string contents (URLs and all) alone."""
    out = []
    in_string = escape = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif char == "/" and text[index:index + 2] == "//":
            while index < len(text) and text[index] != "\n":
                index += 1
            out.append(" ")
            continue
        elif char == "/" and text[index:index + 2] == "/*":
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            out.append(" ")
            continue
        else:
            out.append(char)
        index += 1
    return "".join(out)


def merge_global_jsonc(raw, uri, remove):
    """Comment-preserving edit of the global `plugins` array.

    Returns (text, changed). Raises ValueError when the layout is ambiguous;
    the caller then reports a manual instruction instead of editing."""
    spans = list(re.finditer(r'"plugins"\s*:\s*\[', raw))
    present = f'"{uri}"' in raw
    if len(spans) > 1:
        raise ValueError('全局配置中出现多处 "plugins" 键')
    if len(spans) == 1:
        opener = spans[0].end() - 1
        closing = _array_span(raw, opener)
        span = raw[opener:closing + 1]
        if remove:
            if not present or f'"{uri}"' not in span:
                return raw, False
            inner = span[1:-1]
            stripped = inner
            quoted = re.escape(f'"{uri}"')
            # Remove the entry together with its comma and, when the entry
            # owns one, its trailing same-line comment.
            for pattern in (quoted + r"[ \t]*,[ \t]*//[^\n]*",
                            quoted + r"[ \t]*,",
                            r",\s*" + quoted,
                            quoted):
                candidate = re.sub(pattern, "", inner, count=1)
                if candidate != inner:
                    stripped = candidate
                    break
            stripped = re.sub(r",\s*,", ",", stripped)
            stripped = re.sub(r",\s*\]", "]", stripped)
            return raw[:opener] + "[" + stripped.strip() + "]" + raw[closing + 1:], True
        if present:
            return raw, False
        inner = span[1:-1]
        if not inner.strip():
            return raw[:opener] + f'["{uri}"]' + raw[closing + 1:], True
        tail = inner.split("\n", 1)
        indent = tail[1][:len(tail[1]) - len(tail[1].lstrip())] if len(tail) > 1 else "  "
        entry = f'\n{indent}"{uri}",'
        return raw[:opener + 1] + entry + raw[opener + 1:], True
    # No "plugins" key anywhere.
    if remove or present:
        return raw, False
    brace = raw.find("{")
    if brace < 0:
        raise ValueError("全局配置不是 JSON 对象")
    if re.sub(r"\s+", "", _without_comments(raw)) == "{}":
        return f'{{ "plugins": ["{uri}"] }}', True
    if re.search(r'"plugins"\s*:', _without_comments(raw)):
        # A "plugins" key exists with a non-array value: cannot merge blindly.
        raise ValueError('全局配置的 "plugins" 不是数组')
    return raw[:brace + 1] + f'"plugins": ["{uri}"],' + raw[brace + 1:], True


def update_global(config_dir, state_dir, remove):
    """Add/remove the plugin directory in opencode.json(c) `plugins`.

    Returns {"registered": bool, "file": path} and, when the file could not
    be merged safely, {"error": hint} — `registered` then reflects reality."""
    path = global_config_path(config_dir)
    uri = plugin_uri(config_dir)
    target = plugin_dir(config_dir)
    if not path.exists():
        if remove:
            return {"registered": False, "file": str(path)}
        write_json(path, {"plugins": [uri]})
        return {"registered": True, "file": str(path), "created": True}
    raw = path.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            text, changed = merge_global_jsonc(raw, uri, remove)
        except ValueError as problem:
            return {"registered": not remove and f'"{uri}"' in raw,
                    "file": str(path),
                    "error": f"{problem}；{manual_edit_hint(path, uri, 'install' if not remove else 'remove')}"}
        if changed:
            saved = backup(path, state_dir)
            write_text(path, text)
            result = {"registered": not remove, "file": str(path)}
            if saved:
                result["backup"] = saved
            return result
        return {"registered": not remove and f'"{uri}"' in raw, "file": str(path)}
    if not isinstance(data, dict):
        return {"registered": False, "file": str(path),
                "error": f"{path.name} 的根不是 JSON 对象；{manual_edit_hint(path, uri, 'install' if not remove else 'remove')}"}
    current = data.get("plugins")
    if current is None:
        current = []
    if not isinstance(current, list):
        return {"registered": False, "file": str(path),
                "error": f'{path.name} 的 "plugins" 不是数组；{manual_edit_hint(path, uri, "install" if not remove else "remove")}'}
    kept = [item for item in current
            if not (isinstance(item, str) and same_file(item, target))]
    if remove:
        if kept == current:
            return {"registered": False, "file": str(path)}
        data["plugins"] = kept
    else:
        if any(isinstance(item, str) and same_file(item, target) for item in current):
            return {"registered": True, "file": str(path)}
        data["plugins"] = current + [uri]
    saved = backup(path, state_dir)
    write_json(path, data)
    result = {"registered": not remove, "file": str(path)}
    if saved:
        result["backup"] = saved
    return result


def read_global_registered(config_dir):
    """Read-only check used by --status. True/False; "unknown" when the
    global config exists but cannot be interpreted automatically."""
    path = global_config_path(config_dir)
    if not path.exists():
        return False, str(path)
    raw = path.read_text()
    if f'"{plugin_uri(config_dir)}"' in raw:
        return True, str(path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "unknown", str(path)
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        return "unknown", str(path)
    target = plugin_dir(config_dir)
    registered = any(isinstance(item, str) and same_file(item, target)
                     for item in data["plugins"])
    return registered, str(path)


def status(plugin, config_dir):
    directory = plugin_dir(config_dir)
    valid = lambda path: path.is_file() and MARKER in path.read_text(errors="ignore")  # noqa: E731
    installed = valid(plugin)
    parts = [path for path in server_parts(config_dir) if path.is_symlink() or valid(path)]
    server_ready = bool(parts)
    registered = False
    try:
        cli = load(config_dir / "cli.json")
        registered = any(same_file(entry, plugin) for entry in entries(cli, "plugins"))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    global_registered, global_file = read_global_registered(config_dir)
    report = {
        "configured": bool(installed and registered
                           and global_registered is True and server_ready),
        "installed": installed,
        "registered": registered,
        "globalRegistered": global_registered is True,
        "globalPluginsFile": global_file,
        "serverPart": str(parts[0]) if server_ready else None,
        "opencodeFound": config_dir.exists(),
        "plugin": str(plugin),
        "message": ("OpenCode 插件已安装；保存配置时 OpenCode 自动加载，无需重启"
                    if installed and registered and global_registered is True and server_ready else
                    "连接后增加审批、提问与完成提醒"),
    }
    if global_registered == "unknown":
        report["globalHint"] = manual_edit_hint(global_file, plugin_uri(config_dir), "install")
    return report


# --- install / remove ------------------------------------------------------

def server_parts(config_dir):
    directory = plugin_dir(config_dir)
    parts = [directory / SERVER_FILE]
    parts += [directory / name for name in SERVER_PART_ALTERNATIVES]
    return parts


def installed_files(config_dir):
    directory = plugin_dir(config_dir)
    files = [directory / "tui.js", directory / SERVER_FILE]
    # Fallback-script server.js symlinks are ours; real manual files are not.
    files += [directory / name for name in SERVER_PART_ALTERNATIVES
              if (directory / name).is_symlink()]
    return files


def install_plugin(config_dir, state_dir, source):
    content = render_plugin(source, state_dir)
    directory = plugin_dir(config_dir)
    plugin = directory / "tui.js"
    temporary = plugin.with_suffix(".js.tmp")
    temporary.write_text(content)
    temporary.chmod(0o600)
    os.replace(temporary, plugin)
    server = directory / SERVER_FILE
    if not server.is_file() and not server.is_symlink():
        # Respect a manually maintained server part; otherwise ship ours.
        if not any((directory / name).is_file() for name in SERVER_PART_ALTERNATIVES):
            write_text(server, content)
    backups = []
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
    return backups


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
    plugin = plugin_file(config_dir)
    source = Path(args.plugin_source)

    if args.status:
        print(json.dumps(status(plugin, config_dir), ensure_ascii=False))
        return

    if args.install:
        if not source.is_file():
            raise ValueError("应用内缺少 OpenCode 插件模板，请重新安装完整应用。")
        config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        plugin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        backups = install_plugin(config_dir, state_dir, source)
        report = update_global(config_dir, state_dir, remove=False)
        installed = (plugin.is_file() and MARKER in plugin.read_text(errors="ignore"))
        registered = False
        try:
            cli = load(config_dir / "cli.json")
            registered = any(same_file(entry, plugin) for entry in entries(cli, "plugins"))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        configured = bool(installed and registered and report["registered"] is True)
        if report["registered"] is True:
            message = "OpenCode 插件已安装；保存配置时 OpenCode 自动加载，无需重启。已保留其他插件与配置。"
        else:
            message = ("应用内插件已安装，但全局 opencode 配置未能自动合并，需要手工处理。"
                       + report.get("error", ""))
        result = {
            "configured": configured,
            "opencodeFound": True,
            "plugin": str(plugin),
            "backups": backups,
            "needsReload": True,
            "globalRegistered": report["registered"] is True,
            "globalPluginsFile": report["file"],
            "message": message,
        }
        if "error" in report:
            result["globalError"] = report["error"]
        print(json.dumps(result, ensure_ascii=False))
        return

    backups = []
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
    report = update_global(config_dir, state_dir, remove=True)
    for target in installed_files(config_dir):
        if target.is_file() or target.is_symlink():
            target.unlink()
    try:
        plugin.parent.rmdir()
    except OSError:
        pass
    message = "已移除 OpenCode 插件；其他插件与配置保留。"
    if report.get("error"):
        message = "已移除应用侧注册；全局 opencode 配置需手工处理：" + report["error"]
    print(json.dumps({
        "configured": False,
        "removed": True,
        "backups": backups,
        "globalRegistered": report["registered"] is True,
        "globalPluginsFile": report["file"],
        "message": message,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

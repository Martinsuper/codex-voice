"""Register observational hooks. Never changes hook trust or approval policy."""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import shlex

MARKER = "codex-voice-observer-v1"
EVENTS = {"PreToolUse":"request_user_input", "PermissionRequest":".*", "PostToolUse":".*", "UserPromptSubmit":None, "Interrupt":None}


def owned(command):
    try:
        parts = shlex.split(command)
    except (ValueError, TypeError):
        return False
    if not parts or not parts[0].endswith("/Contents/MacOS/CodexVoice") or "--hook" not in parts:
        return False
    try:
        index = parts.index("--observer-id")
        return index + 1 < len(parts) and parts[index + 1] == MARKER
    except ValueError:
        return False


def legacy(command):
    try:
        parts = shlex.split(command)
        script = next(Path(p) for p in parts if p.endswith("/Contents/Resources/voice_bridge.py"))
        info = plistlib.loads((script.parent.parent/"Info.plist").read_bytes())
        return info.get("CFBundleIdentifier") == "local.rico.CodexVoice" and "hook" in parts
    except (ValueError, TypeError, StopIteration, OSError, plistlib.InvalidFileException):
        return False


def count_hooks(data):
    return sum(1 for event, groups in data.get("hooks", {}).items() if event in EVENTS for group in groups for hook in group.get("hooks", []) if owned(hook.get("command", "")) or legacy(hook.get("command", "")))


def configured(data):
    return all(any(owned(hook.get("command", "")) or legacy(hook.get("command", "")) for group in data.get("hooks", {}).get(event, []) for hook in group.get("hooks", [])) for event in EVENTS)


def update_hooks(data, app, remove=False):
    # Preserve unrelated hooks and every setting outside this file.
    hooks = data.setdefault("hooks", {})
    for event, groups in list(hooks.items()):
        kept = []
        for group in groups:
            handlers = [hook for hook in group.get("hooks", []) if not owned(hook.get("command", "")) and not legacy(hook.get("command", ""))]
            if handlers:
                kept.append(dict(group, hooks=handlers))
        hooks[event] = kept
    if not remove:
        command = shlex.join([str(Path(app)/"Contents/MacOS/CodexVoice"), "--hook", "--observer-id", MARKER])
        for event, matcher in EVENTS.items():
            group = {"hooks":[{"type":"command", "command":command, "timeout":3}]}
            if matcher is not None:
                group["matcher"] = matcher
            hooks.setdefault(event, []).append(group)
    data["hooks"] = {event: groups for event, groups in hooks.items() if groups}
    return data


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ["status", "install", "remove"]:
        modes.add_argument("--" + name, action="store_true")
    parser.add_argument("--app", required=True)
    parser.add_argument("--codex-dir", required=True)
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()
    codex = Path(args.codex_dir); target = codex/"hooks.json"
    data = json.loads(target.read_text()) if target.exists() else {"hooks":{}}
    if not isinstance(data.get("hooks", {}), dict):
        raise ValueError("hooks.json 的格式不受支持，请先检查原文件。")
    if args.install or args.remove:
        executable = Path(args.app)/"Contents/MacOS/CodexVoice"
        if args.install and not executable.is_file():
            raise ValueError("请先将完整应用放入应用程序文件夹。")
        original = json.dumps(data, sort_keys=True)
        data = update_hooks(data, args.app, args.remove)
        if original != json.dumps(data, sort_keys=True):
            codex.mkdir(parents=True, exist_ok=True, mode=0o700)
            if target.exists():
                backups = Path(args.state_dir)/"hook-backups";backups.mkdir(parents=True, exist_ok=True, mode=0o700)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                backup = backups/(stamp+"-hooks.json");backup.write_bytes(target.read_bytes());backup.chmod(0o600)
            temporary = target.with_suffix(".codex-voice.tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n");temporary.chmod(0o600)
            os.replace(temporary, target)
    print(json.dumps({"configured":configured(data),"count":count_hooks(data),"codexFound":codex.exists(),"needsReview":bool(args.install),"message":"已安装5个观察器；请在Codex的 /hooks 中逐项检查并信任。" if args.install else ""}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error":str(error)}, ensure_ascii=False))
        raise SystemExit(1)

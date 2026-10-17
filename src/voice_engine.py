#!/usr/bin/env python3
"""Local Codex voice reminders. No network, no approval decisions, no model calls."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

INTERVALS = (30, 60, 180)
KINDS = {"approval": "等待审批", "question": "等待回答", "result": "已有结果", "blocked": "需要关注", "test": "播报测试"}
VERSION = "0.5.0-beta.1"


def clean_label(value, fallback="当前任务"):
    value = re.sub(r"[\x00-\x1f<>]", "", str(value or "")).strip()
    # Keep private commands, URLs, and long text out of spoken labels.
    if not value or "http" in value or "/Users/" in value:
        return fallback
    return value[:24]


class Speaker:
    def __init__(self, audio_device="", device_provider=None, device_uid=""):
        self.process = None
        self.alert_id = None
        self.audio_device = audio_device
        self.audio_device_uid = device_uid
        self.current_name = audio_device or "Mac 当前默认输出"
        self.device_id = None
        self.output_devices = []
        self.default_name = ""
        self.device_provider = device_provider
        self.available = not bool(audio_device)
        self.muted = False
        self.volume = None
        self.next_device_check = 0
        self.last_error = ""

    def refresh_audio(self):
        if time.monotonic() < self.next_device_check:
            return
        self.next_device_check = time.monotonic() + 4
        try:
            if self.device_provider:
                provided = self.device_provider()
                if isinstance(provided, dict):
                    info = provided
                else:
                    info = {"connected": not self.audio_device or self.audio_device in provided, "name": self.audio_device, "muted": self.muted, "volume": self.volume, "devices": [{"name": name, "uid": "name:" + name, "connected": True} for name in provided]}
            else:
                helper = Path(__file__).resolve().parent / "AudioDeviceInfo"
                if helper.is_file():
                    args = [str(helper), self.audio_device]
                    if self.audio_device_uid:
                        args += ["--uid", self.audio_device_uid]
                    result = subprocess.run(args, capture_output=True, text=True, timeout=2, check=True)
                    info = json.loads(result.stdout)
                else:
                    result = subprocess.run(["/usr/bin/say", "-a", "?"], capture_output=True, text=True, timeout=2)
                    names = [m.group(1).strip() for line in result.stdout.splitlines() if (m := re.match(r"\s*\d+\s+(.+)", line))]
                    info = {"connected": not self.audio_device_uid and (not self.audio_device or self.audio_device in names), "name": self.audio_device, "devices": [{"name": name, "uid": "name:" + name, "connected": True} for name in names]}
            self.available = bool(info.get("connected"))
            self.current_name = info.get("name") or self.audio_device or "Mac 当前默认输出"
            self.device_id = info.get("id")
            self.output_devices = info.get("devices", [])
            self.default_name = info.get("defaultName", "")
            self.muted = bool(info.get("muted", False))
            self.volume = info.get("volume")
            self.last_error = "" if self.available else "所选扬声器未连接，已暂停播报"
            if self.available and self.muted:
                self.last_error = "所选扬声器处于静音，已暂停播报"
            elif self.available and self.volume == 0:
                self.last_error = "所选扬声器音量为零，已暂停播报"
            if self.last_error:
                self.stop()
        except (OSError, ValueError, subprocess.SubprocessError):
            self.available = False
            self.last_error = "无法读取扬声器状态，已暂停播报"
            self.stop()

    def set_device(self, name, uid=""):
        if not isinstance(name, str) or not isinstance(uid, str) or len(name) > 256 or len(uid) > 1024 or re.search(r"[\x00-\x1f]", name + uid):
            return False
        if name == self.audio_device and uid == self.audio_device_uid:
            return False
        self.stop()
        self.audio_device = name
        self.audio_device_uid = uid
        self.current_name = name or "Mac 当前默认输出"
        self.device_id = None
        self.muted = False
        self.volume = None
        self.next_device_check = 0
        self.refresh_audio()
        return True

    def audio_status(self):
        self.refresh_audio()
        return {"device": self.current_name, "selectedDevice": self.audio_device, "selectedUID": self.audio_device_uid, "followSystem": not bool(self.audio_device or self.audio_device_uid), "devices": self.output_devices, "defaultName": self.default_name, "available": self.available, "ready": self.available and not self.muted and self.volume != 0, "muted": self.muted, "volume": self.volume, "error": self.last_error}

    def busy(self):
        return self.process is not None and self.process.poll() is None

    def speak(self, alert_id, text):
        if self.busy():
            return False
        self.next_device_check = 0
        self.refresh_audio()
        if not self.available or self.muted or self.volume == 0:
            return False
        args = ["/usr/bin/say", "-v", "Tingting", "-r", "185"]
        if self.audio_device or self.audio_device_uid:
            args += ["-a", str(self.device_id) if self.device_id is not None else self.audio_device]
        self.process = subprocess.Popen(args + [text], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.alert_id = alert_id
        return True

    def stop(self, alert_id=None):
        if alert_id is None or self.alert_id == alert_id:
            if self.busy():
                self.process.terminate()
            self.alert_id = None


class Engine:
    def __init__(self, speaker, now=time.time, enabled=True):
        self.speaker = speaker
        self.now = now
        self.enabled = enabled
        self.alerts = {}
        self.seen = collections.OrderedDict()
        self.muted_until = 0.0
        self.last_spoken = 0.0
        self.monitor = {"state": "starting", "detail": "正在连接本地事件", "files": 0, "lastEventAt": None, "hookLastSeen": None}
        self.history = collections.deque(maxlen=40)

    def remember(self, key):
        if key in self.seen:
            return False
        self.seen[key] = self.now()
        while len(self.seen) > 5000:
            self.seen.popitem(last=False)
        return True

    def add(self, event):
        key = str(event.get("id") or uuid.uuid4())
        if not self.remember(key):
            return
        if not self.enabled:
            return
        kind = event.get("kind", "result")
        if kind not in KINDS:
            return
        created = self.now()
        # A new result supersedes older results for this chat only.
        if kind == "result":
            self.resolve_thread(str(event.get("thread", "")), kinds={"result"}, reason="已有更新结果")
        self.alerts[key] = {"id": key, "thread": str(event.get("thread", "")), "turn": str(event.get("turn", "")), "kind": kind, "title": clean_label(event.get("title")), "detail": str(event.get("detail", KINDS[kind]))[:150], "createdAt": created, "nextAt": created + max(0, float(event.get("delay", 0))), "count": 0, "state": "pending", "test": bool(event.get("test", False)), "requestId": str(event.get("requestId", "")), "source": str(event.get("source", "manual"))}
        self.history.append({"at": created, "action": "added", "id": key, "kind": kind})

    def resolve(self, key, reason="已处理"):
        alert = self.alerts.get(key)
        if alert:
            self.speaker.stop(key)
            del self.alerts[key]
            self.history.append({"at": self.now(), "action": reason, "id": key})

    def resolve_thread(self, thread, kinds=None, reason="任务已继续", turn=None):
        if not thread:
            return
        for key, alert in list(self.alerts.items()):
            if alert["thread"] == thread and (kinds is None or alert["kind"] in kinds) and (turn is None or not alert["turn"] or alert["turn"] == turn):
                self.resolve(key, reason)

    def event(self, event):
        action = event.get("action", "add")
        if action == "add":
            self.add(event)
        elif action in ("ack", "resolve"):
            self.resolve(event.get("id"), "已接手" if action == "ack" else "已处理")
        elif action == "resolve_thread":
            self.resolve_thread(event.get("thread"), set(event["kinds"]) if event.get("kinds") else None, event.get("reason", "任务已继续"), event.get("turn"))
        elif action == "resolve_request":
            for key, alert in list(self.alerts.items()):
                if alert["thread"] == event.get("thread") and alert["requestId"] == event.get("requestId"):
                    self.resolve(key)
        elif action == "snooze":
            alert = self.alerts.get(event.get("id"))
            if alert:
                self.speaker.stop(alert["id"])
                alert["nextAt"] = self.now() + max(5, min(3600, float(event.get("seconds", 300))))
                alert["state"] = "snoozed"
        elif action == "replay":
            alert = self.alerts.get(event.get("id"))
            if alert and self.enabled:
                self.speaker.stop(alert["id"])
                alert["nextAt"] = self.now()
                alert["state"] = "pending"
        elif action == "mute":
            self.muted_until = self.now() + float(event.get("seconds", 900))
            self.speaker.stop()
        elif action == "unmute":
            self.muted_until = 0
        elif action == "ack_all":
            for key in list(self.alerts):
                self.resolve(key, "全部已接手")
        elif action == "test":
            key = "test-" + str(uuid.uuid4())
            self.add({"id": key, "thread": key, "kind": "test", "title": "语音提醒测试", "detail": "测试每隔 5、10、15 秒重复；点“已接手”应立即停止。", "test": True})
        elif action == "clear_tests":
            for key, alert in list(self.alerts.items()):
                if alert["test"]:
                    self.resolve(key, "测试已结束")
        elif action == "set_enabled":
            self.enabled = bool(event.get("enabled", True))
            if self.enabled:
                self.muted_until = 0
            if not self.enabled:
                self.speaker.stop()
                for key in list(self.alerts):
                    self.resolve(key, "提醒已关闭")
            self.history.append({"at": self.now(), "action": "enabled" if self.enabled else "disabled"})
        elif action == "set_audio_device":
            interrupted = self.speaker.alert_id if self.speaker.busy() else None
            if self.speaker.set_device(event.get("device", ""), event.get("uid", "")):
                if interrupted in self.alerts:
                    self.alerts[interrupted]["nextAt"] = self.now()
                self.history.append({"at": self.now(), "action": "audio_device_changed", "device": self.speaker.audio_device or "跟随系统输出"})
        elif action == "refresh_audio":
            self.speaker.next_device_check = 0
            self.speaker.refresh_audio()

    def tick(self):
        now = self.now()
        if not self.enabled or now < self.muted_until or self.speaker.busy() or now - self.last_spoken < 1.5:
            return
        due = [a for a in self.alerts.values() if a["nextAt"] <= now]
        due.sort(key=lambda a: (0 if a["kind"] in ("approval", "question", "blocked") else 1, a["nextAt"], a["createdAt"]))
        if not due:
            return
        alert = due[0]
        phrase = {"approval": "需要你审批", "question": "有问题需要你回答", "result": "已有结果，请查看", "blocked": "需要你关注", "test": "请点已接手，测试停止播报"}[alert["kind"]]
        text = "老板，" + alert["title"] + "，" + phrase + "。"
        if self.speaker.speak(alert["id"], text):
            schedule = (5, 10, 15) if alert["test"] else INTERVALS
            alert["nextAt"] = now + schedule[min(alert["count"], len(schedule) - 1)]
            alert["count"] += 1
            alert["state"] = "pending"
            self.last_spoken = now
            self.history.append({"at": now, "action": "spoken", "id": alert["id"], "count": alert["count"]})

    def snapshot(self):
        audio = self.speaker.audio_status() if hasattr(self.speaker, "audio_status") else {}
        return {"version": VERSION, "at": self.now(), "enabled": self.enabled, "mutedUntil": self.muted_until, "speakingId": self.speaker.alert_id if self.speaker.busy() else None, "audio": audio, "alerts": sorted(self.alerts.values(), key=lambda a: a["createdAt"], reverse=True), "monitor": self.monitor, "history": list(self.history)}


class RolloutAdapter:
    """Compatibility adapter for current local JSONL records; ignores reasoning."""
    def __init__(self, engine, codex_dir):
        self.engine, self.codex_dir = engine, Path(codex_dir)
        self.positions = {}
        self.threads = {}
        self.last_scan = 0
        self.calls = {}
        self.started_at = engine.now()

    def metadata(self, thread):
        item = self.threads.get(thread)
        if item:
            return item
        return {"title": "当前任务", "cwd": ""}

    def title(self, thread):
        return clean_label(self.metadata(thread).get("title"))

    def discover(self):
        now = self.engine.now()
        if now - self.last_scan < 3:
            return
        self.last_scan = now
        try:
            candidates = list(self.codex_dir.glob("state_*.sqlite"))
            db = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else self.codex_dir / "state_5.sqlite"
            connection = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=.2)
            columns = {row[1] for row in connection.execute("pragma table_info(threads)")}
            title = "coalesce(name,title)" if {"name", "title"} <= columns else "title" if "title" in columns else "'当前任务'"
            source = "source" if "source" in columns else "''"
            rows = connection.execute(f"select id,rollout_path,{title},cwd,{source} from threads where archived=0 and updated_at>=? order by updated_at desc limit 200", (int(now) - 3 * 86400,)).fetchall()
            connection.close()
            for thread, path, title, cwd, source in rows:
                if "subagent" in str(source).lower():
                    continue
                self.threads[thread] = {"title": title, "cwd": cwd, "path": path}
                file = Path(path)
                if file.suffix == ".jsonl" and file.is_file() and path not in self.positions:
                    # Never replay old results when the app starts.
                    stat = file.stat()
                    offset = stat.st_size if stat.st_mtime < self.started_at else 0
                    if not offset and getattr(stat, "st_birthtime", self.started_at) < self.started_at:
                        offset = max(0, stat.st_size - 1048576)
                    self.positions[path] = {"offset": offset, "thread": thread, "turn": "", "question": False}
            self.engine.monitor.update(state="connected", detail="本地事件记录已连接", files=len(self.positions))
        except (sqlite3.Error, OSError, ValueError):
            self.engine.monitor.update(state="unavailable", detail="本地事件暂不可用；手动确认仍可使用")

    def poll(self):
        self.discover()
        for path, cursor in list(self.positions.items()):
            try:
                file = Path(path)
                if file.stat().st_size < cursor["offset"]:
                    cursor["offset"] = 0
                with file.open("rb") as stream:
                    stream.seek(cursor["offset"])
                    for _ in range(500):
                        line = stream.readline()
                        if not line or not line.endswith(b"\n"):
                            break
                        cursor["offset"] = stream.tell()
                        try:
                            record = json.loads(line)
                        except (ValueError, UnicodeError):
                            continue
                        self.record(record, cursor)
            except OSError:
                continue

    def record(self, record, cursor):
        # An old chat may become active in a different project long after this
        # app started. Its existing history must never be replayed as new work.
        stamp = record.get("timestamp")
        if isinstance(stamp, str):
            try:
                if dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() < self.started_at:
                    return
            except ValueError:
                pass
        thread = cursor["thread"]
        payload = record.get("payload") or {}
        kind = record.get("type")
        if kind == "event_msg":
            event = payload.get("type")
            if event in {"task_started", "task_complete", "turn_aborted"}:
                self.engine.monitor["lastEventAt"] = self.engine.now()
            if event == "task_started":
                cursor["turn"] = payload.get("turn_id", "")
                cursor["question"] = False
                # Only a real composer turn acknowledges prior reminders.
                trigger = (payload.get("turn_attribution") or {}).get("turn_trigger")
                if trigger == "composer":
                    self.engine.resolve_thread(thread, reason="你已在此聊天继续操作")
            elif event == "task_complete":
                turn = payload.get("turn_id", cursor["turn"])
                self.engine.resolve_thread(thread, {"approval"}, turn=turn)
                if not cursor["question"]:
                    self.engine.add({"id": "result:" + thread + ":" + turn, "thread": thread, "turn": turn, "title": self.title(thread), "kind": "result", "source": "local-events"})
            elif event == "turn_aborted":
                self.engine.resolve_thread(thread, reason="本轮已取消", turn=cursor["turn"])
            return
        if kind != "response_item":
            return
        if payload.get("type") == "message" and payload.get("role") == "user":
            text = "\n".join(item.get("text", "") for item in payload.get("content", []) if isinstance(item, dict))
            match = re.search(r"<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>", text, re.S)
            if match:
                try:
                    for reply in json.loads(match.group(1)):
                        reference = json.loads(reply["questionItemId"])
                        self.engine.event({"action": "resolve_request", "thread": thread, "requestId": reference[1]})
                    cursor["question"] = any(a["thread"] == thread and a["kind"] == "question" for a in self.engine.alerts.values())
                    self.engine.monitor["lastEventAt"] = self.engine.now()
                except (ValueError, KeyError, IndexError, TypeError):
                    pass
            return
        # Structured question calls work for direct tool calls. Code-mode calls
        # are covered by the hook bridge, not by evaluating arbitrary JavaScript.
        if payload.get("type") == "function_call":
            name = str(payload.get("name", ""))
            if "request_user_input" in name:
                call = payload.get("call_id", "")
                self.calls[call] = (thread, cursor["turn"])
                cursor["question"] = True
                self.engine.add({"id": "question:" + thread + ":" + call, "thread": thread, "turn": cursor["turn"], "requestId": call, "title": self.title(thread), "kind": "question", "source": "local-events"})
        elif payload.get("type") == "function_call_output" and payload.get("call_id") in self.calls:
            # Async question tools returning immediately are NOT an answer.
            pass


def handle_hook(raw, engine, adapter):
    name = raw.get("hook_event_name", "")
    thread = str(raw.get("session_id", ""))
    turn = str(raw.get("turn_id", ""))
    request = str(raw.get("tool_use_id", ""))
    tool = str(raw.get("tool_name", ""))
    engine.monitor["hookLastSeen"] = engine.now()
    if name == "PreToolUse" and "request_user_input" in tool:
        engine.add({"id": "question:" + thread + ":" + request, "thread": thread, "turn": turn, "requestId": request, "kind": "question", "title": adapter.title(thread), "source": "hook"})
    elif name == "PostToolUse" and "request_user_input" in tool and "async" not in tool:
        engine.event({"action": "resolve_request", "thread": thread, "requestId": request})
    elif name == "UserPromptSubmit":
        engine.resolve_thread(thread, reason="你已在此聊天回复")
    elif name == "Interrupt":
        engine.resolve_thread(thread, reason="本轮已取消", turn=turn)
    elif name == "PermissionRequest":
        # A permission hook does not prove a human is waiting: auto review can
        # handle it. Enable only on hosts explicitly using the user reviewer.
        if raw.get("voice_reviewer") == "user":
            title = raw.get("project_title") or adapter.title(thread)
            engine.add({"id": "approval:" + thread + ":" + request, "thread": thread, "turn": turn, "requestId": request, "title": title, "kind": "approval", "delay": 1, "source": "hook"})
    elif name == "PostToolUse" and request and "request_user_input" not in tool:
        engine.event({"action": "resolve_request", "thread": thread, "requestId": request})


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def save_preferences(path, settings, engine):
    settings.update(enabled=engine.enabled, audio_device=engine.speaker.audio_device, audio_device_uid=engine.speaker.audio_device_uid)
    atomic_json(path, settings)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--codex-dir", default=str(Path.home() / ".codex"))
    args = parser.parse_args()
    state_dir = Path(args.state_dir)
    inbox = state_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    import fcntl
    lock = (state_dir / "engine.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"error": "语音提醒已经在运行"}), flush=True)
        return 1
    try:
        settings = json.loads((state_dir / "settings.json").read_text())
    except (OSError, ValueError):
        settings = {}
    engine = Engine(Speaker(str(settings.get("audio_device", "")), device_uid=str(settings.get("audio_device_uid", ""))), enabled=bool(settings.get("enabled", True)))
    adapter = RolloutAdapter(engine, args.codex_dir)
    commands = queue.Queue()

    def read_commands():
        for line in sys.stdin:
            try:
                commands.put(json.loads(line))
            except ValueError:
                pass
        commands.put({"action": "quit"})

    threading.Thread(target=read_commands, daemon=True).start()
    previous = ""
    last_emit = 0
    def dispatch(event):
        engine.event(event)
        if event.get("action") in ("set_enabled", "set_audio_device"):
            save_preferences(state_dir / "settings.json", settings, engine)
    try:
        while True:
            while not commands.empty():
                command = commands.get()
                if command.get("action") == "quit":
                    return 0
                dispatch(command)
            for event_file in sorted(inbox.glob("*.json"))[:100]:
                try:
                    event = json.loads(event_file.read_text())
                    # Stale spool entries from an old run must not start shouting.
                    if adapter.started_at <= float(event.get("sentAt", 0)) <= time.time() + 5:
                        if event.get("action") == "hook":
                            handle_hook(event.get("event", {}), engine, adapter)
                        else:
                            dispatch(event)
                    event_file.unlink()
                except (OSError, ValueError, TypeError):
                    try:
                        event_file.unlink()
                    except OSError:
                        pass
            adapter.poll()
            engine.tick()
            snapshot = engine.snapshot()
            marker = json.dumps({k:v for k,v in snapshot.items() if k != "at"}, ensure_ascii=False)
            if marker != previous or time.time() - last_emit > 2:
                atomic_json(state_dir / "status.json", snapshot)
                print(json.dumps(snapshot, ensure_ascii=False), flush=True)
                previous, last_emit = marker, time.time()
            time.sleep(.2)
    finally:
        engine.speaker.stop()


if __name__ == "__main__":
    raise SystemExit(main())

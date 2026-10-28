"""Read Codex local rollout events and translate them for the reminder engine."""

import datetime as dt
import json
from pathlib import Path
import re
import sqlite3


def clean_label(value, fallback="当前任务"):
    value = re.sub(r"[\x00-\x1f<>]", "", str(value or "")).strip()
    # Keep private commands, URLs, and long text out of spoken labels.
    if not value or "http" in value or "/Users/" in value:
        return fallback
    return value[:24]


class RolloutAdapter:
    """Compatibility adapter for current local JSONL records; ignores reasoning."""
    def __init__(self, engine, codex_dir):
        self.engine, self.codex_dir = engine, Path(codex_dir)
        self.positions = {}
        self.threads = {}
        self.last_scan = 0
        self.calls = {}
        self.started_at = engine.now()
        self.recovery_floor = None
        self.restore_since = None
        self.recovery_db_ready = False
        self.recovery_live_threads = set()
        self.reconcile_until = 0

    def begin_reconcile(self):
        self.recovery_db_ready = False
        self.last_scan = 0
        self.recovery_floor = max(self.started_at, self.engine.now() - 86400)
        self.reconcile_until = self.engine.now() + 15
        for cursor in self.positions.values():
            self.engine.verifying_threads.add(cursor["thread"])
        for alert in self.engine.alerts.values():
            if alert["thread"] and alert["source"] != "manual":
                alert["recoveryPending"] = True
        self.engine.recovery.update(state="checking", detail="正在同步唤醒后的任务状态")

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
            pending = {a["thread"] for a in self.engine.alerts.values() if a.get("recoveryPending")}
            checking = list((self.engine.verifying_threads | pending))[:500]
            self.recovery_live_threads = set()
            if checking:
                recovered = connection.execute("select id,archived,rollout_path from threads where id in (" + ",".join("?" for _ in checking) + ")", checking).fetchall()
                found = {row[0] for row in recovered}
                for thread, archived, path in recovered:
                    if archived:
                        self.engine.resolve_thread(thread, reason="聊天已归档")
                        self.engine.verifying_threads.discard(thread)
                    else:
                        self.recovery_live_threads.add(thread)
                        if thread in pending and path and path not in self.positions:
                            file = Path(path)
                            if file.suffix == ".jsonl" and file.is_file():
                                self.positions[path] = {"offset": max(0, file.stat().st_size - 1048576), "thread": thread, "turn": "", "question": False, "since": self.restore_since or self.started_at}
                                self.engine.verifying_threads.add(thread)
                for thread in set(checking) - found:
                    self.engine.resolve_thread(thread, reason="聊天已不可用")
                    self.engine.verifying_threads.discard(thread)
            self.recovery_db_ready = True
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
                    if self.recovery_floor is not None:
                        offset = stat.st_size if stat.st_mtime < self.recovery_floor else max(0, stat.st_size - 1048576)
                    if not offset and getattr(stat, "st_birthtime", self.started_at) < self.started_at:
                        offset = max(0, stat.st_size - 1048576)
                    self.positions[path] = {"offset": offset, "thread": thread, "turn": "", "question": False}
                    if self.recovery_floor is not None:
                        self.positions[path]["since"] = self.recovery_floor
                        self.engine.verifying_threads.add(thread)
                self.recovery_live_threads.add(thread)
            self.engine.monitor.update(state="connected", detail="本地事件记录已连接", files=len(self.positions))
        except (sqlite3.Error, OSError, ValueError):
            # A machine running only OpenCode never has a Codex state database;
            # once its plugin has delivered an event, keep reporting connected.
            if self.engine.monitor.get("agentLastSeen") is not None:
                self.engine.monitor.update(state="connected", detail="OpenCode 插件已连接；Codex 本地事件暂不可用")
            else:
                self.engine.monitor.update(state="unavailable", detail="本地事件暂不可用；手动确认仍可使用")

    def poll(self):
        self.discover()
        for path, cursor in list(self.positions.items()):
            try:
                file = Path(path)
                if file.stat().st_size < cursor["offset"]:
                    cursor["offset"] = 0
                    cursor["truncated"] = True
                    cursor["since"] = self.engine.now()
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
                if (self.recovery_db_ready and cursor["thread"] in self.recovery_live_threads
                        and not cursor.get("truncated") and cursor["offset"] >= file.stat().st_size):
                    self.engine.verifying_threads.discard(cursor["thread"])
                    for alert in self.engine.alerts.values():
                        if alert["thread"] == cursor["thread"]:
                            alert["recoveryPending"] = False
            except OSError:
                continue
        pending = sum(bool(a.get("recoveryPending")) for a in self.engine.alerts.values())
        if not self.engine.verifying_threads or self.engine.now() >= self.reconcile_until:
            self.recovery_floor = None
        checking = bool(self.engine.verifying_threads and self.engine.now() < self.reconcile_until)
        self.engine.recovery.update(state="checking" if checking else "partial" if pending else "ready",
                                    unverified=pending, detail="正在核对任务事件" if checking else "部分事项待核验，暂不自动播报" if pending else "事项状态已同步")

    def record(self, record, cursor):
        # An old chat may become active in a different project long after this
        # app started. Its existing history must never be replayed as new work.
        stamp = record.get("timestamp")
        if isinstance(stamp, str):
            try:
                if dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() < cursor.get("since", self.started_at):
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
                self.engine.activity[thread] = {"title": self.title(thread), "thread": thread}
                cursor["turn"] = payload.get("turn_id", "")
                cursor["question"] = False
                # Only a real composer turn acknowledges prior reminders.
                trigger = (payload.get("turn_attribution") or {}).get("turn_trigger")
                if trigger == "composer":
                    cursor.pop("truncated", None)
                    self.engine.resolve_thread(thread, reason="你已在此聊天继续操作")
            elif event == "task_complete":
                self.engine.activity.pop(thread, None)
                turn = payload.get("turn_id", cursor["turn"])
                self.engine.resolve_thread(thread, {"approval"}, turn=turn)
                if not cursor["question"]:
                    self.engine.add({"id": "result:" + thread + ":" + turn, "thread": thread, "turn": turn, "title": self.title(thread), "kind": "result", "source": "local-events"})
            elif event == "turn_aborted":
                self.engine.activity.pop(thread, None)
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



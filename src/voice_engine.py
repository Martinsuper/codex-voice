#!/usr/bin/env python3
"""Local voice reminders with optional official account-quota reads; no model calls."""
from __future__ import annotations

import collections
import hashlib
import json
import math
import os
import time
import uuid

from speech_settings import SpeechSettings
from reminder_rules import KindRule, QuietHours, load_rules, update_rules
from passport_output import PASSPORT_UID
from speaker import ComputerSpeaker, Speaker
from rollout_adapter import RolloutAdapter, clean_label
from event_adapters import handle_agent, handle_hook

INTERVALS = (30, 60, 180)
PREVIEW_ID = "speech-preview"
USAGE_RESET_ID = "usage-reset:"
USAGE_RESET_PREVIEW_ID = USAGE_RESET_ID + "preview"
USAGE_LOW_ID = "usage-low:"
USAGE_LOW_PREVIEW_ID = USAGE_LOW_ID + "preview"
DEFAULT_PAUSE_MINUTES = 15
KINDS = {"approval": "等待审批", "question": "等待回答", "result": "已有结果", "blocked": "需要关注", "test": "播报测试"}
VERSION = "0.9.1-beta.1"


class Engine:
    def __init__(self, speaker, now=time.time, enabled=True, speech_settings=None, pause_minutes=DEFAULT_PAUSE_MINUTES, usage_reset_enabled=True, usage_low_enabled=True, usage_low_threshold=20, reminder_rules=None, quiet_hours=None):
        self.passport_error = ""
        self.output_error = ""
        self.speaker = speaker
        self.now = now
        self.enabled = enabled
        self.alerts = {}
        self.seen = collections.OrderedDict()
        self.muted_until = 0.0
        self.last_spoken = 0.0
        self.monitor = {"state": "starting", "detail": "正在连接本地事件", "files": 0, "lastEventAt": None, "hookLastSeen": None, "agentLastSeen": None}
        self.history = collections.deque(maxlen=40)
        self.speech = SpeechSettings.load(speech_settings)
        self.speaker.speech = self.speech
        self.settings_error = ""
        self.preview_error = ""
        try:
            self.pause_minutes = self.valid_pause_minutes(pause_minutes)
        except ValueError:
            self.pause_minutes = DEFAULT_PAUSE_MINUTES
        self.pause_error = ""
        self.usage_reset_enabled = usage_reset_enabled if type(usage_reset_enabled) is bool else True
        self.usage_reset_queue = collections.deque(maxlen=8)
        self.usage_reset_error = ""
        self.last_usage_reset = {}
        self.usage_low_enabled = usage_low_enabled if type(usage_low_enabled) is bool else True
        self.usage_low_threshold = usage_low_threshold if type(usage_low_threshold) is int and 1 <= usage_low_threshold <= 99 else 20
        self.pending_usage_low = None
        self.spoken_usage_lows = collections.deque(maxlen=512)
        self.last_usage_low = {}
        self.usage_low_error = ""
        self.on_usage_low_spoken = lambda event: True
        self.rules = load_rules(reminder_rules)
        self.rules_error = ""
        self.quiet = QuietHours.load(quiet_hours)
        self.quiet_error = ""
        self.was_quiet = False
        self.verifying_threads = set()
        self.recovery = {"state": "ready", "restored": 0, "detail": "恢复记录已就绪"}
        self.sleeping = False
        self.activity = {}

    def rule(self, alert):
        return self.rules.get(alert["kind"], KindRule())

    def play(self, key, text, kind):
        target = self.alerts.get(key,{}).get("outputTarget")
        accessory = getattr(self.speaker,"passport_settings",None)
        if ((accessory and accessory.enabled and accessory.voiceEnabled and target in (None,"passport"))
            or getattr(self.speaker,"audio_device_uid","") == PASSPORT_UID):
            prepare = getattr(self,"before_device_play",None)
            if prepare: prepare()
        if hasattr(self.speaker,"speak_to"):
            return self.speaker.speak_to(key,text,kind,target)
        method = getattr(self.speaker,"speak_kind",None)
        return method(key,text,kind) if method else self.speaker.speak(key,text)

    def quiet_blocks(self, kind=None):
        return self.quiet.active(self.now()) and not (kind == "approval" and self.quiet.allow_approval)

    def interrupt_current(self):
        key = self.speaker.alert_id if self.speaker.busy() else None
        if key in self.alerts:
            alert = self.alerts[key]
            alert["count"] = max(0, alert["count"] - 1)
            alert.pop("lastSpokenAt", None)
            alert["nextAt"] = self.now()
        return key

    def sync_quiet(self):
        active = self.quiet.active(self.now())
        if active:
            key = self.speaker.alert_id if self.speaker.busy() else None
            kind = self.alerts.get(key, {}).get("kind")
            if key and not (kind == "approval" and self.quiet.allow_approval):
                self.interrupt_current(); self.speaker.stop(key)
            self.discard_usage_resets(); self.discard_usage_lows()
        self.was_quiet = active

    def configure_rules(self, patch):
        try:
            updated = update_rules(self.rules, patch)
        except ValueError as error:
            self.rules_error = str(error)
            return False
        self.rules = updated; self.rules_error = ""
        for alert in self.alerts.values():
            if alert["kind"] not in patch:
                continue
            rule = self.rule(alert)
            if not rule.enabled and self.speaker.alert_id == alert["id"]:
                self.interrupt_current(); self.speaker.stop(alert["id"])
            if alert["state"] == "pending" and not alert.get("manualReplay"):
                schedule = rule.intervals or self.speech.intervals
                alert["nextAt"] = max(self.now(), alert.get("lastSpokenAt", self.now()) + schedule[min(max(0, alert["count"] - 1), 2)]) if alert["count"] else self.now()
        return True

    def configure_quiet(self, patch):
        try:
            self.quiet = self.quiet.update(patch)
        except ValueError as error:
            self.quiet_error = str(error)
            return False
        self.quiet_error = ""
        self.sync_quiet()
        return True

    def usage_period_label(self, event):
        periods = []
        for window in event.get("windows", []):
            minutes = window.get("windowMinutes")
            if type(minutes) not in (int, float) or not math.isfinite(minutes) or not 0 < minutes <= 10_000_000:
                continue
            name = "每周" if minutes == 10080 else "每日" if minutes == 1440 else f"{int(minutes / 60)}小时" if minutes % 60 == 0 else f"{minutes:g}分钟"
            periods.append(name)
        return "和".join(periods)

    def usage_reset_text(self, event, preview=False):
        prefix = self.speech.address + "，" if self.speech.address else ""
        label = self.usage_period_label(event)
        remaining = event.get("remainingPercent", 100)
        return prefix + ("这是额度重置提醒试听。" if preview else "") + f"Codex{label}额度已重置，当前总剩余用量百分之{remaining}。"

    def usage_low_text(self, event, preview=False):
        prefix = self.speech.address + "，" if self.speech.address else ""
        label = self.usage_period_label(event)
        threshold = event.get("threshold", self.usage_low_threshold)
        remaining = event.get("remainingPercent", max(0, threshold - 1))
        return prefix + ("这是低额度提醒试听。" if preview else "") + f"Codex{label}额度偏低，当前总剩余用量百分之{remaining}，已低于设置的百分之{threshold}。"

    def discard_usage_lows(self, stop=False):
        self.pending_usage_low = None
        if self.last_usage_low.get("state") == "queued":
            self.last_usage_low["state"] = "skipped"
        if stop and str(self.speaker.alert_id or "").startswith(USAGE_LOW_ID):
            self.speaker.stop(self.speaker.alert_id)

    def update_usage_low(self, event):
        if not event or not self.enabled or not self.usage_low_enabled or self.now() < self.muted_until or self.quiet_blocks() or self.sleeping:
            self.discard_usage_lows()
            return
        windows = [w for w in event["windows"] if w["key"] not in self.spoken_usage_lows]
        if not windows:
            self.discard_usage_lows()
            return
        identifier = hashlib.sha256(":".join(sorted(w["key"] for w in windows)).encode()).hexdigest()
        self.pending_usage_low = dict(event, id=identifier, windows=windows)
        if self.last_usage_low.get("id") != identifier or self.last_usage_low.get("state") != "queued":
            self.last_usage_low = {"id": identifier, "at": event["at"], "state": "queued", "threshold": event["threshold"]}

    def configure_usage_low(self, settings):
        if not isinstance(settings, dict) or set(settings) - {"enabled", "threshold"}:
            self.usage_low_error = "无法读取低额度提醒设置。"
            return False
        enabled = settings.get("enabled", self.usage_low_enabled)
        threshold = settings.get("threshold", self.usage_low_threshold)
        if type(enabled) is not bool or type(threshold) is not int or not 1 <= threshold <= 99:
            self.usage_low_error = "提醒阈值须为 1–99 之间的整数。"
            return False
        self.discard_usage_lows(stop=not enabled)
        self.usage_low_enabled, self.usage_low_threshold = enabled, threshold
        self.usage_low_error = ""
        return True

    def usage_reset(self, event):
        if not event.get("id") or not self.remember(USAGE_RESET_ID + event["id"]):
            return
        self.last_usage_reset = {"id": event["id"], "at": event["at"], "state": "queued"}
        self.history.append({"at": self.now(), "action": "usage_reset_detected", "id": event["id"]})
        if not self.enabled or not self.usage_reset_enabled or self.now() < self.muted_until or self.quiet_blocks() or self.sleeping:
            self.last_usage_reset["state"] = "skipped"
            return
        self.usage_reset_queue.append(event)

    def discard_usage_resets(self):
        self.usage_reset_queue.clear()
        if self.last_usage_reset.get("state") == "queued":
            self.last_usage_reset["state"] = "skipped"

    @staticmethod
    def valid_pause_minutes(value):
        if type(value) is not int or not 1 <= value <= 1440:
            raise ValueError("暂停时长须为 1–1440 分钟的整数。")
        return value

    def speech_text(self, title, phrase):
        prefix = self.speech.address + "，" if self.speech.address else ""
        return prefix + title + "，" + phrase + "。"

    def configure_speech(self, patch):
        try:
            updated = self.speech.update(patch)
            if updated.voice != self.speech.voice and hasattr(self.speaker, "speech_status"):
                if not any(voice["id"] == updated.voice for voice in self.speaker.speech_status()["voices"]):
                    raise ValueError("所选音色不可用，请刷新后重新选择。")
        except ValueError as error:
            self.settings_error = str(error)
            return False
        if updated.intervals != self.speech.intervals:
            for alert in self.alerts.values():
                if not alert["test"] and alert["count"] and alert["state"] == "pending" and self.rule(alert).intervals is None and not alert.get("manualReplay"):
                    interval = updated.intervals[min(alert["count"] - 1, 2)]
                    alert["nextAt"] = max(self.now(), alert["lastSpokenAt"] + interval)
        self.speech = self.speaker.speech = updated
        self.speaker.playback_error = ""
        self.settings_error = self.preview_error = ""
        return True

    def remember(self, key):
        if key in self.seen:
            return False
        self.seen[key] = self.now()
        while len(self.seen) > 5000:
            self.seen.popitem(last=False)
        return True

    def add(self, event):
        key = str(event.get("id") or uuid.uuid4())
        request = str(event.get("requestId", ""))
        if request and "resolved-request:" + str(event.get("thread", "")) + ":" + request in self.seen:
            return
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
        if kind == "test" and event.get("outputTarget") in ("computer","passport"):
            self.alerts[key]["outputTarget"] = event["outputTarget"]
        self.alerts[key]["recoveryPending"] = self.alerts[key]["thread"] in self.verifying_threads
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
        if action == "set_passport_settings":
            try:
                self.speaker.configure_passport(event.get("settings"))
                self.passport_error = ""
                return True
            except ValueError as error:
                self.passport_error = str(error); return False
        if action == "set_computer_audio_enabled":
            try:
                self.speaker.configure_computer(event.get("enabled"))
                self.output_error = ""
                return True
            except ValueError as error:
                self.output_error = str(error); return False
        if action == "add":
            self.add(event)
        elif action in ("ack", "resolve"):
            if isinstance(event.get("id"), str):
                self.remember(event["id"])
                self.resolve(event["id"], "已接手" if action == "ack" else "已处理")
        elif action == "resolve_thread":
            self.resolve_thread(event.get("thread"), set(event["kinds"]) if event.get("kinds") else None, event.get("reason", "任务已继续"), event.get("turn"))
        elif action == "resolve_request":
            if event.get("requestId"):
                self.remember("resolved-request:" + str(event.get("thread", "")) + ":" + str(event["requestId"]))
            for key, alert in list(self.alerts.items()):
                if alert["thread"] == event.get("thread") and alert["requestId"] == event.get("requestId"):
                    self.resolve(key)
        elif action == "snooze":
            alert = self.alerts.get(event.get("id"))
            if alert:
                if self.speaker.alert_id == alert["id"]:
                    self.interrupt_current()
                self.speaker.stop(alert["id"])
                alert["nextAt"] = self.now() + max(5, min(3600, float(event.get("seconds", 300))))
                alert["state"] = "snoozed"
                alert["manualReplay"] = True
        elif action == "replay":
            alert = self.alerts.get(event.get("id"))
            if alert and self.enabled:
                self.speaker.stop(alert["id"])
                alert["nextAt"] = self.now()
                alert["state"] = "pending"
                alert["manualReplay"] = True
                alert["recoveryPending"] = False
        elif action == "mute":
            try:
                raw_seconds = event.get("seconds", self.pause_minutes * 60)
                if isinstance(raw_seconds, bool):
                    raise ValueError()
                seconds = float(raw_seconds)
                if not math.isfinite(seconds) or not 0 < seconds <= 86400:
                    raise ValueError()
            except (ValueError, TypeError, OverflowError):
                self.pause_error = "暂停时长须大于 0 且不超过 24 小时。"
                return False
            self.pause_error = ""
            self.muted_until = self.now() + seconds
            self.interrupt_current()
            self.speaker.stop()
            self.discard_usage_resets()
            self.discard_usage_lows()
        elif action in ("set_pause_duration", "pause"):
            try:
                minutes = self.valid_pause_minutes(event.get("minutes"))
                if action == "pause" and not self.enabled:
                    raise ValueError("请先开启提醒，再暂停。")
            except ValueError as error:
                self.pause_error = str(error)
                return False
            self.pause_minutes = minutes
            self.pause_error = ""
            if action == "pause":
                self.muted_until = self.now() + minutes * 60
                self.interrupt_current()
                self.speaker.stop()
                self.discard_usage_resets()
                self.discard_usage_lows()
            return True
        elif action == "unmute":
            self.muted_until = 0
            self.pause_error = ""
        elif action == "ack_all":
            targets = event.get("ids")
            if not isinstance(targets, list) or not all(isinstance(key, str) for key in targets):
                targets = list(self.alerts)
            for key in targets:
                self.remember(key)
                self.resolve(key, "全部已接手")
        elif action == "test":
            key = "test-" + str(uuid.uuid4())
            target = event.get("target") if event.get("target") in ("computer","passport") else None
            title = "AI Passport 播报测试" if target == "passport" else "电脑播报测试" if target == "computer" else "语音提醒测试"
            self.add({"id":key,"thread":key,"kind":"test","title":title,"detail":"测试每隔 5、10、15 秒重复；点“已接手”应立即停止。","test":True,"outputTarget":target})
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
                self.discard_usage_resets()
                self.discard_usage_lows()
                for key in list(self.alerts):
                    self.resolve(key, "提醒已关闭")
            self.history.append({"at": self.now(), "action": "enabled" if self.enabled else "disabled"})
        elif action == "set_audio_device":
            computer_busy = ComputerSpeaker.busy(self.speaker) if isinstance(self.speaker,Speaker) else self.speaker.busy()
            interrupted = self.speaker.alert_id if computer_busy else None
            retry = not getattr(self.speaker,"last_badge_started",False)
            changed = event.get("device","") != self.speaker.audio_device or event.get("uid","") != self.speaker.audio_device_uid
            if interrupted in self.alerts and changed and retry:
                self.interrupt_current()
            if self.speaker.set_device(event.get("device",""),event.get("uid","")):
                if interrupted in self.alerts and retry: self.alerts[interrupted]["nextAt"] = self.now()
                self.history.append({"at":self.now(),"action":"audio_device_changed","device":self.speaker.audio_device or "跟随系统输出"})
        elif action == "refresh_audio":
            self.speaker.next_device_check = 0
            self.speaker.refresh_audio()
        elif action == "set_speech_settings":
            return self.configure_speech(event.get("settings"))
        elif action == "refresh_voices":
            self.speaker.refresh_voices()
        elif action == "preview":
            self.preview_error = ""
            if self.sleeping or self.quiet_blocks():
                self.preview_error = "当前休眠或定时免打扰生效，暂不试听。"
            elif not self.enabled or self.now() < self.muted_until:
                self.preview_error = "请先开启并恢复语音提醒，再试听。"
            else:
                self.speaker.stop(PREVIEW_ID)
                if self.speaker.busy():
                    self.preview_error = "正在播报提醒，请结束后再试听。"
                elif self.speaker.speak(PREVIEW_ID, (self.speech.address + "，" if self.speech.address else "") + "这是当前的播报声音。"):
                    self.last_spoken = self.now()
                else:
                    self.preview_error = "暂时无法试听，请检查扬声器和音色。"
        elif action == "stop_preview":
            self.speaker.stop(PREVIEW_ID)
            self.preview_error = ""
        elif action == "set_usage_reset_enabled":
            if type(event.get("enabled")) is not bool:
                self.usage_reset_error = "无法保存重置播报开关，请重试。"
                return False
            self.usage_reset_enabled = event["enabled"]
            self.usage_reset_error = ""
            if not self.usage_reset_enabled:
                self.discard_usage_resets()
                if str(self.speaker.alert_id or "").startswith(USAGE_RESET_ID):
                    self.speaker.stop(self.speaker.alert_id)
            return True
        elif action == "preview_usage_reset":
            self.usage_reset_error = ""
            if self.sleeping or self.quiet_blocks():
                self.usage_reset_error = "当前休眠或定时免打扰生效，暂不试听。"
            elif not self.enabled or self.now() < self.muted_until:
                self.usage_reset_error = "请先开启并恢复语音提醒，再试听。"
            elif self.speaker.busy():
                self.usage_reset_error = "正在播报提醒，请结束后再试听。"
            elif self.speaker.speak(USAGE_RESET_PREVIEW_ID, self.usage_reset_text({}, preview=True)):
                self.last_spoken = self.now()
            else:
                self.usage_reset_error = "暂时无法试听，请检查扬声器和音色。"
        elif action == "stop_usage_preview":
            self.speaker.stop(USAGE_RESET_PREVIEW_ID)
            self.usage_reset_error = ""
        elif action == "set_usage_low_settings":
            return self.configure_usage_low(event.get("settings"))
        elif action == "preview_usage_low":
            self.usage_low_error = ""
            if self.sleeping or self.quiet_blocks():
                self.usage_low_error = "当前休眠或定时免打扰生效，暂不试听。"
            elif not self.enabled or self.now() < self.muted_until:
                self.usage_low_error = "请先开启并恢复语音提醒，再试听。"
            elif self.speaker.busy():
                self.usage_low_error = "正在播报提醒，请结束后再试听。"
            elif self.speaker.speak(USAGE_LOW_PREVIEW_ID, self.usage_low_text({}, preview=True)):
                self.last_spoken = self.now()
            else:
                self.usage_low_error = "暂时无法试听，请检查扬声器和音色。"
        elif action == "stop_usage_low_preview":
            self.speaker.stop(USAGE_LOW_PREVIEW_ID)
            self.usage_low_error = ""
        elif action == "set_reminder_rules":
            return self.configure_rules(event.get("rules"))
        elif action == "set_quiet_hours":
            return self.configure_quiet(event.get("settings"))

    def tick(self):
        now = self.now()
        self.sync_quiet()
        if self.pending_usage_low and not -5 <= now - self.pending_usage_low["at"] < 180:
            self.discard_usage_lows()
        while self.usage_reset_queue and now - self.usage_reset_queue[0]["at"] > 120:
            expired = self.usage_reset_queue.popleft()
            if self.last_usage_reset.get("id") == expired["id"]:
                self.last_usage_reset["state"] = "expired"
        if self.sleeping or not self.enabled or now < self.muted_until or self.speaker.busy() or now - self.last_spoken < 1.5:
            return
        due = [a for a in self.alerts.values() if a["nextAt"] <= now and not self.quiet_blocks(a["kind"]) and not a.get("recoveryPending")
               and (a.get("manualReplay") or (self.rule(a).enabled
                    and (self.rule(a).max_plays == 0 or a["count"] < self.rule(a).max_plays)))]
        due.sort(key=lambda a: (0 if a["kind"] in ("approval", "question", "blocked") else 1, a["nextAt"], a["createdAt"]))
        if not due:
            if self.quiet_blocks():
                return
            if self.usage_low_enabled and self.pending_usage_low:
                event = self.pending_usage_low
                if self.play(USAGE_LOW_ID + event["id"], self.usage_low_text(event), "usage-low"):
                    self.pending_usage_low = None
                    self.spoken_usage_lows.extend(w["key"] for w in event["windows"])
                    self.last_spoken = now
                    self.last_usage_low["state"] = "spoken"
                    if self.on_usage_low_spoken(event) is False:
                        self.usage_low_error = "已播报，暂时无法保存去重记录，重启后可能再次提醒。"
                    self.history.append({"at": now, "action": "usage_low_spoken", "id": event["id"]})
                return
            if self.usage_reset_enabled and self.usage_reset_queue:
                event = self.usage_reset_queue[0]
                if self.play(USAGE_RESET_ID + event["id"], self.usage_reset_text(event), "usage-reset"):
                    self.usage_reset_queue.popleft()
                    self.last_spoken = now
                    if self.last_usage_reset.get("id") == event["id"]:
                        self.last_usage_reset["state"] = "spoken"
                    self.history.append({"at": now, "action": "usage_reset_spoken", "id": event["id"]})
            return
        alert = due[0]
        phrase = {"approval": "需要你审批", "question": "有问题需要你回答", "result": "已有结果，请查看", "blocked": "需要你关注", "test": "请点已接手，测试停止播报"}[alert["kind"]]
        text = self.speech_text(alert["title"], phrase)
        if self.play(alert["id"], text, alert["kind"]):
            schedule = (5, 10, 15) if alert["test"] else self.rule(alert).intervals or self.speech.intervals
            alert["nextAt"] = now + schedule[min(alert["count"], len(schedule) - 1)]
            alert["lastSpokenAt"] = now
            alert["count"] += 1
            alert["state"] = "pending"
            alert["manualReplay"] = False
            self.last_spoken = now
            self.history.append({"at": now, "action": "spoken", "id": alert["id"], "count": alert["count"]})

    def snapshot(self):
        audio = self.speaker.audio_status() if hasattr(self.speaker, "audio_status") else {}
        speaking = self.speaker.active_alert_id() if hasattr(self.speaker,"active_alert_id") else self.speaker.alert_id if self.speaker.busy() else None
        speech = self.speech.to_dict()
        speech.update(self.speaker.speech_status() if hasattr(self.speaker, "speech_status") else {"ready": True, "voices": [], "error": ""})
        speech.update(settingsError=self.settings_error, previewError=self.preview_error, previewing=speaking == PREVIEW_ID)
        announcement = {"enabled": self.usage_reset_enabled, "previewing": speaking == USAGE_RESET_PREVIEW_ID, "error": self.usage_reset_error, "lastReset": self.last_usage_reset}
        low_announcement = {"enabled": self.usage_low_enabled, "threshold": self.usage_low_threshold, "previewing": speaking == USAGE_LOW_PREVIEW_ID, "error": self.usage_low_error, "lastWarning": self.last_usage_low}
        alerts = [dict(a, voiceEnabled=self.rule(a).enabled, playLimit=self.rule(a).max_plays,
                       limitReached=bool(self.rule(a).max_plays and a["count"] >= self.rule(a).max_plays)) for a in self.alerts.values()]
        return {"version": VERSION, "at": self.now(), "enabled": self.enabled, "mutedUntil": self.muted_until, "pause": {"minutes": self.pause_minutes, "error": self.pause_error}, "speakingId": speaking, "audio": audio, "passport": dict(self.speaker.passport_status(),settingsError=self.passport_error) if hasattr(self.speaker,"passport_status") else {}, "outputError":self.output_error, "speech": speech, "usageAnnouncement": announcement, "usageLowAnnouncement": low_announcement, "reminderRules": {k:v.to_dict() for k,v in self.rules.items()}, "rulesError": self.rules_error, "quietHours": dict(self.quiet.to_dict(), active=self.quiet.active(self.now()), error=self.quiet_error), "recovery": self.recovery, "alerts": sorted(alerts, key=lambda a: a["createdAt"], reverse=True), "monitor": self.monitor, "activeTasks": list(self.activity.values())[:12], "history": list(self.history)}


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def save_preferences(path, settings, engine):
    settings.update(enabled=engine.enabled, audio_device=engine.speaker.audio_device, audio_device_uid=engine.speaker.audio_device_uid, speech=engine.speech.to_dict(), pause_minutes=engine.pause_minutes, usage_reset_announcement=engine.usage_reset_enabled, usage_low_announcement=engine.usage_low_enabled, usage_low_threshold=engine.usage_low_threshold)
    if hasattr(engine.speaker,"passport_settings"):
        settings.update(passport=engine.speaker.passport_settings.to_dict(),computer_audio_enabled=engine.speaker.computer_enabled)
    settings.update(reminder_rules={kind:rule.to_dict() for kind,rule in engine.rules.items()}, quiet_hours=engine.quiet.to_dict())
    atomic_json(path, settings)


def main():
    from engine_runtime import main as run
    return run()

if __name__ == "__main__":
    raise SystemExit(main())

"""A bounded speech handoff to the native BLE owner; never falls back to Mac audio."""
import threading
import time
import uuid

PASSPORT_UID = "codex-passport:ble"
PASSPORT_NAME = "AI Passport（蓝牙工牌）"
PHRASES = frozenset({"result", "question", "approval", "blocked", "test", "usage-low", "usage-reset"})


class PassportOutput:
    def __init__(self, emit=None, timeout=3.0, clock=time.monotonic):
        self.emit = emit or (lambda _: None)
        self.timeout, self.clock = timeout, clock
        self.condition = threading.Condition()
        self.connected = False
        self.piko_connected = False
        self.dictating = False
        self.ready_at = float("-inf")
        self.piko_ready_at = float("-inf")
        self.volume = 60
        self.firmware = ""
        self.pet_name_supported = False
        self.pet_sync = {"state":"waiting","detail":"等待工牌连接","progress":0,"sha":""}
        self.error = ""
        self.link_error = ""
        self.current = None
        self.retry_at = 0

    def ready(self):
        return bool(self.route())

    def route(self):
        """Which badge can announce right now; a live link outranks a muted
        BLE badge, and BLE keeps priority when both links can play."""
        now = self.clock()
        ble_live = self.connected and now - self.ready_at < 10
        if ble_live and self.volume != 0:
            return "ble"
        # PikoLink reports authentication and disconnection explicitly and
        # monitors the device heartbeat itself. A stable connection does not
        # emit repeated status updates, so it must not expire after ten seconds.
        if self.piko_connected:
            return "piko"
        return "ble" if ble_live else ""

    def feedback(self, event):
        if not isinstance(event, dict):
            return
        with self.condition:
            if event.get("kind") == "link":
                self.connected = event.get("connected") is True
                if not self.connected:
                    self.dictating = False
                self.firmware = str(event.get("firmware", self.firmware))[:40]
                self.pet_name_supported = event.get("petNameSupported", self.pet_name_supported) is True
                self.ready_at = self.clock()
                self.link_error = str(event.get("error", ""))[:160]
                value = event.get("volume", 60)
                if type(value) is int and 0 <= value <= 100:
                    self.volume = value
                if not self.connected and self.current:
                    self.current["finished"] = True
                    self.current["failed"] = True
            elif event.get("kind") == "piko":
                self.piko_connected = event.get("connected") is True
                if self.piko_connected:
                    self.piko_ready_at = self.clock()
                elif self.current:
                    self.current["finished"] = True
                    self.current["failed"] = True
            elif event.get("kind") == "pet":
                state=event.get("state")
                if state in {"waiting","disabled","unsupported","preparing","paused","transferring","synced"}:
                    progress=event.get("progress",0);sha=event.get("sha","")
                    if type(progress) is int and 0<=progress<=100 and isinstance(sha,str) and (not sha or len(sha)==64 and all(c in '0123456789abcdef' for c in sha)):
                        detail=str(event.get("detail",""))[:100]
                        if 'http:' in detail or 'https:' in detail:detail='正在同步工牌宠物'
                        self.pet_sync={"state":state,"detail":detail,"progress":progress,"sha":sha}
            elif event.get("kind") == "dictation":
                self.dictating = event.get("active") is True
            elif event.get("kind") == "audio" and self.current:
                if event.get("id") != self.current["id"]:
                    return
                phase = event.get("phase")
                if phase == "started":
                    self.current["started"] = True
                    self.current["until"] = self.clock() + 12
                    self.error = ""
                elif phase in ("done", "stopped", "failed"):
                    self.current["finished"] = True
                    self.current["failed"] = phase == "failed"
                    if phase == "failed":
                        self.error = "工牌未能播放，等待重试"
            self.condition.notify_all()

    def busy(self):
        with self.condition:
            if self.dictating and self.ready():
                return True
            if not self.current or not self.current["started"] or self.current["finished"]:
                return False
            if not self.ready() or self.clock() > self.current["until"]:
                self.current["finished"] = True
                self.error = "工牌连接或播放反馈超时"
                return False
            return True

    def speak(self, alert_id, kind):
        if kind not in PHRASES:
            kind = "test"
        with self.condition:
            transport = self.route()
            if not transport or (transport == "ble" and self.volume == 0) or self.clock() < self.retry_at or self.busy_unlocked():
                return False
            item = {"id": uuid.uuid4().hex, "alertId": alert_id, "started": False,
                    "finished": False, "failed": False, "until": 0}
            self.current = item
        self.emit({"op": "play", "id": item["id"], "alertId": alert_id, "phrase": kind, "transport": transport})
        deadline = time.monotonic() + self.timeout
        with self.condition:
            while self.current is item and not item["started"] and not item["finished"] and self.route() == transport:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
            success = self.current is item and item["started"] and not item["failed"]
            if not success:
                item["finished"] = True
                self.retry_at = self.clock() + 5
                self.error = self.error or "尚未收到工牌播放确认，暂不计入播报次数"
        if not success:
            self.emit({"op": "stop", "id": item["id"]})
        return success

    def busy_unlocked(self):
        return bool((self.dictating and self.ready()) or (self.current and self.current["started"] and not self.current["finished"]
                    and self.ready() and self.clock() <= self.current["until"]))

    def stop(self, alert_id=None):
        with self.condition:
            item = self.current
            if not item or (alert_id is not None and item["alertId"] != alert_id):
                return
            item["finished"] = True
            self.current = None
            self.condition.notify_all()
        self.emit({"op": "stop", "id": item["id"]})

    def status(self):
        with self.condition:
            ready = self.ready()
            return {"available": ready, "volume": self.volume,
                    "error": (self.link_error or self.error) if ready else (self.link_error or "工牌未连接，已暂停播报")}

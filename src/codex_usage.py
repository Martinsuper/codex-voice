"""Read account quotas through the installed, authenticated official Codex CLI.

Only initialize, account/read and account/rateLimits/read are sent. Raw account
responses, credentials, credit balances and RPC errors never leave this module.
"""
import copy
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import select
import shutil
import subprocess
import threading
import time


POLL_SECONDS = 60
STALE_SECONDS = 180
MESSAGES = {
    "loading": "正在读取 Codex 用量",
    "missing_cli": "未找到 Codex 客户端，请安装或更新后重试。",
    "signed_out": "请先在本机 Codex 中登录 ChatGPT 账号。",
    "api_key": "当前 Codex 使用 API Key，无法读取订阅剩余额度。",
    "unsupported": "当前 Codex 版本不支持读取用量，请更新后重试。",
    "unavailable": "当前账号未返回可用的 Codex 额度。",
    "timeout": "读取用量超时，稍后会自动重试。",
    "error": "暂时无法读取用量，请检查网络或 Codex 登录状态。",
    "stale": "用量数据已过期，等待重新同步。",
    "disabled": "用量同步未启动。",
}


class UsageError(Exception):
    def __init__(self, state):
        self.state = state if state in MESSAGES else "error"
        super().__init__(MESSAGES[self.state])


def find_codex_cli():
    # Finder-launched menu bar apps usually have a minimal PATH.
    candidates = [
        "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
        "/Applications/Codex.app/Contents/Resources/codex",
        str(Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
        str(Path.home() / "Applications/Codex.app/Contents/Resources/codex"),
        shutil.which("codex"),
        "/opt/homebrew/bin/codex", "/usr/local/bin/codex",
        str(Path.home() / ".local/bin/codex"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise UsageError("missing_cli")


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def normalize_limits(result):
    if not isinstance(result, dict):
        raise UsageError("unavailable")
    buckets = result.get("rateLimitsByLimitId")
    if isinstance(buckets, dict) and "codex" in buckets:
        bucket = buckets["codex"]
    else:
        bucket = result.get("rateLimits")
    if not isinstance(bucket, dict) or bucket.get("limitId") not in (None, "codex"):
        raise UsageError("unavailable")
    windows = []
    for key in ("primary", "secondary"):
        window = bucket.get(key)
        if window is None:
            continue
        if not isinstance(window, dict) or not finite_number(window.get("usedPercent")):
            # An unknown second limit must not inflate the displayed allowance.
            raise UsageError("unavailable")
        duration, reset = window.get("windowDurationMins"), window.get("resetsAt")
        windows.append({
            "id": key,
            "remainingPercent": math.floor(max(0, min(100, 100 - window["usedPercent"]))),
            "isFull": window["usedPercent"] == 0,
            "windowMinutes": duration if finite_number(duration) and duration > 0 else None,
            "resetsAt": reset if finite_number(reset) and reset > 0 else None,
        })
    if not windows:
        raise UsageError("unavailable")
    plan = bucket.get("planType")
    return {"remainingPercent": min(w["remainingPercent"] for w in windows),
            "windows": windows, "planType": plan if plan in ("free", "plus", "pro", "team", "business", "enterprise", "edu") else ""}


class UsageRPC:
    def __init__(self, executable, codex_home, stop=None, timeout=25):
        self.stop = stop or threading.Event()
        self.deadline = time.monotonic() + timeout
        self.pending = b""
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("PYTHON") and key != "__PYVENV_LAUNCHER__"}
        environment["CODEX_HOME"] = str(codex_home)
        self.process = subprocess.Popen(
            [str(executable), "app-server", "--listen", "stdio://", "-c", "analytics.enabled=false"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment, start_new_session=True)

    def send(self, value):
        self.process.stdin.write((json.dumps(value) + "\n").encode())
        self.process.stdin.flush()

    def receive(self, identifier):
        while not self.stop.is_set():
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise UsageError("timeout")
            if b"\n" in self.pending:
                line, self.pending = self.pending.split(b"\n", 1)
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(value, dict):
                    continue
                if "id" in value and "method" in value:
                    # Never fulfill auth-token refresh, tool or approval requests.
                    self.send({"id": value["id"], "error": {"code": -32601, "message": "Read-only quota client"}})
                elif value.get("id") == identifier:
                    if "error" in value:
                        code = (value["error"] or {}).get("code") if isinstance(value["error"], dict) else None
                        raise UsageError("unsupported" if code == -32601 else "signed_out" if code in (401, 403) else "error")
                    if "result" not in value:
                        raise UsageError("error")
                    return value["result"]
                continue
            if select.select([self.process.stdout], [], [], min(.2, remaining))[0]:
                chunk = os.read(self.process.stdout.fileno(), 131072)
                if not chunk:
                    raise UsageError("error")
                self.pending += chunk
                if len(self.pending) > 2 * 1024 * 1024:
                    raise UsageError("error")
        raise UsageError("error")

    def close(self):
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        finally:
            self.process.stdout.close()


def read_usage(codex_home, stop=None, executable=None, timeout=25):
    rpc = None
    try:
        rpc = UsageRPC(executable or find_codex_cli(), codex_home, stop, timeout)
        rpc.send({"id": 1, "method": "initialize", "params": {"clientInfo": {
            "name": "codex_voice", "title": "Codex 语音提醒", "version": "0.6.0-beta.2"}}})
        rpc.receive(1)
        rpc.send({"method": "initialized", "params": {}})
        rpc.send({"id": 2, "method": "account/read", "params": {"refreshToken": False}})
        result = rpc.receive(2)
        account = result.get("account") if isinstance(result, dict) else None
        if not isinstance(account, dict):
            raise UsageError("signed_out")
        if account.get("type") == "apiKey":
            raise UsageError("api_key")
        if account.get("type") != "chatgpt":
            raise UsageError("unavailable")
        rpc.send({"id": 3, "method": "account/rateLimits/read"})
        limits = normalize_limits(rpc.receive(3))
        identity = account.get("id") or account.get("email")
        # Keep this discriminator in memory only, never the email or auth data.
        account_key = hashlib.sha256(identity.strip().casefold().encode()).hexdigest() if isinstance(identity, str) and identity.strip() else ""
        return dict(limits, state="ready", message="", fetchedAt=time.time(), _accountKey=account_key)
    except UsageError:
        raise
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        raise UsageError("error") from None
    finally:
        if rpc:
            rpc.close()


def public_snapshot(value, now):
    value = copy.deepcopy(value)
    value.pop("_accountKey", None)
    fetched = value.get("fetchedAt", 0)
    reset_passed = any(finite_number(w.get("resetsAt")) and w["resetsAt"] <= now for w in value.get("windows", []))
    if value.get("state") == "ready" and (now - fetched >= STALE_SECONDS or now < fetched - 5 or reset_passed):
        value.update(state="stale", message=MESSAGES["stale"], remainingPercent=None, windows=[])
    return value


class UsageResetDetector:
    """Infer a replenished cycle from comparable, successful quota readings."""
    def __init__(self):
        self.previous = None
        self.seen = collections.deque(maxlen=128)

    def observe(self, value):
        if value.get("state") != "ready":
            if value.get("state") in ("signed_out", "api_key"):
                self.previous = None
            return []
        current = copy.deepcopy(value)
        previous, self.previous = self.previous, current
        scope = current.get("_accountKey")
        timestamp = current.get("fetchedAt")
        if not scope or not finite_number(timestamp) or previous is None:
            return []
        previous_at = previous.get("fetchedAt")
        if (not finite_number(previous_at) or not 0 < timestamp - previous_at <= 600
                or scope != previous.get("_accountKey") or current.get("planType") != previous.get("planType")):
            return []
        old_windows = {w["id"]: w for w in previous.get("windows", [])}
        changed = []
        for window in current.get("windows", []):
            old = old_windows.get(window.get("id"))
            if not old:
                continue
            duration, reset, old_reset = window.get("windowMinutes"), window.get("resetsAt"), old.get("resetsAt")
            old_remaining = old.get("remainingPercent")
            if (not finite_number(duration) or duration <= 0 or duration != old.get("windowMinutes")
                    or not finite_number(reset) or not finite_number(old_reset)
                    or old_reset <= previous_at or reset <= timestamp or reset <= old_reset
                    or not finite_number(old_remaining) or not 0 <= old_remaining < 100
                    or window.get("remainingPercent") != 100 or window.get("isFull") is not True):
                continue
            key = hashlib.sha256(f"{scope}:{window['id']}:{duration}:{reset}".encode()).hexdigest()
            if key not in self.seen:
                self.seen.append(key)
                changed.append({"id": window["id"], "windowMinutes": duration, "resetsAt": reset, "key": key})
        if not changed:
            return []
        identifier = hashlib.sha256(":".join(w["key"] for w in changed).encode()).hexdigest()
        for window in changed:
            del window["key"]
        return [{"id": identifier,
                 "at": timestamp, "remainingPercent": current["remainingPercent"], "windows": changed}]


class UsageLowDetector:
    """Warn once for each account, window cycle and threshold, across restarts."""
    def __init__(self, state_file=None, now=time.time):
        self.now = now
        self.state_file = Path(state_file) if state_file else None
        self.announced = {}
        if self.state_file:
            try:
                if self.state_file.stat().st_size <= 65536:
                    saved = json.loads(self.state_file.read_text())
                    records = saved.get("announced", {}) if isinstance(saved, dict) and saved.get("version") == 1 else {}
                    if isinstance(records, dict):
                        self.announced = {key: expiry for key, expiry in records.items()
                                          if isinstance(key, str) and len(key) == 64 and all(c in "0123456789abcdef" for c in key)
                                          and finite_number(expiry) and expiry > self.now()}
            except (OSError, ValueError):
                pass
        self._prune(self.now())

    def _prune(self, now):
        self.announced = dict(sorted(((key, expiry) for key, expiry in self.announced.items() if expiry > now),
                                     key=lambda pair: pair[1], reverse=True)[:512])

    def detect(self, value, threshold, now):
        if type(threshold) is not int or not 1 <= threshold <= 99:
            return None
        scope, fetched = value.get("_accountKey"), value.get("fetchedAt")
        if (value.get("state") != "ready" or not scope or not finite_number(fetched)
                or not -5 <= now - fetched < STALE_SECONDS):
            return None
        self._prune(now)
        windows = value.get("windows", [])
        # Do not announce a partly expired multi-window reading.
        if any(not finite_number(w.get("resetsAt")) or w["resetsAt"] <= now for w in windows):
            return None
        low = []
        for window in windows:
            remaining, duration, reset = window.get("remainingPercent"), window.get("windowMinutes"), window.get("resetsAt")
            if (not finite_number(remaining) or not 0 <= remaining < threshold
                    or not finite_number(duration) or duration <= 0):
                continue
            key = hashlib.sha256(f"usage-low:{scope}:{value.get('planType')}:{window['id']}:{duration}:{reset}:{threshold}".encode()).hexdigest()
            if key not in self.announced:
                low.append({"id": window["id"], "windowMinutes": duration, "resetsAt": reset, "key": key})
        if not low:
            return None
        identifier = hashlib.sha256(":".join(sorted(w["key"] for w in low)).encode()).hexdigest()
        return {"id": identifier, "at": fetched, "threshold": threshold,
                "remainingPercent": value["remainingPercent"], "windows": low}

    def mark_announced(self, event):
        for window in event["windows"]:
            self.announced[window["key"]] = window["resetsAt"]
        self._prune(self.now())
        if not self.state_file:
            return True
        try:
            temporary = self.state_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"version": 1, "announced": self.announced}))
            temporary.chmod(0o600)
            os.replace(temporary, self.state_file)
            return True
        except OSError:
            # In-memory deduplication still works if storage is temporarily full.
            return False


class UsageMonitor:
    """One bounded read on a worker; reminder/audio dispatch never waits on it."""
    def __init__(self, codex_home, provider=None, interval=POLL_SECONDS, min_refresh=10, low_state_file=None):
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.reset_detector = UsageResetDetector()
        self.reset_events = collections.deque(maxlen=8)
        self.low_detector = UsageLowDetector(low_state_file)
        self.provider = provider or (lambda: read_usage(codex_home, self.stop_event))
        self.interval, self.min_refresh = interval, min_refresh
        self.value = {"state": "loading", "message": MESSAGES["loading"], "remainingPercent": None,
                      "windows": [], "fetchedAt": 0, "lastAttemptAt": 0, "refreshing": True,
                      "pollSeconds": interval, "nextAttemptAt": 0}
        self.thread = threading.Thread(target=self.run, name="codex-usage", daemon=True)

    def start(self):
        self.thread.start()

    def request_refresh(self):
        with self.lock:
            if self.value["refreshing"] or time.time() - self.value["lastAttemptAt"] < self.min_refresh:
                return False
            self.value["refreshing"] = True
        self.wake.set()
        return True

    def snapshot(self):
        with self.lock:
            return public_snapshot(self.value, time.time())

    def drain_reset_events(self):
        with self.lock:
            events = list(self.reset_events)
            self.reset_events.clear()
            return events

    def low_warning(self, threshold):
        with self.lock:
            return self.low_detector.detect(self.value, threshold, time.time())

    def mark_low_announced(self, event):
        with self.lock:
            return self.low_detector.mark_announced(event)

    def run(self):
        while not self.stop_event.is_set():
            self.wake.clear()
            with self.lock:
                self.value.update(refreshing=True, lastAttemptAt=time.time())
            try:
                result = self.provider()
            except Exception as error:
                state = error.state if isinstance(error, UsageError) else "error"
                result = {"state": state, "message": MESSAGES[state], "remainingPercent": None,
                          "windows": [], "fetchedAt": 0, "planType": ""}
            with self.lock:
                self.reset_events.extend(self.reset_detector.observe(result))
                self.value.update(result, refreshing=False, nextAttemptAt=time.time() + self.interval)
            self.wake.wait(self.interval)

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread.is_alive():
            self.thread.join(timeout=3)

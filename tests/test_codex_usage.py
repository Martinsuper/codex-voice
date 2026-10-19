import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from codex_usage import MESSAGES, UsageError, UsageMonitor, find_codex_cli, normalize_limits, public_snapshot, read_usage


def limits(primary=1, secondary=None):
    return {"limitId": "codex", "planType": "pro",
            "primary": {"usedPercent": primary, "windowDurationMins": 10080, "resetsAt": 2_000_000_000},
            "secondary": {"usedPercent": secondary, "windowDurationMins": 300, "resetsAt": 2_000_000_001} if secondary is not None else None}


class LimitsTests(unittest.TestCase):
    def test_remaining_percent_and_windows(self):
        result = normalize_limits({"rateLimits": limits(1, 76.2)})
        self.assertEqual(result["remainingPercent"], 23)
        self.assertEqual([w["remainingPercent"] for w in result["windows"]], [99, 23])
        self.assertEqual(result["windows"][0]["windowMinutes"], 10080)

    def test_current_codex_bucket_takes_precedence_over_legacy_and_other_models(self):
        result = normalize_limits({"rateLimitsByLimitId": {"codex": limits(10), "other_model": limits(99)}, "rateLimits": limits(85)})
        self.assertEqual(result["remainingPercent"], 90)

    def test_legacy_codex_without_id_supported(self):
        bucket = limits(25)
        del bucket["limitId"]
        self.assertEqual(normalize_limits({"rateLimits": bucket})["remainingPercent"], 75)

    def test_missing_malformed_or_other_model_quota_stays_unknown(self):
        other = dict(limits(), limitId="other_model")
        malformed = dict(limits(), secondary={"usedPercent": None})
        for result in (None, {}, {"rateLimits": {}}, {"rateLimits": other}, {"rateLimits": malformed},
                       {"rateLimitsByLimitId": {"codex": None}, "rateLimits": limits()}):
            with self.subTest(result=result), self.assertRaises(UsageError):
                normalize_limits(result)

    def test_invalid_used_values_do_not_become_zero_or_one_hundred(self):
        for value in (None, True, "1", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(UsageError):
                normalize_limits({"rateLimits": limits(value)})

    def test_zero_full_and_out_of_range_are_clamped(self):
        for used, remaining in ((0, 100), (100, 0), (101, 0), (-1, 100)):
            self.assertEqual(normalize_limits({"rateLimits": limits(used)})["remainingPercent"], remaining)

    def test_private_account_and_credit_fields_are_removed(self):
        bucket = dict(limits(), credits={"balance": "private"}, resetCredits={"id": "private"}, email="private")
        value = normalize_limits({"rateLimits": bucket, "secret": "private"})
        self.assertNotIn("private", json.dumps(value))

    def test_stale_data_and_reset_crossing_clear_percentage(self):
        data = dict(normalize_limits({"rateLimits": limits()}), state="ready", fetchedAt=100, message="")
        self.assertEqual(public_snapshot(data, 279)["remainingPercent"], 99)
        for now in (280, 90, 2_000_000_000):
            expired = public_snapshot(data, now)
            self.assertEqual(expired["state"], "stale")
            self.assertIsNone(expired["remainingPercent"])
        self.assertEqual(data["remainingPercent"], 99, "Snapshot checks must not mutate worker data")


class RPCTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.binary = self.root / "codex"
        self.log = self.root / "methods.jsonl"

    def tearDown(self):
        self.temporary.cleanup()

    def server(self, account=None, rate_error=None, hang=False, reverse_request=False):
        # Run the protocol fixture with the host Python, without real auth/network.
        import sys
        source = "#!" + sys.executable + "\n" + "import json, os, sys, time\n"
        source += "account = " + repr(account if account is not None else {"type": "chatgpt", "email": "private-test", "planType": "pro"}) + "\n"
        source += "result = " + repr({"rateLimitsByLimitId": {"codex": limits()}}) + "\n"
        source += "error = " + repr(rate_error) + "\n"
        source += "log = " + repr(str(self.log)) + "\n"
        source += """
for line in sys.stdin:
    request = json.loads(line)
    with open(log, 'a') as output:
        output.write(json.dumps(request) + '\\n')
    method = request.get('method')
    if method == 'initialize':
        reply = {'id': request['id'], 'result': {'version': 'test'}}
    elif method == 'account/read':
        assert request['params'] == {'refreshToken': False}
        reply = {'id': request['id'], 'result': {'account': account or None}}
    elif method == 'account/rateLimits/read':
        reply = {'id': request['id'], 'error': error} if error else {'id': request['id'], 'result': result}
    else:
        continue
"""
        if hang:
            source += "    time.sleep(10)\n"
        if reverse_request:
            source += "    print(json.dumps({'id':'server-refresh','method':'account/chatgptAuthTokens/refresh','params':{}}), flush=True)\n"
        source += "    print(json.dumps(reply), flush=True)\n"
        self.binary.write_text(source)
        self.binary.chmod(0o700)

    def methods(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_initialize_and_read_only_account_methods(self):
        self.server(reverse_request=True)
        value = read_usage(self.root, executable=self.binary, timeout=2)
        self.assertEqual(value["remainingPercent"], 99)
        self.assertNotIn("private-test", json.dumps(value))
        messages = self.methods()
        self.assertEqual([m["method"] for m in messages if "method" in m],
                         ["initialize", "initialized", "account/read", "account/rateLimits/read"])
        self.assertTrue(any(m.get("error", {}).get("code") == -32601 for m in messages))

    def test_signed_out_or_api_key_does_not_query_quota(self):
        for account, state in (({}, "signed_out"), ({"type": "apiKey"}, "api_key")):
            self.server(account=account)
            if self.log.exists():
                self.log.unlink()
            with self.assertRaises(UsageError) as raised:
                read_usage(self.root, executable=self.binary, timeout=2)
            self.assertEqual(raised.exception.state, state)
            self.assertNotIn("account/rateLimits/read", [m.get("method") for m in self.methods()])

    def test_rpc_errors_are_fixed_messages_without_raw_server_data(self):
        self.server(rate_error={"code": -32601, "message": "private-test-token"})
        with self.assertRaises(UsageError) as raised:
            read_usage(self.root, executable=self.binary, timeout=2)
        self.assertEqual(raised.exception.state, "unsupported")
        self.assertNotIn("private-test", str(raised.exception))

    def test_unresponsive_client_has_bounded_timeout_and_cleanup(self):
        self.server(hang=True)
        started = time.monotonic()
        with self.assertRaises(UsageError) as raised:
            read_usage(self.root, executable=self.binary, timeout=.2)
        self.assertEqual(raised.exception.state, "timeout")
        self.assertLess(time.monotonic() - started, 2)

    def test_missing_cli_is_reported_without_credentials(self):
        with patch("codex_usage.shutil.which", return_value=None), patch("codex_usage.Path.is_file", return_value=False):
            with self.assertRaises(UsageError) as raised:
                find_codex_cli()
        self.assertEqual(raised.exception.state, "missing_cli")


class MonitorTests(unittest.TestCase):
    def wait(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(predicate())

    def test_slow_read_does_not_block_caller_and_refresh_is_single_flight(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def provider():
            calls.append(1); entered.set(); release.wait(2)
            return dict(normalize_limits({"rateLimits": limits()}), state="ready", message="", fetchedAt=time.time())
        monitor = UsageMonitor("/unused", provider=provider, interval=60, min_refresh=.05)
        try:
            started = time.monotonic(); monitor.start()
            self.assertTrue(entered.wait(1))
            self.assertLess(time.monotonic() - started, .5)
            self.assertTrue(monitor.snapshot()["refreshing"])
            self.assertFalse(monitor.request_refresh())
            release.set()
            self.wait(lambda: monitor.snapshot()["state"] == "ready")
            self.assertEqual(monitor.snapshot()["remainingPercent"], 99)
            time.sleep(.06)
            self.assertTrue(monitor.request_refresh())
            self.wait(lambda: len(calls) == 2 and not monitor.snapshot()["refreshing"])
        finally:
            release.set(); monitor.close()
        self.assertFalse(monitor.thread.is_alive())

    def test_failed_refresh_removes_last_percentage_and_never_leaks_exception(self):
        called = []
        def provider():
            called.append(1)
            if len(called) == 1:
                return dict(normalize_limits({"rateLimits": limits()}), state="ready", fetchedAt=time.time(), message="")
            raise RuntimeError("private-test-token")
        monitor = UsageMonitor("/unused", provider=provider, interval=60, min_refresh=.03)
        try:
            monitor.start(); self.wait(lambda: monitor.snapshot()["state"] == "ready")
            time.sleep(.04); self.assertTrue(monitor.request_refresh())
            self.wait(lambda: monitor.snapshot()["state"] == "error")
            value = monitor.snapshot()
            self.assertIsNone(value["remainingPercent"])
            self.assertEqual(value["windows"], [])
            self.assertEqual(value["message"], MESSAGES["error"])
            self.assertNotIn("private-test", json.dumps(value))
            self.assertFalse(monitor.request_refresh(), "Manual refresh should be rate limited")
        finally:
            monitor.close()

    def test_automatic_refresh_continues_without_manual_input(self):
        calls = []
        def provider():
            calls.append(1)
            return dict(normalize_limits({"rateLimits": limits(len(calls))}), state="ready", fetchedAt=time.time(), message="")
        monitor = UsageMonitor("/unused", provider=provider, interval=.03)
        try:
            monitor.start(); self.wait(lambda: len(calls) >= 2 and (monitor.snapshot()["remainingPercent"] or 100) <= 98)
            self.assertLessEqual(monitor.snapshot()["remainingPercent"], 98)
        finally:
            monitor.close()


if __name__ == "__main__":
    unittest.main()

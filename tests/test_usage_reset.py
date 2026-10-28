import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_usage import UsageMonitor, UsageResetDetector, normalize_limits, public_snapshot
from test_voice_engine import FakeSpeaker
from voice_engine import Engine, Speaker, USAGE_RESET_ID, USAGE_RESET_PREVIEW_ID, save_preferences


def reading(used, *, at=1000, reset=2000, scope="account-A", plan="pro", secondary=None):
    bucket = {"limitId": "codex", "planType": plan,
              "primary": {"usedPercent": used, "windowDurationMins": 10080, "resetsAt": reset}}
    if secondary is not None:
        bucket["secondary"] = {"usedPercent": secondary, "windowDurationMins": 300, "resetsAt": reset + 60}
    return dict(normalize_limits({"rateLimits": bucket}), state="ready", fetchedAt=at, _accountKey=scope)


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = UsageResetDetector()

    def test_full_transition_with_new_cycle_emits_once(self):
        self.assertEqual(self.detector.observe(reading(70)), [])
        current = reading(0, at=1060, reset=3000)
        events = self.detector.observe(current)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["remainingPercent"], 100)
        self.assertEqual(events[0]["windows"][0]["windowMinutes"], 10080)
        self.assertEqual(self.detector.observe(current), [])
        self.assertEqual(self.detector.observe(reading(0, at=1120, reset=3000)), [])

    def test_initial_full_and_unused_cycle_rollover_are_quiet(self):
        self.assertEqual(self.detector.observe(reading(0)), [])
        self.assertEqual(self.detector.observe(reading(0, at=1060, reset=3000)), [])

    def test_percentage_recovery_without_cycle_change_is_not_a_reset(self):
        self.detector.observe(reading(70))
        self.assertEqual(self.detector.observe(reading(0, at=1060)), [])

    def test_partial_recovery_and_clamped_negative_values_are_quiet(self):
        for used in (1, -1):
            with self.subTest(used=used):
                detector = UsageResetDetector(); detector.observe(reading(70))
                self.assertEqual(detector.observe(reading(used, at=1060, reset=3000)), [])

    def test_account_plan_or_window_changes_establish_a_new_baseline(self):
        for change in ({"_accountKey": "account-B"}, {"_accountKey": ""}, {"planType": "plus"}):
            detector = UsageResetDetector(); detector.observe(reading(70))
            current = reading(0, at=1060, reset=3000); current.update(change)
            self.assertEqual(detector.observe(current), [])
        detector = UsageResetDetector(); detector.observe(reading(70))
        current = reading(0, at=1060, reset=3000); current["windows"][0]["windowMinutes"] = 300
        self.assertEqual(detector.observe(current), [])

    def test_unknown_identity_never_announces(self):
        self.detector.observe(reading(70, scope=""))
        self.assertEqual(self.detector.observe(reading(0, at=1060, reset=3000, scope="")), [])

    def test_transient_read_error_can_recover_but_sign_out_clears_baseline(self):
        for state, expected in (("error", 1), ("timeout", 1), ("signed_out", 0), ("api_key", 0)):
            detector = UsageResetDetector(); detector.observe(reading(70))
            self.assertEqual(detector.observe({"state": state}), [])
            self.assertEqual(len(detector.observe(reading(0, at=1060, reset=3000))), expected)

    def test_long_gap_and_clock_rollback_do_not_replay_old_resets(self):
        for at in (999, 1000, 1601):
            detector = UsageResetDetector(); detector.observe(reading(70))
            self.assertEqual(detector.observe(reading(0, at=at, reset=3000)), [])

    def test_missing_or_expired_cycle_metadata_is_quiet(self):
        for reset in (None, 0, 1050):
            detector = UsageResetDetector(); detector.observe(reading(70))
            current = reading(0, at=1060, reset=3000); current["windows"][0]["resetsAt"] = reset
            self.assertEqual(detector.observe(current), [])

    def test_two_cycles_merge_and_another_limited_cycle_keeps_total_correct(self):
        self.detector.observe(reading(70, secondary=50))
        events = self.detector.observe(reading(0, at=1060, reset=3000, secondary=0))
        self.assertEqual(len(events), 1); self.assertEqual(len(events[0]["windows"]), 2)
        detector = UsageResetDetector(); detector.observe(reading(70, secondary=80))
        event = detector.observe(reading(0, at=1060, reset=3000, secondary=80))[0]
        self.assertEqual(event["remainingPercent"], 20)
        self.assertEqual(len(event["windows"]), 1)

    def test_duplicate_cycle_after_a_server_rollback_does_not_announce_twice(self):
        self.detector.observe(reading(70))
        self.assertTrue(self.detector.observe(reading(0, at=1060, reset=3000)))
        self.detector.observe(reading(70, at=1120, reset=2000))
        self.assertEqual(self.detector.observe(reading(0, at=1180, reset=3000)), [])

    def test_account_discriminator_never_enters_snapshots_or_events(self):
        self.detector.observe(reading(70, scope="private-identity"))
        current = reading(0, at=1060, reset=3000, scope="private-identity")
        events = self.detector.observe(current)
        self.assertNotIn("private-identity", json.dumps(events))
        public = public_snapshot(current, 1060)
        self.assertNotIn("_accountKey", public)
        self.assertNotIn("private-identity", json.dumps(public))
        self.assertEqual(current["_accountKey"], "private-identity")

    def test_monitor_delivers_each_reset_to_engine_only_once(self):
        started = time.time(); calls = []
        def provider():
            calls.append(1)
            return reading(70 if len(calls) == 1 else 0, at=time.time(), reset=started + (1000 if len(calls) == 1 else 2000))
        monitor = UsageMonitor("/unused", provider=provider, interval=.02)
        try:
            monitor.start()
            deadline = time.monotonic() + 2
            events = []
            while not events and time.monotonic() < deadline:
                events = monitor.drain_reset_events(); time.sleep(.005)
            self.assertEqual(len(events), 1)
            time.sleep(.06)
            self.assertEqual(monitor.drain_reset_events(), [])
            self.assertNotIn("_accountKey", monitor.snapshot())
        finally:
            monitor.close()


class AnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.speaker = FakeSpeaker()
        self.engine = Engine(self.speaker, lambda: self.now)
        self.event = {"id": "cycle-1", "at": self.now, "remainingPercent": 100,
                      "windows": [{"id": "primary", "windowMinutes": 10080, "resetsAt": 3000}]}

    def test_reset_is_one_shot_without_a_task_or_repeated_reminder(self):
        self.engine.usage_reset(self.event); self.engine.tick()
        self.assertEqual(len(self.speaker.calls), 1)
        self.assertIn("每周额度已重置", self.speaker.calls[0][1])
        self.assertIn("百分之100", self.speaker.calls[0][1])
        self.assertEqual(self.speaker.calls[0][0], USAGE_RESET_ID + "cycle-1")
        self.assertFalse(self.engine.alerts)
        for second in (1002, 1060, 1300):
            self.now = second; self.engine.usage_reset(self.event); self.engine.tick()
        self.assertEqual(len(self.speaker.calls), 1)

    def test_normal_reminders_and_active_speech_have_priority(self):
        self.engine.add({"id": "question", "kind": "question"})
        self.engine.usage_reset(self.event); self.speaker.active = True
        self.engine.tick(); self.assertFalse(self.speaker.calls)
        self.speaker.active = False; self.engine.tick()
        self.assertEqual(self.speaker.calls[0][0], "question")
        self.now += 2; self.engine.tick()
        self.assertTrue(self.speaker.calls[1][0].startswith(USAGE_RESET_ID))

    def test_toggle_total_off_and_pause_skip_events_without_later_backlog(self):
        for action in ({"action": "set_usage_reset_enabled", "enabled": False}, {"action": "set_enabled", "enabled": False}, {"action": "mute"}):
            engine = Engine(FakeSpeaker(), lambda: self.now)
            engine.event(action); engine.usage_reset(self.event)
            engine.event({"action": "set_usage_reset_enabled", "enabled": True})
            engine.event({"action": "set_enabled", "enabled": True}); engine.event({"action": "unmute"})
            engine.tick()
            self.assertFalse(engine.speaker.calls)
            self.assertEqual(engine.last_usage_reset["state"], "skipped")

    def test_pausing_or_disabling_clears_already_queued_events(self):
        for action in ({"action": "pause", "minutes": 15}, {"action": "mute"}, {"action": "set_enabled", "enabled": False}, {"action": "set_usage_reset_enabled", "enabled": False}):
            engine = Engine(FakeSpeaker(), lambda: self.now)
            engine.usage_reset(self.event); engine.event(action)
            self.assertFalse(engine.usage_reset_queue)

    def test_failed_output_retries_briefly_then_expires_instead_of_announcing_late(self):
        self.engine.usage_reset(self.event)
        with patch.object(self.speaker, "speak", return_value=False):
            self.engine.tick()
        self.assertTrue(self.engine.usage_reset_queue)
        self.now += 121; self.engine.tick()
        self.assertFalse(self.engine.usage_reset_queue)
        self.assertFalse(self.speaker.calls)
        self.assertEqual(self.engine.last_usage_reset["state"], "expired")

    def test_custom_address_empty_address_and_total_remaining_are_honored(self):
        self.event["remainingPercent"] = 20
        for address in ("Rico", ""):
            self.engine.configure_speech({"address": address})
            text = self.engine.usage_reset_text(self.event)
            self.assertTrue(text.startswith(address + "，" if address else "Codex"))
            self.assertIn("总剩余用量百分之20", text)

    def test_reset_reaches_the_existing_voice_rate_and_selected_device(self):
        info = {"connected": True, "name": "测试扬声器", "id": 42}
        speaker = Speaker("测试扬声器", device_provider=lambda: info, voice_provider=lambda: [{"id": "Tingting"}])
        engine = Engine(speaker, lambda: self.now, speech_settings={"rate": 230, "address": "Rico"})
        engine.usage_reset(self.event)
        with patch("speaker.subprocess.Popen") as popen:
            engine.tick()
            args = popen.call_args.args[0]
        self.assertEqual(args[args.index("-v")+1], "Tingting")
        self.assertEqual(args[args.index("-r")+1], "230")
        self.assertEqual(args[args.index("-a")+1], "42")
        self.assertTrue(args[-1].startswith("Rico，"))

    def test_preview_is_labeled_and_does_not_fake_an_actual_reset_or_change_quota(self):
        self.engine.event({"action": "preview_usage_reset"})
        self.assertEqual(self.speaker.calls[0][0], USAGE_RESET_PREVIEW_ID)
        self.assertIn("这是额度重置提醒试听", self.speaker.calls[0][1])
        self.assertFalse(self.engine.alerts); self.assertFalse(self.engine.last_usage_reset)
        self.speaker.active = True
        self.assertTrue(self.engine.snapshot()["usageAnnouncement"]["previewing"])
        self.engine.event({"action": "stop_usage_preview"})
        self.assertFalse(self.speaker.active)

    def test_preview_respects_pause_disabled_and_busy_and_stop_does_not_stop_real_alerts(self):
        for mode in ("pause", "disabled", "busy"):
            engine = Engine(FakeSpeaker(), lambda: self.now)
            if mode == "pause": engine.event({"action": "mute"})
            elif mode == "disabled": engine.event({"action": "set_enabled", "enabled": False})
            else: engine.speaker.active = True
            engine.event({"action": "preview_usage_reset"})
            self.assertFalse(engine.speaker.calls)
            self.assertTrue(engine.snapshot()["usageAnnouncement"]["error"])
        self.speaker.alert_id = "actual-task"; self.speaker.active = True
        self.engine.event({"action": "stop_usage_preview"})
        self.assertTrue(self.speaker.active)

    def test_setting_is_validated_saved_and_restored_without_changing_other_values(self):
        for value in (None, "false", 0, []):
            self.assertFalse(self.engine.event({"action": "set_usage_reset_enabled", "enabled": value}))
            self.assertTrue(self.engine.usage_reset_enabled)
        speaker = Speaker(voice_provider=lambda: [{"id": "Tingting"}])
        engine = Engine(speaker, speech_settings={"rate": 220}, pause_minutes=37)
        self.assertTrue(engine.event({"action": "set_usage_reset_enabled", "enabled": False}))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_preferences(path, {"other": "keep"}, engine)
            saved = json.loads(path.read_text())
            restarted = Engine(FakeSpeaker(), usage_reset_enabled=saved["usage_reset_announcement"])
            self.assertFalse(restarted.usage_reset_enabled)
            self.assertEqual((saved["speech"]["rate"], saved["pause_minutes"], saved["other"]), (220, 37, "keep"))


if __name__ == "__main__":
    unittest.main()

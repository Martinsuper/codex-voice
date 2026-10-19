import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_usage import UsageLowDetector
from test_usage_reset import reading
from test_voice_engine import FakeSpeaker
from voice_engine import Engine, Speaker, USAGE_LOW_ID, USAGE_LOW_PREVIEW_ID, save_preferences


class LowDetectorTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.detector = UsageLowDetector(now=lambda: self.now)

    def detect(self, remaining, threshold=20, **kwargs):
        value = reading(100-remaining, at=self.now, **kwargs)
        return self.detector.detect(value, threshold, self.now)

    def test_strict_threshold_and_zero_balance(self):
        for remaining, warned in ((100, False), (21, False), (20, False), (19, True), (0, True)):
            self.assertEqual(self.detect(remaining) is not None, warned)

    def test_first_valid_reading_below_threshold_can_warn(self):
        event = self.detect(15)
        self.assertEqual(event["threshold"], 20)
        self.assertEqual(event["remainingPercent"], 15)

    def test_same_cycle_is_quiet_after_actual_announcement(self):
        event = self.detect(19); self.detector.mark_announced(event)
        for remaining in (18, 25, 19, 0):
            self.assertIsNone(self.detect(remaining))

    def test_each_threshold_is_a_separate_rule_but_returning_to_old_rule_is_quiet(self):
        self.detector.mark_announced(self.detect(19))
        self.assertIsNotNone(self.detect(19, threshold=30))
        self.assertIsNone(self.detect(19, threshold=10))
        self.assertIsNotNone(self.detect(9, threshold=10))
        self.assertIsNone(self.detect(9, threshold=20))

    def test_new_account_plan_or_cycle_has_its_own_warning(self):
        self.detector.mark_announced(self.detect(19))
        self.assertIsNotNone(self.detect(19, scope="account-B"))
        self.assertIsNotNone(self.detect(19, plan="plus"))
        self.assertIsNotNone(self.detect(19, reset=3000))
        self.assertIsNone(self.detect(19))

    def test_unknown_stale_signed_out_and_expired_readings_never_warn(self):
        for field in ({"state":"error"}, {"state":"signed_out"}, {"state":"loading"},
                      {"_accountKey":""}, {"fetchedAt":self.now-180}, {"fetchedAt":self.now+6},
                      {"fetchedAt":float("nan")}):
            value = reading(90); value.update(field)
            self.assertIsNone(self.detector.detect(value, 20, self.now))
        for reset in (None, 0, self.now):
            value = reading(90); value["windows"][0]["resetsAt"] = reset
            self.assertIsNone(self.detector.detect(value, 20, self.now))

    def test_invalid_thresholds_and_unknown_window_duration_are_quiet(self):
        for threshold in (None, True, "20", 0, 100, 20.5):
            self.assertIsNone(self.detector.detect(reading(90), threshold, self.now))
        value = reading(90); value["windows"][0]["windowMinutes"] = None
        self.assertIsNone(self.detector.detect(value, 20, self.now))

    def test_multiple_low_windows_merge_then_warn_only_for_new_low_cycle(self):
        value = reading(85, secondary=90)
        event = self.detector.detect(value, 20, self.now)
        self.assertEqual(len(event["windows"]), 2)
        self.assertEqual(event["remainingPercent"], 10)
        self.detector.mark_announced(event)
        updated = copy.deepcopy(value)
        updated["windows"][1]["resetsAt"] += 300*60
        event = self.detector.detect(updated, 20, self.now)
        self.assertEqual([w["id"] for w in event["windows"]], ["secondary"])

    def test_another_window_reset_does_not_repeat_existing_weekly_warning(self):
        value = reading(85, secondary=0)
        self.detector.mark_announced(self.detector.detect(value, 20, self.now))
        value["windows"][1]["resetsAt"] += 300*60
        self.assertIsNone(self.detector.detect(value, 20, self.now))

    def test_expired_second_window_blocks_partial_reading(self):
        value = reading(85, secondary=0)
        value["windows"][1]["resetsAt"] = self.now-1
        self.assertIsNone(self.detector.detect(value, 20, self.now))

    def test_warning_is_not_consumed_until_sound_actually_starts(self):
        first = self.detect(19)
        self.assertEqual(first["id"], self.detect(19)["id"])
        self.detector.mark_announced(first)
        self.assertIsNone(self.detect(19))

    def test_deduplication_survives_restart_and_contains_only_opaque_cycle_marks(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/"usage-low-alerts.json"
            first = UsageLowDetector(file, now=lambda: self.now)
            value = reading(90, scope="private-account-identity")
            event = first.detect(value, 20, self.now)
            self.assertTrue(first.mark_announced(event))
            text = file.read_text()
            self.assertNotIn("private-account-identity", text)
            self.assertNotIn("threshold", text); self.assertNotIn("_accountKey", text)
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            restarted = UsageLowDetector(file, now=lambda: self.now)
            self.assertIsNone(restarted.detect(value, 20, self.now))
            value["windows"][0]["resetsAt"] += 10080*60
            self.assertIsNotNone(restarted.detect(value, 20, self.now))

    def test_corrupt_checkpoint_falls_back_safely_and_expired_entries_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/"marks.json"
            for text in ("not-json", "[]", '{"version":1,"announced":[1]}',
                         json.dumps({"version":1,"announced":{"a"*64:999,"invalid":2000}})):
                file.write_text(text)
                detector = UsageLowDetector(file, now=lambda: self.now)
                self.assertEqual(detector.announced, {})

    def test_storage_failure_keeps_in_memory_deduplication(self):
        event = self.detect(19)
        self.detector.state_file = Path("/unavailable-parent/marks.json")
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            self.assertFalse(self.detector.mark_announced(event))
        self.assertIsNone(self.detect(19))


class LowAnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.speaker = FakeSpeaker()
        self.engine = Engine(self.speaker, lambda: self.now)
        self.detector = UsageLowDetector(now=lambda: self.now)
        self.engine.on_usage_low_spoken = self.detector.mark_announced
        self.value = reading(85)

    def check(self):
        self.value["fetchedAt"] = self.now
        event = self.detector.detect(self.value, self.engine.usage_low_threshold, self.now)
        self.engine.update_usage_low(event); self.engine.tick()

    def test_low_warning_speaks_once_without_creating_a_task(self):
        self.check()
        self.assertEqual(len(self.speaker.calls), 1)
        self.assertTrue(self.speaker.calls[0][0].startswith(USAGE_LOW_ID))
        self.assertIn("每周额度偏低", self.speaker.calls[0][1])
        self.assertIn("百分之15", self.speaker.calls[0][1]); self.assertIn("百分之20", self.speaker.calls[0][1])
        self.assertFalse(self.engine.alerts)
        self.now += 60; self.check()
        self.assertEqual(len(self.speaker.calls), 1)

    def test_existing_task_speech_has_priority(self):
        self.engine.add({"id":"urgent","kind":"question"})
        self.check(); self.assertEqual(self.speaker.calls[0][0], "urgent")
        self.speaker.active = True; self.now += 2; self.check()
        self.assertEqual(len(self.speaker.calls), 1)
        self.speaker.active = False; self.now += 2; self.check()
        self.assertTrue(self.speaker.calls[1][0].startswith(USAGE_LOW_ID))

    def test_pause_then_resume_rechecks_ongoing_low_condition(self):
        self.engine.event({"action":"mute"}); self.check()
        self.assertFalse(self.speaker.calls); self.assertFalse(self.detector.announced)
        self.engine.event({"action":"unmute"}); self.now += 2; self.check()
        self.assertEqual(len(self.speaker.calls), 1)
        self.engine.event({"action":"mute"}); self.engine.event({"action":"unmute"}); self.now += 2; self.check()
        self.assertEqual(len(self.speaker.calls), 1)

    def test_disabling_either_switch_suppresses_sound_until_reenabled(self):
        for action in ({"action":"set_enabled","enabled":False}, {"action":"set_usage_low_settings","settings":{"enabled":False}}):
            engine = Engine(FakeSpeaker(), lambda: self.now)
            engine.event(action)
            engine.update_usage_low(self.detector.detect(self.value, 20, self.now)); engine.tick()
            self.assertFalse(engine.speaker.calls)

    def test_failed_audio_is_not_marked_and_can_retry_after_reconnection(self):
        with patch.object(self.speaker, "speak", return_value=False): self.check()
        self.assertFalse(self.detector.announced)
        self.now += 2; self.check()
        self.assertEqual(len(self.speaker.calls), 1)
        self.assertTrue(self.detector.announced)

    def test_recovery_or_read_failure_cancels_a_waiting_warning(self):
        self.speaker.active = True; self.check()
        self.assertIsNotNone(self.engine.pending_usage_low)
        self.engine.update_usage_low(None); self.speaker.active = False; self.now += 2; self.engine.tick()
        self.assertFalse(self.speaker.calls)

    def test_stale_queued_data_does_not_speak(self):
        self.engine.update_usage_low(self.detector.detect(self.value, 20, self.now))
        self.now += 180; self.engine.tick()
        self.assertFalse(self.speaker.calls); self.assertIsNone(self.engine.pending_usage_low)

    def test_threshold_change_rechecks_current_data_and_respects_old_rule_dedup(self):
        self.engine.configure_usage_low({"threshold":10}); self.check(); self.assertFalse(self.speaker.calls)
        self.engine.configure_usage_low({"threshold":30}); self.check(); self.assertEqual(len(self.speaker.calls), 1)
        self.now += 2; self.engine.configure_usage_low({"threshold":10}); self.check()
        self.engine.configure_usage_low({"threshold":30}); self.check()
        self.assertEqual(len(self.speaker.calls), 1)

    def test_default_legacy_and_invalid_preferences(self):
        self.assertTrue(self.engine.usage_low_enabled); self.assertEqual(self.engine.usage_low_threshold, 20)
        for value in (None, True, 0, 100, "20", 20.5):
            engine = Engine(FakeSpeaker(), usage_low_threshold=value)
            self.assertEqual(engine.usage_low_threshold, 20)

    def test_settings_validate_atomically_and_preserve_other_preferences(self):
        for settings in (None, [], {"threshold":0}, {"threshold":100}, {"threshold":True}, {"enabled":"false"}, {"unknown":1}, {"enabled":False,"threshold":0}):
            self.assertFalse(self.engine.configure_usage_low(settings))
            self.assertEqual((self.engine.usage_low_enabled,self.engine.usage_low_threshold), (True,20))
        engine = Engine(Speaker(), speech_settings={"rate":215}, pause_minutes=37, usage_reset_enabled=False)
        self.assertTrue(engine.configure_usage_low({"enabled":False,"threshold":25}))
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/"settings.json"; save_preferences(file, {"other":"keep"}, engine)
            saved = json.loads(file.read_text())
            restarted = Engine(FakeSpeaker(), usage_low_enabled=saved["usage_low_announcement"], usage_low_threshold=saved["usage_low_threshold"])
            self.assertFalse(restarted.usage_low_enabled); self.assertEqual(restarted.usage_low_threshold,25)
            self.assertEqual((saved["speech"]["rate"], saved["pause_minutes"], saved["usage_reset_announcement"], saved["other"]),(215,37,False,"keep"))

    def test_preview_uses_saved_threshold_and_is_not_an_actual_warning(self):
        self.engine.configure_usage_low({"threshold":25})
        self.engine.event({"action":"preview_usage_low"})
        self.assertEqual(self.speaker.calls[0][0], USAGE_LOW_PREVIEW_ID)
        self.assertIn("这是低额度提醒试听",self.speaker.calls[0][1])
        self.assertIn("百分之24",self.speaker.calls[0][1]); self.assertIn("百分之25",self.speaker.calls[0][1])
        self.assertFalse(self.detector.announced); self.assertFalse(self.engine.alerts)

    def test_preview_stop_does_not_interrupt_other_reminders(self):
        self.speaker.alert_id="actual-task"; self.speaker.active=True
        self.engine.event({"action":"stop_usage_low_preview"})
        self.assertTrue(self.speaker.active)
        self.engine.event({"action":"preview_usage_low"}); self.assertFalse(self.speaker.calls)
        self.assertTrue(self.engine.usage_low_error)

    def test_preview_respects_total_off_and_pause(self):
        for action in ({"action":"set_enabled","enabled":False}, {"action":"mute"}):
            engine = Engine(FakeSpeaker(), lambda:self.now); engine.event(action)
            engine.event({"action":"preview_usage_low"}); self.assertFalse(engine.speaker.calls)

    def test_custom_voice_rate_address_and_device_are_used(self):
        speaker=Speaker("chosen",device_provider=lambda:{"connected":True,"id":42},voice_provider=lambda:[{"id":"Tingting"}])
        engine=Engine(speaker,lambda:self.now,speech_settings={"address":"Rico","rate":230})
        engine.update_usage_low(self.detector.detect(self.value,20,self.now))
        with patch("voice_engine.subprocess.Popen") as popen:
            engine.tick(); args=popen.call_args.args[0]
        self.assertEqual(args[args.index("-v")+1],"Tingting")
        self.assertEqual(args[args.index("-r")+1],"230")
        self.assertEqual(args[args.index("-a")+1],"42")
        self.assertTrue(args[-1].startswith("Rico，"))

    def test_disabled_low_switch_stops_its_own_audio_only(self):
        self.speaker.alert_id=USAGE_LOW_PREVIEW_ID; self.speaker.active=True
        self.engine.configure_usage_low({"enabled":False}); self.assertFalse(self.speaker.active)
        self.speaker.alert_id="actual-task"; self.speaker.active=True
        self.engine.configure_usage_low({"enabled":False}); self.assertTrue(self.speaker.active)


if __name__ == "__main__":
    unittest.main()

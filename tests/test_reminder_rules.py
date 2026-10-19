import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from reminder_rules import KindRule, QuietHours, load_rules, update_rules
from test_voice_engine import FakeSpeaker
from voice_engine import Engine, Speaker, save_preferences


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.speaker = FakeSpeaker()
        self.engine = Engine(self.speaker, lambda: self.now)

    def test_legacy_defaults_keep_global_schedule_and_unlimited_repeats(self):
        for rule in load_rules(None).values():
            self.assertEqual(rule, KindRule())
        self.engine.add({"id":"a","kind":"result"}); self.engine.tick()
        self.assertEqual(self.engine.alerts["a"]["nextAt"],1030)

    def test_settings_validate_atomically(self):
        bad = [{"approval":{"enabled":0}}, {"result":{"max_plays":100}}, {"question":{"max_plays":True}},
               {"blocked":{"intervals":[4,60,180]}}, {"result":{"intervals":[5,60]}}, {"other":{}}, [], None]
        for patch in bad:
            self.assertFalse(self.engine.configure_rules(patch))
            self.assertEqual(self.engine.rules,load_rules(None))
        self.assertFalse(self.engine.configure_rules({"result":{"max_plays":1},"approval":{"max_plays":-1}}))
        self.assertEqual(self.engine.rules["result"].max_plays,0)

    def test_single_and_limited_repeats_keep_cards(self):
        for cap in (1,3):
            engine=Engine(FakeSpeaker(),lambda:self.now)
            engine.configure_rules({"result":{"max_plays":cap,"intervals":[5,5,5]}})
            engine.add({"id":"r","kind":"result"})
            for _ in range(6): engine.tick(); self.now+=5
            self.assertEqual(len(engine.speaker.calls),cap)
            self.assertIn("r",engine.alerts)
            self.assertTrue(engine.snapshot()["alerts"][0]["limitReached"])

    def test_manual_replay_bypasses_limit_or_type_voice_switch(self):
        self.engine.configure_rules({"result":{"max_plays":1}})
        self.engine.add({"id":"r","kind":"result"}); self.engine.tick()
        self.now+=2; self.engine.event({"action":"replay","id":"r"}); self.engine.tick()
        self.assertEqual(len(self.speaker.calls),2)
        self.engine.configure_rules({"result":{"enabled":False}})
        self.now+=2; self.engine.tick(); self.assertEqual(len(self.speaker.calls),2)
        self.engine.event({"action":"replay","id":"r"}); self.engine.tick()
        self.assertEqual(len(self.speaker.calls),3)

    def test_custom_intervals_do_not_affect_other_types_or_global_updates(self):
        self.engine.configure_rules({"question":{"intervals":[7,11,19]}})
        self.engine.add({"id":"q","kind":"question"}); self.engine.tick()
        self.assertEqual(self.engine.alerts["q"]["nextAt"],1007)
        self.engine.configure_speech({"intervals":[8,12,20]})
        self.assertEqual(self.engine.alerts["q"]["nextAt"],1007)
        self.now=1007; self.engine.tick(); self.assertEqual(self.engine.alerts["q"]["nextAt"],1018)

    def test_changing_rules_keeps_snoozed_deadline(self):
        self.engine.add({"id":"q","kind":"question"})
        self.engine.event({"action":"snooze","id":"q","seconds":300})
        self.engine.configure_rules({"question":{"intervals":[5,5,5]}})
        self.assertEqual(self.engine.alerts["q"]["nextAt"],1300)

    def test_explicit_snooze_can_remind_again_after_a_single_play_limit(self):
        self.engine.configure_rules({"result":{"max_plays":1}})
        self.engine.add({"id":"r","kind":"result"}); self.engine.tick()
        self.engine.event({"action":"snooze","id":"r","seconds":300})
        self.now=1299; self.engine.tick(); self.assertEqual(len(self.speaker.calls),1)
        self.now=1300; self.engine.tick(); self.assertEqual(len(self.speaker.calls),2)
        self.now=1400; self.engine.tick(); self.assertEqual(len(self.speaker.calls),2)

    def test_disabling_type_keeps_card_and_stops_only_its_audio(self):
        self.engine.add({"id":"q","kind":"question"}); self.engine.tick(); self.speaker.active=True
        self.engine.configure_rules({"question":{"enabled":False}})
        self.assertFalse(self.speaker.active); self.assertIn("q",self.engine.alerts)
        self.now+=60; self.engine.tick(); self.assertEqual(len(self.speaker.calls),1)
        self.engine.configure_rules({"question":{"enabled":True}}); self.engine.tick()
        self.assertEqual(len(self.speaker.calls),2)

    def test_test_reminder_preserves_its_own_rhythm(self):
        self.engine.configure_rules({"result":{"enabled":False,"max_plays":1}})
        self.engine.event({"action":"test"}); self.engine.tick()
        alert=next(iter(self.engine.alerts.values()))
        self.assertEqual(alert["nextAt"],1005)

    def test_rule_settings_round_trip_without_losing_existing_values(self):
        engine=Engine(Speaker(),speech_settings={"rate":225},pause_minutes=42)
        engine.configure_rules({"result":{"max_plays":1},"approval":{"intervals":[5,10,30]}})
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/"settings.json"; save_preferences(file,{"other":"keep"},engine)
            saved=json.loads(file.read_text()); restored=Engine(FakeSpeaker(),reminder_rules=saved["reminder_rules"])
            self.assertEqual(restored.rules["result"].max_plays,1)
            self.assertEqual(restored.rules["approval"].intervals,(5,10,30))
            self.assertEqual((saved["speech"]["rate"],saved["pause_minutes"],saved["other"]),(225,42,"keep"))


class QuietHoursTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,10,19,9,59,58).timestamp()  # Monday, local time.
        self.speaker=FakeSpeaker(); self.engine=Engine(self.speaker,lambda:self.now)
        self.settings={"enabled":True,"start":"10:00","end":"11:00","days":[0],"allow_approval":False}

    def test_daytime_boundaries(self):
        quiet=QuietHours().update(self.settings)
        for hour,minute,expected in ((9,59,False),(10,0,True),(10,59,True),(11,0,False)):
            self.assertEqual(quiet.active_at(dt.datetime(2026,10,19,hour,minute)),expected)
        self.assertFalse(quiet.active_at(dt.datetime(2026,10,20,10,30)))

    def test_overnight_uses_the_start_day_including_week_wrap(self):
        quiet=QuietHours().update({"enabled":True,"start":"23:00","end":"09:00","days":[6]})
        self.assertTrue(quiet.active_at(dt.datetime(2026,10,18,23,30)))
        self.assertTrue(quiet.active_at(dt.datetime(2026,10,19,8,59)))
        self.assertFalse(quiet.active_at(dt.datetime(2026,10,19,9,0)))
        self.assertFalse(quiet.active_at(dt.datetime(2026,10,19,23,30)))

    def test_bad_times_days_and_switches_leave_configuration_unchanged(self):
        for patch in ({"start":"24:00"},{"end":"9:00"},{"start":"09:00","end":"09:00"},
                      {"days":[]},{"days":[0,0]},{"days":[True]},{"days":[7]},{"enabled":1},{"allow_approval":"yes"}):
            self.assertFalse(self.engine.configure_quiet(patch))
            self.assertFalse(self.engine.quiet.enabled)

    def test_all_types_are_silent_but_cards_stay_until_end(self):
        self.engine.configure_quiet(self.settings)
        self.now+=3
        for kind in ("approval","question","result","blocked"):
            self.engine.add({"id":kind,"kind":kind,"thread":kind})
        self.engine.tick(); self.assertFalse(self.speaker.calls); self.assertEqual(len(self.engine.alerts),4)
        self.now=dt.datetime(2026,10,19,11,0).timestamp(); self.engine.tick()
        self.assertEqual(len(self.speaker.calls),1)

    def test_optional_approval_exception_does_not_override_manual_pause(self):
        self.settings["allow_approval"]=True; self.engine.configure_quiet(self.settings); self.now+=3
        self.engine.add({"id":"q","kind":"question"}); self.engine.add({"id":"a","kind":"approval"})
        self.engine.event({"action":"mute"}); self.engine.tick(); self.assertFalse(self.speaker.calls)
        self.engine.event({"action":"unmute"}); self.engine.tick()
        self.assertEqual([c[0] for c in self.speaker.calls],["a"])

    def test_entering_quiet_hours_stops_audio_and_does_not_consume_single_play(self):
        self.engine.configure_rules({"result":{"max_plays":1}})
        self.engine.configure_quiet(self.settings)
        self.engine.add({"id":"r","kind":"result"}); self.engine.tick(); self.speaker.active=True
        self.now+=3; self.engine.tick()
        self.assertFalse(self.speaker.active); self.assertEqual(self.engine.alerts["r"]["count"],0)
        self.now=dt.datetime(2026,10,19,11,1).timestamp(); self.engine.tick()
        self.assertEqual(len(self.speaker.calls),2); self.assertEqual(self.engine.alerts["r"]["count"],1)

    def test_handled_cards_are_not_replayed_after_quiet_hours(self):
        self.engine.configure_quiet(self.settings); self.now+=3
        self.engine.add({"id":"r","kind":"result"}); self.engine.tick()
        self.engine.event({"action":"ack","id":"r"})
        self.now=dt.datetime(2026,10,19,11,1).timestamp(); self.engine.tick()
        self.assertFalse(self.speaker.calls)

    def test_usage_announcements_and_all_previews_respect_quiet_hours(self):
        self.engine.configure_quiet(self.settings); self.now+=3
        self.engine.usage_reset({"id":"reset","at":self.now,"remainingPercent":100,"windows":[]})
        self.assertFalse(self.engine.usage_reset_queue)
        for action in ("preview","preview_usage_reset","preview_usage_low"):
            self.engine.event({"action":action})
        self.assertFalse(self.speaker.calls)

    def test_prepare_sleep_state_suppresses_every_preview(self):
        self.engine.sleeping=True
        for action in ("preview","preview_usage_reset","preview_usage_low"):
            self.engine.event({"action":action})
        self.assertFalse(self.speaker.calls)

    def test_quiet_preferences_persist_and_restore(self):
        engine=Engine(Speaker()); engine.configure_quiet(self.settings)
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/"settings.json"; save_preferences(file,{"other":"keep"},engine)
            saved=json.loads(file.read_text()); restored=Engine(FakeSpeaker(),quiet_hours=saved["quiet_hours"])
            self.assertEqual(restored.quiet.to_dict(),engine.quiet.to_dict())
            self.assertEqual(saved["other"],"keep")


if __name__=="__main__": unittest.main()

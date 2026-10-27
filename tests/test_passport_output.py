import unittest
from passport_output import PassportOutput, PASSPORT_UID
from voice_engine import Engine, Speaker, RolloutAdapter


class PassportTests(unittest.TestCase):
    def output(self, response=None):
        sent = []
        device = PassportOutput(timeout=.03)
        def emit(event):
            sent.append(event)
            if event["op"] == "play" and response:
                device.feedback({"kind": "audio", "id": event["id"], "phase": response})
        device.emit = emit
        device.feedback({"kind": "link", "connected": True})
        return device, sent

    def test_disconnected_device_does_not_consume_a_play(self):
        device, sent = self.output()
        device.feedback({"kind": "link", "connected": False})
        self.assertFalse(device.speak("a", "question"))
        self.assertEqual(sent, [])

    def test_only_actual_start_acknowledges_playback(self):
        device, sent = self.output("started")
        self.assertTrue(device.speak("a", "approval"))
        self.assertTrue(device.busy())
        device.feedback({"kind": "audio", "id": sent[0]["id"], "phase": "done"})
        self.assertFalse(device.busy())
        self.assertEqual(sent[0]["phrase"], "approval")
        self.assertNotIn("text", sent[0])

    def test_timeout_and_failures_do_not_consume_a_play(self):
        for response in (None, "failed"):
            device, sent = self.output(response)
            self.assertFalse(device.speak("a", "result"))
            self.assertEqual(sent[-1]["op"], "stop")
            self.assertFalse(device.busy())

    def test_wrong_play_id_cannot_acknowledge_another_play(self):
        device, sent = self.output()
        device.emit = lambda event: device.feedback({"kind": "audio", "id": "wrong", "phase": "started"})
        self.assertFalse(device.speak("a", "result"))

    def test_link_heartbeats_do_not_hide_playback_failure(self):
        device, sent = self.output("failed")
        self.assertFalse(device.speak("a", "result"))
        device.feedback({"kind": "link", "connected": True, "error": ""})
        self.assertIn("未能播放", device.status()["error"])

    def test_disconnect_stops_busy_and_older_stop_does_not_cancel_new_alert(self):
        device, sent = self.output("started")
        device.speak("a", "question")
        device.stop("other")
        self.assertTrue(device.busy())
        device.feedback({"kind": "link", "connected": False})
        self.assertFalse(device.busy())


    def piko_output(self, response=None):
        sent = []
        device = PassportOutput(timeout=.03)
        def emit(event):
            sent.append(event)
            if event["op"] == "play" and response:
                device.feedback({"kind": "audio", "id": event["id"], "phase": response})
        device.emit = emit
        device.feedback({"kind": "piko", "connected": True})
        return device, sent

    def test_piko_connection_enables_playback_with_transport(self):
        device, sent = self.piko_output("started")
        self.assertTrue(device.route() == "piko")
        self.assertTrue(device.speak("a", "question"))
        self.assertEqual(sent[0]["transport"], "piko")
        device.feedback({"kind": "audio", "id": sent[0]["id"], "phase": "done"})
        self.assertFalse(device.busy())

    def test_ble_connection_wins_when_both_links_are_live(self):
        device, sent = self.piko_output("started")
        device.feedback({"kind": "link", "connected": True})
        self.assertEqual(device.route(), "ble")
        self.assertTrue(device.speak("a", "result"))
        self.assertEqual(sent[0]["transport"], "ble")

    def test_piko_disconnect_fails_the_running_play(self):
        device, sent = self.piko_output()
        device.emit = lambda event: device.feedback(
            {"kind": "audio", "id": event["id"], "phase": "started"}
        ) if event.get("transport") == "piko" else None
        self.assertTrue(device.speak("a", "result"))
        self.assertTrue(device.busy())
        device.feedback({"kind": "piko", "connected": False})
        self.assertFalse(device.busy())
        self.assertFalse(device.speak("a", "result"))

    def test_muted_volume_only_gates_the_ble_route(self):
        device, sent = self.piko_output("started")
        device.feedback({"kind": "link", "connected": True, "volume": 0})
        self.assertTrue(device.speak("a", "result"))
        self.assertEqual(sent[0]["transport"], "piko")

    def test_engine_retains_alert_and_counter_until_device_starts(self):
        speaker = Speaker(device_uid=PASSPORT_UID, voice_provider=lambda: [])
        speaker.passport, sent = self.output("failed")
        engine = Engine(speaker, now=lambda: 1000)
        engine.add({"id": "a", "kind": "question", "title": "测试任务"})
        engine.tick()
        self.assertEqual(engine.alerts["a"]["count"], 0)
        speaker.passport, sent = self.output("started")
        engine.tick()
        self.assertEqual(engine.alerts["a"]["count"], 1)
        self.assertEqual(sent[0]["phrase"], "question")
        engine.event({"action": "ack", "id": "a"})
        self.assertFalse(engine.alerts)
        self.assertEqual(sent[-1]["op"], "stop")

    def test_observed_activity_closes_on_turn_completion(self):
        speaker = Speaker(voice_provider=lambda: [])
        engine = Engine(speaker, now=lambda: 1000)
        adapter = RolloutAdapter(engine, "/tmp/nonexistent")
        cursor = {"thread": "one", "turn": "", "question": False}
        adapter.record({"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t"}}, cursor)
        self.assertEqual(len(engine.snapshot()["activeTasks"]), 1)
        adapter.record({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "t"}}, cursor)
        self.assertEqual(engine.snapshot()["activeTasks"], [])

    def test_dictation_queues_reminders_without_consuming_them(self):
        device, sent = self.output("started")
        device.feedback({"kind":"dictation", "active":True})
        self.assertTrue(device.busy())
        self.assertFalse(device.speak("a", "result"))
        self.assertEqual(sent, [])
        device.feedback({"kind":"dictation", "active":False})
        self.assertFalse(device.busy())
        self.assertTrue(device.speak("a", "result"))

    def test_dictation_busy_clears_on_disconnect(self):
        device, sent = self.output("started")
        device.feedback({"kind":"dictation", "active":True})
        device.feedback({"kind":"link", "connected":False})
        self.assertFalse(device.busy())
        self.assertFalse(device.dictating)

    def test_fixed_speech_does_not_require_an_installed_mac_voice(self):
        speaker = Speaker(device_uid=PASSPORT_UID, voice_provider=lambda: [])
        speaker.passport.feedback({"kind": "link", "connected": True})
        self.assertTrue(speaker.speech_status()["ready"])


if __name__ == "__main__":
    unittest.main()

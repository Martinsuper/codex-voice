import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_voice_engine import FakeSpeaker
from voice_engine import Engine, Speaker, save_preferences


class PauseDurationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.speaker = FakeSpeaker()
        self.engine = Engine(self.speaker, lambda: self.now)

    def test_legacy_or_invalid_saved_duration_uses_fifteen_minutes(self):
        for value in [None, True, '30', 0, -1, 1441, 1.5]:
            with self.subTest(value=value):
                engine = Engine(FakeSpeaker(), pause_minutes=value, speech_settings={'rate': 220})
                self.assertEqual(engine.pause_minutes, 15)
                self.assertEqual(engine.speech.rate, 220)
        self.engine.event({'action': 'mute'})
        self.assertEqual(self.engine.muted_until, 1900)

    def test_custom_pause_stops_speech_keeps_items_and_resumes_at_expiry(self):
        self.engine.add({'id': 'approval', 'thread': 'one', 'kind': 'approval'})
        self.engine.add({'id': 'result', 'thread': 'two', 'kind': 'result'})
        self.speaker.active = True
        self.assertTrue(self.engine.event({'action': 'pause', 'minutes': 42}))
        self.assertFalse(self.speaker.active)
        self.assertEqual(self.engine.muted_until, 3520)
        self.assertEqual(self.engine.pause_minutes, 42)
        self.assertEqual(set(self.engine.alerts), {'approval', 'result'})
        self.now = 3519
        self.engine.tick()
        self.assertFalse(self.speaker.calls)
        self.now = 3520
        self.engine.tick()
        self.assertEqual(self.speaker.calls[0][0], 'approval')

    def test_saving_duration_does_not_change_an_existing_pause_or_interrupt_audio(self):
        self.engine.event({'action': 'pause', 'minutes': 20})
        until = self.engine.muted_until
        self.now += 10
        with patch.object(self.speaker, 'stop') as stop:
            self.assertTrue(self.engine.event({'action': 'set_pause_duration', 'minutes': 90}))
            stop.assert_not_called()
        self.assertEqual(self.engine.muted_until, until)
        self.assertEqual(self.engine.pause_minutes, 90)

    def test_resume_and_one_click_pause_use_last_selected_duration(self):
        self.engine.event({'action': 'pause', 'minutes': 37})
        self.engine.event({'action': 'unmute'})
        self.assertEqual(self.engine.muted_until, 0)
        self.now += 5
        self.engine.event({'action': 'mute'})
        self.assertEqual(self.engine.muted_until, self.now + 37 * 60)
        self.engine.event({'action': 'mute', 'seconds': 17.5})
        self.assertEqual(self.engine.muted_until, self.now + 17.5)
        self.assertEqual(self.engine.pause_minutes, 37)

    def test_invalid_durations_do_not_change_timer_preferences_or_stop_speech(self):
        self.engine.event({'action': 'pause', 'minutes': 30})
        until = self.engine.muted_until
        for value in [None, True, '20', 0, -1, 1441, 1.5, float('nan'), float('inf')]:
            for action in ['pause', 'set_pause_duration']:
                with self.subTest(action=action, value=value), patch.object(self.speaker, 'stop') as stop:
                    self.assertFalse(self.engine.event({'action': action, 'minutes': value}))
                    stop.assert_not_called()
                    self.assertEqual(self.engine.pause_minutes, 30)
                    self.assertEqual(self.engine.muted_until, until)
                    self.assertTrue(self.engine.snapshot()['pause']['error'])

    def test_minimum_and_maximum_and_disabled_configuration(self):
        self.assertTrue(self.engine.event({'action': 'pause', 'minutes': 1}))
        self.assertEqual(self.engine.muted_until, 1060)
        self.assertTrue(self.engine.event({'action': 'pause', 'minutes': 1440}))
        self.assertEqual(self.engine.muted_until, 87400)
        self.engine.event({'action': 'set_enabled', 'enabled': False})
        self.assertTrue(self.engine.event({'action': 'set_pause_duration', 'minutes': 60}))
        until = self.engine.muted_until
        self.assertFalse(self.engine.event({'action': 'pause', 'minutes': 90}))
        self.assertEqual((self.engine.pause_minutes, self.engine.muted_until), (60, until))

    def test_invalid_legacy_seconds_do_not_crash_or_change_the_current_pause(self):
        self.engine.event({'action': 'mute', 'seconds': 300})
        for value in [None, True, 0, -1, 86401, 'invalid', float('nan'), float('inf')]:
            with self.subTest(value=value), patch.object(self.speaker, 'stop') as stop:
                self.assertFalse(self.engine.event({'action': 'mute', 'seconds': value}))
                stop.assert_not_called()
                self.assertEqual(self.engine.muted_until, 1300)

    def test_saved_duration_survives_restart_and_preserves_other_preferences(self):
        speaker = Speaker('USB 扬声器', device_uid='usb', voice_provider=lambda: [{'id': 'Tingting'}])
        engine = Engine(speaker, enabled=False, speech_settings={'address': 'Rico'})
        self.assertTrue(engine.event({'action': 'set_pause_duration', 'minutes': 75}))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            save_preferences(path, {'other': 'keep'}, engine)
            saved = json.loads(path.read_text())
            restarted = Engine(FakeSpeaker(), enabled=saved['enabled'], speech_settings=saved['speech'], pause_minutes=saved['pause_minutes'])
            self.assertEqual(restarted.pause_minutes, 75)
            self.assertFalse(restarted.enabled)
            self.assertEqual(restarted.speech.address, 'Rico')
            self.assertEqual((saved['audio_device'], saved['audio_device_uid'], saved['other']), ('USB 扬声器', 'usb', 'keep'))


if __name__ == '__main__':
    unittest.main()

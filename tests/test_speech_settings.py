import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from speech_settings import SpeechSettings, parse_voices
from voice_engine import Engine, PREVIEW_ID, Speaker, save_preferences
from test_voice_engine import FakeSpeaker


class SpeechSettingsTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.speaker = FakeSpeaker()
        self.engine = Engine(self.speaker, lambda: self.now)

    def test_old_profile_retains_original_defaults(self):
        self.assertEqual(SpeechSettings.load(None).to_dict(), {
            'voice': 'Tingting', 'rate': 185, 'address': '老板', 'intervals': [30, 60, 180]})

    def test_damaged_saved_fields_fall_back_independently(self):
        settings = SpeechSettings.load({'voice': 'Tingting', 'rate': False, 'address': 'Rico', 'intervals': [5, '10', 20]})
        self.assertEqual((settings.rate, settings.address, settings.intervals), (185, 'Rico', (30, 60, 180)))
        self.assertEqual(SpeechSettings.load(['not a settings object']), SpeechSettings())

    def test_invalid_update_is_atomic_and_never_discards_current_reminders(self):
        self.engine.add({'id': 'a', 'kind': 'approval'})
        for bad in [None, {'rate': True}, {'rate': 200.5}, {'rate': 301}, {'address': 'Rico\n'},
                    {'address': '[[rate 1]]'}, {'address': '字' * 21}, {'voice': '\nTingting'},
                    {'intervals': [4, 60, 180]}, {'intervals': [5, 60]}, {'intervals': [5, 60, float('inf')]}]:
            with self.subTest(bad=bad):
                self.assertFalse(self.engine.event({'action': 'set_speech_settings', 'settings': bad}))
                self.assertEqual(self.engine.speech, SpeechSettings())
                self.assertIn('a', self.engine.alerts)
                self.assertTrue(self.engine.snapshot()['speech']['settingsError'])

    def test_custom_intervals_repeat_last_stage_until_acknowledged(self):
        self.engine.configure_speech({'intervals': [7, 11, 19]})
        self.engine.add({'id': 'a'})
        for timestamp, next_at in [(1000, 1007), (1007, 1018), (1018, 1037), (1037, 1056)]:
            self.now = timestamp
            self.engine.tick()
            self.assertEqual(self.engine.alerts['a']['nextAt'], next_at)
        self.engine.event({'action': 'ack', 'id': 'a'})
        self.now = 2000
        self.engine.tick()
        self.assertEqual(len(self.speaker.calls), 4)

    def test_interval_change_keeps_snooze_and_does_not_replay_new_reminders(self):
        for key in ['pending', 'snoozed', 'new']:
            self.engine.add({'id': key, 'kind': 'question', 'delay': 200 if key == 'new' else 0})
        self.engine.tick()
        self.now += 2
        self.engine.tick()
        self.engine.event({'action': 'snooze', 'id': 'snoozed', 'seconds': 300})
        self.now += 10
        self.engine.configure_speech({'intervals': [5, 10, 20]})
        self.assertEqual(self.engine.alerts['pending']['nextAt'], self.now)
        self.assertEqual(self.engine.alerts['snoozed']['nextAt'], 1302)
        self.assertEqual(self.engine.alerts['new']['nextAt'], 1200)
        self.assertEqual(len(self.speaker.calls), 2)

    def test_custom_address_and_empty_address_change_only_spoken_prefix(self):
        self.engine.configure_speech({'address': ' Rico '})
        self.engine.add({'id': 'a', 'kind': 'approval', 'title': '课程任务'})
        self.engine.tick()
        self.assertEqual(self.speaker.calls[-1][1], 'Rico，课程任务，需要你审批。')
        self.engine.configure_speech({'address': ''})
        self.now += 30
        self.engine.tick()
        self.assertEqual(self.speaker.calls[-1][1], '课程任务，需要你审批。')

    def test_voice_change_does_not_interrupt_or_repeat_current_reminder(self):
        self.engine.add({'id': 'a'})
        self.engine.tick()
        self.speaker.active = True
        self.engine.configure_speech({'rate': 240, 'address': '同学'})
        self.assertTrue(self.speaker.active)
        self.assertEqual(self.engine.alerts['a']['count'], 1)
        self.assertEqual(self.engine.alerts['a']['nextAt'], 1030)

    def test_audition_is_one_shot_and_preserves_real_alerts(self):
        self.engine.add({'id': 'a', 'delay': 300})
        self.engine.event({'action': 'preview'})
        self.assertEqual(self.speaker.calls, [(PREVIEW_ID, '老板，这是当前的播报声音。')])
        self.assertEqual(list(self.engine.alerts), ['a'])
        self.assertEqual(self.engine.alerts['a']['count'], 0)
        self.now += 40
        self.engine.tick()
        self.assertEqual(len(self.speaker.calls), 1)

    def test_audition_respects_pause_disable_and_active_real_speech(self):
        self.engine.event({'action': 'mute', 'seconds': 900})
        self.engine.event({'action': 'preview'})
        self.assertFalse(self.speaker.calls)
        self.engine.event({'action': 'unmute'})
        self.engine.event({'action': 'set_enabled', 'enabled': False})
        self.engine.event({'action': 'preview'})
        self.assertFalse(self.speaker.calls)
        self.engine.event({'action': 'set_enabled', 'enabled': True})
        self.engine.add({'id': 'a'})
        self.engine.tick()
        self.speaker.active = True
        self.engine.event({'action': 'preview'})
        self.assertTrue(self.speaker.active)
        self.assertEqual(len(self.speaker.calls), 1)
        self.assertTrue(self.engine.snapshot()['speech']['previewError'])

    def test_stop_audition_never_stops_an_actual_reminder(self):
        self.engine.add({'id': 'a'})
        self.engine.tick()
        self.speaker.active = True
        self.engine.event({'action': 'stop_preview'})
        self.assertTrue(self.speaker.active)
        self.speaker.alert_id = PREVIEW_ID
        self.engine.event({'action': 'stop_preview'})
        self.assertFalse(self.speaker.active)

    def test_preferences_round_trip_preserves_device_enabled_and_unrelated_fields(self):
        speaker = Speaker('USB 扬声器', device_uid='usb-speaker', voice_provider=lambda: [{'id': 'Tingting'}])
        engine = Engine(speaker, enabled=False)
        self.assertTrue(engine.configure_speech({'rate': 230, 'address': '', 'intervals': [15, 45, 90]}))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'settings.json'
            save_preferences(path, {'other': 'keep'}, engine)
            saved = json.loads(path.read_text())
            restarted = Engine(FakeSpeaker(), enabled=saved['enabled'], speech_settings=saved['speech'])
            self.assertEqual(restarted.speech, engine.speech)
            self.assertFalse(restarted.enabled)
            self.assertEqual((saved['audio_device'], saved['audio_device_uid'], saved['other']), ('USB 扬声器', 'usb-speaker', 'keep'))

    def test_system_voice_list_parses_localized_names_and_deduplicates(self):
        voices = parse_voices('''Tingting (中文（中国大陆）) zh_CN # 你好
Tingting (中文（中国大陆）) zh_CN # 你好
Eddy (中文（中国大陆）) zh_CN # 你好
Eddy (英语（美国）) en_US # Hello
Bad News en_US # Hello
invalid line''')
        self.assertEqual(len(voices), 4)
        self.assertEqual(voices[0]['id'], 'Tingting')
        self.assertEqual(voices[1]['id'], 'Eddy (中文（中国大陆）)')
        self.assertIn('Eddy (英语（美国）)', [voice['id'] for voice in voices])

    def test_selected_voice_and_rate_reach_say_without_shell_interpolation(self):
        voice = 'Eddy (中文（中国大陆）)'
        speaker = Speaker(device_provider=lambda: {'connected': True}, voice_provider=lambda: [{'id': voice}])
        engine = Engine(speaker)
        self.assertTrue(engine.configure_speech({'voice': voice, 'rate': 210}))
        with patch('voice_engine.subprocess.Popen') as popen:
            self.assertTrue(speaker.speak('a', '-o 不应成为命令参数'))
            args = popen.call_args.args[0]
            self.assertEqual(args, ['/usr/bin/say', '-v', voice, '-r', '210', '--', '-o 不应成为命令参数'])

    def test_unavailable_voice_does_not_fall_back_or_count_as_spoken(self):
        speaker = Speaker(device_provider=lambda: {'connected': True}, voice_provider=lambda: [{'id': 'Tingting'}])
        engine = Engine(speaker, speech_settings={'voice': 'Removed voice'})
        engine.add({'id': 'a'})
        with patch('voice_engine.subprocess.Popen') as popen:
            engine.tick()
            popen.assert_not_called()
        self.assertEqual(engine.alerts['a']['count'], 0)
        self.assertFalse(engine.snapshot()['speech']['ready'])
        self.assertFalse(engine.configure_speech({'voice': 'Not installed'}))
        self.assertTrue(engine.configure_speech({'voice': 'Tingting'}))
        self.assertTrue(engine.snapshot()['speech']['ready'])


if __name__ == '__main__':
    unittest.main()

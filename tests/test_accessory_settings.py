import unittest
from unittest.mock import patch
from accessory_settings import PassportSettings,migrate_preferences
from passport_output import PASSPORT_UID,PassportOutput
from voice_engine import Speaker,Engine

class Process:
    def __init__(self): self.stopped=False
    def poll(self): return 0 if self.stopped else None
    def terminate(self): self.stopped=True

class AccessoryTests(unittest.TestCase):
    def speaker(self,computer=True,badge=True,voice=True,remote=True):
        s=Speaker(device_provider=lambda:{'connected':True,'name':'Mac','id':1,'devices':[{'name':'Mac','uid':'mac','connected':True}]},voice_provider=lambda:[{'id':'Tingting','name':'Tingting'}])
        sent=[]
        def emit(event):
            sent.append(event)
            if event['op']=='play': s.passport.feedback({'kind':'audio','id':event['id'],'phase':'started'})
        s.passport=PassportOutput(emit,timeout=.05)
        s.configure_passport({'enabled':badge,'voiceEnabled':voice,'petName':'那个谁'})
        s.configure_computer(computer)
        s.passport.feedback({'kind':'link','connected':remote})
        return s,sent

    def test_fresh_install_keeps_computer_and_no_radio(self):
        v=migrate_preferences({'other':'preserved'})
        self.assertTrue(v['computer_audio_enabled']);self.assertFalse(v['passport']['enabled']);self.assertEqual(v['other'],'preserved');self.assertEqual(v['passport']['petName'],'Codex')
    def test_legacy_badge_migration_preserves_existing_hearing_behavior(self):
        v=migrate_preferences({'audio_device':'badge','audio_device_uid':PASSPORT_UID})
        self.assertFalse(v['computer_audio_enabled']);self.assertTrue(v['passport']['enabled']);self.assertTrue(v['passport']['voiceEnabled']);self.assertEqual(v['audio_device_uid'],'');self.assertEqual(v['passport']['petName'],'Codex')
        self.assertEqual(v,migrate_preferences(v))
    def test_new_default_preserves_existing_custom_nickname(self):
        for name in ['那个谁','Momo']:
            raw={'passport':{'enabled':True,'voiceEnabled':False,'petName':name},'computer_audio_enabled':True}
            migrated=migrate_preferences(raw)
            self.assertEqual(migrated['passport']['petName'],name)
            self.assertEqual(migrate_preferences(migrated),migrated)
        self.assertEqual(PassportSettings().update({'petName':'小蓝'}).petName,'小蓝')
    def test_validation_is_atomic(self):
        v=PassportSettings(enabled=True)
        for patch in [{'enabled':'false'},{'petName':''},{'petName':'123456789'},{'petName':'名字\n'},{'petName':'😀'},{'voiceEnabled':1}]:
            with self.assertRaises(ValueError):v.update(patch)
        self.assertTrue(v.enabled)
    def test_four_output_combinations(self):
        for computer,badge_voice in [(True,False),(False,True),(True,True),(False,False)]:
            with self.subTest(computer=computer,badge=badge_voice):
                s,sent=self.speaker(computer=computer,voice=badge_voice)
                with patch('voice_engine.subprocess.Popen',return_value=Process()) as say:
                    started=s.speak_kind('a','测试','result')
                self.assertEqual(say.call_count,int(computer));self.assertEqual(len([e for e in sent if e['op']=='play']),int(badge_voice));self.assertEqual(started,computer or badge_voice)
    def test_badge_offline_does_not_stop_computer(self):
        s,sent=self.speaker(remote=False)
        with patch('voice_engine.subprocess.Popen',return_value=Process()) as say:self.assertTrue(s.speak_kind('a','测试','result'))
        self.assertEqual(say.call_count,1);self.assertTrue(s.busy())
    def test_computer_failure_still_delivers_badge(self):
        s,sent=self.speaker()
        with patch('voice_engine.subprocess.Popen',side_effect=OSError):self.assertTrue(s.speak_kind('a','测试','question'))
        self.assertEqual(sent[0]['op'],'play')
    def test_disable_one_route_keeps_other_playing(self):
        s,sent=self.speaker();p=Process()
        with patch('voice_engine.subprocess.Popen',return_value=p):self.assertTrue(s.speak_kind('a','测试','result'))
        s.configure_computer(False);self.assertTrue(p.stopped);self.assertTrue(s.passport.busy())
        self.assertFalse(any(e['op']=='stop' for e in sent))
        s.configure_passport({'voiceEnabled':False});self.assertFalse(s.passport.busy());self.assertTrue(s.passport.ready())
    def test_badge_voice_off_retains_connection_and_dictation_gate(self):
        s,sent=self.speaker(computer=True,voice=False)
        self.assertTrue(s.passport_status()['connected']);s.passport_feedback({'kind':'dictation','active':True});self.assertTrue(s.busy())
        with patch('voice_engine.subprocess.Popen') as say:self.assertFalse(s.speak_kind('a','测试','result'))
        say.assert_not_called();self.assertEqual(sent,[])
    def test_dictionary_capture_interrupts_computer_without_new_reminder(self):
        s,sent=self.speaker();p=Process()
        with patch('voice_engine.subprocess.Popen',return_value=p):self.assertTrue(s.speak_kind('a','测试','result'))
        s.passport_feedback({'kind':'dictation','active':True});self.assertTrue(p.stopped)
    def test_passport_test_does_not_also_play_computer(self):
        s,sent=self.speaker();e=Engine(s,now=lambda:1000);e.event({'action':'test','target':'passport'})
        with patch('voice_engine.subprocess.Popen') as say:e.tick()
        say.assert_not_called();self.assertEqual(len([x for x in sent if x['op']=='play']),1);self.assertEqual(next(iter(e.alerts.values()))['count'],1)
    def test_badge_not_in_computer_output_picker(self):
        s,_=self.speaker();self.assertNotIn(PASSPORT_UID,[d['uid'] for d in s.audio_status()['devices']])
    def test_invalid_setting_does_not_change_running_routes(self):
        s,_=self.speaker();e=Engine(s)
        self.assertFalse(e.event({'action':'set_passport_settings','settings':{'enabled':'off'}}));self.assertTrue(s.passport_settings.enabled)
    def test_changing_computer_output_does_not_replay_delivered_badge(self):
        s,sent=self.speaker();e=Engine(s,now=lambda:1000);e.event({'action':'test'})
        with patch('voice_engine.subprocess.Popen',return_value=Process()):e.tick()
        alert=next(iter(e.alerts.values()));self.assertEqual(alert['count'],1)
        e.event({'action':'set_audio_device','device':'Other','uid':'other'})
        self.assertEqual(alert['count'],1);self.assertEqual(alert['nextAt'],1005)
        self.assertEqual(len([x for x in sent if x['op']=='play']),1)
        self.assertFalse(any(x['op']=='stop' for x in sent))
    def test_pet_progress_keeps_nickname_and_drops_transport_secrets(self):
        s,_=self.speaker();s.passport_feedback({'kind':'pet','state':'transferring','progress':32,'sha':'a'*64,'url':'https://private.invalid/?token=secret','detail':'https://private.invalid/?token=secret'})
        v=s.passport_status();self.assertEqual(v['petName'],'那个谁');self.assertEqual(v['petSync']['progress'],32)
        self.assertNotIn('token=secret',str(v));self.assertNotIn('url',v['petSync'])

if __name__=='__main__':unittest.main()

import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from voice_engine import Engine, RolloutAdapter, Speaker, handle_agent, handle_hook, save_preferences
from voice_bridge import effective_reviewer


class FakeSpeaker:
    def __init__(self): self.calls = []; self.alert_id = None; self.active = False
    def busy(self): return self.active
    def speak(self, key, text): self.calls.append((key,text)); self.alert_id = key; return True
    def stop(self, key=None):
        if key is None or self.alert_id == key: self.active = False; self.alert_id = None


class Tests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0; self.speaker = FakeSpeaker(); self.e = Engine(self.speaker, lambda:self.now)
    def add(self, key="a", thread="one", kind="question"):
        self.e.add({"id":key,"thread":thread,"kind":kind,"title":"课程任务"})
    def test_backoff_and_ack(self):
        self.add(); self.e.tick(); self.assertEqual(self.e.alerts['a']['nextAt'],1030)
        self.now=1029;self.e.tick();self.assertEqual(len(self.speaker.calls),1)
        self.now=1030;self.e.tick();self.assertEqual(self.e.alerts['a']['nextAt'],1090)
        self.e.event({'action':'ack','id':'a'});self.now=2000;self.e.tick();self.assertEqual(len(self.speaker.calls),2)
        self.add();self.assertFalse(self.e.alerts) # Duplicate cannot undo acknowledgement.
    def test_snooze_cancels_current_speech(self):
        self.add();self.e.tick();self.speaker.active=True
        self.e.event({'action':'snooze','id':'a','seconds':300});self.assertFalse(self.speaker.busy())
        self.now=1299;self.e.tick();self.assertEqual(len(self.speaker.calls),1)
        self.now=1300;self.e.tick();self.assertEqual(len(self.speaker.calls),2)
    def test_separate_chats_and_requests(self):
        self.add();self.add('b','two');self.e.resolve_thread('one');self.assertEqual(list(self.e.alerts),['b'])
        self.e.alerts['b']['requestId']='B';self.e.event({'action':'resolve_request','thread':'two','requestId':'A'});self.assertIn('b',self.e.alerts)
    def test_replay_resumes_same_snoozed_reminder(self):
        self.add();self.e.tick()
        self.e.event({'action':'snooze','id':'a','seconds':300})
        self.now+=2;self.e.event({'action':'replay','id':'a'});self.e.tick()
        self.assertEqual(list(self.e.alerts),['a'])
        self.assertEqual(self.e.alerts['a']['state'],'pending')
        self.assertEqual(self.e.alerts['a']['count'],2)
    def test_replay_respects_pause_and_resolved_reminders(self):
        self.add();self.e.event({'action':'mute','seconds':900})
        self.e.event({'action':'replay','id':'a'});self.e.tick();self.assertFalse(self.speaker.calls)
        self.e.event({'action':'ack','id':'a'});self.e.event({'action':'replay','id':'a'})
        self.assertFalse(self.e.alerts)
    def test_priority_serialization_and_mute(self):
        self.add('a',kind='result');self.add('b',kind='approval');self.e.tick();self.assertEqual(self.speaker.calls[0][0],'b')
        self.e.event({'action':'mute','seconds':900});self.now=1500;self.e.tick();self.assertEqual(len(self.speaker.calls),1)
        self.e.event({'action':'unmute'});self.e.tick();self.assertEqual(len(self.speaker.calls),2)
    def test_new_reply_clears_only_that_chat(self):
        self.add();self.add('b','two');adapter=RolloutAdapter(self.e,'/tmp/nonexistent')
        adapter.record({'type':'event_msg','payload':{'type':'task_started','turn_id':'t','turn_attribution':{'turn_trigger':'composer'}}},{'thread':'one','turn':'','question':False})
        self.assertEqual(list(self.e.alerts),['b'])
    def test_hook_auto_review_never_claims_human_approval(self):
        adapter=RolloutAdapter(self.e,'/tmp/nonexistent');raw={'hook_event_name':'PermissionRequest','session_id':'one','tool_use_id':'tool','voice_reviewer':'unknown'}
        handle_hook(raw,self.e,adapter);self.assertFalse(self.e.alerts)
        raw['voice_reviewer']='user';handle_hook(raw,self.e,adapter);self.assertEqual(len(self.e.alerts),1)
    def test_async_tool_return_is_not_a_user_answer(self):
        adapter=RolloutAdapter(self.e,'/tmp/nonexistent');raw={'hook_event_name':'PreToolUse','session_id':'one','tool_use_id':'q','tool_name':'request_user_input_async'}
        handle_hook(raw,self.e,adapter);raw['hook_event_name']='PostToolUse';handle_hook(raw,self.e,adapter);self.assertEqual(len(self.e.alerts),1)
        raw['hook_event_name']='UserPromptSubmit';handle_hook(raw,self.e,adapter);self.assertFalse(self.e.alerts)
    def test_internal_continuation_does_not_acknowledge(self):
        self.add();adapter=RolloutAdapter(self.e,'/tmp/nonexistent')
        adapter.record({'type':'event_msg','payload':{'type':'task_started','turn_id':'t','turn_attribution':{'turn_trigger':'stop_hook'}}},{'thread':'one','turn':'','question':False})
        self.assertIn('a',self.e.alerts)
    def test_interrupt_and_complete_are_distinct(self):
        self.add();adapter=RolloutAdapter(self.e,'/tmp/nonexistent')
        adapter.record({'type':'event_msg','payload':{'type':'turn_aborted'}},{'thread':'one','turn':'t','question':False});self.assertFalse(self.e.alerts)
        adapter.record({'type':'event_msg','payload':{'type':'task_complete','turn_id':'t'}},{'thread':'one','turn':'t','question':False})
        self.assertEqual(next(iter(self.e.alerts.values()))['kind'],'result')
    def test_busy_speaker_does_not_queue_stale_audio(self):
        self.add();self.speaker.active=True;self.e.tick();self.assertFalse(self.speaker.calls)
        self.e.resolve('a');self.speaker.active=False;self.e.tick();self.assertFalse(self.speaker.calls)
    def test_actual_async_answer_resolves_exact_question(self):
        adapter=RolloutAdapter(self.e,'/tmp/nonexistent');cursor={'thread':'one','turn':'t','question':True}
        for key in ['q1','q2']:
            self.e.add({'id':key,'thread':'one','kind':'question','requestId':key})
        content=json.dumps([{'questionItemId':json.dumps(['request_user_input_async','q1',0]),'answer':'测试回答'}])
        adapter.record({'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'<send_user_message_question_reply>'+content+'</send_user_message_question_reply>'}]}},cursor)
        self.assertEqual(list(self.e.alerts),['q2']);self.assertTrue(cursor['question'])
    def test_missing_named_speaker_never_falls_back(self):
        speaker=Speaker('测试蓝牙音箱',device_provider=lambda:['Mac mini扬声器'])
        self.assertFalse(speaker.speak('a','老板，测试。'))
        self.assertFalse(speaker.available);self.assertIsNone(speaker.process)
    def test_named_speaker_can_reconnect(self):
        devices=[];speaker=Speaker('测试蓝牙音箱',device_provider=lambda:devices)
        self.assertFalse(speaker.audio_status()['available'])
        devices.append('测试蓝牙音箱');speaker.next_device_check=0
        self.assertTrue(speaker.audio_status()['available'])
    def test_muted_speaker_does_not_report_spoken(self):
        speaker=Speaker('测试蓝牙音箱',device_provider=lambda:['测试蓝牙音箱']);speaker.muted=True
        e=Engine(speaker,lambda:1000)
        e.add({'id':'a','kind':'question'});e.tick()
        self.assertEqual(e.alerts['a']['count'],0);self.assertFalse(speaker.audio_status()['ready'])
    def test_manual_off_stops_and_drops_backlog(self):
        self.add();self.e.tick();self.speaker.active=True
        self.e.event({'action':'set_enabled','enabled':False})
        self.assertFalse(self.speaker.busy());self.assertFalse(self.e.alerts)
        self.add('while-disabled');self.assertFalse(self.e.alerts)
        self.e.event({'action':'set_enabled','enabled':True})
        self.add('while-disabled');self.assertFalse(self.e.alerts)
        self.add('new');self.now+=10;self.e.tick();self.assertEqual(self.speaker.calls[-1][0],'new')
    def test_saved_off_is_honored_after_restart(self):
        engine=Engine(self.speaker,lambda:1000,enabled=False)
        engine.add({'id':'a','kind':'result'});engine.tick()
        self.assertFalse(engine.snapshot()['enabled']);self.assertFalse(self.speaker.calls)
    def test_effective_turn_reviewer_overrides_global_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            transcript=Path(temp)/'turns.jsonl'
            transcript.write_text('\n'.join(json.dumps({'type':'turn_context','payload':{'turn_id':turn,'approvals_reviewer':reviewer}}) for turn,reviewer in [('old','auto_review'),('current','user')]))
            self.assertEqual(effective_reviewer({'transcript_path':str(transcript),'turn_id':'current'},temp),'user')
            self.assertEqual(effective_reviewer({'transcript_path':str(transcript),'turn_id':'old'},temp),'automatic')
            self.assertEqual(effective_reviewer({'transcript_path':str(transcript),'turn_id':'missing'},temp),'unknown')
    def test_reactivated_other_project_does_not_replay_old_results(self):
        adapter=RolloutAdapter(self.e,'/tmp/nonexistent');cursor={'thread':'other-project','turn':'','question':False}
        adapter.record({'timestamp':'1970-01-01T00:16:39Z','type':'event_msg','payload':{'type':'task_complete','turn_id':'old'}},cursor)
        self.assertFalse(self.e.alerts)
        adapter.record({'timestamp':'1970-01-01T00:16:41Z','type':'event_msg','payload':{'type':'task_complete','turn_id':'new'}},cursor)
        self.assertEqual(len(self.e.alerts),1)

    def test_selected_device_uses_current_id_and_persists(self):
        info={'connected':True,'name':'USB 扬声器','id':99,'devices':[{'name':'USB 扬声器','uid':'usb-speaker','connected':True}]}
        speaker=Speaker('小爱音箱',device_provider=lambda:info,voice_provider=lambda:[{'id':'Tingting'}])
        engine=Engine(speaker,lambda:1000)
        engine.event({'action':'set_audio_device','device':'USB 扬声器','uid':'usb-speaker'})
        with patch('voice_engine.subprocess.Popen') as popen:
            self.assertTrue(speaker.speak('test','老板，测试。'))
            args=popen.call_args.args[0]
            self.assertEqual(args[args.index('-a')+1],'99')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'settings.json'
            save_preferences(path,{'other':'keep'},engine)
            saved=json.loads(path.read_text())
            self.assertEqual((saved['audio_device'],saved['audio_device_uid']),('USB 扬声器','usb-speaker'))
            self.assertEqual(saved['other'],'keep')

    def test_device_switch_retries_only_interrupted_reminder(self):
        info={'connected':True,'name':'Mac mini扬声器','id':79,'devices':[]}
        speaker=Speaker('小爱音箱',device_provider=lambda:info)
        engine=Engine(speaker,lambda:1000)
        for key in ['a','b']: engine.add({'id':key,'kind':'question','delay':300})
        class Playing:
            stopped=False
            def poll(self): return 0 if self.stopped else None
            def terminate(self): self.stopped=True
        playing=Playing();speaker.process=playing;speaker.alert_id='a'
        engine.event({'action':'set_audio_device','device':'Mac mini扬声器','uid':'builtin'})
        self.assertTrue(playing.stopped)
        self.assertEqual(set(engine.alerts),{'a','b'})
        self.assertEqual(engine.alerts['a']['nextAt'],1000)
        self.assertEqual(engine.alerts['b']['nextAt'],1300)

    def test_disconnected_selected_uid_keeps_other_choices_without_fallback(self):
        info={'connected':False,'devices':[{'name':'Mac mini扬声器','uid':'builtin','connected':True}],'defaultName':'Mac mini扬声器'}
        speaker=Speaker('蓝牙音箱',device_uid='bluetooth-speaker',device_provider=lambda:info)
        with patch('voice_engine.subprocess.Popen') as popen:
            self.assertFalse(speaker.speak('a','老板，测试。'));popen.assert_not_called()
        status=speaker.audio_status()
        self.assertEqual(status['selectedUID'],'bluetooth-speaker')
        self.assertEqual(status['devices'][0]['name'],'Mac mini扬声器')

    def test_follow_system_output_does_not_pin_an_old_device_id(self):
        info={'connected':True,'name':'Mac mini扬声器','id':79,'defaultName':'Mac mini扬声器','devices':[]}
        speaker=Speaker('小爱音箱',device_provider=lambda:info,device_uid='old-speaker',voice_provider=lambda:[{'id':'Tingting'}])
        self.assertTrue(speaker.set_device(''))
        with patch('voice_engine.subprocess.Popen') as popen:
            self.assertTrue(speaker.speak('a','老板，测试。'))
            self.assertNotIn('-a',popen.call_args.args[0])
        self.assertTrue(speaker.audio_status()['followSystem'])

    def test_reselecting_same_output_does_not_interrupt_speech(self):
        speaker=Speaker('扬声器',device_uid='same')
        with patch.object(speaker,'stop') as stop:
            self.assertFalse(speaker.set_device('扬声器','same'));stop.assert_not_called()

    def agent(self, raw):
        handle_agent(raw, self.e)
    def test_opencode_approval_and_completion_flow(self):
        self.agent({'action':'add','source':'opencode','thread':'oc-1','requestId':'perm-1','kind':'approval','title':'重构提醒服务','detail':'等待你在 OpenCode 中确认操作','delay':1,'id':'opencode:approval:perm-1'})
        self.assertEqual(list(self.e.alerts),['opencode:approval:perm-1'])
        alert=self.e.alerts['opencode:approval:perm-1']
        self.assertEqual((alert['kind'],alert['requestId'],alert['source']),('approval','perm-1','opencode'))
        self.assertEqual(alert['nextAt'],1001) # delay 1 honored
        self.agent({'action':'add','source':'opencode','thread':'oc-1','requestId':'perm-1','kind':'approval','title':'重构提醒服务','id':'opencode:approval:perm-1'})
        self.assertEqual(len(self.e.alerts),1) # duplicate approval cannot stack
        self.agent({'action':'resolve_request','source':'opencode','thread':'oc-1','requestId':'perm-1'})
        self.assertFalse(self.e.alerts)
        self.agent({'action':'add','source':'opencode','thread':'oc-1','kind':'result','title':'重构提醒服务','detail':'这一轮已经完成','id':'opencode:result:oc-1:turn-9'})
        self.assertEqual(list(self.e.alerts),['opencode:result:oc-1:turn-9'])
        self.assertEqual(self.e.monitor['agentLastSeen'],1000)
    def test_opencode_untrusted_events_are_rejected(self):
        for raw in [
            {'action':'add','source':'codex','thread':'oc','kind':'result','id':'x'},
            {'action':'set_enabled','source':'opencode','enabled':False},
        ]:
            self.agent(raw)
            self.assertFalse(self.e.alerts)
            self.assertIsNone(self.e.monitor['agentLastSeen']) # envelope itself untrusted
        for raw in [
            {'action':'add','source':'opencode','thread':'oc','kind':'test','id':'x'},
            {'action':'add','source':'opencode','thread':'oc','kind':'result','id':''},
            {'action':'add','source':'opencode','thread':'oc','kind':'result'},
        ]:
            self.agent(raw);self.assertFalse(self.e.alerts)
    def test_opencode_thread_resolution_and_text_limits(self):
        self.add('a','oc-1');self.add('b','oc-2')
        self.agent({'action':'resolve_thread','source':'opencode','thread':'oc-1','reason':'任务已继续'})
        self.assertEqual(list(self.e.alerts),['b'])
        self.agent({'action':'add','source':'opencode','thread':'oc-2','kind':'result','title':'任务','detail':'x'*300,'delay':'soon','id':'r1'})
        alert=self.e.alerts['r1']
        self.assertEqual(len(alert['detail']),150) # detail clamped
        self.assertEqual(alert['nextAt'],1000) # invalid delay ignored, speaks immediately
    def test_opencode_only_machine_stays_connected_in_monitor(self):
        adapter=RolloutAdapter(self.e,'/tmp/nonexistent-codex-voice')
        adapter.discover();self.assertEqual(self.e.monitor['state'],'unavailable')
        self.agent({'action':'add','source':'opencode','thread':'oc-1','kind':'result','id':'r1'})
        self.now+=10 # discover() rescans at most every 3 seconds
        adapter.discover();self.assertEqual(self.e.monitor['state'],'connected')
        self.assertIn('OpenCode',self.e.monitor['detail'])


if __name__ == '__main__': unittest.main()

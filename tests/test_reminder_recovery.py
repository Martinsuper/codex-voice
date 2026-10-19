import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from reminder_recovery import RecoveryStore
from test_voice_engine import FakeSpeaker
from voice_engine import Engine, RolloutAdapter


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(); self.root=Path(self.temporary.name)
        self.codex=self.root/"codex"; self.codex.mkdir()
        self.transcript=self.codex/"session.jsonl"; self.transcript.write_text("")
        self.file=self.root/"reminder-state.json"
        self.now=1000.0
        self.engine=Engine(FakeSpeaker(),lambda:self.now)
        self.adapter=RolloutAdapter(self.engine,self.codex)
        self.adapter.positions[str(self.transcript)]={"offset":0,"thread":"t","turn":"turn","question":False}
        self.store=RecoveryStore(self.file,lambda:self.now)
        db=sqlite3.connect(self.codex/"state_5.sqlite")
        db.execute("create table threads(id text,rollout_path text,title text,cwd text,source text,archived integer,updated_at integer)")
        db.execute("insert into threads values(?,?,?,?,?,?,?)",("t",str(self.transcript),"测试任务",str(self.root),"local",0,1000))
        db.commit(); db.close()

    def tearDown(self): self.temporary.cleanup()
    def add(self,kind="question",key="question:t:q",source="hook"):
        self.engine.add({"id":key,"thread":"t","turn":"turn","kind":kind,"requestId":"q","source":source})
    def save(self): self.store.save(self.engine,self.adapter,force=True)
    def restore(self,enabled=True):
        self.now+=5
        engine=Engine(FakeSpeaker(),lambda:self.now,enabled=enabled)
        adapter=RolloutAdapter(engine,self.codex)
        store=RecoveryStore(self.file,lambda:self.now); store.load(engine,adapter)
        return engine,adapter,store
    def append(self,event):
        event["timestamp"]=dt.datetime.fromtimestamp(self.now+1,dt.timezone.utc).isoformat()
        with self.transcript.open("a") as out: out.write(json.dumps(event)+"\n")

    def test_pending_card_waits_for_verification_then_resumes(self):
        self.add(); self.save(); engine,adapter,_=self.restore()
        engine.tick(); self.assertFalse(engine.speaker.calls)
        adapter.poll(); engine.tick()
        self.assertEqual(len(engine.speaker.calls),1)
        self.assertFalse(engine.alerts["question:t:q"]["recoveryPending"])
        self.assertEqual(self.file.stat().st_mode & 0o777,0o600)

    def test_user_reply_during_outage_clears_old_reminder_before_audio(self):
        self.add(); self.save()
        self.append({"type":"event_msg","payload":{"type":"task_started","turn_id":"new","turn_attribution":{"turn_trigger":"composer"}}})
        engine,adapter,_=self.restore(); adapter.poll(); engine.tick()
        self.assertFalse(engine.alerts); self.assertFalse(engine.speaker.calls)

    def test_tool_completion_during_outage_clears_approval(self):
        self.add("approval","approval:t:call"); self.save()
        self.append({"type":"event_msg","payload":{"type":"task_complete","turn_id":"turn"}})
        engine,adapter,_=self.restore(); adapter.poll()
        self.assertNotIn("approval:t:call",engine.alerts)
        self.assertEqual([a["kind"] for a in engine.alerts.values()],["result"])

    def test_acknowledged_result_and_seen_id_do_not_reappear(self):
        self.add("result","result:t:turn"); self.engine.event({"action":"ack","id":"result:t:turn"}); self.save()
        self.append({"type":"event_msg","payload":{"type":"task_complete","turn_id":"turn"}})
        engine,adapter,_=self.restore(); adapter.poll(); engine.tick()
        self.assertFalse(engine.alerts); self.assertFalse(engine.speaker.calls)

    def test_in_flight_interruption_retries_but_completed_single_play_does_not(self):
        for active in (True,False):
            self.engine=Engine(FakeSpeaker(),lambda:self.now)
            self.engine.configure_rules({"result":{"max_plays":1}})
            self.add("result","result:t:turn"); self.engine.tick(); self.engine.speaker.active=active
            self.save(); engine,adapter,_=self.restore()
            engine.configure_rules({"result":{"max_plays":1}})
            adapter.poll(); self.now+=2; engine.tick()
            self.assertEqual(len(engine.speaker.calls),1 if active else 0)

    def test_pause_and_snooze_deadlines_survive_restart(self):
        self.add(); self.engine.event({"action":"snooze","id":"question:t:q","seconds":300})
        self.engine.event({"action":"mute","seconds":900}); self.save()
        engine,adapter,_=self.restore(); adapter.poll(); engine.tick()
        self.assertEqual(engine.muted_until,1900)
        self.assertEqual(engine.alerts["question:t:q"]["nextAt"],1300)
        self.assertFalse(engine.speaker.calls)

    def test_snoozed_single_play_waits_for_verification_after_restart(self):
        self.engine.configure_rules({"result":{"max_plays":1}})
        self.add("result","result:t:turn"); self.engine.tick()
        self.engine.event({"action":"snooze","id":"result:t:turn","seconds":5}); self.save()
        engine,adapter,_=self.restore(); engine.configure_rules({"result":{"max_plays":1}})
        engine.tick(); self.assertFalse(engine.speaker.calls)
        adapter.poll(); engine.tick(); self.assertEqual(len(engine.speaker.calls),1)

    def test_manual_cards_restore_without_transcript_and_test_cards_do_not(self):
        self.engine.add({"id":"manual","kind":"blocked"})
        self.engine.event({"action":"test"}); self.save()
        engine,_,_=self.restore(); engine.tick()
        self.assertEqual(set(engine.alerts),{"manual"})
        self.assertEqual(len(engine.speaker.calls),1)

    def test_archived_chat_is_removed_before_resume(self):
        self.add(); self.save()
        db=sqlite3.connect(self.codex/"state_5.sqlite"); db.execute("update threads set archived=1"); db.commit(); db.close()
        engine,adapter,_=self.restore(); adapter.poll(); engine.tick()
        self.assertFalse(engine.alerts); self.assertFalse(engine.speaker.calls)

    def test_missing_database_keeps_card_silent_for_manual_handling(self):
        self.add(); self.save(); (self.codex/"state_5.sqlite").unlink()
        engine,adapter,_=self.restore(); adapter.poll(); engine.tick()
        self.assertTrue(engine.alerts["question:t:q"]["recoveryPending"])
        self.assertFalse(engine.speaker.calls)
        engine.event({"action":"ack","id":"question:t:q"}); self.assertFalse(engine.alerts)

    def test_new_events_are_not_played_until_restored_cursor_catches_up(self):
        self.save()
        for i in range(510): self.append({"type":"response_item","payload":{"type":"function_call","name":"request_user_input","call_id":str(i)}})
        self.append({"type":"event_msg","payload":{"type":"task_started","turn_id":"next","turn_attribution":{"turn_trigger":"composer"}}})
        engine,adapter,_=self.restore(); adapter.poll(); engine.tick()
        self.assertFalse(engine.speaker.calls)
        adapter.poll(); engine.tick()
        self.assertFalse(engine.alerts); self.assertFalse(engine.speaker.calls)

    def test_corrupt_state_is_skipped_and_older_cards_wait_for_verification(self):
        for value in ("not-json",json.dumps({"version":1,"at":1000,"seen":[],"alerts":[],"positions":[]}),json.dumps({"version":99,"at":1000})):
            self.file.write_text(value); engine,_,_=self.restore()
            self.assertFalse(engine.alerts)
        self.now=1000; self.add(); self.save(); self.now+=86401
        engine,_,_=self.restore()
        self.assertIn("question:t:q",engine.alerts)
        self.assertTrue(engine.alerts["question:t:q"]["recoveryPending"])
        engine.tick(); self.assertFalse(engine.speaker.calls)

    def test_disabled_global_switch_does_not_restore_pending_cards(self):
        self.add(); self.save(); engine,adapter,_=self.restore(enabled=False); adapter.poll(); engine.tick()
        self.assertFalse(engine.alerts); self.assertFalse(engine.speaker.calls)

    def test_wake_reconciles_new_composer_action_before_existing_audio(self):
        self.add(); self.adapter.begin_reconcile()
        self.append({"type":"event_msg","payload":{"type":"task_started","turn_id":"new","turn_attribution":{"turn_trigger":"composer"}}})
        self.adapter.poll(); self.engine.tick()
        self.assertFalse(self.engine.alerts); self.assertFalse(self.engine.speaker.calls)

    def test_out_of_order_resolved_request_never_creates_an_obsolete_approval(self):
        self.engine.event({"action":"resolve_request","thread":"t","requestId":"q"})
        self.add("approval","approval:t:q"); self.assertFalse(self.engine.alerts)
        self.save(); engine,_,_=self.restore()
        engine.add({"id":"approval:t:q","thread":"t","kind":"approval","requestId":"q"})
        self.assertFalse(engine.alerts)

    def test_ack_before_transcript_replay_is_a_persistent_tombstone(self):
        self.engine.event({"action":"ack","id":"result:t:turn"}); self.save()
        engine,_,_=self.restore()
        engine.add({"id":"result:t:turn","thread":"t","kind":"result"})
        self.assertFalse(engine.alerts)

    def test_bulk_ack_targets_visible_ids_and_leaves_later_requests(self):
        self.engine.event({"action":"ack_all","ids":["old"]})
        self.engine.add({"id":"old","kind":"result"})
        self.engine.add({"id":"new","kind":"approval"})
        self.assertEqual(set(self.engine.alerts),{"new"})


if __name__=="__main__": unittest.main()

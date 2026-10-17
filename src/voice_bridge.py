#!/usr/bin/env python3
"""Tiny fail-open hook/manual adapter. Never prints an approval decision."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid


def effective_reviewer(raw, codex_dir=None):
    """Use the actual turn context, not an unrelated global reviewer default."""
    codex_dir = Path(codex_dir or Path.home()/'.codex')
    transcript = raw.get('transcript_path')
    if not transcript:
        try:
            import sqlite3
            db=sqlite3.connect((codex_dir/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)
            row=db.execute('select rollout_path from threads where id=?',(raw.get('session_id',''),)).fetchone();db.close()
            transcript=row[0] if row else None
        except Exception:
            pass
    if transcript:
        try:
            path=Path(transcript)
            with path.open('rb') as stream:
                total=path.stat().st_size
                for window in [262144,1048576,4194304,16777216]:
                    start=max(0,total-window);stream.seek(start)
                    if start:stream.readline()
                    lines=stream.read().splitlines()
                    for line in reversed(lines):
                        if b'"turn_context"' not in line:continue
                        record=json.loads(line)
                        if record.get('type')!='turn_context':continue
                        context=record.get('payload',{})
                        if raw.get('turn_id') and context.get('turn_id')!=raw['turn_id']:continue
                        reviewer=context.get('approvals_reviewer')
                        if reviewer=='user':return 'user'
                        if reviewer in ['auto_review','guardian_subagent']:return 'automatic'
                    if start==0:break
        except Exception:
            pass
    return 'unknown'


def send(state_dir, event):
    inbox = Path(state_dir) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    event["sentAt"] = time.time()
    path = inbox / (str(time.time_ns()) + "-" + str(uuid.uuid4()) + ".json")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(event, ensure_ascii=False))
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("mode", choices=["hook", "event"])
    parser.add_argument("payload", nargs="?")
    args = parser.parse_args()
    try:
        raw = json.loads(args.payload or sys.stdin.read())
        if args.mode == "hook":
            # Forward metadata only; no transcripts, commands, or tool outputs.
            allowed = {k:raw[k] for k in ["hook_event_name", "session_id", "turn_id", "tool_name", "tool_use_id", "cwd"] if k in raw}
            # PermissionRequest does not always contain tool_use_id. Correlate
            # it with PostToolUse using a digest; never persist the tool input.
            fingerprint = json.dumps([raw.get('turn_id'),raw.get('tool_name'),raw.get('tool_input')],sort_keys=True,ensure_ascii=False)
            allowed['tool_use_id'] = (raw.get('tool_use_id') if 'request_user_input' in str(raw.get('tool_name','')) else None) or hashlib.sha256(fingerprint.encode()).hexdigest()[:24]
            allowed["voice_reviewer"] = effective_reviewer(raw) if raw.get('hook_event_name')=='PermissionRequest' else 'unknown'
            allowed['project_title'] = Path(str(raw.get('cwd',''))).name or '当前任务'
            send(args.state_dir, {"action":"hook", "event":allowed})
        else:
            send(args.state_dir, raw)
    except Exception:
        # A failed reminder must never block the user's actual task.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

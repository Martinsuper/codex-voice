#!/usr/bin/env python3
"""Engine process lifecycle, persistence and transport loop."""

import argparse
import json
import os
from pathlib import Path
import queue
import signal
import sys
import threading
import time

from accessory_settings import migrate_preferences
from codex_usage import UsageMonitor
from reminder_recovery import RecoveryStore
from rollout_adapter import RolloutAdapter
from speaker import Speaker
from voice_engine import DEFAULT_PAUSE_MINUTES, Engine, atomic_json, save_preferences
from event_adapters import handle_agent, handle_hook


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--codex-dir", default=str(Path.home() / ".codex"))
    parser.add_argument("--usage", action="store_true", help="Read account quotas on a separate worker")
    args = parser.parse_args()
    try:
        os.setsid()
    except OSError:
        pass
    state_dir = Path(args.state_dir)
    inbox = state_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    import fcntl
    lock = (state_dir / "engine.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"error": "语音提醒已经在运行"}), flush=True)
        return 1
    try:
        settings = json.loads((state_dir / "settings.json").read_text())
    except (OSError, ValueError):
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    migrated = migrate_preferences(settings)
    if migrated != settings:
        settings = migrated; atomic_json(state_dir / "settings.json",settings)
    engine = Engine(Speaker(str(settings.get("audio_device", "")), device_uid=str(settings.get("audio_device_uid", "")),
                    passport_emit=lambda event: print(json.dumps({"passportCommand": event}), flush=True)),
                    enabled=bool(settings.get("enabled", True)), speech_settings=settings.get("speech"),
                    pause_minutes=settings.get("pause_minutes", DEFAULT_PAUSE_MINUTES), usage_reset_enabled=settings.get("usage_reset_announcement", True),
                    usage_low_enabled=settings.get("usage_low_announcement", True), usage_low_threshold=settings.get("usage_low_threshold", 20),
                    reminder_rules=settings.get("reminder_rules"), quiet_hours=settings.get("quiet_hours"))
    engine.speaker.configure_passport(settings["passport"])
    engine.speaker.configure_computer(settings["computer_audio_enabled"])
    adapter = RolloutAdapter(engine, args.codex_dir)
    store = RecoveryStore(state_dir / "reminder-state.json")
    store.load(engine, adapter)
    inbox_since = time.time() - 86400 if adapter.restore_since is not None else adapter.started_at
    usage = UsageMonitor(args.codex_dir, low_state_file=state_dir / "usage-low-alerts.json") if args.usage else None
    if usage:
        engine.on_usage_low_spoken = usage.mark_low_announced
        usage.start()
    commands = queue.Queue()
    def prepare_device_state():
        value = engine.snapshot()
        if usage:
            value["usage"] = usage.snapshot()
        print(json.dumps(value, ensure_ascii=False), flush=True)
    engine.before_device_play = prepare_device_state
    signal.signal(signal.SIGTERM, lambda *_: commands.put({"action":"quit"}))
    signal.signal(signal.SIGINT, lambda *_: commands.put({"action":"quit"}))

    def read_commands():
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if isinstance(command, dict):
                    if command.get("action") == "passport_feedback":
                        engine.speaker.passport_feedback(command.get("event"))
                    else:
                        commands.put(command)
            except ValueError:
                pass
        commands.put({"action": "quit"})

    threading.Thread(target=read_commands, daemon=True).start()
    previous = ""
    last_emit = 0
    last_flight = None
    def dispatch(event):
        if event.get("action") == "refresh_usage":
            if usage:
                usage.request_refresh()
            return
        if event.get("action") == "prepare_sleep":
            engine.sleeping = True
            engine.interrupt_current(); engine.speaker.stop()
            store.save(engine, adapter, force=True)
            return
        if event.get("action") == "wake":
            engine.sleeping = False
            engine.interrupt_current(); engine.speaker.stop()
            engine.speaker.next_device_check = 0
            adapter.begin_reconcile()
            if usage:
                usage.request_refresh()
            return
        accepted = engine.event(event)
        if event.get("action") in ("set_enabled", "set_audio_device") or (event.get("action") in ("set_passport_settings", "set_computer_audio_enabled", "set_speech_settings", "set_pause_duration", "pause", "set_usage_reset_enabled", "set_usage_low_settings", "set_reminder_rules", "set_quiet_hours") and accepted):
            save_preferences(state_dir / "settings.json", settings, engine)
        store.save(engine, adapter, force=True)
    try:
        while True:
            while not commands.empty():
                command = commands.get()
                if command.get("action") == "quit":
                    return 0
                dispatch(command)
            entries = []
            for candidate in inbox.glob("*.json"):
                try:
                    entries.append((candidate.stat().st_mtime_ns, candidate.name, candidate))
                except OSError:
                    pass
            for _, _, event_file in sorted(entries)[:100]:
                try:
                    event = json.loads(event_file.read_text())
                    if not isinstance(event, dict):
                        raise ValueError()
                    # Stale spool entries from an old run must not start shouting.
                    panel_action = event_file.name.startswith("panel-") and event.get("action") in ("ack", "ack_all", "resolve", "snooze")
                    if (panel_action or inbox_since <= float(event.get("sentAt", 0)) <= time.time() + 5) and engine.remember("spool:" + event_file.name):
                        if event.get("action") == "hook":
                            if isinstance(event.get("event"), dict):
                                handle_hook(event["event"], engine, adapter)
                        elif event.get("action") == "agent":
                            if isinstance(event.get("event"), dict):
                                handle_agent(event["event"], engine)
                        else:
                            dispatch(event)
                        store.save(engine, adapter, force=True)
                    event_file.unlink()
                except (OSError, ValueError, TypeError):
                    try:
                        event_file.unlink()
                    except OSError:
                        pass
            adapter.poll()
            if usage:
                for reset in usage.drain_reset_events():
                    engine.usage_reset(reset)
                engine.update_usage_low(usage.low_warning(engine.usage_low_threshold) if engine.usage_low_enabled else None)
            engine.tick()
            flight = engine.speaker.alert_id if engine.speaker.busy() else None
            store.save(engine, adapter, force=flight != last_flight)
            last_flight = flight
            snapshot = engine.snapshot()
            snapshot["service"] = {"pid": os.getpid(), "processGroup": os.getpgrp(), "sleeping":engine.sleeping, "checkpointError":store.error}
            if usage:
                snapshot["usage"] = usage.snapshot()
            marker = json.dumps({k:v for k,v in snapshot.items() if k != "at"}, ensure_ascii=False)
            if marker != previous or time.time() - last_emit > 2:
                atomic_json(state_dir / "status.json", snapshot)
                print(json.dumps(snapshot, ensure_ascii=False), flush=True)
                previous, last_emit = marker, time.time()
            time.sleep(.2)
    finally:
        store.save(engine, adapter, force=True)
        engine.speaker.stop()
        if usage:
            usage.close()



if __name__ == "__main__":
    raise SystemExit(main())

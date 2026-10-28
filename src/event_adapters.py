"""Translate supported hook and agent events into reminder operations."""

AGENT_SOURCES = {"opencode"}
AGENT_ACTIONS = {"add", "resolve", "resolve_request", "resolve_thread"}
AGENT_KINDS = {"approval", "question", "result", "blocked"}


def handle_agent(raw, engine):
    """Sanitized notifications from OpenCode CLI plugins; observational only."""
    action = raw.get("action")
    source = str(raw.get("source", ""))
    if action not in AGENT_ACTIONS or source not in AGENT_SOURCES:
        return
    engine.monitor["agentLastSeen"] = engine.now()
    thread = str(raw.get("thread", ""))
    if action == "add":
        kind = raw.get("kind", "result")
        identifier = raw.get("id")
        if kind not in AGENT_KINDS or not isinstance(identifier, str) or not identifier:
            return
        try:
            delay = float(raw.get("delay", 0))
        except (TypeError, ValueError):
            delay = 0
        engine.add({"id": identifier, "thread": thread, "turn": str(raw.get("turn", "")), "requestId": str(raw.get("requestId", "")), "kind": kind, "title": raw.get("title", ""), "detail": str(raw.get("detail", ""))[:150], "delay": max(0, delay), "source": source})
    elif action == "resolve":
        if isinstance(raw.get("id"), str):
            engine.event({"action": "resolve", "id": raw["id"]})
    elif action == "resolve_request":
        engine.event({"action": "resolve_request", "thread": thread, "requestId": str(raw.get("requestId", ""))})
    elif action == "resolve_thread":
        engine.event({"action": "resolve_thread", "thread": thread, "reason": str(raw.get("reason", "任务已继续"))[:80]})


def handle_hook(raw, engine, adapter):
    name = raw.get("hook_event_name", "")
    thread = str(raw.get("session_id", ""))
    turn = str(raw.get("turn_id", ""))
    request = str(raw.get("tool_use_id", ""))
    tool = str(raw.get("tool_name", ""))
    engine.monitor["hookLastSeen"] = engine.now()
    if name == "PreToolUse" and "request_user_input" in tool:
        engine.add({"id": "question:" + thread + ":" + request, "thread": thread, "turn": turn, "requestId": request, "kind": "question", "title": adapter.title(thread), "source": "hook"})
    elif name == "PostToolUse" and "request_user_input" in tool and "async" not in tool:
        engine.event({"action": "resolve_request", "thread": thread, "requestId": request})
    elif name == "UserPromptSubmit":
        engine.resolve_thread(thread, reason="你已在此聊天回复")
    elif name == "Interrupt":
        engine.resolve_thread(thread, reason="本轮已取消", turn=turn)
    elif name == "PermissionRequest":
        # A permission hook does not prove a human is waiting: auto review can
        # handle it. Enable only on hosts explicitly using the user reviewer.
        if raw.get("voice_reviewer") == "user":
            title = raw.get("project_title") or adapter.title(thread)
            engine.add({"id": "approval:" + thread + ":" + request, "thread": thread, "turn": turn, "requestId": request, "title": title, "kind": "approval", "delay": 1, "source": "hook"})
    elif name == "PostToolUse" and request and "request_user_input" not in tool:
        engine.event({"action": "resolve_request", "thread": thread, "requestId": request})



"""Provider-native terminal output and usage; never infer subscription validity/cost."""

import json

from intelligenceai.security import clean

USAGE_FIELDS = {
    "claude": (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ),
    "codex": ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"),
    "grok": (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "reasoning_tokens",
    ),
}


def usage(provider, value, measured_at, incomplete=False):
    value = value if isinstance(value, dict) else {}
    return {
        "source": provider + ":native-cli-result",
        "measured_at": measured_at,
        "unit": "tokens",
        "values": {
            field: value.get(field) if type(value.get(field)) is int and value[field] >= 0 else None
            for field in USAGE_FIELDS[provider]
        },
        "completeness": "INCOMPLETE"
        if incomplete
        else "PROVIDED_FIELDS_ONLY"
        if value
        else "NOT_PROVIDED",
    }


def parse(provider, stdout, stderr, returncode, measured_at, *, truncated=False):
    result = {
        "availability": "EXECUTION_ERROR",
        "text": None,
        "usage": usage(provider, None, measured_at),
    }
    if truncated:
        return result | {"availability": "OUTPUT_TRUNCATED"}
    try:
        text = stdout.decode("utf-8", errors="strict")
        if provider == "codex":
            events = [json.loads(line) for line in text.splitlines() if line.strip()]
            terminal = [
                event for event in events if event.get("type") in {"turn.completed", "turn.failed"}
            ]
            diagnostics = [
                event
                for event in events
                if event.get("type") == "error"
                or (
                    event.get("type") in {"item.started", "item.completed"}
                    and event.get("item", {}).get("type") == "error"
                )
            ]
            messages = [
                event["item"]["text"]
                for event in events
                if event.get("type") == "item.completed"
                and event.get("item", {}).get("type") == "agent_message"
            ]
            # Tool output is never accepted as a text-only native result.
            tool_events = [
                event
                for event in events
                if event.get("type") in {"item.started", "item.completed"}
                and event.get("item", {}).get("type") not in {"agent_message", "reasoning", "error"}
            ]
            success = (
                len(terminal) == 1
                and terminal[0]["type"] == "turn.completed"
                and bool(messages)
                and not tool_events
                and not diagnostics
            )
            result["native_outcome"] = {
                "turn_completed": any(event["type"] == "turn.completed" for event in terminal),
                "turn_failed": any(event["type"] == "turn.failed" for event in terminal),
                "agent_message_count": len(messages),
                "diagnostic_count": len(diagnostics),
                "unsupported_item_count": len(tool_events),
            }
            if result["native_outcome"]["turn_failed"]:
                result["availability"] = "REQUEST_FAILED"
            elif result["native_outcome"]["turn_completed"] and diagnostics:
                result["availability"] = "PARTIAL_FAILURE"
            elif tool_events:
                result["availability"] = "UNSUPPORTED_ITEM"
            value = terminal[0] if terminal else {}
            # rust-v0.162.1 drops message phase in JSONL; the final message is last.
            # An empty final message must not fall back to prior commentary.
            answer = messages[-1] if messages else None
        elif provider == "claude":
            value = json.loads(text)
            success = (
                value.get("type") == "result"
                and value.get("subtype") == "success"
                and value.get("is_error") is False
            )
            answer = value.get("result")
        elif provider == "grok":
            try:
                value = json.loads(text)
                answer = value.get("text")
                allowed = True
            except ValueError:
                events = [json.loads(line) for line in text.splitlines() if line.strip()]
                ends = [event for event in events if event.get("type") == "end"]
                allowed = bool(
                    len(ends) == 1
                    and events[-1] == ends[0]
                    and all(
                        event.get("type") in {"text", "thought", "usage", "end"} for event in events
                    )
                )
                value = ends[0] if len(ends) == 1 else {}
                answer = "".join(event["data"] for event in events if event.get("type") == "text")
            success = allowed and value.get("stopReason") == "end_turn" and not value.get("error")
        else:
            return result | {"availability": "UNSUPPORTED"}
        result["usage"] = usage(
            provider, value.get("usage"), measured_at, value.get("usage_is_incomplete") is True
        )
        if success and returncode == 0 and isinstance(answer, str) and answer.strip():
            return result | {"availability": "AVAILABLE", "text": clean(answer)}
    except (UnicodeError, ValueError, KeyError, TypeError, AttributeError):
        pass
    # Never persist native stderr. Classification has no credential/PII payload.
    diagnostic = (stdout + stderr).decode("utf-8", errors="replace").lower()
    if any(
        word in diagnostic
        for word in ("authentication required", "not logged in", "login required", "unauthorized")
    ):
        result["availability"] = "AUTHENTICATION_REQUIRED"
    elif any(word in diagnostic for word in ("rate limit", "quota exceeded", "usage limit")):
        result["availability"] = "USAGE_LIMITED"
    return result

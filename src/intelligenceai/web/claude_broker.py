"""Single-request broker. Real key stays here; no proxy URLs or headers from the CLI."""

import json
import time

import httpx

from intelligenceai.security import SafetyError, canonical, digest, require_no_secrets
from intelligenceai.web.live_authority import unique_object

MAX_REQUEST = 256 * 1024
MAX_RESPONSE = 1024 * 1024
UPSTREAM = "https://api.anthropic.com/v1/messages"


def text_blocks(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, list) or len(value) > 64:
        raise SafetyError("claude_text_content_required")
    blocks = []
    for block in value:
        if (
            not isinstance(block, dict)
            or set(block) - {"type", "text", "cache_control"}
            or (block.get("type") != "text" or not isinstance(block.get("text"), str))
        ):
            raise SafetyError("claude_tools_media_and_external_content_denied")
        # Provider caching is deliberately not requested by this bounded profile.
        blocks.append({"type": "text", "text": block["text"]})
    return blocks


def bounded_request(raw, profile):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_REQUEST:
        raise SafetyError("claude_request_limit")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeDecodeError):
        raise SafetyError("claude_invalid_json") from None
    if not isinstance(value, dict) or set(value) - {
        "model",
        "max_tokens",
        "messages",
        "system",
        "stream",
        "tools",
        "metadata",
        "output_config",
        "temperature",
        "stop_sequences",
        "thinking",
    }:
        raise SafetyError("claude_unknown_request_fields")
    if (
        value.get("model") != profile.model
        or value.get("stream") is not True
        or (
            value.get("tools", []) != []
            or type(value.get("max_tokens")) is not int
            or value["max_tokens"] < 1
        )
    ):
        raise SafetyError("claude_model_stream_or_tools_changed")
    output = value.get("output_config", {})
    if (
        not isinstance(output, dict)
        or set(output) - {"effort"}
        or (output.get("effort", profile.effort) != profile.effort)
    ):
        raise SafetyError("claude_effort_changed")
    messages = value.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 4:
        raise SafetyError("claude_bounded_messages_required")
    forwarded = []
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or (message["role"] not in {"user", "assistant"})
        ):
            raise SafetyError("claude_message_invalid")
        forwarded.append({"role": message["role"], "content": text_blocks(message["content"])})
    safe = {
        "model": profile.model,
        "max_tokens": min(value["max_tokens"], profile.output_token_limit),
        "messages": forwarded,
        "stream": True,
        "output_config": {"effort": profile.effort},
    }
    if "system" in value:
        safe["system"] = text_blocks(value["system"])
    if "thinking" in value:
        thinking = value["thinking"]
        if not isinstance(thinking, dict) or set(thinking) - {"type", "budget_tokens", "display"}:
            raise SafetyError("claude_thinking_invalid")
        kind = thinking.get("type")
        if thinking.get("display", "omitted") not in {"omitted", "summarized"}:
            raise SafetyError("claude_thinking_display_invalid")
        if kind in {"adaptive", "disabled"}:
            if "budget_tokens" in thinking or (kind == "disabled" and "display" in thinking):
                raise SafetyError("claude_thinking_invalid")
        elif kind == "enabled":
            budget = thinking.get("budget_tokens")
            if type(budget) is not int or not 1024 <= budget < safe["max_tokens"]:
                raise SafetyError("claude_thinking_budget_invalid")
        else:
            raise SafetyError("claude_thinking_invalid")
        # Thinking shares the bounded max_tokens and output price ceiling.
        safe["thinking"] = thinking
    # Drop client metadata, stop sequences, temperature and all client headers.
    require_no_secrets(safe)
    return canonical(safe).encode()


def stream_result(raw, profile):
    """Settle complete bounded text/thinking streams; retain only answer text."""
    if len(raw) > MAX_RESPONSE:
        raise SafetyError("claude_response_limit")
    try:
        wire = raw.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise SafetyError("claude_stream_invalid") from None
    started = stopped = delta_seen = terminal = False
    input_tokens = output_tokens = None
    blocks, closed, chunks = {}, set(), []
    signatures = set()
    for frame in wire.split("\n\n"):
        if not frame.strip():
            continue
        events = [line[7:] for line in frame.splitlines() if line.startswith("event: ")]
        data = [line[6:] for line in frame.splitlines() if line.startswith("data: ")]
        if len(events) != 1 or len(data) != 1 or stopped:
            raise SafetyError("claude_stream_framing_invalid")
        try:
            value = json.loads(data[0], object_pairs_hook=unique_object)
        except ValueError:
            raise SafetyError("claude_stream_json_invalid") from None
        event = events[0]
        if not isinstance(value, dict) or value.get("type") != event:
            raise SafetyError("claude_stream_event_invalid")
        if event == "ping":
            continue
        if event == "message_start":
            message = value.get("message", {})
            usage = message.get("usage", {})
            if (
                started
                or message.get("model") != profile.model
                or (
                    message.get("type") != "message"
                    or message.get("role") != "assistant"
                    or message.get("content") != []
                    or usage.get("cache_creation_input_tokens", 0) != 0
                    or usage.get("cache_read_input_tokens", 0) != 0
                    or set(usage)
                    - {
                        "input_tokens",
                        "output_tokens",
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    }
                )
            ):
                raise SafetyError("claude_response_model_or_usage_changed")
            started = True
            input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        elif not started:
            raise SafetyError("claude_stream_start_required")
        elif event == "content_block_start":
            index, block = value.get("index"), value.get("content_block", {})
            if (
                type(index) is not int
                or index < 0
                or index in blocks
                or delta_seen
                or not isinstance(block, dict)
                or block.get("type") not in {"text", "thinking", "redacted_thinking"}
            ):
                raise SafetyError("claude_bounded_response_required")
            kind = block["type"]
            allowed = {
                "text": {"type", "text"},
                "thinking": {"type", "thinking", "signature"},
                "redacted_thinking": {"type", "data"},
            }[kind]
            field = {"text": "text", "thinking": "thinking", "redacted_thinking": "data"}[kind]
            if set(block) - allowed or not isinstance(block.get(field), str):
                raise SafetyError("claude_content_block_invalid")
            if kind == "thinking":
                if not isinstance(block.get("signature", ""), str):
                    raise SafetyError("claude_thinking_signature_invalid")
                if block.get("signature"):
                    signatures.add(index)
            blocks[index] = kind
            if kind == "text":
                chunks.append(block["text"])
        elif event == "content_block_delta":
            index, delta = value.get("index"), value.get("delta", {})
            if index not in blocks.keys() - closed or delta_seen or not isinstance(delta, dict):
                raise SafetyError("claude_content_delta_invalid")
            if (
                blocks[index] == "text"
                and set(delta) == {"type", "text"}
                and (delta["type"] == "text_delta" and isinstance(delta["text"], str))
            ):
                chunks.append(delta["text"])
            elif (
                blocks[index] == "thinking"
                and index not in signatures
                and (
                    set(delta) == {"type", "thinking"}
                    and delta["type"] == "thinking_delta"
                    and isinstance(delta["thinking"], str)
                )
            ):
                pass  # Never persist thinking summaries in the private review or audit.
            elif (
                blocks[index] == "thinking"
                and index not in signatures
                and (
                    set(delta) == {"type", "signature"}
                    and delta["type"] == "signature_delta"
                    and isinstance(delta["signature"], str)
                    and delta["signature"]
                )
            ):
                signatures.add(index)
            else:
                raise SafetyError("claude_content_delta_invalid")
        elif event == "content_block_stop":
            index = value.get("index")
            if index not in blocks.keys() - closed or (
                blocks[index] == "thinking" and index not in signatures
            ):
                raise SafetyError("claude_content_stop_invalid")
            closed.add(index)
        elif event == "message_delta":
            usage = value.get("usage", {})
            delta = value.get("delta", {})
            cumulative = usage.get("output_tokens")
            if (
                closed != blocks.keys()
                or not isinstance(delta, dict)
                or set(delta) - {"stop_reason", "stop_sequence"}
                or delta.get("stop_reason") not in {None, "end_turn"}
                or delta.get("stop_sequence") is not None
                or set(usage) != {"output_tokens"}
                or type(cumulative) is not int
                or type(output_tokens) is not int
                or cumulative < output_tokens
            ):
                raise SafetyError("claude_terminal_usage_required")
            delta_seen, output_tokens = True, cumulative
            terminal = terminal or delta.get("stop_reason") == "end_turn"
        elif event == "message_stop":
            if not terminal or closed != blocks.keys():
                raise SafetyError("claude_terminal_frame_required")
            stopped = True
        else:
            # Unknown billing/tool/error/fallback events cannot assert a known price bound.
            raise SafetyError("claude_unverified_stream_event")
    if (
        not started
        or not stopped
        or any(type(v) is not int or v < 0 for v in (input_tokens, output_tokens))
    ):
        raise SafetyError("claude_incomplete_stream")
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}, "".join(chunks)


class ClaudeBroker:
    def __init__(
        self, ledger, intent, profile, credential, prompt, *, transport=None, check_authority=None
    ):
        # credential is a broker-owned memory callback injected by the operator.
        # It is never serialized, mounted, inherited, logged or read from a user HOME.
        self.ledger, self.intent, self.profile, self.credential = (
            ledger,
            intent,
            profile,
            credential,
        )
        self._transport = transport  # Tests inject httpx.MockTransport, no alternate URL.
        self.result = None
        self.prompt = prompt
        self.check_authority = check_authority

    def exchange(self, raw):
        if self.profile.binding != self.intent.profile_digest:
            raise SafetyError("claude_profile_changed")
        payload = bounded_request(raw, self.profile)
        message = json.loads(payload)["messages"][-1]
        content = message["content"]
        text = content if isinstance(content, str) else "".join(b["text"] for b in content)
        if (
            message["role"] != "user"
            or text != self.prompt
            or (digest(self.prompt) != self.intent.prompt_digest)
        ):
            raise SafetyError("claude_approved_prompt_changed")
        remaining = min(
            self.profile.duration_seconds, self.intent.approval.expires_at - time.time()
        )
        if remaining <= 0:
            raise SafetyError("claude_request_expired")
        key = self.credential()
        if not isinstance(key, str) or not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise SafetyError("claude_broker_credential_unavailable")
        # Commit the consumed fence before any HTTP bytes. No SDK/native retry may replay it.
        if self.check_authority:
            self.check_authority()
        self.ledger.admit(self.intent, digest(json.loads(payload)))
        try:
            output = bytearray()
            deadline = time.monotonic() + remaining
            with httpx.Client(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=min(remaining, 15),
            ) as client:
                with client.stream(
                    "POST",
                    UPSTREAM,
                    content=payload,
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                        "accept": "text/event-stream",
                    },
                ) as response:
                    if response.status_code != 200 or (
                        response.headers.get("content-type", "").split(";")[0]
                        != "text/event-stream"
                    ):
                        raise SafetyError("claude_upstream_response_unverified")
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= deadline or len(output) + len(chunk) > MAX_RESPONSE:
                            raise SafetyError("claude_upstream_limit")
                        output.extend(chunk)
            usage, text = stream_result(bytes(output), self.profile)
            self.ledger.settle(self.intent, self.profile, usage, bytes(output))
            self.result = text
            # No upstream credential/provider request headers are sent back to the CLI.
            return bytes(output)
        except Exception:
            self.ledger.uncertain(self.intent.invocation_id)
            raise SafetyError("claude_upstream_needs_reconciliation") from None

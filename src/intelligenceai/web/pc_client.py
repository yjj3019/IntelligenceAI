"""Opt-in outbound PC client; no DB URL, server session or OIDC secret is required."""

import argparse
import getpass
import hashlib
import json
import os
import secrets
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, Timer
from urllib.parse import urlsplit

import httpx

from intelligenceai.security import clean, digest
from intelligenceai.web.cli_results import parse
from intelligenceai.web.cli_runtime import NativeRuntime
from intelligenceai.web.pc_contracts import AttemptInput, ResultInput

HEARTBEAT_SECONDS = 2


def save(path, value, *, exclusive=False):
    """Fsync before granting native execution. Only this dedicated directory is used."""
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


class API:
    def __init__(self, origin, token):
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("canonical_https_origin_required")
        self.origin, self.token = origin.rstrip("/"), token

    def call(self, action, data):
        if action not in {"exchange", "claim", "start", "heartbeat", "result"}:
            raise ValueError("unsupported_pc_action")
        # No proxy environment, redirects, cookies, URL tokens or arbitrary target requests.
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
            with client.stream(
                "POST",
                self.origin + "/api/pc/" + action,
                json=data,
                headers={"Authorization": "Bearer " + self.token},
            ) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 32768:
                        raise ValueError("pc_response_too_large")
                return json.loads(body)


class Client:
    def __init__(self, api, runtime, state_dir):
        self.api, self.runtime = api, runtime
        self.root = Path(state_dir).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def retry_result(self, attempt_id):
        # UUID validation prevents an operator-supplied journal path from escaping root.
        import uuid

        if str(uuid.UUID(attempt_id)) != attempt_id:
            raise ValueError("invalid_attempt_id")
        value = json.loads((self.root / (attempt_id + ".json")).read_text(encoding="utf-8"))
        if not value.get("result"):
            raise ValueError("unknown_attempt_cannot_replay")
        result = ResultInput.model_validate(value["result"])
        return self.api.call("result", result.model_dump())

    def once(self):
        response = self.api.call("claim", {})
        claim = response.get("attempt")
        if claim is None:
            return False
        bound = AttemptInput.model_validate({key: claim[key] for key in AttemptInput.model_fields})
        if (
            claim["provider"] != self.runtime.provider
            or claim["runtime_digest"] != self.runtime.runtime_digest
            or hashlib.sha256(claim["prompt"].encode("utf-8")).hexdigest()
            != claim["payload_sha256"]
            or len(claim["prompt"].encode("utf-8")) > 8000
        ):
            raise ValueError("pc_local_allowlist_changed")
        journal = self.root / (bound.attempt_id + ".json")
        # Even a lost start response consumes this attempt locally, before the HTTP call.
        save(journal, {"state": "CONSUMED_UNKNOWN", "attempt": bound.model_dump()}, exclusive=True)
        grant = self.api.call("start", bound.model_dump())
        if grant.get("authorized") is not True:
            raise ValueError("pc_start_unavailable")
        deadline = min(
            time.monotonic() + 60, time.monotonic() + max(0, grant["deadline"] - time.time())
        )
        cancelled = False
        expired = Event()

        @contextmanager
        def boundary():
            def check():
                if expired.is_set() or time.monotonic() >= deadline:
                    raise RuntimeError("pc_authority_changed")
                allowed = self.api.call("heartbeat", bound.model_dump()).get("continue") is True
                # HTTP timeouts are per operation/chunk, not the execution wall clock.
                if not allowed or expired.is_set() or time.monotonic() >= deadline:
                    raise RuntimeError("pc_authority_changed")

            check()
            yield check

        workspace = self.root / bound.attempt_id
        workspace.mkdir(mode=0o700)
        process = None
        closed = False
        cleanup_done = False
        cleanup_lock = Lock()

        def cleanup():
            nonlocal closed, cleanup_done
            with cleanup_lock:
                if process is not None and not cleanup_done:
                    cleanup_done = True
                    try:
                        closed = process.close()
                    except Exception:
                        closed = False

        def expire():
            expired.set()
            cleanup()

        watchdog = Timer(max(0, deadline - time.monotonic()), expire)
        watchdog.daemon = True
        watchdog.start()

        def attached(owned):
            nonlocal process
            process = owned
            if expired.is_set():
                cleanup()

        try:
            process = self.runtime.start(workspace, claim["prompt"], boundary, on_spawn=attached)
            if expired.is_set():
                cleanup()
            next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
            while process.process.poll() is None:
                if process.overflow.is_set() or expired.is_set() or time.monotonic() >= deadline:
                    cancelled = True
                    break
                if time.monotonic() >= next_heartbeat:
                    allowed = self.api.call("heartbeat", bound.model_dump()).get("continue") is True
                    if not allowed or expired.is_set() or time.monotonic() >= deadline:
                        cancelled = True
                        break
                    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
                try:
                    process.process.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    pass
        except Exception:
            cancelled = True
        finally:
            cleanup()
            watchdog.cancel()
            watchdog.join()
            cancelled = cancelled or expired.is_set()
        if process:
            stdout, stderr = process.output()
            parsed = parse(
                self.runtime.provider,
                stdout,
                stderr,
                process.process.returncode,
                int(time.time()),
                truncated=process.overflow.is_set(),
            )
        else:
            parsed = {"availability": "EXECUTION_ERROR", "text": None, "usage": {"values": {}}}
        text = clean(parsed["text"] or "")
        available = parsed["availability"] == "AVAILABLE"
        if len(text.encode("utf-8")) > 6000:
            text, available = "", False
            parsed["availability"] = "OUTPUT_TRUNCATED"
        values = parsed["usage"]["values"]
        result = ResultInput(
            **bound.model_dump(),
            outcome="CANCELLED"
            if cancelled and closed
            else "COMPLETED"
            if available and closed
            else "FAILED"
            if closed
            else "UNKNOWN",
            text=text if not cancelled else "",
            cleanup_reported=closed,
            availability=parsed["availability"]
            if parsed["availability"] in {"AVAILABLE", "UNVERIFIED_FORMAT", "OUTPUT_TRUNCATED"}
            else "EXECUTION_ERROR",
            input_tokens=values.get("input_tokens"),
            output_tokens=values.get("output_tokens"),
        )
        # Immutable result journal survives a lost upload response. Never store raw CLI output.
        save(
            journal,
            {
                "state": "RESULT_RECORDED",
                "attempt": bound.model_dump(),
                "result": result.model_dump(),
            },
        )
        self.api.call("result", result.model_dump())
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Owner-approved outbound PC client (no DB/OIDC secret)"
    )
    parser.add_argument("action", choices=["pair", "once", "retry-result"])
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--origin")
    parser.add_argument("--provider", choices=["claude", "codex"])
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--attempt-id")
    args = parser.parse_args()
    try:
        root = args.state_dir.resolve()
        if args.action == "pair":
            if not all((args.origin, args.provider, args.executable, args.version)):
                raise ValueError("local_operator_configuration_required")
            runtime = NativeRuntime(args.provider, args.executable, args.version)
            if not runtime.manifest()["can_execute"]:
                raise ValueError("native_cli_restrictions_unverified")
            code = getpass.getpass("One-time pairing code: ")
            token = secrets.token_urlsafe(32)
            api = API(args.origin, code)
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            config = {
                "origin": args.origin,
                "token": token,
                "provider": args.provider,
                "executable": str(runtime.executable),
                "version": args.version,
            }
            # Never overwrite an existing enrollment or journal.
            save(root / "connection.json", config, exclusive=True)
            manifest = {
                key: runtime.manifest()[key]
                for key in ("provider", "version", "binary_digest", "scope")
            }
            response = api.call(
                "exchange",
                {"token": token, "manifest": manifest | {"runtime_digest": runtime.runtime_digest}},
            )
            print("Provider/version:", runtime.provider, runtime.version)
            print("Binary digest:", runtime.binary_digest)
            print("Runtime digest:", runtime.runtime_digest)
            if response["manifest_digest"] != digest(
                manifest | {"runtime_digest": runtime.runtime_digest}
            ):
                raise ValueError("pc_manifest_changed")
            print("Pending owner confirmation. Device ID:", response["runner_id"])
        else:
            config = json.loads((root / "connection.json").read_text(encoding="utf-8"))
            runtime = NativeRuntime(config["provider"], config["executable"], config["version"])
            client = Client(API(config["origin"], config["token"]), runtime, root)
            if args.action == "retry-result":
                client.retry_result(args.attempt_id)
            else:
                client.once()
    except Exception:
        # Library exceptions may contain URLs or inputs; never print raw transport details.
        parser.exit(
            1, "PC operation unavailable. Check owner approval, local configuration and journal.\n"
        )


if __name__ == "__main__":
    main()

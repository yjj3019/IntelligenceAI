"""Version-scoped protocol preparation. No production transport can be selected here.

_ProtocolSession is an injected-transport contract engine used by project tests only.
Public CLI/controller/MCP never construct it. LiveGateway has no enable flag.
"""

import json
import re
import time
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .adapter_contracts import parse_agy_json, validate_stream
from .contracts import Contract, Step
from .ledger import Ledger
from .security import SafetyError, canonical, clean, redact


class MCPCall(Contract):
    tool: Literal["codereview"] = "codereview"
    arguments: dict


class PreparedInvocation(Contract):
    invocation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    task_id: str
    generation: int = Field(ge=1)
    executor: Literal["omnilane", "mco", "pal", "gemini-cli", "antigravity"]
    contract_version: str
    lane: str
    provider: str
    model: str
    effort: str | None
    mode: Literal["read_only", "write"]
    argv: list[str]
    stdin: str
    cwd: str
    env: dict[str, str] = Field(default_factory=dict)
    deadline: float
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    messages: list[MCPCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_authority(self):
        if self.env or not Path(self.cwd).is_absolute():
            raise ValueError("credential-free empty env and absolute cwd required")
        if self.executor == "pal" and (self.argv or len(self.messages) != 1):
            raise ValueError("PAL requires one allowlisted MCP message")
        return self


def prepare(
    step: Step,
    *,
    task_id: str,
    generation: int,
    invocation_id: str,
    request: str,
    cwd: Path,
    candidate_digest: str,
    now: float | None = None,
) -> PreparedInvocation:
    step = Step.model_validate(step.model_dump())
    cwd = cwd.resolve(strict=True)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}", step.model):
        raise SafetyError("unverified model selector syntax")
    if any("," in p for p in step.allowed_paths):
        raise SafetyError("comma-delimited upstream paths cannot represent this scope")
    timeout = str(step.timeout_seconds)
    version, argv, messages = "", [], []
    if step.executor == "omnilane":
        versions = {
            "claude": {"low", "medium", "high", "xhigh", "max"},
            "codex": {"low", "medium", "high", "xhigh", "max"},
            "grok": {None, "low", "high"},
            "gemini": {"low", "medium", "high"},
        }
        if step.provider not in versions or step.effort not in versions[step.provider]:
            raise SafetyError("Omnilane provider effort contract unverified")
        if step.lane in {"fixture", "omnilane", "mco", "pal", "sysops"}:
            raise SafetyError("an explicit Omnilane routing lane is required")
        version = "omnilane-0.53.0"
        argv = [
            "omnilane",
            "route",
            "--background",
            "--single-shot",
            "--executor",
            "cli",
            "--mode",
            "work" if step.mode == "write" else "advise",
            "--workdir",
            str(cwd),
            "--vendor",
            step.provider,
            "--model",
            step.model,
            "--timeout",
            timeout,
            "--job-timeout",
            timeout,
        ]
        if step.effort is not None:
            argv += ["--effort", step.effort]
        argv += [step.lane, "-"]
    elif step.executor == "mco":
        if step.mode != "read_only" or step.provider not in {
            "claude",
            "codex",
            "grok",
            "gemini",
            "agy",
        }:
            raise SafetyError("MCO is a read-only review protocol")
        if step.effort is not None:
            raise SafetyError("MCO review CLI has no verified per-agent effort flag")
        version = "mco-0.12.1"
        argv = [
            "mco",
            "review",
            "--repo",
            str(cwd),
            "--execution-mode",
            "read_only",
            "--enforcement-mode",
            "strict",
            "--agent",
            f"review={step.provider}:{step.model}",
            "--task-id",
            invocation_id,
            "--file",
            "-",
            "--json",
            "--result-mode",
            "both",
            "--target-paths",
            ",".join(step.allowed_paths),
            "--allow-paths",
            ",".join(step.allowed_paths),
            "--invocation-hard-timeout",
            timeout,
            "--review-hard-timeout",
            timeout,
        ]
    elif step.executor == "pal":
        if (
            step.mode != "read_only"
            or step.provider not in {"gemini", "openai", "anthropic"}
            or step.effort is not None
        ):
            raise SafetyError("PAL codereview provider/effort contract unverified")
        version = "pal-9.8.2"
        messages = [
            MCPCall(
                arguments={
                    "step": redact(request),
                    "step_number": 1,
                    "total_steps": 2,
                    "next_step_required": True,
                    "findings": "",
                    "relevant_files": [str(cwd / p) for p in step.allowed_paths],
                    "model": step.model,
                    "review_validation_type": "internal",
                    "use_assistant_model": False,
                }
            )
        ]
    elif step.executor in {"gemini-cli", "antigravity"}:
        if step.provider != "gemini":
            raise SafetyError("Google executor/provider mismatch")
        if step.executor == "gemini-cli":
            if step.effort is not None:
                raise SafetyError("Gemini CLI effort flag unverified")
            version = "gemini-headless-doc-2026-03-10"
            argv = [
                "gemini",
                "--prompt",
                redact(request),
                "--model",
                step.model,
                "--output-format",
                "json",
            ]
        else:
            if step.effort not in {None, "low", "medium", "high"}:
                raise SafetyError("Antigravity effort value unverified")
            version = "agy-headless-doc-2026-10-10"
            argv = [
                "agy",
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--model",
                step.model,
                "--print-timeout",
                timeout + "s",
            ]
            if step.effort is not None:
                argv += ["--effort", step.effort]
            request = canonical({"event": "user", "message": {"content": redact(request)}}) + "\n"
    else:
        raise SafetyError("no verified preparation contract")
    return PreparedInvocation(
        invocation_id=invocation_id,
        task_id=task_id,
        generation=generation,
        executor=step.executor,
        contract_version=version,
        lane=step.lane,
        provider=step.provider,
        model=step.model,
        effort=step.effort,
        mode=step.mode,
        argv=argv,
        stdin=redact(request),
        cwd=str(cwd),
        deadline=(time.time() if now is None else now) + step.timeout_seconds,
        candidate_digest=candidate_digest,
        messages=messages,
    )


def omnilane_command(prepared: PreparedInvocation, operation: str, job_id: str) -> list[str]:
    if prepared.executor != "omnilane" or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", job_id):
        raise SafetyError("unsafe or wrong native job handle")
    if operation not in {"status", "result", "cancel"}:
        raise SafetyError("unsupported job operation")
    return ["omnilane", "jobs", *([] if operation == "cancel" else ["--json"]), operation, job_id]


def parse_omnilane(payload: str, job_id: str, operation: str) -> dict:
    value = _object(payload)
    job = value.get("job", {})
    if (
        value.get("schema_version") != 1
        or value.get("command") != operation
        or value.get("ok") is not True
        or job.get("id") != job_id
    ):
        raise SafetyError("Omnilane job envelope mismatch")
    if job.get("state") not in {"running", "done", "dead", "pending", "cancelled", "expired"}:
        raise SafetyError("unknown native job state")
    return clean(job | {"answer": None, "model_verification": "UNVERIFIED"})


def _object(payload: str) -> dict:
    try:
        value = json.loads(payload)
    except ValueError as exc:
        raise SafetyError("partial JSON; reconciliation required") from exc
    if not isinstance(value, dict):
        raise SafetyError("protocol envelope must be object")
    return value


def parse_mco(exit_code: int, payload: str) -> dict:
    value = _object(payload)
    status = {0: "complete", 1: "partial", 2: "failed"}.get(exit_code)
    outputs = value.get("outputs")
    if not status or value.get("status") != status or not isinstance(outputs, list):
        raise SafetyError("MCO task status/exit/outputs mismatch")
    for item in outputs:
        if not isinstance(item, dict) or item.get("status") not in {
            "success",
            "failed",
            "timeout",
            "cancelled",
        }:
            raise SafetyError("MCO invocation status invalid")
        if item.get("output") is not None and not isinstance(item["output"], str):
            raise SafetyError("MCO opaque output must be text")
    successes = sum(i["status"] == "success" for i in outputs)
    if (
        (status == "complete" and (not outputs or successes != len(outputs)))
        or (status == "partial" and not 0 < successes < len(outputs))
        or (status == "failed" and successes)
    ):
        raise SafetyError("MCO aggregate contradicts per-invocation statuses")
    return clean(
        {
            "status": status,
            "outputs": [
                {
                    k: i.get(k)
                    for k in ("invocation_id", "provider", "model", "status", "output", "exit_code")
                }
                for i in outputs
            ],
            "model_verification": "UNVERIFIED",
        }
    )


def parse_google(executor: str, exit_code: int, payload: str) -> dict:
    if executor == "gemini-cli":
        value = _object(payload)
        if (
            exit_code != 0
            or "error" in value
            or not isinstance(value.get("response"), str)
            or not isinstance(value.get("stats"), dict)
        ):
            raise SafetyError("Gemini JSON result invalid")
        answer = value["response"]
    elif executor == "antigravity":
        validate_stream(executor, payload.splitlines())
        records = [_object(line) for line in payload.splitlines()]
        identity = records[0].get("conversation_id")
        if not isinstance(identity, str) or not identity:
            raise SafetyError("Antigravity conversation identity missing")
        if any(not isinstance(r.get(r["event"]), dict) for r in records):
            raise SafetyError("Antigravity payload missing")
        if any(r[r["event"]].get("conversation_id", identity) != identity for r in records):
            raise SafetyError("Antigravity conversation mismatch")
        answer = parse_agy_json(exit_code, canonical(records[-1]["result"])).redacted_answer
    else:
        raise SafetyError("unknown Google contract")
    return {
        "status": "TRANSPORT_SUCCESS_ONLY",
        "answer": redact(answer),
        "model_verification": "UNVERIFIED",
    }


def pal_continue(prepared: PreparedInvocation, response: dict, findings: str) -> PreparedInvocation:
    if prepared.executor != "pal" or response.get("status") != "codereview_in_progress":
        raise SafetyError("PAL continuation response unrecognized")
    continuation = response.get("continuation_id")
    if not isinstance(continuation, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", continuation):
        raise SafetyError("PAL continuation handle invalid")
    previous = prepared.messages[0].arguments
    if previous["step_number"] >= 2:
        raise SafetyError("PAL review step budget exhausted")
    args = previous | {
        "step": "Complete the static review",
        "step_number": 2,
        "next_step_required": False,
        "findings": redact(findings),
        "continuation_id": continuation,
    }
    return prepared.model_copy(update={"messages": [MCPCall(arguments=args)]})


class LiveGateway:
    """There is deliberately no env/config/constructor option or external transport."""

    @staticmethod
    def submit(*args, **kwargs):
        raise SafetyError(
            "live dispatch disabled: identity, model mapping and OS containment unverified"
        )

    poll = collect = cancel = reconcile = submit


class TransportReply(Contract):
    exit_code: int
    stdout: str
    termination_verified: bool = False


class _Transport(Protocol):
    def exchange(
        self, prepared: PreparedInvocation, operation: str, job_id: str | None
    ) -> TransportReply: ...


class _ProtocolSession:
    """Offline contract harness. Never instantiated by production service surfaces."""

    def __init__(self, ledger: Ledger, transport: _Transport, scanner, crash_at=None):
        self.ledger, self.transport, self.scanner, self.crash_at = (
            ledger,
            transport,
            scanner,
            crash_at,
        )

    def submit(self, prepared: PreparedInvocation) -> dict:
        prepared = PreparedInvocation.model_validate(prepared.model_dump())
        evidence = self.scanner.scan(
            [canonical(prepared.model_dump()).encode()],
            prepared.candidate_digest,
            "protocol-input-gitleaks-v1",
        )
        if evidence.status != "PASS" or not evidence.live:
            raise SafetyError("verified input scanner required before transport")
        if time.time() >= prepared.deadline:
            raise SafetyError("protocol deadline expired before dispatch")
        with self.ledger.transaction():
            task = self.ledger.task(prepared.task_id)
            if task["generation"] != prepared.generation or task["state"] not in {
                "READY",
                "RUNNING",
            }:
                raise SafetyError("stale or cancelled protocol request")
            old = self.ledger.db.execute(
                "SELECT * FROM invocations WHERE id=?", (prepared.invocation_id,)
            ).fetchone()
            if old:
                if old["data"] != canonical(prepared.model_dump()):
                    raise SafetyError("conflicting protocol invocation identity")
                return dict(old)
            count = self.ledger.db.execute(
                "SELECT count(*) FROM invocations WHERE task_id=?", (prepared.task_id,)
            ).fetchone()[0]
            if count >= task["data"]["budgets"]["max_model_calls"]:
                raise SafetyError("shared call budget exhausted")
            active = self.ledger.db.execute(
                "SELECT count(*) FROM invocations WHERE status IN ('STARTING','RUNNING')"
            ).fetchone()[0]
            if active >= 3:
                raise SafetyError("global active call budget exhausted")
            if prepared.mode == "write":
                self.ledger.db.execute(
                    "INSERT INTO writers VALUES(?,?)", (prepared.cwd, prepared.invocation_id)
                )
            self.ledger.db.execute(
                "INSERT INTO invocations VALUES(?,?,?,?,?,?,NULL)",
                (
                    prepared.invocation_id,
                    prepared.task_id,
                    "STARTING",
                    prepared.generation,
                    prepared.mode,
                    canonical(prepared.model_dump()),
                ),
            )
        if self.crash_at == "starting":
            raise RuntimeError("injected starting crash")
        reply = self.transport.exchange(prepared, "submit", None)
        if self.crash_at == "submitted":
            raise RuntimeError("injected effect before receipt crash")
        if prepared.executor == "omnilane":
            handle = reply.stdout.strip()
            omnilane_command(prepared, "status", handle)
            receipt = {"native_job_id": handle, "status": "RUNNING"}
        elif prepared.executor == "mco":
            receipt = parse_mco(reply.exit_code, reply.stdout)
        elif prepared.executor == "pal":
            receipt = _object(reply.stdout)
        else:
            receipt = parse_google(prepared.executor, reply.exit_code, reply.stdout)
        terminal = "SUCCEEDED"
        if prepared.executor == "mco":
            terminal = {"complete": "SUCCEEDED", "partial": "PARTIAL", "failed": "FAILED"}[
                receipt["status"]
            ]
        self._receipt(
            prepared,
            receipt,
            "RUNNING" if prepared.executor in {"omnilane", "pal"} else terminal,
        )
        return receipt

    def _receipt(self, prepared, receipt, status):
        with self.ledger.transaction():
            row = self.ledger.db.execute(
                "SELECT * FROM invocations WHERE id=?", (prepared.invocation_id,)
            ).fetchone()
            if (
                row is None
                or row["generation"] != prepared.generation
                or self.ledger.task(prepared.task_id)["generation"] != prepared.generation
                or self.ledger.task(prepared.task_id)["state"]
                in {"CANCELLED", "BLOCKED", "NEEDS_RECONCILIATION", "FAILED"}
            ):
                raise SafetyError("stale protocol receipt")
            if row["status"] in {"SUCCEEDED", "PARTIAL", "FAILED"}:
                if row["receipt"] != canonical(clean(receipt)):
                    raise SafetyError("conflicting duplicate protocol receipt")
                return
            self.ledger.db.execute(
                "UPDATE invocations SET status=?,receipt=? WHERE id=?",
                (status, canonical(clean(receipt)), prepared.invocation_id),
            )
            if status in {"SUCCEEDED", "PARTIAL", "FAILED"}:
                self.ledger.db.execute(
                    "DELETE FROM writers WHERE invocation_id=?", (prepared.invocation_id,)
                )

    def poll(self, prepared):
        row = self.ledger.db.execute(
            "SELECT * FROM invocations WHERE id=?", (prepared.invocation_id,)
        ).fetchone()
        if not row or not row["receipt"] or row["data"] != canonical(prepared.model_dump()):
            raise SafetyError("no matching durable protocol handle; reconcile required")
        if self.ledger.task(prepared.task_id)["generation"] != prepared.generation:
            raise SafetyError("stale protocol poll")
        receipt = json.loads(row["receipt"])
        if prepared.executor == "omnilane" and row["status"] == "RUNNING":
            job_id = receipt["native_job_id"]
            reply = self.transport.exchange(prepared, "status", job_id)
            receipt = parse_omnilane(reply.stdout, job_id, "status") | {"native_job_id": job_id}
            self._receipt(prepared, receipt, "RUNNING")
        return receipt

    def collect(self, prepared):
        receipt = self.poll(prepared)
        if prepared.executor != "omnilane":
            return receipt
        if receipt.get("collected"):
            return receipt
        job_id = receipt["native_job_id"]
        reply = self.transport.exchange(prepared, "result", job_id)
        result = parse_omnilane(reply.stdout, job_id, "result")
        if result["state"] != "done" or result.get("exit_code") != 0:
            raise SafetyError("native result not successful; answer metadata is not evidence")
        result |= {"native_job_id": job_id, "collected": True}
        self._receipt(prepared, result, "SUCCEEDED")
        return result

    def advance(self, prepared, findings: str):
        receipt = self.poll(prepared)
        continuation = pal_continue(prepared, receipt, findings)
        evidence = self.scanner.scan(
            [canonical(continuation.model_dump()).encode()],
            prepared.candidate_digest,
            "protocol-input-gitleaks-v1",
        )
        if evidence.status != "PASS" or not evidence.live:
            raise SafetyError("PAL continuation input scan required")
        reply = self.transport.exchange(continuation, "continue", receipt["continuation_id"])
        value = _object(reply.stdout)
        if (
            reply.exit_code != 0
            or value.get("status") != "code_review_complete_ready_for_implementation"
            or value.get("continuation_id") != receipt["continuation_id"]
        ):
            raise SafetyError("PAL continuation completion unverified")
        self._receipt(prepared, value, "SUCCEEDED")
        return clean(value)

    def cancel(self, prepared):
        receipt = self.poll(prepared)
        reply = self.transport.exchange(prepared, "cancel", receipt.get("native_job_id"))
        # A native cancel rc0 never proves process-tree termination.
        self.ledger.cancel(prepared.task_id)
        return {
            "termination_verified": False,
            "native_exit_code": reply.exit_code,
            "state": self.ledger.task(prepared.task_id)["state"],
        }

    def reconcile(self, prepared):
        self.ledger.reconcile(prepared.task_id)
        return self.ledger.task(prepared.task_id)["state"]

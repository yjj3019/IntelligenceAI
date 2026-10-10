"""Fail-closed parsing helpers, not enabled upstream adapters.

Contract examples are locally authored synthetic fixtures. No vendor is launched here.
"""

import json
from dataclasses import dataclass

from .security import SafetyError, redact


@dataclass(frozen=True)
class Observation:
    status: str
    redacted_answer: str
    model_verification: str = "UNVERIFIED"


def opaque_mco_answer(exit_code: int, raw_answer: str) -> Observation:
    # MCO's raw answer is not a finding, consensus or verified test result.
    return Observation(
        {0: "COMPLETE", 1: "PARTIAL", 2: "FAILED"}.get(exit_code, "UNVERIFIED"), redact(raw_answer)
    )


def parse_agy_json(exit_code: int, payload: str) -> Observation:
    try:
        record = json.loads(payload)
    except ValueError as exc:
        raise SafetyError("incomplete Antigravity JSON; reconciliation required") from exc
    if (
        not isinstance(record, dict)
        or record.get("status") != "SUCCESS"
        or exit_code != 0
        or not isinstance(record.get("response"), str)
    ):
        raise SafetyError("Antigravity result is not confirmed successful")
    # rc0/SUCCESS alone do not prove model identity, tool permission or completion criteria.
    return Observation("TRANSPORT_SUCCESS_ONLY", redact(record["response"]))


def validate_stream(executor: str, lines: list[str]) -> Observation:
    types = {
        "gemini-cli": {"init", "message", "tool_use", "tool_result", "error", "result"},
        "antigravity": {"init", "step_update", "result"},
    }
    if executor not in types:
        raise SafetyError("unknown stream contract")
    try:
        records = [json.loads(line) for line in lines]
    except ValueError as exc:
        raise SafetyError("partial stream frame; reconciliation required") from exc
    if (
        not records
        or any(not isinstance(r, dict) for r in records)
        or records[0].get("type") != "init"
        or any(r.get("type") not in types[executor] for r in records)
        or sum(r.get("type") == "result" for r in records) != 1
        or records[-1].get("type") != "result"
    ):
        raise SafetyError("missing, duplicate or mixed stream result")
    return Observation("TERMINAL_FRAME_ONLY", "content withheld; semantic contract unverified")


def expected_executable(executor: str, provider: str) -> str:
    paths = {
        ("omnilane", "gemini"): "agy",
        ("mco", "gemini"): "gemini",
        ("mco", "agy"): "agy",
        ("gemini-cli", "gemini"): "gemini",
        ("antigravity", "gemini"): "agy",
    }
    if (executor, provider) not in paths:
        raise SafetyError("executor/provider mapping unverified")
    return paths[executor, provider]

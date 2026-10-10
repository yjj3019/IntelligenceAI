from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class State(StrEnum):
    RECEIVED = "RECEIVED"
    PLANNED = "PLANNED"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    REVIEWING = "REVIEWING"
    REPAIRING = "REPAIRING"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    UNVERIFIED = "UNVERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


def safe_path(value: str) -> str:
    p = PurePosixPath(value)
    reserved = {".git", ".intelligenceai", ".agents", ".codex", ".aws", ".ssh"}
    devices = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if (
        not value
        or p.is_absolute()
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 for c in value)
        or str(p) != value
        or any(
            x in {".", ".."}
            or x.lower() in reserved
            or x.endswith((".", " "))
            or x.split(".")[0].lower() in devices
            for x in p.parts
        )
    ):
        raise ValueError("unsafe or controller-owned path")
    return value


class Budgets(Contract):
    max_model_calls: int = Field(default=3, ge=1, le=3)
    max_repairs: int = Field(default=2, ge=0, le=2)
    same_failure_limit: int = Field(default=3, ge=1, le=3)


class Step(Contract):
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    dependencies: list[str] = Field(default_factory=list)
    role: Literal["implement", "review", "analyze"]
    lane: Literal["fixture", "omnilane", "mco", "pal"] = "fixture"
    executor: str = "fixture"
    provider: str = "fixture"
    model: str = "deterministic-v1"
    effort: Literal["low", "medium", "high"] = "low"
    mode: Literal["write", "read_only"]
    allowed_paths: list[str] = Field(min_length=1)
    fallback_allowed: Literal[False] = False
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    repair_round: int = Field(default=0, ge=0, le=2)

    @field_validator("allowed_paths")
    @classmethod
    def paths(cls, values: list[str]) -> list[str]:
        return [safe_path(v) for v in values]

    @model_validator(mode="after")
    def role_mode(self):
        if self.role != "implement" and self.mode != "read_only":
            raise ValueError("reviews and analysis must be read only")
        return self


class Plan(Contract):
    schema_version: Literal[1] = 1
    steps: list[Step] = Field(min_length=1, max_length=16)
    budgets: Budgets = Field(default_factory=Budgets)

    @model_validator(mode="after")
    def dag(self):
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate step")
        if sum(s.mode == "write" for s in self.steps) > 1:
            raise ValueError("initial controller supports one writer step")
        done: set[str] = set()
        for _ in self.steps:
            for s in self.steps:
                if set(s.dependencies) <= done:
                    done.add(s.step_id)
        if done != set(ids):
            raise ValueError("cyclic or missing dependency")
        return self


class Task(Contract):
    task_id: str
    redacted_request: str
    repo_identity: str
    base_sha: str
    plan_version: int = 1
    policy_version: str = "local-fixture-v1"
    state: str = State.RECEIVED
    budgets: Budgets = Field(default_factory=Budgets)
    generation: int = 1


class Invocation(Contract):
    invocation_id: str
    task_id: str
    step_id: str
    attempt: int
    owner_generation: int
    executor: str
    provider: str
    model: str
    effort: str
    mode: str
    status: str = "RESERVED"
    native_job_id: str | None = None
    process_identity: str | None = None
    receipt: str | None = None


class Candidate(Contract):
    candidate_id: str
    base_sha: str
    head_sha: str
    tree_digest: str
    changed_paths: list[str]
    artifact_digests: dict[str, str]


class Finding(Contract):
    finding_id: str
    candidate_id: str
    source_invocation: str
    evidence: str
    reproduced: bool
    blocking: bool
    resolution: Literal["open", "resolved", "unverified"] = "open"


class Evidence(Contract):
    candidate_id: str
    command_profile: str
    tool_version: str
    environment: str
    exit_code: int | None
    status: Literal["PASS", "FAIL", "UNVERIFIED"]
    redacted_log: str
    timestamp: float
    live: bool = False


class Action(Contract):
    kind: Literal["publish", "push", "merge", "deploy"]
    destination: str = Field(min_length=1, max_length=512)
    argv: list[str] = Field(min_length=1, max_length=16)


class Approval(Contract):
    approval_id: str
    principal: str
    action_digest: str
    candidate_id: str
    policy_version: str
    scope: list[str]
    decision: Literal["approve", "reject"]
    expires_at: float

"""Narrow outbound PC contract. No commands, environment, paths or browser principals."""

from typing import Literal

from pydantic import Field

from intelligenceai.web.contracts import Input

PC_ROUTES = frozenset(
    "/api/pc/" + action for action in ("exchange", "claim", "start", "heartbeat", "result")
)


class PairInput(Input):
    provider: Literal["claude", "codex"]


class Manifest(Input):
    provider: Literal["claude", "codex"]
    version: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9._-]+$")
    runtime_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    binary_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    scope: Literal["LOCAL_NATIVE_CLI", "FAKE_CLI_TEST_ONLY"]


class ExchangeInput(Input):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    manifest: Manifest


class ConfirmInput(Input):
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class AttemptInput(Input):
    attempt_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    task_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    generation: int = Field(ge=1)
    binding_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    lease: str = Field(pattern=r"^[a-f0-9]{64}$")


class ResultInput(AttemptInput):
    outcome: Literal["COMPLETED", "FAILED", "CANCELLED", "UNKNOWN"]
    text: str = Field(max_length=6000)
    cleanup_reported: bool
    availability: Literal["AVAILABLE", "EXECUTION_ERROR", "UNVERIFIED_FORMAT", "OUTPUT_TRUNCATED"]
    input_tokens: int | None = Field(default=None, ge=0, le=10**12)
    output_tokens: int | None = Field(default=None, ge=0, le=10**12)

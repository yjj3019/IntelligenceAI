"""Operator-only tool-free Claude review profile. No defaults for model or pricing."""

from typing import Literal

from pydantic import Field, model_validator

from intelligenceai.contracts import Contract
from intelligenceai.isolation_contracts import Digest, Identity, PinnedRoot
from intelligenceai.security import digest
from intelligenceai.web.live_authority import PaidApprovalBinding


class ClaudeProfile(Contract):
    version: Literal[1] = 1
    provider: Literal["claude"] = "claude"
    purpose: Literal["immutable_candidate_review"] = "immutable_candidate_review"
    credential_mode: Literal["broker_api_key"] = "broker_api_key"
    model: str = Field(pattern=r"^claude-[a-z0-9][a-z0-9-]{1,100}$")
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    cli_version: Literal["2.1.296"] = "2.1.296"
    image: PinnedRoot
    backend_digest: Digest
    cli_digest: Digest
    bridge_digest: Digest
    # Whole supported context ceiling, not a heuristic tokenizer estimate.
    input_token_ceiling: int = Field(ge=1, le=2_000_000)
    output_token_limit: int = Field(ge=1, le=64_000)
    # microusd/token, rounded UP, including the greatest applicable premium.
    input_price_ceiling: int = Field(ge=1, le=10_000)
    output_price_ceiling: int = Field(ge=1, le=100_000)
    pricing_evidence_digest: Digest
    policy_digest: Digest
    memory_bytes: int = Field(ge=128 * 1024 * 1024, le=8 * 1024**3)
    pids: int = Field(ge=4, le=128)
    cpu_quota_us: int = Field(ge=1000, le=400_000)
    duration_seconds: int = Field(ge=1, le=240)

    @property
    def reservation(self):
        return (
            self.input_token_ceiling * self.input_price_ceiling
            + self.output_token_limit * self.output_price_ceiling
        )

    @property
    def binding(self):
        return digest(self.model_dump(mode="json"))


class PaidReviewIntent(Contract):
    invocation_id: Identity
    approved_by: Identity
    approval: PaidApprovalBinding
    profile_digest: Digest
    prompt_digest: Digest
    budget_microusd: int = Field(ge=1, le=1_000_000_000_000)

    @model_validator(mode="after")
    def review_destination(self):
        if self.approval.destination_id != "private-model-review":
            raise ValueError("a candidate application approval is not paid review authority")
        return self

    @property
    def binding(self):
        return digest(self.model_dump(mode="json"))


def claude_argv(profile: ClaudeProfile):
    """Inside the immutable image. Prompt arrives on stdin, never a shell argument."""
    return (
        "/claude",
        "--bare",
        "--print",
        "--output-format",
        "json",
        "--model",
        profile.model,
        "--effort",
        profile.effort,
        "--tools",
        "",
        "--disallowedTools",
        "*",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--setting-sources",
        "",
        "--settings",
        '{"disableAllHooks":true}',
        "--no-session-persistence",
        "--max-turns",
        "1",
    )

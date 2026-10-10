"""Trusted launch contracts. No browser input, credential value or enable switch."""

import platform
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import Contract, safe_path
from .security import SafetyError, digest, require_no_secrets

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identity = Annotated[
    str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
]
Provider = Literal["claude", "codex", "grok", "gemini-cli", "antigravity", "isolation-probe"]
Mode = Literal["read_only", "write"]
HostOS = Literal["Linux", "Darwin", "Windows"]


class PinnedRoot(Contract):
    path: str
    tree_digest: Digest

    @field_validator("path")
    @classmethod
    def absolute(cls, value):
        if not Path(value).is_absolute() or "\x00" in value:
            raise ValueError("absolute operator-owned root required")
        return value


class NetworkPolicy(Contract):
    provider_hosts: tuple[str, ...] = ()
    generated_tools: Literal["deny"] = "deny"
    enforcement_digest: Digest | None = None

    @field_validator("provider_hosts")
    @classmethod
    def domains(cls, values):
        if len(set(values)) != len(values) or any(
            not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,63}", v) for v in values
        ):
            raise ValueError("exact provider domains required; URLs, wildcards and IPs forbidden")
        return values


class InvocationBudget(Contract):
    wrapper_attempts: Literal[1] = 1
    max_invocations: int = Field(ge=1, le=3)
    max_cost_microusd: int = Field(ge=1, le=1_000_000_000_000)
    native_retries: Literal["UNVERIFIED"] = "UNVERIFIED"
    accounting: Literal["WRAPPER_INVOCATIONS_ONLY"] = "WRAPPER_INVOCATIONS_ONLY"


class LaunchManifest(Contract):
    """All authority comes from a trusted runner's independently verified profile."""

    version: Literal[1] = 1
    invocation_id: Identity
    task_id: Identity
    project_id: Identity
    actor_id: Identity
    generation: int = Field(ge=1)
    provider: Provider
    model: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$")
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None
    mode: Mode
    host_os: HostOS
    backend: Literal["linux-bwrap-offline-v1", "linux-bwrap-claude-relay-v1"]
    backend_binary_digest: Digest
    vendor_binary_digest: Digest
    runner_digest: Digest
    policy_digest: Digest
    image: PinnedRoot
    workspace: PinnedRoot
    writable_files: tuple[str, ...] = ()
    network: NetworkPolicy
    credential_refs: tuple[Identity, ...] = ()
    overlay_digest: Digest | None = None
    caller_context_digest: Digest | None = None
    deadline: float = Field(gt=0, allow_inf_nan=False)
    budget: InvocationBudget
    fallback_allowed: Literal[False] = False

    @field_validator("writable_files")
    @classmethod
    def scoped_paths(cls, values):
        if len(values) > 32 or len(set(values)) != len(values):
            raise ValueError("bounded unique writable files required")
        return tuple(safe_path(value) for value in values)

    @model_validator(mode="after")
    def boundaries(self):
        if (self.mode == "read_only" and self.writable_files) or (
            self.mode == "write" and not self.writable_files
        ):
            raise ValueError("mode and explicit write scope disagree")
        if self.provider == "grok" and self.host_os == "Darwin" and self.mode == "write":
            raise ValueError("Grok macOS work is unsupported; no unconfined fallback")
        if self.provider != "isolation-probe" and not (
            self.overlay_digest and self.caller_context_digest
        ):
            raise ValueError("caller and transport overlay bindings required")
        if self.provider == "isolation-probe" and (
            self.network.provider_hosts or self.credential_refs
        ):
            raise ValueError("offline isolation probes cannot have network or credentials")
        require_no_secrets(self.model_dump(mode="json"))
        return self

    @property
    def binding(self):
        return digest(self.model_dump(mode="json"))

    def revalidate(self):
        # model_copy(update=...) bypasses validation, including on frozen models.
        return type(self).model_validate(self.model_dump())


class CapabilityEvidence(Contract):
    """Evidence reference, not authorization; a verifier must validate its signature/provenance."""

    manifest_digest: Digest
    host_os: HostOS
    provider: Provider
    mode: Mode
    expires_at: float = Field(gt=0, allow_inf_nan=False)
    scope: Literal["OFFLINE_PROBE", "LIVE_PROVIDER"]
    evidence_digest: Digest

    def matches(self, manifest: LaunchManifest, *, now: float):
        self.revalidate()
        manifest.revalidate()
        return (
            self.manifest_digest == manifest.binding
            and self.host_os == manifest.host_os
            and self.provider == manifest.provider
            and self.mode == manifest.mode
            and now < self.expires_at
            and now < manifest.deadline
            and (self.scope == "OFFLINE_PROBE") == (manifest.provider == "isolation-probe")
        )

    def revalidate(self):
        return type(self).model_validate(self.model_dump())


CONTROL_FILES = frozenset(
    {
        ".claude",
        ".codex",
        ".grok",
        ".gemini",
        ".omnilane",
        ".mcp.json",
        ".env",
        "agents.md",
        ".agents",
        ".claude-plugin",
        ".git",
        ".aws",
        ".ssh",
        "claude.md",
        "gemini.md",
        "grok.md",
        ".bashrc",
        ".profile",
    }
)


def reject_control_paths(paths):
    for value in paths:
        parts = PurePosixPath(str(value).replace("\\", "/")).parts
        if any(part.lower() in CONTROL_FILES or part.lower().startswith(".env.") for part in parts):
            raise SafetyError(
                "project hook/MCP/credential configuration cannot enter provider image"
            )


def live_readiness(provider: str, mode: str, *, host_os: str | None = None):
    """Read-only status. File existence never counts as OS/provider verification."""
    current_os = host_os or platform.system()
    if provider not in {"claude", "codex", "grok", "gemini-cli", "antigravity"} or mode not in {
        "read_only",
        "write",
    }:
        raise SafetyError("provider/mode contract not supported")
    reasons = [
        "provider_capability_unverified",
        "credential_broker_unavailable",
        "budget_enforcement_unverified",
        "paid_model_not_authorized",
    ]
    if current_os != "Linux":
        reasons.insert(0, "isolation_backend_unsupported")
    elif not shutil.which("bwrap"):
        reasons.insert(0, "isolation_backend_unavailable")
    else:
        reasons.insert(0, "isolation_probe_required")
    if provider == "grok" and current_os == "Darwin" and mode == "write":
        reasons.insert(0, "grok_macos_write_unsupported")
    return {
        "provider": provider,
        "mode": mode,
        "host_os": current_os,
        "status": "BLOCKED",
        "reasons": reasons,
        "live_model": "NOTRUN",
        "os_isolation": "UNVERIFIED",
        "wrapper_attempts": 1,
        "native_retries": "UNVERIFIED",
    }

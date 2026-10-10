from dataclasses import asdict, dataclass

from .contracts import Step
from .security import SafetyError


@dataclass(frozen=True)
class Capability:
    executor: str
    providers: tuple[str, ...]
    enabled: bool
    verification: str
    reason: str


CAPABILITIES = {
    "static": Capability(
        "static",
        ("local",),
        True,
        "STATIC_ONLY",
        "Declarative parsers only; project code and test/build execution disabled",
    ),
    "fixture": Capability(
        "fixture",
        ("fixture",),
        True,
        "FIXTURE_ONLY",
        "Trusted deterministic local fixture; no vendor or subprocess worker",
    ),
    "omnilane": Capability(
        "omnilane",
        ("claude", "codex", "grok", "gemini"),
        False,
        "UNVERIFIED",
        "Exact upstream identity, caller/transport and OS enforcement unverified",
    ),
    "mco": Capability(
        "mco",
        ("claude", "codex", "grok", "gemini", "agy"),
        False,
        "UNVERIFIED",
        "Raw-answer contract researched; read-only enforcement and receipts unverified",
    ),
    "pal": Capability(
        "pal",
        ("gemini", "openai", "anthropic"),
        False,
        "UNVERIFIED",
        "No verified tool allowlist, cancellation or artifact isolation; clink excluded",
    ),
    "gemini-cli": Capability(
        "gemini-cli",
        ("gemini",),
        False,
        "UNVERIFIED",
        "Independent CLI path requires version and OS sandbox verification",
    ),
    "antigravity": Capability(
        "antigravity",
        ("gemini",),
        False,
        "UNVERIFIED",
        "Execution product is not a Gemini CLI/API alias; contract unresolved",
    ),
}


def registry() -> list[dict]:
    return [asdict(c) for c in CAPABILITIES.values()]


def authorize_step(step: Step):
    step = Step.model_validate(step.model_dump())
    # A mutable capability report or environment variable cannot enable live execution.
    if step.executor not in {"fixture", "static"}:
        raise SafetyError("live executor dispatch is unconditionally disabled")
    cap = CAPABILITIES.get(step.executor)
    if not cap or not cap.enabled or step.provider not in cap.providers:
        raise SafetyError("executor/provider capability disabled or unverified")
    if step.executor == "fixture" and (step.lane != "fixture" or step.model != "deterministic-v1"):
        raise SafetyError("fixture cannot stand in for a requested vendor/model")
    if step.executor == "static" and (
        step.provider != "local"
        or step.model != "static-v1"
        or step.lane != "fixture"
        or step.effort is not None
    ):
        raise SafetyError("static checker cannot stand in for a vendor/model")

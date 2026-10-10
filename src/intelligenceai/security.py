import hashlib
import json
import re
from typing import Any


class SafetyError(RuntimeError):
    pass


# Defense in depth, not a replacement for the required Gitleaks gate.
PATTERNS = [
    re.compile(
        r"(?i)(?:sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9]{16,}|"
        r"github_pat_[a-z0-9_]{16,}|AKIA[A-Z0-9]{16}|IAI_TEST_SECRET_[A-Z0-9]+)"
    ),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----"),
    re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@"),
]


def redact(value: str) -> str:
    for pattern in PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def clean(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {redact(str(k)): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require_no_secrets(value: Any):
    if clean(value) != value:
        raise SafetyError("sensitive payload blocked before outbound transmission")

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from intelligenceai.security import require_no_secrets


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyInput(Input):
    pass


class TaskInput(Input):
    title: str = Field(min_length=3, max_length=120)
    request: str = Field(min_length=3, max_length=4000)
    profile: Literal["python-review", "json-review"]

    @field_validator("title", "request")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("control characters forbidden")
        try:
            require_no_secrets(value)
        except RuntimeError as exc:
            raise ValueError("remove credentials before submission") from exc
        result = value.strip()
        if len(result) < 3:
            raise ValueError("at least three non-whitespace characters required")
        return result


class ApprovalInput(Input):
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    destination_id: Literal["private-review"]
    generation: int = Field(ge=1)
    expires_at: int = Field(ge=1)


class MemberInput(Input):
    user_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    role: Literal["viewer", "operator", "approver", "owner", "revoked"]


def preview(data: TaskInput) -> dict:
    """Fixed declarative plan; request text never becomes code, argv, paths or URLs."""
    path = "answer.py" if data.profile == "python-review" else "settings.json"
    return {
        "profile": data.profile,
        "steps": [
            {"id": "inspect", "role": "analyze", "depends_on": [], "mode": "read_only"},
            {
                "id": "candidate",
                "role": "implement",
                "depends_on": ["inspect"],
                "mode": "disabled",
            },
            {
                "id": "verify",
                "role": "review",
                "depends_on": ["candidate"],
                "mode": "read_only",
            },
            {"id": "approval", "role": "gate", "depends_on": ["verify"], "mode": "human"},
        ],
        "scope": [path],
        "model_calls": 0,
        "execution_enabled": False,
        "evidence": "UNVERIFIED",
        "reason": "No verified Linux runner or provider configured",
    }

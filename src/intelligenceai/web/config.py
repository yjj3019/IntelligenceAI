import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str
    origin: str
    issuer: str
    client_id: str
    client_secret: str
    static_dir: str
    secure: bool = True

    @classmethod
    def from_env(cls):
        required = [
            "DATABASE_URL",
            "PUBLIC_ORIGIN",
            "OIDC_ISSUER",
            "OIDC_CLIENT_ID",
            "OIDC_CLIENT_SECRET",
        ]
        values = {key: os.environ.get("IAI_" + key, "") for key in required}
        if not all(values.values()):
            raise ValueError("missing required IAI web configuration; see docs/web-deployment.md")
        for key in ["PUBLIC_ORIGIN", "OIDC_ISSUER"]:
            parsed = urlsplit(values[key])
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "web origin and OIDC issuer require operator-configured HTTPS URLs"
                )
        if urlsplit(values["PUBLIC_ORIGIN"]).path not in {"", "/"}:
            raise ValueError("PUBLIC_ORIGIN cannot contain a path")
        return cls(
            database_url=values["DATABASE_URL"],
            origin=values["PUBLIC_ORIGIN"].rstrip("/"),
            issuer=values["OIDC_ISSUER"].rstrip("/"),
            client_id=values["OIDC_CLIENT_ID"],
            client_secret=values["OIDC_CLIENT_SECRET"],
            static_dir=os.environ.get("IAI_STATIC_DIR", "web/dist"),
        )

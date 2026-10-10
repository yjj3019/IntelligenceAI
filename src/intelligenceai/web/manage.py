"""Operator-only initialization. No HTTP bootstrap, user enrollment or credential creation."""

import argparse

from intelligenceai.web.config import Settings
from intelligenceai.web.service import Problem, bootstrap
from intelligenceai.web.store import engine, metadata


def main():
    parser = argparse.ArgumentParser(description="Initialize a private IntelligenceAI web ledger")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    owner = commands.add_parser("bootstrap")
    owner.add_argument("--subject", required=True, help="existing verified OIDC subject")
    owner.add_argument("--name", required=True)
    owner.add_argument("--project", required=True)
    args = parser.parse_args()
    config = Settings.from_env()
    db = engine(config.database_url)
    try:
        if args.command == "init-db":
            metadata.create_all(db)
            print("Initial web schema ready. Existing schemas are not automatically migrated.")
        else:
            _, project = bootstrap(db, config.issuer, args.subject, args.name, args.project)
            print("Project owner provisioned:", project)
    except Problem as exc:
        raise SystemExit(exc.code) from None
    except Exception:
        raise SystemExit(
            "Web ledger initialization failed; check operator configuration."
        ) from None
    finally:
        db.dispose()


if __name__ == "__main__":
    main()

"""Operator-only initialization. No HTTP bootstrap, user enrollment or credential creation."""

import argparse

from sqlalchemy import delete, insert, select

from intelligenceai.web.config import Settings
from intelligenceai.web.service import Problem, bootstrap
from intelligenceai.web.store import engine, execution_grants, metadata, now, projects


def main():
    parser = argparse.ArgumentParser(description="Initialize a private IntelligenceAI web ledger")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    grant = commands.add_parser("allow-fixed-fixture")
    grant.add_argument("--project", required=True)
    grant.add_argument("--seconds", type=int, default=3600)
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
        elif args.command == "allow-fixed-fixture":
            if not 60 <= args.seconds <= 86400:
                raise Problem(400, "fixture_grant_ttl_invalid")
            with db.begin() as conn:
                project = (
                    conn.execute(
                        select(projects).where(projects.c.id == args.project).with_for_update()
                    )
                    .mappings()
                    .one()
                )
                conn.execute(
                    delete(execution_grants).where(execution_grants.c.project_id == args.project)
                )
                conn.execute(
                    insert(execution_grants).values(
                        project_id=args.project,
                        mode="fixed-fixture",
                        policy_digest=project["policy_digest"],
                        expires_at=now() + args.seconds,
                    )
                )
            print("Fixed fixture only authorized; live providers and effects remain disabled")
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

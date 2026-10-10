"""Portable fixture schema; production uses PostgreSQL, never core SQLite/file locks."""

import time
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.pool import StaticPool

metadata = MetaData()
users = Table(
    "web_users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("issuer", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("name", String(120), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    UniqueConstraint("issuer", "subject"),
)
projects = Table(
    "web_projects",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), nullable=False),
    Column("name", String(120), nullable=False),
    Column("policy_digest", String(64), nullable=False),
)
members = Table(
    "web_members",
    metadata,
    Column("project_id", ForeignKey(projects.c.id), primary_key=True),
    Column("user_id", ForeignKey(users.c.id), primary_key=True),
    Column("role", String(16), nullable=False),
)
sessions = Table(
    "web_sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("data", JSON, nullable=False),
    Column("expires_at", BigInteger, nullable=False),
    Column("revoked", Boolean, nullable=False, default=False),
    Column("version", Integer, nullable=False, default=1),
)
tasks = Table(
    "web_tasks",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False, index=True),
    Column("actor_id", ForeignKey(users.c.id), nullable=False),
    Column("title", String(120), nullable=False),
    Column("request", Text, nullable=False),
    Column("plan", JSON, nullable=False),
    Column("state", String(32), nullable=False),
    Column("generation", Integer, nullable=False, default=1),
    Column("created_at", BigInteger, nullable=False),
    Column("candidate_digest", String(64)),
    Column("evidence_digest", String(64)),
    Column("evidence_verified", Boolean, nullable=False, default=False),
    Column("destination_id", String(32), nullable=False, default="private-review"),
)
jobs = Table(
    "web_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey(tasks.c.id), unique=True, nullable=False),
    Column("generation", Integer, nullable=False),
    Column("state", String(32), nullable=False),
    Column("cancel_requested", Boolean, nullable=False, default=False),
    Column("lease_token", String(64)),
    Column("lease_expires_at", BigInteger),
)
execution_grants = Table(
    "web_execution_grants",
    metadata,
    Column("project_id", ForeignKey(projects.c.id), primary_key=True),
    Column("mode", String(32), nullable=False),
    Column("policy_digest", String(64), nullable=False),
    Column("expires_at", BigInteger, nullable=False),
)
attempts = Table(
    "web_attempts",
    metadata,
    Column("core_task_id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False),
    Column("task_id", ForeignKey(tasks.c.id), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("phase", String(32), nullable=False),
    Column("profile", String(32), nullable=False),
    Column("policy_digest", String(64), nullable=False),
    Column("plan_digest", String(64), nullable=False),
    Column("receipt", JSON),
    UniqueConstraint("task_id", "generation"),
)
receipts = Table(
    "web_receipts",
    metadata,
    Column("project_id", ForeignKey(projects.c.id), primary_key=True),
    Column("actor_id", ForeignKey(users.c.id), primary_key=True),
    Column("key", String(128), primary_key=True),
    Column("payload_digest", String(64), nullable=False),
    Column("result", JSON, nullable=False),
)
approvals = Table(
    "web_approvals",
    metadata,
    Column("task_id", ForeignKey(tasks.c.id), primary_key=True),
    Column("actor_id", ForeignKey(users.c.id), nullable=False),
    Column("binding", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
)
vendor_invocations = Table(
    "web_vendor_invocations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False),
    Column("task_id", ForeignKey(tasks.c.id), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("actor_id", ForeignKey(users.c.id), nullable=False),
    Column("session_hash", ForeignKey(sessions.c.token_hash), nullable=False),
    Column("approved_by", ForeignKey(users.c.id), nullable=False),
    Column("binding", JSON, nullable=False),
    Column("binding_digest", String(64), nullable=False),
    Column("deadline", BigInteger, nullable=False),
    Column("state", String(32), nullable=False),
    Column("lease_token", String(64)),
    Column("lease_expires_at", BigInteger),
    Column("result", JSON),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("task_id", "generation"),
)
paid_budgets = Table(
    "web_paid_budgets",
    metadata,
    Column("project_id", ForeignKey(projects.c.id), primary_key=True),
    Column("policy_digest", String(64), nullable=False),
    Column("limit_microusd", BigInteger, nullable=False),
    Column("held_microusd", BigInteger, nullable=False, default=0),
    Column("spent_microusd", BigInteger, nullable=False, default=0),
    Column("expires_at", BigInteger, nullable=False),
)
paid_reviews = Table(
    "web_paid_reviews",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False),
    Column("task_id", ForeignKey(tasks.c.id), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("actor_id", ForeignKey(users.c.id), nullable=False),
    Column("session_hash", ForeignKey(sessions.c.token_hash), nullable=False),
    Column("approved_by", ForeignKey(users.c.id), nullable=False),
    Column("intent", JSON, nullable=False),
    Column("intent_digest", String(64), nullable=False),
    Column("receipt_digest", String(64), nullable=False),
    Column("revoked", Boolean, nullable=False, default=False),
    Column("termination_confirmed", Boolean, nullable=False, default=False),
    Column("state", String(32), nullable=False),
    Column("hold_microusd", BigInteger, nullable=False),
    Column("request_digest", String(64)),
    Column("result", JSON),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("task_id", "generation"),
)


paid_profiles = Table(
    "web_paid_profiles",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False, index=True),
    Column("name", String(80), nullable=False),
    Column("profile", JSON, nullable=False),
    Column("active", Boolean, nullable=False, default=False),
)
paid_requests = Table(
    "web_paid_requests",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False, index=True),
    Column("task_id", ForeignKey(tasks.c.id), nullable=False, index=True),
    Column("actor_id", ForeignKey(users.c.id), nullable=False),
    Column("session_hash", ForeignKey(sessions.c.token_hash), nullable=False),
    Column("profile_id", ForeignKey(paid_profiles.c.id), nullable=False),
    Column("quote", JSON, nullable=False),
    Column("quote_digest", String(64), nullable=False),
    Column("state", String(32), nullable=False),
    Column("created_at", BigInteger, nullable=False),
)

paid_dispatches = Table(
    "web_paid_dispatches",
    metadata,
    Column("request_id", ForeignKey(paid_requests.c.id), primary_key=True),
    Column("invocation_id", ForeignKey(paid_reviews.c.id), nullable=False, unique=True),
    Column("descriptor", JSON, nullable=False),
    Column("descriptor_digest", String(64), nullable=False),
    Column("quote_digest", String(64), nullable=False),
    Column("created_at", BigInteger, nullable=False),
)

artifacts = Table(
    "web_artifacts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey(tasks.c.id), nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("digest", String(64), nullable=False),
)
audit = Table(
    "web_audit",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False, index=True),
    Column("actor_id", ForeignKey(users.c.id), nullable=False),
    Column("task_id", String(36)),
    Column("event", String(64), nullable=False),
    Column("detail", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
)


local_cli_profiles = Table(
    "web_local_cli_profiles",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False),
    Column("actor_id", ForeignKey(users.c.id), nullable=False),
    Column("provider", String(16), nullable=False),
    Column("runtime_digest", String(64), nullable=False),
    Column("metadata", JSON, nullable=False),
    Column("active", Boolean, nullable=False, default=True),
)
local_cli_requests = Table(
    "web_local_cli_requests",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False),
    Column("task_id", ForeignKey(tasks.c.id), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("actor_id", ForeignKey(users.c.id), nullable=False),
    Column("session_hash", ForeignKey(sessions.c.token_hash), nullable=False),
    Column("profile_id", ForeignKey(local_cli_profiles.c.id), nullable=False),
    Column("binding", JSON, nullable=False),
    Column("binding_digest", String(64), nullable=False),
    Column("state", String(32), nullable=False),
    Column("lease_token", String(64)),
    Column("result", JSON),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("task_id", "generation"),
)

# Additive schema: a PC has one owner/project/provider and one approved immutable profile.
pc_runners = Table(
    "web_pc_runners",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", ForeignKey(projects.c.id), nullable=False),
    Column("actor_id", ForeignKey(users.c.id), nullable=False),
    Column("provider", String(16), nullable=False),
    Column("pair_hash", String(64), unique=True),
    Column("token_hash", String(64), unique=True),
    Column("state", String(16), nullable=False),
    Column("expires_at", BigInteger, nullable=False),
    Column("manifest", JSON),
    Column("manifest_digest", String(64)),
    Column("profile_id", ForeignKey(local_cli_profiles.c.id)),
)
pc_attempts = Table(
    "web_pc_attempts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("runner_id", ForeignKey(pc_runners.c.id), nullable=False),
    Column("request_id", ForeignKey(local_cli_requests.c.id), unique=True, nullable=False),
    Column("binding_digest", String(64), nullable=False),
    Column("lease", String(64), nullable=False),
    Column("expires_at", BigInteger, nullable=False),
    Column("deadline", BigInteger, nullable=False),
    Column("state", String(16), nullable=False),
    Column("result_digest", String(64)),
    Column("result", JSON),
)


def now() -> int:
    return int(time.time())


def uid() -> str:
    return str(uuid.uuid4())


def engine(url: str, *, testing: bool = False):
    if not testing and not url.startswith("postgresql+psycopg://"):
        raise ValueError("production requires PostgreSQL + psycopg")
    options = {"pool_pre_ping": True}
    if testing and url == "sqlite://":
        options = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    result = create_engine(url, **options)
    if result.dialect.name == "sqlite":

        @event.listens_for(result, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return result

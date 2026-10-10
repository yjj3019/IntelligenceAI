# Fixed fixture supervisor

The runner now connects the durable web inbox to the real core typed DAG, within a narrow offline scope. It creates an owned synthetic Git repository, executes one deterministic fixture writer and static AST/JSON parsers, then imports a private candidate and receipts. It never opens a user repository, executes submitted code, invokes a vendor CLI or authorizes an external effect. Real models are **NOTRUN**, OS containment is **UNVERIFIED**, and the core secret scanner remains **UNVERIFIED**. Static parser PASS means only that the fixed candidate bytes satisfy that parser.

## Admission and authority

Saving a task still creates `BLOCKED` / `HELD`. An operator must provision an expiring `fixed-fixture` execution capability, bound to the current project policy, using `python -m intelligenceai.web.manage allow-fixed-fixture --project PROJECT_UUID --seconds 3600`. This is a trusted management operation with no HTTP equivalent. It does not create a credential. The console's explicit **Run fixed fixture** action posts an empty JSON object to `.../tasks/TASK_UUID/run-fixture`. The session actor must be an active operator/owner. An idempotent request records `QUEUED`; GET/status/SSE/Refresh never enqueue, claim or reconcile.

`private-review` approvals bind the current frozen candidate, policy, static evidence, destination, generation and expiry. The service rechecks snapshot bytes/digests and current approver role. A current review binding and separate fixture capability can admit only the explicit [approved fake vendor flow](web-approved-vendor.md). Review approval cannot enable live execution, publishing, paid models, push, merge or deployment.

## Ownership and recovery

Queue scanning uses bounded keyset pages ordered by creation time and task UUID. Missing, expired or policy-mismatched capabilities move the affected job back to HELD/BLOCKED and record the admission failure. A blocked or locked first page cannot hide a healthy later project indefinitely.

All mutating paths lock **project → task → job**, including cancellation, membership changes, claim, heartbeat, start, result import and reconciliation. A worker claims a queued job with a new lease token and persists the immutable web task/project/generation → core UUID mapping before creating core state. PostgreSQL owns shared admission and ownership. Each attempt has a separate core SQLite ledger and checkpoint directory; workers never share a core state directory across attempts.

The supervisor prepares a fixed source and core task in a credential-free subprocess, records `RESERVED` after that subprocess exits, and persists `STARTING` before invoking the core. Role, capability expiry, policy and plan are checked again at the start boundary. Actual subprocess creation also holds the project/task/job locks and rechecks role, cancellation and the fence; the committed STARTING intent remains authoritative on failure. EXECUTING records the launch boundary and cannot be replayed. Heartbeats can extend only an unexpired current lease. Every web state, receipt, artifact and audit write checks project/task/generation/token/expiry. A late or older-generation result cannot be imported. Permission revocation after admission causes a completed result to be retained as `BLOCKED`, without a reviewable grant.

Crash behavior is deliberately conservative:

| Boundary | Restart behavior |
| --- | --- |
| Claimed, before core preparation receipt | `NEEDS_RECONCILIATION`; no automatic retry |
| Prepared and durably `RESERVED`, before `STARTING` | Reuse the same mapping and prepared core task; fence the old owner before start |
| `STARTING` or `EXECUTING`, no completed receipt | `NEEDS_RECONCILIATION`; never replay an unknown invocation |
| Completed core receipt, before PostgreSQL import | Reverify the stored candidate bytes and read-only core ledger; import with new fenced ownership, without provider execution |
| Already imported | Return the existing result; do not create artifacts or invocations again |

Lease expiry proves only loss of ownership. It never proves process termination. An unclaimed HELD/QUEUED job may be synchronously cancelled. A claimed/running job reports `CANCEL_REQUESTED` until the supervisor sees preparation exit before any invocation, or verifies the completed fixed-fixture receipt. This implementation does not forcibly terminate arbitrary processes. A completed cancelled/blocked task can be recovered through the existing API, which bumps generation, clears current artifacts/approval and creates another HELD job. Uncertain STARTING work stays blocked; there is no browser force-unlock or fabricated termination receipt.

The completed receipt is not accepted as provider testimony. The trusted verifier reads the actual bounded, regular, unlinked candidate files, reads the isolated core ledger in SQLite read-only mode, validates the fixed plan and real invocation receipt, recomputes tree/candidate digests and runs static parsers over those bytes. Secrets are rejected/redacted before database storage. Core scanner UNVERIFIED is preserved independently from the web's verified **static-only** evidence.

## Operator configuration

The API discriminates receipt types as `completed` or `never_started`; incomplete/unknown receipt shapes are not rendered as completed steps. A cancel arriving after import is confirmed only with the current generation's verified FIXTURE_STATIC_ONLY completion and no outstanding lease. Finish-before-cancel and cancel-before-finish converge to confirmed CANCELLED, allowing explicit recovery without replay. A FINISHED row lacking that proof is rejected with `termination_receipt_required`. Candidate views invalidate bytes on SSE artifact ID/digest/generation changes and discard late responses from an earlier selection.

This iteration does not deploy anything. For an already-approved private deployment, initialize the three additive supervisor/invocation tables with `python -m intelligenceai.web.manage init-db`; no existing task schema is altered. Back up the existing database and verify this migration on a disposable copy first.

The supervisor needs `IAI_RUNNER_DATABASE_URL` (existing PostgreSQL + psycopg connection) and `IAI_RUNNER_STATE_DIR` (operator-owned private state directory). Run one bounded job with `python -m intelligenceai.web.runner --once`, or reconcile a mapped core UUID with `python -m intelligenceai.web.runner --reconcile CORE_UUID`. Multiple supervisors can share PostgreSQL; attempts remain isolated. State storage must remain durable on the designated worker host so reconciliation can read the existing receipts. A different host without those bytes cannot infer success or rerun STARTING. On Windows keep the dedicated state root at most 120 characters; Git has a separate worktree path ceiling. Linux/macOS/Windows fixture portability does not prove Linux hostile-code isolation.

Provision separate existing database identities through the trusted operator, following least privilege. The web API has no execution-state filesystem mount. The supervisor reads users, members, projects and execution capabilities, locks projects with narrowly scoped UPDATE privilege, reads/updates task state and candidate/evidence fields, reads/updates job ownership fields, inserts/updates attempts, and inserts artifacts/audit. It requires no ability to change project policy, membership, users, execution capabilities, generation, request receipts or web approvals. Only trusted management can write execution capabilities; only the API records human approvals. Do not use a shared database superuser for deployment.

Subprocess environment is constructed from a small platform allowlist, private HOME/TEMP paths and fixed Git/tracing settings. Database URLs, OIDC secrets, model tokens, caller environment and browser fields are not inherited. stdout/stderr go to DEVNULL; only bounded redacted receipts persist. Each subprocess has a 90-second deadline. A timeout/failure leaves reconciliation required rather than inventing a completed cancellation. This process separation is **not an OS sandbox**.

## Reproducible validation

Additional regression coverage includes a real completion/cancel race across separate PostgreSQL pools, both deterministic completion orders, never-started receipt rendering in Korean/English, SSE candidate introduction/replacement/removal with delayed responses, and 100 invalid queued jobs ahead of a healthy project. These tests remain fixture/static evidence, not live-model success or OS sandbox certification.

Run `uv run --frozen --extra dev --extra web pytest tests/test_web.py tests/test_web_runner.py -q --durations=15`. SQLite tests use a trusted test factory and owned short state paths. The CI web job repeats the same suite against actual ephemeral PostgreSQL 17.6. PostgreSQL race tests use separate connection pools and test claim/claim, claim/cancel and claim/revocation. Lease expiry, late completion, old generation, all four crash boundaries, no-repeat receipt import and candidate-byte tampering are also covered.

`uv run --frozen --extra web python tests/support/web_fixture.py` starts a loopback-only test console and synthetic signed OIDC issuer at `http://127.0.0.1:4173`. It provisions a temporary fixture capability and runs the same supervisor against its test ledger. The test issuer/state is never included in the production container. The browser can submit, explicitly queue a fixed fixture, inspect its steps/candidate, approve a private static review and recover confirmed cancelled work. This is offline fullstack evidence, not verification of a live issuer, production PostgreSQL deployment, model or sandbox.

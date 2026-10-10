# Private API v1

The private console additionally records [paid review consent and one-time
operator-admission requests](paid-admission.md). Browser mutations record only
consent and one request. The separate [private dispatcher](paid-dispatch.md)
consumes requests with external signing and atomic holds; HTTP does not launch
provider CLIs. Authorized reads show durable worker state and distinguish
`NOTRUN`, `REQUEST_STARTED`, `RESULT_RECEIVED` and `UNKNOWN`, without descriptors,
session hashes or signatures. Result receipt is not a model correctness claim.

There is no paid-review launch route in this API. The separate operator-only
[Claude worker](claude-transport.md) uses signed server-owned descriptors and
PostgreSQL accounting. Once imported with current authority and verified
cleanup, a `review` artifact follows the existing project-authorized artifact
read path. Browser input never supplies provider credentials or commands.

All `/api` calls require the opaque server session. There are no bearer principal headers or browser-selected actors. Reads and mutations recheck membership; object identifiers do not grant access. Production requires same-origin HTTPS. Mutation requests require an exact `Origin`, JSON content type, `X-CSRF-Token` from `/api/session` and (for ledger mutations) a unique `Idempotency-Key` of at most 128 alphanumeric/`-`/`_` characters. The client preserves the key for retries of the same operation and payload.

| Route | Behavior / role |
| --- | --- |
| `GET /api/session` | Active session identity and CSRF token |
| `POST /api/logout` | `{}`; revoke session |
| `GET /api/projects` | Current identity's accessible projects |
| `GET /api/projects/{project}` | Membership and existing members |
| `PUT /api/projects/{project}/members` | Owner; existing `user_id`, role; no self change/enrollment |
| `GET /api/projects/{project}/connections` | Sanitized disabled/unverified configuration plus ten read-only provider/mode readiness rows; no paths, argv, environment or credential references |
| `POST /api/projects/{project}/preview` | Operator/owner; fixed declarative plan, no effect |
| `GET /api/projects/{project}/tasks` | Up to 100 current tasks |
| `POST /api/projects/{project}/tasks` | Operator/owner; atomically record BLOCKED task + HELD job |
| `GET /api/projects/{project}/tasks/{task}` | Task, artifact metadata and review binding |
| `POST .../{task}/cancel` | `{}`; operator/owner; confirmed unstarted or CANCEL_REQUESTED |
| `POST .../{task}/run-fixture` | `{}`; operator/owner plus operator-provisioned fixed-fixture capability; idempotent queue admission only |
| `POST .../{task}/run-approved-fixture` | `{}`; operator/owner with current server session, bound private review approval and fixed-fixture capability; reserve one synthetic vendor invocation per generation |
| `POST .../{task}/recover` | `{}`; operator/owner; unstarted only; invalidate old approval |
| `POST .../{task}/approve` | Approver/owner; exact binding; verified evidence mandatory |
| `GET .../{task}/approval-receipts/{key}` | Approver/owner; session actor's historical receipt only; read-only, never creates/replays approval |
| `POST .../{task}/reject` | `{}`; approver/owner; available review only |
| `GET .../{task}/logs` | Bounded, redacted project/task audit events |
| `GET .../{task}/events` | Finite SSE snapshot; authorization on every reconnect |
| `GET .../{task}/artifacts/{artifact}` | Private plain-text attachment; no redirects or external URLs |
| `GET /api/projects/{project}/audit` | Up to 100 project events |

Task input accepts **only** `title` (3–120 characters), `request` (3–4000), `profile` (`python-review` or `json-review`). Control characters and recognized credentials are rejected; the request is descriptive text and never becomes a shell command. Input is limited to 16 KiB, including chunked bodies. Actor, principal, tenant, environment, server paths, repository URLs, argv, provider, destination URL and livegate fields are forbidden.

Approval input accepts `candidate_digest`, `policy_digest`, `evidence_digest` (SHA256 hex), `destination_id` (`private-review`), positive `generation`, and epoch-second `expires_at`. These must match current server records and verified evidence; expiry must be in the next 15 minutes. A current private review grant permits only the explicitly requested fixed fake process described in the [approved vendor contract](web-approved-vendor.md). It never authorizes a paid model or external effect. There is no evidence write, arbitrary artifact path, force-reconciliation, publishing, merge, deploy or live dispatch API.

The console freezes an approval intent's payload, expiry and request key when the reviewer explicitly prepares it. Only "Record review approval" or the clearly labeled "Resend the same approval request" sends a POST. Receipt checks use the read-only GET with that key, return `{found: false}` when no matching actor/project/task approval receipt exists, and never create or replay a mutation. A found response includes the historical result, not a claim that its grant is currently valid. Current membership, approver/owner role and task ownership are checked on every lookup. Expiry does not prevent reading history; expired intents cannot be resent as new approvals. Preparing a new intent is an explicit action. Cancellation confirmation captures project/task/user identity and route; navigation discards it and confirmation rechecks the captured target. Logout and authority loss invalidate pending reads and mutations in the client so late responses cannot restore private data.

Errors contain only a stable `error` code, never rejected payloads, raw exceptions or SQL parameters. 401 means sign-in required, 403 means role/CSRF/origin rejection, 404 hides inaccessible objects, 409 means stale binding/idempotency conflict/reconciliation needed, 413 means oversized input, 415 means non-JSON, and 422 means invalid fields. Frontend translations map these to meaningful KO/EN messages. Database/configuration failures fail closed with 503.

The 409 message allowlist distinguishes `termination_receipt_required`, `recovery_not_available`, `verified_evidence_required`, `approval_binding_changed`, `approval_expired_or_ttl_invalid` and `idempotency_conflict`. Unknown codes use a safe translated fallback; raw codes and exception text are never rendered.

`/auth/login` and `/auth/callback` implement OIDC with fixed server-configured callback origin. No arbitrary return URL is accepted. `/healthz` reports only readiness and execution-disabled, without credentials, filesystem paths or provider identities.

Task detail now includes `runs`: `core_task_id`, `generation`, `phase` and a redacted receipt. Receipts label `FIXTURE_STATIC_ONLY`, `live_model: NOTRUN`, `os_sandbox: UNVERIFIED`, original core state and actual step/invocation records. These are synthetic candidate/static-parser results, never model success. Connection reads expose capability authorization status without credentials or state paths. Queue admission errors `fixture_execution_grant_required` and `fixture_run_not_available` have KO/EN messages. Status/receipt/log/artifact/SSE GETs have no execution mutation. The [runner contract](web-runner.md) defines crash/reconciliation behavior; there is no browser force-reconcile route.

Task detail additionally returns `vendor_runs` with invocation ID, generation, state and a bounded redacted synthetic receipt. Its private `vendor-result` artifact uses the existing authorized plain-text download. Session hashes, lease tokens and executable paths are never returned. Same-key retries return the original reservation; a different key for the same task/generation returns 409. See [approved synthetic execution](web-approved-vendor.md).

## Local CLI review

`GET /api/projects/{project}/tasks/{task}/local-cli` returns only the current actor's registered profile metadata, saved quota snapshots and requests after project authorization. `POST .../local-cli/prepare` accepts only `{profile_id}`. `POST .../local-cli/approve` accepts only `{request_id,binding_digest}`. Both require session-derived actor, project owner role, CSRF/Origin and Idempotency-Key. The latter atomically queues one request. Payload identity/size, provider/runtime, candidate/evidence/policy/destination/generation/session and expiry are bound and rechecked before native stdin release and private import. Status reads/reconnects never trigger quota or model calls. CLI quota refresh is a manual local operator command.

# Private API v1

All `/api` calls require the opaque server session. There are no bearer principal headers or browser-selected actors. Reads and mutations recheck membership; object identifiers do not grant access. Production requires same-origin HTTPS. Mutation requests require an exact `Origin`, JSON content type, `X-CSRF-Token` from `/api/session` and (for ledger mutations) a unique `Idempotency-Key` of at most 128 alphanumeric/`-`/`_` characters. The client preserves the key for retries of the same operation and payload.

| Route | Behavior / role |
| --- | --- |
| `GET /api/session` | Active session identity and CSRF token |
| `POST /api/logout` | `{}`; revoke session |
| `GET /api/projects` | Current identity's accessible projects |
| `GET /api/projects/{project}` | Membership and existing members |
| `PUT /api/projects/{project}/members` | Owner; existing `user_id`, role; no self change/enrollment |
| `GET /api/projects/{project}/connections` | Sanitized disabled/unverified configuration |
| `POST /api/projects/{project}/preview` | Operator/owner; fixed declarative plan, no effect |
| `GET /api/projects/{project}/tasks` | Up to 100 current tasks |
| `POST /api/projects/{project}/tasks` | Operator/owner; atomically record BLOCKED task + HELD job |
| `GET /api/projects/{project}/tasks/{task}` | Task, artifact metadata and review binding |
| `POST .../{task}/cancel` | `{}`; operator/owner; confirmed unstarted or CANCEL_REQUESTED |
| `POST .../{task}/recover` | `{}`; operator/owner; unstarted only; invalidate old approval |
| `POST .../{task}/approve` | Approver/owner; exact binding; verified evidence mandatory |
| `GET .../{task}/approval-receipts/{key}` | Approver/owner; session actor's historical receipt only; read-only, never creates/replays approval |
| `POST .../{task}/reject` | `{}`; approver/owner; available review only |
| `GET .../{task}/logs` | Bounded, redacted project/task audit events |
| `GET .../{task}/events` | Finite SSE snapshot; authorization on every reconnect |
| `GET .../{task}/artifacts/{artifact}` | Private plain-text attachment; no redirects or external URLs |
| `GET /api/projects/{project}/audit` | Up to 100 project events |

Task input accepts **only** `title` (3–120 characters), `request` (3–4000), `profile` (`python-review` or `json-review`). Control characters and recognized credentials are rejected; the request is descriptive text and never becomes a shell command. Input is limited to 16 KiB, including chunked bodies. Actor, principal, tenant, environment, server paths, repository URLs, argv, provider, destination URL and livegate fields are forbidden.

Approval input accepts `candidate_digest`, `policy_digest`, `evidence_digest` (SHA256 hex), `destination_id` (`private-review`), positive `generation`, and epoch-second `expires_at`. These must match current server records and verified evidence; expiry must be in the next 15 minutes. A recorded review grant never permits actual dispatch in this release. There is no evidence write, arbitrary artifact path, force-reconciliation, publishing, merge, deploy or dispatch API.

The console freezes an approval intent's payload, expiry and request key when the reviewer explicitly prepares it. Only "Record review approval" or the clearly labeled "Resend the same approval request" sends a POST. Receipt checks use the read-only GET with that key, return `{found: false}` when no matching actor/project/task approval receipt exists, and never create or replay a mutation. A found response includes the historical result, not a claim that its grant is currently valid. Current membership, approver/owner role and task ownership are checked on every lookup. Expiry does not prevent reading history; expired intents cannot be resent as new approvals. Preparing a new intent is an explicit action. Cancellation confirmation captures project/task/user identity and route; navigation discards it and confirmation rechecks the captured target. Logout and authority loss invalidate pending reads and mutations in the client so late responses cannot restore private data.

Errors contain only a stable `error` code, never rejected payloads, raw exceptions or SQL parameters. 401 means sign-in required, 403 means role/CSRF/origin rejection, 404 hides inaccessible objects, 409 means stale binding/idempotency conflict/reconciliation needed, 413 means oversized input, 415 means non-JSON, and 422 means invalid fields. Frontend translations map these to meaningful KO/EN messages. Database/configuration failures fail closed with 503.

The 409 message allowlist distinguishes `termination_receipt_required`, `recovery_not_available`, `verified_evidence_required`, `approval_binding_changed`, `approval_expired_or_ttl_invalid` and `idempotency_conflict`. Unknown codes use a safe translated fallback; raw codes and exception text are never rendered.

`/auth/login` and `/auth/callback` implement OIDC with fixed server-configured callback origin. No arbitrary return URL is accepted. `/healthz` reports only readiness and execution-disabled, without credentials, filesystem paths or provider identities.

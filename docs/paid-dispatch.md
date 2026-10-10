# Private paid-review dispatch

The owner still explicitly prepares, approves and requests one fixed quote.
`PaidDispatcher.prepare(request_id, runtime, facts)` now connects that durable
request to the existing operator-only Claude worker. This function is private
server code; no browser dispatch, signer, runtime or credential route was added.
No actual paid provider was called to validate this change.

The dispatcher requires an injected `ReceiptIssuer.issue(ControlStatement)`
interface and an independently configured `ReceiptVerifier` public-key/control
map. It does not implement a signing service or generate/load private keys. Five
operator `ControlFact` evidence references with valid time windows are required;
the paid authorization statement derives its evidence digest from the exact
stored quote. The existing six signatures remain bound to manifest, approval,
evidence and expiry. Every issued statement must exactly match the requested
statement. File existence, a successful test or a profile digest is never used
to invent operational capability/egress/resource/credential evidence.

An independent `DispatchRuntime` supplies the pinned runner, workspace and
egress bindings. Profile/model/effort/pricing/budget and principal come only from
the current server-owned request and operator profile. Signing happens outside
DB locks. After signing, the dispatcher repeats current owner/session, project,
task, snapshot, generation, cancellation, lease, profile, budget and exact quote
checks. It atomically changes `REQUESTED` to `DISPATCHED`, reserves the existing
paid ledger hold and inserts a private `web_paid_dispatches` descriptor. Any
failure rolls all three changes back. Invocation ID equals the unique request ID.

After a committed delivery, retries/restarts return its existing invocation and
paid ledger state without re-signing or holding funds again. A reserved delivery
can be supplied to `python -m intelligenceai.web.claude_worker --request-id <id>`
using the worker's existing required backend/cgroup/runtime/public-trust-key
arguments and an independently supplied credential fd. This optional selector
replaces `--descriptor`; it does not grant authority or provision credentials.
Both CLI paths call the same runner function. The worker verifies signatures
again and atomically claims the matching reservation before any local process.
Concurrent/stale copies cannot pass that durable claim.

Launch, gate, HTTP admission and result import recheck current authority. For
dispatches this includes the active unchanged profile, original quote digest,
current owner and unrevoked consumed request. Cancellation revokes dispatches
through the existing task API. A proven unsent reservation is released once;
`LAUNCHING` cancellation waits for cleanup confirmation. Started or unknown
results retain holds and cannot replay automatically. A fresh attempt needs
recovery to a new generation and fresh consent. Neither lease expiry nor a
missing worker response proves cancellation.

The authorized paid-status GET adds `worker_state`. `live_model` is `NOTRUN` for
unstarted/proven-unsent records, `REQUEST_STARTED` after durable HTTP admission,
`RESULT_RECEIVED` after settlement/import, and `UNKNOWN` for ambiguous launch or
reconciliation states. A received result does not prove model correctness or
production compatibility. No descriptor, signature, session hash or private
filesystem path appears in public responses. The GUI cannot launch/replay a
worker and keeps `execution_enabled: false` for its browser actions.

Migration is additive: back up the DB, review the schema and use the existing
`web.manage init-db` procedure for `web_paid_dispatches`. Protect its rows and
backups like private artifacts; they contain session bindings and signed grants.
All operator provisioning/revocation must follow the shared project lock, while
logout uses the session lock. No signing/credential env var or default signer was
added. Missing external signer/control evidence/configuration fails closed.

Tests use ephemeral test-only Ed25519 keys, synthetic profiles/budgets/users,
mock process/cgroup seams and `httpx.MockTransport`; default provider HTTP is
blocked in these tests. They cover atomic rollback, duplicate delivery and lost
responses, restart before claim, crash after claim, cancel/role/session/profile
revocation, gate-to-HTTP revocation, unknown-result holds, and no replay/recharge.
CI also checks competing dispatchers against real ephemeral PostgreSQL. These
tests do not verify actual paid models, operational signing/credential systems,
production cgroups or supported-browser/mobile behavior.

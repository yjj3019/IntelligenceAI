# Claude review transport

[한국어 검토 보완 기록](claude-review-fixes.ko.md)

The separate `intelligenceai.web.claude_worker` executes one tool-free, read-only
review of an existing immutable candidate. It implements a production transport;
tests use an explicitly fake provider and CLI. Deployment and real paid model
execution have not been verified or enabled by the GUI work.

## Request and authorization

The operator supplies a pinned `ClaudeProfile`, a `LaunchManifest` with backend
`linux-bwrap-claude-relay-v1`, a `PaidReviewIntent`, the existing server-session
hash, and six signed control receipts. Model and effort have no guessed defaults.
The supported CLI contract is pinned to `2.1.296`. Codex, Grok and Gemini remain
outside this implementation; the existing offline backend still rejects live
provider execution.

The manifest overlay digest binds profile digest, prompt digest, approved budget
and approver ID. The paid approval binds candidate, policy, evidence, destination,
generation, actor and expiry. Its destination must be `private-model-review`.
The manifest invocation ID must equal the durable invocation ID. Its caller
context digest binds actor ID, project ID and the exact server-session hash.
A private review or candidate application approval cannot authorize a paid call.
The separate paid signer grants that scope explicitly. The server derives the
prompt from private candidate artifact bytes; a browser cannot select a command,
credential, path, environment, model fallback or arbitrary provider URL.

The worker verifies receipts before reservation, before launching and again
before the broker's request. The ledger checks current active requester and
approver membership, server session, task generation, cancellation, candidate
and evidence bytes, policy, budget expiry and the durable consumption fence.
Reservation and launch intent are committed before side effects. PostgreSQL
locks the project to serialize budgets across competing tasks. Each task
generation reserves once, launches once and admits one upstream request.
After image hashing and cgroup preparation, a short transaction locks current
project, review, task, job and session authority through process creation and
the exec gate. It rechecks expiry and cancellation after attachment. Gate
permission is the local launch admission point; physical CLI creation happens
later. Supported membership/cancellation APIs use the same project lock, and
logout must wait on the session lock. Provisioning SQL must follow those locks.
No database lock is held through provider HTTP, process polling or relay drain.

## Transport and isolation

The CLI runs in a bubblewrap network, PID, user and mount namespace with all
capabilities dropped. It sees an immutable image and invocation-local scratch
directories; no repository, host HOME, credential store or project hooks are
mounted. `--bare`, empty built-in tools, all disallowed tools, strict empty MCP,
disabled slash commands/hooks and no session persistence reduce CLI behavior.
No permission-bypass flag is used. CLI flags alone are not OS isolation evidence.

The stdlib HTTP bridge listens only on namespace loopback. It forwards through
a private Unix socket mounted at `/relay/broker.sock`. The CLI receives only an
ephemeral relay capability. The broker keeps the API key in its own memory,
replaces all client headers and connects exclusively to
`https://api.anthropic.com/v1/messages` with certificate verification, no proxy
environment, no redirect following and no transport retries. Provider OAuth,
subscription tokens, Bedrock and other credential modes are not implemented.
The worker accepts an already supplied operator credential file descriptor;
it does not discover or create credentials. No actual secret was supplied in
these tests. Python strings do not provide a secure memory-erasure guarantee.
The bridge accepts exactly `/v1/messages` or the native
`/v1/messages?beta=true`; other paths, queries and absolute targets are denied.
The pinned CLI environment sets `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`
and `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1` to remove paired pre-release
fields, including context management. It does not assume that thinking can be
disabled on every model. Context-management requests remain rejected before
HTTP. This single tool-free request does not preserve multi-turn thinking.

The bridge and CLI are inside an already delegated cgroup v2 leaf. The runner
applies and reads back memory, swap, process and CPU limits, then attaches the
trusted waiting launcher before permitting its exec. It never enables global
controllers or changes security settings. Missing delegation is a blocker.
After exit, deadline, output overflow or cancellation it uses `cgroup.kill` and
requires `cgroup.events` to report `populated=0` before importing a result.
Killing local processes does not prove remote model cancellation.

## Accounting and reconciliation

Before launch, the project budget holds the model's complete supported input
context ceiling times the operator-attested upper input price, plus bounded
output tokens times the upper output price. Prices are microusd per token,
rounded upward and must cover every applicable premium. A signed pricing
evidence digest is required. There is no bundled current model/pricing guess.
An incorrect operator model-ceiling or pricing attestation invalidates the
financial safety bound; it must be independently verified before operation.

The broker accepts text-only input messages, pins model and effort, caps max tokens,
removes caching requests and denies tools, media, external content and unknown
request fields. Adaptive/disabled thinking and bounded manual thinking are
validated. Thinking uses the same output token ceiling and price ceiling.
It bounds request/response bytes and deadlines. A complete text/thinking SSE
stream, terminal `end_turn`, `message_stop` and recognized cumulative usage
are required to settle. Multiple `message_delta` events update the cumulative
count rather than adding charges. Thinking signatures and redacted blocks
are relayed without storing reasoning in the private review or audit.
Unexpected billing fields, fallback model, malformed thinking,
tools, stream errors, missing usage, redirect, timeout or transport ambiguity
retain the entire hold and mark `NEEDS_RECONCILIATION`. They never auto-replay.
The booked charge is a conservative upper bound from observed token usage,
not a provider invoice or a claim of an exact billed amount.

Financial settlement remains possible after logout or cancellation so observed
upstream costs are accounted for. Result import separately checks current
authority and cgroup cleanup and applies secret redaction before storing the
private review artifact. The broker drains an in-flight response even when the
local CLI disconnects. A crash before a confirmed response holds funds;
operator reconciliation requires external billing evidence. This release has
no automatic release/refund or retry of ambiguous invocations.
An unclaimed reservation cancelled without a lease, or a `LAUNCHING` invocation
with verified local cleanup and no committed HTTP admission, releases its hold
atomically once and records `TERMINATED`. A possibly sent request never refunds
on local cleanup alone. A fresh attempt requires task recovery to a new
generation and new approval; the consumed approval cannot reserve again.

## Deployment inputs and evidence

Initialize the additive paid accounting tables with the existing `web.manage
init-db` migration procedure after backup/review. The operator must separately
provide a bounded project budget, private signed descriptor and existing
authorized API-key fd, immutable Linux image with `/claude`, `/python`,
`/bridge.py` and Python stdlib under `/usr`, pinned bubblewrap, PostgreSQL and
an already delegated cgroup subtree. The worker uses only `IAI_DATABASE_URL`;
credential values do not belong in `.env`, JSON descriptors or browser input.

`python -m intelligenceai.web.claude_worker --help` describes the entrypoint.
Run it as a dedicated trusted service with its own restricted UID and private
runtime root. Do not expose this CLI as a public HTTP launcher. The HTTP API
does not currently enqueue paid reviews or offer a paid-enable toggle; UI
admission, operational approval issuance, budget provisioning and deployment
remain separate work. This implemented worker is callable once those existing
operator inputs and explicit paid approval are supplied.

Tests exercise durable reservation, revocation, prompt drift, duplicate calls,
malformed streams, bounded accounting, private result import and real PostgreSQL
competition. Linux CI additionally runs an actual namespace and Unix relay with
a CLI-shaped fake. The optional actual cgroup test runs only with an existing
`IAI_TEST_DELEGATED_CGROUP`; absent delegation is explicitly skipped/unverified.
No test outcome proves vendor/model compatibility, production OIDC/PostgreSQL,
HTTPS deployment, paid authorization or cgroup enforcement on another host.

Contract sources: [Claude CLI reference](https://code.claude.com/docs/en/cli-reference),
[gateway contract](https://code.claude.com/docs/en/llm-gateway),
[gateway protocol](https://code.claude.com/docs/en/llm-gateway-protocol),
[thinking accounting](https://platform.claude.com/docs/en/build-with-claude/thinking),
[Messages streaming](https://platform.claude.com/docs/en/build-with-claude/streaming),
[bubblewrap](https://github.com/containers/bubblewrap),
[cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).

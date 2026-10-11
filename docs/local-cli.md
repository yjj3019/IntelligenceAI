# Own local CLI execution

The private console has a local CLI review path alongside the optional API broker.
Each user uses their own installed CLI and existing native login. The service does
not manage plans, billing, API prices or subscription changes. Installation, native
login status and a user-requested model result are separate observations. No
background availability ping or model retry is added.

## Request and execution

1. The local operator registers an existing executable against one verified web
   owner and project. HTTP inputs cannot supply paths, environment, commands or actors.
2. The owner prepares a review of a frozen candidate and evidence. The API stores
   provider/runtime identity, candidate/evidence/policy/destination/generation,
   session, payload digest, five-minute expiry and fixed execution bounds.
3. Explicit approval atomically queues one durable request. A separate local worker
   claims it, rechecks authority immediately before stdin release and before import,
   and stores the result as a private project text artifact.

The bounds are one CLI invocation, 60 seconds and one active worker per owner.
Native internal requests are unknown. A consumed attempt cannot be automatically
replayed after interruption, parsing failure, lost acknowledgement or timeout.
Unknown termination/result requires receipt review; recovery never clears it away.
An expired unstarted intent can be explicitly cancelled and recovered into a new
generation; its old approval is never reused.
Queued cancellation proves never started. Running cancellation first records
`CANCEL_REQUESTED`; local process termination does not prove remote cancellation.

Claude 2.1.296 uses normal safe/restricted mode, empty tools and strict empty MCP,
hooks disabled for the invocation, no persisted session and one maximum turn.
Managed policy remains effective. Codex 0.162.1 uses normal read-only sandbox,
approval `never`, ephemeral execution, ignored user config/rules and per-invocation
shell/app/plugin/hook/browser/subagent feature restrictions. It creates an empty
owned Git directory using no templates. No privilege bypass or model/effort override
is used. Grok 1.0.50 remains unavailable for execution because its builtin tool
filter does not establish invocation-only exclusion of native/plugin MCP and hooks.
Its subscription is not evaluated by this application.

Worker credentials stay in the native user's normal login storage. The application
does not read, copy, migrate or transmit credential files. The child inherits only
standard OS/home/location/locale environment names; API keys, endpoint overrides,
helper variables and database credentials are excluded without reading their values.
Windows assigns a stdin-gated launcher to a kill-on-close Job before native launch.
POSIX uses an owned process group. These are process cleanup controls, not claims
of hostile-code OS containment. The API never executes repository code or a CLI.

## Payload and usage

The deterministic prompt sends request, candidate contents and frozen evidence
once. Identical candidate contents are grouped with every source name preserved.
No GUI state, execution UUID/time, prior answers, session history or logs are appended.
Compact sorted JSON uses actual UTF-8, including Korean, rather than `\uXXXX` text.
Global canonical signing/digest serialization is unchanged. Exact prompt SHA256,
bytes/chars, file/content counts and format are bound before approval; changed
payload/format cannot reuse old approval. Inputs over 8,000 UTF-8 bytes are rejected
before enqueue, never silently truncated. Output is bounded to 65,536 bytes per
stream. Payload size is not a token count; actual token savings are unmeasured.

Native result token fields retain provider meanings and missing values remain
unknown. Codex cached input is a subset reported separately, never added again to
input tokens. Grok headless input is uncached, cache buckets stay separate and
`usage_is_incomplete` remains visible. Cost fields are not imported as bills.
Codex diagnostic items are distinguished from tool items. A completed turn with
diagnostics is `PARTIAL_FAILURE`; `turn.failed` is `REQUEST_FAILED`; incomplete or
malformed output is unverified. Diagnostics never import an answer as success or
mark the installed CLI permanently unavailable. Only safe event counts/terminal
flags are stored; raw diagnostic messages and native JSONL are not persisted.

Manual local Codex quota refresh uses official app-server `initialize`, `initialized`
and `account/rateLimits/read`; no `thread/start`, `turn/start` or model call is sent.
Snapshots preserve source, measurement time, limit ID, window duration in minutes,
used percentage and reset epoch. A 10,080-minute window is seven days. Account
windows and per-run tokens are shown separately. Claude/Grok independent headless
quota JSON is not verified; display `NOT_PROVIDED`. GUI refresh reads saved data only.

## Operator deployment

Keep the existing supported OIDC/server session and private PostgreSQL deployment.
Do not ship a public write demo or share one machine's CLI login across web users.
This initial worker requires private operator-provisioned ledger access on that
user's machine. The separate [outbound PC client](pc-connection.md) implements
owner-approved hosted enrollment without DB/OIDC secrets; use that route for a
user PC connected to a private web console.
The public synthetic demo does not register profiles or launch this worker.

Apply additive tables with `python -m intelligenceai.web.manage init-db` using the
existing operator environment, then register locally (values are existing IDs/paths):

```text
python -m intelligenceai.web.cli_worker register --project PROJECT_UUID --actor OWNER_UUID --provider claude --executable LOCAL_CLI --version 2.1.296 --root OWNED_WORKER_DIRECTORY
python -m intelligenceai.web.cli_worker serve --profile PROFILE_UUID --provider claude --executable LOCAL_CLI --version 2.1.296 --root OWNED_WORKER_DIRECTORY
python -m intelligenceai.web.cli_worker quota --profile PROFILE_UUID --provider codex --executable LOCAL_CLI --version 0.162.1 --root OWNED_WORKER_DIRECTORY
```

`once` consumes at most one already-approved request; `serve` polls only approved
jobs. `quota` is manual and does not start a model. No new account, OAuth login,
tunnel, public port, cloud resource or billing/security setting is provisioned.
Production database/OIDC enrollment and public deployment require the separately
provided supported target. Local fixture tests are not production deployment evidence.

## Primary contracts

The launch authority transaction remains open through the actual stdin gate
handoff, with a final expiry/lease/session/role recheck. Owner serialization uses
PostgreSQL `FOR NO KEY UPDATE`, compatible with audit/receipt user foreign-key
checks. Quota work takes no database locks while waiting for the native status;
publication locks project before profile and checks current identity/authority.
Expired or revoked requests still in `QUEUED` are recorded as `NEVER_STARTED` with
zero invocations; the worker can then process later valid requests. Consumed
`STARTING`/`RUNNING`/`UNKNOWN` attempts continue to block automatic replay.

CLI result artifacts are displayed separately from candidate artifacts and their
text is fetched through the authorized artifact endpoint. Native internal model
calls remain unknown after a native launch; they are not inferred from one CLI
invocation. Confirmed results prove one CLI invocation, uncertain launches remain
unknown, and only confirmed unstarted requests claim zero/`NOTRUN`.

Codex JSONL for this version omits agent-message phase. With one completed turn,
no diagnostics/tools and exit zero, the last agent message is selected. An empty
last message cannot fall back to commentary. This follows the pinned
[official final-message contract](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/exec/src/event_processor_with_jsonl_output.rs#L387-L400).
Private metadata records only terminal flags, safe counts, exit/termination,
availability and native usage; it does not preserve raw messages, event order or
account output. Existing lost smoke output cannot be reconstructed from it.

- [Claude CLI reference](https://code.claude.com/docs/en/cli-reference),
  [hooks](https://code.claude.com/docs/en/hooks),
  [headless](https://code.claude.com/docs/en/headless).
- [Codex noninteractive execution](https://developers.openai.com/codex/noninteractive/),
  [official app-server](https://developers.openai.com/codex/app-server),
  [official tool registration source](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/spec_plan.rs).
- [Grok headless output at source 2bdd1d6](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-pager/docs/user-guide/14-headless-mode.md),
  [MCP restrictions](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-pager/docs/user-guide/07-mcp-servers.md).
  The public source SHA is not asserted to match installed binary c58f321264ba.

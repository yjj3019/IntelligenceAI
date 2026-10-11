# IntelligenceAI

[Owner-approved PC connection](docs/pc-connection.md) links a scoped local client
to the private console over outbound HTTPS without DB/OIDC secrets. This feature
has synthetic verification; real enrollment and production activation remain pending.

The private console now offers [your own local CLI review](docs/local-cli.md) as the primary review path. Installation, native login status and user-requested execution results are separate. Approved jobs run in a separate owner-bound local worker; subscription/billing stays with the AI service. Account windows and per-run tokens are shown separately. Existing API review remains an advanced option.

The private console records [bounded paid-review consent and one-time
operator requests](docs/paid-admission.md). A [private dispatcher](docs/paid-dispatch.md)
now connects approved requests, external receipt issuance, atomic budget holds
and the existing worker. Browser actions supply no credentials or launch flags.

The separate [Claude review worker](docs/claude-transport.md) implements an actual
HTTP broker, PostgreSQL budget reservation, namespace relay and cgroup cleanup.
Tests use fake providers. Actual paid execution, operational signer/credential
configuration and production deployment remain unverified and disabled.

The private console supports [one-time approved synthetic execution](docs/web-approved-vendor.md), with current session/approval rechecks, private results and conservative cancellation/recovery. This fixed fake process uses zero model calls; live providers and OS isolation remain unverified.

[Provider isolation contracts and an offline Linux probe](docs/provider-isolation.md) now separate manifest preparation, OS evidence and live authorization. The connections view shows per-provider/mode blockers. Paid models remain disabled; offline probe evidence cannot authorize or attest a live model.

[Live authority receipt contracts](docs/live-authority.md) verify six role-specific signatures bound to an approval and exact manifest. The verifier returns signature evidence only. The separate Claude worker additionally implements broker/namespace/resource/accounting checks; its actual paid operation still requires independently verified deployment inputs and explicit approval.

[한국어](README.md) · [Architecture](docs/architecture.md) · [Security](SECURITY.md) · [Design coverage](docs/requirements.md)

IntelligenceAI is an early local task controller. LangGraph persists workflow position while an independent SQLite ledger owns effect accounting. Git workspaces, candidate fingerprints and exact approval gates connect the workflow. The executable paths are declarative static DAGs and trusted deterministic fixture writers. Claude, Codex, Grok, Gemini CLI, Antigravity, Omnilane, MCO and PAL live integrations remain disabled until execution and OS permission contracts are verified.

This is a foundation, not a finished general AI assistant. It does not authenticate tools, call paid models, publish, merge or deploy. Meta AI is excluded.

## Web GUI

The web app provides public introduction/docs, a synthetic read-only demo, and a private project console with eight views: dashboard, projects/members, new task/plan preview, task/steps, candidate/checks, approval/recovery, connections/environments, and audit. KO/EN switching saves only the language preference; dates and numbers use Intl and the browser timezone.

The private API uses a separate PostgreSQL ledger and opaque OIDC server sessions with project authorization. Submissions enter a durable HELD queue. A separate [fixed-fixture supervisor](docs/web-runner.md) can execute the real core typed DAG after an operator provisions an expiring project capability and a user explicitly queues the task. Its candidates are synthetic and evidence is static-only. Real models and external effects remain disabled; OS containment is unverified. It does not expose the local CLI SQLite database, file locks or in-memory queue over HTTP. The public demo has no private data, login or writes.

The completed GUI scope is fixed-fixture submission, durable queuing, core DAG execution, static results, private review approval, cancellation and recovery. Arbitrary repository code, shell and vendor CLI execution are unavailable. Production authentication/DB/TLS validation and current supervisor UI browser QA remain incomplete; this scope does not constitute a finished AI product. See the [validation record](docs/web-validation.md) for evidence and NOTRUN items.

Read [architecture](docs/web-architecture.md), [API](docs/web-api.md), [security](docs/web-security.md), [deployment](docs/web-deployment.md) and [validation](docs/web-validation.md). Build with the optional web dependencies, then `npm ci --ignore-scripts`, `npm run build` and `npm run build:public` under `web/`. Run `uv run --frozen --extra web python scripts/pack_public_demo.py` from the repository root to create the self-contained `deliverables/public-demo.html`.

The [public introduction and KO/EN synthetic demo](https://intelligenceai.violet-pixie-4145.chatgpt.site) is deployed on Sites. It contains only static HTML, synthetic data and disabled mutations; no login, private API, database or runner is connected. [Deployment identity and source provenance](deploy/public-site.json) are retained for updates. A real private rollout still needs an approved Linux destination, existing PostgreSQL and OIDC registration, and HTTPS ingress. Container recipes are prepared but not runtime-verified.

## Install and run

A restricted [local stdio MCP service](docs/mcp.md) uses the same controller and official pinned Python SDK 1.26.0. It exposes capabilities/preview/submit/status/results/cancel only. Operator repository grants and durable admission keys restrict requests; approval and external actions are absent from model tools. No HTTP port or application registration is needed.

The controller now executes typed DAGs with durable per-step receipts, explicit result references, serialized fixture writers and parallel static reviewers over one frozen candidate. File existence, JSON shape and Python AST profiles inspect real bytes without executing project code. See [DAG guide](docs/dag.md) and the owned Python/JSON sample plans under `examples`. Test/build commands remain disabled.

Version-scoped argv/stdin preparation, separate provider result parsers and offline lifecycle regressions are implemented in `protocols.py`. See [protocol contracts](docs/protocols.md). Production dispatch is unconditionally disabled; public inputs cannot select fake transports or enable the live gate.

Use Python 3.11+, Git, and an already installed uv. Dependencies and hashes are fixed in `uv.lock`; sources and licenses are in [dependencies](docs/dependencies.md).

```sh
uv sync --frozen --extra dev
uv run --frozen intelligenceai capabilities
uv run --frozen intelligenceai --state-dir ../iai-state preview
uv run --frozen intelligenceai --state-dir ../iai-state submit --repo /path/to/fixture-repo --request "Check workflow" --scenario repair --run
uv run --frozen intelligenceai --state-dir ../iai-state status TASK_ID
uv run --frozen intelligenceai --state-dir ../iai-state results TASK_ID
```

Use a disposable Git repository with at least one commit and keep state outside it. The controller makes a detached worktree from committed HEAD; it preserves original uncommitted changes. The default profile writes fixed `answer.py` bytes; the registered JSON profile writes fixed `settings.json` bytes. `success` writes 42, `repair` repairs 41 to 42, and `exhaust` tests the repair budget. The assertion parses an AST without executing target code. Fixture reviews are deterministic checks, not independent model reviews.

Without verified Gitleaks 8.30.1 and Linux/macOS supervision the result is `UNVERIFIED`, even when assertions pass. Test scanner stubs are not live scanner evidence. Native Windows process supervision is disabled.

## Approval and recovery

```sh
uv run --frozen intelligenceai --state-dir ../iai-state approve TASK_ID --action push --destination example.invalid/repo --ttl 900
uv run --frozen intelligenceai --state-dir ../iai-state dry-run TASK_ID --action push --destination example.invalid/repo
uv run --frozen intelligenceai --state-dir ../iai-state reject TASK_ID
uv run --frozen intelligenceai --state-dir ../iai-state cancel TASK_ID
uv run --frozen intelligenceai --state-dir ../iai-state recover TASK_ID
```

Approval requires mandatory evidence and binds repo/base, candidate bytes including untracked/ignored files, scope, action/argv/destination, policy, generation and proof. Mutation, expiry or rejection blocks the gate. External actions are always disabled; approved dry runs report zero external actions.

Recovery reconciles the ledger before the persisted graph. Reserved calls may proceed; uncertain starts become `NEEDS_RECONCILIATION` and retain writer ownership. Do not delete state or clear writer ownership to force retry. No force-reconciliation command is provided until actual operation receipts and termination can be verified.

The local single-user CLI is the approval channel. Workers have no approval API. Worktrees are not OS sandboxes, and application checks do not protect against malicious processes with the controller user's OS privileges. Read [security limits](SECURITY.md).

## Validate

```sh
uv run --frozen pytest -q
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
```

CI checks CLI/DAG, contracts, approval, recovery, actual stdio SDK, ordinary Linux/macOS process groups, secret scans and installed wheel entry points. Vendor E2E, API connectivity, Windows/WSL isolation and cost/performance remain `UNVERIFIED`. No external exactly-once or measured quality improvement is claimed. The web GUI uses a separate private ledger and deployment boundary. See the [macOS guide](docs/macos.md) for separate Apple Silicon/Intel CI and support boundaries.


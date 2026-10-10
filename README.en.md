# IntelligenceAI

[한국어](README.md) · [Architecture](docs/architecture.md) · [Security](SECURITY.md) · [Design coverage](docs/requirements.md)

IntelligenceAI is an early local task controller. LangGraph persists workflow position while an independent SQLite ledger owns effect accounting. Git workspaces, candidate fingerprints and exact approval gates connect the workflow. The current executable path is a deterministic fixture. Claude, Codex, Grok, Gemini CLI, Antigravity, Omnilane, MCO and PAL live integrations remain disabled until execution and OS permission contracts are verified.

This is a foundation, not a finished general AI assistant. It does not authenticate tools, call paid models, publish, merge or deploy. Meta AI is excluded.

## Install and run

Use Python 3.11+, Git, and an already installed uv. Dependencies and hashes are fixed in `uv.lock`; sources and licenses are in [dependencies](docs/dependencies.md).

```sh
uv sync --frozen --extra dev
uv run --frozen intelligenceai capabilities
uv run --frozen intelligenceai --state-dir ../iai-state preview
uv run --frozen intelligenceai --state-dir ../iai-state submit --repo /path/to/fixture-repo --request "Check workflow" --scenario repair --run
uv run --frozen intelligenceai --state-dir ../iai-state status TASK_ID
uv run --frozen intelligenceai --state-dir ../iai-state results TASK_ID
```

Use a disposable Git repository with at least one commit and keep state outside it. The controller makes a detached worktree from committed HEAD; it preserves original uncommitted changes. It writes only fixed `answer.py` bytes. `success` writes 42, `repair` repairs 41 to 42, and `exhaust` tests the repair budget. The assertion parses an AST without executing target code. Fixture reviews are deterministic checks, not independent model reviews.

Without verified Gitleaks 8.30.1 and Linux supervision the result is `UNVERIFIED`, even when assertions pass. Test scanner stubs are not live scanner evidence. Native Windows process supervision is disabled.

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

CI runs fixture, contract, approval, crash and Linux process tree tests. Vendor E2E, API connectivity, Windows/WSL isolation and cost/performance remain `UNVERIFIED`. No external exactly-once or measured quality improvement is claimed. MCP and UI are deferred.


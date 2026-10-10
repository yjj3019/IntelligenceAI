# Provider isolation: first increment

[한국어 안내](provider-isolation.ko.md)

Live provider execution remains blocked. The new executor runs a fixed unpaid
Linux namespace probe, separately from the fixed-fixture supervisor. A passing
probe is evidence about that offline OS policy, never provider authentication,
model identity, billing enforcement or permission to run a paid model.

## Trusted launch contract

`LaunchManifest` binds invocation/task/project/actor, generation, provider,
model/effort/mode, OS/backend, backend/vendor/runner/policy hashes, image and
workspace tree hashes, explicit writable files, separate provider-host and
generated-tool network policy, credential references, caller/overlay hashes,
deadline and invocation/cost budget. It rejects unknown JSON fields, fallback,
non-finite deadlines, implicit write scope and credential/network-enabled probes.
Credential references contain UUIDs, never credential values. The actor must come
from the server session; no HTTP endpoint accepts this internal manifest.

Capability evidence is only a reference. Matching hashes and expiry do not
authenticate its provenance. Offline and live scopes cannot be interchanged.
No evidence object, fixture grant, environment variable or successful process
exit can activate `LiveGateway`. No live executor is implemented in this increment.

## Offline namespace backend

`LinuxOfflineExecutor` accepts an operator-owned absolute bubblewrap executable
and immutable minimal image. It checks pinned file bytes and tree permissions;
rejects symlinks, hardlinks, special/setuid/setgid files, overlapping roots and
project hooks/MCP/credential configuration. Its only command is `/probe`, a pinned
static test binary. It does not accept shell strings, arbitrary argv or vendor CLI
commands. It mounts only the read-only image and workspace, explicitly scoped
writable files, private `/home` and `/tmp`, namespace-local `/proc` and `/dev`.
It unshares user/PID/network/IPC/UTS namespaces, drops capabilities, clears the
environment, and requests parent-death/session isolation. No host root, HOME,
ledger, credential directory, Docker socket or network proxy is mounted.

Timeout and cancellation target only the owned process group. A successful
`wait()` does not prove descendant cleanup: the result stays `UNVERIFIED` or
`BLOCKED` and explicitly reports cleanup `UNVERIFIED`. The independent test must
observe a real `setsid()` descendant heartbeat stop. Bounded output is redacted
before being returned; no raw provider log or credential is persisted.

The operator must keep materialized trees immutable across hashing and launch.
This prototype does not solve hostile concurrent host mutation or enforce
cgroup memory/CPU/disk quotas. Its network namespace denies provider access too.
A future live backend still needs independently verified credential brokering,
provider-only egress distinct from generated tools, resource/billing enforcement,
transport/caller provenance and exact OS × provider × mode evidence. CLI sandbox
flags and fixture process supervision cannot substitute for those controls.

## Upstream retry contract

Omnilane v0.53.0, commit `15d5c99b1de982651af1b5cb00d339319d965661`, defaults
Grok wrapper retries to **five**. Offline Grok preparation now supplies the sole
allowlisted environment entry `OMNILANE_GROK_MAX_ATTEMPTS=1`; all caller assertions,
unconfined opt-ins and other environment entries are rejected. One wrapper
invocation is not one billable model call: native retries remain `UNVERIFIED`.
Grok macOS write preparation is rejected; there is no `--always-approve` /
`--sandbox off` fallback. Standalone Gemini CLI and Antigravity/agy are separate
contracts; agy's app-data configuration and interface compatibility remain
unverified. Missing or drifted transport overlays/caller bindings remain blocked;
the controller never re-signs or fabricates them.

The unchanged MIT-licensed `run-grok.sh` is retained under
`tests/support/upstream/omnilane-0.53.0`, SHA256
`120910ce341e9bbfebb33f64c7d6ac72e7578fcfe20642016a649f035f0b613b`.
POSIX tests run those exact bytes with a fake vendor and **mocked test-only helper
functions**. They verify default-five versus capped-one retries and actual argv,
not upstream authentication, real model success or OS isolation. Empty fake
vendor output remains failure even when the fake vendor exits zero.

## API, UI and verification

The existing authorized read-only `GET /api/projects/{project}/connections`
returns ten `provider_readiness` rows (five providers × two modes) for the server
OS. Each is `BLOCKED`, live model `NOTRUN`, OS evidence `UNVERIFIED`, wrapper
attempts one, native retries `UNVERIFIED`, with concrete blocking codes. It
exposes no commands, paths, environment or credential references. It performs no
database mutation and rechecks session/project authorization on every request,
including membership revocation. The KO/EN connections view presents these
conditions in a captioned, keyboard-scrollable responsive table.

The eight existing core CI environments remain intact. A dedicated ephemeral
Ubuntu 22.04 test job installs only official Ubuntu bubblewrap
`0.6.1-1ubuntu0.3` and records the package/binary/compiler versions and digest.
The preinstalled compiler builds an unpaid static malicious fixture. It checks
host ledger/credential sentinel invisibility, read-only write denial, inability
to reach a real host loopback listener, ambient environment/config isolation and
timeout/cancel cleanup of a `setsid()` descendant. No account/vendor network or
host security setting change occurs. Missing backend/compiler or denied user
namespaces is explicitly `BLOCKED`; unexpected probe failure is `FAILED`.
`scripts/isolation_ci_report.py` distinguishes these from
`VERIFIED_OFFLINE_PROBE` in the job summary; none counts as live verification.

Windows/macOS run portable contract tests only; Linux namespace probes are
`BLOCKED` there. Dedicated browser QA remains NOTRUN while the supported test
browser is unavailable. No private deployment, paid model call, new credential,
user-PC package installation or OS security change is part of this increment.

## Primary references

- [bubblewrap security model](https://github.com/containers/bubblewrap/blob/main/README.md)
- [Ubuntu pinned CI package](https://packages.ubuntu.com/jammy/bubblewrap)
- [Pinned Grok runner](https://github.com/Seraphim0916/omnilane/blob/15d5c99b1de982651af1b5cb00d339319d965661/scripts/runners/run-grok.sh)
- [Pinned transport overlay](https://github.com/Seraphim0916/omnilane/blob/15d5c99b1de982651af1b5cb00d339319d965661/docs/transport-overlay.md)
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Gemini headless CLI](https://geminicli.com/docs/cli/headless/)

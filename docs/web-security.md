# Web security and remaining evidence

The [private dispatcher](paid-dispatch.md) verifies exact externally issued
statements and rechecks consent/profile/session/project authority after signing.
Request consumption, budget hold and private delivery commit together. Durable
worker claim fences duplicate/restarted deliveries; launch/gate/HTTP/import
recheck revocation. Unknown results retain funds and cannot replay. Dispatcher
rows and backups contain private session bindings and signed grants; protect
them as artifacts. No HTTP signer/dispatch/credential endpoint exists. Operational
signing, credentials, production cgroups and actual models remain unverified.

[Paid request consent](paid-admission.md) binds one server session owner to
immutable scope/currency/cost limits. It accepts only a provisioned profile ID
or request ID/digest, never model overrides, actor, credentials, environments,
commands or URLs. Each mutation takes the project lock and rechecks current
authority/budget; newer quotes supersede old consent, and task cancel/recovery
revoke request records. No HTTP route dispatches paid model execution. Existing
operator worker receipt verification and launch authorization remain mandatory.

The [Claude transport](claude-transport.md) keeps provider credentials in an
operator-injected broker fd/memory callback, requires one-time durable HTTP
admission and drains upstream accounting after local cancellation. The CLI is
tool-free in a network namespace and an existing delegated cgroup. Operational
model/pricing evidence, vendor compatibility and actual target enforcement are
still required; fake-wire CI cannot supply those attestations.

The public static artifact is a synthetic read-only demo. It has no private API, authentication bypass or public-write endpoint. The standalone CSP allows only the exact inline script/style hashes and disallows all network connections, forms, objects and base URLs. The server-hosted build uses a self-only script/style policy, no external fonts, frame denial, `nosniff`, no-referrer and no-store. Hosting headers remain the responsibility of the selected platform.

Production private startup requires PostgreSQL, HTTPS origin/issuer and an existing OIDC registration. It rejects SQLite and insecure sessions. There is no environment flag enabling test users or an auth bypass. The explicit `testing=True` factory exists only for trusted test code; container recipes exclude `tests/` and fixture issuers. Production cookies use `__Host-iai_session`, Secure, HttpOnly, SameSite=Lax, path `/` and no Domain. No provider token is returned to browser storage.

CSRF combines an exact same-origin header and session-bound unpredictable token for JSON mutations. Foreign/`null` origins, cross-site fetch metadata and incorrect Host (including a wrong port) are rejected. CORS is not enabled. OIDC state/nonce/PKCE and signature/issuer/audience/expiry are checked through the pinned official Authlib client; application identity lookup is scoped to configured issuer and subject. Offline valid and forged/expired/mismatched JWT regressions test this contract, not a real issuer deployment.

Every object read, log, artifact and finite SSE snapshot checks project membership. Replayed mutation receipts still require a current grant. PostgreSQL project locks serialize membership revocation with mutations; a trusted dispatch must check current approver membership and every approval digest again immediately before any effect. Actual dispatch is unconditionally disabled.

The browser accepts fixed profiles and descriptive task text only. It cannot select a tenant/principal, repository URL, destination URL, environment, server path, command, provider or live gate. No server HTTP route runs a vendor CLI, repository program or outbound browser-selected URL. Operator-configured discovery/DB URLs need trusted network egress controls; they are not user input. React text escaping and plain-text artifact attachments prevent stored markup from becoming executable HTML. Static file serving is limited to build HTML/CSS/JS; `.env`, source files and arbitrary server paths are excluded.

Task submissions reject recognized secrets; audit detail is redacted before storage; errors never echo input. Production exception containment suppresses raw exceptions and database parameters. This regex redaction is defense in depth. A real scanner, source retention policy, DB encryption/backups and ingress access-log policy still need operational verification. OIDC callback query strings and cookies must not be logged at the ingress.

The local core retains its own single-user threat model. Neither worktrees nor this API constitute an OS sandbox. The separate runner is restricted to owned fixed fixtures and static parsers, with one mapped core ledger per attempt. Trusted receipt import reads real candidate bytes and the core ledger, recomputes digests and fences every database write. Worker capability is independent of human private-review approval. Database credentials remain in the supervisor and are excluded from the child environment; the worker needs no policy/membership/approval write privileges. Hostile-code isolation, real model execution, costs and all external effects remain unverified/disabled. Leases are never cleared merely because they expired. Unknown STARTING work becomes NEEDS_RECONCILIATION; completed receipt import never reruns the provider. Cancellation is confirmed only with never-started or completed fixed-fixture evidence. See [the runner contract](web-runner.md).

Before private rollout, independently verify actual PostgreSQL concurrency/restart/backups, OIDC provider and secure cookies through the target TLS ingress, active user/session/project revocation, rate and body limits, allowed proxy IPs, log redaction and artifact isolation. Supply a trusted ingress allowlist; `serve.py` rejects wildcard proxy trust. No production security setting, firewall, tunnel or public PC port was changed during implementation.


## Offline isolation evidence and live authority

[Launch contracts](provider-isolation.md) reject browser authority, fallback,
unconfined Grok macOS work, mutable binary/image digests and project hook/MCP
configuration. Offline probe evidence never satisfies a live capability or paid
model authorization. Namespace cleanup is independently tested with a setsid
descendant rather than inferred from leader exit. Trees must remain immutable
across pinning/launch; hostile host mutation and cgroup quotas are not implemented.
Provider and generated-code network separation still requires a verified broker.

The [approved fake vendor supervisor](web-approved-vendor.md) requires a current server session, requester and approver roles, bound current review approval and operator fixture grant, with durable one-time task/generation reservation and current-authority checks at Popen. Its child accepts only a fixed bounded synthetic descriptor and inherits no secrets. STARTING cannot be replayed without actual termination proof; lease expiry never proves cancellation. This path does not use the signed live receipt verifier or unlock any live provider.

## Native owner-bound worker

The [local CLI path](local-cli.md) accepts no HTTP command, executable, absolute path, environment, actor override, credential or live flag. Operator-local registration binds the binary/version to one existing web owner and project. Native credentials remain local, standard environment variables alone reach the child, and output is bounded/redacted before storage. Job/process-group cleanup is separate from remote cancellation and hostile-code OS isolation. A consumed/unknown request is never replayed or cleared by recovery. No public worker enrollment or credential migration is supplied.

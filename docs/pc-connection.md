# Owner-approved PC connection

The private console registers an outbound PC client scoped to one owner, project
and provider. It needs no server DB URL, browser session or OIDC client secret.
Existing CLI login stays on the PC. Opening the console never installs or starts
a worker. The public Sites introduction remains a static read-only demo.

## Register and review

1. A signed-in owner chooses Claude or Codex in **Connections**, then explicitly
   creates a pairing code. It expires in five minutes, is exchanged once and is
   shown once. Receipt retries return the device ID without its plaintext code.
2. The local operator selects an existing allowed executable/version and a new
   dedicated private state directory. Only these local arguments select paths.
   Install the locked package with its `web` extra, then locally run:

   ```text
   python -m intelligenceai.web.pc_client pair --origin https://console.example --provider codex --executable /operator/allowed/codex --version 0.162.1 --state-dir /operator/private/iai-pc
   ```

   Enter the code at the hidden prompt, never in a URL or command argument. The
   client generates a capability and stores it in `connection.json` in that
   directory. It prints device ID, provider/version and binary/runtime fingerprints.
   It does not read CLI credential files or change login, billing or firewall settings.
3. Refresh devices, compare the printed fingerprints, then **Approve this PC**.
   Pending devices cannot claim input. Activation expires after 30 days; there
   is no silent renewal. Server storage contains capability/pairing hashes only.
4. Separately prepare and approve a bound **Local CLI review** for a task. Locally
   run `python -m intelligenceai.web.pc_client once --state-dir ...`. This polls
   once, invokes at most one CLI and does not install a background service. Existing
   restrictions and the 60-second limit apply. Grok remains technically unavailable.

Keep the state directory private to its operator. POSIX creation modes are 0700
and 0600; Windows inherits its directory ACL, which the operator must verify.
The client is not an OS sandbox. A lost pairing exchange response leaves uncertain
local enrollment: review/revoke it and use a fresh directory rather than replaying
the code. Never delete consumption journals to resolve uncertain execution.

## Protocol and trust boundary

Machine POST routes are `/api/pc/exchange`, `/claim`, `/start`, `/heartbeat` and
`/result`. They require Authorization bearer; browser cookies are ignored and
Origin/Fetch Metadata are rejected. All other browser routes retain session,
same-origin, CSRF and idempotency checks. Host, HTTPS and bounded bodies apply to
machine routes too. The client disables redirects and ambient proxy settings and
accepts only a canonical operator-selected HTTPS origin. No server endpoint sends
argv, filesystem paths, environment variables or browser principals.

Claim binds owner/project/provider, immutable registration, task/generation,
candidate/evidence/policy/destination/approval/payload, attempt and lease. Every
operation rechecks active user, current owner membership and registration. Start
also rechecks the approval session, exact snapshot and expiry. PostgreSQL actor
and project fences serialize claims; start consumes the attempt once. The direct
DB worker rejects outbound-PC profiles.

**Atomic start is the execution authorization point.** Server DB locks cannot be
held across a remote PC's stdin handoff. After authorization, revoke/cancel is best
effort. The client checks again before handoff and polls heartbeat every two seconds,
terminating its owned local process on denial, communication failure, overflow or
deadline. Heartbeat leases last 15 seconds; the overall deadline is 60 seconds.
Cancellation remains requested until an accepted device cleanup report. Provider
side cancellation remains unknown.

Before requesting start, the client exclusively creates and fsyncs an attempt
consumption journal. Lost start responses/crashes never cause another CLI call.
Expired or revoked consumed work becomes `UNKNOWN`, retaining the lease and
blocking automatic replay/recovery. Result upload loss permits only the same
recorded result to be resent:

```text
python -m intelligenceai.web.pc_client retry-result --state-dir ... --attempt-id <saved-attempt-UUID>
```

Original upload hashes distinguish identical retries from conflicting content.
Artifact ID, project/task and fixed name are server-selected. Extra path, actor,
command or env fields are rejected. Request JSON is limited to 16 KiB, the text
field to 6,000 characters and client text to 6,000 UTF-8 bytes. Secrets are redacted
before private persistence; raw CLI streams are never uploaded or stored by the server.

Result/usage/cleanup source is `USER_DEVICE_REPORT`, scope `PC_REPORTED`. It does
not prove internal model call counts, billing, subscription eligibility, remote
cancellation or OS isolation. Verified invocation counts and model calls stay
unknown; fake fixtures retain live model `NOTRUN`. A compromised owner PC can
misreport outcomes. These reports cannot become trusted core execution receipts.

**Disconnect this PC** blocks new claim/start/import, disables the profile and
makes consumed in-flight attempts unknown. The next heartbeat fails and local
termination is best effort. It does not disconnect Codex app/SSH or change CLI login.

## Deployment and validation

`web_pc_runners` and `web_pc_attempts` are additive PostgreSQL tables. Apply the
reviewed schema through the existing init/migration procedure. No new secret
issuer, daemon, inbound PC port or deployment environment variables are required.
Reverse-proxy logs must exclude Authorization and request bodies.

The code is verified with synthetic enrollment/API, fake native processes and
UI components. Actual account enrollment, real tokens, new model calls and
production HTTPS/OIDC activation were not performed. Official mcp-ssh tools were
unavailable, so real deployment remains blocked; no SSH fallback, tunnel or
firewall changes were made. Dedicated IAB was unavailable; component/HTTP tests
are not browser QA.

`tests/test_pc_connection.py` covers scoped pairing, hashes, expiry/revocation,
binding/input attacks, cookie/Origin/Host/body defenses, cancellation and lease
behavior, secret redaction, identical/conflicting uploads, lost responses, replay
fences and execution without server configuration. CI runs independent real
ephemeral PostgreSQL claim/start barriers and preserves eight core environments.
`PCPanel.test.tsx` covers explicit consent/disconnect, duplicate clicks, navigation,
late responses, authority loss, ephemeral codes and Korean labels.

The local wall-clock deadline is independent of HTTP operation timeouts. An owned
process watchdog also covers the final authorization heartbeat before native stdin
handoff; every heartbeat response is checked against the monotonic deadline again.
Delayed final-gate and running responses are separate synthetic regression cases.

If cancellation commits after an immutable completed result journal was saved,
the exact bound cleanup report closes that attempt as `CANCELLED`. Its text is
discarded, and an identical retry returns the same receipt without another CLI
launch. Stale or conflicting uploads remain rejected.

Remote usage is a device report limited to input/output tokens
(`INPUT_OUTPUT_ONLY`). Cache/reasoning tokens and measurement time are not
provided. Missing values remain unknown and are never interpreted as zero.

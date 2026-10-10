# Paid review consent and request ledger

The private approval screen now records a server-owned quote, explicit consent,
and one durable execution request. Every response labels the model `NOTRUN`.
`REQUESTED` means an operator-admission request was recorded; it is not a queued
provider call, a reserved financial hold, or model execution success. There is
no request dispatcher or receipt signer in this release. The independent Claude
worker still requires its six signed control receipts and operator inputs.

No profile is provisioned by default. An operator must supply an existing,
verified `ClaudeProfile` and corresponding project budget through private
provisioning following the project lock. The GUI/API cannot create credentials,
change pricing, choose an arbitrary model/effort, or activate a runtime. Test
profiles are named `SYNTHETIC_PROFILE_ONLY` and never select real models.

The quote fixes the current session actor, project, task, generation, provider,
model, effort, one call, USD currency, cost ceiling, profile/candidate/evidence/
policy digests, private review destination and a maximum five-minute expiry.
Only a current project owner may consent and request. It is bound to that exact
server session; another user or a new login cannot reuse it. The server rechecks
task evidence/snapshot, cancellation, lease, generation, session, role, active
profile and available project budget at each mutation. Quotes do not hold funds;
the worker's existing paid ledger must reserve again immediately before launch.

| Route under `.../tasks/{task}/paid-review` | Input / behavior |
| --- | --- |
| `GET` | Authorized actor's history and provisioned profile summaries; read only |
| `POST /quote` | Only `profile_id`; derive all authority and cost fields on server |
| `POST /approve` | Only `request_id`, `quote_digest`; record exact consent |
| `POST /request` | Same binding; consume approved consent once for the generation |

All mutations use existing Origin/CSRF/JSON/idempotency controls. Same-key retries
return historical receipts; they do not create a second request. A different key
cannot consume consent again. A newer quote supersedes earlier unconsumed
consent. Cancellation/recovery revoke pending request records; current reads
label changed/expired bindings `STALE`. A subsequent execution requires recovery
to a new generation, fresh evidence and a fresh approval. Navigation and read
refreshes never send approval. The UI keeps request keys through lost responses,
ignores late responses after navigation/logout, and clears private data on
authority loss. Public synthetic demo pages do not mount this component.

Additive tables are `web_paid_profiles` and `web_paid_requests`; use the existing
reviewed `web.manage init-db` procedure after backup. No new secret environment
variable, account or payment management feature was added. Deployment still
needs the previously selected private HTTPS/OIDC/PostgreSQL target, existing
operator-confirmed credential path, verified Linux runtime and independently
issued control receipts. Nothing in this change enables actual paid calls.

Local service tests use SQLite, synthetic users/profile/budget and no provider.
CI additionally runs the same tests and competing request admission against real
ephemeral PostgreSQL. UI tests use jsdom; actual supported-browser/mobile QA
remains NOTRUN until the supported dedicated browser runtime is available.

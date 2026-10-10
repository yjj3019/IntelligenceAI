# Live authority receipt contracts

This increment verifies signed internal statements. It does not implement a
credential broker, egress proxy, cgroup controller, billing limiter, live vendor
executor or a browser enable switch. Successful verification returns
`VERIFIED_SIGNATURES_ONLY`, execution `BLOCKED`, model `NOTRUN`.

The server derives a `PaidApprovalBinding` from its durable approval snapshot.
It binds actor, project, task, generation, candidate, evidence, policy,
destination, manifest and expiry. A fixture execution grant cannot substitute
for the explicit `paid_model_execution` operation. The manifest digest includes
provider/model/effort, image and executable pins, write and network scope,
credential references, deadline and invocation/cost ceilings.

Six distinct control statements are required: provider capability, credential
broker, provider egress, resource limits, cost accounting and paid-call
authorization. An operator-owned verifier registry associates each Ed25519
public key with one control role. A signature from another role, unknown key,
remote-key header, symmetric algorithm, duplicate JSON field or duplicate
receipt ID is rejected. Statements must match the exact manifest and approval
digests. Their issuance cannot be in the future and their expiry cannot exceed
the approval or manifest. At verification the deadline must be within 300
seconds; exact expiry is rejected. An empty key registry fails closed.

The verifier has no HTTP route, private-key generator, credential loader,
database write or process launcher. It accepts no signing authority from the
browser. Signatures authenticate statements made by registered attestors; they
do not independently prove the underlying OS, network, credential or billing
claims. Tests use ephemeral, in-memory keys and synthetic evidence digests.
They are not real-provider evidence.

The separate [approved synthetic vendor flow](web-approved-vendor.md) exercises
durable one-time reservation and current session/membership, generation,
approval and cancellation rechecks using a fixed fake executable. It cannot
consume these statements or enable a live provider. Before a production runner
can consume these contracts it still needs independent attestor provisioning and key
revocation; verified secret brokering and provider-only egress; actual resource
and billing enforcement; immutable host materialization; and authorization for
the specific paid call. Receipts must be rechecked at the actual spawn boundary.
Receipt replay across separate verification calls is intentionally not claimed
to be prevented by this stateless verifier.

The existing Linux executor continues to reject every live provider. The API
and GUI continue to report all live provider/mode combinations as blocked.
Browser QA and the private PostgreSQL/OIDC/HTTPS deployment remain separate
unfinished work.

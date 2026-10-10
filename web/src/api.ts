export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    credentials: "same-origin",
    headers: { Accept: "application/json", ...options.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, data.error || "request_failed");
  }
  return response.json() as Promise<T>;
}
export function mutation<T>(
  path: string,
  csrf: string,
  key: string,
  body: unknown,
  method = "POST",
) {
  return api<T>(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
      "Idempotency-Key": key,
    },
    body: JSON.stringify(body),
  });
}
export function message(error: unknown): string {
  if (error instanceof ApiError) {
    const safeCodes: Record<string, string> = {
      fixture_execution_grant_required:
        "An operator must provision an unexpired fixed-fixture capability before this task can be queued.",
      fixture_run_not_available:
        "This task cannot be queued in its current state. Refresh its saved status.",
      termination_receipt_required:
        "Recovery is blocked until a trusted termination receipt confirms the prior runner stopped. Do not clear its lease.",
      recovery_not_available:
        "Recovery is unavailable in this state. Refresh status and review the task.",
      verified_evidence_required:
        "Approval is blocked until trusted candidate and evidence checks are verified.",
      approval_binding_changed:
        "The candidate, policy, evidence, destination or generation changed. Refresh before preparing a new approval intent.",
      approval_expired_or_ttl_invalid:
        "This approval intent expired. Check its recorded receipt before explicitly preparing a new intent.",
      idempotency_conflict:
        "This request key belongs to a different payload. Reconcile the recorded request before starting a new intent.",
    };
    if (error.status === 409 && Object.hasOwn(safeCodes, error.code))
      return safeCodes[error.code];
    if (error.status === 401)
      return "Your session expired. Sign in again to continue.";
    if (error.status === 403 || error.status === 404)
      return "Access is unavailable. Your project permissions may have changed.";
    if (error.status === 409)
      return "The task or approval changed. Refresh and review the latest evidence.";
    if (error.status === 422)
      return "Check your input. Credentials, commands and authority fields are not accepted.";
    return "The service could not complete this request. Try again with the same request key.";
  }
  return "Connection interrupted. Reconnect to retrieve the latest saved state.";
}

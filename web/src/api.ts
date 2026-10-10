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

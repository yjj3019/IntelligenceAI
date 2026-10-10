import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError, message, mutation } from "./api";
import { translate } from "./i18n";
afterEach(() => vi.restoreAllMocks());
it("reuses request keys and only sends session-bound CSRF authority", async () => {
  const spy = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response("{}"));
  await mutation("/projects/p/tasks", "csrf", "fixed-key", { title: "Review" });
  await mutation("/projects/p/tasks", "csrf", "fixed-key", { title: "Review" });
  for (const [, options] of spy.mock.calls) {
    expect(options?.credentials).toBe("same-origin");
    expect(options?.headers).toMatchObject({
      "Idempotency-Key": "fixed-key",
      "X-CSRF-Token": "csrf",
    });
    expect(options?.body).not.toContain("principal");
  }
});
it("maps safe recovery/approval conflict codes to distinct KO/EN guidance", () => {
  const codes = [
    "termination_receipt_required",
    "recovery_not_available",
    "verified_evidence_required",
    "approval_binding_changed",
    "approval_expired_or_ttl_invalid",
    "idempotency_conflict",
  ];
  const messages = codes.map((code) => message(new ApiError(409, code)));
  expect(new Set(messages).size).toBe(codes.length);
  for (const text of messages)
    expect(translate("ko", text)).not.toBe(translate("en", text));
  expect(messages[0]).toContain("termination receipt");
  expect(message(new ApiError(409, "raw_secret_exception"))).not.toContain(
    "raw_secret_exception",
  );
});
it("does not echo server exceptions or credential payloads", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: "private_sql_with_secret" }), {
      status: 500,
    }),
  );
  await expect(api("/session")).rejects.toBeInstanceOf(ApiError);
  expect(message(new ApiError(500, "secret"))).not.toContain("secret");
});

import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError, message, mutation } from "./api";
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
it("does not echo server exceptions or credential payloads", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: "private_sql_with_secret" }), {
      status: 500,
    }),
  );
  await expect(api("/session")).rejects.toBeInstanceOf(ApiError);
  expect(message(new ApiError(500, "secret"))).not.toContain("secret");
});

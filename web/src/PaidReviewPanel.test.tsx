import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LocaleProvider } from "./i18n";
import { PaidReviewPanel } from "./PaidReviewPanel";

const properties = {
  projectId: "project",
  taskId: "task",
  generation: 1,
  csrf: "csrf-fixture",
  onAuthorityLost: vi.fn(),
};
const quote = {
  actor_id: "fixture-actor",
  project_id: "project",
  task_id: "task",
  generation: 1,
  provider: "claude",
  model: "claude-fixture-test",
  effort: "low",
  max_calls: 1,
  currency: "USD",
  cost_ceiling_microusd: 240,
  expires_at: Math.floor(Date.now() / 1000) + 300,
  candidate_digest: "a".repeat(64),
  policy_digest: "b".repeat(64),
  evidence_digest: "c".repeat(64),
  destination_id: "private-model-review",
};
const record = {
  id: "request",
  quote,
  quote_digest: "d".repeat(64),
  state: "QUOTED",
  live_model: "NOTRUN",
};
const status = {
  profiles: [
    {
      id: "profile",
      name: "SYNTHETIC_PROFILE_ONLY",
      model: quote.model,
      effort: "low",
      cost_ceiling_microusd: 240,
    },
  ],
  requests: [],
  can_consent: true,
  generation: 1,
  execution_enabled: false,
  live_model: "NOTRUN",
  blockers: [],
};
const response = (value: unknown, statusCode = 200) =>
  new Response(JSON.stringify(value), {
    status: statusCode,
    headers: { "Content-Type": "application/json" },
  });
function panel(props = properties) {
  return (
    <LocaleProvider>
      <PaidReviewPanel {...props} />
    </LocaleProvider>
  );
}
beforeEach(() => {
  vi.restoreAllMocks();
  properties.onAuthorityLost.mockClear();
  localStorage.setItem("iai.language", "en");
});

it("records fixed consent and one explicit request, with double-click and navigation having no extra effects", async () => {
  const posts: { path: string; options: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options: RequestInit) => {
      if (options.method !== "POST") return response(status);
      posts.push({ path, options });
      return response({
        ...record,
        state: path.endsWith("/quote")
          ? "QUOTED"
          : path.endsWith("/approve")
            ? "APPROVED"
            : "REQUESTED",
      });
    }),
  );
  const view = render(panel());
  const prepare = screen.getByRole("button", {
    name: "Prepare paid review quote",
  });
  await waitFor(() => expect(prepare).toBeEnabled());
  fireEvent.click(prepare);
  fireEvent.click(prepare);
  const approve = await screen.findByRole("button", {
    name: "Approve this cost ceiling",
  });
  await waitFor(() => expect(approve).toBeEnabled());
  expect(screen.getByText("USD 0.000240")).toBeInTheDocument();
  expect(
    screen.getByText("claude / claude-fixture-test / low"),
  ).toBeInTheDocument();
  fireEvent.click(approve);
  fireEvent.click(approve);
  const request = screen.getByRole("button", {
    name: "Request this review once",
  });
  await waitFor(() => expect(request).toBeEnabled());
  fireEvent.click(request);
  fireEvent.click(request);
  expect(
    await screen.findByText(/One execution request recorded/),
  ).toBeInTheDocument();
  expect(posts).toHaveLength(3);
  expect(JSON.parse(posts[0].options.body as string)).toEqual({
    profile_id: "profile",
  });
  expect(JSON.parse(posts[1].options.body as string)).toEqual({
    request_id: "request",
    quote_digest: "d".repeat(64),
  });
  view.unmount();
  expect(posts).toHaveLength(3);
});

it("retries interrupted consent with the same payload and key; saved-state reads never send consent", async () => {
  const posts: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, options: RequestInit) => {
      if (options.method !== "POST")
        return response({ ...status, requests: [record] });
      posts.push(options);
      if (posts.length === 1) throw new TypeError("fixture lost response");
      return response({ ...record, state: "APPROVED" });
    }),
  );
  render(panel());
  const approve = screen.getByRole("button", {
    name: "Approve this cost ceiling",
  });
  await waitFor(() => expect(approve).toBeEnabled());
  fireEvent.click(approve);
  await screen.findByRole("alert");
  fireEvent.click(
    screen.getByRole("button", { name: "Check saved paid request" }),
  );
  await waitFor(() => expect(approve).toBeEnabled());
  expect(posts).toHaveLength(1);
  fireEvent.click(approve);
  await screen.findByText(/Consent recorded for this exact quote/);
  expect(posts).toHaveLength(2);
  expect(posts[0].body).toBe(posts[1].body);
  expect(posts[0].headers).toEqual(posts[1].headers);
});

it("keeps an expired intent disabled and clears private content on revoked authority", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, options: RequestInit) => {
      if (options.method === "POST")
        return response({ error: "role_required" }, 403);
      return response({
        ...status,
        requests: [{ ...record, quote: { ...quote, expires_at: 1 } }],
      });
    }),
  );
  render(panel());
  expect(
    await screen.findByText(/This paid intent expired/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Approve this cost ceiling" }),
  ).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Prepare paid review quote" }),
  );
  await waitFor(() =>
    expect(properties.onAuthorityLost).toHaveBeenCalledWith(403),
  );
  expect(screen.queryByText("fixture-actor")).not.toBeInTheDocument();
});

it("ignores a late previous-task response and shows setup blockers with no model defaults", async () => {
  let resolve: (value: Response) => void = () => {};
  const first = new Promise<Response>((yes) => {
    resolve = yes;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      path.includes("/tasks/task/")
        ? first
        : Promise.resolve(response({ ...status, profiles: [], requests: [] })),
    ),
  );
  const view = render(panel());
  view.rerender(panel({ ...properties, taskId: "other" }));
  await screen.findByText(
    /An operator must provision an existing model profile/,
  );
  await act(async () => resolve(response({ ...status, requests: [record] })));
  expect(screen.queryByText("fixture-actor")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Prepare paid review quote" }),
  ).toBeDisabled();
});

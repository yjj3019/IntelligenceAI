import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LocaleProvider } from "./i18n";
import { LocalCLIPanel } from "./LocalCLIPanel";

const props = {
  projectId: "project",
  taskId: "task",
  generation: 1,
  csrf: "synthetic-csrf",
  onAuthorityLost: vi.fn(),
};
const profile = {
  id: "profile",
  provider: "codex",
  version: "SYNTHETIC",
  scope: "FAKE_CLI_TEST_ONLY",
  installation: "FAKE_INSTALLED",
  availability: "FAKE_TEST_ONLY",
  can_execute: true,
  quota: {
    status: "PROVIDED",
    measured_at: 123,
    source: "SYNTHETIC:account/rateLimits/read",
    limits: [
      {
        limit_id: "fixture",
        windows: {
          primary: {
            usedPercent: 0,
            windowDurationMins: 10080,
            resetsAt: null,
          },
        },
      },
    ],
  },
};
const record = {
  id: "request",
  profile_id: "profile",
  generation: 1,
  state: "PREPARED",
  binding_digest: "d".repeat(64),
  result: null,
  binding: {
    provider: "codex",
    candidate_digest: "a".repeat(64),
    evidence_digest: "b".repeat(64),
    policy_digest: "c".repeat(64),
    expires_at: Math.floor(Date.now() / 1000) + 300,
    max_cli_invocations: 1,
    wall_seconds: 60,
    result_destination: "private-cli-review",
  },
};
const status = {
  profiles: [profile],
  requests: [],
  generation: 1,
  can_consent: true,
};
const response = (value: unknown, code = 200) =>
  new Response(JSON.stringify(value), {
    status: code,
    headers: { "Content-Type": "application/json" },
  });
const panel = (properties: Parameters<typeof LocalCLIPanel>[0] = props) => (
  <LocaleProvider>
    <LocalCLIPanel {...properties} />
  </LocaleProvider>
);
beforeEach(() => {
  vi.restoreAllMocks();
  props.onAuthorityLost.mockClear();
  localStorage.clear();
});

it("mount, reconnect and manual refresh only read saved status", async () => {
  const fetcher = vi.fn().mockResolvedValue(response(status));
  vi.stubGlobal("fetch", fetcher);
  render(panel());
  await screen.findByRole("combobox");
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "profile" },
  });
  await screen.findByText(/SYNTHETIC:account\/rateLimits\/read/);
  expect(screen.getByText(/10080 min/)).toBeInTheDocument();
  expect(screen.getByText(/0%/)).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh saved CLI status" }),
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(fetcher.mock.calls.every((call) => !call[1].method)).toBe(true);
});

it("explicit prepare and approve queue once; double clicks never duplicate", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(response(status))
    .mockResolvedValueOnce(response(record))
    .mockResolvedValueOnce(response({ ...status, requests: [record] }))
    .mockResolvedValueOnce(response({ ...record, state: "QUEUED" }))
    .mockResolvedValueOnce(
      response({
        ...status,
        can_consent: false,
        requests: [{ ...record, state: "QUEUED" }],
      }),
    );
  vi.stubGlobal("fetch", fetcher);
  render(panel());
  await screen.findByRole("combobox");
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "profile" },
  });
  const prepare = screen.getByRole("button", { name: "Prepare CLI approval" });
  fireEvent.click(prepare);
  fireEvent.click(prepare);
  const approve = await screen.findByRole("button", {
    name: "Approve and queue once",
  });
  fireEvent.click(approve);
  fireEvent.click(approve);
  await screen.findByText("Saved CLI request: QUEUED");
  const posts = fetcher.mock.calls.filter((call) => call[1].method === "POST");
  expect(posts).toHaveLength(2);
  expect(JSON.parse(posts[1][1].body)).toEqual({
    request_id: "request",
    binding_digest: record.binding_digest,
  });
  expect(posts[1][1].headers["X-CSRF-Token"]).toBe("synthetic-csrf");
});

it("unknown usage is not zero and incomplete native usage is separate", async () => {
  const saved = {
    ...record,
    state: "COMPLETED",
    result: {
      availability: "AVAILABLE",
      scope: "FAKE_CLI_TEST_ONLY",
      live_model: "NOTRUN",
      local_termination_confirmed: true,
      remote_cancellation: "UNKNOWN",
      usage: {
        source: "SYNTHETIC:cli-result",
        measured_at: 456,
        unit: "tokens",
        completeness: "INCOMPLETE",
        values: {
          input_tokens: 12,
          cached_input_tokens: null,
          output_tokens: 0,
        },
      },
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response({ ...status, requests: [saved] })),
  );
  render(panel());
  await screen.findByText(/SYNTHETIC:cli-result/);
  expect(
    screen.getByRole("heading", { name: "Account usage snapshot" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "This execution's tokens" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Unknown tokens")).toBeInTheDocument();
  expect(screen.getByText("0 tokens")).toBeInTheDocument();
  expect(screen.getByText(/INCOMPLETE/)).toBeInTheDocument();
});

it("authority loss clears private controls and reports to the parent", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response({ error: "project_not_found" }, 404)),
  );
  render(panel());
  await screen.findByRole("alert");
  expect(props.onAuthorityLost).toHaveBeenCalledWith(404);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});

it("late responses cannot leak across task navigation", async () => {
  let deliver: (value: Response) => void = () => {};
  const fetcher = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          deliver = resolve;
        }),
    )
    .mockResolvedValueOnce(response({ ...status, profiles: [], requests: [] }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(
    <LocaleProvider>
      <LocalCLIPanel key="old" {...props} />
    </LocaleProvider>,
  );
  view.rerender(
    <LocaleProvider>
      <LocalCLIPanel key="new" {...props} taskId="other" />
    </LocaleProvider>,
  );
  await screen.findByText(/No owner-bound/);
  await act(async () =>
    deliver(
      response({
        ...status,
        profiles: [{ ...profile, provider: "PRIVATE_OLD_CONTEXT" }],
      }),
    ),
  );
  expect(screen.queryByText(/PRIVATE_OLD_CONTEXT/)).not.toBeInTheDocument();
});

it("renders untrusted status as escaped text and keeps unsupported CLI disabled", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        ...status,
        profiles: [
          {
            ...profile,
            provider: "grok",
            can_execute: false,
            restriction: '<img src=x onerror="alert(1)">',
          },
        ],
      }),
    ),
  );
  const view = render(panel());
  await screen.findByRole("combobox");
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "profile" },
  });
  expect(
    screen.getByRole("button", { name: "Prepare CLI approval" }),
  ).toBeDisabled();
  expect(view.container.querySelector("img")).toBeNull();
  expect(
    screen.getByText('<img src=x onerror="alert(1)">'),
  ).toBeInTheDocument();
});

it("expired approval cannot be queued", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        ...status,
        requests: [
          { ...record, binding: { ...record.binding, expires_at: 1 } },
        ],
      }),
    ),
  );
  render(panel());
  expect(
    await screen.findByRole("button", { name: "Approve and queue once" }),
  ).toBeDisabled();
});

const resultArtifact = {
  id: "result",
  kind: "cli-result",
  name: "Private review",
  digest: "a".repeat(64),
};

it("opens only CLI result artifacts as escaped private text", async () => {
  const fetcher = vi
    .fn()
    .mockImplementation(async (input) =>
      String(input).includes("/artifacts/")
        ? new Response("SYNTHETIC_RESULT <img src=x onerror=alert(1)>")
        : response(status),
    );
  vi.stubGlobal("fetch", fetcher);
  const view = render(
    panel({
      ...props,
      artifacts: [
        { ...resultArtifact, id: "candidate", kind: "candidate" },
        resultArtifact,
      ],
    }),
  );
  const button = await screen.findByRole("button", {
    name: "Open CLI result: Private review",
  });
  fireEvent.click(button);
  expect(await screen.findByLabelText("CLI result text")).toHaveTextContent(
    "SYNTHETIC_RESULT",
  );
  expect(view.container.querySelector("img")).toBeNull();
  expect(
    fetcher.mock.calls
      .filter(([input]) => String(input).includes("/artifacts/"))
      .map(([input]) => String(input)),
  ).toEqual(["/api/projects/project/tasks/task/artifacts/result"]);
});

it("late result bytes are discarded after task navigation", async () => {
  let deliver: (value: Response) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (input) =>
      String(input).includes("/artifacts/")
        ? new Promise<Response>((resolve) => {
            deliver = resolve;
          })
        : response(status),
    ),
  );
  const view = render(
    <LocaleProvider>
      <LocalCLIPanel key="old-result" {...props} artifacts={[resultArtifact]} />
    </LocaleProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Open CLI result: Private review",
    }),
  );
  view.rerender(
    <LocaleProvider>
      <LocalCLIPanel key="new-result" {...props} taskId="other" />
    </LocaleProvider>,
  );
  await act(async () => deliver(new Response("PRIVATE_OLD_RESULT")));
  expect(screen.queryByText("PRIVATE_OLD_RESULT")).not.toBeInTheDocument();
});

it("KO errors and diagnostic outcomes are localized while codes are preserved", async () => {
  localStorage.setItem("iai.language", "ko");
  const fetcher = vi
    .fn()
    .mockImplementation(async (input) =>
      String(input).includes("/artifacts/")
        ? response({ error: "project_not_found" }, 403)
        : response({
            ...status,
            requests: [
              {
                ...record,
                state: "UNKNOWN",
                result: {
                  availability: "PARTIAL_FAILURE",
                  scope: "LOCAL_NATIVE_CLI",
                  live_model: "UNKNOWN",
                  local_termination_confirmed: true,
                  remote_cancellation: "UNKNOWN",
                },
              },
            ],
          }),
    );
  vi.stubGlobal("fetch", fetcher);
  render(panel({ ...props, artifacts: [resultArtifact] }));
  expect(await screen.findByText(/진단이 포함된 완료/)).toBeInTheDocument();
  expect(screen.getByText("PARTIAL_FAILURE")).toBeInTheDocument();
  expect(screen.getByText(/0% 사용/)).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "CLI 결과 열기: Private review" }),
  );
  expect(await screen.findByRole("alert")).not.toHaveTextContent(
    "Access is unavailable",
  );
  expect(props.onAuthorityLost).toHaveBeenCalledWith(403);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});

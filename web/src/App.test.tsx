import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { demoAudit, demoConnections, demoProject, demoTasks } from "./demo";
import type { Task } from "./types";

beforeEach(() => {
  localStorage.setItem("iai.language", "en");
  history.replaceState({}, "", "/demo");
  vi.restoreAllMocks();
});

describe("read-only demo", () => {
  it("shows eight accessible screens and explicit fixture provenance", async () => {
    render(<App />);
    expect(
      await screen.findByRole("heading", {
        name: "Make room for thoughtful work.",
      }),
    ).toBeVisible();
    expect(
      screen.getByText(/Sample tasks and evidence. No model has run/),
    ).toBeVisible();
    const labels = [
      "Projects & people",
      "New task",
      "Task & steps",
      "Candidate & checks",
      "Approval & recovery",
      "Connections",
      "Audit trail",
    ];
    for (const label of labels) {
      fireEvent.click(
        screen.getByRole("link", {
          name: new RegExp("^" + label.replace("&", "&")),
        }),
      );
      expect(
        screen.getByRole("heading", { name: label, level: 1 }),
      ).toBeVisible();
    }
    expect(
      screen.queryByRole("button", { name: "Save to private ledger" }),
    ).not.toBeInTheDocument();
  });
  it("previews without writes or model calls and preserves form across navigation", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: /^New task$/ }));
    fireEvent.change(screen.getByLabelText("Task title"), {
      target: { value: "Review settings" },
    });
    fireEvent.change(screen.getByLabelText("What should change?"), {
      target: { value: "Inspect the defaults" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview plan" }));
    expect(
      screen.getByRole("button", { name: "Save to private ledger" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/0 model calls · execution disabled/),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: /^Overview$/ }));
    fireEvent.click(screen.getByRole("link", { name: /^New task$/ }));
    expect(screen.getByLabelText("Task title")).toHaveValue("Review settings");
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("filters tasks and keeps browser back navigation consistent", async () => {
    render(<App />);
    fireEvent.change(screen.getByRole("textbox", { name: "Search tasks" }), {
      target: { value: "nonexistent" },
    });
    expect(screen.getByText("No matching tasks")).toBeVisible();
    history.replaceState({}, "", "/demo/candidate?task=sample-review");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(
      screen.getByRole("heading", { name: "Candidate & checks" }),
    ).toBeVisible();
    expect(
      await screen.findByText(/Synthetic illustration only/),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Record review approval" }),
    ).not.toBeInTheDocument();
  });
});

function privateFetch(
  status = 200,
  taskOverrides: Partial<(typeof demoTasks)[number]> = {},
) {
  const project = {
    ...demoProject,
    id: "project-fixture",
    role: "owner" as const,
    members: [],
  };
  const task = {
    ...demoTasks[0],
    id: "task-fixture",
    project_id: project.id,
    source: "test-fixture",
    title: "<img src=x onerror=alert(1)>",
    state: "BLOCKED",
    candidate_digest: null,
    evidence_digest: null,
    artifacts: [],
    ...taskOverrides,
  };
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, options) => {
      const path = String(input);
      if (status !== 200)
        return new Response(JSON.stringify({ error: "sign_in_required" }), {
          status,
        });
      let body: unknown = {};
      if (path === "/api/session")
        body = {
          user: { id: "user-fixture", name: "Fixture user" },
          csrf: "test-csrf",
        };
      else if (path === "/api/projects") body = [project];
      else if (path === "/api/projects/" + project.id) body = project;
      else if (path.endsWith("/audit")) body = demoAudit;
      else if (path.endsWith("/connections")) body = demoConnections;
      else if (path.endsWith("/paid-review"))
        body = {
          profiles: [],
          requests: [],
          can_consent: true,
          generation: task.generation,
          execution_enabled: false,
          live_model: "NOTRUN",
          blockers: [],
        };
      else if (path.endsWith("/tasks") && !options?.method) body = [task];
      else if (path.endsWith("/tasks/" + task.id)) body = task;
      else if (path.endsWith("/cancel"))
        body = { id: task.id, state: "CANCEL_REQUESTED" };
      else if (path.endsWith("/tasks") && options?.method === "POST")
        body = { id: task.id, state: "BLOCKED" };
      else if (path.endsWith("/preview")) body = task.plan;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
}

describe("private boundary and failure flows", () => {
  function approvedVendor(
    taskOverrides: Partial<Task> = {},
    authorized = true,
  ) {
    history.replaceState({}, "", "/app/task");
    const mock = privateFetch(200, {
      state: "READY_FOR_APPROVAL",
      generation: 2,
      approval: {
        candidate_digest: "a".repeat(64),
        evidence_digest: "b".repeat(64),
        policy_digest: "c".repeat(64),
        destination_id: "private-review",
        generation: 2,
        expires_at: Math.floor(Date.now() / 1000) + 300,
      },
      ...taskOverrides,
    });
    const base = mock.getMockImplementation()!;
    mock.mockImplementation(async (input, options) => {
      if (String(input).endsWith("/connections"))
        return new Response(
          JSON.stringify({
            ...demoConnections,
            fixture_execution: authorized ? "AUTHORIZED" : "BLOCKED",
          }),
        );
      if (String(input).endsWith("/run-approved-fixture"))
        return new Response(
          JSON.stringify({ id: "task-fixture", state: "VENDOR_QUEUED" }),
        );
      return base(input, options);
    });
    return mock;
  }
  it("queues a synthetic vendor only on explicit action, with old generations preserved", async () => {
    const mock = approvedVendor({
      vendor_runs: [
        { id: "old-run", generation: 1, state: "TERMINATED", result: null },
      ],
    });
    render(<App />);
    const button = await screen.findByRole("button", {
      name: "Run approved synthetic vendor",
    });
    await waitFor(() => expect(button).toBeEnabled());
    const posts = () =>
      mock.mock.calls.filter(([, opts]) => opts?.method === "POST");
    expect(posts()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    const refreshed = await screen.findByRole("button", {
      name: "Run approved synthetic vendor",
    });
    await waitFor(() => expect(refreshed).toBeEnabled());
    expect(posts()).toHaveLength(0);
    fireEvent.click(refreshed);
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(String(posts()[0][0])).toMatch(/\/run-approved-fixture$/);
    expect(posts()[0][1]?.body).toBe("{}");
    expect(
      await screen.findByText(
        "Approved synthetic vendor queued. No paid model is authorized.",
      ),
    ).toBeVisible();
  });
  it.each(["missing", "expired", "duplicate", "no-capability"])(
    "blocks synthetic execution with %s authority",
    async (reason) => {
      const mock = approvedVendor(
        reason === "missing"
          ? { approval: null }
          : reason === "expired"
            ? {
                approval: {
                  candidate_digest: "a".repeat(64),
                  evidence_digest: "b".repeat(64),
                  policy_digest: "c".repeat(64),
                  generation: 2,
                  destination_id: "private-review",
                  expires_at: 1,
                },
              }
            : reason === "duplicate"
              ? {
                  vendor_runs: [
                    {
                      id: "current",
                      generation: 2,
                      state: "RESERVED",
                      result: null,
                    },
                  ],
                }
              : {},
        reason !== "no-capability",
      );
      render(<App />);
      expect(
        await screen.findByRole("button", {
          name: "Run approved synthetic vendor",
        }),
      ).toBeDisabled();
      expect(
        mock.mock.calls.filter(([, opts]) => opts?.method === "POST"),
      ).toHaveLength(0);
    },
  );
  it("labels synthetic output and process termination without claiming a live model", async () => {
    approvedVendor({
      state: "FIXTURE_COMPLETED",
      vendor_runs: [
        {
          id: "synthetic-run",
          generation: 2,
          state: "COMPLETED",
          result: {
            kind: "completed",
            scope: "FAKE_VENDOR_TEST_ONLY",
            live_model: "NOTRUN",
            termination_confirmed: true,
            output: {
              message: "Synthetic fixture completed",
              value: 42,
              status: "SYNTHETIC_OUTPUT",
            },
          },
        },
      ],
    });
    render(<App />);
    expect(
      await screen.findByRole("heading", {
        name: "Approved synthetic vendor runs",
      }),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Synthetic process termination confirmed. Live model NOTRUN.",
      ),
    ).toBeVisible();
    expect(screen.getByText(/fixed fake executable/)).toBeVisible();
    expect(screen.getByText("Synthetic fixture completed: 42")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Run approved synthetic vendor" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Switch to Korean" }));
    expect(screen.getByText("합성 vendor 완료")).toBeVisible();
    expect(
      screen.getByText(
        "합성 프로세스 종료를 확인했습니다. 실제 모델은 NOTRUN입니다.",
      ),
    ).toBeVisible();
  });
  it("shows server provider blockers in both languages without enabling execution", async () => {
    history.replaceState({}, "", "/app/connections");
    const mock = privateFetch();
    const original = mock.getMockImplementation()!;
    mock.mockImplementation(async (input, options) => {
      if (String(input).endsWith("/connections"))
        return new Response(
          JSON.stringify({
            ...demoConnections,
            provider_readiness: [
              {
                provider: "grok",
                mode: "write",
                host_os: "Darwin",
                status: "BLOCKED",
                reasons: [
                  "grok_macos_write_unsupported",
                  "paid_model_not_authorized",
                ],
                live_model: "NOTRUN",
                os_isolation: "UNVERIFIED",
                wrapper_attempts: 1,
                native_retries: "UNVERIFIED",
              },
            ],
          }),
        );
      return original(input, options);
    });
    render(<App />);
    expect(
      await screen.findByRole("heading", {
        name: "Provider execution readiness",
      }),
    ).toBeVisible();
    expect(screen.getByRole("table")).toHaveAccessibleName(
      /All live execution is blocked/,
    );
    expect(
      screen.getByText("Grok macOS write mode is unsupported"),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Run live/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch to Korean" }));
    expect(
      screen.getByText("Grok의 macOS 파일 변경 모드 미지원"),
    ).toBeVisible();
    expect(
      mock.mock.calls.every(
        ([, options]) => !options?.method || options.method === "GET",
      ),
    ).toBe(true);
  });
  it("renders confirmed cancellation before invocation without completed steps", async () => {
    history.replaceState({}, "", "/app/task");
    privateFetch(200, {
      state: "CANCELLED",
      runs: [
        {
          core_task_id: "never-started",
          generation: 1,
          phase: "TERMINATED",
          receipt: { kind: "never_started", never_started: true },
        },
      ],
    });
    render(<App />);
    expect(
      await screen.findByText(/Cancellation confirmed before invocation/),
    ).toBeVisible();
    expect(
      screen.queryByText(/Static checks verify candidate bytes/),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch to Korean" }));
    expect(
      screen.getByText(/실행 호출 전에 취소가 확인됐습니다/),
    ).toBeVisible();
  });
  it("refreshes SSE artifact changes and rejects late bytes after replacement or recovery", async () => {
    history.replaceState({}, "", "/app/candidate");
    const mock = privateFetch();
    const base = mock.getMockImplementation()!;
    const streams: Stream[] = [];
    class Stream {
      onerror = null;
      close = vi.fn();
      snapshot: ((event: MessageEvent) => void) | undefined;
      constructor() {
        streams.push(this);
      }
      addEventListener(_name: string, handler: (event: MessageEvent) => void) {
        this.snapshot = handler;
      }
    }
    const original = globalThis.EventSource;
    vi.stubGlobal("EventSource", Stream);
    const responses: ((value: Response) => void)[] = [];
    mock.mockImplementation(async (input, options) => {
      if (String(input).includes("/artifacts/"))
        return new Promise<Response>((resolve) => responses.push(resolve));
      return base(input, options);
    });
    const view = render(<App />);
    try {
      await screen.findByRole("heading", {
        name: "Candidate & checks",
        level: 1,
      });
      await waitFor(() => expect(streams).toHaveLength(1));
      const task = {
        ...demoTasks[0],
        id: "task-fixture",
        project_id: "project-fixture",
        title: "Updated task",
        source: "test-fixture",
        generation: 1,
        state: "READY_FOR_APPROVAL",
      };
      const snapshot = async (digest: string | null, generation = 1) =>
        act(async () => {
          streams[0].snapshot?.(
            new MessageEvent("snapshot", {
              data: JSON.stringify({
                ...task,
                generation,
                artifacts: digest ? [{ id: "artifact-fixture", digest }] : [],
              }),
            }),
          );
        });
      await snapshot("a".repeat(64));
      await waitFor(() => expect(responses).toHaveLength(1));
      await snapshot("b".repeat(64));
      await waitFor(() => expect(responses).toHaveLength(2));
      await act(async () => responses[0](new Response("stale-candidate")));
      expect(screen.queryByText("stale-candidate")).not.toBeInTheDocument();
      await act(async () => responses[1](new Response("current-candidate")));
      expect(await screen.findByText("current-candidate")).toBeVisible();
      await snapshot("c".repeat(64));
      await waitFor(() => expect(responses).toHaveLength(3));
      await snapshot(null, 2);
      await act(async () => responses[2](new Response("removed-candidate")));
      expect(screen.queryByText("removed-candidate")).not.toBeInTheDocument();
      expect(screen.queryByText("current-candidate")).not.toBeInTheDocument();
      expect(screen.getByText("No candidate artifact yet")).toBeVisible();
      expect(
        mock.mock.calls.filter(([, options]) => options?.method === "POST"),
      ).toHaveLength(0);
    } finally {
      view.unmount();
      vi.stubGlobal("EventSource", original);
    }
  });
  it("queues only an explicit fixed fixture action and labels real static receipts honestly in KO/EN", async () => {
    history.replaceState({}, "", "/app/task");
    const mock = privateFetch(200, {
      runs: [
        {
          core_task_id: "core-fixture",
          generation: 1,
          phase: "RECEIVED",
          receipt: {
            kind: "completed",
            scope: "FIXTURE_STATIC_ONLY",
            live_model: "NOTRUN",
            os_sandbox: "UNVERIFIED",
            core_state: "UNVERIFIED",
            steps: [
              {
                step_id: "candidate",
                status: "SUCCEEDED",
                result: { status: "SUCCEEDED" },
              },
            ],
          },
        },
      ],
    });
    const base = mock.getMockImplementation()!;
    mock.mockImplementation(async (input, options) => {
      if (String(input).endsWith("/connections"))
        return new Response(
          JSON.stringify({
            ...demoConnections,
            fixture_execution: "AUTHORIZED",
          }),
        );
      if (String(input).endsWith("/run-fixture"))
        return new Response(
          JSON.stringify({ id: "task-fixture", state: "QUEUED" }),
        );
      return base(input, options);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "Core runs & receipts" });
    expect(
      screen.getByText(/Static checks verify candidate bytes/),
    ).toBeVisible();
    const posts = () =>
      mock.mock.calls.filter(([, options]) => options?.method === "POST");
    expect(posts()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("heading", { name: "Core runs & receipts" });
    expect(posts()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Run fixed fixture" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0][1]?.body).toBe("{}");
    expect(String(posts()[0][0])).toMatch(
      /\/tasks\/task-fixture\/run-fixture$/,
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch to Korean" }));
    expect(
      await screen.findByRole("heading", { name: "Core 실행·수신 기록" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "고정 fixture 실행" }),
    ).toBeVisible();
  });
  it("keeps fixture execution disabled without operator capability", async () => {
    history.replaceState({}, "", "/app/task");
    privateFetch();
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Run fixed fixture" }),
    ).toBeDisabled();
  });
  it("never queues fixtures from the public synthetic demo", async () => {
    history.replaceState({}, "", "/demo/task?task=sample-review");
    const mock = vi.spyOn(globalThis, "fetch");
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Run fixed fixture" }),
    ).toBeDisabled();
    expect(mock).not.toHaveBeenCalled();
  });
  it("receipt checks and refresh never submit approval; only explicit retry resends the immutable intent", async () => {
    history.replaceState({}, "", "/app/approvals");
    const mock = privateFetch(200, {
      state: "READY_FOR_APPROVAL",
      evidence_verified: true,
      candidate_digest: "a".repeat(64),
      evidence_digest: "c".repeat(64),
    });
    const base = mock.getMockImplementation()!;
    let posts = 0;
    mock.mockImplementation(async (input, options) => {
      if (String(input).includes("/approval-receipts/"))
        return new Response(JSON.stringify({ found: false }));
      if (String(input).endsWith("/approve")) {
        if (++posts === 1) throw new Error("lost acknowledgement");
        return new Response("{}");
      }
      return base(input, options);
    });
    const requests = () =>
      mock.mock.calls.filter(([path]) => String(path).endsWith("/approve"));
    const refresh = async () => {
      fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
      await screen.findByText(
        "Static evidence is verified. No live model or sandbox claim is implied.",
      );
    };
    const check = async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Check recorded approval receipt" }),
      );
      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(
          "Checking did not submit approval",
        ),
      );
    };
    render(<App />);
    await screen.findByText(
      "Static evidence is verified. No live model or sandbox claim is implied.",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Prepare approval intent" }),
    );
    await check();
    await refresh();
    await check();
    expect(posts).toBe(0);
    expect(
      screen.queryByRole("button", {
        name: "Resend the same approval request",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Record review approval" }),
    );
    await screen.findByRole("alert");
    await check();
    await refresh();
    await check();
    expect(posts).toBe(1);
    const lookups = mock.mock.calls.filter(([path]) =>
      String(path).includes("/approval-receipts/"),
    );
    expect(lookups).toHaveLength(4);
    for (const [, options] of lookups) {
      expect(options?.method).toBeUndefined();
      expect(options?.body).toBeUndefined();
    }
    fireEvent.click(
      screen.getByRole("button", { name: "Resend the same approval request" }),
    );
    await waitFor(() => expect(posts).toBe(2));
    expect(requests()[1][1]?.body).toBe(requests()[0][1]?.body);
    expect(requests()[1][1]?.headers).toEqual(requests()[0][1]?.headers);
  });
  it("retries the same approval payload and key after a later language rerender", async () => {
    history.replaceState({}, "", "/app/approvals");
    let clock = Date.parse("2026-10-10T10:00:00Z");
    vi.spyOn(Date, "now").mockImplementation(() => clock);
    const mock = privateFetch(200, {
      state: "READY_FOR_APPROVAL",
      evidence_verified: true,
      candidate_digest: "a".repeat(64),
      evidence_digest: "c".repeat(64),
    });
    const base = mock.getMockImplementation()!;
    let count = 0;
    mock.mockImplementation(async (input, options) => {
      if (String(input).endsWith("/approve")) {
        if (++count === 1) throw new Error("lost acknowledgement");
        return new Response("{}");
      }
      return base(input, options);
    });
    render(<App />);
    await screen.findByText(
      "Static evidence is verified. No live model or sandbox claim is implied.",
    );
    const prepare = screen.queryByRole("button", {
      name: "Prepare approval intent",
    });
    if (prepare) fireEvent.click(prepare);
    fireEvent.click(
      screen.getByRole("button", { name: "Record review approval" }),
    );
    await screen.findByRole("alert");
    clock += 120000;
    fireEvent.click(screen.getByRole("button", { name: "Switch to Korean" }));
    fireEvent.click(screen.getByRole("button", { name: "영어로 전환" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Resend the same approval request" }),
    );
    await screen.findByRole("status");
    const requests = mock.mock.calls.filter(([path]) =>
      String(path).endsWith("/approve"),
    );
    expect(requests).toHaveLength(2);
    expect(requests[1][1]?.body).toBe(requests[0][1]?.body);
    expect(requests[1][1]?.headers).toEqual(requests[0][1]?.headers);
  });
  it("dismisses the fixed cancellation target on task switching, browser back and forward", async () => {
    history.replaceState(
      {},
      "",
      "/app/task?project=project-fixture&task=task-fixture",
    );
    const mock = privateFetch();
    const base = mock.getMockImplementation()!;
    mock.mockImplementation(async (input, options) => {
      if (String(input).endsWith("/tasks/task-b")) {
        const response = await base(
          "/api/projects/project-fixture/tasks/task-fixture",
          options,
        );
        return new Response(
          JSON.stringify({
            ...(await response.json()),
            id: "task-b",
            title: "Second private task",
          }),
        );
      }
      return base(input, options);
    });
    render(<App />);
    await screen.findByRole("heading", {
      name: "<img src=x onerror=alert(1)>",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Request cancellation" }),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("task-fixture");
    history.pushState({}, "", "/app/task?project=project-fixture&task=task-b");
    fireEvent(window, new PopStateEvent("popstate"));
    await screen.findByRole("heading", { name: "Second private task" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Request cancellation" }),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("task-b");
    act(() => history.back());
    await screen.findByRole("heading", {
      name: "<img src=x onerror=alert(1)>",
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    act(() => history.forward());
    await screen.findByRole("heading", { name: "Second private task" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      mock.mock.calls.filter(([path]) => String(path).endsWith("/cancel")),
    ).toHaveLength(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Request cancellation" }),
    );
    const confirm = screen.getByRole("button", {
      name: "Confirm cancellation",
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await screen.findByRole("status");
    expect(
      mock.mock.calls.filter(([path]) => String(path).endsWith("/cancel")),
    ).toHaveLength(1);
    expect(
      mock.mock.calls.find(([path]) => String(path).endsWith("/cancel"))?.[0],
    ).toContain("/tasks/task-b/cancel");
  });
  it("rejects a cancellation target changed in history before React handles navigation", async () => {
    history.replaceState({}, "", "/app/task");
    const mock = privateFetch();
    render(<App />);
    await screen.findByRole("heading", {
      name: "<img src=x onerror=alert(1)>",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Request cancellation" }),
    );
    history.pushState({}, "", "/app/task?task=other-task");
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm cancellation" }),
    );
    expect(
      mock.mock.calls.filter(([path]) => String(path).endsWith("/cancel")),
    ).toHaveLength(0);
  });
  it.each([200, 404])(
    "ignores delayed private read status %i after logout",
    async (status) => {
      history.replaceState({}, "", "/app/task");
      const mock = privateFetch();
      const base = mock.getMockImplementation()!;
      render(<App />);
      await screen.findByRole("heading", {
        name: "<img src=x onerror=alert(1)>",
      });
      let release!: () => void;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      let pendingReads = 0;
      mock.mockImplementation(async (input, options) => {
        if (String(input).startsWith("/api/projects/") && !options?.method) {
          pendingReads += 1;
          await gate;
          if (status !== 200)
            return new Response(
              JSON.stringify({ error: "project_not_found" }),
              { status },
            );
        }
        return base(input, options);
      });
      fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
      await waitFor(() => expect(pendingReads).toBeGreaterThanOrEqual(4));
      fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "You have signed out",
      );
      await act(async () => {
        release();
        await gate;
      });
      await waitFor(() =>
        expect(screen.queryByText("Fixture user")).not.toBeInTheDocument(),
      );
      expect(
        screen.queryByText("<img src=x onerror=alert(1)>"),
      ).not.toBeInTheDocument();
      expect(screen.queryByText("Atlas workspace")).not.toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent(
        "You have signed out",
      );
    },
  );
  it.each([200, 404])(
    "ignores delayed mutation status %i after logout",
    async (status) => {
      history.replaceState({}, "", "/app/task");
      const mock = privateFetch();
      const base = mock.getMockImplementation()!;
      let release!: (response: Response) => void;
      const pendingResponse = new Promise<Response>((resolve) => {
        release = resolve;
      });
      mock.mockImplementation(async (input, options) =>
        String(input).endsWith("/cancel")
          ? pendingResponse
          : base(input, options),
      );
      render(<App />);
      await screen.findByRole("heading", {
        name: "<img src=x onerror=alert(1)>",
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Request cancellation" }),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Confirm cancellation" }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "You have signed out",
      );
      await act(async () => {
        release(
          new Response(
            JSON.stringify(
              status === 200
                ? { state: "CANCEL_REQUESTED" }
                : { error: "project_not_found" },
            ),
            { status },
          ),
        );
        await pendingResponse;
      });
      expect(screen.getByRole("alert")).toHaveTextContent(
        "You have signed out",
      );
      expect(
        screen.queryByText("<img src=x onerror=alert(1)>"),
      ).not.toBeInTheDocument();
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    },
  );
  it("freezes approval payload/key through lost response, rerenders, refresh and expiry; new intent is explicit", async () => {
    history.replaceState({}, "", "/app/approvals");
    let clock = Date.parse("2026-10-10T10:00:00Z");
    vi.spyOn(Date, "now").mockImplementation(() => clock);
    const mock = privateFetch(200, {
      state: "READY_FOR_APPROVAL",
      evidence_verified: true,
      candidate_digest: "a".repeat(64),
      evidence_digest: "c".repeat(64),
    });
    const base = mock.getMockImplementation()!;
    let approvals = 0;
    mock.mockImplementation(async (input, options) => {
      if (String(input).endsWith("/approve")) {
        approvals += 1;
        if (approvals === 1) throw new Error("lost acknowledgement");
        return new Response(JSON.stringify({ review_grant_recorded: true }));
      }
      if (String(input).includes("/approval-receipts/"))
        return new Response(JSON.stringify({ found: true }));
      return base(input, options);
    });
    render(<App />);
    await screen.findByText(
      "Static evidence is verified. No live model or sandbox claim is implied.",
    );
    expect(
      screen.getByRole("button", { name: "Record review approval" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Prepare approval intent" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Record review approval" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Connection interrupted",
    );
    clock += 120000;
    fireEvent.click(screen.getByRole("button", { name: "Switch to Korean" }));
    expect(
      screen.getByRole("button", { name: "새 승인 요청 준비" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "영어로 전환" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText(
      "Static evidence is verified. No live model or sandbox claim is implied.",
    );
    clock += 600000;
    fireEvent.click(screen.getByRole("button", { name: "Switch to Korean" }));
    expect(
      screen.getByRole("button", { name: "동일 승인 요청 다시 전송" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "영어로 전환" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Check recorded approval receipt" }),
    );
    await screen.findByRole("status");
    const requests = () =>
      mock.mock.calls.filter(([path]) => String(path).endsWith("/approve"));
    expect(requests()).toHaveLength(1);
    const lookups = mock.mock.calls.filter(([path]) =>
      String(path).includes("/approval-receipts/"),
    );
    expect(lookups).toHaveLength(1);
    expect(lookups[0][1]?.method).toBeUndefined();
    fireEvent.click(
      screen.getByRole("button", { name: "Prepare new approval intent" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Record review approval" }),
    );
    await waitFor(() => expect(approvals).toBe(2));
    expect(requests()[1][1]?.body).not.toBe(requests()[0][1]?.body);
    expect(
      (requests()[1][1]?.headers as Record<string, string>)["Idempotency-Key"],
    ).not.toBe(
      (requests()[0][1]?.headers as Record<string, string>)["Idempotency-Key"],
    );
  });
  it("keeps a mutation key after lost acknowledgement and releases it for the next confirmed intent", async () => {
    history.replaceState({}, "", "/app/task");
    const mock = privateFetch();
    const base = mock.getMockImplementation()!;
    let cancellationCalls = 0;
    mock.mockImplementation(async (input, options) => {
      if (String(input).endsWith("/cancel")) {
        cancellationCalls += 1;
        if (cancellationCalls === 1) throw new Error("lost acknowledgement");
        return new Response(JSON.stringify({ state: "CANCEL_REQUESTED" }), {
          status: 200,
        });
      }
      return base(input, options);
    });
    render(<App />);
    await screen.findByRole("heading", {
      name: "<img src=x onerror=alert(1)>",
    });
    const confirmCancellation = () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Request cancellation" }),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Confirm cancellation" }),
      );
    };
    confirmCancellation();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Connection interrupted",
    );
    confirmCancellation();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Termination has not been confirmed",
    );
    confirmCancellation();
    await waitFor(() => expect(cancellationCalls).toBe(3));
    const requests = mock.mock.calls.filter(([path]) =>
      String(path).endsWith("/cancel"),
    );
    const key = (index: number) =>
      (requests[index][1]?.headers as Record<string, string>)[
        "Idempotency-Key"
      ];
    expect(key(0)).toBe(key(1));
    expect(key(2)).not.toBe(key(1));
  });
  it.each(["cancel", "run-approved-fixture"])(
    "creates a new %s intent after a lost acknowledgement, SSE and recovery",
    async (operation) => {
      const mock = approvedVendor();
      const base = mock.getMockImplementation()!;
      let currentTask: Task = {
        ...demoTasks[0],
        id: "task-fixture",
        project_id: "project-fixture",
        source: "test-fixture",
        generation: 1,
        title: "Generation-bound fixture",
        approval: {
          candidate_digest: "a".repeat(64),
          evidence_digest: "b".repeat(64),
          policy_digest: "c".repeat(64),
          generation: 1,
          destination_id: "private-review",
          expires_at: Math.floor(Date.now() / 1000) + 300,
        },
        vendor_runs: [],
      };
      let calls = 0;
      const streams: Stream[] = [];
      class Stream {
        onerror = null;
        close = vi.fn();
        snapshot?: (event: MessageEvent) => void;
        constructor() {
          streams.push(this);
        }
        addEventListener(
          _name: string,
          handler: (event: MessageEvent) => void,
        ) {
          this.snapshot = handler;
        }
      }
      const original = globalThis.EventSource;
      vi.stubGlobal("EventSource", Stream);
      mock.mockImplementation(async (input, options) => {
        const path = String(input);
        if (path.endsWith("/tasks/task-fixture"))
          return new Response(JSON.stringify(currentTask));
        if (path.endsWith("/" + operation)) {
          calls += 1;
          currentTask = {
            ...currentTask,
            state: operation === "cancel" ? "CANCELLED" : "VENDOR_QUEUED",
          };
          if (calls === 1) throw new Error("lost acknowledgement after commit");
          return new Response(
            JSON.stringify({ id: currentTask.id, state: currentTask.state }),
          );
        }
        if (path.endsWith("/cancel")) {
          currentTask = { ...currentTask, state: "CANCELLED" };
          return new Response(
            JSON.stringify({ id: currentTask.id, state: "CANCELLED" }),
          );
        }
        if (path.endsWith("/recover")) {
          currentTask = {
            ...currentTask,
            generation: 2,
            state: "READY_FOR_APPROVAL",
            approval: { ...currentTask.approval!, generation: 2 },
          };
          return new Response(
            JSON.stringify({
              id: currentTask.id,
              generation: 2,
              state: "BLOCKED",
            }),
          );
        }
        return base(input, options);
      });
      const view = render(<App />);
      const cancel = () => {
        fireEvent.click(
          screen.getByRole("button", { name: "Request cancellation" }),
        );
        fireEvent.click(
          screen.getByRole("button", { name: "Confirm cancellation" }),
        );
      };
      try {
        await screen.findByRole("heading", { name: currentTask.title });
        await waitFor(() =>
          expect(
            screen.getByRole("button", {
              name: "Run approved synthetic vendor",
            }),
          ).toBeEnabled(),
        );
        if (operation === "cancel") cancel();
        else
          fireEvent.click(
            screen.getByRole("button", {
              name: "Run approved synthetic vendor",
            }),
          );
        expect(await screen.findByRole("alert")).toHaveTextContent(
          "Connection interrupted",
        );
        const streamCount = streams.length;
        fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
        await waitFor(() =>
          expect(streams.length).toBeGreaterThan(streamCount),
        );
        await act(async () =>
          streams.at(-1)?.snapshot?.(
            new MessageEvent("snapshot", {
              data: JSON.stringify(currentTask),
            }),
          ),
        );
        if (operation !== "cancel") {
          cancel();
          await waitFor(() =>
            expect(
              screen.getByRole("button", { name: "Request cancellation" }),
            ).toBeDisabled(),
          );
        }
        fireEvent.click(
          screen.getByRole("link", { name: /^Approval & recovery/ }),
        );
        const recover = await screen.findByRole("button", {
          name: "Prepare recovery",
        });
        await waitFor(() => expect(recover).toBeEnabled());
        fireEvent.click(recover);
        await waitFor(() => expect(currentTask.generation).toBe(2));
        fireEvent.click(screen.getByRole("link", { name: /^Task & steps$/ }));
        const next = await screen.findByRole("button", {
          name:
            operation === "cancel"
              ? "Request cancellation"
              : "Run approved synthetic vendor",
        });
        await waitFor(() => expect(next).toBeEnabled());
        if (operation === "cancel") cancel();
        else fireEvent.click(next);
        await waitFor(() => expect(calls).toBe(2));
        const requests = mock.mock.calls.filter(
          ([path, options]) =>
            String(path).endsWith("/" + operation) &&
            options?.method === "POST",
        );
        const keys = requests.map(
          ([, options]) =>
            (options?.headers as Record<string, string>)["Idempotency-Key"],
        );
        expect(keys).toHaveLength(2);
        expect(keys[1]).not.toBe(keys[0]);
        expect(requests.every(([, options]) => options?.body === "{}")).toBe(
          true,
        );
      } finally {
        view.unmount();
        vi.stubGlobal("EventSource", original);
      }
    },
  );
  it("reauthorizes finite stream reconnects and clears revoked content without a manual refresh", async () => {
    history.replaceState({}, "", "/app/task");
    const mock = privateFetch();
    const original = globalThis.EventSource;
    const streams: Stream[] = [];
    class Stream {
      onerror: (() => void) | null = null;
      close = vi.fn();
      constructor() {
        streams.push(this);
      }
      addEventListener() {}
    }
    vi.stubGlobal("EventSource", Stream);
    const view = render(<App />);
    try {
      await screen.findByRole("heading", {
        name: "<img src=x onerror=alert(1)>",
      });
      vi.useFakeTimers();
      await act(async () => {
        streams[0].onerror?.();
      });
      expect(streams[0].close).toHaveBeenCalled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(streams).toHaveLength(2);
      mock.mockImplementation(
        async () =>
          new Response(JSON.stringify({ error: "project_not_found" }), {
            status: 404,
          }),
      );
      await act(async () => {
        streams[1].onerror?.();
      });
      expect(
        screen.queryByText("<img src=x onerror=alert(1)>"),
      ).not.toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent(
        "permissions may have changed",
      );
      view.unmount();
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      view.unmount();
      vi.useRealTimers();
      vi.stubGlobal("EventSource", original);
    }
  });
  it("never falls back to demo data after authentication failure", async () => {
    history.replaceState({}, "", "/app");
    privateFetch(401);
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your session expired",
    );
    expect(
      screen.getByRole("link", { name: /Sign in securely/ }),
    ).toHaveAttribute("href", "/auth/login");
    expect(
      screen.queryByText("Clarify the configuration defaults"),
    ).not.toBeInTheDocument();
  });
  it("renders untrusted task titles as text, requires cancel confirmation and avoids fake success", async () => {
    history.replaceState({}, "", "/app/task");
    const mock = privateFetch();
    render(<App />);
    expect(
      await screen.findByRole("heading", {
        name: "<img src=x onerror=alert(1)>",
      }),
    ).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Request cancellation" }),
    );
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(
      mock.mock.calls.filter(([, o]) => o?.method === "POST"),
    ).toHaveLength(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm cancellation" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Termination has not been confirmed",
    );
    const mutations = mock.mock.calls.filter(([p]) =>
      String(p).endsWith("/cancel"),
    );
    expect(mutations).toHaveLength(1);
    expect(mutations[0][1]?.headers).toMatchObject({
      "X-CSRF-Token": "test-csrf",
    });
  });
  it("clears private content on revoked project access and reconnect failure", async () => {
    history.replaceState({}, "", "/app");
    const mock = privateFetch();
    render(<App />);
    await screen.findByText("<img src=x onerror=alert(1)>");
    mock.mockResolvedValue(
      new Response(JSON.stringify({ error: "project_not_found" }), {
        status: 404,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() =>
      expect(
        screen.queryByText("<img src=x onerror=alert(1)>"),
      ).not.toBeInTheDocument(),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "permissions may have changed",
    );
  });
});

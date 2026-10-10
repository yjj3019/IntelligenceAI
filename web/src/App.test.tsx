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

function privateFetch(status = 200) {
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

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { LocaleProvider } from "./i18n";
import { PCPanel } from "./PCPanel";

const props = {
  projectId: "private",
  csrf: "fixture",
  onAuthorityLost: vi.fn(),
};
const device = {
  id: "device",
  provider: "codex",
  state: "PENDING",
  expires_at: Math.floor(Date.now() / 1000) + 300,
  manifest_digest: "a".repeat(64),
  manifest: {
    version: "SYNTHETIC",
    scope: "FAKE_CLI_TEST_ONLY",
    binary_digest: "b".repeat(64),
    runtime_digest: "c".repeat(64),
  },
};
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const panel = (value = props) => (
  <LocaleProvider>
    <PCPanel {...value} />
  </LocaleProvider>
);
beforeEach(() => {
  vi.restoreAllMocks();
  props.onAuthorityLost.mockClear();
  localStorage.clear();
});

it("mount and refresh only read; owner must review the manifest before confirming", async () => {
  const fetcher = vi.fn().mockResolvedValue(response([device]));
  vi.stubGlobal("fetch", fetcher);
  render(panel());
  const approve = await screen.findByRole("button", {
    name: "Approve this PC",
  });
  expect(approve).toBeDisabled();
  expect(fetcher.mock.calls.every((call) => !call[1]?.method)).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fetcher
    .mockResolvedValueOnce(response({ state: "ACTIVE" }))
    .mockResolvedValue(response([{ ...device, state: "ACTIVE" }]));
  fireEvent.click(approve);
  fireEvent.click(approve);
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter((call) => call[1]?.method === "POST"),
    ).toHaveLength(1),
  );
  const request = fetcher.mock.calls.find(
    (call) => call[1]?.method === "POST",
  )!;
  expect(JSON.parse(request[1].body)).toEqual({
    manifest_digest: device.manifest_digest,
  });
  expect(request[1].headers["X-CSRF-Token"]).toBe("fixture");
  expect(request[1].headers["Idempotency-Key"]).toBeTruthy();
});

it("pairing code remains in component memory and disappears on navigation", async () => {
  const code = "s".repeat(43);
  const fetcher = vi.fn().mockResolvedValue(response([]));
  vi.stubGlobal("fetch", fetcher);
  const view = render(panel());
  await waitFor(() => expect(fetcher).toHaveBeenCalled());
  fetcher
    .mockResolvedValueOnce(response({ pairing_code: code }))
    .mockResolvedValue(response([]));
  fireEvent.click(
    screen.getByRole("button", { name: "Create one-time pairing code" }),
  );
  await screen.findByText(code);
  expect(localStorage.length).toBe(0);
  expect(location.href).not.toContain(code);
  view.unmount();
  render(panel());
  expect(screen.queryByText(code)).not.toBeInTheDocument();
});

it("disconnect is explicit and explains best effort cancellation", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(response([{ ...device, state: "ACTIVE" }]));
  vi.stubGlobal("fetch", fetcher);
  render(panel());
  fireEvent.click(
    await screen.findByRole("button", { name: "Review disconnect" }),
  );
  expect(fetcher.mock.calls.every((call) => !call[1]?.method)).toBe(true);
  expect(
    screen.getByText(/already authorized call stops best effort/),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Keep connected" }));
  expect(
    screen.queryByRole("button", { name: "Disconnect this PC" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Review disconnect" }));
  fetcher
    .mockResolvedValueOnce(response({ state: "REVOKED" }))
    .mockResolvedValue(response([]));
  fireEvent.click(screen.getByRole("button", { name: "Disconnect this PC" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some((call) => String(call[0]).endsWith("/revoke")),
    ).toBe(true),
  );
});

it("permission revocation clears private device data and code", async () => {
  const fetcher = vi.fn().mockResolvedValue(response([device]));
  vi.stubGlobal("fetch", fetcher);
  render(panel());
  await screen.findByText("device");
  fetcher.mockResolvedValueOnce(response({ error: "pc_inactive" }, 403));
  fireEvent.click(screen.getByRole("button", { name: "Refresh devices" }));
  await waitFor(() => expect(props.onAuthorityLost).toHaveBeenCalledWith(403));
  expect(screen.queryByText("device")).not.toBeInTheDocument();
});

it("late responses from an unmounted project cannot reveal its pairing code", async () => {
  let resolve!: (value: Response) => void;
  const fetcher = vi.fn().mockResolvedValue(response([]));
  vi.stubGlobal("fetch", fetcher);
  const view = render(panel());
  await waitFor(() => expect(fetcher).toHaveBeenCalled());
  fetcher.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Create one-time pairing code" }),
  );
  view.unmount();
  render(panel({ ...props, projectId: "other" }));
  await act(async () =>
    resolve(response({ pairing_code: "old-private-code" })),
  );
  expect(screen.queryByText("old-private-code")).not.toBeInTheDocument();
});

it("Korean device actions are readable and expired proposals cannot be approved", async () => {
  localStorage.setItem("iai.language", "ko");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response([{ ...device, expires_at: 1 }])),
  );
  render(panel());
  await screen.findByRole("heading", { name: "내 PC 연결" });
  fireEvent.click(await screen.findByRole("checkbox"));
  expect(screen.getByRole("button", { name: "이 PC 승인" })).toBeDisabled();
});

it.each([
  ["initial", "confirm"],
  ["initial", "revoke"],
  ["manual", "confirm"],
  ["manual", "revoke"],
])(
  "late %s GET cannot undo %s and its latest saved status",
  async (mode, action) => {
    let resolve!: (value: Response) => void;
    let reads = 0;
    let state = action === "confirm" ? "PENDING" : "ACTIVE";
    const fetcher = vi.fn().mockImplementation((input, options) => {
      if (options?.method === "POST") {
        if (String(input).endsWith("/confirm")) state = "ACTIVE";
        if (String(input).endsWith("/revoke")) state = "REVOKED";
        return Promise.resolve(response({ state }));
      }
      reads++;
      if (reads === (mode === "initial" ? 1 : 2)) {
        return new Promise<Response>((done) => {
          resolve = done;
        });
      }
      return Promise.resolve(response([{ ...device, state }]));
    });
    vi.stubGlobal("fetch", fetcher);
    render(panel());
    if (mode === "initial") {
      await waitFor(() => expect(reads).toBe(1));
      fireEvent.click(
        screen.getByRole("button", { name: "Create one-time pairing code" }),
      );
    }
    await screen.findByText("device");
    if (mode === "manual") {
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Refresh devices" }),
        ).toBeEnabled(),
      );
      fireEvent.click(screen.getByRole("button", { name: "Refresh devices" }));
      expect(
        screen.getByRole("button", { name: "Refresh devices" }),
      ).toBeDisabled();
    }
    if (action === "confirm") {
      fireEvent.click(screen.getByRole("checkbox"));
      fireEvent.click(screen.getByRole("button", { name: "Approve this PC" }));
    } else {
      fireEvent.click(
        screen.getByRole("button", { name: "Review disconnect" }),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Disconnect this PC" }),
      );
    }
    const finalState = action === "confirm" ? "ACTIVE" : "REVOKED";
    await screen.findByRole("heading", { name: "codex · " + finalState });
    await act(async () =>
      resolve(
        response([
          { ...device, state: action === "confirm" ? "PENDING" : "ACTIVE" },
        ]),
      ),
    );
    expect(
      screen.getByRole("heading", { name: "codex · " + finalState }),
    ).toBeInTheDocument();
    expect(props.onAuthorityLost).not.toHaveBeenCalled();
  },
);

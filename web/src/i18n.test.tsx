import { readFileSync } from "node:fs";
import ts from "typescript";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { catalogs, en, initialLanguage, ko, translate } from "./i18n";

beforeEach(() => {
  localStorage.clear();
  history.replaceState({}, "", "/demo");
});
afterEach(() => vi.restoreAllMocks());
it("has key parity and no untranslated static fallback in JSX or translation calls", () => {
  expect(Object.keys(ko).sort()).toEqual(Object.keys(en).sort());
  const source = readFileSync("src/App.tsx", "utf8");
  const tree = ts.createSourceFile(
    "App.tsx",
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const allowed = new Set([
    "Intelligence",
    "IntelligenceAI",
    "AI",
    "GitHub",
    "private-review",
    "v",
  ]);
  const missing: string[] = [];
  function walk(node: ts.Node) {
    if (ts.isJsxText(node)) {
      const text = node.text.replace(/\s+/g, " ").trim();
      if (/[a-zA-Z]/.test(text) && !allowed.has(text)) missing.push(text);
    }
    if (
      ts.isCallExpression(node) &&
      node.expression.getText(tree) === "t" &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      const key = node.arguments[0].text;
      if (!(key in ko)) missing.push(key);
    }
    if (
      ts.isJsxAttribute(node) &&
      ["aria-label", "placeholder", "title", "text"].includes(
        node.name.getText(tree),
      ) &&
      node.initializer &&
      ts.isStringLiteral(node.initializer)
    )
      missing.push(node.initializer.text);
    ts.forEachChild(node, walk);
  }
  walk(tree);
  expect(missing).toEqual([]);
});
it("falls back to the English catalog while preserving identifiers and model names", () => {
  const original = catalogs.ko["Refresh"];
  delete catalogs.ko["Refresh"];
  expect(translate("ko", "Refresh")).toBe("Refresh");
  catalogs.ko["Refresh"] = original;
  expect(translate("ko", "task-abc123")).toBe("task-abc123");
  expect(translate("ko", "Claude")).toBe("Claude");
});
it("prefers explicit language, defaults from browser language and tolerates blocked storage", () => {
  vi.spyOn(navigator, "language", "get").mockReturnValue("ko-KR");
  expect(initialLanguage()).toBe("ko");
  localStorage.setItem("iai.language", "en");
  expect(initialLanguage()).toBe("en");
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(initialLanguage()).toBe("ko");
});
it("switches all screens, accessible labels and warnings without translating IDs or original diff", async () => {
  localStorage.setItem("iai.language", "en");
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Switch to Korean" }));
  await waitFor(() => expect(document.documentElement.lang).toBe("ko"));
  expect(localStorage.getItem("iai.language")).toBe("ko");
  expect(
    screen.getByText(/모델은 실행되지 않았으며 모든 데모 변경 기능은 비활성/),
  ).toBeVisible();
  expect(screen.getByRole("textbox", { name: "작업 검색" })).toBeVisible();
  fireEvent.click(screen.getByRole("link", { name: /^승인·복구/ }));
  expect(screen.getByRole("button", { name: "검토 승인 기록" })).toBeDisabled();
  expect(
    screen.getByText("승인 차단: 검증된 증거가 필요합니다."),
  ).toBeVisible();
  expect(screen.getByText("private-review")).toBeVisible();
  fireEvent.click(screen.getByRole("link", { name: "후보·검사" }));
  expect(await screen.findByText(/Synthetic illustration only/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "영어로 전환" }));
  expect(
    screen.getByRole("heading", { name: "Candidate & checks" }),
  ).toBeVisible();
});
it("retains language through remount, back navigation and direct links with explicit timezone", async () => {
  localStorage.setItem("iai.language", "ko");
  history.replaceState({}, "", "/demo/audit?task=sample-review");
  const rendered = render(<App />);
  expect(
    await screen.findByRole("heading", { name: "감사 기록" }),
  ).toBeVisible();
  expect(screen.getByText(/시간대:/)).toHaveTextContent(
    Intl.DateTimeFormat().resolvedOptions().timeZone,
  );
  rendered.unmount();
  render(<App />);
  history.replaceState({}, "", "/demo/dashboard");
  fireEvent(window, new PopStateEvent("popstate"));
  expect(
    screen.getByRole("heading", { name: "신중하게 작업을 진행하세요." }),
  ).toBeVisible();
  expect(document.documentElement.lang).toBe("ko");
});
it("localizes queue, supervisor and core step states using the rendered badge keys", () => {
  for (const state of [
    "QUEUED",
    "SUCCEEDED",
    "EXECUTING",
    "CLAIMED",
    "RESERVED",
    "STARTING",
    "RECEIVED",
    "TERMINATED",
    "UNVERIFIED",
  ]) {
    const key = state.replaceAll("_", " ").toLowerCase();
    expect(key in ko).toBe(true);
    expect(translate("en", key)).toBe(key);
    expect(translate("ko", key)).not.toBe(key);
  }
});
it("keeps cancellation meanings equivalent in KO and EN", () => {
  expect(ko["cancel requested"]).toContain("요청");
  expect(ko["cancelled"]).toContain("확인 완료");
  expect(
    ko["Cancellation requested. Termination has not been confirmed."],
  ).toContain("종료는 아직 확인되지 않았습니다");
  expect(
    ko[
      "Recovery invalidates old approvals and increments the generation. Execution remains disabled."
    ],
  ).toContain("기존 승인이 무효화");
});

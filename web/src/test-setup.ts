import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
afterEach(cleanup);
class TestEventSource {
  onerror: (() => void) | null = null;
  addEventListener() {}
  close() {}
}
Object.defineProperty(globalThis, "EventSource", {
  value: TestEventSource,
  configurable: true,
});
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close = function () {
  this.removeAttribute("open");
};

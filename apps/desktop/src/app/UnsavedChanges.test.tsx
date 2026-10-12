// @vitest-environment jsdom
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  UnsavedChangesProvider,
  useNavigationGuard,
  useUnsavedChanges,
} from "./UnsavedChanges";
const windowMock = vi.hoisted(() => ({
  close: undefined as
    undefined | ((event: { preventDefault: () => void }) => void),
  destroy: vi.fn(),
  stop: vi.fn(),
}));
vi.mock("../services/runtime", () => ({ native: true }));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({
    onCloseRequested: async (callback: typeof windowMock.close) => {
      windowMock.close = callback;
      return windowMock.stop;
    },
    destroy: windowMock.destroy,
  }),
}));
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  windowMock.destroy.mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  windowMock.close = undefined;
});
function Editor({ leave }: { leave: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  useUnsavedChanges(text.length > 0, busy);
  const { confirm } = useNavigationGuard();
  return (
    <>
      <input
        aria-label="Draft"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button onClick={() => confirm(leave)}>Leave</button>
      <button onClick={() => setBusy(!busy)}>Toggle save</button>
    </>
  );
}
function setup() {
  const leave = vi.fn();
  render(
    <UnsavedChangesProvider>
      <Editor leave={leave} />
    </UnsavedChangesProvider>,
  );
  fireEvent.change(screen.getByLabelText("Draft"), {
    target: { value: "Keep this text" },
  });
  return leave;
}
it("keeps unsaved text when navigation is cancelled, and requires explicit discard", () => {
  const leave = setup();
  fireEvent.click(screen.getByText("Leave"));
  expect(leave).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Stay in editor"));
  expect((screen.getByLabelText("Draft") as HTMLInputElement).value).toBe(
    "Keep this text",
  );
  fireEvent.click(screen.getByText("Leave"));
  fireEvent.click(screen.getByText("Discard changes and continue"));
  expect(leave).toHaveBeenCalledOnce();
});
it("does not navigate while a save is in flight", () => {
  const leave = setup();
  fireEvent.click(screen.getByText("Toggle save"));
  fireEvent.click(screen.getByText("Leave"));
  fireEvent.click(screen.getByText("Discard changes and continue"));
  expect(leave).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toBeTruthy();
});
it("protects browser unload", () => {
  setup();
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
});
it("prevents native close until discard is confirmed", async () => {
  setup();
  await waitFor(() => expect(windowMock.close).toBeDefined());
  const preventDefault = vi.fn();
  // Fire via a DOM event so React observes the callback inside an act boundary.
  const listener = () => windowMock.close!({ preventDefault });
  window.addEventListener("test-close", listener, { once: true });
  fireEvent(window, new Event("test-close"));
  expect(preventDefault).toHaveBeenCalledOnce();
  expect(windowMock.destroy).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Discard changes and continue"));
  await waitFor(() => expect(windowMock.destroy).toHaveBeenCalledOnce());
});

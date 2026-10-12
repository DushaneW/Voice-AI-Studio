// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useRecoveryDraft } from "./useRecoveryDraft";
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});
const initial = {
  scope: "p.timeline",
  loaded: true,
  dirty: false,
  revision: 2,
  content: { text: "saved" },
  apply: vi.fn(),
  validate: (v: unknown) =>
    !!v && typeof (v as { text: string }).text === "string",
};
it("persists unsaved content across unmount without overwriting the saved document", () => {
  const first = renderHook((p) => useRecoveryDraft(p), {
    initialProps: initial,
  });
  first.rerender({ ...initial, dirty: true, content: { text: "unsaved" } });
  expect(first.result.current.status).toBe("saved");
  first.unmount();
  const apply = vi.fn();
  const second = renderHook(() => useRecoveryDraft({ ...initial, apply }));
  expect(second.result.current.pending?.content.text).toBe("unsaved");
  expect(apply).not.toHaveBeenCalled();
  act(() => second.result.current.recover());
  expect(apply).toHaveBeenCalledWith({ text: "unsaved" });
});
it("keeps the old base revision for the conflict notice", () => {
  localStorage.setItem(
    "nexus.recovery.v1.p.timeline",
    JSON.stringify({
      schema: 1,
      revision: 1,
      content: { text: "old draft" },
      updated: new Date().toISOString(),
    }),
  );
  const { result } = renderHook(() => useRecoveryDraft(initial));
  expect(result.current.pending?.revision).toBe(1);
  act(() => result.current.clear());
  expect(localStorage.getItem("nexus.recovery.v1.p.timeline")).toBeNull();
});
it("reports quota failures without claiming protection", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("quota");
  });
  const { result } = renderHook(() =>
    useRecoveryDraft({ ...initial, dirty: true }),
  );
  expect(result.current.status).toBe("error");
});
it("does not overwrite an unreadable recovery copy", () => {
  localStorage.setItem("nexus.recovery.v1.p.timeline", "invalid");
  const { result } = renderHook(() => useRecoveryDraft(initial));
  expect(result.current.status).toBe("error");
  expect(localStorage.getItem("nexus.recovery.v1.p.timeline")).toBe("invalid");
});

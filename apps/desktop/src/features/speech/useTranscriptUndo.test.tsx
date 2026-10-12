// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useTranscriptUndo } from "./useTranscriptUndo";
it("bounds history and drops redo after an alternate edit", () => {
  const { result } = renderHook(useTranscriptUndo);
  const snapshot = (n: number) => [{ start: 0, end: 1, text: String(n) }];
  act(() => {
    for (let i = 0; i < 60; i++) result.current.record(snapshot(i));
  });
  let previous;
  act(() => {
    for (let i = 0; i < 50; i++)
      previous = result.current.undo(snapshot(60 - i));
  });
  expect(previous).toEqual(snapshot(10));
  expect(result.current.canUndo).toBe(false);
  expect(result.current.canRedo).toBe(true);
  act(() => result.current.record(snapshot(100)));
  expect(result.current.canRedo).toBe(false);
  act(() =>
    result.current.record([
      { start: 0, end: 1, text: "x".repeat(9 * 1024 * 1024) },
    ]),
  );
  expect(result.current.canUndo).toBe(false);
});

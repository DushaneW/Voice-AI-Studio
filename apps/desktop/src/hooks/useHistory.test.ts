// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useHistory } from "./useHistory";

it("supports undo/redo, discards an abandoned branch, and isolates projects", () => {
  const { result } = renderHook(() => useHistory(["original"]));
  act(() => result.current.set(["edited"]));
  act(() => result.current.undo());
  expect(result.current.value).toEqual(["original"]);
  act(() => result.current.redo());
  expect(result.current.value).toEqual(["edited"]);
  act(() => result.current.undo());
  act(() => result.current.set(["different"]));
  expect(result.current.canRedo).toBe(false);
  act(() => result.current.reset(["new project"]));
  expect(result.current.canUndo).toBe(false);
  act(() => result.current.undo());
  expect(result.current.value).toEqual(["new project"]);
});

it("bounds retained snapshots to 100 edits", () => {
  const { result } = renderHook(() => useHistory(0));
  for (let i = 1; i <= 105; i++) act(() => result.current.set(i));
  for (let i = 0; i < 105; i++) act(() => result.current.undo());
  expect(result.current.value).toBe(5);
  expect(result.current.canUndo).toBe(false);
});

import { useCallback, useReducer } from "react";

interface History<T> {
  past: T[];
  present: T;
  future: T[];
}
type Action<T> =
  { type: "edit" | "reset"; value: T } | { type: "undo" | "redo" };
const LIMIT = 100;

function reduce<T>(state: History<T>, action: Action<T>): History<T> {
  switch (action.type) {
    case "reset":
      return { past: [], present: action.value, future: [] };
    case "edit":
      if (Object.is(state.present, action.value)) return state;
      return {
        past: [...state.past, state.present].slice(-LIMIT),
        present: action.value,
        future: [],
      };
    case "undo": {
      const value = state.past.at(-1);
      if (!state.past.length) return state;
      return {
        past: state.past.slice(0, -1),
        present: value as T,
        future: [state.present, ...state.future],
      };
    }
    case "redo":
      if (!state.future.length) return state;
      return {
        past: [...state.past, state.present],
        present: state.future[0],
        future: state.future.slice(1),
      };
  }
}

/** Immutable editor snapshots; loading a project must reset its history. */
export function useHistory<T>(initial: T) {
  const [state, dispatch] = useReducer(reduce<T>, {
    past: [],
    present: initial,
    future: [],
  });
  const set = useCallback((value: T) => dispatch({ type: "edit", value }), []);
  const reset = useCallback(
    (value: T) => dispatch({ type: "reset", value }),
    [],
  );
  const undo = useCallback(() => dispatch({ type: "undo" }), []);
  const redo = useCallback(() => dispatch({ type: "redo" }), []);
  return {
    value: state.present,
    set,
    reset,
    undo,
    redo,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
  };
}

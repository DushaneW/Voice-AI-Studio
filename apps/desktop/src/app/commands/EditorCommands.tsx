import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { Key } from "../i18n";
import type { Command } from "./registry";
function makeStore() {
  const entries = new Map<symbol, Command>(),
    listeners = new Set<() => void>();
  let snapshot: Command[] = [];
  function publish() {
    snapshot = [...entries.values()];
    listeners.forEach((listener) => listener());
  }
  return {
    snapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    register: (key: symbol, command: Command) => {
      entries.set(key, command);
      publish();
      return () => {
        entries.delete(key);
        publish();
      };
    },
  };
}
const Context = createContext(makeStore());
export function EditorCommandsProvider({ children }: { children: ReactNode }) {
  const store = useMemo(makeStore, []);
  return <Context.Provider value={store}>{children}</Context.Provider>;
}
export function useEditorCommands() {
  const store = useContext(Context);
  return useSyncExternalStore(store.subscribe, store.snapshot);
}
export function useEditorAction(
  id: string,
  label: Key,
  enabled: boolean,
  run: () => unknown,
  shortcut?: string,
) {
  const store = useContext(Context),
    key = useRef(Symbol(id)),
    latest = useRef(run);
  latest.current = run;
  useEffect(
    () =>
      store.register(key.current, {
        id,
        label,
        enabled,
        shortcut,
        run: () => {
          if (enabled) void latest.current();
        },
      }),
    [store, id, label, enabled, shortcut],
  );
}
export function useEditorSave(enabled: boolean, save: () => Promise<unknown>) {
  useEditorAction("saveActiveDocument", "save", enabled, save, "mod+s");
}

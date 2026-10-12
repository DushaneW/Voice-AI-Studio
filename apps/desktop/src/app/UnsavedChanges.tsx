import { translator } from "./i18n";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { native } from "../services/runtime";
import { Modal } from "../components/dialogs/Modal";

type Status = { dirty: boolean; busy: boolean };
type Guard = {
  entries: Map<symbol, Status>;
  confirm: (action: () => void) => void;
  setLanguage: (language: "en" | "pl") => void;
};
const fallback: Guard = {
  entries: new Map(),
  confirm: (action) => action(),
  setLanguage: () => {},
};
const Context = createContext<Guard>(fallback);

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const entries = useRef(new Map<symbol, Status>()).current;
  const [pending, setPending] = useState<(() => void) | null>(null);
  const [language, setLanguage] = useState<"en" | "pl">("en");
  const [message, setMessage] = useState(false);
  const blocked = useCallback(
    () => [...entries.values()].some((s) => s.dirty || s.busy),
    [entries],
  );
  const confirm = useCallback(
    (action: () => void) => {
      if (blocked()) {
        setMessage(false);
        setPending(() => action);
      } else action();
    },
    [blocked],
  );
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (blocked()) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    let disposed = false;
    let unlisten: (() => void) | undefined;
    if (native) {
      void import("@tauri-apps/api/window")
        .then(async ({ getCurrentWindow }) => {
          if (disposed) return;
          const win = getCurrentWindow();
          const stop = await win.onCloseRequested((event) => {
            if (blocked()) {
              event.preventDefault();
              confirm(() => {
                void win.destroy().catch(() => setMessage(true));
              });
            }
          });
          if (disposed) stop();
          else unlisten = stop;
        })
        .catch(() => setMessage(true));
    }
    return () => {
      disposed = true;
      unlisten?.();
      window.removeEventListener("beforeunload", beforeUnload);
    };
  }, [blocked, confirm]);
  const value = useMemo(
    () => ({ entries, confirm, setLanguage }),
    [entries, confirm],
  );
  const pl = language === "pl";
  return (
    <Context.Provider value={value}>
      {children}
      {message && (
        <p role="alert">
          {pl
            ? "Poczekaj na zakończenie operacji. Jeśli problem dotyczy zamknięcia okna, zapisz pracę i spróbuj ponownie."
            : "Wait for the operation to finish. If window closing failed, save your work and try again."}
        </p>
      )}
      {pending && (
        <Modal
          closeLabel={translator(language)("close")}
          title={pl ? "Ochrona niezapisanej pracy" : "Unsaved changes"}
          onClose={() => setPending(null)}
        >
          <p>
            {pl
              ? "Pozostań w edytorze, aby zapisać zmiany. Kontynuowanie odrzuci niezapisane zmiany na tym ekranie."
              : "Stay in the editor to save your changes. Continuing discards unsaved changes on this screen."}
          </p>
          <div className="dialog-actions">
            <button autoFocus onClick={() => setPending(null)}>
              {pl ? "Zostań w edytorze" : "Stay in editor"}
            </button>
            <button
              onClick={() => {
                if ([...entries.values()].some((s) => s.busy)) {
                  setMessage(true);
                  return;
                }
                const action = pending;
                setPending(null);
                action();
              }}
            >
              {pl
                ? "Odrzuć zmiany i kontynuuj"
                : "Discard changes and continue"}
            </button>
          </div>
        </Modal>
      )}
    </Context.Provider>
  );
}

export function useNavigationGuard() {
  return useContext(Context);
}

/** Register only editors; clear synchronously before successful save-and-navigate. */
export function useUnsavedChanges(dirty: boolean, busy = false) {
  const { entries } = useContext(Context);
  const id = useRef(Symbol("editor")).current;
  useLayoutEffect(() => {
    entries.set(id, { dirty, busy });
    return () => {
      entries.delete(id);
    };
  }, [entries, id, dirty, busy]);
  return useCallback(() => {
    entries.set(id, { dirty: false, busy: false });
  }, [entries, id]);
}

import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { Key } from "../app/i18n";
export const AutosaveInterval = createContext(0);
export function useAutosave(
  dirty: boolean,
  busy: boolean,
  save: () => Promise<boolean>,
  secondsOverride?: number,
) {
  const configured = useContext(AutosaveInterval);
  const seconds = secondsOverride ?? configured;
  const latest = useRef(save);
  latest.current = save;
  const inFlight = useRef(false),
    mounted = useRef(true);
  const [failed, setFailed] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!dirty) setFailed(false);
  }, [dirty]);
  useEffect(() => {
    if (!seconds || !dirty || busy || failed) return;
    const timer = setTimeout(async () => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const ok = await latest.current();
        if (mounted.current) {
          if (ok) setSavedAt(new Date().toLocaleTimeString());
          else setFailed(true);
        }
      } catch {
        if (mounted.current) setFailed(true);
      } finally {
        inFlight.current = false;
      }
    }, seconds * 1000);
    return () => clearTimeout(timer);
  }, [seconds, dirty, busy, failed]);
  return { failed, savedAt, resume: () => setFailed(false) };
}
export function AutosaveStatus({
  state,
  t,
}: {
  state: ReturnType<typeof useAutosave>;
  t: (key: Key) => string;
}) {
  return state.failed ? (
    <p role="alert">
      {t("autosavePaused")}{" "}
      <button onClick={state.resume}>{t("autosaveResume")}</button>
    </p>
  ) : state.savedAt ? (
    <p role="status">
      {t("autosavedAt")} {state.savedAt}
    </p>
  ) : null;
}

import { useLayoutEffect, useRef, useState } from "react";
interface Draft<T> {
  schema: 1;
  revision: number;
  content: T;
  updated: string;
}
export function useRecoveryDraft<T>({
  scope,
  loaded,
  dirty,
  revision,
  content,
  apply,
  validate,
}: {
  scope: string;
  loaded: boolean;
  dirty: boolean;
  revision: number;
  content: T;
  apply: (content: T) => void;
  validate: (value: unknown) => boolean;
}) {
  const prefix = `nexus.recovery.v1.${scope}`;
  const session = useRef(crypto.randomUUID());
  const ownKey = `${prefix}.${session.current}`;
  const inspected = useRef("");
  const recoveredKey = useRef<string | null>(null);
  const lastWritten = useRef("");
  const [pending, setPending] = useState<Draft<T> | null>(null);
  const [status, setStatus] = useState<"idle" | "saved" | "error">("idle");
  const [blocked, setBlocked] = useState(false);
  useLayoutEffect(() => {
    if (!loaded || inspected.current === prefix) return;
    inspected.current = prefix;
    try {
      const candidates: { key: string; draft: Draft<T> }[] = [];
      for (let index = 0; index < localStorage.length; index++) {
        const key = localStorage.key(index);
        if (!key || (key !== prefix && !key.startsWith(prefix + "."))) continue;
        const raw = localStorage.getItem(key);
        if (!raw || raw.length > 1_048_576) throw new Error("invalid_draft");
        const draft = JSON.parse(raw) as Draft<T>;
        if (
          draft.schema !== 1 ||
          !Number.isInteger(draft.revision) ||
          draft.revision < 0 ||
          !validate(draft.content) ||
          !Number.isFinite(Date.parse(draft.updated))
        )
          throw new Error("invalid_draft");
        candidates.push({ key, draft });
      }
      candidates.sort((a, b) => b.draft.updated.localeCompare(a.draft.updated));
      if (candidates[0]) {
        recoveredKey.current = candidates[0].key;
        setPending(candidates[0].draft);
      }
    } catch {
      setStatus("error");
      setBlocked(true);
    }
  }, [prefix, loaded]);
  useLayoutEffect(() => {
    if (!loaded || !dirty || pending || blocked || inspected.current !== prefix)
      return;
    try {
      const fingerprint = JSON.stringify({ prefix, revision, content });
      if (lastWritten.current === fingerprint) return;
      const raw = JSON.stringify({
        schema: 1,
        revision,
        content,
        updated: new Date().toISOString(),
      });
      if (raw.length > 1_048_576) throw new Error("draft_too_large");
      localStorage.setItem(ownKey, raw);
      lastWritten.current = fingerprint;
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  }, [prefix, ownKey, loaded, dirty, revision, content, pending, blocked]);
  function clear() {
    try {
      localStorage.removeItem(ownKey);
      if (recoveredKey.current) localStorage.removeItem(recoveredKey.current);
      recoveredKey.current = null;
      lastWritten.current = "";
      setPending(null);
      setBlocked(false);
      setStatus("idle");
    } catch {
      setStatus("error");
    }
  }
  function recover() {
    if (!pending) return;
    apply(pending.content);
    setPending(null);
    setBlocked(false);
  }
  return { pending, status, blocked, clear, recover };
}

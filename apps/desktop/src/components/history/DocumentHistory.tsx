import { useUnsavedChanges } from "../../app/UnsavedChanges";
import { useState } from "react";
import { request } from "../../services/runtime";
import type { Key } from "../../app/i18n";
export interface SavedDocument {
  revision: number;
  content: Record<string, unknown>;
}
interface Revision {
  revision: number;
  created: string;
  bytes: number;
}
export function DocumentHistory({
  projectId,
  kind,
  revision,
  disabled,
  t,
  onRestore,
  onError,
  onBusy,
}: {
  projectId: string;
  kind: "timeline" | "audiobook" | "dubbing" | "transcript" | "project";
  revision: number;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
  t: (key: Key) => string;
  onRestore: (value: SavedDocument) => void;
  onError: (error: string) => void;
}) {
  const endpoint =
    kind === "transcript"
      ? `/v1/transcripts/${projectId}`
      : `/v1/projects/${projectId}/documents/${kind}`;
  const [items, setItems] = useState<Revision[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  useUnsavedChanges(false, busy);
  const [open, setOpen] = useState(false);
  async function load(more = false) {
    setBusy(true);
    onBusy(true);
    try {
      const result = await request<{
        items: Revision[];
        next_cursor: number | null;
      }>("POST", `${endpoint}/history`, {
        before: more ? cursor : null,
      });
      setItems((previous) =>
        more ? [...previous, ...result.items] : result.items,
      );
      setCursor(result.next_cursor);
      setOpen(true);
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
      onBusy(false);
    }
  }
  async function restore() {
    setBusy(true);
    onBusy(true);
    try {
      const value = await request<SavedDocument>(
        "POST",
        `${endpoint}/restore`,
        { source_revision: Number(selected), expected_revision: revision },
      );
      onRestore(value);
      setOpen(false);
      setSelected("");
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
      onBusy(false);
    }
  }
  return (
    <section className="panel" aria-label={t("revisionHistory")}>
      <button
        disabled={disabled || busy || revision === 0}
        onClick={() => void load()}
      >
        {t("revisionHistory")}
      </button>
      <p>{t("revisionHistoryHint")}</p>
      {open && (
        <>
          <select
            aria-label={t("revisionHistory")}
            value={selected}
            disabled={disabled || busy}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">{t("choose")}</option>
            {items.map((item) => (
              <option
                key={item.revision}
                value={item.revision}
                disabled={item.revision === revision}
              >
                {item.revision} · {new Date(item.created).toLocaleString()} ·{" "}
                {Math.ceil(item.bytes / 1024)} KB
              </option>
            ))}
          </select>
          <button
            disabled={
              disabled || busy || !selected || Number(selected) === revision
            }
            onClick={() => void restore()}
          >
            {t("restoreRevision")}
          </button>
          {cursor !== null && (
            <button disabled={busy} onClick={() => void load(true)}>
              {t("wfMore")}
            </button>
          )}
        </>
      )}
    </section>
  );
}

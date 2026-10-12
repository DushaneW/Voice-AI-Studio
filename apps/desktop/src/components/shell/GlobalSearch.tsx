import { useEffect, useState } from "react";
import { Modal } from "../dialogs/Modal";
import { request } from "../../services/runtime";
import type { Key } from "../../app/i18n";
export type SearchHit = {
  id: string;
  project_id: string;
  asset_id?: string;
  label: string;
  snippet?: string;
  segment?: number;
};
export type SearchKind = "projects" | "assets" | "transcripts";
type Results = {
  groups: Record<SearchKind, { items: SearchHit[]; more: boolean }>;
};
export function GlobalSearch({
  t,
  onClose,
  onOpen,
}: {
  t: (key: Key) => string;
  onClose: () => void;
  onOpen: (kind: SearchKind, hit: SearchHit) => void;
}) {
  const [query, setQuery] = useState(""),
    [result, setResult] = useState<Results | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(false);
  useEffect(() => {
    let live = true;
    setResult(null);
    setError(false);
    setLoading(query.trim().length >= 2);
    const timer = setTimeout(() => {
      if (query.trim().length < 2) return;
      void request<Results>("POST", "/v1/search", { query: query.trim() })
        .then((value) => {
          if (live) setResult(value);
        })
        .catch(() => {
          if (live) setError(true);
        })
        .finally(() => {
          if (live) setLoading(false);
        });
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query]);
  const kinds: SearchKind[] = ["projects", "assets", "transcripts"];
  const labels: Record<SearchKind, Key> = {
    projects: "projects",
    assets: "media",
    transcripts: "transcription",
  };
  return (
    <Modal title={t("globalSearch")} closeLabel={t("close")} onClose={onClose}>
      <input
        autoFocus
        maxLength={100}
        aria-label={t("globalSearchQuery")}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <p>{t("globalSearchHint")}</p>
      {loading && <p role="status">{t("recordingWorking")}</p>}
      {error && <p role="alert">{t("globalSearchFailed")}</p>}
      {result &&
        kinds.map((kind) => (
          <section key={kind}>
            <h3>{t(labels[kind])}</h3>
            <div className="command-list">
              {result.groups[kind].items.map((hit) => (
                <button
                  key={`${hit.id}-${hit.segment ?? ""}`}
                  onClick={() => {
                    onClose();
                    onOpen(kind, hit);
                  }}
                >
                  <span>
                    {hit.label}
                    {hit.snippet && <small>{hit.snippet}</small>}
                  </span>
                </button>
              ))}
              {!result.groups[kind].items.length && (
                <p>{t("searchNoResults")}</p>
              )}
              {result.groups[kind].more && <p>{t("searchMore")}</p>}
            </div>
          </section>
        ))}
    </Modal>
  );
}

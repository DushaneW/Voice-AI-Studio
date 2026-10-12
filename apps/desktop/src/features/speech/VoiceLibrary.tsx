import {
  type Preset,
  MAX_TRANSFER_BYTES,
  STORAGE,
  readPresets,
  exportPresets,
  importPresets,
  mergePresets,
} from "./presets";
import { useEffect, useRef, useState } from "react";
import { audioUrl, request } from "../../services/runtime";
import { useUnsavedChanges } from "../../app/UnsavedChanges";
import { en, type Key } from "../../app/i18n";
import type { Voice } from "./Speech";
import type { Model } from "../models/Models";
type Status = {
  id: string;
  state: string;
  error: string | null;
  asset_id: string | null;
};
export function VoiceLibrary({
  projectId,
  t,
}: {
  projectId: string;
  t: (key: Key) => string;
}) {
  const [voices, setVoices] = useState<Voice[]>([]),
    [available, setAvailable] = useState(false),
    [loading, setLoading] = useState(true);
  const [query, setQuery] = useState(""),
    [language, setLanguage] = useState(""),
    [favoriteOnly, setFavoriteOnly] = useState(false);
  const [presets, setPresets] = useState<Record<string, Preset>>({}),
    [storageError, setStorageError] = useState(false);
  const [selected, setSelected] = useState(""),
    [text, setText] = useState(""),
    [job, setJob] = useState<Status | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [url, setUrl] = useState("");
  const [transfer, setTransfer] = useState("");
  const [imported, setImported] = useState(false);
  const generation = useRef(0),
    live = useRef(true);
  useUnsavedChanges(text.trim().length > 0, busy);
  useEffect(() => {
    live.current = true;
    try {
      setPresets(readPresets());
    } catch {
      setStorageError(true);
    }
    Promise.all([
      request<Voice[]>("GET", "/v1/voices"),
      request<Model[]>("GET", "/v1/models"),
      request<{ id: string; installed: boolean }[]>("GET", "/v1/engines"),
    ])
      .then(([v, m, e]) => {
        if (!live.current) return;
        setVoices(v);
        setSelected(v[0]?.id ?? "");
        setAvailable(
          m.some((x) => x.id === "kokoro-v1" && x.state === "installed") &&
            e.some((x) => x.id === "kokoro-onnx" && x.installed),
        );
      })
      .catch((cause) => {
        if (live.current) setError(String(cause));
      })
      .finally(() => {
        if (live.current) setLoading(false);
      });
    return () => {
      live.current = false;
      generation.current++;
    };
  }, []);
  useEffect(() => {
    if (
      !job ||
      ["completed", "failed", "cancelled", "interrupted"].includes(job.state)
    )
      return;
    let closed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const value = await request<Status>("GET", `/v1/jobs/${job.id}/status`);
        if (!closed) {
          setJob(value);
          if (
            !["completed", "failed", "cancelled", "interrupted"].includes(
              value.state,
            )
          )
            timer = setTimeout(() => void poll(), 1000);
        }
      } catch (cause) {
        if (!closed) {
          setError(String(cause));
          timer = setTimeout(() => void poll(), 3000);
        }
      }
    };
    void poll();
    return () => {
      closed = true;
      clearTimeout(timer);
    };
  }, [job?.id]);
  useEffect(() => {
    setUrl("");
    let closed = false;
    let owned = "";
    if (job?.state === "completed" && job.asset_id)
      void audioUrl(job.asset_id)
        .then((value) => {
          owned = value;
          if (closed) URL.revokeObjectURL(value);
          else setUrl(value);
        })
        .catch((cause) => {
          if (!closed) setError(String(cause));
        });
    return () => {
      closed = true;
      if (owned) URL.revokeObjectURL(owned);
    };
  }, [job?.state, job?.asset_id]);
  function update(id: string, patch: Partial<Preset>) {
    if (storageError) return;
    const now = new Date().toISOString();
    const next = {
      ...presets,
      [id]: {
        ...(presets[id] ?? {
          favorite: false,
          tags: "",
          speed: 1,
          created: now,
        }),
        ...patch,
        modified: now,
      },
    };
    try {
      const data = JSON.stringify(next);
      if (data.length > 262144) throw new Error("voiceStorageFailed");
      localStorage.setItem(STORAGE, data);
      setPresets(next);
    } catch {
      setStorageError(true);
    }
  }
  const voice = voices.find((v) => v.id === selected),
    preset = presets[selected];
  const active =
    !!job &&
    !["completed", "failed", "cancelled", "interrupted"].includes(job.state);
  const shown = voices.filter(
    (v) =>
      (!language || v.language === language) &&
      (!favoriteOnly || presets[v.id]?.favorite) &&
      `${v.id} ${v.source} ${presets[v.id]?.tags ?? ""}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  );
  async function preview() {
    if (!voice || !text.trim() || !available || !projectId || active) return;
    setBusy(true);
    setError("");
    const current = ++generation.current;
    try {
      const value = await request<{ id: string }>("POST", "/v1/tts", {
        project_id: projectId,
        model_id: "kokoro-v1",
        text: text.trim(),
        voice: voice.id,
        language: voice.language,
        speed: preset?.speed ?? 1,
      });
      if (live.current && current === generation.current) {
        setText("");
        setJob({ id: value.id, state: "queued", asset_id: null, error: null });
      }
    } catch (cause) {
      if (live.current) setError(String(cause));
    } finally {
      if (live.current) setBusy(false);
    }
  }
  return (
    <section>
      <p>{t("voiceLibraryHint")}</p>
      {loading && <p role="status">{t("recordingWorking")}</p>}
      {!loading && !available && <p role="status">{t("voiceEngineMissing")}</p>}
      {error && <p role="alert">{error}</p>}
      {storageError && <p role="alert">{t("voiceStorageFailed")}</p>}
      <div className="toolbar">
        <label>
          {t("voiceSearch")}
          <input value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <label>
          {t("language")}
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
          >
            <option value="">{t("voiceAllLanguages")}</option>
            {[...new Set(voices.map((v) => v.language))].sort().map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={favoriteOnly}
            onChange={(e) => setFavoriteOnly(e.target.checked)}
          />
          {t("voiceFavorites")}
        </label>
      </div>
      <details className="panel">
        <summary>{t("voiceTransfer")}</summary>
        <p>{t("voiceTransferHint")}</p>
        <button
          disabled={storageError}
          onClick={() => {
            setTransfer(exportPresets(presets));
            setImported(false);
          }}
        >
          {t("voiceExport")}
        </button>
        <label>
          {t("voiceImport")}
          <input
            type="file"
            accept=".json,application/json"
            disabled={storageError}
            onChange={async (e) => {
              const file = e.currentTarget.files?.[0];
              e.currentTarget.value = "";
              if (!file) return;
              setImported(false);
              try {
                if (file.size > MAX_TRANSFER_BYTES)
                  throw new Error("voiceImportInvalid");
                const incoming = importPresets(await file.text());
                if (!live.current) return;
                // Re-read current storage after async file access to preserve changes made meanwhile.
                const next = mergePresets(readPresets(), incoming);
                localStorage.setItem(STORAGE, JSON.stringify(next));
                setPresets(next);
                setImported(true);
                setError("");
              } catch {
                if (live.current) setError(t("voiceImportInvalid"));
              }
            }}
          />
        </label>
        {imported && <p role="status">{t("voiceImportDone")}</p>}
        {transfer && (
          <label>
            {t("voiceExportText")}
            <textarea
              rows={8}
              readOnly
              value={transfer}
              onFocus={(e) => e.currentTarget.select()}
            />
          </label>
        )}
      </details>
      <div className="project-grid">
        {shown.map((v) => (
          <article className="panel" key={v.id}>
            <h3>
              {v.id
                .split("_")
                .slice(1)
                .join(" ")
                .replace(/^./, (c) => c.toUpperCase())}
            </h3>
            <code>{v.id}</code>
            <p>
              {v.language} · {v.source} · {t("voiceLocal")}
            </p>
            <button
              disabled={busy || active}
              onClick={() => {
                setSelected(v.id);
                setJob(null);
                setError("");
              }}
              aria-pressed={selected === v.id}
            >
              {t("voiceSelect")}
            </button>
            <button
              disabled={storageError}
              aria-pressed={presets[v.id]?.favorite ?? false}
              aria-label={`${t("voiceFavorite")} ${v.id}`}
              onClick={() =>
                update(v.id, { favorite: !presets[v.id]?.favorite })
              }
            >
              {presets[v.id]?.favorite ? "★" : "☆"}
            </button>
            {presets[v.id]?.tags && <p>{presets[v.id].tags}</p>}
          </article>
        ))}
      </div>
      {!loading && !shown.length && <p>{t("voiceNoMatches")}</p>}
      {voice && (
        <section className="panel">
          <h3>{voice.id}</h3>
          <label>
            {t("voiceTags")}
            <input
              maxLength={160}
              disabled={storageError}
              value={preset?.tags ?? ""}
              onChange={(e) => update(voice.id, { tags: e.target.value })}
            />
          </label>
          <label>
            {t("speed")} {(preset?.speed ?? 1).toFixed(1)}×
            <input
              type="range"
              min="0.5"
              max="2"
              step="0.1"
              disabled={storageError}
              value={preset?.speed ?? 1}
              onChange={(e) =>
                update(voice.id, { speed: Number(e.target.value) })
              }
            />
          </label>
          {preset && (
            <small>
              {t("voicePresetModified")}:{" "}
              {new Date(preset.modified).toLocaleString()}
            </small>
          )}
          <label>
            {t("voiceSampleText")}
            <textarea
              rows={3}
              maxLength={500}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <button
            disabled={
              !available || !projectId || !text.trim() || busy || active
            }
            onClick={() => void preview()}
          >
            {t("voicePreview")}
          </button>
          {!projectId && <p>{t("selectProject")}</p>}
          {job && (
            <p role="status">
              {t("voicePreviewStatus")}:{" "}
              {job.state in en ? t(job.state as Key) : job.state}
              {job.error ? ` · ${job.error}` : ""}
            </p>
          )}
          {active && (
            <button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await request("POST", `/v1/jobs/${job!.id}/cancel`);
                } catch (cause) {
                  setError(String(cause));
                } finally {
                  if (live.current) setBusy(false);
                }
              }}
            >
              {t("cancel")}
            </button>
          )}
          {url && <audio controls src={url} />}
        </section>
      )}
    </section>
  );
}

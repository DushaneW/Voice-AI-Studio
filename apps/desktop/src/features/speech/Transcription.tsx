import { useEditorAction } from "../../app/commands/EditorCommands";
import { SegmentTiming } from "./SegmentTiming";
import { mergeSegment, retimeSegment, splitSegment } from "./transcriptEdit";
import { useTranscriptUndo } from "./useTranscriptUndo";
import { SpeakerTools } from "./SpeakerTools";
import { TranscriptRecovery } from "./TranscriptRecovery";
import { useUnsavedChanges } from "../../app/UnsavedChanges";
import { useEffect, useRef, useState } from "react";
import { request, audioUrl, exportTranscript } from "../../services/runtime";
import type { Asset, Settings } from "../../types/domain";
import type { Key } from "../../app/i18n";
import type { Model } from "../models/Models";
import { asrHint, formatModelSize, pickAsrModel } from "../models/asr";
interface Segment {
  speaker?: string | null;
  start: number;
  end: number;
  text: string;
}
interface Transcript {
  id: string;
  asset_id: string;
  revision: number;
  language: string;
  segments: Segment[];
}
export function Transcription({
  defaults,
  initialAssetId,
  initialTranscriptId,
  initialSegment,
  assets,
  t,
  onError,
  onQueued,
}: {
  defaults?: Settings;
  initialAssetId?: string;
  initialTranscriptId?: string;
  initialSegment?: number;
  assets: Asset[];
  t: (k: Key) => string;
  onError: (e: string) => void;
  onQueued: () => void;
}) {
  const [assetId, setAssetId] = useState(initialAssetId ?? assets[0]?.id ?? "");
  const [items, setItems] = useState<Transcript[]>([]);
  const [transcriptId, setTranscriptId] = useState(initialTranscriptId ?? "");
  const [models, setModels] = useState<Model[]>([]);
  const [modelId, setModelId] = useState(defaults?.transcription_model ?? "");
  const [device, setDevice] = useState(defaults?.transcription_device ?? "cpu");
  const [cuda, setCuda] = useState(false);
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const [page, setPage] = useState(Math.floor((initialSegment ?? 0) / 100));
  const [active, setActive] = useState(initialSegment ?? -1);
  const chosen = pickAsrModel(models, modelId);
  const hint = asrHint(chosen?.id);
  const modelReady =
    chosen?.state === "installed" &&
    chosen.devices.includes(device) &&
    (device === "cpu" || cuda);

  const [language, setLanguage] = useState(
    defaults?.transcription_language ?? "",
  );
  const [dirty, setDirty] = useState(false);
  const [selected, setSelected] = useState<Transcript | null>(null);
  const history = useTranscriptUndo();
  const caret = useRef<{ index: number; position: number } | null>(null);
  function editSegments(segments: Segment[]) {
    if (!selected || saving) return;
    history.record(selected.segments);
    setSelected({ ...selected, segments });
    setDirty(true);
  }
  function structuralEdit(action: () => Segment[]) {
    try {
      editSegments(action());
    } catch (error) {
      onError(String(error));
    }
  }
  useEffect(() => {
    history.clear();
    caret.current = null;
  }, [selected?.id]);
  const [url, setUrl] = useState("");
  const audio = useRef<HTMLAudioElement>(null);
  const subtitleInput = useRef<HTMLInputElement>(null);
  const [saving, setSaving] = useState(false);
  const refreshVersion = useRef(0);
  const clean = useUnsavedChanges(dirty, saving);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      const version = ++refreshVersion.current;
      try {
        const [tr, models, report] = await Promise.all([
          request<Transcript[]>("GET", "/v1/transcripts"),
          request<Model[]>("GET", "/v1/models"),
          request<{ gpu: { cuda_devices?: number } }>("GET", "/v1/diagnostics"),
        ]);
        if (live && version === refreshVersion.current) {
          setItems(tr);
          setModels(
            models.filter((model) => model.engine === "faster-whisper"),
          );
          setCuda((report.gpu.cuda_devices ?? 0) > 0);
        }
      } catch {
        /* Runtime recovery handles disconnects; polling retries. */
      }
      if (live) timer = setTimeout(() => void refresh(), 2000);
    }
    void refresh();
    return () => {
      live = false;
      refreshVersion.current++;
      clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    if (!dirty)
      setSelected(
        items.find((tr) => tr.asset_id === assetId && tr.id === transcriptId) ??
          items.find((tr) => tr.asset_id === assetId) ??
          null,
      );
  }, [items, assetId, dirty, transcriptId]);
  useEffect(() => {
    let live = true,
      objectUrl = "";
    setUrl("");
    const asset = assets.find((a) => a.id === assetId);
    if (asset && asset.size <= 32 * 1048576)
      audioUrl(assetId)
        .then((u) => {
          objectUrl = u;
          if (live) setUrl(u);
          else URL.revokeObjectURL(u);
        })
        .catch(() => {});
    return () => {
      live = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [assetId]);
  async function transcribe() {
    if (!chosen || !modelReady || (language && !/^[a-z]{2,3}$/.test(language)))
      return;
    try {
      await request("POST", "/v1/transcribe", {
        asset_id: assetId,
        language: language || null,
        model_id: chosen?.id,
        device,
      });
      onQueued();
    } catch (e) {
      onError(String(e));
    }
  }
  async function save() {
    if (!selected || saving) return false;
    setSaving(true);
    refreshVersion.current++;
    try {
      const saved = await request<Transcript>(
        "PUT",
        "/v1/transcripts/" + selected.id,
        { revision: selected.revision, segments: selected.segments },
      );
      refreshVersion.current++;
      history.clear();
      setSelected(saved);
      setItems((current) =>
        current.map((tr) => (tr.id === saved.id ? saved : tr)),
      );
      setDirty(false);
      clean();
      return true;
    } catch (e) {
      onError(String(e));
      return false;
    } finally {
      setSaving(false);
    }
  }
  useEditorAction(
    "transcribeActiveAsset",
    "transcribe",
    !!assetId && modelReady && !(language && !/^[a-z]{2,3}$/.test(language)),
    transcribe,
  );
  useEditorAction(
    "importActiveSubtitles",
    "importSubtitles",
    !!assetId && !dirty && !saving,
    () => subtitleInput.current?.click(),
  );
  const matches =
    selected?.segments
      .map((segment, index) => ({ segment, index }))
      .filter(({ segment }) =>
        segment.text.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
      ) ?? [];
  const lastPage = Math.max(0, Math.ceil(matches.length / 100) - 1);
  const shownPage = Math.min(page, lastPage);
  return (
    <>
      <div className="toolbar">
        <label>
          {t("media")}
          <select
            value={assetId}
            disabled={dirty || saving}
            onChange={(e) => {
              setAssetId(e.target.value);
              setTranscriptId("");
              setPage(0);
              setQuery("");
            }}
          >
            <option value="">{t("choose")}</option>
            {assets.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("language")}
          <input
            value={language}
            maxLength={3}
            list="transcription-languages"
            placeholder={t("automatic")}
            pattern="[a-z]{2,3}"
            aria-label={t("languageCode")}
            onChange={(e) => setLanguage(e.target.value.toLowerCase())}
          />
        </label>
        <datalist id="transcription-languages">
          {(chosen?.languages ?? []).map((code) => (
            <option key={code} value={code} />
          ))}
        </datalist>
        <label>
          {t("models")}
          <select
            value={chosen?.id ?? ""}
            onChange={(e) => setModelId(e.target.value)}
          >
            {!models.length && <option value="">{t("installAsrModel")}</option>}
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.name} · {formatModelSize(model.size)} ·{" "}
                {t(
                  model.state === "installed"
                    ? "installedModels"
                    : "modelNotInstalled",
                )}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("inferenceDevice")}
          <select
            value={device}
            onChange={(e) => setDevice(e.target.value as "cpu" | "cuda")}
          >
            <option value="cpu">CPU</option>
            <option
              value="cuda"
              disabled={!cuda || !chosen?.devices.includes("cuda")}
            >
              CUDA
            </option>
          </select>
        </label>
        <button
          className="primary"
          disabled={
            !assetId ||
            !modelReady ||
            !!(language && !/^[a-z]{2,3}$/.test(language))
          }
          onClick={() => void transcribe()}
        >
          {t("transcribe")}
        </button>
      </div>
      {hint && <p>{t(hint)}</p>}
      {!modelReady && <p>{t("installAsrModel")}</p>}
      <p>{t("languageCodeHint")}</p>
      {url && (
        <audio
          ref={audio}
          controls
          src={url}
          onTimeUpdate={() => {
            const time = audio.current?.currentTime ?? 0;
            setActive(
              selected?.segments.findIndex(
                (segment) => segment.start <= time && segment.end > time,
              ) ?? -1,
            );
          }}
        />
      )}
      <div className="toolbar">
        <label>
          {t("importSubtitles")}
          <input
            ref={subtitleInput}
            type="file"
            accept=".srt,.vtt"
            disabled={!assetId || dirty || saving}
            onChange={async (e) => {
              const file = e.currentTarget.files?.[0];
              e.currentTarget.value = "";
              if (!file) return;
              setSaving(true);
              try {
                const format = file.name.toLowerCase().split(".").pop();
                if (
                  file.size > 512 * 1024 ||
                  !["srt", "vtt"].includes(format ?? "")
                )
                  throw new Error("invalid_subtitles");
                const imported = await request<Transcript>(
                  "POST",
                  "/v1/transcripts/import",
                  {
                    asset_id: assetId,
                    request_id: crypto.randomUUID(),
                    text: new TextDecoder("utf-8", { fatal: true }).decode(
                      await file.arrayBuffer(),
                    ),
                    format,
                    language: language || "und",
                  },
                );
                refreshVersion.current++;
                setItems((current) => [
                  imported,
                  ...current.filter((tr) => tr.id !== imported.id),
                ]);
                setTranscriptId(imported.id);
                history.clear();
                setSelected(imported);
                setPage(0);
                setQuery("");
              } catch (cause) {
                onError(String(cause));
              } finally {
                setSaving(false);
              }
            }}
          />
        </label>
        <p>{t("importSubtitlesHint")}</p>
        <label>
          {t("chooseTranscript")}
          <select
            disabled={dirty || saving}
            value={selected?.id ?? ""}
            onChange={(e) => {
              setTranscriptId(e.target.value);
              setPage(0);
            }}
          >
            <option value="">{t("choose")}</option>
            {items
              .filter((tr) => tr.asset_id === assetId)
              .map((tr) => (
                <option key={tr.id} value={tr.id}>
                  {tr.language} · {t("revision")} {tr.revision} ·{" "}
                  {tr.id.slice(0, 8)}
                </option>
              ))}
          </select>
        </label>
      </div>
      {selected ? (
        <>
          <div className="toolbar">
            <h3>
              {t("transcript")} · {selected.language}
            </h3>
            <TranscriptRecovery
              key={selected.id}
              id={selected.id}
              onError={onError}
              onBusy={setSaving}
              restored={(document) => {
                history.clear();
                refreshVersion.current++;
                setSelected({
                  ...selected,
                  revision: document.revision,
                  language: document.content.language as string,
                  segments: document.content.segments as Segment[],
                });
                setDirty(false);
                setPage(0);
                clean();
                setItems((items) =>
                  items.map((item) =>
                    item.id === selected.id
                      ? {
                          ...item,
                          revision: document.revision,
                          language: document.content.language as string,
                          segments: document.content.segments as Segment[],
                        }
                      : item,
                  ),
                );
              }}
              revision={selected.revision}
              segments={selected.segments}
              dirty={dirty}
              saving={saving}
              save={save}
              recover={(segments) => {
                editSegments(segments);
                setPage(0);
              }}
              t={t}
            />
            {(["srt", "vtt", "txt", "json"] as const).map((format) => (
              <button
                key={format}
                disabled={dirty || saving}
                onClick={() =>
                  void exportTranscript(selected.id, format).catch((e) =>
                    onError(String(e)),
                  )
                }
              >
                {format.toUpperCase()}
              </button>
            ))}
            {dirty && (
              <button
                disabled={saving}
                onClick={() => {
                  history.clear();
                  setSelected(
                    items.find((tr) => tr.id === selected.id) ?? null,
                  );
                  setDirty(false);
                }}
              >
                {t("cancel")}
              </button>
            )}
          </div>
          <div className="toolbar">
            <input
              aria-label={t("searchTranscript")}
              placeholder={t("searchTranscript")}
              value={query}
              maxLength={500}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(0);
              }}
            />
            <input
              aria-label={t("replacementText")}
              placeholder={t("replacementText")}
              value={replacement}
              maxLength={500}
              onChange={(e) => setReplacement(e.target.value)}
            />
            <button
              disabled={!query || saving}
              onClick={() => {
                editSegments(
                  selected.segments.map((segment) => ({
                    ...segment,
                    text: segment.text.split(query).join(replacement),
                  })),
                );
              }}
            >
              {t("replaceExact")}
            </button>
            <button
              disabled={shownPage === 0}
              onClick={() => setPage(shownPage - 1)}
            >
              {t("previousPage")}
            </button>
            <span>
              {shownPage + 1} / {lastPage + 1} · {matches.length} {t("segment")}
            </span>
            <button
              disabled={shownPage >= lastPage}
              onClick={() => setPage(shownPage + 1)}
            >
              {t("nextPage")}
            </button>
          </div>
          <p>{t("transcriptEditHint")}</p>
          <div className="toolbar">
            <button
              disabled={saving || !history.canUndo}
              onClick={() => {
                const segments = history.undo(selected.segments);
                if (segments) {
                  setSelected({ ...selected, segments });
                  setDirty(true);
                }
              }}
            >
              {t("undo")}
            </button>
            <button
              disabled={saving || !history.canRedo}
              onClick={() => {
                const segments = history.redo(selected.segments);
                if (segments) {
                  setSelected({ ...selected, segments });
                  setDirty(true);
                }
              }}
            >
              {t("redo")}
            </button>
          </div>
          <SpeakerTools
            segments={selected.segments}
            disabled={saving}
            t={t}
            onChange={(segments) => {
              editSegments(segments);
            }}
          />
          <datalist id="transcript-speakers">
            {[
              ...new Set(
                selected.segments.map((s) => s.speaker).filter(Boolean),
              ),
            ].map((name) => (
              <option key={name} value={name!} />
            ))}
          </datalist>
          <div className="transcript">
            {matches
              .slice(shownPage * 100, (shownPage + 1) * 100)
              .map(({ segment, index }) => (
                <div
                  className={
                    "segment" + (active === index ? " active-segment" : "")
                  }
                  key={index}
                >
                  <button
                    onClick={() => {
                      if (audio.current)
                        audio.current.currentTime = segment.start;
                    }}
                  >
                    {segment.start.toFixed(2)} s
                  </button>
                  <input
                    aria-label={t("speaker") + " " + (index + 1)}
                    placeholder={t("speakerUnassigned")}
                    list="transcript-speakers"
                    maxLength={80}
                    disabled={saving}
                    value={segment.speaker ?? ""}
                    onChange={(e) => {
                      const name = e.target.value.replace(/[\x00-\x1f]/g, "");
                      editSegments(
                        selected.segments.map((s, i) =>
                          i === index ? { ...s, speaker: name || null } : s,
                        ),
                      );
                    }}
                    onBlur={() => {
                      if (
                        segment.speaker &&
                        segment.speaker !== segment.speaker.trim()
                      ) {
                        editSegments(
                          selected.segments.map((s, i) =>
                            i === index
                              ? { ...s, speaker: s.speaker?.trim() || null }
                              : s,
                          ),
                        );
                      }
                    }}
                  />
                  <SegmentTiming
                    key={`${index}:${segment.start}:${segment.end}:${segment.text}`}
                    segment={segment}
                    index={index}
                    disabled={saving}
                    t={t}
                    canMerge={
                      !!selected.segments[index + 1] &&
                      (segment.speaker ?? null) ===
                        (selected.segments[index + 1]?.speaker ?? null)
                    }
                    retime={(start, end) =>
                      structuralEdit(() =>
                        retimeSegment(
                          selected.segments,
                          index,
                          start,
                          end,
                          assets.find((a) => a.id === assetId)?.duration,
                        ),
                      )
                    }
                    split={(at) =>
                      structuralEdit(() =>
                        splitSegment(
                          selected.segments,
                          index,
                          at,
                          caret.current?.index === index
                            ? caret.current.position
                            : -1,
                        ),
                      )
                    }
                    merge={() =>
                      structuralEdit(() =>
                        mergeSegment(selected.segments, index),
                      )
                    }
                  />
                  <textarea
                    disabled={saving}
                    aria-label={t("segment") + " " + (index + 1)}
                    value={segment.text}
                    onSelect={(e) => {
                      caret.current = {
                        index,
                        position: e.currentTarget.selectionStart,
                      };
                    }}
                    onChange={(e) => {
                      editSegments(
                        selected.segments.map((s, i) =>
                          i === index ? { ...s, text: e.target.value } : s,
                        ),
                      );
                    }}
                  />
                </div>
              ))}
          </div>
        </>
      ) : (
        <div className="empty">{t("noTranscript")}</div>
      )}
    </>
  );
}

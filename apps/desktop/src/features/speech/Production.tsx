import { useAutosave, AutosaveStatus } from "../../hooks/useAutosave";
import { useEditorSave } from "../../app/commands/EditorCommands";
import { DocumentHistory } from "../../components/history/DocumentHistory";
import { useRecoveryDraft } from "../../hooks/useRecoveryDraft";
import { RecoveryNotice } from "../../components/recovery/RecoveryNotice";
import { useUnsavedChanges } from "../../app/UnsavedChanges";
import { useEffect, useState } from "react";
import { request } from "../../services/runtime";
import type { Key } from "../../app/i18n";
import type { Voice } from "./Speech";
interface Chapter {
  title: string;
  text: string;
}
interface Transcript {
  id: string;
  project_id: string;
  language: string;
  segments: { text: string }[];
}
export function Production({
  mode,
  projectId,
  t,
  onQueued,
  onError,
}: {
  mode: "audiobook" | "dubbing";
  projectId: string;
  t: (k: Key) => string;
  onQueued: () => void;
  onError: (s: string) => void;
}) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voice, setVoice] = useState("");
  const [chapters, setChapters] = useState<Chapter[]>([
    { title: "1", text: "" },
  ]);
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [transcriptId, setTranscriptId] = useState("");
  const [revision, setRevision] = useState(0);
  const [gap, setGap] = useState(1);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const clean = useUnsavedChanges(dirty, busy);
  const draft = useRecoveryDraft({
    scope: `${projectId}.${mode}`,
    loaded: loaded && !!projectId,
    dirty,
    revision,
    content: { chapters, gap, voice, transcriptId },
    validate: (value) => {
      const d = value as {
        chapters?: Chapter[];
        gap?: number;
        voice?: string;
        transcriptId?: string;
      } | null;
      return (
        !!d &&
        Array.isArray(d.chapters) &&
        d.chapters.length <= 50 &&
        d.chapters.every(
          (c) => c && typeof c.title === "string" && typeof c.text === "string",
        ) &&
        Number.isFinite(d.gap) &&
        typeof d.voice === "string" &&
        typeof d.transcriptId === "string"
      );
    },
    apply: (value) => {
      if (!Array.isArray(value.chapters)) {
        onError("invalid_document");
        return;
      }
      setChapters(value.chapters);
      setGap(value.gap);
      setVoice(value.voice);
      setTranscriptId(value.transcriptId);
      setDirty(true);
    },
  });
  useEffect(() => {
    let live = true;
    setLoaded(false);
    setDirty(false);
    setRevision(0);
    setChapters([{ title: "1", text: "" }]);
    setGap(1);
    setVoice("");
    setTranscriptId("");
    if (projectId) {
      Promise.all([
        request<Voice[]>("GET", "/v1/voices"),
        request<Transcript[]>("GET", "/v1/transcripts"),
        request<{
          revision: number;
          content: {
            chapters?: Chapter[];
            gap?: number;
            voice?: string;
            transcriptId?: string;
          };
        }>("GET", "/v1/projects/" + projectId + "/documents/" + mode),
      ])
        .then(([v, tr, d]) => {
          if (!live) return;
          const available = tr.filter((x) => x.project_id === projectId);
          setVoices(v);
          setTranscripts(available);
          setVoice(d.content.voice ?? v[0]?.id ?? "");
          setTranscriptId(
            available.find((x) => x.id === d.content.transcriptId)?.id ??
              available[0]?.id ??
              "",
          );
          setRevision(d.revision);
          setChapters(d.content.chapters ?? [{ title: "1", text: "" }]);
          setGap(d.content.gap ?? 1);
          setLoaded(true);
        })
        .catch((e) => {
          if (live) onError(String(e));
        });
    }
    return () => {
      live = false;
    };
  }, [projectId, mode]);
  async function save() {
    if (draft.pending) throw new Error("recoverDraft");
    const d = await request<{ revision: number }>(
      "PUT",
      "/v1/projects/" + projectId + "/documents/" + mode,
      { revision, content: { chapters, gap, voice, transcriptId } },
    );
    setRevision(d.revision);
    setDirty(false);
    draft.clear();
  }
  async function persist() {
    if (busy || !loaded || draft.pending) return false;
    setBusy(true);
    try {
      await save();
      clean();
      return true;
    } catch (error) {
      onError(String(error));
      return false;
    } finally {
      setBusy(false);
    }
  }
  useEditorSave(dirty && loaded && !busy && !draft.pending, persist);
  const autosave = useAutosave(
    dirty,
    busy || !loaded || !!draft.pending,
    persist,
  );
  async function generate() {
    if (busy || !loaded || draft.pending) return;
    setBusy(true);
    try {
      await save();
      const common = {
        project_id: projectId,
        voice,
        language: voices.find((v) => v.id === voice)?.language ?? "en-us",
      };
      await request(
        "POST",
        "/v1/" + mode,
        mode === "audiobook"
          ? { ...common, chapters, gap }
          : { ...common, transcript_id: transcriptId },
      );
      clean();
      onQueued();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }
  if (!projectId) return <div className="empty">{t("selectProject")}</div>;
  return (
    <>
      <AutosaveStatus state={autosave} t={t} />
      <RecoveryNotice
        pending={draft.pending}
        status={draft.status}
        revision={revision}
        recover={draft.recover}
        discard={draft.clear}
        t={t}
      />
      {!voices.length && <p role="status">{t("installSpeechModel")}</p>}
      <DocumentHistory
        key={projectId + mode}
        projectId={projectId}
        kind={mode}
        revision={revision}
        disabled={dirty || busy || !loaded || !!draft.pending}
        t={t}
        onError={onError}
        onBusy={setBusy}
        onRestore={(document) => {
          const content = document.content as {
            chapters?: Chapter[];
            gap?: number;
            voice?: string;
            transcriptId?: string;
          };
          setChapters(content.chapters ?? [{ title: "1", text: "" }]);
          setGap(content.gap ?? 1);
          setVoice(content.voice ?? "");
          setTranscriptId(content.transcriptId ?? "");
          setRevision(document.revision);
          setDirty(false);
          draft.clear();
          clean();
        }}
      />
      <p>{t(mode === "dubbing" ? "dubbingNotice" : "audiobookNotice")}</p>
      <div className="toolbar">
        <label>
          {t("voice")}
          <select
            value={voice}
            disabled={busy || !loaded}
            onChange={(e) => {
              setDirty(true);
              setVoice(e.target.value);
            }}
          >
            {voice && !voices.some((v) => v.id === voice) && (
              <option value={voice}>{voice}</option>
            )}
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.id} · {v.language}
              </option>
            ))}
          </select>
        </label>
        {mode === "audiobook" ? (
          <label>
            {t("chapterGap")}
            <input
              type="number"
              value={gap}
              min="0"
              max="10"
              step=".1"
              disabled={busy || !loaded}
              onChange={(e) => {
                setDirty(true);
                setGap(Number(e.target.value));
              }}
            />
          </label>
        ) : (
          <label>
            {t("transcript")}
            <select
              value={transcriptId}
              disabled={busy || !loaded}
              onChange={(e) => {
                setDirty(true);
                setTranscriptId(e.target.value);
              }}
            >
              {transcripts.map((tr) => (
                <option key={tr.id} value={tr.id}>
                  {tr.language} · {tr.segments[0]?.text.slice(0, 45)}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          disabled={busy || !loaded || !dirty || !!draft.pending}
          onClick={async () => {
            if (busy) return;
            setBusy(true);
            try {
              await save();
              clean();
            } catch (e) {
              onError(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {t("save")}
        </button>
        <button
          className="primary"
          disabled={
            busy ||
            !loaded ||
            !voices.some((v) => v.id === voice) ||
            !!draft.pending ||
            (mode === "dubbing"
              ? !transcriptId
              : chapters.some((c) => !c.text.trim() || !c.title.trim()))
          }
          onClick={() => void generate()}
        >
          {t("generateSpeech")}
        </button>
      </div>
      {mode === "audiobook" && (
        <>
          {chapters.map((chapter, index) => (
            <section className="panel model-card" key={index}>
              <div className="toolbar">
                <label>
                  {t("chapterTitle")}
                  <input
                    value={chapter.title}
                    disabled={busy || !loaded}
                    maxLength={120}
                    onChange={(e) => {
                      setDirty(true);
                      setChapters(
                        chapters.map((c, i) =>
                          i === index ? { ...c, title: e.target.value } : c,
                        ),
                      );
                    }}
                  />
                </label>
                <button
                  aria-label={t("moveChapterUp")}
                  disabled={index === 0 || busy || !loaded}
                  onClick={() => {
                    setDirty(true);
                    const next = [...chapters];
                    [next[index - 1], next[index]] = [
                      next[index],
                      next[index - 1],
                    ];
                    setChapters(next);
                  }}
                >
                  ↑
                </button>
                <button
                  aria-label={t("moveChapterDown")}
                  disabled={index === chapters.length - 1 || busy || !loaded}
                  onClick={() => {
                    setDirty(true);
                    const next = [...chapters];
                    [next[index], next[index + 1]] = [
                      next[index + 1],
                      next[index],
                    ];
                    setChapters(next);
                  }}
                >
                  ↓
                </button>
                <button
                  disabled={chapters.length === 1 || busy}
                  onClick={() => {
                    setDirty(true);
                    setChapters(chapters.filter((_, i) => i !== index));
                  }}
                >
                  {t("remove")}
                </button>
              </div>
              <textarea
                aria-label={t("speechText") + " " + (index + 1)}
                disabled={busy || !loaded}
                rows={4}
                maxLength={5000}
                value={chapter.text}
                onChange={(e) => {
                  setDirty(true);
                  setChapters(
                    chapters.map((c, i) =>
                      i === index ? { ...c, text: e.target.value } : c,
                    ),
                  );
                }}
              />
            </section>
          ))}
          <button
            disabled={chapters.length >= 50 || busy}
            onClick={() => {
              setDirty(true);
              setChapters([
                ...chapters,
                { title: String(chapters.length + 1), text: "" },
              ]);
            }}
          >
            {t("addChapter")}
          </button>
        </>
      )}
    </>
  );
}

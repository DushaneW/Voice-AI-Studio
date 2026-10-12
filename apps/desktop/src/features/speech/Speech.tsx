import { useEditorAction } from "../../app/commands/EditorCommands";
import { useUnsavedChanges } from "../../app/UnsavedChanges";
import { useEffect, useState } from "react";
import { request } from "../../services/runtime";
import type { Settings } from "../../types/domain";
import type { Key } from "../../app/i18n";
import type { Model } from "../models/Models";
export interface Voice {
  id: string;
  language: string;
  source: string;
}
export function Speech({
  defaults,
  projectId,
  t,
  onQueued,
  onError,
  voicesOnly = false,
}: {
  defaults?: Settings;
  projectId: string;
  t: (k: Key) => string;
  onQueued: () => void;
  onError: (e: string) => void;
  voicesOnly?: boolean;
}) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voice, setVoice] = useState("");
  const [text, setText] = useState("");
  const [speed, setSpeed] = useState(defaults?.tts_speed ?? 1);
  const [installed, setInstalled] = useState(false);
  const [busy, setBusy] = useState(false);
  const clean = useUnsavedChanges(!voicesOnly && text.length > 0, busy);
  useEffect(() => {
    let alive = true;
    Promise.all([
      request<Voice[]>("GET", "/v1/voices"),
      request<Model[]>("GET", "/v1/models"),
    ])
      .then(([v, m]) => {
        if (alive) {
          setVoices(v);
          setVoice(
            v.some((voice) => voice.id === defaults?.tts_voice)
              ? defaults!.tts_voice!
              : (v[0]?.id ?? ""),
          );
          setInstalled(
            m.some((x) => x.id === "kokoro-v1" && x.state === "installed"),
          );
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  async function generate() {
    setBusy(true);
    try {
      await request("POST", "/v1/tts", {
        project_id: projectId,
        text,
        voice,
        speed,
        language: voices.find((v) => v.id === voice)?.language ?? "en-us",
      });
      setText("");
      clean();
      onQueued();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }
  useEditorAction(
    "generateActiveSpeech",
    "generateSpeech",
    installed &&
      !voicesOnly &&
      !!projectId &&
      !!text.trim() &&
      !!voice &&
      !busy,
    generate,
  );
  if (!installed)
    return (
      <div className="empty">
        <h3>{t("installSpeechModel")}</h3>
        <p>{t("modelInstallHint")}</p>
      </div>
    );
  if (voicesOnly)
    return (
      <div className="project-grid">
        {voices.map((v) => (
          <article className="panel" key={v.id}>
            <h3>{v.id}</h3>
            <p>
              {v.language} · {v.source}
            </p>
          </article>
        ))}
      </div>
    );
  return (
    <section className="panel">
      <label>
        {t("speechText")}
        <textarea
          disabled={busy}
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={5000}
          rows={9}
        />
      </label>
      <div className="toolbar">
        <label>
          {t("voice")}
          <select
            disabled={busy}
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
          >
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.id} · {v.language}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("speed")} {speed.toFixed(1)}×{" "}
          <input
            disabled={busy}
            type="range"
            min=".5"
            max="2"
            step=".1"
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
          />
        </label>
        <button
          className="primary"
          disabled={!projectId || !text.trim() || !voice || busy}
          onClick={() => void generate()}
        >
          {t("generateSpeech")}
        </button>
      </div>
      {!projectId && <p>{t("selectProject")}</p>}
      <small>{text.length} / 5000</small>
    </section>
  );
}

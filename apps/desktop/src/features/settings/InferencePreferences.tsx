import { useEffect, useState } from "react";
import { request } from "../../services/runtime";
import type { Settings } from "../../types/domain";
import type { Model } from "../models/Models";
import type { Voice } from "../speech/Speech";
import type { Key } from "../../app/i18n";

export function InferencePreferences({
  value,
  onChange,
  t,
}: {
  value: Settings;
  onChange: (value: Settings) => void;
  t: (key: Key) => string;
}) {
  const [models, setModels] = useState<Model[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [failed, setFailed] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let live = true;
    Promise.all([
      request<Model[]>("GET", "/v1/models"),
      request<Voice[]>("GET", "/v1/voices"),
    ])
      .then(([catalog, voices]) => {
        if (live) {
          setModels(catalog.filter((m) => m.engine === "faster-whisper"));
          setVoices(voices);
          setFailed(false);
        }
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [refresh]);
  return (
    <section aria-label={t("inferenceDefaults")}>
      <h3>{t("inferenceDefaults")}</h3>
      <p>{t("inferenceDefaultsHint")}</p>
      {failed && (
        <p role="alert">
          {t("unknownError")}{" "}
          <button onClick={() => setRefresh((n) => n + 1)}>{t("retry")}</button>
        </p>
      )}
      <label>
        {t("defaultAsrModel")}
        <select
          value={value.transcription_model ?? ""}
          onChange={(e) =>
            onChange({ ...value, transcription_model: e.target.value || null })
          }
        >
          <option value="">{t("catalogDefault")}</option>
          {value.transcription_model &&
            !models.some((m) => m.id === value.transcription_model) && (
              <option value={value.transcription_model}>
                {value.transcription_model} · {t("unavailable")}
              </option>
            )}
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("defaultAsrLanguage")}
        <input
          maxLength={3}
          pattern="[a-z]{2,3}"
          placeholder={t("automatic")}
          defaultValue={value.transcription_language ?? ""}
          onBlur={(e) => {
            const language = e.target.value.trim().toLowerCase();
            if (!language || /^[a-z]{2,3}$/.test(language))
              onChange({ ...value, transcription_language: language || null });
            else e.target.value = value.transcription_language ?? "";
          }}
        />
      </label>
      <label>
        {t("inferenceDevice")}
        <select
          value={value.transcription_device ?? "cpu"}
          onChange={(e) =>
            onChange({
              ...value,
              transcription_device: e.target.value as "cpu" | "cuda",
            })
          }
        >
          <option value="cpu">CPU</option>
          <option value="cuda">CUDA</option>
        </select>
      </label>
      <p>{t("deviceDefaultHint")}</p>
      <label>
        {t("defaultTtsVoice")}
        <select
          value={value.tts_voice ?? ""}
          onChange={(e) =>
            onChange({ ...value, tts_voice: e.target.value || null })
          }
        >
          <option value="">{t("catalogDefault")}</option>
          {value.tts_voice && !voices.some((v) => v.id === value.tts_voice) && (
            <option value={value.tts_voice}>
              {value.tts_voice} · {t("unavailable")}
            </option>
          )}
          {voices.map((v) => (
            <option key={v.id} value={v.id}>
              {v.id} · {v.language}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("defaultTtsSpeed")} {value.tts_speed ?? 1}×
        <input
          type="range"
          min="0.5"
          max="2"
          step="0.1"
          value={value.tts_speed ?? 1}
          onChange={(e) =>
            onChange({ ...value, tts_speed: Number(e.target.value) })
          }
        />
      </label>
    </section>
  );
}

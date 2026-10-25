import { AudioPreferences } from "./AudioPreferences";
import { InferencePreferences } from "./InferencePreferences";
import { SafetyCenter } from "./SafetyCenter";
import { Storage } from "./Storage";
import type { Settings as Data } from "../../types/domain";
import type { Key } from "../../app/i18n";
export function Settings({
  value,
  onChange,
  t,
}: {
  value: Data;
  onChange: (v: Data) => void;
  t: (k: Key) => string;
}) {
  return (
    <section className="panel preferences">
      <label>
        {t("language")}
        <select
          value={value.language}
          onChange={(e) =>
            onChange({ ...value, language: e.target.value as "en" | "pl" })
          }
        >
          <option value="en">English</option>
          <option value="pl">Polski</option>
        </select>
      </label>
      <label>
        {t("appearance")}
        <select
          value={value.theme ?? "dark"}
          onChange={(e) =>
            onChange({
              ...value,
              theme: e.target.value as "dark" | "light" | "system",
            })
          }
        >
          <option value="dark">{t("darkTheme")}</option>
          <option value="light">{t("lightTheme")}</option>
          <option value="system">{t("systemTheme")}</option>
        </select>
      </label>
      <label>
        {t("motion")}
        <select
          value={value.motion ?? "system"}
          onChange={(e) =>
            onChange({
              ...value,
              motion: e.target.value as "system" | "full" | "reduced",
            })
          }
        >
          <option value="system">{t("motionSystem")}</option>
          <option value="full">{t("motionFull")}</option>
          <option value="reduced">{t("motionReduced")}</option>
        </select>
      </label>
      <label>
        {t("showInspector")}
        <input
          type="checkbox"
          checked={value.inspector}
          onChange={(e) => onChange({ ...value, inspector: e.target.checked })}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={value.model_downloads_allowed ?? true}
          onChange={(e) =>
            onChange({ ...value, model_downloads_allowed: e.target.checked })
          }
        />
        {t("allowModelDownloads")}
      </label>
      <p>{t("networkControlHint")}</p>
      <SafetyCenter t={t} />
      <AudioPreferences value={value} onChange={onChange} t={t} />
      <InferencePreferences value={value} onChange={onChange} t={t} />
      <h3>{t("privacyLocal")}</h3>
      <p>{t("privacyLocalDetail")}</p>
      <label>
        {t("autosaveInterval")}
        <select
          value={value.autosave_seconds ?? 0}
          onChange={(e) =>
            onChange({
              ...value,
              autosave_seconds: Number(e.target.value) as 0 | 5 | 15 | 30 | 60,
            })
          }
        >
          <option value={0}>{t("autosaveOff")}</option>
          {[5, 15, 30, 60].map((seconds) => (
            <option key={seconds} value={seconds}>
              {seconds} s
            </option>
          ))}
        </select>
      </label>
      <h3>{t("recoveryStorage")}</h3>
      <p>{t("recoveryStorageDetail")}</p>
      <label>
        <input
          type="checkbox"
          checked={value.waveform_cache_enabled ?? true}
          onChange={(e) =>
            onChange({ ...value, waveform_cache_enabled: e.target.checked })
          }
        />
        {t("waveformCacheEnabled")}
      </label>
      <label>
        {t("waveformCacheLimit")}
        <select
          value={value.waveform_cache_mb ?? 0}
          onChange={(e) =>
            onChange({
              ...value,
              waveform_cache_mb: Number(e.target.value) as 0 | 128 | 512 | 1024,
            })
          }
        >
          <option value={0}>{t("manualCacheCleanup")}</option>
          {[128, 512, 1024].map((size) => (
            <option key={size} value={size}>
              {size} MiB
            </option>
          ))}
        </select>
      </label>
      <p>{t("cachePolicyHint")}</p>
      <Storage t={t} />
      <h3>{t("shortcuts")}</h3>
      <p>
        {navigator.platform.toLowerCase().includes("mac") ? "⌘" : "Ctrl"} + K —{" "}
        {t("palette")}
      </p>
      <p>
        {navigator.platform.toLowerCase().includes("mac") ? "⌘" : "Ctrl"} + N —{" "}
        {t("newProject")}
      </p>
      <p>
        {navigator.platform.toLowerCase().includes("mac") ? "⌘" : "Ctrl"} + O —{" "}
        {t("projects")}
      </p>
    </section>
  );
}

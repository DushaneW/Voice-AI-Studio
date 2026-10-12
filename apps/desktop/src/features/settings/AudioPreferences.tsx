import type { Settings } from "../../types/domain";
import type { Key } from "../../app/i18n";

export function AudioPreferences({
  value,
  onChange,
  t,
}: {
  value: Settings;
  onChange: (value: Settings) => void;
  t: (key: Key) => string;
}) {
  const options = [
    ["recording_sample_rate", "recordingRate", [24000, 44100, 48000], 48000],
    ["recording_channels", "recordingChannels", [1, 2], 1],
    ["recording_preroll", "recordingPreRoll", [0, 1, 2, 3, 5], 0],
    ["recording_countdown", "recordingCountdown", [0, 3, 5], 0],
  ] as const;
  return (
    <section aria-label={t("audioDefaults")}>
      <h3>{t("audioDefaults")}</h3>
      <p>{t("audioDefaultsHint")}</p>
      {options.map(([key, label, options, fallback]) => (
        <label key={key}>
          {t(label)}
          <select
            value={value[key] ?? fallback}
            onChange={(e) =>
              onChange({ ...value, [key]: Number(e.target.value) })
            }
          >
            {options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
      ))}
      <label>
        {t("recordingGain")} {value.recording_gain ?? 1}×
        <input
          type="range"
          min="0"
          max="4"
          step="0.1"
          value={value.recording_gain ?? 1}
          onChange={(e) =>
            onChange({ ...value, recording_gain: Number(e.target.value) })
          }
        />
      </label>
      <label>
        {t("monitorVolume")} {Math.round((value.playback_volume ?? 1) * 100)}%
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={value.playback_volume ?? 1}
          onChange={(e) =>
            onChange({ ...value, playback_volume: Number(e.target.value) })
          }
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={value.playback_muted ?? false}
          onChange={(e) =>
            onChange({ ...value, playback_muted: e.target.checked })
          }
        />
        {t("monitorMute")}
      </label>
    </section>
  );
}

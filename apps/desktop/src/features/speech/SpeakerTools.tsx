import { useState } from "react";
import type { TranscriptSegment } from "../../types/domain";
import type { Key } from "../../app/i18n";
export function SpeakerTools({
  segments,
  disabled,
  t,
  onChange,
}: {
  segments: TranscriptSegment[];
  disabled: boolean;
  t: (key: Key) => string;
  onChange: (segments: TranscriptSegment[]) => void;
}) {
  const [source, setSource] = useState("");
  const [name, setName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const counts = new Map<string, number>();
  for (const segment of segments)
    if (segment.speaker)
      counts.set(segment.speaker, (counts.get(segment.speaker) ?? 0) + 1);
  const speakers = [...counts.keys()].sort();
  const target = name.trim();
  const merges = speakers.includes(target) && target !== source;
  const valid =
    source &&
    speakers.includes(source) &&
    target &&
    target !== source &&
    !/[\x00-\x1f]/.test(target);
  return (
    <section className="panel">
      <h3>{t("manualSpeakers")}</h3>
      <p>{t("manualSpeakersHint")}</p>
      <p>
        {speakers.map((s) => `${s} (${counts.get(s)})`).join(" · ") ||
          t("speakerUnassigned")}
      </p>
      <label>
        {t("speakerSource")}
        <select
          disabled={disabled}
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            setConfirmed(false);
          }}
        >
          <option value="">{t("choose")}</option>
          {speakers.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <label>
        {t("speakerName")}
        <input
          disabled={disabled}
          maxLength={80}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setConfirmed(false);
          }}
        />
      </label>
      {merges && (
        <label>
          <input
            type="checkbox"
            disabled={disabled}
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          {t("speakerMergeConfirm")}
        </label>
      )}
      <button
        disabled={disabled || !valid || (merges && !confirmed)}
        onClick={() => {
          onChange(
            segments.map((s) =>
              s.speaker === source ? { ...s, speaker: target } : s,
            ),
          );
          setSource(target);
          setName("");
          setConfirmed(false);
        }}
      >
        {t(merges ? "speakerMerge" : "speakerRename")}
      </button>
    </section>
  );
}

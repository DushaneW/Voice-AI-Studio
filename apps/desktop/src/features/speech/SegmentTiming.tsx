import { useState } from "react";
import type { TranscriptSegment } from "../../types/domain";
import type { Key } from "../../app/i18n";
export function SegmentTiming({
  segment,
  index,
  disabled,
  canMerge,
  t,
  retime,
  split,
  merge,
}: {
  segment: TranscriptSegment;
  index: number;
  disabled: boolean;
  canMerge: boolean;
  t: (key: Key) => string;
  retime: (start: number, end: number) => void;
  split: (at: number) => void;
  merge: () => void;
}) {
  const [start, setStart] = useState(String(segment.start));
  const [end, setEnd] = useState(String(segment.end));
  const [at, setAt] = useState(String((segment.start + segment.end) / 2));
  return (
    <div className="segment-timing">
      <label>
        {t("segmentStart")}
        <input
          aria-label={`${t("segmentStart")} ${index + 1}`}
          type="number"
          min="0"
          step="0.01"
          disabled={disabled}
          value={start}
          onChange={(e) => setStart(e.target.value)}
        />
      </label>
      <label>
        {t("segmentEnd")}
        <input
          aria-label={`${t("segmentEnd")} ${index + 1}`}
          type="number"
          min="0"
          step="0.01"
          disabled={disabled}
          value={end}
          onChange={(e) => setEnd(e.target.value)}
        />
      </label>
      <button
        disabled={disabled || !start || !end}
        onClick={() => retime(Number(start), Number(end))}
      >
        {t("applyTiming")}
      </button>
      <label>
        {t("splitAt")}
        <input
          aria-label={`${t("splitAt")} ${index + 1}`}
          type="number"
          step="0.01"
          disabled={disabled}
          value={at}
          onChange={(e) => setAt(e.target.value)}
        />
      </label>
      <button disabled={disabled || !at} onClick={() => split(Number(at))}>
        {t("splitSegment")}
      </button>
      <button disabled={disabled || !canMerge} onClick={merge}>
        {t("mergeNextSegment")}
      </button>
    </div>
  );
}

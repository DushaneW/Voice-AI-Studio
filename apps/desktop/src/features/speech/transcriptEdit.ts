import type { TranscriptSegment } from "../../types/domain";

function valid(segments: TranscriptSegment[], duration?: number) {
  if (segments.length > 10000) throw new Error("invalid_transcript_segments");
  let previous = -1;
  for (const s of segments) {
    if (
      !Number.isFinite(s.start) ||
      !Number.isFinite(s.end) ||
      s.start < 0 ||
      s.end <= s.start ||
      s.start < previous ||
      (duration !== undefined && s.end > duration + 0.05) ||
      s.text.length > 10000
    )
      throw new Error("invalid_transcript_segment");
    previous = s.start;
  }
  return segments;
}
function changed(segment: TranscriptSegment): TranscriptSegment {
  return { ...segment, words: [], word_timestamps_valid: false };
}
export function retimeSegment(
  segments: TranscriptSegment[],
  index: number,
  start: number,
  end: number,
  duration?: number,
) {
  return valid(
    segments.map((s, i) => (i === index ? changed({ ...s, start, end }) : s)),
    duration,
  );
}
export function splitSegment(
  segments: TranscriptSegment[],
  index: number,
  at: number,
  caret: number,
) {
  const s = segments[index];
  if (
    !s ||
    !Number.isFinite(at) ||
    at <= s.start ||
    at >= s.end ||
    !Number.isInteger(caret) ||
    caret <= 0 ||
    caret >= s.text.length
  )
    throw new Error("invalid_transcript_segment");
  const left = s.text.slice(0, caret).trimEnd(),
    right = s.text.slice(caret).trimStart();
  if (!left || !right) throw new Error("invalid_transcript_segment");
  return valid([
    ...segments.slice(0, index),
    changed({ ...s, end: at, text: left }),
    changed({ ...s, start: at, text: right }),
    ...segments.slice(index + 1),
  ]);
}
export function mergeSegment(segments: TranscriptSegment[], index: number) {
  const a = segments[index],
    b = segments[index + 1];
  if (!a || !b || (a.speaker ?? null) !== (b.speaker ?? null))
    throw new Error("speaker_merge_required");
  return valid([
    ...segments.slice(0, index),
    changed({
      ...a,
      end: Math.max(a.end, b.end),
      text: `${a.text.trimEnd()} ${b.text.trimStart()}`,
    }),
    ...segments.slice(index + 2),
  ]);
}

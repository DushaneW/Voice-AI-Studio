import { useRef, useState } from "react";
import type { TranscriptSegment } from "../../types/domain";

// Conservative logical-size budget (not a heap measurement). Shared segments
// count towards every snapshot, keeping both count and retained content bounded.
const BUDGET = 16 * 1024 * 1024;
function bounded(values: TranscriptSegment[][]) {
  let bytes = 0;
  const result: TranscriptSegment[][] = [];
  for (let i = values.length - 1; i >= 0 && result.length < 50; i--) {
    const size = values[i].reduce(
      (n, segment) =>
        n +
        128 +
        2 * (segment.text.length + (segment.speaker?.length ?? 0)) +
        (segment.words?.reduce((n, word) => n + 64 + word.text.length * 2, 0) ??
          0),
      0,
    );
    if (bytes + size > BUDGET) break;
    bytes += size;
    result.unshift(values[i]);
  }
  return result;
}
export function useTranscriptUndo() {
  const past = useRef<TranscriptSegment[][]>([]);
  const future = useRef<TranscriptSegment[][]>([]);
  const [, render] = useState(0);
  const update = () => render((n) => n + 1);
  return {
    canUndo: past.current.length > 0,
    canRedo: future.current.length > 0,
    record(value: TranscriptSegment[]) {
      past.current = bounded([...past.current, value]);
      future.current = [];
      update();
    },
    undo(value: TranscriptSegment[]) {
      const previous = past.current.pop();
      if (!previous) return null;
      future.current = bounded([...future.current, value]);
      update();
      return previous;
    },
    redo(value: TranscriptSegment[]) {
      const next = future.current.pop();
      if (!next) return null;
      past.current = bounded([...past.current, value]);
      update();
      return next;
    },
    clear() {
      past.current = [];
      future.current = [];
      update();
    },
  };
}

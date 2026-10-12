import { expect, it } from "vitest";
import { mergeSegment, retimeSegment, splitSegment } from "./transcriptEdit";
const original = [
  {
    start: 0,
    end: 2,
    text: "Hello world",
    speaker: "Alice",
    words: [{ start: 0, end: 1, text: "Hello" }],
  },
];
it("splits text at the caret and time explicitly, retaining the speaker and invalidating word alignment", () => {
  const result = splitSegment(original, 0, 0.8, 6);
  expect(result.map((s) => [s.start, s.end, s.text, s.speaker])).toEqual([
    [0, 0.8, "Hello", "Alice"],
    [0.8, 2, "world", "Alice"],
  ]);
  expect(
    result.every(
      (s) => s.word_timestamps_valid === false && s.words?.length === 0,
    ),
  ).toBe(true);
  expect(original[0].words).toHaveLength(1);
  expect(mergeSegment(result, 0)[0].text).toBe("Hello world");
});
it("rejects invalid splits, timing order, duration overflow and merging different speakers", () => {
  expect(() => splitSegment(original, 0, 2, 6)).toThrow();
  expect(() => splitSegment(original, 0, 1, 0)).toThrow();
  expect(() => retimeSegment(original, 0, 0, 3, 2)).toThrow();
  const two = [...original, { start: 2, end: 3, text: "Next", speaker: "Bob" }];
  expect(() => retimeSegment(two, 1, 0, 3)).not.toThrow(); // Equal starts are permitted by the backend.
  expect(() => retimeSegment(two, 1, -1, 3)).toThrow();
  expect(() => mergeSegment(two, 0)).toThrow("speaker_merge_required");
});

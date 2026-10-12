import { expect, it } from "vitest";
import { splitClip, duplicateClip } from "./edit";
const clip = {
  asset_id: "a",
  track_id: "voice",
  offset: 10,
  trim_start: 2,
  trim_end: 8,
  gain: 0.7,
  fade_in: 1,
  fade_out: 1,
};
it("splits trimmed source coordinates while keeping placement and track", () => {
  const [first, second] = splitClip(clip, 13);
  expect(first).toEqual({ ...clip, trim_end: 5, fade_out: 0 });
  expect(second).toEqual({ ...clip, trim_start: 5, offset: 13, fade_in: 0 });
  expect(
    first.trim_end - first.trim_start + second.trim_end - second.trim_start,
  ).toBe(6);
  expect(clip.trim_end).toBe(8);
});
it("rejects out-of-range cuts and cuts through existing fade envelopes", () => {
  expect(() => splitClip(clip, 10)).toThrow("split_outside_clip");
  expect(() => splitClip(clip, 10.5)).toThrow("split_crosses_fade");
});
it("duplicates after the original while preserving source range", () => {
  expect(duplicateClip(clip)).toEqual({ ...clip, offset: 16 });
});

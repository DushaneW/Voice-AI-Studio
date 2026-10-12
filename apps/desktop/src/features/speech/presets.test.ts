import { expect, it } from "vitest";
import { exportPresets, importPresets, mergePresets } from "./presets";
const p = {
  favorite: true,
  tags: "narration",
  speed: 1.2,
  created: "2026-10-03T00:00:00Z",
  modified: "2026-10-04T00:00:00Z",
};
it("roundtrips settings and preserves local conflicts", () => {
  const incoming = importPresets(exportPresets({ af_heart: p, bf_emma: p }));
  const current = { af_heart: { ...p, speed: 0.8 } };
  expect(mergePresets(current, incoming)).toEqual({
    af_heart: current.af_heart,
    bf_emma: p,
  });
  expect(incoming.af_heart.speed).toBe(1.2);
});
it("rejects malformed, unsupported, dangerous and oversized imports", () => {
  for (const raw of [
    "null",
    "{}",
    "broken",
    JSON.stringify({ format: "nexus-voice-presets", version: 2, presets: {} }),
    JSON.stringify({
      format: "nexus-voice-presets",
      version: 1,
      presets: { af_heart: { ...p, speed: 4 } },
    }),
    '{"format":"nexus-voice-presets","version":1,"presets":{"__proto__":{}}}',
    " ".repeat(1048577),
  ])
    expect(() => importPresets(raw)).toThrow();
  expect(() =>
    mergePresets({}, { af_heart: { ...p, tags: "x".repeat(161) } }),
  ).toThrow();
});

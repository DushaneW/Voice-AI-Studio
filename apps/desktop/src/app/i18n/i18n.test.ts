import { describe, expect, it } from "vitest";
import { en, pl, errorMessage, translator } from "./index";

describe("translations", () => {
  // pl spreads en as a fallback, so a missing Polish key would silently show
  // English. Only words that are identical in both languages may match.
  const SAME_IN_BOTH = [
    "audio", "dubbing", "ffmpeg", "gpu", "media", "mono", "python",
    "recordingPreRoll", "rms", "solo", "stereo", "system", "templatePodcast",
  ];

  it("has no untranslated Polish keys outside the allowlist", () => {
    const untranslated = (Object.keys(en) as (keyof typeof en)[]).filter(
      (key) => en[key] === pl[key] && !SAME_IN_BOTH.includes(key),
    );
    expect(untranslated).toEqual([]);
  });

  it("have no empty strings", () => {
    for (const [language, table] of [["en", en], ["pl", pl]] as const) {
      for (const [key, value] of Object.entries(table)) {
        expect(value.trim(), `${language}.${key}`).not.toBe("");
      }
    }
  });

  it("use the same interpolation placeholders in both languages", () => {
    const placeholders = (text: string) => (text.match(/\{[a-zA-Z0-9_]+\}/g) ?? []).sort();
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(placeholders(pl[key]), key).toEqual(placeholders(en[key]));
    }
  });

  it("maps known runtime error codes and falls back for unknown ones", () => {
    expect(errorMessage(new Error("active_jobs"), "en")).toBe(en.active_jobs);
    expect(errorMessage("not_a_real_code", "pl")).toBe(pl.unknownError);
    expect(translator("pl")("stop")).toBe(pl.stop);
  });
});

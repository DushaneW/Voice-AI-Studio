import { describe, expect, it } from "vitest";
import { asrHint, formatModelSize, pickAsrModel } from "./asr";
import type { Model } from "./Models";

const model = (id: string, state: string) => ({ id, state }) as Model;

describe("pickAsrModel", () => {
  const models = [
    model("whisper-tiny", "available"),
    model("whisper-small", "installed"),
    model("whisper-medium", "installed"),
  ];

  it("keeps an explicit choice even when it is not installed", () => {
    expect(pickAsrModel(models, "whisper-tiny")?.id).toBe("whisper-tiny");
  });

  it("falls back to the first installed model", () => {
    expect(pickAsrModel(models, "")?.id).toBe("whisper-small");
    expect(pickAsrModel(models, "removed-model")?.id).toBe("whisper-small");
  });

  it("falls back to the first entry when nothing is installed", () => {
    expect(pickAsrModel([model("a", "available")], null)?.id).toBe("a");
    expect(pickAsrModel([], null)).toBeUndefined();
  });
});

describe("model hints and sizes", () => {
  it("has hints only for known Whisper entries", () => {
    expect(asrHint("whisper-medium")).toBe("asrHintMedium");
    expect(asrHint("test-asr-catalog-entry")).toBeNull();
    expect(asrHint(undefined)).toBeNull();
  });

  it("formats MiB and GiB", () => {
    expect(formatModelSize(78_203_619)).toBe("75 MiB");
    expect(formatModelSize(1_530_571_744)).toBe("1.4 GiB");
  });
});

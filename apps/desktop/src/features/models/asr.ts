import type { Key } from "../../app/i18n";
import type { Model } from "./Models";

// Speed/accuracy hints for the pinned Whisper catalog entries. Unknown ids get no hint.
const ASR_HINTS: Record<string, Key> = {
  "whisper-tiny": "asrHintTiny",
  "whisper-base": "asrHintBase",
  "whisper-small": "asrHintSmall",
  "whisper-medium": "asrHintMedium",
};

export function asrHint(id: string | undefined): Key | null {
  return (id && ASR_HINTS[id]) || null;
}

export function formatModelSize(bytes: number): string {
  return bytes >= 1024 ** 3
    ? (bytes / 1024 ** 3).toFixed(1) + " GiB"
    : (bytes / 1024 ** 2).toFixed(0) + " MiB";
}

/** The preferred model if it is in the catalog, else the first installed one, else the first. */
export function pickAsrModel(
  models: Model[],
  preferred: string | null | undefined,
): Model | undefined {
  return (
    models.find((m) => m.id === preferred) ??
    models.find((m) => m.state === "installed") ??
    models[0]
  );
}

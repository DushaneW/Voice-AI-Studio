export type Preset = {
  favorite: boolean;
  tags: string;
  speed: number;
  created: string;
  modified: string;
};
export const STORAGE = "nexus.voice-presets.v1";
export const MAX_PRESET_BYTES = 262144;
export const MAX_TRANSFER_BYTES = 1048576;
export function validatePresets(data: unknown): Record<string, Preset> {
  if (!data || typeof data !== "object" || Array.isArray(data))
    throw new Error("voiceImportInvalid");
  const clean: Record<string, Preset> = {};
  for (const [id, value] of Object.entries(data)) {
    const p = value as Preset;
    if (
      !/^[a-z][a-z]_[a-z0-9_]+$/.test(id) ||
      !p ||
      typeof p !== "object" ||
      Array.isArray(p) ||
      typeof p.favorite !== "boolean" ||
      typeof p.tags !== "string" ||
      p.tags.length > 160 ||
      typeof p.speed !== "number" ||
      !Number.isFinite(p.speed) ||
      p.speed < 0.5 ||
      p.speed > 2 ||
      typeof p.created !== "string" ||
      typeof p.modified !== "string" ||
      !Number.isFinite(Date.parse(p.created)) ||
      !Number.isFinite(Date.parse(p.modified))
    )
      throw new Error("voiceImportInvalid");
    clean[id] = {
      favorite: p.favorite,
      tags: p.tags,
      speed: p.speed,
      created: p.created,
      modified: p.modified,
    };
  }
  if (
    new TextEncoder().encode(JSON.stringify(clean)).byteLength >
    MAX_PRESET_BYTES
  )
    throw new Error("voiceImportInvalid");
  return clean;
}
export function readPresets(): Record<string, Preset> {
  const raw = localStorage.getItem(STORAGE);
  if (!raw) return {};
  if (raw.length > MAX_PRESET_BYTES) throw new Error("voiceImportInvalid");
  return validatePresets(JSON.parse(raw));
}
export function exportPresets(presets: Record<string, Preset>): string {
  return JSON.stringify(
    {
      format: "nexus-voice-presets",
      version: 1,
      presets: validatePresets(presets),
    },
    null,
    2,
  );
}
export function importPresets(raw: string): Record<string, Preset> {
  if (new TextEncoder().encode(raw).byteLength > MAX_TRANSFER_BYTES)
    throw new Error("voiceImportInvalid");
  const data = JSON.parse(raw);
  if (!data || data.format !== "nexus-voice-presets" || data.version !== 1)
    throw new Error("voiceImportInvalid");
  return validatePresets(data.presets);
}
export function mergePresets(
  current: Record<string, Preset>,
  incoming: Record<string, Preset>,
) {
  // Existing local preferences always win. Import never silently overwrites them.
  return validatePresets({ ...incoming, ...current });
}

export interface EditableClip {
  asset_id: string;
  track_id?: string;
  offset: number;
  trim_start: number;
  trim_end: number;
  gain: number;
  fade_in: number;
  fade_out: number;
}
export function splitClip<T extends EditableClip>(
  clip: T,
  position: number,
): [T, T] {
  const local = position - clip.offset;
  const duration = clip.trim_end - clip.trim_start;
  if (!Number.isFinite(position) || local <= 0 || local >= duration)
    throw new Error("split_outside_clip");
  if (local < clip.fade_in || duration - local < clip.fade_out)
    throw new Error("split_crosses_fade");
  const cut = clip.trim_start + local;
  return [
    { ...clip, trim_end: cut, fade_out: 0 },
    { ...clip, offset: position, trim_start: cut, fade_in: 0 },
  ];
}
export function duplicateClip<T extends EditableClip>(clip: T): T {
  return { ...clip, offset: clip.offset + clip.trim_end - clip.trim_start };
}

import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { Asset, Settings } from "../../types/domain";
import type { Key } from "../../app/i18n";
import { isEditing } from "../../app/commands/registry";
import type { EditableClip } from "./edit";
interface Track {
  id: string;
  volume: number;
  pan: number;
  muted: boolean;
  solo: boolean;
}
interface Document {
  clips: EditableClip[];
  tracks: Track[];
  channels: number;
}
export function TimelineTransport({
  defaults,
  document,
  assets,
  position,
  onPosition,
  onError,
  disabled,
  t,
  seekVersion,
}: {
  defaults?: Settings;
  document: Document;
  assets: Asset[];
  position: number;
  onPosition: (position: number) => void;
  onError: (error: string) => void;
  disabled: boolean;
  seekVersion: number;
  t: (key: Key) => string;
}) {
  const [volume, setVolume] = useState(defaults?.playback_volume ?? 1);
  const [muted, setMuted] = useState(defaults?.playback_muted ?? false);
  const master = useRef<GainNode | null>(null);
  const monitorLevel = useRef(muted ? 0 : volume);
  monitorLevel.current = muted ? 0 : volume;
  useEffect(() => {
    if (master.current && current.current)
      master.current.gain.setTargetAtTime(
        monitorLevel.current,
        current.current.currentTime,
        0.01,
      );
  }, [volume, muted]);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const current = useRef<AudioContext | null>(null);
  const generation = useRef(0);
  const frame = useRef(0);
  const mounted = useRef(true);
  function stop() {
    generation.current++;
    if (typeof cancelAnimationFrame === "function")
      cancelAnimationFrame(frame.current);
    const context = current.current;
    current.current = null;
    master.current = null;
    if (context) void context.close().catch(() => {});
    if (mounted.current) {
      setPlaying(false);
      setLoading(false);
    }
  }
  useEffect(() => {
    stop();
  }, [document, seekVersion]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      stop();
    };
  }, []);
  async function play() {
    if (disabled || loading || playing || !document.clips.length) return;
    if (typeof AudioContext === "undefined") {
      onError("playback_unavailable");
      return;
    }
    stop();
    const token = ++generation.current;
    setLoading(true);
    let context: AudioContext;
    try {
      context = new AudioContext();
    } catch {
      setLoading(false);
      onError("playback_unavailable");
      return;
    }
    current.current = context;
    try {
      if (
        document.clips.some(
          (clip) =>
            ![
              clip.offset,
              clip.trim_start,
              clip.trim_end,
              clip.gain,
              clip.fade_in,
              clip.fade_out,
            ].every(Number.isFinite) ||
            clip.offset < 0 ||
            clip.trim_start < 0 ||
            clip.trim_end <= clip.trim_start ||
            clip.gain < 0 ||
            clip.gain > 4 ||
            clip.fade_in < 0 ||
            clip.fade_out < 0,
        )
      )
        throw new Error("invalid_clip");
      await context.resume();
      const anySolo = document.tracks.some((track) => track.solo);
      const audible = document.clips.filter((clip) => {
        const track = document.tracks.find(
          (track) => track.id === (clip.track_id ?? "main"),
        );
        return track && !track.muted && (!anySolo || track.solo);
      });
      const end = Math.max(
        ...document.clips.map((c) => c.offset + c.trim_end - c.trim_start),
      );
      const start = position >= end ? 0 : position;
      const needed = [
        ...new Set(
          audible
            .filter((c) => c.offset + c.trim_end - c.trim_start > start)
            .map((c) => c.asset_id),
        ),
      ];
      let memory = 0;
      for (const id of needed) {
        const asset = assets.find((asset) => asset.id === id);
        if (!asset || asset.channels > 2)
          throw new Error("preview_source_unsupported");
        memory +=
          asset.duration *
          Math.max(context.sampleRate, asset.sample_rate) *
          asset.channels *
          4;
        if (asset.size > 32 * 1048576 || memory > 64 * 1048576)
          throw new Error("preview_memory_limit");
      }
      const buffers = new Map<string, AudioBuffer>();
      for (const id of needed) {
        const bytes = await invoke<ArrayBuffer>("read_audio", { assetId: id });
        if (generation.current !== token) return;
        buffers.set(id, await context.decodeAudioData(bytes));
        if (generation.current !== token) return;
      }
      const output = context.createGain();
      output.gain.value = monitorLevel.current;
      output.connect(context.destination);
      master.current = output;
      const base = context.currentTime + 0.05;
      for (const clip of audible) {
        const duration = clip.trim_end - clip.trim_start;
        const local = Math.max(0, start - clip.offset);
        if (local >= duration) continue;
        const buffer = buffers.get(clip.asset_id);
        if (!buffer) continue;
        const track = document.tracks.find(
          (track) => track.id === (clip.track_id ?? "main"),
        )!;
        const at = base + Math.max(0, clip.offset - start),
          until = at + duration - local;
        const source = context.createBufferSource();
        source.buffer = buffer;
        const level = context.createGain();
        level.gain.value = clip.gain * track.volume;
        const fadeIn = context.createGain(),
          fadeOut = context.createGain();
        fadeIn.gain.setValueAtTime(
          clip.fade_in > 0 ? Math.min(1, local / clip.fade_in) : 1,
          at,
        );
        if (clip.fade_in > local)
          fadeIn.gain.linearRampToValueAtTime(1, at + clip.fade_in - local);
        fadeOut.gain.setValueAtTime(
          clip.fade_out > 0
            ? Math.min(1, (duration - local) / clip.fade_out)
            : 1,
          at,
        );
        if (clip.fade_out > 0) {
          if (duration - local > clip.fade_out)
            fadeOut.gain.setValueAtTime(1, until - clip.fade_out);
          fadeOut.gain.linearRampToValueAtTime(0, until);
        }
        source.connect(level).connect(fadeIn).connect(fadeOut);
        if (document.channels === 1) {
          const mono = context.createGain();
          mono.channelCount = 1;
          mono.channelCountMode = "explicit";
          fadeOut.connect(mono).connect(output);
        } else {
          fadeOut.channelCount = 2;
          fadeOut.channelCountMode = "explicit";
          const split = context.createChannelSplitter(2),
            merge = context.createChannelMerger(2);
          const left = context.createGain(),
            right = context.createGain();
          left.gain.value = Math.min(1, 1 - track.pan);
          right.gain.value = Math.min(1, 1 + track.pan);
          fadeOut.connect(split);
          split.connect(left, 0);
          split.connect(right, 1);
          left.connect(merge, 0, 0);
          right.connect(merge, 0, 1);
          merge.connect(output);
        }
        source.start(at, clip.trim_start + local, duration - local);
      }
      if (generation.current !== token) return;
      setLoading(false);
      setPlaying(true);
      let lastUpdate = -1;
      function tick() {
        if (generation.current !== token) return;
        const cursor = Math.min(
          end,
          start + Math.max(0, context.currentTime - base),
        );
        if (cursor - lastUpdate >= 0.1 || cursor >= end) {
          onPosition(cursor);
          lastUpdate = cursor;
        }
        if (cursor >= end) {
          stop();
          return;
        }
        frame.current = requestAnimationFrame(tick);
      }
      tick();
    } catch (error) {
      if (generation.current === token) {
        stop();
        onError(String(error));
      }
    }
  }
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (
        event.code !== "Space" ||
        event.defaultPrevented ||
        isEditing(event.target) ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey
      )
        return;
      if (
        event.target instanceof HTMLElement &&
        event.target.tagName === "BUTTON"
      )
        return;
      event.preventDefault();
      if (playing || loading) stop();
      else void play();
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  return (
    <div className="toolbar">
      <button
        disabled={disabled || !document.clips.length || loading}
        onClick={() => (playing ? stop() : void play())}
      >
        {t(playing ? "pausePlayback" : "playTimeline")}
      </button>
      <button
        disabled={!playing && !loading && position === 0}
        onClick={() => {
          stop();
          onPosition(0);
        }}
      >
        {t("stopPlayback")}
      </button>
      <label>
        {t("monitorVolume")} {Math.round(volume * 100)}%
        <input
          aria-label={t("monitorVolume")}
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={muted}
          onChange={(e) => setMuted(e.target.checked)}
        />
        {t("monitorMute")}
      </label>
      <span role="status">
        {loading ? t("preparingPlayback") : `${position.toFixed(2)} s`}
      </span>
    </div>
  );
}

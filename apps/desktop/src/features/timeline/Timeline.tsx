import { useAutosave, AutosaveStatus } from "../../hooks/useAutosave";
import { useEditorSave } from "../../app/commands/EditorCommands";
import { TimelineTransport } from "./TimelineTransport";
import { splitClip, duplicateClip } from "./edit";
import { runShortcut, isEditing } from "../../app/commands/registry";
import { useRecoveryDraft } from "../../hooks/useRecoveryDraft";
import { RecoveryNotice } from "../../components/recovery/RecoveryNotice";
import { DocumentHistory } from "../../components/history/DocumentHistory";
import { useUnsavedChanges } from "../../app/UnsavedChanges";
import { useEffect, useState } from "react";
import { useHistory } from "../../hooks/useHistory";
import { request } from "../../services/runtime";
import type { Asset, Settings } from "../../types/domain";
import type { Key } from "../../app/i18n";
interface Track {
  id: string;
  name: string;
  volume: number;
  pan: number;
  muted: boolean;
  solo: boolean;
  locked: boolean;
  visible: boolean;
}
const mainTrack = (): Track => ({
  id: "main",
  name: "Main",
  volume: 1,
  pan: 0,
  muted: false,
  solo: false,
  locked: false,
  visible: true,
});
interface Clip {
  track_id?: string;
  asset_id: string;
  offset: number;
  trim_start: number;
  trim_end: number;
  gain: number;
  fade_in: number;
  fade_out: number;
}
interface TimelineDocument {
  clips: Clip[];
  tracks: Track[];
  sample_rate: number;
  channels: number;
}
const initialDocument = (): TimelineDocument => ({
  clips: [],
  tracks: [mainTrack()],
  sample_rate: 48000,
  channels: 2,
});
export function Timeline({
  defaults,
  projectId,
  assets,
  t,
  onError,
  onQueued,
}: {
  defaults?: Settings;
  projectId: string;
  assets: Asset[];
  t: (k: Key) => string;
  onError: (s: string) => void;
  onQueued: () => void;
}) {
  const history = useHistory<TimelineDocument>(initialDocument());
  const { clips, tracks, sample_rate: sampleRate, channels } = history.value;
  const setClips = (value: Clip[]) =>
    history.set({ ...history.value, clips: value });
  const setSampleRate = (value: number) =>
    history.set({ ...history.value, sample_rate: value });
  const setChannels = (value: number) =>
    history.set({ ...history.value, channels: value });
  const loadDocument = (value: Partial<TimelineDocument>) =>
    history.reset({ ...initialDocument(), ...value });
  const [targetTrack, setTargetTrack] = useState("main");
  const [selectedClip, setSelectedClip] = useState<number | null>(null);
  const [cursor, setCursor] = useState(0);
  const [seekVersion, setSeekVersion] = useState(0);
  const [clipboard, setClipboard] = useState<Clip | null>(null);
  const selected = selectedClip === null ? null : clips[selectedClip];
  const selectedTrack = tracks.find(
    (track) => track.id === (selected?.track_id ?? "main"),
  );
  function updateTrack(id: string, patch: Partial<Track>) {
    history.set({
      ...history.value,
      tracks: tracks.map((track) =>
        track.id === id ? { ...track, ...patch } : track,
      ),
    });
    setDirty(true);
  }
  const [revision, setRevision] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [assetId, setAssetId] = useState("");
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const clean = useUnsavedChanges(dirty, saving);
  const draft = useRecoveryDraft({
    scope: `${projectId}.timeline`,
    loaded: loaded && !!projectId,
    dirty,
    revision,
    content: history.value,
    validate: (value) => {
      const d = value as Partial<TimelineDocument> | null;
      return (
        !!d &&
        Array.isArray(d.clips) &&
        d.clips.length <= 64 &&
        [24000, 44100, 48000].includes(d.sample_rate ?? 48000) &&
        [1, 2].includes(d.channels ?? 2) &&
        (!d.tracks ||
          (Array.isArray(d.tracks) &&
            d.tracks.length <= 32 &&
            d.tracks.every(
              (t) =>
                t &&
                typeof t.id === "string" &&
                typeof t.name === "string" &&
                Number.isFinite(t.volume) &&
                Number.isFinite(t.pan),
            ))) &&
        d.clips.every(
          (c) =>
            c &&
            typeof c.asset_id === "string" &&
            [
              c.offset,
              c.trim_start,
              c.trim_end,
              c.gain,
              c.fade_in,
              c.fade_out,
            ].every(Number.isFinite),
        )
      );
    },
    apply: (value) => {
      if (!Array.isArray(value.clips)) {
        onError("invalid_document");
        return;
      }
      history.set({ ...initialDocument(), ...value });
      setDirty(true);
    },
  });
  useEffect(() => {
    let live = true;
    setLoaded(false);
    loadDocument({});
    setTargetTrack("main");
    setRevision(0);
    setDirty(false);
    if (projectId)
      request<{ revision: number; content: Partial<TimelineDocument> }>(
        "GET",
        "/v1/projects/" + projectId + "/documents/timeline",
      )
        .then((d) => {
          if (live) {
            loadDocument(d.content);
            setRevision(d.revision);
            setLoaded(true);
          }
        })
        .catch((e) => onError(String(e)));
    return () => {
      live = false;
    };
  }, [projectId]);
  async function save(render = false) {
    if (saving || !loaded || draft.pending) return false;
    setSaving(true);
    try {
      if (dirty) {
        const d = await request<{ revision: number }>(
          "PUT",
          "/v1/projects/" + projectId + "/documents/timeline",
          { revision, content: history.value },
        );
        setRevision(d.revision);
        setDirty(false);
        draft.clear();
      }
      if (render) {
        await request("POST", "/v1/timeline/render", {
          project_id: projectId,
          sample_rate: sampleRate,
          channels,
          tracks,
          clips,
        });
      }
      clean();
      if (render) onQueued();
      return true;
    } catch (e) {
      onError(String(e));
      return false;
    } finally {
      setSaving(false);
    }
  }
  useEditorSave(dirty && loaded && !saving && !draft.pending, () => save());
  const autosave = useAutosave(
    dirty,
    saving || !loaded || !!draft.pending,
    () => save(),
  );
  function editSelected(
    action: "split" | "duplicate" | "delete" | "copy" | "cut",
  ) {
    if (
      !selected ||
      selectedClip === null ||
      saving ||
      !loaded ||
      selectedTrack?.locked ||
      selectedTrack?.visible === false
    )
      return;
    try {
      if (action === "copy" || action === "cut") setClipboard({ ...selected });
      if (action === "copy") return;
      const next = [...clips];
      if (action === "split")
        next.splice(selectedClip, 1, ...splitClip(selected, cursor));
      if (action === "duplicate")
        next.splice(selectedClip + 1, 0, duplicateClip(selected));
      if (action === "delete" || action === "cut") {
        next.splice(selectedClip, 1);
        setSelectedClip(null);
      }
      if (next.length > 64) throw new Error("timeline_clip_limit");
      setClips(next);
      setDirty(true);
    } catch (error) {
      onError(String(error));
    }
  }
  function pasteClip() {
    const track = tracks.find((t) => t.id === targetTrack) ?? tracks[0];
    if (!clipboard || saving || !loaded || clips.length >= 64 || track.locked)
      return;
    setClips([...clips, { ...clipboard, offset: cursor, track_id: track.id }]);
    setSelectedClip(clips.length);
    setDirty(true);
  }
  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      if (
        event.defaultPrevented ||
        (isEditing(event.target) && event.key.toLowerCase() !== "s")
      )
        return;
      runShortcut(event, [
        {
          id: "timeline-save",
          label: "save",
          shortcut: "mod+s",
          enabled: loaded && dirty && !saving && !draft.pending,
          run: () => void save(),
        },
        {
          id: "timeline-undo",
          label: "undo",
          shortcut: "mod+z",
          enabled: history.canUndo && !saving,
          run: () => {
            history.undo();
            setDirty(true);
          },
        },
        {
          id: "timeline-redo",
          label: "redo",
          shortcut: "mod+shift+z",
          enabled: history.canRedo && !saving,
          run: () => {
            history.redo();
            setDirty(true);
          },
        },
        {
          id: "timeline-delete",
          label: "remove",
          shortcut: "delete",
          enabled: !!selected && !saving,
          run: () => editSelected("delete"),
        },
        {
          id: "timeline-copy",
          label: "copyClip",
          shortcut: "mod+c",
          enabled: !!selected,
          run: () => editSelected("copy"),
        },
        {
          id: "timeline-cut",
          label: "cutClip",
          shortcut: "mod+x",
          enabled: !!selected,
          run: () => editSelected("cut"),
        },
        {
          id: "timeline-paste",
          label: "pasteClip",
          shortcut: "mod+v",
          enabled: !!clipboard,
          run: pasteClip,
        },
      ]);
    }
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  });
  function update(
    index: number,
    key: keyof Omit<Clip, "asset_id" | "track_id">,
    value: number,
  ) {
    setClips(clips.map((c, i) => (i === index ? { ...c, [key]: value } : c)));
    setDirty(true);
  }
  const end = Math.max(
    1,
    ...clips.map((c) => c.offset + c.trim_end - c.trim_start),
  );
  return !projectId ? (
    <div className="empty">{t("selectProject")}</div>
  ) : (
    <>
      <AutosaveStatus state={autosave} t={t} />
      <RecoveryNotice
        pending={draft.pending}
        status={draft.status}
        revision={revision}
        recover={draft.recover}
        discard={draft.clear}
        t={t}
      />
      <div className="toolbar">
        <button
          disabled={!history.canUndo || saving || !loaded}
          onClick={() => {
            history.undo();
            setDirty(true);
          }}
        >
          {t("undo")}
        </button>
        <button
          disabled={!history.canRedo || saving || !loaded}
          onClick={() => {
            history.redo();
            setDirty(true);
          }}
        >
          {t("redo")}
        </button>
        <select
          aria-label={t("media")}
          value={assetId}
          onChange={(e) => setAssetId(e.target.value)}
        >
          <option value="">{t("choose")}</option>
          {assets.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <button
          disabled={
            !assetId ||
            clips.length >= 64 ||
            saving ||
            !loaded ||
            tracks.find((t) => t.id === targetTrack)?.locked
          }
          onClick={() => {
            const a = assets.find((a) => a.id === assetId);
            if (a) {
              setClips([
                ...clips,
                {
                  asset_id: a.id,
                  track_id: tracks.some((t) => t.id === targetTrack)
                    ? targetTrack
                    : tracks[0].id,
                  offset: 0,
                  trim_start: 0,
                  trim_end: a.duration,
                  gain: 1,
                  fade_in: 0,
                  fade_out: 0,
                },
              ]);
              setDirty(true);
            }
          }}
        >
          {t("addClip")}
        </button>
        <button
          disabled={!dirty || saving || !loaded || !!draft.pending}
          onClick={() => void save()}
        >
          {t("save")}
        </button>
        <button
          className="primary"
          disabled={!clips.length || saving || !loaded || !!draft.pending}
          onClick={() => void save(true)}
        >
          {t("renderAudio")}
        </button>
      </div>
      <div className="toolbar">
        <label>
          WAV PCM16{" "}
          <select
            aria-label="Sample rate"
            value={sampleRate}
            disabled={saving || !loaded}
            onChange={(e) => {
              setSampleRate(Number(e.target.value));
              setDirty(true);
            }}
          >
            <option value={24000}>24 kHz</option>
            <option value={44100}>44.1 kHz</option>
            <option value={48000}>48 kHz</option>
          </select>
        </label>
        <select
          aria-label="Channels"
          value={channels}
          disabled={saving || !loaded}
          onChange={(e) => {
            setChannels(Number(e.target.value));
            setDirty(true);
          }}
        >
          <option value={1}>Mono</option>
          <option value={2}>Stereo</option>
        </select>
      </div>
      <TimelineTransport
        defaults={defaults}
        seekVersion={seekVersion}
        document={history.value}
        assets={assets}
        position={cursor}
        onPosition={setCursor}
        onError={onError}
        disabled={saving || !loaded || !!draft.pending}
        t={t}
      />
      <DocumentHistory
        key={projectId}
        projectId={projectId}
        kind="timeline"
        revision={revision}
        disabled={dirty || saving || !loaded || !!draft.pending}
        t={t}
        onError={onError}
        onBusy={setSaving}
        onRestore={(document) => {
          loadDocument(document.content as Partial<TimelineDocument>);
          setRevision(document.revision);
          setDirty(false);
          clean();
        }}
      />
      <section className="panel" aria-label={t("tracks")}>
        <div className="toolbar">
          <h3>{t("tracks")}</h3>
          <button
            disabled={saving || !loaded || tracks.length >= 32}
            onClick={() => {
              const id = crypto.randomUUID();
              const track = {
                ...mainTrack(),
                id,
                name: `${t("track")} ${tracks.length + 1}`,
              };
              history.set({ ...history.value, tracks: [...tracks, track] });
              setTargetTrack(id);
              setDirty(true);
            }}
          >
            {t("addTrack")}
          </button>
          <select
            aria-label={t("targetTrack")}
            value={targetTrack}
            onChange={(e) => setTargetTrack(e.target.value)}
          >
            {tracks.map((track) => (
              <option key={track.id} value={track.id}>
                {track.name}
              </option>
            ))}
          </select>
        </div>
        {tracks.map((track) => (
          <div key={track.id} className="toolbar">
            <input
              aria-label={t("trackName")}
              value={track.name}
              maxLength={120}
              disabled={saving || track.locked}
              onChange={(e) => updateTrack(track.id, { name: e.target.value })}
            />
            <label>
              {t("trackVolume")}
              <input
                type="range"
                min="0"
                max="4"
                step="0.01"
                value={track.volume}
                disabled={saving || track.locked}
                onChange={(e) =>
                  updateTrack(track.id, { volume: Number(e.target.value) })
                }
              />
              <output>{track.volume.toFixed(2)}</output>
            </label>
            <label>
              {t("trackPan")}
              <input
                type="range"
                min="-1"
                max="1"
                step="0.01"
                value={track.pan}
                disabled={saving || track.locked}
                onChange={(e) =>
                  updateTrack(track.id, { pan: Number(e.target.value) })
                }
              />
              <output>{track.pan.toFixed(2)}</output>
            </label>
            {(["muted", "solo", "locked", "visible"] as const).map((key) => (
              <label key={key}>
                <input
                  type="checkbox"
                  checked={track[key]}
                  disabled={saving || (track.locked && key !== "locked")}
                  onChange={(e) =>
                    updateTrack(track.id, { [key]: e.target.checked })
                  }
                />
                {t(key)}
              </label>
            ))}
          </div>
        ))}
      </section>
      <div className="toolbar">
        <label>
          {t("editCursor")}
          <input
            type="range"
            min="0"
            max={end}
            step="0.01"
            value={cursor}
            onChange={(e) => {
              setCursor(Number(e.target.value));
              setSeekVersion((v) => v + 1);
            }}
          />
          <output>{cursor.toFixed(2)} s</output>
        </label>
        <button
          disabled={!selected || saving || selectedTrack?.locked}
          onClick={() => editSelected("split")}
        >
          {t("splitClip")}
        </button>
        <button
          disabled={
            !selected || saving || selectedTrack?.locked || clips.length >= 64
          }
          onClick={() => editSelected("duplicate")}
        >
          {t("duplicateClip")}
        </button>
        <button
          disabled={!selected || saving}
          onClick={() => editSelected("copy")}
        >
          {t("copyClip")}
        </button>
        <button
          disabled={!clipboard || saving || clips.length >= 64}
          onClick={pasteClip}
        >
          {t("pasteClip")}
        </button>
      </div>
      <div className="timeline-ruler">
        <span>0 s</span>
        <span>{(end / 2).toFixed(1)} s</span>
        <span>{end.toFixed(1)} s</span>
      </div>
      {clips.map((c, index) => (
        <section
          className={
            "panel timeline-clip" +
            (selectedClip === index ? " selected-clip" : "")
          }
          onClick={() => setSelectedClip(index)}
          key={index}
          hidden={
            tracks.find((t) => t.id === (c.track_id ?? "main"))?.visible ===
            false
          }
        >
          <div className="timeline-lane">
            <div
              className="clip-block"
              style={{
                marginLeft: (c.offset / end) * 100 + "%",
                width:
                  Math.max(1, ((c.trim_end - c.trim_start) / end) * 100) + "%",
              }}
            >
              <button
                aria-pressed={selectedClip === index}
                onClick={() => setSelectedClip(index)}
              >
                {assets.find((a) => a.id === c.asset_id)?.name ??
                  `${t("addClip")} ${index + 1}`}
              </button>
            </div>
          </div>
          <div className="toolbar">
            <strong>
              {index + 1}. {assets.find((a) => a.id === c.asset_id)?.name}
            </strong>
            <select
              aria-label={t("track")}
              value={c.track_id ?? "main"}
              disabled={
                saving ||
                tracks.find((t) => t.id === (c.track_id ?? "main"))?.locked
              }
              onChange={(e) => {
                setClips(
                  clips.map((clip, i) =>
                    i === index ? { ...clip, track_id: e.target.value } : clip,
                  ),
                );
                setDirty(true);
              }}
            >
              {tracks.map((track) => (
                <option key={track.id} value={track.id} disabled={track.locked}>
                  {track.name}
                </option>
              ))}
            </select>
            <button
              disabled={
                saving ||
                !loaded ||
                tracks.find((t) => t.id === (c.track_id ?? "main"))?.locked
              }
              onClick={() => {
                setClips(clips.filter((_, i) => i !== index));
                setDirty(true);
              }}
            >
              {t("remove")}
            </button>
          </div>
          <div className="clip-fields">
            {(
              [
                "offset",
                "trim_start",
                "trim_end",
                "gain",
                "fade_in",
                "fade_out",
              ] as const
            ).map((key) => (
              <label key={key}>
                {t(key)}
                <input
                  disabled={
                    saving ||
                    !loaded ||
                    tracks.find((t) => t.id === (c.track_id ?? "main"))?.locked
                  }
                  type="number"
                  min="0"
                  step="0.1"
                  value={c[key]}
                  onChange={(e) => update(index, key, Number(e.target.value))}
                />
              </label>
            ))}
          </div>
        </section>
      ))}
      {!clips.length && <div className="empty">{t("emptyTimeline")}</div>}
    </>
  );
}

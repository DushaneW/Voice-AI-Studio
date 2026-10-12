import { useEditorAction } from "../../app/commands/EditorCommands";
import type { Settings } from "../../types/domain";
import { useEffect, useRef, useState } from "react";
import { useUnsavedChanges } from "../../app/UnsavedChanges";
import type { Key } from "../../app/i18n";
import { saveRecording } from "../../services/runtime";
import { MicrophoneCapture, PcmTake } from "./capture";
import { useTakeJournal } from "./useTakeJournal";
import { LiveWaveform } from "./LiveWaveform";
type State =
  | "idle"
  | "starting"
  | "armed"
  | "countdown"
  | "recording"
  | "paused"
  | "stopping"
  | "ready"
  | "saving";
export function Recorder({
  defaults,
  projectId,
  t,
  saved,
}: {
  defaults?: Settings;
  projectId: string;
  t: (key: Key) => string;
  saved: () => void;
}) {
  const capture = useRef<MicrophoneCapture | undefined>(undefined),
    alive = useRef(true),
    session = useRef(0);
  const timer = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const journal = useTakeJournal(projectId);
  const [state, setState] = useState<State>("idle"),
    [devices, setDevices] = useState<MediaDeviceInfo[]>([]),
    [device, setDevice] = useState("");
  const [rate, setRate] = useState<number>(
      defaults?.recording_sample_rate ?? 48000,
    ),
    [channels, setChannels] = useState<number>(
      defaults?.recording_channels ?? 1,
    ),
    [gain, setGain] = useState<number>(defaults?.recording_gain ?? 1),
    [preRoll, setPreRoll] = useState<number>(defaults?.recording_preroll ?? 0),
    [countdown, setCountdown] = useState<number>(
      defaults?.recording_countdown ?? 0,
    ),
    [remaining, setRemaining] = useState(0);
  const [seconds, setSeconds] = useState(0),
    [peak, setPeak] = useState(0),
    [peaks, setPeaks] = useState<number[]>([]),
    [take, setTake] = useState<PcmTake | null>(null);
  const [error, setError] = useState(""),
    [url, setUrl] = useState(""),
    [discard, setDiscard] = useState<string | null>(null),
    [savedNotice, setSavedNotice] = useState(false);
  const locked = state !== "idle" || journal.loading;
  useUnsavedChanges(
    !!take?.samples || state === "recording" || state === "paused",
    !["idle", "ready"].includes(state),
  );
  function level(value: number) {
    if (alive.current) {
      setPeak(value);
      setPeaks((old) => [...old.slice(-119), value]);
    }
  }
  async function devicesChanged() {
    try {
      const values = await navigator.mediaDevices?.enumerateDevices();
      if (alive.current)
        setDevices(values?.filter((d) => d.kind === "audioinput") ?? []);
    } catch {
      /* Start reports the actual permission failure. */
    }
  }
  useEffect(() => {
    alive.current = true;
    void devicesChanged();
    navigator.mediaDevices?.addEventListener("devicechange", devicesChanged);
    return () => {
      alive.current = false;
      session.current++;
      clearInterval(timer.current);
      capture.current?.dispose();
      navigator.mediaDevices?.removeEventListener(
        "devicechange",
        devicesChanged,
      );
    };
  }, []);
  useEffect(() => {
    if (state !== "ready" || !take?.samples) {
      setUrl("");
      return;
    }
    const value = URL.createObjectURL(
      new Blob([take.wav()], { type: "audio/wav" }),
    );
    setUrl(value);
    return () => URL.revokeObjectURL(value);
  }, [state, take]);
  async function stop() {
    clearInterval(timer.current);
    setState("stopping");
    await capture.current?.stop();
    if (!alive.current) return;
    const value = capture.current?.take;
    if (value) journal.sync(value);
    await journal.flush();
    if (!alive.current) return;
    setTake(value ?? null);
    setPeak(0);
    setState(value?.samples ? "ready" : "idle");
    if (!value?.samples) {
      setError("recording_empty");
      await journal.remove();
    }
  }
  function record() {
    const current = session.current;
    if (!countdown) {
      capture.current?.record();
      setState("recording");
      return;
    }
    const until = Date.now() + countdown * 1000;
    setRemaining(countdown);
    setState("countdown");
    timer.current = setInterval(() => {
      if (!alive.current || current !== session.current) {
        clearInterval(timer.current);
        return;
      }
      const left = Math.max(0, Math.ceil((until - Date.now()) / 1000));
      setRemaining(left);
      if (!left) {
        clearInterval(timer.current);
        capture.current?.record();
        setState("recording");
      }
    }, 100);
  }
  async function cancelPreparation() {
    session.current++;
    clearInterval(timer.current);
    capture.current?.dispose();
    capture.current = undefined;
    setPeak(0);
    setState("stopping");
    await journal.remove();
    if (alive.current) setState("idle");
  }
  async function start() {
    const current = ++session.current;
    setState("starting");
    setError("");
    setSavedNotice(false);
    setSeconds(0);
    setPeaks([]);
    await journal.begin(rate, channels);
    if (!alive.current || current !== session.current) return;
    const recorder = new MicrophoneCapture(
      (value) => {
        if (alive.current) {
          setSeconds(value.seconds);
          level(value.peak);
          journal.sync(value);
        }
      },
      (code) => {
        if (alive.current) {
          setError(code);
          void stop();
        }
      },
      level,
    );
    capture.current = recorder;
    try {
      await recorder.start(
        device,
        rate,
        channels,
        gain,
        preRoll > 0 || countdown > 0,
        preRoll,
      );
      if (!alive.current || current !== session.current) {
        recorder.dispose();
        return;
      }
      setState(preRoll || countdown ? "armed" : "recording");
      void devicesChanged();
    } catch (cause) {
      if (!alive.current) return;
      const name =
        cause && typeof cause === "object" && "name" in cause ? cause.name : "";
      setError(
        name === "NotAllowedError"
          ? "recording_permission"
          : name === "NotFoundError" || name === "OverconstrainedError"
            ? "recording_device"
            : "recording_unsupported",
      );
      setState("idle");
      await journal.remove();
    }
  }
  async function save() {
    if (!take) return;
    setState("saving");
    setError("");
    try {
      await saveRecording(projectId, take.wav(), journal.requestId());
      await journal.remove();
      if (alive.current) {
        capture.current = undefined;
        setTake(null);
        setState("idle");
        setSavedNotice(true);
        saved();
      }
    } catch (cause) {
      if (alive.current) {
        setState("ready");
        const code = String(cause).replace(/^Error: /, "");
        setError(
          ["import_request_conflict", "asset_in_trash"].includes(code)
            ? code
            : "recording_save_failed",
        );
      }
    }
  }
  async function confirmDiscard() {
    if (!discard) return;
    setState("stopping");
    const okay = await journal.remove(
      discard === "current" ? undefined : discard,
    );
    if (!alive.current) return;
    if (!okay) {
      setState(take ? "ready" : "idle");
      return;
    }
    if (discard === "current") {
      capture.current = undefined;
      setTake(null);
      setSeconds(0);
      setError("");
    }
    setDiscard(null);
    setState("idle");
  }
  useEditorAction(
    "recordActiveProject",
    preRoll || countdown ? "recordingPrepare" : "recordingStart",
    !locked && !!projectId,
    start,
  );
  useEditorAction(
    "stopActiveRecording",
    "recordingStop",
    state === "recording" || state === "paused",
    stop,
  );
  return (
    <section className="panel recorder">
      <h3>{t("recording")}</h3>
      <p>{t("recordingHint")}</p>
      <div className="toolbar">
        <label>
          {t("recordingDevice")}
          <select
            value={device}
            disabled={locked}
            onChange={(e) => setDevice(e.target.value)}
          >
            <option value="">{t("recordingDefault")}</option>
            {devices.map((d, i) => (
              <option key={d.deviceId || i} value={d.deviceId}>
                {d.label || `${t("recordingDevice")} ${i + 1}`}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("recordingRate")}
          <select
            value={rate}
            disabled={locked}
            onChange={(e) => setRate(Number(e.target.value))}
          >
            {[24000, 44100, 48000].map((v) => (
              <option key={v} value={v}>
                {v} Hz
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("recordingChannels")}
          <select
            value={channels}
            disabled={locked}
            onChange={(e) => setChannels(Number(e.target.value))}
          >
            <option value={1}>Mono</option>
            <option value={2}>Stereo</option>
          </select>
        </label>
        <label>
          {t("recordingGain")} {gain.toFixed(1)}×
          <input
            type="range"
            min="0"
            max="4"
            step="0.1"
            value={gain}
            disabled={["ready", "saving"].includes(state)}
            onChange={(e) => {
              const value = Number(e.target.value);
              setGain(value);
              capture.current?.setGain(value);
            }}
          />
        </label>
      </div>
      <div className="toolbar">
        <label>
          {t("recordingPreRoll")}
          <select
            value={preRoll}
            disabled={locked}
            onChange={(e) => setPreRoll(Number(e.target.value))}
          >
            {[0, 1, 2, 3, 5].map((v) => (
              <option key={v} value={v}>
                {v} s
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("recordingCountdown")}
          <select
            value={countdown}
            disabled={locked}
            onChange={(e) => setCountdown(Number(e.target.value))}
          >
            {[0, 3, 5].map((v) => (
              <option key={v} value={v}>
                {v} s
              </option>
            ))}
          </select>
        </label>
      </div>
      <LiveWaveform peaks={peaks} label={t("recordingWaveform")} />
      <div className="toolbar">
        <output aria-label={t("recordingDuration")}>
          {seconds.toFixed(1)} s
        </output>
        <meter
          aria-label={t("recordingLevel")}
          min={0}
          max={1}
          high={0.95}
          value={peak}
        />
        {state === "idle" && (
          <button
            disabled={journal.loading || !!discard}
            onClick={() => void start()}
          >
            {t(preRoll || countdown ? "recordingPrepare" : "recordingStart")}
          </button>
        )}
        {state === "armed" && (
          <>
            <p>{t("recordingArmed")}</p>
            <button onClick={record}>{t("recordingStart")}</button>
          </>
        )}
        {state === "countdown" && (
          <output role="status">
            {t("recordingCountdown")}: {remaining}
          </output>
        )}
        {["armed", "countdown"].includes(state) && (
          <button onClick={() => void cancelPreparation()}>
            {t("cancel")}
          </button>
        )}
        {["recording", "paused"].includes(state) && (
          <>
            <button
              onClick={() => {
                const paused = state === "recording";
                capture.current?.pause(paused);
                setState(paused ? "paused" : "recording");
              }}
            >
              {t(state === "recording" ? "recordingPause" : "recordingResume")}
            </button>
            <button onClick={() => void stop()}>{t("recordingStop")}</button>
          </>
        )}
        {["starting", "stopping", "saving"].includes(state) && (
          <span role="status">{t("recordingWorking")}</span>
        )}
      </div>
      {error && <p role="alert">{t(error as Key)}</p>}
      {journal.failed && <p role="alert">{t("recording_storage_failed")}</p>}
      {url && <audio controls src={url} />}
      {state === "ready" && (
        <div className="toolbar">
          <button disabled={!!discard} onClick={() => void save()}>
            {t("recordingSave")}
          </button>
          <button onClick={() => setDiscard("current")}>
            {t("recordingDiscard")}
          </button>
        </div>
      )}
      {state === "idle" && journal.drafts.length > 0 && (
        <div className="panel">
          <h4>{t("recordingRecovery")}</h4>
          <p>{t("recordingRecoveryHint")}</p>
          {journal.drafts.map((draft) => (
            <div className="toolbar" key={draft.id}>
              <span>
                {new Date(draft.created).toLocaleString()} ·{" "}
                {(draft.samples / draft.channels / draft.rate).toFixed(1)} s
              </span>
              <button
                disabled={!draft.samples || !!discard}
                onClick={async () => {
                  setState("starting");
                  try {
                    const value = await journal.recover(draft.id);
                    if (alive.current) {
                      setTake(value);
                      setSeconds(value.seconds);
                      setState("ready");
                      setError("");
                    }
                  } catch {
                    if (alive.current) {
                      setState("idle");
                      setError("recording_recovery_failed");
                    }
                  }
                }}
              >
                {t("recordingRecover")}
              </button>
              <button disabled={!!discard} onClick={() => setDiscard(draft.id)}>
                {t("recordingDiscard")}
              </button>
            </div>
          ))}
        </div>
      )}
      {discard && (
        <div role="alert">
          <p>{t("recordingDiscardConfirm")}</p>
          <button
            disabled={state === "stopping"}
            onClick={() => void confirmDiscard()}
          >
            {t("recordingDiscard")}
          </button>
          <button
            disabled={state === "stopping"}
            onClick={() => setDiscard(null)}
          >
            {t("cancel")}
          </button>
        </div>
      )}
      {savedNotice && <p role="status">{t("recordingSaved")}</p>}
    </section>
  );
}

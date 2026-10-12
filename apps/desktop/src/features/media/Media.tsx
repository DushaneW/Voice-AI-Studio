import { useEffect, useRef, useState } from "react";
import type { Asset, Job, Analysis } from "../../types/domain";
import type { Key } from "../../app/i18n";
import { audioUrl, request } from "../../services/runtime";
import { Waveform } from "../../components/audio/Waveform";
export function Media({
  assets,
  selected,
  onSelect,
  jobs,
  onAnalyze,
  onExport,
  onTrash,
  t,
}: {
  assets: Asset[];
  selected: Asset | null;
  onSelect: (id: string) => void;
  jobs: Job[];
  onAnalyze: () => void;
  onExport: () => void;
  onTrash: () => void;
  t: (k: Key) => string;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [url, setUrl] = useState("");
  const [position, setPosition] = useState(0);
  const [error, setError] = useState(false);
  const [cached, setCached] = useState<Analysis | null>(null);
  const [cacheError, setCacheError] = useState(false);
  useEffect(() => {
    let live = true;
    setCached(null);
    setCacheError(false);
    if (selected)
      void request<{ analysis: Analysis | null }>(
        "GET",
        `/v1/assets/${selected.id}/waveform`,
      )
        .then((value) => {
          if (live) setCached(value.analysis);
        })
        .catch(() => {
          if (live) setCacheError(true);
        });
    return () => {
      live = false;
    };
  }, [selected?.id]);
  useEffect(() => {
    let live = true;
    let objectUrl = "";
    setUrl("");
    setPosition(0);
    setError(false);
    if (selected && selected.size <= 32 * 1048576)
      audioUrl(selected.id)
        .then((u) => {
          objectUrl = u;
          if (live) setUrl(u);
          else URL.revokeObjectURL(u);
        })
        .catch(() => {
          if (live) setError(true);
        });
    return () => {
      live = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [selected?.id]);
  const analysisJob = jobs.find(
    (j) =>
      j.asset_id === selected?.id &&
      j.state === "completed" &&
      j.kind === "analyze",
  );
  const result =
    (analysisJob?.kind === "analyze" ? analysisJob.result : null) ?? cached;
  const seek = (ratio: number) => {
    if (audio.current && Number.isFinite(audio.current.duration)) {
      audio.current.currentTime = ratio * audio.current.duration;
      setPosition(ratio);
    }
  };
  return (
    <>
      <div className="asset-list">
        {assets.map((a) => (
          <button
            key={a.id}
            className={a.id === selected?.id ? "selected" : ""}
            onClick={() => onSelect(a.id)}
          >
            {a.name}
            <small>
              {a.duration.toFixed(1)} s · {a.sample_rate} Hz
            </small>
          </button>
        ))}
      </div>
      {!selected ? (
        <div className="empty">
          <h3>{t("emptyMedia")}</h3>
          <p>{t("emptyMediaDetail")}</p>
        </div>
      ) : (
        <section className="panel">
          <div className="toolbar">
            <h3>{selected.name}</h3>
            <button onClick={onAnalyze}>{t("analyze")}</button>
            <button onClick={onExport}>{t("export")}</button>
            <button onClick={onTrash}>{t("moveToTrash")}</button>
          </div>
          {result ? (
            <>
              <Waveform
                peaks={result.peaks}
                position={position}
                onSeek={seek}
                label={t("waveform")}
              />
              <p>
                {t("peak")}: {result.peak_dbfs?.toFixed(2) ?? t("silence")} dBFS
                · {t("rms")}: {result.rms_dbfs?.toFixed(2) ?? t("silence")} dBFS
              </p>
            </>
          ) : (
            <div className="empty">
              {t(cacheError ? "waveformCacheError" : "waveformEmpty")}
            </div>
          )}
          {url ? (
            <audio
              ref={audio}
              controls
              src={url}
              onTimeUpdate={() => {
                if (audio.current)
                  setPosition(
                    audio.current.currentTime / audio.current.duration || 0,
                  );
              }}
            />
          ) : (
            <p>
              {selected.size > 32 * 1048576
                ? t("audioTooLarge")
                : error
                  ? t("runtime_unavailable")
                  : t("loadingAudio")}
            </p>
          )}
        </section>
      )}
    </>
  );
}

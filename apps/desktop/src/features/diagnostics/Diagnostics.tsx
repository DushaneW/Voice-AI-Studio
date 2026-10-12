import type { Diagnostics as Data } from "../../types/domain";
import type { Key } from "../../app/i18n";
export function Diagnostics({
  data,
  t,
}: {
  data: Data | null;
  t: (k: Key) => string;
}) {
  const gib = (n: number | null | undefined) =>
    n == null ? "—" : (n / 1073741824).toFixed(2) + " GiB";
  const rows: [Key, string][] = [
    ["runtime", data ? t("ready") : t("unavailable")],
    ["platform", data?.os ?? "—"],
    ["python", data?.python ?? "—"],
    ["cpu", String(data?.cpu_logical ?? "—")],
    ["cpuModel", data?.host?.cpu_model ?? "—"],
    ["cpuPhysical", String(data?.host?.cpu_physical ?? "—")],
    ["architecture", data?.host?.architecture ?? "—"],
    ["ramTotal", gib(data?.host?.ram_total)],
    ["ramAvailable", gib(data?.host?.ram_available)],
    ["processMemory", gib(data?.host?.process_rss)],
    [
      "freeStorage",
      data ? (data.storage_free / 1073741824).toFixed(1) + " GiB" : "—",
    ],
    [
      "ffmpeg",
      data ? t(data.ffmpeg_available ? "available" : "notDetected") : "—",
    ],
    [
      "gpu",
      data
        ? t(data.gpu.state === "available" ? "available" : "unavailable")
        : "—",
    ],
    ["schema", String(data?.database_schema ?? "—")],
  ];
  return (
    <div className="diagnostic-grid">
      {data?.gpu_inventory?.devices.map((device) => (
        <div className="panel" key={device.index}>
          <small>{device.vendor}</small>
          <strong>{device.name}</strong>
          <p>
            VRAM: {gib(device.vram_free)} / {gib(device.vram_total)}
          </p>
        </div>
      ))}
      {data?.engines?.map((engine) => (
        <div className="panel" key={engine.id}>
          <small>{engine.id}</small>
          <strong>
            {engine.installed
              ? (engine.version ?? t("available"))
              : t("notDetected")}
          </strong>
        </div>
      ))}
      {rows.map(([k, v]) => (
        <div className="panel" key={k}>
          <small>{t(k)}</small>
          <strong>{v}</strong>
        </div>
      ))}
    </div>
  );
}

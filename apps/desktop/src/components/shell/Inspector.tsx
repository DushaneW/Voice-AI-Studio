import { SlidersHorizontal } from "lucide-react";
import type { Asset, Project } from "../../types/domain";
import type { Key } from "../../app/i18n";
export function Inspector({
  asset,
  project,
  t,
}: {
  asset: Asset | null;
  project: Project | null;
  t: (k: Key) => string;
}) {
  return (
    <aside className="inspector">
      <header>
        <SlidersHorizontal size={15} />
        {t("inspector")}
      </header>
      <div className="inspector-body">
        <span className="eyebrow">{t("selection")}</span>
        {asset ? (
          <>
            <h3>{asset.name}</h3>
            <dl>
              <dt>{t("duration")}</dt>
              <dd>{asset.duration.toFixed(2)} s</dd>
              <dt>{t("sampleRate")}</dt>
              <dd>{asset.sample_rate.toLocaleString()} Hz</dd>
              <dt>{t("channels")}</dt>
              <dd>{asset.channels}</dd>
              <dt>{t("size")}</dt>
              <dd>{(asset.size / 1048576).toFixed(2)} MiB</dd>
            </dl>
            <span className="eyebrow">SHA-256</span>
            <code className="hash">{asset.sha256}</code>
          </>
        ) : project ? (
          <>
            <h3>{project.name}</h3>
            <dl>
              <dt>{t("assets")}</dt>
              <dd>{project.asset_count}</dd>
              <dt>{t("duration")}</dt>
              <dd>{project.duration.toFixed(1)} s</dd>
              <dt>{t("schema")}</dt>
              <dd>{project.schema_version}</dd>
            </dl>
          </>
        ) : (
          <p>{t("noSelection")}</p>
        )}
      </div>
    </aside>
  );
}

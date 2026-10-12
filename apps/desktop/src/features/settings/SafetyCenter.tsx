import { useEffect, useState } from "react";
import { request } from "../../services/runtime";
import type { Key } from "../../app/i18n";
interface Report {
  api: {
    authentication: string;
    browser_origins: string;
    packaged_bind: string;
  };
  workspace: {
    private: boolean | null;
    entries: {
      name: string;
      exists: boolean;
      symlink: boolean;
      private: boolean | null;
    }[];
  };
  models: { id: string; state: string; error: string | null }[];
}
interface Privacy {
  model_downloads_allowed: boolean;
  active_model_operations: { id: string; state: string }[];
  catalog_download_hosts: string[];
}
export function SafetyCenter({ t }: { t: (key: Key) => string }) {
  const [security, setSecurity] = useState<Report | null>(null),
    [privacy, setPrivacy] = useState<Privacy | null>(null),
    [failed, setFailed] = useState(false),
    [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const [s, p] = await Promise.all([
          request<Report>("GET", "/v1/security"),
          request<Privacy>("GET", "/v1/privacy"),
        ]);
        if (live) {
          setSecurity(s);
          setPrivacy(p);
          setFailed(false);
        }
      } catch {
        if (live) setFailed(true);
      } finally {
        if (live) timer = setTimeout(load, 5000);
      }
    }
    void load();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [refresh]);
  const measured = (value: boolean | null) =>
    value === null
      ? t("notInspected")
      : t(value ? "privateAccess" : "sharedAccess");
  return (
    <section aria-label={t("safetyCenter")}>
      <h3>{t("safetyCenter")}</h3>
      <button onClick={() => setRefresh((n) => n + 1)}>
        {t("storageRefresh")}
      </button>
      {failed && <p role="alert">{t("unknownError")}</p>}
      {security && (
        <>
          <p>
            {t("apiProtection")}: {security.api.authentication} ·{" "}
            {security.api.browser_origins} · {security.api.packaged_bind}
          </p>
          <p>
            {t("workspacePermissions")}: {measured(security.workspace.private)}
          </p>
          <table>
            <thead>
              <tr>
                <th>{t("storageCategory")}</th>
                <th>{t("status")}</th>
              </tr>
            </thead>
            <tbody>
              {security.workspace.entries
                .filter((e) => e.exists)
                .map((e) => (
                  <tr key={e.name}>
                    <td>{e.name}</td>
                    <td>
                      {e.symlink
                        ? t("symbolicLinkWarning")
                        : measured(e.private)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          <p>{t("modelVerificationPolicy")}</p>
          <ul>
            {security.models.map((m) => (
              <li key={m.id}>
                {m.id}: {m.state}
                {m.error ? ` (${m.error})` : ""}
              </li>
            ))}
          </ul>
        </>
      )}
      {privacy && (
        <>
          <h4>{t("privacyLocal")}</h4>
          <p>{t("privacyScope")}</p>
          <p>
            {t(
              privacy.model_downloads_allowed
                ? "modelDownloadsAllowed"
                : "modelDownloadsBlocked",
            )}
          </p>
          <p>
            {t("activeModelOperations")}:{" "}
            {privacy.active_model_operations.length}
          </p>
          <p>
            {t("downloadHosts")}: {privacy.catalog_download_hosts.join(", ")}
          </p>
        </>
      )}
    </section>
  );
}

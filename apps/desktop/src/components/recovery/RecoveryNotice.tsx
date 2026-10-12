import type { Key } from "../../app/i18n";
export function RecoveryNotice({
  pending,
  status,
  revision,
  recover,
  discard,
  t,
}: {
  pending: { revision: number; updated: string } | null;
  status: "idle" | "saved" | "error";
  revision: number;
  recover: () => void;
  discard: () => void;
  t: (key: Key) => string;
}) {
  return (
    <div
      role={pending || status === "error" ? "alert" : "status"}
      aria-live="polite"
    >
      {pending ? (
        <section className="panel">
          <strong>{t("recoverDraft")}</strong>
          <p>
            {t(
              pending.revision === revision
                ? "recoverDraftDetail"
                : "recoverDraftConflict",
            )}
          </p>
          <p>{new Date(pending.updated).toLocaleString()}</p>
          <button onClick={recover}>{t("recoverDraft")}</button>
          <button onClick={discard}>{t("discardDraft")}</button>
        </section>
      ) : status === "error" ? (
        <p>{t("draftStorageError")}</p>
      ) : status === "saved" ? (
        <small>{t("draftSaved")}</small>
      ) : null}
    </div>
  );
}

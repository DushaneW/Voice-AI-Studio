import { useEffect, useState } from "react";
import { Modal } from "../../components/dialogs/Modal";
import { DocumentHistory } from "../../components/history/DocumentHistory";
import {
  useNavigationGuard,
  useUnsavedChanges,
} from "../../app/UnsavedChanges";
import { request } from "../../services/runtime";
import { useAutosave, AutosaveStatus } from "../../hooks/useAutosave";
import { useEditorSave } from "../../app/commands/EditorCommands";
import { useRecoveryDraft } from "../../hooks/useRecoveryDraft";
import { RecoveryNotice } from "../../components/recovery/RecoveryNotice";
import type { Key } from "../../app/i18n";
interface Metadata {
  description: string;
  author: string;
  language: string;
  tags: string[];
}
const empty: Metadata = { description: "", author: "", language: "", tags: [] };
function valid(value: unknown): value is Metadata {
  const m = value as Metadata | null;
  return (
    !!m &&
    typeof m.description === "string" &&
    m.description.length <= 5000 &&
    typeof m.author === "string" &&
    m.author.length <= 120 &&
    typeof m.language === "string" &&
    m.language.length <= 35 &&
    Array.isArray(m.tags) &&
    m.tags.length <= 20 &&
    m.tags.every((tag) => typeof tag === "string" && tag.length <= 60)
  );
}
export function ProjectMetadata({
  id,
  t,
  onClose,
  onError,
}: {
  id: string;
  t: (key: Key) => string;
  onClose: () => void;
  onError: (error: string) => void;
}) {
  const [content, setContent] = useState<Metadata>(empty),
    [revision, setRevision] = useState(0),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [loaded, setLoaded] = useState(false);
  const clean = useUnsavedChanges(dirty, busy),
    guard = useNavigationGuard(),
    endpoint = `/v1/projects/${id}/documents/project`;
  const draft = useRecoveryDraft({
    scope: `${id}.project`,
    loaded,
    dirty,
    revision,
    content,
    validate: valid,
    apply: (value) => {
      setContent(value);
      setDirty(true);
    },
  });
  useEffect(() => {
    let live = true;
    void request<{ revision: number; content: Metadata }>("GET", endpoint)
      .then((value) => {
        if (live) {
          setContent({ ...empty, ...value.content });
          setRevision(value.revision);
          setLoaded(true);
        }
      })
      .catch((error) => {
        if (live) onError(String(error));
      });
    return () => {
      live = false;
    };
  }, [endpoint]);
  function edit(patch: Partial<Metadata>) {
    setContent((value) => ({ ...value, ...patch }));
    setDirty(true);
  }
  async function save() {
    if (busy || !loaded || draft.pending) return false;
    setBusy(true);
    try {
      const result = await request<{ revision: number; content: Metadata }>(
        "PUT",
        endpoint,
        {
          revision,
          content: {
            ...content,
            tags: content.tags.map((tag) => tag.trim()).filter(Boolean),
          },
        },
      );
      setContent(result.content);
      setRevision(result.revision);
      setDirty(false);
      draft.clear();
      clean();
      return true;
    } catch (error) {
      onError(String(error));
      return false;
    } finally {
      setBusy(false);
    }
  }
  useEditorSave(dirty && loaded && !busy && !draft.pending, save);
  const autosave = useAutosave(dirty, busy || !loaded || !!draft.pending, save);
  return (
    <Modal
      title={t("projectMetadata")}
      closeLabel={t("close")}
      onClose={() => guard.confirm(onClose)}
    >
      <AutosaveStatus state={autosave} t={t} />
      <RecoveryNotice
        pending={draft.pending}
        status={draft.status}
        revision={revision}
        recover={draft.recover}
        discard={draft.clear}
        t={t}
      />
      <fieldset disabled={!loaded || busy || !!draft.pending}>
        <label>
          {t("projectAuthor")}
          <input
            maxLength={120}
            value={content.author}
            onChange={(e) => edit({ author: e.target.value })}
          />
        </label>
        <label>
          {t("language")}
          <input
            maxLength={35}
            value={content.language}
            onChange={(e) => edit({ language: e.target.value })}
          />
        </label>
        <label>
          {t("projectDescription")}
          <textarea
            maxLength={5000}
            value={content.description}
            onChange={(e) => edit({ description: e.target.value })}
          />
        </label>
        <label>
          {t("projectTags")}
          <input
            value={content.tags.join(",")}
            onChange={(e) => edit({ tags: e.target.value.split(",") })}
          />
        </label>
        <button disabled={!dirty} onClick={() => void save()}>
          {t("save")}
        </button>
      </fieldset>
      <DocumentHistory
        projectId={id}
        kind="project"
        revision={revision}
        disabled={!loaded || dirty || busy || !!draft.pending}
        t={t}
        onBusy={setBusy}
        onError={onError}
        onRestore={(document) => {
          setContent({ ...empty, ...document.content } as Metadata);
          setRevision(document.revision);
          setDirty(false);
          draft.clear();
          clean();
        }}
      />
    </Modal>
  );
}

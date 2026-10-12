import { useState } from "react";
import { ProjectMetadata } from "../features/projects/ProjectMetadata";
import { EditorCommandsProvider } from "./commands/EditorCommands";
import { AutosaveInterval } from "../hooks/useAutosave";
import { Notifications } from "../features/jobs/Notifications";
import { GlobalSearch } from "../components/shell/GlobalSearch";
import { VoiceLibrary } from "../features/speech/VoiceLibrary";
import { Recorder } from "../features/recording/Recorder";
import { Workflows } from "../features/workflows/Workflows";
import { RuntimeRecovery } from "../components/runtime/RuntimeRecovery";
import { VERSION } from "./version";
import { Trash } from "../features/projects/Trash";
import { errorMessage } from "./i18n";
import { UnsavedChangesProvider } from "./UnsavedChanges";
import { Production } from "../features/speech/Production";
import { Timeline } from "../features/timeline/Timeline";
import { Models } from "../features/models/Models";
import { Speech } from "../features/speech/Speech";
import { Transcription } from "../features/speech/Transcription";
import { AudioLines, Plus, Search } from "lucide-react";
import { Sidebar } from "../components/shell/Sidebar";
import { Inspector } from "../components/shell/Inspector";
import { CommandPalette } from "../components/shell/CommandPalette";
import { Modal } from "../components/dialogs/Modal";
import { Projects } from "../features/projects/Projects";
import { Media } from "../features/media/Media";
import { Jobs } from "../features/jobs/Jobs";
import { Diagnostics } from "../features/diagnostics/Diagnostics";
import { Settings } from "../features/settings/Settings";
import {
  request,
  native,
  importAudio,
  exportAudio,
  exportDiagnostics,
  backupProject,
  restoreProject,
} from "../services/runtime";
import { useWorkstation } from "./useWorkstation";
export default function App() {
  return (
    <EditorCommandsProvider>
      <UnsavedChangesProvider>
        <AppContent />
      </UnsavedChangesProvider>
    </EditorCommandsProvider>
  );
}
function AppContent() {
  const [metadataId, setMetadataId] = useState<string | null>(null);
  const {
    closeProject,
    jobTarget,
    openJob,
    searchOpen,
    setSearchOpen,
    searchTarget,
    openSearchResult,
    prefs,
    projects,
    assets,
    jobs,
    report,
    ready,
    runtimeError,
    busy,
    projectId,
    project,
    asset,
    palette,
    setPalette,
    dialog,
    setDialog,
    setTarget,
    name,
    setName,
    template,
    setTemplate,
    notice,
    setNotice,
    t,
    page,
    refresh,
    operation,
    changePrefs,
    navigate,
    newProject,
    open,
    commands,
    submit,
    setAssetId,
  } = useWorkstation();
  return (
    <AutosaveInterval.Provider value={prefs.autosave_seconds ?? 0}>
      <div className="application">
        {metadataId && (
          <ProjectMetadata
            key={metadataId}
            id={metadataId}
            t={t}
            onClose={() => setMetadataId(null)}
            onError={(error) => setNotice(errorMessage(error, prefs.language))}
          />
        )}
        <header className="titlebar">
          <div className="brand">
            <AudioLines size={21} />
            <b>NEXUS</b>
            <span>{t("subtitle")}</span>
          </div>
          {project && (
            <button onClick={closeProject}>{t("closeProject")}</button>
          )}
          <Notifications ready={ready} t={t} onOpenJob={openJob} />
          <button disabled={!ready} onClick={() => setSearchOpen(true)}>
            {t("globalSearch")}
          </button>
          <button onClick={() => setPalette(true)}>
            <Search size={14} />
            {t("palette")}
            <kbd>Ctrl / ⌘ K</kbd>
          </button>
        </header>
        <div className="body">
          <Sidebar
            collapsed={prefs.sidebar_collapsed ?? false}
            onToggle={() =>
              changePrefs({
                ...prefs,
                sidebar_collapsed: !prefs.sidebar_collapsed,
              })
            }
            page={page}
            setPage={navigate}
            t={t}
          />
          <main>
            <div className="breadcrumb">
              {t("workspace")} / {t(page)}
              <button onClick={() => setDialog("about")}>{t("about")}</button>
            </div>
            {!ready &&
              (native ? (
                <RuntimeRecovery
                  code={runtimeError}
                  t={t}
                  onRestart={refresh}
                />
              ) : (
                <div className="runtime-banner" role="status">
                  ● {t("desktopRequired")}
                </div>
              ))}
            <div className="workspace">
              <header className="page-heading">
                <div>
                  <span className="eyebrow">
                    {project?.name ?? "NEXUS WORKSTATION"}
                  </span>
                  <h1>{page === "home" ? t("welcome") : t(page)}</h1>
                  <p>
                    {page === "home"
                      ? t("homeDescription")
                      : page === "media"
                        ? t("mediaDescription")
                        : page === "jobs"
                          ? t("jobsDescription")
                          : page === "settings"
                            ? t("settingsDescription")
                            : page === "diagnostics"
                              ? t("diagnosticsDescription")
                              : t("emptyProjectsDetail")}
                  </p>
                </div>
                {["home", "projects"].includes(page) && (
                  <button
                    className="primary"
                    disabled={!ready || busy}
                    onClick={newProject}
                  >
                    <Plus size={16} />
                    {t("newProject")}
                  </button>
                )}
                {(page === "projects" || page === "media") && (
                  <Trash
                    t={t}
                    onChanged={refresh}
                    onError={(error) =>
                      setNotice(errorMessage(error, prefs.language))
                    }
                  />
                )}
                {page === "media" && (
                  <button
                    className="primary"
                    disabled={!ready || !project || busy}
                    onClick={() =>
                      void operation(() => importAudio(projectId), "imported")
                    }
                  >
                    {t("importAudio")}
                  </button>
                )}
              </header>
              {page === "home" && (
                <div className="session-note">
                  <AudioLines size={24} />
                  <div>
                    <strong>{t("activeProject")}</strong>
                    <p>{project?.name ?? t("noProject")}</p>
                  </div>
                  <button onClick={() => navigate("projects")}>
                    {t("openProject")}
                  </button>
                </div>
              )}
              {page === "projects" && (
                <div className="toolbar">
                  <button
                    disabled={!ready || busy}
                    onClick={() => void operation(restoreProject, "saved")}
                  >
                    {t("restoreProject")}
                  </button>
                  <button
                    disabled={!ready || !project || busy}
                    onClick={() =>
                      void operation(() => backupProject(projectId), "exported")
                    }
                  >
                    {t("backupProject")}
                  </button>
                </div>
              )}
              {(page === "home" || page === "projects") && (
                <Projects
                  items={projects}
                  recentIds={prefs.recent_project_ids}
                  onMetadata={(p) => setMetadataId(p.id)}
                  onRepair={(p) =>
                    void operation(async () => {
                      await request("POST", `/v1/projects/${p.id}/repair-plan`);
                      navigate("jobs");
                    })
                  }
                  onOpen={open}
                  busy={busy}
                  onValidate={(p) =>
                    void operation(async () => {
                      await request("POST", `/v1/projects/${p.id}/validate`);
                      navigate("jobs");
                    })
                  }
                  onDuplicate={(p) =>
                    void operation(async () => {
                      const key = "nexus-copy-request:" + p.id;
                      let requestId = localStorage.getItem(key);
                      if (!requestId) {
                        requestId = crypto.randomUUID();
                        localStorage.setItem(key, requestId);
                      }
                      await request("POST", `/v1/projects/${p.id}/duplicate`, {
                        request_id: requestId,
                        name: (p.name + " — " + t("copy")).slice(0, 120),
                      });
                      localStorage.removeItem(key);
                      navigate("jobs");
                    })
                  }
                  onEdit={(p) => {
                    setTarget(p);
                    setName(p.name);
                    setDialog("rename");
                  }}
                  onDelete={(p) => {
                    setTarget(p);
                    setDialog("delete");
                  }}
                  onFavorite={(p) =>
                    void operation(() =>
                      request("PATCH", "/v1/projects/" + p.id, {
                        name: p.name,
                        favorite: !p.favorite,
                      }),
                    )
                  }
                  t={t}
                />
              )}
              {(page === "projects" || page === "media") && (
                <Trash
                  t={t}
                  onChanged={refresh}
                  onError={(error) =>
                    setNotice(errorMessage(error, prefs.language))
                  }
                />
              )}
              {page === "media" && projectId && (
                <Recorder
                  defaults={prefs}
                  key={projectId}
                  projectId={projectId}
                  t={t}
                  saved={() => void refresh()}
                />
              )}
              {page === "media" && (
                <Media
                  assets={assets.filter((a) => a.project_id === projectId)}
                  selected={asset}
                  onSelect={setAssetId}
                  jobs={jobs}
                  onAnalyze={() =>
                    asset &&
                    void operation(
                      () => request("POST", "/v1/jobs", { asset_id: asset.id }),
                      "analysisQueued",
                    )
                  }
                  onTrash={() =>
                    asset &&
                    void operation(
                      () => request("DELETE", "/v1/assets/" + asset.id),
                      "movedToTrash",
                    )
                  }
                  onExport={() =>
                    asset &&
                    void operation(() => exportAudio(asset.id), "exported")
                  }
                  t={t}
                />
              )}
              {page === "jobs" && (
                <Jobs
                  targetId={jobTarget}
                  onChanged={refresh}
                  onError={(error) =>
                    setNotice(errorMessage(error, prefs.language))
                  }
                  jobs={jobs}
                  assets={assets}
                  onOpenProject={(id) => {
                    const p = projects.find((p) => p.id === id);
                    if (p) open(p);
                  }}
                  onOpenAsset={(id) => {
                    const a = assets.find((a) => a.id === id);
                    const p = projects.find((p) => p.id === a?.project_id);
                    if (p) {
                      openSearchResult("assets", {
                        id,
                        asset_id: id,
                        project_id: p.id,
                        label: a?.name ?? "",
                      });
                    }
                  }}
                  onAction={(id, action) =>
                    void operation(() =>
                      request("POST", "/v1/jobs/" + id + "/" + action),
                    )
                  }
                  t={t}
                />
              )}
              {(page === "audiobook" || page === "dubbing") && (
                <Production
                  key={page + projectId}
                  mode={page}
                  projectId={projectId}
                  t={t}
                  onError={(error) =>
                    setNotice(errorMessage(error, prefs.language))
                  }
                  onQueued={() => navigate("jobs")}
                />
              )}
              {page === "workflows" && (
                <Workflows
                  key={projectId}
                  projectId={projectId}
                  assets={assets.filter(
                    (asset) => asset.project_id === projectId,
                  )}
                  t={t}
                  onError={(error) =>
                    setNotice(errorMessage(error, prefs.language))
                  }
                />
              )}
              {page === "timeline" && (
                <Timeline
                  defaults={prefs}
                  key={projectId}
                  projectId={projectId}
                  assets={assets.filter((a) => a.project_id === projectId)}
                  t={t}
                  onError={(error) =>
                    setNotice(errorMessage(error, prefs.language))
                  }
                  onQueued={() => {
                    setNotice(t("analysisQueued"));
                    navigate("jobs");
                  }}
                />
              )}
              {page === "models" && (
                <Models
                  onOpenJob={openJob}
                  t={t}
                  onError={(error) =>
                    setNotice(errorMessage(error, prefs.language))
                  }
                />
              )}
              {page === "voices" && (
                <VoiceLibrary key={projectId} projectId={projectId} t={t} />
              )}
              {page === "tts" && (
                <Speech
                  defaults={prefs}
                  key={page + projectId}
                  projectId={projectId}
                  t={t}
                  onError={(error) =>
                    setNotice(errorMessage(error, prefs.language))
                  }
                  onQueued={() => {
                    setNotice(t("analysisQueued"));
                    navigate("jobs");
                  }}
                />
              )}
              {page === "transcription" && (
                <Transcription
                  defaults={prefs}
                  key={
                    projectId +
                    (searchTarget?.id ?? "") +
                    (searchTarget?.segment ?? "")
                  }
                  initialAssetId={searchTarget?.asset_id}
                  initialTranscriptId={searchTarget?.id}
                  initialSegment={searchTarget?.segment}
                  assets={assets.filter((a) => a.project_id === projectId)}
                  t={t}
                  onError={(error) =>
                    setNotice(errorMessage(error, prefs.language))
                  }
                  onQueued={() => {
                    setNotice(t("analysisQueued"));
                    void refresh();
                  }}
                />
              )}
              {page === "settings" && (
                <Settings value={prefs} onChange={changePrefs} t={t} />
              )}
              {page === "diagnostics" && (
                <>
                  <div className="toolbar">
                    <button onClick={() => void refresh()}>
                      {t("runDiagnostics")}
                    </button>
                    <button
                      disabled={!ready}
                      onClick={() =>
                        void operation(exportDiagnostics, "exported")
                      }
                    >
                      {t("exportReport")}
                    </button>
                  </div>
                  <Diagnostics data={report} t={t} />
                </>
              )}
            </div>
          </main>
          {prefs.inspector && (
            <Inspector asset={asset} project={project} t={t} />
          )}
        </div>
        <footer>
          <span>
            ● {t("runtime")}: {t(ready ? "ready" : "unavailable")}
          </span>
          <span>
            {t("jobs")}:{" "}
            {ready
              ? jobs.filter((j) => ["queued", "running"].includes(j.state))
                  .length
              : "—"}
          </span>
          <span>CPU {report?.cpu_logical ?? "—"} · GPU —</span>
          <span className="footer-end">
            {t("localOnly")} · {VERSION}
          </span>
        </footer>
        {notice && (
          <div className="toast" role="status">
            {notice}
            <button aria-label={t("dismiss")} onClick={() => setNotice("")}>
              ×
            </button>
          </div>
        )}
        {searchOpen && (
          <GlobalSearch
            t={t}
            onClose={() => setSearchOpen(false)}
            onOpen={openSearchResult}
          />
        )}
        {palette && (
          <CommandPalette
            commands={commands}
            t={t}
            onClose={() => setPalette(false)}
          />
        )}
        {dialog && (
          <Modal
            closeLabel={t("close")}
            title={t(
              dialog === "new"
                ? "newProject"
                : dialog === "rename"
                  ? "rename"
                  : dialog === "delete"
                    ? "deleteTitle"
                    : "about",
            )}
            onClose={() => setDialog(null)}
          >
            {dialog === "about" ? (
              <p>{t("info")}</p>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void submit();
                }}
              >
                {dialog === "new" && (
                  <label>
                    {t("projectTemplate")}
                    <select
                      aria-label={t("projectTemplate")}
                      value={template}
                      onChange={(e) => setTemplate(e.target.value)}
                    >
                      <option value="empty">{t("templateEmpty")}</option>
                      <option value="podcast">{t("templatePodcast")}</option>
                      <option value="multitrack">
                        {t("templateMultitrack")}
                      </option>
                      <option value="audiobook">{t("audiobook")}</option>
                    </select>
                  </label>
                )}
                {dialog === "delete" ? (
                  <p>{t("deleteDetail")}</p>
                ) : (
                  <label>
                    {t("projectName")}
                    <input
                      autoFocus
                      required
                      maxLength={120}
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </label>
                )}
                <div className="dialog-actions">
                  <button type="button" onClick={() => setDialog(null)}>
                    {t("cancel")}
                  </button>
                  <button
                    className="primary"
                    disabled={
                      busy || !ready || (dialog !== "delete" && !name.trim())
                    }
                  >
                    {t(dialog === "delete" ? "remove" : "save")}
                  </button>
                </div>
              </form>
            )}
          </Modal>
        )}
      </div>
    </AutosaveInterval.Provider>
  );
}

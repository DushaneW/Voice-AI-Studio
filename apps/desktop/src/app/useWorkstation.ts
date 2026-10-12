import { useEditorCommands } from "./commands/EditorCommands";
import type { SearchHit, SearchKind } from "../components/shell/GlobalSearch";
import { useNavigationGuard } from "./UnsavedChanges";
import { useCallback, useEffect, useRef, useState } from "react";
import { request, importAudio, exportAudio } from "../services/runtime";
import type {
  Project,
  Asset,
  Job,
  Settings as Preferences,
  Diagnostics as Report,
  Workspace,
} from "../types/domain";
import { translator, type Key, en } from "./i18n";
import { isWorkspaceEnabled, visibleWorkspace } from "./features";
import { runShortcut, type Command } from "./commands/registry";
export function useWorkstation() {
  const editorCommands = useEditorCommands();
  const guard = useNavigationGuard();
  const sessionTouched = useRef(false);
  const preferenceWrites = useRef<Promise<unknown>>(Promise.resolve());
  function recent(id: string) {
    return [
      id,
      ...(prefs.recent_project_ids ?? []).filter((value) => value !== id),
    ].slice(0, 20);
  }
  const [prefs, setPrefs] = useState<Preferences>({
    language: "en",
    workspace: "home",
    inspector: true,
  });
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: light)");
    function applyTheme() {
      document.documentElement.dataset.theme =
        prefs.theme === "system"
          ? media?.matches
            ? "light"
            : "dark"
          : (prefs.theme ?? "dark");
    }
    applyTheme();
    media?.addEventListener("change", applyTheme);
    return () => media?.removeEventListener("change", applyTheme);
  }, [prefs.theme]);
  const [jobTarget, setJobTarget] = useState<string | null>(null);
  function openJob(id: string) {
    guard.confirm(() => {
      setJobTarget(id);
      changePrefs({ ...prefs, workspace: "jobs" });
    });
  }
  const [template, setTemplate] = useState("empty");
  const [projects, setProjects] = useState<Project[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [ready, setReady] = useState(false);
  const [runtimeError, setRuntimeError] = useState("");
  const [busy, setBusy] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [assetId, setAssetId] = useState("");
  const [palette, setPalette] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchTarget, setSearchTarget] = useState<SearchHit | null>(null);
  function openSearchResult(kind: SearchKind, hit: SearchHit) {
    guard.confirm(() => {
      setProjectId(hit.project_id);
      setAssetId(hit.asset_id ?? "");
      setSearchTarget(kind === "transcripts" ? hit : null);
      changePrefs({
        ...prefs,
        last_project_id: hit.project_id,
        recent_project_ids: recent(hit.project_id),
        workspace: kind === "transcripts" ? "transcription" : "media",
      });
    });
  }
  const [dialog, setDialog] = useState<
    "new" | "rename" | "delete" | "about" | null
  >(null);
  const [target, setTarget] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [notice, setNotice] = useState("");
  const t = translator(prefs.language),
    page = visibleWorkspace(prefs.workspace);
  const project = projects.find((p) => p.id === projectId) ?? null,
    asset =
      assets.find((a) => a.id === assetId && a.project_id === projectId) ??
      null;
  useEffect(
    () => guard.setLanguage(prefs.language),
    [prefs.language, guard.setLanguage],
  );
  const refreshVersion = useRef(0);
  const refresh = useCallback(async () => {
    const version = ++refreshVersion.current;
    try {
      await request("GET", "/health");
      const [p, a, j, d] = await Promise.all([
        request<Project[]>("GET", "/v1/projects"),
        request<Asset[]>("GET", "/v1/assets"),
        request<Job[]>("GET", "/v1/jobs"),
        request<Report>("GET", "/v1/diagnostics"),
      ]);
      if (version !== refreshVersion.current) return;
      setProjects(p);
      setAssets(a);
      setJobs(j);
      setReport(d);
      setReady(true);
      setRuntimeError("");
    } catch (error) {
      if (version !== refreshVersion.current) return;
      setRuntimeError(String(error instanceof Error ? error.message : error));
      setReady(false);
      setReport(null);
    }
  }, []);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      await refresh();
      if (live) timer = setTimeout(() => void poll(), 2000);
    }
    void poll();
    void request<Preferences>("GET", "/v1/settings")
      .then((value) => {
        if (live && !sessionTouched.current) {
          setPrefs(value);
          setProjectId(value.last_project_id ?? "");
        }
      })
      .catch(() => {});
    return () => {
      live = false;
      refreshVersion.current++;
      clearTimeout(timer);
    };
  }, [refresh]);
  async function operation(fn: () => Promise<unknown>, message?: Key) {
    setBusy(true);
    try {
      const result = await fn();
      await refresh();
      if (message && result !== false) setNotice(t(message));
    } catch (e) {
      const code = String(e instanceof Error ? e.message : e);
      setNotice(t(code in en ? (code as Key) : "unknownError"));
    } finally {
      setBusy(false);
    }
  }
  function changePrefs(value: Preferences) {
    sessionTouched.current = true;
    setPrefs(value);
    if (ready) {
      const write = preferenceWrites.current
        .catch(() => {})
        .then(() => request("PUT", "/v1/settings", value));
      preferenceWrites.current = write;
      void operation(() => write);
    }
  }
  function navigate(workspace: Workspace) {
    if (workspace !== prefs.workspace)
      guard.confirm(() => {
        setSearchTarget(null);
        changePrefs({ ...prefs, workspace });
      });
  }
  function newProject() {
    guard.confirm(() => {
      setName("");
      setTemplate("empty");
      setTarget(null);
      setDialog("new");
    });
  }
  function open(p: Project) {
    guard.confirm(() => {
      setSearchTarget(null);
      setProjectId(p.id);
      setAssetId("");
      changePrefs({
        ...prefs,
        workspace: "media",
        last_project_id: p.id,
        recent_project_ids: recent(p.id),
      });
    });
  }
  function closeProject() {
    guard.confirm(() => {
      setProjectId("");
      setAssetId("");
      setSearchTarget(null);
      changePrefs({ ...prefs, last_project_id: null, workspace: "projects" });
    });
  }
  const commands: Command[] = [
    {
      id: "closeProject",
      label: "closeProject",
      enabled: !!projectId,
      run: closeProject,
    },
    ...editorCommands,
    {
      id: "globalSearch",
      label: "globalSearch",
      shortcut: "mod+p",
      enabled: ready,
      run: () => setSearchOpen(true),
    },
    {
      id: "new",
      label: "newProject",
      shortcut: "mod+n",
      enabled: ready && !busy,
      run: newProject,
    },
    {
      id: "projects",
      label: "openProject",
      shortcut: "mod+o",
      run: () => navigate("projects"),
    },
    {
      id: "palette",
      label: "palette",
      shortcut: "mod+k",
      run: () => setPalette(true),
    },
    {
      id: "exportAudio",
      label: "export",
      enabled: ready && !!asset && !busy,
      run: () => {
        if (asset) void operation(() => exportAudio(asset.id), "exported");
      },
    },
    {
      id: "import",
      label: "importAudio",
      enabled: ready && !!project && !busy,
      run: () => void operation(() => importAudio(projectId), "imported"),
    },
    ...(
      [
        "home",
        "media",
        "jobs",
        "settings",
        "diagnostics",
        "models",
        "tts",
        "transcription",
        "voices",
        "timeline",
        "workflows",
        "audiobook",
        "dubbing",
      ] as Workspace[]
    )
      .filter((id) => isWorkspaceEnabled(id))
      .map((id) => ({ id, label: id, run: () => navigate(id) })),
    {
      id: "inspector",
      label: "inspector",
      run: () => changePrefs({ ...prefs, inspector: !prefs.inspector }),
    },
    { id: "about", label: "about", run: () => setDialog("about") },
  ];
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.defaultPrevented && !dialog && !palette && !searchOpen)
        runShortcut(e, commands);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });
  async function submit() {
    await operation(
      async () => {
        if (dialog === "new") {
          const p = await request<Project>("POST", "/v1/projects", {
            name,
            template,
          });
          setSearchTarget(null);
          setAssetId("");
          setProjectId(p.id);
          changePrefs({
            ...prefs,
            last_project_id: p.id,
            recent_project_ids: recent(p.id),
          });
        } else if (target && dialog === "rename")
          await request("PATCH", "/v1/projects/" + target.id, {
            name,
            favorite: !!target.favorite,
          });
        else if (target && dialog === "delete") {
          await request("DELETE", "/v1/projects/" + target.id);
          if (projectId === target.id) {
            setProjectId("");
            setAssetId("");
            changePrefs({ ...prefs, last_project_id: null });
          }
        }
        setDialog(null);
      },
      dialog === "delete" ? "projectDeleted" : "saved",
    );
  }
  return {
    closeProject,
    jobTarget,
    openJob,
    template,
    setTemplate,
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
  };
}

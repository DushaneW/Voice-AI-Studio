import { VERSION } from "../../app/version";
import {
  AudioLines,
  Workflow,
  Mic,
  Captions,
  Layers,
  BookOpen,
  Clapperboard,
  Music,
  Cpu,
  FolderOpen,
  House,
  ListChecks,
  Settings2,
  Activity,
  PanelLeftClose,
} from "lucide-react";
import type { Workspace } from "../../types/domain";
import { isWorkspaceEnabled } from "../../app/features";
import type { Key } from "../../app/i18n";
const sections: { key: Key; items: { id: Workspace; icon: typeof House }[] }[] =
  [
    {
      key: "workspace",
      items: [
        { id: "home", icon: House },
        { id: "projects", icon: FolderOpen },
        { id: "tts", icon: Mic },
        { id: "transcription", icon: Captions },
        { id: "timeline", icon: Layers },
        { id: "workflows", icon: Workflow },
        { id: "audiobook", icon: BookOpen },
        { id: "dubbing", icon: Clapperboard },
      ],
    },
    {
      key: "library",
      items: [
        { id: "media", icon: Music },
        { id: "voices", icon: AudioLines },
        { id: "models", icon: Cpu },
        { id: "jobs", icon: ListChecks },
      ],
    },
    {
      key: "system",
      items: [
        { id: "settings", icon: Settings2 },
        { id: "diagnostics", icon: Activity },
      ],
    },
  ];
export function Sidebar({
  page,
  collapsed,
  onToggle,
  setPage,
  t,
}: {
  page: Workspace;
  collapsed: boolean;
  onToggle: () => void;
  setPage: (p: Workspace) => void;
  t: (k: Key) => string;
}) {
  return (
    <aside className={"sidebar" + (collapsed ? " collapsed" : "")}>
      <div className="sidebar-caption">
        <span>NEXUS STUDIO</span>
        <button
          aria-label={t("toggleSidebar")}
          aria-expanded={!collapsed}
          onClick={onToggle}
        >
          <PanelLeftClose size={14} />
        </button>
      </div>
      {sections.map((section) => (
        <section key={section.key}>
          <h2>{t(section.key)}</h2>
          {section.items
            .filter(({ id }) => isWorkspaceEnabled(id))
            .map(({ id, icon: Icon }) => (
              <button
                key={id}
                aria-label={t(id)}
                title={collapsed ? t(id) : undefined}
                onClick={() => setPage(id)}
                className={page === id ? "selected" : ""}
                aria-current={page === id ? "page" : undefined}
              >
                <Icon size={17} />
                <span className="nav-label">{t(id)}</span>
                {page === id && <span className="nav-dot" />}
              </button>
            ))}
        </section>
      ))}
      <div className="sidebar-bottom">
        <span className="local-dot" />
        {t("localOnly")}
        <small>v{VERSION}</small>
      </div>
    </aside>
  );
}

import { useState } from "react";
import { FolderOpen, Star } from "lucide-react";
import type { Project } from "../../types/domain";
import type { Key } from "../../app/i18n";
export function Projects({
  items,
  recentIds = [],
  onOpen,
  onEdit,
  onDelete,
  onFavorite,
  onDuplicate,
  onValidate,
  onRepair,
  onMetadata,
  busy = false,
  t,
}: {
  items: Project[];
  recentIds?: string[];
  onOpen: (p: Project) => void;
  onEdit: (p: Project) => void;
  onDelete: (p: Project) => void;
  onFavorite: (p: Project) => void;
  busy?: boolean;
  onMetadata?: (p: Project) => void;
  onRepair?: (p: Project) => void;
  onValidate?: (p: Project) => void;
  onDuplicate?: (p: Project) => void;
  t: (k: Key) => string;
}) {
  const [recentOnly, setRecentOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [favorites, setFavorites] = useState(false);
  const [sort, setSort] = useState("recent");
  const shown = items
    .filter(
      (p) =>
        p.name.toLowerCase().includes(query.toLowerCase()) &&
        (!favorites || p.favorite) &&
        (!recentOnly || recentIds.includes(p.id)),
    )
    .sort((a, b) =>
      recentOnly
        ? recentIds.indexOf(a.id) - recentIds.indexOf(b.id)
        : sort === "name"
          ? a.name.localeCompare(b.name)
          : b.modified.localeCompare(a.modified),
    );
  return (
    <>
      <div className="toolbar">
        <label>
          <input
            type="checkbox"
            checked={recentOnly}
            onChange={(e) => setRecentOnly(e.target.checked)}
          />
          {t("recentProjects")}
        </label>
        <input
          aria-label={t("search")}
          placeholder={t("search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          aria-label={t("modified")}
          value={sort}
          onChange={(e) => setSort(e.target.value)}
        >
          <option value="recent">{t("sortRecent")}</option>
          <option value="name">{t("sortName")}</option>
        </select>
        <label>
          <input
            type="checkbox"
            checked={favorites}
            onChange={(e) => setFavorites(e.target.checked)}
          />
          {t("favoritesOnly")}
        </label>
      </div>
      {!shown.length ? (
        <div className="empty">
          <FolderOpen size={32} />
          <h3>{t("emptyProjects")}</h3>
          <p>{t("emptyProjectsDetail")}</p>
        </div>
      ) : (
        <div className="project-grid">
          {shown.map((p) => (
            <article key={p.id}>
              <button className="project-open" onClick={() => onOpen(p)}>
                <FolderOpen size={24} />
                <h3>{p.name}</h3>
                <p>
                  {p.asset_count} {t("assets")} · {p.duration.toFixed(1)} s
                </p>
                <small>{new Date(p.modified).toLocaleString()}</small>
              </button>
              <div className="toolbar">
                <button
                  aria-label={t("favorite")}
                  aria-pressed={!!p.favorite}
                  onClick={() => onFavorite(p)}
                >
                  <Star size={14} fill={p.favorite ? "currentColor" : "none"} />
                </button>
                <button disabled={busy} onClick={() => onValidate?.(p)}>
                  {t("validate_project")}
                </button>
                <button disabled={busy} onClick={() => onDuplicate?.(p)}>
                  {t("duplicate_project")}
                </button>
                <button disabled={busy} onClick={() => onRepair?.(p)}>
                  {t("plan_repair")}
                </button>
                <button onClick={() => onMetadata?.(p)}>
                  {t("projectMetadata")}
                </button>
                <button onClick={() => onEdit(p)}>{t("rename")}</button>
                <button onClick={() => onDelete(p)}>{t("remove")}</button>
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

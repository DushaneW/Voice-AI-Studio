import type { Workspace } from "../types/domain";

// Workspaces whose backend exists and is tested but whose end-to-end behaviour is
// not verified on a packaged build. They are hidden by default; build with
// VITE_NEXUS_EXPERIMENTAL=1 to show them again.
export const EXPERIMENTAL_WORKSPACES: readonly Workspace[] = [
  "workflows",
  "audiobook",
  "dubbing",
];

export function experimentalEnabled(): boolean {
  const env = (import.meta as { env?: Record<string, string | undefined> }).env;
  return env?.VITE_NEXUS_EXPERIMENTAL === "1";
}

export function isWorkspaceEnabled(
  workspace: Workspace,
  experimental = experimentalEnabled(),
): boolean {
  return experimental || !EXPERIMENTAL_WORKSPACES.includes(workspace);
}

/** A stored preference may point at a workspace that is now hidden. */
export function visibleWorkspace(
  workspace: Workspace,
  experimental = experimentalEnabled(),
): Workspace {
  return isWorkspaceEnabled(workspace, experimental) ? workspace : "home";
}

// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { useWorkstation } from "./useWorkstation";
import { request } from "../services/runtime";
import type { Project } from "../types/domain";

vi.mock("../services/runtime", () => ({
  request: vi.fn(),
  importAudio: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("does not let an older refresh overwrite newer project data", async () => {
  const pending: ((value: Project[]) => void)[] = [];
  vi.mocked(request).mockImplementation(async (_method, path) => {
    if (path === "/v1/projects")
      return new Promise<Project[]>((resolve) => pending.push(resolve));
    if (path === "/v1/settings")
      return { language: "en", workspace: "home", inspector: true };
    return [];
  });
  const { result } = renderHook(useWorkstation);
  await waitFor(() => expect(pending).toHaveLength(1));
  let latest: Promise<void>;
  act(() => {
    latest = result.current.refresh();
  });
  await waitFor(() => expect(pending).toHaveLength(2));
  const project = { id: "current", name: "Current project" } as Project;
  await act(async () => {
    pending[1]([project]);
    await latest;
  });
  expect(result.current.projects).toEqual([project]);
  await act(async () => {
    pending[0]([]);
  });
  expect(result.current.projects).toEqual([project]);
});
it("restores last project and persists open and close retaining recent history", async () => {
  const project = { id: "project-one", name: "One" } as Project;
  vi.mocked(request).mockImplementation(async (method, path) => {
    if (path === "/v1/settings" && method === "GET")
      return {
        language: "en",
        workspace: "projects",
        inspector: true,
        last_project_id: project.id,
        recent_project_ids: [project.id],
      };
    if (path === "/v1/projects") return [project];
    return [];
  });
  const { result } = renderHook(useWorkstation);
  await waitFor(() => expect(result.current.projectId).toBe(project.id));
  await waitFor(() => expect(result.current.ready).toBe(true));
  act(() => result.current.closeProject());
  expect(result.current.projectId).toBe("");
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "PUT",
      "/v1/settings",
      expect.objectContaining({
        last_project_id: null,
        recent_project_ids: [project.id],
      }),
    ),
  );
  act(() => result.current.open(project));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "PUT",
      "/v1/settings",
      expect.objectContaining({
        last_project_id: project.id,
        recent_project_ids: [project.id],
      }),
    ),
  );
});

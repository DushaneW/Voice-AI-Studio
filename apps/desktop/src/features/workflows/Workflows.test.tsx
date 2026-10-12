// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Workflows } from "./Workflows";
import { request } from "../../services/runtime";
import { translator } from "../../app/i18n";
import type { Asset } from "../../types/domain";
vi.mock("../../services/runtime", () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("reuses the request key after an uncertain submit", async () => {
  const submitted: unknown[] = [];
  vi.mocked(request).mockImplementation(async (_method, path, body) => {
    if (path === "/v1/workflow-templates")
      return [
        {
          id: "audio-review",
          name: "Audio review",
          builtin: true,
          ready: true,
          requirements: [],
          definition: {
            input_kind: "audio",
            steps: [{ kind: "analyze", options: {} }],
          },
        },
      ];
    if (path === "/v1/engines") return [];
    if (path === "/v1/workflows/search")
      return { items: [], next_cursor: null };
    if (path === "/v1/workflows") {
      submitted.push(body);
      throw new Error("runtime_unavailable");
    }
    return {};
  });
  render(
    <Workflows
      projectId="project"
      assets={[{ id: "audio", name: "Recording", duration: 1 } as Asset]}
      t={translator("en")}
      onError={vi.fn()}
    />,
  );
  fireEvent.click(await screen.findByRole("checkbox", { name: /Recording/ }));
  const button = screen.getByRole("button", { name: "Start workflow" });
  fireEvent.click(button);
  await waitFor(() => expect(submitted).toHaveLength(1));
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  fireEvent.click(button);
  await waitFor(() => expect(submitted).toHaveLength(2));
  expect(submitted[0]).toEqual(submitted[1]);
  expect(submitted[0]).toMatchObject({
    project_id: "project",
    template_id: "audio-review",
    inputs: ["audio"],
  });
});

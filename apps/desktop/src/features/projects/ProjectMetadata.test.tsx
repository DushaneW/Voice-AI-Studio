// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProjectMetadata } from "./ProjectMetadata";
import { request } from "../../services/runtime";
import { translator } from "../../app/i18n";
vi.mock("../../services/runtime", () => ({ request: vi.fn(), native: false }));
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close = function () {
  this.removeAttribute("open");
};
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.resetAllMocks();
});
it("keeps dirty content and recovery draft when optimistic revision check fails", async () => {
  const error = vi.fn();
  vi.mocked(request).mockImplementation(async (method) => {
    if (method === "PUT") throw new Error("document_revision_conflict");
    return {
      revision: 4,
      content: {
        author: "Original",
        description: "Notes",
        language: "pl",
        tags: [],
      },
    };
  });
  render(
    <ProjectMetadata
      id="project"
      t={translator("en")}
      onClose={vi.fn()}
      onError={error}
    />,
  );
  fireEvent.change(await screen.findByDisplayValue("Original"), {
    target: { value: "Edited" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(error).toHaveBeenCalledWith("Error: document_revision_conflict"),
  );
  expect(request).toHaveBeenCalledWith(
    "PUT",
    "/v1/projects/project/documents/project",
    {
      revision: 4,
      content: {
        author: "Edited",
        description: "Notes",
        language: "pl",
        tags: [],
      },
    },
  );
  expect(screen.getByDisplayValue("Edited")).toBeTruthy();
  expect(
    Object.keys(localStorage).some((key) =>
      key.startsWith("nexus.recovery.v1.project.project"),
    ),
  ).toBe(true);
});

// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { request } from "../../services/runtime";
import { translator } from "../../app/i18n";
import { Models } from "./Models";
vi.mock("../../services/runtime", () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("shows persisted queued model work and navigates to its exact Job Center entry", async () => {
  const open = vi.fn();
  vi.mocked(request).mockResolvedValue([
    {
      id: "whisper-tiny",
      name: "Whisper",
      state: "available",
      job_id: "durable-model-job",
      job_state: "queued",
      provider: "Provider",
      license: "MIT",
      devices: ["cpu"],
      languages: ["en"],
      files: [],
      size: 100,
    },
  ]);
  render(<Models t={translator("en")} onError={vi.fn()} onOpenJob={open} />);
  fireEvent.click(await screen.findByRole("button", { name: "Open job" }));
  expect(open).toHaveBeenCalledWith("durable-model-job");
  expect(screen.queryByRole("button", { name: "Install" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "POST",
      "/v1/models/whisper-tiny/cancel",
    ),
  );
});

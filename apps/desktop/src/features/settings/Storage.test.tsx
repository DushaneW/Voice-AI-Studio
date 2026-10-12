// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Storage } from "./Storage";
import { request } from "../../services/runtime";
import { translator } from "../../app/i18n";
vi.mock("../../services/runtime", () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("requires confirmation before clearing cache and refreshes real counts", async () => {
  const report = {
    categories: Object.fromEntries(
      ["assets", "models", "cache", "backups", "logs"].map((k) => [
        k,
        { bytes: 100, files: 1, complete: true },
      ]),
    ),
    database_bytes: 10,
    disk_free: 1000,
    disk_total: 2000,
    trash_audio_bytes: 0,
  };
  vi.mocked(request).mockImplementation(async (method) =>
    method === "GET" ? report : { complete: true, removed: 1 },
  );
  render(<Storage t={translator("en")} />);
  await screen.findByText("Managed audio");
  const button = screen.getByRole("button", {
    name: "Clear waveform cache",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await screen.findByText("Waveform cache cleared.");
  expect(request).toHaveBeenCalledWith("POST", "/v1/storage/waveforms/clear", {
    confirmed: true,
  });
  await waitFor(() => expect(button.disabled).toBe(true));
  expect(
    vi.mocked(request).mock.calls.filter((c) => c[0] === "GET").length,
  ).toBe(2);
});

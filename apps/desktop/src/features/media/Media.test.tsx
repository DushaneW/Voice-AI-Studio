// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Media } from "./Media";
import { request } from "../../services/runtime";
import { translator } from "../../app/i18n";
vi.mock("../../services/runtime", () => ({
  request: vi.fn(),
  audioUrl: vi.fn().mockResolvedValue("blob:audio"),
}));
vi.mock("../../components/audio/Waveform", () => ({
  Waveform: ({ peaks }: { peaks: number[] }) => (
    <div data-testid="waveform">{peaks.join(",")}</div>
  ),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("shows cached waveform with no jobs present", async () => {
  URL.revokeObjectURL = vi.fn();
  vi.mocked(request).mockResolvedValue({
    analysis: { peaks: [0.1, 0.7], peak_dbfs: -3, rms_dbfs: -12 },
  });
  const asset = {
    id: "asset",
    project_id: "project",
    name: "Take",
    duration: 1,
    sample_rate: 24000,
    channels: 1,
    size: 100,
    sha256: "a".repeat(64),
  };
  render(
    <Media
      assets={[asset]}
      selected={asset}
      jobs={[]}
      onSelect={vi.fn()}
      onAnalyze={vi.fn()}
      onExport={vi.fn()}
      onTrash={vi.fn()}
      t={translator("en")}
    />,
  );
  expect((await screen.findByTestId("waveform")).textContent).toBe("0.1,0.7");
  expect(request).toHaveBeenCalledWith("GET", "/v1/assets/asset/waveform");
});

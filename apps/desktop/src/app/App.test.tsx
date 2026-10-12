// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import App from "./App";
import { Jobs } from "../features/jobs/Jobs";
import { translator } from "./i18n";
vi.mock("../services/runtime", () => ({
  native: false,
  request: vi.fn().mockRejectedValue(new Error("desktop_required")),
  importAudio: vi.fn(),
  exportAudio: vi.fn(),
  exportDiagnostics: vi.fn(),
}));
afterEach(cleanup);
describe("Disconnected desktop shell", () => {
  it("disables writes and shows no invented hardware readings", async () => {
    render(<App />);
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "New project" })
          .hasAttribute("disabled"),
      ).toBe(true),
    );
    expect(screen.getByText("CPU — · GPU —")).toBeTruthy();
    expect(screen.getByText(/Open NEXUS desktop/)).toBeTruthy();
  });
  it("navigates and changes language without a runtime", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "pl" },
    });
    expect(screen.getByRole("heading", { name: "Ustawienia" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zadania" }));
    expect(screen.getByText("Brak zadań")).toBeTruthy();
  });
  it("renders fractional measured job progress as a percentage", () => {
    render(
      <Jobs
        onChanged={() => {}}
        onError={() => {}}
        assets={[]}
        jobs={[
          {
            id: "j",
            project_id: "p",
            asset_id: "a",
            kind: "analyze",
            state: "running",
            progress: 0.42,
            result: null,
            error: null,
            created: "",
          },
        ]}
        onAction={() => {}}
        t={translator("en")}
      />,
    );
    expect(screen.getByText("42%")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("max")).toBe("1");
  });
});

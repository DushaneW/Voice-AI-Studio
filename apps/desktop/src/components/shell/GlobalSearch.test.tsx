// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GlobalSearch } from "./GlobalSearch";
import { translator } from "../../app/i18n";
import { request } from "../../services/runtime";
vi.mock("../../services/runtime", () => ({ request: vi.fn() }));
vi.mock("../dialogs/Modal", () => ({
  Modal: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("opens the exact transcript search result", async () => {
  const hit = {
    id: "transcript",
    project_id: "project",
    asset_id: "asset",
    segment: 150,
    label: "Recording",
    snippet: "Hello",
  };
  vi.mocked(request).mockResolvedValue({
    groups: {
      projects: { items: [], more: false },
      assets: { items: [], more: false },
      transcripts: { items: [hit], more: false },
    },
  });
  const open = vi.fn(),
    close = vi.fn();
  render(<GlobalSearch t={translator("en")} onOpen={open} onClose={close} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Hello" } });
  fireEvent.click(await screen.findByRole("button", { name: /Recording/ }));
  expect(open).toHaveBeenCalledWith("transcripts", hit);
  expect(close).toHaveBeenCalledOnce();
});

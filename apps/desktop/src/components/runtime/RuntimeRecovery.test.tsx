// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { RuntimeRecovery } from "./RuntimeRecovery";
import { translator } from "../../app/i18n";
import { restartRuntime, runtimeLog } from "../../services/runtime";
vi.mock("../../services/runtime", () => ({
  restartRuntime: vi.fn(),
  runtimeLog: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("shows launch failure and log, then refreshes after restart", async () => {
  vi.mocked(runtimeLog).mockResolvedValue("Missing engine library");
  vi.mocked(restartRuntime).mockResolvedValue();
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(
    <RuntimeRecovery
      code="runtime_launch_failed"
      t={translator("en")}
      onRestart={refresh}
    />,
  );
  expect(screen.getByText("runtime_launch_failed")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Show runtime log" }));
  await screen.findByText("Missing engine library");
  fireEvent.click(screen.getByRole("button", { name: "Restart runtime" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
});
it("retains restart refusal without claiming successful recovery", async () => {
  vi.mocked(restartRuntime).mockRejectedValue("runtime_still_running");
  const refresh = vi.fn();
  render(
    <RuntimeRecovery
      code="runtime_unavailable"
      t={translator("en")}
      onRestart={refresh}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Restart runtime" }));
  await screen.findByText("runtime_still_running");
  expect(refresh).not.toHaveBeenCalled();
});
it("explains a missing executable rather than implying restart will repair it", () => {
  render(
    <RuntimeRecovery
      code="runtime_executable_missing"
      t={translator("pl")}
      onRestart={vi.fn()}
    />,
  );
  expect(screen.getByText(/npm run desktop/)).toBeTruthy();
  expect(screen.queryByText(translator("pl")("runtimeRestartHint"))).toBeNull();
});

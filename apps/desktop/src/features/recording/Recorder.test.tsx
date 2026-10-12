// @vitest-environment jsdom
import "fake-indexeddb/auto";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Recorder } from "./Recorder";
import { translator } from "../../app/i18n";
import { saveRecording } from "../../services/runtime";
const mock = vi.hoisted(() => ({
  start: vi.fn(),
  stop: vi.fn(),
  dispose: vi.fn(),
  record: vi.fn(),
}));
vi.mock("../../services/runtime", () => ({
  native: false,
  microphonePermission: vi.fn().mockResolvedValue(undefined),
  saveRecording: vi.fn(),
}));
vi.mock("./capture", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./capture")>();
  return {
    ...actual,
    MicrophoneCapture: class {
      take = new actual.PcmTake(48000, 1);
      constructor() {
        this.take.append(new Float32Array([0.1, 0.2]));
      }
      start = mock.start;
      stop = mock.stop;
      dispose = mock.dispose;
      record = mock.record;
      pause() {}
      setGain() {}
    },
  };
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});
it("retains the take after failed save and clears only after successful save", async () => {
  URL.createObjectURL = vi.fn(() => "blob:take");
  URL.revokeObjectURL = vi.fn();
  mock.start.mockResolvedValue(undefined);
  mock.stop.mockResolvedValue(undefined);
  vi.mocked(saveRecording)
    .mockRejectedValueOnce(new Error("runtime_unavailable"))
    .mockResolvedValueOnce({ id: "asset" });
  const saved = vi.fn();
  render(<Recorder projectId="project" t={translator("en")} saved={saved} />);
  await waitFor(() =>
    expect(
      (screen.getByText("Start recording") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByText("Start recording"));
  await screen.findByText("Stop recording");
  fireEvent.click(screen.getByText("Stop recording"));
  fireEvent.click(await screen.findByText("Save take to project"));
  await screen.findByRole("alert");
  expect(saved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Save take to project"));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(saveRecording).toHaveBeenCalledTimes(2);
  expect(vi.mocked(saveRecording).mock.calls[0][2]).toBe(
    vi.mocked(saveRecording).mock.calls[1][2],
  );
  expect(vi.mocked(saveRecording).mock.calls[0][2]).toMatch(/^[0-9a-f-]{36}$/);
  expect(vi.mocked(saveRecording).mock.calls[0][1].byteLength).toBe(48);
});
it("reports denied permission and releases resources on unmount", async () => {
  mock.start.mockRejectedValueOnce(
    new DOMException("denied", "NotAllowedError"),
  );
  const { unmount } = render(
    <Recorder projectId="project" t={translator("en")} saved={vi.fn()} />,
  );
  await waitFor(() =>
    expect(
      (screen.getByText("Start recording") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByText("Start recording"));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "access denied",
  );
  unmount();
  expect(mock.dispose).toHaveBeenCalled();
});
it("recovers a committed take after unmount without changing PCM", async () => {
  mock.start.mockResolvedValue(undefined);
  mock.stop.mockResolvedValue(undefined);
  const first = render(
    <Recorder projectId="reopen" t={translator("en")} saved={vi.fn()} />,
  );
  await waitFor(() =>
    expect(
      (screen.getByText("Start recording") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByText("Start recording"));
  fireEvent.click(await screen.findByText("Stop recording"));
  vi.mocked(saveRecording).mockRejectedValueOnce(
    new Error("runtime_unavailable"),
  );
  fireEvent.click(await screen.findByText("Save take to project"));
  await screen.findByRole("alert");
  const originalRequestId = vi.mocked(saveRecording).mock.calls[0][2];
  vi.mocked(saveRecording).mockClear();
  first.unmount();
  vi.mocked(saveRecording).mockResolvedValue({ id: "recovered" });
  render(<Recorder projectId="reopen" t={translator("en")} saved={vi.fn()} />);
  fireEvent.click(await screen.findByText("Recover take"));
  fireEvent.click(await screen.findByText("Save take to project"));
  await waitFor(() => expect(saveRecording).toHaveBeenCalledOnce());
  expect(vi.mocked(saveRecording).mock.calls[0][2]).toBe(originalRequestId);
  expect(
    new DataView(vi.mocked(saveRecording).mock.calls[0][1]).getInt16(44, true),
  ).toBe(3277);
});
it("records only after the countdown has elapsed", async () => {
  mock.start.mockResolvedValue(undefined);
  render(
    <Recorder projectId="countdown" t={translator("en")} saved={vi.fn()} />,
  );
  await waitFor(() =>
    expect(
      (screen.getByText("Start recording") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  fireEvent.change(screen.getByLabelText("Countdown"), {
    target: { value: "3" },
  });
  fireEvent.change(screen.getByLabelText("Pre-roll"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByText("Prepare microphone"));
  await screen.findByText("Start recording");
  expect(mock.start).toHaveBeenLastCalledWith("", 48000, 1, 1, true, 2);
  vi.useFakeTimers();
  fireEvent.click(screen.getByText("Start recording"));
  act(() => vi.advanceTimersByTime(2900));
  expect(mock.record).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(100));
  expect(mock.record).toHaveBeenCalledOnce();
});
it("cancels countdown, releases microphone and never starts recording", async () => {
  mock.start.mockResolvedValue(undefined);
  render(
    <Recorder
      projectId="cancel-countdown"
      t={translator("en")}
      saved={vi.fn()}
    />,
  );
  await waitFor(() =>
    expect(
      (screen.getByText("Start recording") as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  fireEvent.change(screen.getByLabelText("Countdown"), {
    target: { value: "3" },
  });
  fireEvent.click(screen.getByText("Prepare microphone"));
  await screen.findByText("Start recording");
  vi.useFakeTimers();
  fireEvent.click(screen.getByText("Start recording"));
  fireEvent.click(screen.getByText("Cancel"));
  act(() => vi.advanceTimersByTime(5000));
  expect(mock.record).not.toHaveBeenCalled();
  expect(mock.dispose).toHaveBeenCalled();
});

it("uses persisted recording format, gain and pre-roll when arming capture", async () => {
  mock.start.mockResolvedValue(undefined);
  render(
    <Recorder
      projectId="preferences"
      defaults={{
        language: "en",
        workspace: "media",
        inspector: true,
        recording_sample_rate: 44100,
        recording_channels: 2,
        recording_gain: 0.6,
        recording_preroll: 2,
        recording_countdown: 3,
      }}
      t={translator("en")}
      saved={vi.fn()}
    />,
  );
  const button = screen.getByText(translator("en")("recordingPrepare"));
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  fireEvent.click(button);
  await waitFor(() =>
    expect(mock.start).toHaveBeenCalledWith("", 44100, 2, 0.6, true, 2),
  );
  expect(
    (
      screen.getByLabelText(
        translator("en")("recordingCountdown"),
      ) as HTMLSelectElement
    ).value,
  ).toBe("3");
});

// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { TimelineTransport } from "./TimelineTransport";
import { translator } from "../../app/i18n";
import type { Asset } from "../../types/domain";
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
class Node {
  gain = {
    value: 1,
    setValueAtTime: vi.fn(),
    setTargetAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
  };
  channelCount = 2;
  channelCountMode = "max";
  buffer: unknown;
  start = vi.fn();
  connect(node: Node) {
    return node;
  }
}
class Context {
  static instances: Context[] = [];
  currentTime = 0;
  sampleRate = 48000;
  destination = new Node();
  sources: Node[] = [];
  gains: Node[] = [];
  close = vi.fn(async () => {});
  resume = vi.fn(async () => {});
  decodeAudioData = vi.fn(async () => ({ duration: 1 }));
  constructor() {
    Context.instances.push(this);
  }
  createBufferSource() {
    const node = new Node();
    this.sources.push(node);
    return node;
  }
  createGain() {
    const node = new Node();
    this.gains.push(node);
    return node;
  }
  createChannelSplitter() {
    return new Node();
  }
  createChannelMerger() {
    return new Node();
  }
}
const clip = {
  asset_id: "a",
  track_id: "voice",
  offset: 0,
  trim_start: 0,
  trim_end: 1,
  gain: 0.8,
  fade_in: 0.5,
  fade_out: 0.2,
};
const document = {
  clips: [clip, { ...clip, track_id: "muted" }],
  tracks: [
    { id: "voice", volume: 0.5, pan: -1, muted: false, solo: false },
    { id: "muted", volume: 1, pan: 0, muted: true, solo: false },
  ],
  channels: 2,
};
const asset = {
  id: "a",
  channels: 1,
  sample_rate: 24000,
  size: 48044,
  duration: 1,
} as Asset;
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
  Context.instances = [];
});
function setup(
  assets = [asset],
  defaults?: React.ComponentProps<typeof TimelineTransport>["defaults"],
) {
  vi.stubGlobal("AudioContext", Context);
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn(() => 1),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.mocked(invoke).mockResolvedValue(new ArrayBuffer(8));
  const error = vi.fn();
  const onPosition = vi.fn();
  const view = render(
    <TimelineTransport
      defaults={defaults}
      document={document}
      assets={assets}
      position={0.25}
      onPosition={onPosition}
      onError={error}
      disabled={false}
      seekVersion={0}
      t={translator("en")}
    />,
  );
  return { error, onPosition, ...view };
}
it("schedules trimmed audio, excludes muted tracks and closes the context on unmount", async () => {
  const { unmount } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Play timeline" }));
  await screen.findByRole("button", { name: "Pause" });
  const context = Context.instances[0];
  expect(context.sources).toHaveLength(1);
  expect(context.sources[0].start).toHaveBeenCalledWith(0.05, 0.25, 0.75);
  expect(context.gains[0].gain.value).toBe(1);
  expect(context.gains[1].gain.value).toBe(0.4);
  expect(context.gains[2].gain.setValueAtTime).toHaveBeenCalledWith(0.5, 0.05);
  expect(context.gains.at(-1)?.gain.value).toBe(0);
  unmount();
  expect(context.close).toHaveBeenCalledOnce();
});
it("rejects an oversized preview before requesting audio bytes", async () => {
  const { error } = setup([{ ...asset, duration: 100000 }]);
  fireEvent.click(screen.getByRole("button", { name: "Play timeline" }));
  await waitFor(() =>
    expect(error).toHaveBeenCalledWith("Error: preview_memory_limit"),
  );
  expect(invoke).not.toHaveBeenCalled();
  expect(Context.instances[0].close).toHaveBeenCalledOnce();
});

it("applies monitor defaults and adjusts real output gain without restarting sources", async () => {
  const { onPosition } = setup([asset], {
    language: "en",
    workspace: "timeline",
    inspector: true,
    playback_volume: 0.3,
  });
  fireEvent.click(screen.getByRole("button", { name: "Play timeline" }));
  await screen.findByRole("button", { name: "Pause" });
  const context = Context.instances[0],
    master = context.gains[0];
  expect(master.gain.value).toBe(0.3);
  fireEvent.click(screen.getByLabelText("Mute timeline monitor"));
  expect(master.gain.setTargetAtTime).toHaveBeenLastCalledWith(0, 0, 0.01);
  fireEvent.change(screen.getByLabelText("Timeline monitor volume"), {
    target: { value: "0.7" },
  });
  expect(master.gain.setTargetAtTime).toHaveBeenLastCalledWith(0, 0, 0.01);
  fireEvent.click(screen.getByLabelText("Mute timeline monitor"));
  expect(master.gain.setTargetAtTime).toHaveBeenLastCalledWith(0.7, 0, 0.01);
  expect(context.sources).toHaveLength(1);
  expect(context.close).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(onPosition).toHaveBeenLastCalledWith(0);
  expect(context.close).toHaveBeenCalledOnce();
});

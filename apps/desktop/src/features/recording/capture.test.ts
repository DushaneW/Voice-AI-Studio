import { expect, it, vi } from "vitest";
import { PcmTake, MicrophoneCapture } from "./capture";
import workletSource from "../../../public/recorder-worklet.js?raw";

it("writes little-endian PCM16 stereo with clipping, finite samples and correct timing", () => {
  const take = new PcmTake(48000, 2);
  take.append(new Float32Array([-2, 2, NaN, 0.5]));
  const bytes = new DataView(take.wav());
  expect(bytes.getUint32(40, true)).toBe(8);
  expect(bytes.getUint16(22, true)).toBe(2);
  expect(bytes.getUint32(28, true)).toBe(192000);
  expect([44, 46, 48, 50].map((i) => bytes.getInt16(i, true))).toEqual([
    -32768, 32767, 0, 16384,
  ]);
  expect(take.seconds).toBe(2 / 48000);
});
it("stops at a whole stereo frame and never exceeds its memory budget", () => {
  const take = new PcmTake(24000, 2, 51);
  expect(take.append(new Float32Array([1, 1, 1, 1]))).toBe(false);
  expect(take.samples).toBe(2);
  expect(take.wav().byteLength).toBe(48);
  expect(take.append(new Float32Array([1, 1]))).toBe(false);
  expect(take.samples).toBe(2);
  expect(() => take.append(new Float32Array([1]))).toThrow("recording_format");
  expect(() => new PcmTake(48000, 1).wav()).toThrow("recording_empty");
});
it("flushes the final partial block and omits paused audio in the real worklet", () => {
  const messages: { block?: Float32Array; stopped?: boolean }[] = [];
  let Processor: any;
  new Function("AudioWorkletProcessor", "registerProcessor", workletSource)(
    class {
      port = {
        postMessage: (value: any) => messages.push(value),
        onmessage: null,
      };
    },
    (_name: string, value: any) => {
      Processor = value;
    },
  );
  const processor = new Processor({ processorOptions: { channels: 1 } });
  processor.process([[new Float32Array([0.1, 0.2])]]);
  processor.port.onmessage({ data: "pause" });
  processor.process([[new Float32Array([0.9])]]);
  processor.port.onmessage({ data: "resume" });
  processor.process([[new Float32Array([0.3])]]);
  processor.port.onmessage({ data: "stop" });
  expect(messages.filter((m) => m.block).map((m) => m.block!.length)).toEqual([
    2, 1,
  ]);
  expect(messages.at(-1)).toEqual({ stopped: true });
});
it("releases a microphone granted after its component was disposed", async () => {
  let grant!: (value: MediaStream) => void;
  const stop = vi.fn();
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: () =>
        new Promise((resolve) => {
          grant = resolve;
        }),
    },
  });
  const capture = new MicrophoneCapture(vi.fn(), vi.fn());
  const pending = capture.start("", 48000, 1, 1);
  capture.dispose();
  await Promise.resolve();
  grant({ getTracks: () => [{ stop }] } as unknown as MediaStream);
  await pending;
  expect(stop).toHaveBeenCalledOnce();
  vi.unstubAllGlobals();
});
it("pre-roll keeps latest stereo frames exactly once", () => {
  const messages: any[] = [];
  let Processor: any;
  new Function("AudioWorkletProcessor", "registerProcessor", workletSource)(
    class {
      port = { postMessage: (v: any) => messages.push(v), onmessage: null };
    },
    (_name: string, value: any) => {
      Processor = value;
    },
  );
  const recorder = new Processor({
    processorOptions: { channels: 2, armed: true, preRollFrames: 2 },
  });
  recorder.process([
    [new Float32Array([1, 2, 3]), new Float32Array([10, 20, 30])],
  ]);
  expect(messages).toEqual([]);
  recorder.port.onmessage({ data: "record" });
  recorder.process([[new Float32Array([4]), new Float32Array([40])]]);
  recorder.port.onmessage({ data: "stop" });
  expect(Array.from(messages[0].block)).toEqual([2, 20, 3, 30, 4, 40]);
});

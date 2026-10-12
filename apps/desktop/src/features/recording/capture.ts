import { microphonePermission } from "../../services/runtime";
export const MAX_RECORDING_BYTES = 32 * 1024 * 1024;

/** Bounded interleaved PCM; pauses contain no synthetic silence. */
export class PcmTake {
  private blocks: Int16Array[] = [];
  samples = 0;
  peak = 0;
  constructor(
    readonly rate: number,
    readonly channels: number,
    readonly limit = MAX_RECORDING_BYTES,
  ) {
    if (![24000, 44100, 48000].includes(rate) || ![1, 2].includes(channels))
      throw new Error("recording_format");
  }
  append(input: Float32Array): boolean {
    if (input.length % this.channels) throw new Error("recording_format");
    const remaining = Math.max(
      0,
      Math.floor((this.limit - 44 - this.samples * 2) / (2 * this.channels)) *
        this.channels,
    );
    const count = Math.min(input.length, remaining);
    const block = new Int16Array(count);
    this.peak = 0;
    for (let i = 0; i < count; i++) {
      const value = Number.isFinite(input[i])
        ? Math.max(-1, Math.min(1, input[i]))
        : 0;
      this.peak = Math.max(this.peak, Math.abs(value));
      block[i] = Math.round(value * (value < 0 ? 32768 : 32767));
    }
    if (count) this.blocks.push(block);
    this.samples += count;
    return count === input.length && remaining > count;
  }
  chunksFrom(index: number): readonly Int16Array[] {
    return this.blocks.slice(index);
  }
  appendPcm(block: Int16Array) {
    if (
      !block.length ||
      block.length % this.channels ||
      44 + (this.samples + block.length) * 2 > this.limit
    )
      throw new Error("recording_format");
    this.blocks.push(block.slice());
    this.samples += block.length;
  }
  get seconds() {
    return this.samples / this.channels / this.rate;
  }
  wav(): ArrayBuffer {
    if (!this.samples) throw new Error("recording_empty");
    const bytes = new ArrayBuffer(44 + this.samples * 2);
    const view = new DataView(bytes);
    const tag = (offset: number, value: string) =>
      [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
    tag(0, "RIFF");
    view.setUint32(4, bytes.byteLength - 8, true);
    tag(8, "WAVE");
    tag(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, this.channels, true);
    view.setUint32(24, this.rate, true);
    view.setUint32(28, this.rate * this.channels * 2, true);
    view.setUint16(32, this.channels * 2, true);
    view.setUint16(34, 16, true);
    tag(36, "data");
    view.setUint32(40, this.samples * 2, true);
    let offset = 44;
    for (const block of this.blocks)
      for (const sample of block) {
        view.setInt16(offset, sample, true);
        offset += 2;
      }
    return bytes;
  }
}

export class MicrophoneCapture {
  private stream?: MediaStream;
  private context?: AudioContext;
  private node?: AudioWorkletNode;
  private gain?: GainNode;
  private closed = false;
  private finish?: () => void;
  private stopping?: Promise<void>;
  take?: PcmTake;
  constructor(
    private update: (take: PcmTake) => void,
    private interrupted: (code: string) => void,
    private monitor: (peak: number) => void = () => {},
  ) {}
  async start(
    device: string,
    rate: number,
    channels: number,
    gain: number,
    armed = false,
    preRoll = 0,
  ) {
    try {
      if (![0, 1, 2, 3, 5].includes(preRoll))
        throw new Error("recording_format");
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error("recording_unsupported");
      await microphonePermission(true);
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: device ? { exact: device } : undefined,
            channelCount: { exact: channels },
            sampleRate: { ideal: rate },
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
          },
        });
      } finally {
        await microphonePermission(false).catch(() => {});
      }
      if (this.closed) {
        this.dispose();
        return;
      }
      this.context = new AudioContext({ sampleRate: rate });
      if (this.context.sampleRate !== rate) throw new Error("recording_format");
      if (!this.context.audioWorklet) throw new Error("recording_unsupported");
      await this.context.audioWorklet.addModule("/recorder-worklet.js");
      if (this.closed) {
        this.dispose();
        return;
      }
      this.take = new PcmTake(this.context.sampleRate, channels);
      this.node = new AudioWorkletNode(this.context, "nexus-capture", {
        processorOptions: {
          channels,
          armed,
          preRollFrames: Math.round(this.context.sampleRate * preRoll),
        },
        channelCount: channels,
        channelCountMode: "explicit",
      });
      this.gain = this.context.createGain();
      this.setGain(gain);
      this.context
        .createMediaStreamSource(this.stream)
        .connect(this.gain)
        .connect(this.node)
        .connect(this.context.destination);
      this.node.port.onmessage = ({ data }) => {
        if (Number.isFinite(data.monitor) && !this.closed) {
          this.monitor(data.monitor);
          return;
        }
        if (data.stopped) {
          this.finish?.();
          return;
        }
        if (this.closed || !this.take || !(data.block instanceof Float32Array))
          return;
        const room = this.take.append(data.block);
        this.update(this.take);
        if (!room && !this.stopping) {
          this.interrupted("recording_limit");
          void this.stop();
        }
      };
      this.node.onprocessorerror = () => {
        this.interrupted("recording_interrupted");
        void this.stop();
      };
      for (const track of this.stream.getTracks())
        track.onended = () => {
          this.interrupted("recording_interrupted");
          void this.stop();
        };
      await this.context.resume();
    } catch (error) {
      this.dispose();
      throw error;
    }
  }
  setGain(value: number) {
    if (this.gain) this.gain.gain.value = Math.max(0, Math.min(4, value));
  }
  record() {
    this.node?.port.postMessage("record");
  }
  pause(paused: boolean) {
    this.node?.port.postMessage(paused ? "pause" : "resume");
  }
  stop(): Promise<void> {
    if (this.stopping) return this.stopping;
    this.stopping = new Promise<void>((resolve) => {
      const done = () => {
        clearTimeout(timer);
        this.dispose();
        resolve();
      };
      // If the device/audio thread has died, preserve all blocks already received.
      const timer = setTimeout(done, 1000);
      this.finish = done;
      if (this.node && !this.closed) this.node.port.postMessage("stop");
      else done();
    });
    return this.stopping;
  }
  dispose() {
    this.closed = true;
    for (const track of this.stream?.getTracks() ?? []) {
      track.onended = null;
      track.stop();
    }
    this.node?.disconnect();
    if (this.node) {
      this.node.onprocessorerror = null;
      this.node.port.onmessage = null;
      this.node.port.close();
    }
    this.gain?.disconnect();
    if (this.context && this.context.state !== "closed")
      void this.context.close().catch(() => {});
  }
}

/* Silent output avoids feedback; armed audio stays in a bounded pre-roll ring. */
class NexusCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const config = options.processorOptions;
    this.channels = config.channels;
    this.mode = config.armed ? "armed" : "recording";
    this.used = 0;
    this.block = new Float32Array(4096 * this.channels);
    this.ring = new Float32Array((config.preRollFrames || 0) * this.channels);
    this.ringHead = 0;
    this.ringCount = 0;
    this.port.onmessage = ({ data }) => {
      if (data === "record" && this.mode === "armed") {
        this.used = 0;
        this.mode = "recording";
        for (let i = 0; i < this.ringCount; i++) {
          this.block[this.used++] =
            this.ring[
              (this.ringHead - this.ringCount + i + this.ring.length) %
                this.ring.length
            ];
          if (this.used === this.block.length) this.flush();
        }
        this.ring = new Float32Array(0);
        this.ringCount = 0;
      }
      if (data === "pause" && this.mode === "recording") {
        this.flush();
        this.mode = "paused";
      }
      if (data === "resume" && this.mode === "paused") this.mode = "recording";
      if (data === "stop") {
        this.flush();
        this.mode = "stopped";
        this.port.postMessage({ stopped: true });
      }
    };
  }
  flush() {
    if (!this.used) return;
    if (this.mode === "armed") {
      let peak = 0;
      for (let i = 0; i < this.used; i++)
        peak = Math.max(peak, Math.abs(this.block[i]));
      this.port.postMessage({ monitor: Math.min(1, peak) });
    } else if (this.mode === "recording") {
      const block = this.block.slice(0, this.used);
      this.port.postMessage({ block }, [block.buffer]);
    }
    this.used = 0;
  }
  process(inputs) {
    const input = inputs[0];
    if (!["armed", "recording"].includes(this.mode) || !input?.length)
      return true;
    for (let frame = 0; frame < input[0].length; frame++) {
      for (let channel = 0; channel < this.channels; channel++) {
        const value = input[channel]?.[frame] ?? 0;
        if (this.mode === "armed" && this.ring.length) {
          this.ring[this.ringHead] = value;
          this.ringHead = (this.ringHead + 1) % this.ring.length;
          this.ringCount = Math.min(this.ringCount + 1, this.ring.length);
        }
        this.block[this.used++] = value;
      }
      if (this.used === this.block.length) this.flush();
    }
    return true;
  }
}
registerProcessor("nexus-capture", NexusCapture);

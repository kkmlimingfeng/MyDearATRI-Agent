class PCMStreamPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.offset = 0;
    this.queuedSamples = 0;
    this.started = false;
    this.ended = false;
    this.port.onmessage = (event) => {
      if (event.data?.type === 'end') {
        this.ended = true;
        return;
      }
      if (event.data instanceof ArrayBuffer) {
        const samples = new Float32Array(event.data);
        this.queue.push(samples);
        this.queuedSamples += samples.length;
      }
    };
  }

  process(_inputs, outputs) {
    const channel = outputs[0][0];
    channel.fill(0);
    if (!this.started) {
      if (!this.ended && this.queuedSamples < sampleRate * 0.12) return true;
      this.started = true;
    }

    let written = 0;
    while (written < channel.length && this.queue.length) {
      const head = this.queue[0];
      const count = Math.min(channel.length - written, head.length - this.offset);
      channel.set(head.subarray(this.offset, this.offset + count), written);
      written += count;
      this.offset += count;
      this.queuedSamples -= count;
      if (this.offset === head.length) {
        this.queue.shift();
        this.offset = 0;
      }
    }

    if (this.ended && this.queuedSamples === 0) {
      this.port.postMessage({ type: 'drained' });
      return false;
    }
    return true;
  }
}

registerProcessor('atri-pcm-stream-player', PCMStreamPlayer);

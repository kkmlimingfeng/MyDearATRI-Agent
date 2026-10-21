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
      if (event.data?.type === 'segment-start' || event.data?.type === 'segment-end') {
        this.queue.push({
          kind: 'marker',
          phase: event.data.type === 'segment-start' ? 'started' : 'finished',
          playbackId: event.data.playbackId,
          text: event.data.text,
        });
        return;
      }
      if (event.data instanceof ArrayBuffer) {
        const samples = new Float32Array(event.data);
        this.queue.push({ kind: 'samples', samples });
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
      if (head.kind === 'marker') {
        this.queue.shift();
        if (head.phase === 'started') {
          this.activePlaybackId = head.playbackId;
          this.port.postMessage({ type: 'segment-started', playbackId: head.playbackId, text: head.text });
        } else {
          this.port.postMessage({ type: 'segment-finished', playbackId: head.playbackId, text: head.text });
          if (this.activePlaybackId === head.playbackId) this.activePlaybackId = null;
        }
        continue;
      }
      const count = Math.min(channel.length - written, head.samples.length - this.offset);
      channel.set(head.samples.subarray(this.offset, this.offset + count), written);
      written += count;
      this.offset += count;
      this.queuedSamples -= count;
      if (this.offset === head.samples.length) {
        this.queue.shift();
        this.offset = 0;
      }
    }

    if (this.ended && this.queue.length === 0 && this.queuedSamples === 0) {
      this.port.postMessage({ type: 'drained' });
      return false;
    }
    return true;
  }
}

registerProcessor('atri-pcm-stream-player', PCMStreamPlayer);

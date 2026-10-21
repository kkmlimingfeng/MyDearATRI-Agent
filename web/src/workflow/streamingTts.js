import pcmWorkletUrl from './pcmStream.worklet.js?url&no-inline';

const SAMPLE_RATE = 24_000;
export const MAX_SPOKEN_CHARACTERS = 200;
export const LONG_REPLY_SPEECH = '内容太多，我不读了，你自己看吧！';

let audioContext;
let workletContext;
let workletModulePromise;
const emojiPart = String.raw`(?:\p{Emoji_Presentation}|\p{Extended_Pictographic}\uFE0F)(?:\p{Emoji_Modifier})?`;
const emojiSequence = new RegExp(`(?:${emojiPart})(?:\\u200D(?:${emojiPart}))*|[\\u{1F1E6}-\\u{1F1FF}]{2}|[#*0-9]\\uFE0F?\\u20E3`, 'gu');

export function stripSpeechEmoji(text) {
  return String(text || '')
    .replace(emojiSequence, '')
    .replace(/[\uFE0E\uFE0F\u200D\u20E3\u{1F3FB}-\u{1F3FF}\u{E0020}-\u{E007F}]/gu, '')
    .replace(/[ \t]{2,}/g, ' ');
}

export function getSpeakableCharacterCount(text) {
  return Array.from(stripSpeechEmoji(text)).length;
}

let activePlayback = null;
let playbackId = 0;
const elementPlaybackLeases = new WeakMap();
const SPEECH_PLAYBACK_EVENT = 'atri:speech-playback';

function publishSpeechPlayback(detail) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(SPEECH_PLAYBACK_EVENT, { detail }));
}

export function subscribeSpeechPlayback(listener) {
  if (typeof window === 'undefined') return () => {};
  const handleEvent = (event) => listener(event.detail || {});
  window.addEventListener(SPEECH_PLAYBACK_EVENT, handleEvent);
  return () => window.removeEventListener(SPEECH_PLAYBACK_EVENT, handleEvent);
}

function observePlayer(player, onDrained) {
  player.port.addEventListener('message', (event) => {
    const message = event.data;
    if (message?.type === 'segment-started' || message?.type === 'segment-finished') {
      if (activePlayback?.id !== message.playbackId) return;
      publishSpeechPlayback({
        type: message.type === 'segment-started' ? 'start' : 'end',
        playbackId: message.playbackId,
        text: message.text,
      });
    }
    if (message?.type === 'drained') onDrained?.();
  });
  player.port.start();
}

export function claimExclusivePlayback(stop) {
  const previous = activePlayback;
  activePlayback = null;
  playbackId += 1;
  previous?.stop();

  const id = playbackId;
  let stopped = false;
  const release = () => {
    if (activePlayback?.id === id) activePlayback = null;
  };
  const interrupt = () => {
    if (stopped) return;
    stopped = true;
    if (activePlayback?.id === id) activePlayback = null;
    stop?.();
  };
  activePlayback = { id, stop: interrupt };
  return { id, release, stop: interrupt };
}

export function playAudioElement(audio, speechText = '') {
  let lease;
  let speechStarted = false;
  const speechLabel = stripSpeechEmoji(speechText).trim();
  let cleanup = () => {};
  const onPlaying = () => {
    if (!speechLabel || speechStarted) return;
    speechStarted = true;
    publishSpeechPlayback({ type: 'start', playbackId: lease.id, text: speechLabel });
  };
  const finish = () => {
    cleanup();
    if (elementPlaybackLeases.get(audio) === lease) elementPlaybackLeases.delete(audio);
    if (speechStarted) publishSpeechPlayback({ type: 'end', playbackId: lease.id });
    speechStarted = false;
    lease?.release();
  };
  lease = claimExclusivePlayback(() => {
    audio.pause();
    audio.currentTime = 0;
    if (speechStarted) publishSpeechPlayback({ type: 'stop', playbackId: lease.id });
    speechStarted = false;
    cleanup();
    if (elementPlaybackLeases.get(audio) === lease) elementPlaybackLeases.delete(audio);
  });
  elementPlaybackLeases.set(audio, lease);
  const onFinish = () => finish();
  cleanup = () => {
    audio.removeEventListener('playing', onPlaying);
    audio.removeEventListener('ended', onFinish);
  };
  audio.addEventListener('playing', onPlaying);
  audio.addEventListener('ended', onFinish, { once: true });
  try {
    return Promise.resolve(audio.play()).then(() => {}, (error) => {
      finish();
      throw error;
    });
  } catch (error) {
    finish();
    return Promise.reject(error);
  }
}

export function stopAudioElement(audio) {
  if (audio) elementPlaybackLeases.get(audio)?.stop();
}

function hasSpeakableText(text) {
  return /[\p{L}\p{N}]/u.test(stripSpeechEmoji(text));
}

export function primeAudioPlayback() {
  if (typeof window === 'undefined') return Promise.resolve(null);
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return Promise.resolve(null);
  if (!audioContext || audioContext.state === 'closed') {
    try {
      audioContext = new AudioContextClass({ sampleRate: SAMPLE_RATE });
    } catch {
      audioContext = new AudioContextClass();
    }
  }
  return audioContext.state === 'suspended' ? audioContext.resume().then(() => audioContext) : Promise.resolve(audioContext);
}

function toWaveBlob(chunks, byteLength) {
  const header = new ArrayBuffer(44);
  const view = new DataView(header);
  const text = (offset, value) => [...value].forEach((character, index) => view.setUint8(offset + index, character.charCodeAt(0)));
  text(0, 'RIFF');
  view.setUint32(4, 36 + byteLength, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, byteLength, true);
  return new Blob([header, ...chunks], { type: 'audio/wav' });
}

function joinBytes(left, right) {
  if (!left.length) return right;
  const joined = new Uint8Array(left.length + right.length);
  joined.set(left);
  joined.set(right, left.length);
  return joined;
}

function decodePCM(bytes, targetRate) {
  const input = new Float32Array(bytes.length / 2);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let index = 0; index < input.length; index += 1) input[index] = view.getInt16(index * 2, true) / 32768;
  if (targetRate === SAMPLE_RATE) return input;
  const outputLength = Math.max(1, Math.floor(input.length * targetRate / SAMPLE_RATE));
  const output = new Float32Array(outputLength);
  for (let index = 0; index < output.length; index += 1) {
    const position = index * SAMPLE_RATE / targetRate;
    const lower = Math.floor(position);
    const upper = Math.min(input.length - 1, lower + 1);
    const fraction = position - lower;
    output[index] = input[lower] * (1 - fraction) + input[upper] * fraction;
  }
  return output;
}

export function splitSpeakableText(text, flush = false) {
  const characters = Array.from(stripSpeechEmoji(text));
  const segments = [];
  let start = 0;
  for (let index = 0; index < characters.length; index += 1) {
    const character = characters[index];
    const length = index - start + 1;
    const next = characters[index + 1] || '';
    const sentenceEnd = /[。！？!?;；\n]/u.test(character)
      || (character === '.' && (!next || /\s/u.test(next)));
    const softEnd = length >= 56 && /[，,、:：]/u.test(character);
    const hardEnd = length >= 160;
    if (!sentenceEnd && !softEnd && !hardEnd) continue;
    const segment = characters.slice(start, index + 1).join('').trim();
    if (hasSpeakableText(segment)) segments.push(segment);
    start = index + 1;
  }
  const remainder = characters.slice(start).join('');
  if (flush && hasSpeakableText(remainder)) segments.push(remainder.trim());
  return { segments, remainder: flush ? '' : remainder };
}

export function createStreamingTtsSession(request, signal) {
  let context;
  let player;
  let playerReady;
  let playbackLease;
  let queue = Promise.resolve();
  let finished = false;
  let failure = null;
  const controller = new AbortController();
  const chunks = [];
  let byteLength = 0;

  const stop = () => {
    finished = true;
    signal?.removeEventListener('abort', stop);
    controller.abort();
    if (playbackLease) publishSpeechPlayback({ type: 'stop', playbackId: playbackLease.id });
    player?.disconnect();
    player = null;
    playbackLease?.release();
    playbackLease = null;
  };
  if (signal?.aborted) stop();
  else signal?.addEventListener('abort', stop, { once: true });

  const ensurePlayer = async () => {
    if (player) return player;
    if (!playerReady) {
      playerReady = (async () => {
        context = await primeAudioPlayback();
        if (!context?.audioWorklet || typeof window.AudioWorkletNode !== 'function') return null;
        if (workletContext !== context) {
          workletContext = context;
          workletModulePromise = context.audioWorklet.addModule(pcmWorkletUrl).catch((error) => {
            if (workletContext === context) {
              workletContext = null;
              workletModulePromise = null;
            }
            throw error;
          });
        }
        await workletModulePromise;
        const node = new window.AudioWorkletNode(context, 'atri-pcm-stream-player', {
          numberOfInputs: 0,
          numberOfOutputs: 1,
          outputChannelCount: [1],
        });
        node.connect(context.destination);
        observePlayer(node, () => {
          node.disconnect();
          if (player === node) {
            player = null;
            playbackLease?.release();
            playbackLease = null;
          }
        });
        player = node;
        return node;
      })();
    }
    return playerReady;
  };

  const synthesize = async (text) => {
    if (controller.signal.aborted) return;
    const node = await ensurePlayer();
    if (controller.signal.aborted) {
      node?.disconnect();
      if (player === node) player = null;
      return;
    }
    if (!node) throw new Error('当前浏览器不支持流式音频播放');
    const response = await fetch(request.endpoint || '/api/tts/speech', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...request, text, response_format: 'pcm' }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || `语音生成失败 (${response.status})`);
    }
    if (!response.body) throw new Error('浏览器不支持语音流读取');

    const reader = response.body.getReader();
    let carry = new Uint8Array(0);
    let segmentQueued = false;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const combined = joinBytes(carry, value);
        const usableLength = combined.length - (combined.length % 2);
        const pcmBytes = combined.subarray(0, usableLength);
        carry = usableLength < combined.length ? combined.subarray(usableLength) : new Uint8Array(0);
        if (!pcmBytes.length) continue;
        const retained = pcmBytes.slice();
        chunks.push(retained);
        byteLength += retained.length;
        const samples = decodePCM(retained, context.sampleRate);
        if (!playbackLease) playbackLease = claimExclusivePlayback(stop);
        if (!segmentQueued) {
          node.port.postMessage({ type: 'segment-start', playbackId: playbackLease.id, text });
          segmentQueued = true;
        }
        node.port.postMessage(samples.buffer, [samples.buffer]);
      }
      if (carry.length) throw new Error('TTS 音频流末尾包含不完整 PCM 样本');
    } finally {
      if (segmentQueued && !controller.signal.aborted) {
        node.port.postMessage({ type: 'segment-end', playbackId: playbackLease?.id, text });
      }
      reader.releaseLock();
    }
  };

  return {
    enqueue(text) {
      const speakableText = stripSpeechEmoji(text).trim();
      if (finished || !hasSpeakableText(speakableText)) return;
      queue = queue.then(() => synthesize(speakableText)).catch((error) => {
        if (!controller.signal.aborted && error?.name !== 'AbortError') failure ||= error;
      });
    },
    async finish() {
      finished = true;
      await queue;
      if (player) player.port.postMessage({ type: 'end' });
      signal?.removeEventListener('abort', stop);
      return {
        blob: byteLength ? toWaveBlob(chunks, byteLength) : null,
        error: failure,
      };
    },
    stop,
  };
}

export async function streamTtsRequest(request, signal) {
  let player = null;
  let reader;
  let playbackLease;
  let streamed = false;
  const controller = new AbortController();
  const stop = () => {
    signal?.removeEventListener('abort', stop);
    controller.abort();
    if (playbackLease) publishSpeechPlayback({ type: 'stop', playbackId: playbackLease.id });
    player?.disconnect();
    try { reader?.cancel().catch(() => {}); } catch { /* The stream may already have released its reader. */ }
    playbackLease?.release();
  };
  if (signal?.aborted) stop();
  else signal?.addEventListener('abort', stop, { once: true });
  const context = await primeAudioPlayback();
  if (context?.audioWorklet && typeof window.AudioWorkletNode === 'function') {
    if (workletContext !== context) {
      workletContext = context;
      workletModulePromise = context.audioWorklet.addModule(pcmWorkletUrl).catch((error) => {
        if (workletContext === context) {
          workletContext = null;
          workletModulePromise = null;
        }
        throw error;
      });
    }
    try {
      await workletModulePromise;
      player = new window.AudioWorkletNode(context, 'atri-pcm-stream-player', {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      player.connect(context.destination);
      streamed = true;
    } catch {
      player = null;
    }
  }

  const speakableText = stripSpeechEmoji(request.text);
  if (!hasSpeakableText(speakableText)) {
    stop();
    signal?.removeEventListener('abort', stop);
    throw new Error('回复没有可朗读的文字');
  }
  const endpoint = request.endpoint || '/api/tts/speech';
  let response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...request, text: speakableText, response_format: 'pcm' }),
      signal: controller.signal,
    });
  } catch (error) {
    stop();
    signal?.removeEventListener('abort', stop);
    throw error;
  }
  if (!response.ok) {
    const detail = await response.text();
    stop();
    signal?.removeEventListener('abort', stop);
    throw new Error(detail || `语音生成失败 (${response.status})`);
  }
  if (!response.body) {
    stop();
    signal?.removeEventListener('abort', stop);
    throw new Error('浏览器不支持语音流读取');
  }

  reader = response.body.getReader();
  const chunks = [];
  let byteLength = 0;
  let carry = new Uint8Array(0);
  let segmentQueued = false;
  const workletPlayer = player;
  if (workletPlayer) observePlayer(workletPlayer, () => {
    workletPlayer.disconnect();
    playbackLease?.release();
    playbackLease = null;
  });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const combined = joinBytes(carry, value);
      const usableLength = combined.length - (combined.length % 2);
      const pcmBytes = combined.subarray(0, usableLength);
      carry = usableLength < combined.length ? combined.subarray(usableLength) : new Uint8Array(0);
      if (!pcmBytes.length) continue;
      const retained = pcmBytes.slice();
      chunks.push(retained);
      byteLength += retained.length;
      if (player) {
        const samples = decodePCM(retained, context.sampleRate);
        if (!playbackLease) playbackLease = claimExclusivePlayback(stop);
        if (!segmentQueued) {
          player.port.postMessage({ type: 'segment-start', playbackId: playbackLease.id, text: speakableText });
          segmentQueued = true;
        }
        player.port.postMessage(samples.buffer, [samples.buffer]);
      }
    }
    if (carry.length) throw new Error('TTS 音频流末尾包含不完整 PCM 样本');
    if (!byteLength) throw new Error('TTS 返回了空音频流');
    if (segmentQueued) player.port.postMessage({ type: 'segment-end', playbackId: playbackLease?.id, text: speakableText });
    player?.port.postMessage({ type: 'end' });
    return { url: URL.createObjectURL(toWaveBlob(chunks, byteLength)), streamed, stop };
  } catch (error) {
    stop();
    throw error;
  } finally {
    signal?.removeEventListener('abort', stop);
    reader.releaseLock();
  }
}

import { useEffect, useRef, useState } from 'react';
import { Pause, Play, Volume2 } from 'lucide-react';
import { getSpeakableCharacterCount, LONG_REPLY_SPEECH, MAX_SPOKEN_CHARACTERS, playAudioElement, primeAudioPlayback, stopAudioElement, streamTtsRequest } from './streamingTts';

export default function VoiceOutput({ request, dataUrl, blob, error: initialError = '', autoGenerate = true, label = '语音输出' }) {
  const audioRef = useRef(null);
  const stopRef = useRef(null);
  const objectUrlRef = useRef(null);
  const [replayUrl, setReplayUrl] = useState(dataUrl || '');
  const [streaming, setStreaming] = useState(false);
  const [playbackError, setPlaybackError] = useState('');
  const [playbackStatus, setPlaybackStatus] = useState('idle');
  const [retry, setRetry] = useState(0);
  const playbackRequest = request && getSpeakableCharacterCount(request.text) > MAX_SPOKEN_CHARACTERS
    ? { ...request, text: LONG_REPLY_SPEECH }
    : request;
  const requestKey = JSON.stringify(playbackRequest || null);

  useEffect(() => {
    const controller = new AbortController();
    setPlaybackError(initialError);
    setStreaming(false);
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = null;
    setReplayUrl(dataUrl || '');

    if (blob) {
      const url = URL.createObjectURL(blob);
      objectUrlRef.current = url;
      setReplayUrl(url);
      return () => {
        controller.abort();
        stopAudioElement(audioRef.current);
        if (objectUrlRef.current === url) {
          URL.revokeObjectURL(url);
          objectUrlRef.current = null;
        }
      };
    }

    if (dataUrl) {
      const audio = audioRef.current;
      if (audio) {
        audio.currentTime = 0;
        playAudioElement(audio, playbackRequest?.text).catch(() => {});
      }
      return () => {
        controller.abort();
        stopAudioElement(audioRef.current);
      };
    }
    if (!requestKey || requestKey === 'null') return () => {
      controller.abort();
      stopAudioElement(audioRef.current);
    };
    if (!autoGenerate && retry === 0) return () => {
      controller.abort();
      stopAudioElement(audioRef.current);
    };

    setStreaming(true);
    streamTtsRequest(JSON.parse(requestKey), controller.signal)
      .then(({ url, streamed, stop }) => {
        if (controller.signal.aborted) {
          URL.revokeObjectURL(url);
          stop();
          return;
        }
        stopRef.current = stop;
        objectUrlRef.current = url;
        setReplayUrl(url);
        setStreaming(false);
        if (!streamed && audioRef.current) {
          audioRef.current.src = url;
          playAudioElement(audioRef.current, playbackRequest?.text).catch(() => {});
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setStreaming(false);
          if (error?.name !== 'AbortError') setPlaybackError(error.message || '语音生成失败');
        }
      });

    return () => {
      controller.abort();
      stopRef.current?.();
      stopRef.current = null;
      stopAudioElement(audioRef.current);
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    };
  }, [autoGenerate, blob, dataUrl, initialError, playbackRequest?.text, requestKey, retry]);

  const replay = async () => {
    if (!replayUrl) {
      if (!streaming && requestKey !== 'null') setRetry((value) => value + 1);
      else await primeAudioPlayback().catch(() => {});
      return;
    }
    const audio = audioRef.current;
    if (!audio) return;
    if (playbackStatus === 'playing') {
      audio.pause();
      return;
    }
    if (playbackStatus === 'paused' && audio.currentTime > 0 && !audio.ended) {
      audio.play().catch(() => setPlaybackError('浏览器阻止了音频播放'));
      return;
    }
    stopRef.current?.();
    stopRef.current = null;
    audio.currentTime = 0;
    playAudioElement(audio, playbackRequest?.text).catch((error) => {
      if (error?.name !== 'AbortError') {
        setPlaybackStatus('idle');
        setPlaybackError('浏览器阻止了音频播放');
      }
    });
  };

  const isPlaying = playbackStatus === 'playing';
  const isPaused = playbackStatus === 'paused';
  const buttonLabel = isPlaying ? `暂停${label}` : isPaused ? `继续${label}` : `重新播放${label}`;

  return (
    <div className="voice-output-control">
      <audio
        ref={audioRef}
        src={replayUrl || undefined}
        preload="auto"
        hidden
        onPlaying={() => {
          setPlaybackStatus('playing');
          setPlaybackError('');
        }}
        onPause={(event) => setPlaybackStatus(event.currentTarget.ended || event.currentTarget.currentTime === 0 ? 'idle' : 'paused')}
        onEnded={() => setPlaybackStatus('idle')}
      />
      <button
        type="button"
        className={`voice-output-button ${isPlaying ? 'is-playing' : ''}`}
        onClick={replay}
        disabled={streaming && !replayUrl}
        aria-label={buttonLabel}
      >
        {isPlaying ? <Pause size={16} aria-hidden="true" /> : isPaused ? <Play size={16} aria-hidden="true" /> : <Volume2 size={16} aria-hidden="true" />}
      </button>
      {playbackError && <small className="voice-output-error" role="status">{playbackError}</small>}
    </div>
  );
}

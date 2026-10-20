import { useEffect, useRef, useState } from 'react';
import { Volume2 } from 'lucide-react';
import { primeAudioPlayback, streamTtsRequest } from './streamingTts';

export default function VoiceOutput({ request, dataUrl, blob, error: initialError = '', autoGenerate = true, label = '语音输出' }) {
  const audioRef = useRef(null);
  const stopRef = useRef(null);
  const objectUrlRef = useRef(null);
  const [replayUrl, setReplayUrl] = useState(dataUrl || '');
  const [streaming, setStreaming] = useState(false);
  const [playbackError, setPlaybackError] = useState('');
  const [retry, setRetry] = useState(0);
  const requestKey = JSON.stringify(request || null);

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
        audio.play().catch(() => {});
      }
      return () => controller.abort();
    }
    if (!requestKey || requestKey === 'null') return () => controller.abort();
    if (!autoGenerate && retry === 0) return () => controller.abort();

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
          audioRef.current.play().catch(() => {});
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setPlaybackError(error.message || '语音生成失败');
          setStreaming(false);
        }
      });

    return () => {
      controller.abort();
      stopRef.current?.();
      stopRef.current = null;
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    };
  }, [autoGenerate, blob, dataUrl, initialError, requestKey, retry]);

  const replay = async () => {
    if (!replayUrl) {
      if (!streaming && requestKey !== 'null') setRetry((value) => value + 1);
      else await primeAudioPlayback().catch(() => {});
      return;
    }
    stopRef.current?.();
    stopRef.current = null;
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = 0;
    audio.play().catch(() => setPlaybackError('浏览器阻止了音频播放'));
  };

  return (
    <div className="voice-output-control">
      <audio ref={audioRef} src={replayUrl || undefined} preload="auto" hidden />
      <button type="button" className="voice-output-button" onClick={replay} disabled={streaming && !replayUrl} title={playbackError || '重新播放语音'} aria-label={`${label}，重新播放`}>
        <Volume2 size={16} />
      </button>
      {playbackError && <small className="voice-output-error" role="status">{playbackError}</small>}
    </div>
  );
}

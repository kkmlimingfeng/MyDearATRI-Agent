import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AudioLines, Check, FolderOpen, Pause, Play, Upload, X } from 'lucide-react';
import './VoiceManager.css';

function collectDirectory(entry, prefix = '') {
  if (entry.isFile) {
    return new Promise((resolve, reject) => entry.file(
      (file) => resolve([{ file, path: prefix ? `${prefix}/${entry.name}` : entry.name }]),
      reject,
    ));
  }
  if (!entry.isDirectory) return Promise.resolve([]);
  const reader = entry.createReader();
  const readBatch = () => new Promise((resolve, reject) => reader.readEntries(resolve, reject));
  const readAll = async () => {
    const children = [];
    while (true) {
      const batch = await readBatch();
      if (!batch.length) break;
      children.push(...batch);
    }
    const path = prefix ? `${prefix}/${entry.name}` : entry.name;
    return (await Promise.all(children.map((child) => collectDirectory(child, path)))).flat();
  };
  return readAll();
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function VoiceManagerPage({ onClose }) {
  const [profiles, setProfiles] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [profileName, setProfileName] = useState('');
  const [uploadFiles, setUploadFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [playingKey, setPlayingKey] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const folderInputRef = useRef(null);
  const audioRef = useRef(null);
  const selected = profiles.find((profile) => profile.id === selectedId) || profiles[0] || null;
  const uploadBytes = uploadFiles.reduce((total, item) => total + item.file.size, 0);

  const loadProfiles = async (preferId) => {
    const response = await fetch('/api/tts/voices');
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || '读取音色列表失败');
    const nextProfiles = Array.isArray(payload.profiles) ? payload.profiles : [];
    setProfiles(nextProfiles);
    setSelectedId((current) => preferId && nextProfiles.some((profile) => profile.id === preferId)
      ? preferId
      : nextProfiles.some((profile) => profile.id === current) ? current : nextProfiles[0]?.id || '');
  };

  useEffect(() => {
    loadProfiles().catch((loadError) => setError(loadError.message || '读取音色列表失败'));
    const closeOnEscape = (event) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('keydown', closeOnEscape);
      audioRef.current?.pause();
      audioRef.current = null;
    };
  }, [onClose]);

  useEffect(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    setPlayingKey('');
  }, [selectedId]);

  const setFiles = (files) => {
    setError('');
    setMessage('');
    setUploadFiles(files);
  };

  const validateUpload = (files) => {
    if (!files.length || files.some((item) => item.path.split('/').length !== 2 || item.path.split('/')[0].toLowerCase() !== 'voice')) {
      setError('请选择根目录名为 voice，且音频直接放在其中的文件夹。');
      setFiles([]);
      return false;
    }
    if (files.some((item) => !/\.(wav|txt)$/i.test(item.file.name))) {
      setError('只支持 WAV 音频和与音频同名的 TXT 台词文件。');
      setFiles([]);
      return false;
    }
    if (!files.some((item) => /\.wav$/i.test(item.file.name))) {
      setError('voice 文件夹中至少需要一个 WAV 音频。');
      setFiles([]);
      return false;
    }
    setFiles(files);
    return true;
  };

  const handleDrop = async (event) => {
    event.preventDefault();
    setDragging(false);
    const items = [...(event.dataTransfer?.items || [])];
    try {
      const entries = items.map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
      if (entries.length !== 1 || !entries[0].isDirectory || entries[0].name.toLowerCase() !== 'voice') {
        setError('请拖入名为 voice 的文件夹。');
        setFiles([]);
        return;
      }
      validateUpload(await collectDirectory(entries[0]));
    } catch {
      setError('读取拖入的文件夹失败，请重新选择。');
    }
  };

  const chooseFolder = (event) => {
    const files = [...(event.target.files || [])];
    const paths = files.map((file) => file.webkitRelativePath || file.name);
    validateUpload(files.map((file, index) => ({ file, path: paths[index] })));
    event.target.value = '';
  };

  const toggleClip = async (clip) => {
    if (!selected || busy) return;
    const files = selected.clips.filter((item) => item.selected && item.name !== clip.name).map((item) => item.name);
    if (!clip.selected) files.push(clip.name);
    if (!files.length) {
      setError('至少保留一个参与合成的音频。');
      return;
    }
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/tts/voices/selection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile: selected.id, files }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || '保存音色选择失败');
      setProfiles(payload.profiles || []);
      setMessage('参与合成的音频已更新。');
      window.dispatchEvent(new Event('atri-tts-references-updated'));
    } catch (saveError) {
      setError(saveError.message || '保存音色选择失败');
      loadProfiles(selected.id).catch(() => {});
    } finally {
      setBusy(false);
    }
  };

  const togglePlayback = async (clip) => {
    const key = `${selected?.id}/${clip.name}`;
    if (playingKey === key && audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
      setPlayingKey('');
      return;
    }
    audioRef.current?.pause();
    const audio = new Audio(clip.url);
    audioRef.current = audio;
    setPlayingKey(key);
    audio.onended = () => { if (audioRef.current === audio) { audioRef.current = null; setPlayingKey(''); } };
    audio.onerror = () => { if (audioRef.current === audio) { audioRef.current = null; setPlayingKey(''); setError('音频试听失败。'); } };
    try {
      await audio.play();
    } catch {
      if (audioRef.current === audio) { audioRef.current = null; setPlayingKey(''); setError('音频试听失败。'); }
    }
  };

  const createProfile = async (event) => {
    event.preventDefault();
    setError('');
    setMessage('');
    if (!profileName.trim()) { setError('请填写音色文件夹名称。'); return; }
    if (!uploadFiles.length) { setError('请先选择 voice 文件夹。'); return; }
    setBusy(true);
    try {
      const formData = new FormData();
      formData.append('name', profileName.trim());
      for (const item of uploadFiles) {
        formData.append('paths', item.path);
        formData.append('files', item.file, item.file.name);
      }
      const response = await fetch('/api/tts/voices/create', { method: 'POST', body: formData });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || '创建音色失败');
      setProfiles(payload.profiles || []);
      setSelectedId(payload.profile.id);
      setProfileName('');
      setUploadFiles([]);
      setMessage(`已添加音色 ${payload.profile.id}`);
      window.dispatchEvent(new Event('atri-tts-references-updated'));
    } catch (createError) {
      setError(createError.message || '创建音色失败');
    } finally {
      setBusy(false);
    }
  };

  return createPortal(<div className="voice-manager-backdrop" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="voice-manager-page" role="dialog" aria-modal="true" aria-label="音色设置">
      <header className="voice-manager-header">
        <div><AudioLines size={18} /><strong>音色设置</strong></div>
        <button type="button" className="icon-button" onClick={onClose} title="关闭" aria-label="关闭音色设置"><X size={17} /></button>
      </header>
      <div className="voice-manager-layout">
        <aside className="voice-manager-list" aria-label="音色列表">
          <div className="voice-manager-list-heading"><strong>音色</strong><span>{profiles.length}</span></div>
          <div className="voice-manager-profile-list">
            {profiles.map((profile) => <button type="button" key={profile.id} className={`voice-manager-profile-row ${selected?.id === profile.id ? 'is-selected' : ''}`} onClick={() => setSelectedId(profile.id)}>
              <span className="voice-manager-profile-icon"><AudioLines size={15} /></span>
              <span className="voice-manager-profile-text"><strong>{profile.id}</strong><small>{profile.clips.length} 段 · {profile.clips.filter((clip) => clip.selected).length} 段参与合成</small></span>
            </button>)}
            {profiles.length === 0 && !error && <p className="voice-manager-empty">还没有可用音色</p>}
          </div>
        </aside>
        <main className="voice-manager-main">
          <section className="voice-manager-clips-section">
            <div className="voice-manager-clips-heading"><div><strong>{selected?.id || '参考音频'}</strong><span>勾选参与合成，点击播放试听</span></div>{selected && <small>{selected.clips.filter((clip) => clip.selected).length}/{selected.clips.length} 已选</small>}</div>
            <div className="voice-manager-clips">
              {selected?.clips.map((clip) => <div className={`voice-manager-clip ${clip.selected ? 'is-selected' : ''}`} key={clip.name}>
                <label className="voice-manager-clip-choice"><input type="checkbox" checked={clip.selected} disabled={busy || (!clip.supported && !clip.selected)} onChange={() => toggleClip(clip)} /><span className="voice-manager-clip-copy"><strong>{clip.label}</strong><small>{clip.duration_seconds}s{!clip.supported ? ' · WAV 格式不支持合成' : clip.ref_text ? ` · ${clip.ref_text}` : ' · 未配置台词'}</small></span></label>
                <button type="button" className="voice-manager-play-button" onClick={() => togglePlayback(clip)} title={playingKey === `${selected.id}/${clip.name}` ? '暂停试听' : '试听音频'} aria-label={playingKey === `${selected.id}/${clip.name}` ? `暂停试听 ${clip.label}` : `试听 ${clip.label}`}>
                  {playingKey === `${selected.id}/${clip.name}` ? <Pause size={15} /> : <Play size={15} />}
                </button>
              </div>)}
              {!selected && <p className="voice-manager-empty-detail">选择或添加音色后可试听参考音频。</p>}
            </div>
          </section>
          <form className="voice-manager-create" onSubmit={createProfile}>
            <div className="voice-manager-create-heading"><strong>添加音色</strong><span>目录结构：voice/*.wav，可带同名 .txt 台词</span></div>
            <label className="voice-manager-name-field"><span>音色名称</span><input value={profileName} maxLength={64} onChange={(event) => setProfileName(event.target.value)} placeholder="例如：atri-new" autoComplete="off" /></label>
            <div className={`voice-manager-dropzone ${dragging ? 'is-dragging' : ''} ${uploadFiles.length ? 'has-files' : ''}`} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false); }} onDrop={handleDrop}>
              {uploadFiles.length ? <div className="voice-manager-upload-summary"><span className="voice-manager-upload-icon"><Check size={16} /></span><div><strong>voice 文件夹 · {uploadFiles.filter((item) => /\.wav$/i.test(item.file.name)).length} 段音频</strong><small>{formatBytes(uploadBytes)}</small></div><button type="button" className="voice-manager-clear-files" onClick={() => setFiles([])} aria-label="移除上传文件"><X size={14} /></button></div> : <div className="voice-manager-drop-prompt"><Upload size={18} /><strong>拖入名为 voice 的文件夹</strong><span>音频需为 16-bit WAV，采样率保持一致</span></div>}
              <button type="button" className="voice-manager-file-button" onClick={() => folderInputRef.current?.click()}><FolderOpen size={14} />选择 voice 文件夹</button>
              <input ref={folderInputRef} type="file" accept=".wav,.txt,audio/wav,text/plain" webkitdirectory="" directory="" multiple hidden onChange={chooseFolder} />
            </div>
            <div className="voice-manager-create-footer"><p className={error ? 'is-error' : 'is-message'} role={error ? 'alert' : 'status'}>{error || message}</p><button type="submit" className="voice-manager-create-button" disabled={busy || !uploadFiles.length}>{busy ? '正在保存…' : '添加音色'}</button></div>
          </form>
        </main>
      </div>
    </section>
  </div>, document.body);
}

export default VoiceManagerPage;

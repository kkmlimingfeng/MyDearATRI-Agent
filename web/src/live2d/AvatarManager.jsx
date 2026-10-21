import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Application, Ticker } from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display/cubism4';
import { Check, Eye, EyeOff, FolderOpen, ImagePlus, PawPrint, X } from 'lucide-react';
import './AvatarManager.css';

const AVATAR_KEY = 'atri.desktop-pet.selected.v1';
const VISIBILITY_KEY = 'atri.desktop-pet.visible.v1';

function readActiveAvatar() {
  try { return localStorage.getItem(AVATAR_KEY) || 'atri'; }
  catch { return 'atri'; }
}

function readPetVisibility() {
  try { return localStorage.getItem(VISIBILITY_KEY) !== 'false'; }
  catch { return true; }
}

function groupAvatars(avatars) {
  const byFolder = new Map();
  for (const avatar of avatars) {
    if (!byFolder.has(avatar.characterId)) byFolder.set(avatar.characterId, avatar);
  }
  return [...byFolder.values()];
}

function collectDirectory(entry, prefix) {
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
      if (batch.length === 0) break;
      children.push(...batch);
    }
    const directoryPath = prefix ? `${prefix}/${entry.name}` : entry.name;
    return (await Promise.all(children.map((child) => collectDirectory(child, directoryPath)))).flat();
  };
  return readAll();
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function AvatarPreview({ avatar }) {
  const containerRef = useRef(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !avatar || avatar.type === 'image') return undefined;
    let disposed = false;
    let model;
    let resizeObserver;
    let app;
    setError('');
    if (!window.Live2DCubismCore) {
      setError('Live2D Core 未加载');
      return undefined;
    }

    Live2DModel.registerTicker(Ticker);
    app = new Application({
      width: 1,
      height: 1,
      antialias: true,
      autoDensity: true,
      backgroundAlpha: 0,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
    });
    container.appendChild(app.view);

    Live2DModel.from(avatar.assetUrl, { autoInteract: false }).then((loadedModel) => {
      if (disposed) {
        loadedModel.destroy({ children: true });
        return;
      }
      model = loadedModel;
      model.anchor.set(0.5, 0.5);
      app.stage.addChild(model);
      const naturalWidth = model.width;
      const naturalHeight = model.height;
      const resize = () => {
        if (!container.clientWidth || !container.clientHeight) return;
        app.renderer.resize(container.clientWidth, container.clientHeight);
        model.position.set(container.clientWidth / 2, container.clientHeight / 2);
        model.scale.set(Math.min(container.clientWidth / naturalWidth, container.clientHeight / naturalHeight));
      };
      resize();
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(container);
    }).catch((loadError) => {
      if (!disposed) setError(loadError?.message || 'Live2D 模型加载失败');
    });

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      if (app?.view.parentElement === container) container.removeChild(app.view);
      app?.destroy(true, { children: true });
    };
  }, [avatar?.id, avatar?.assetUrl, avatar?.type]);

  if (avatar?.type === 'image') return <img className="avatar-manager-preview-image" src={avatar.assetUrl} alt="桌宠预览" />;
  return <div ref={containerRef} className="avatar-manager-preview-live2d">{error && <span role="status">{error}</span>}</div>;
}

function AvatarManagerPage({ onClose }) {
  const [avatars, setAvatars] = useState([]);
  const [selectedCharacterId, setSelectedCharacterId] = useState('');
  const [activeAvatarId, setActiveAvatarId] = useState(readActiveAvatar);
  const [isPetVisible, setIsPetVisible] = useState(readPetVisibility);
  const [avatarName, setAvatarName] = useState('');
  const [uploadFiles, setUploadFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const imageInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const pets = useMemo(() => groupAvatars(avatars), [avatars]);
  const selectedAvatar = pets.find((avatar) => avatar.characterId === selectedCharacterId) || pets[0] || null;

  const loadAvatars = async (preferId) => {
    const response = await fetch('/api/avatars');
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || '读取桌宠列表失败');
    const available = Array.isArray(payload.avatars) ? payload.avatars : [];
    setAvatars(available);
    const nextPets = groupAvatars(available);
    setSelectedCharacterId((current) => {
      if (preferId && nextPets.some((avatar) => avatar.characterId === preferId)) return preferId;
      if (nextPets.some((avatar) => avatar.characterId === current)) return current;
      const active = nextPets.find((avatar) => avatar.id === activeAvatarId || avatar.characterId === activeAvatarId);
      return active?.characterId || nextPets[0]?.characterId || '';
    });
  };

  useEffect(() => {
    loadAvatars().catch((loadError) => setError(loadError.message));
  }, []);

  useEffect(() => {
    const closeOnEscape = (event) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [onClose]);

  const setFiles = (files) => {
    setError('');
    setMessage('');
    setUploadFiles(files);
  };

  const handleDrop = async (event) => {
    event.preventDefault();
    setDragging(false);
    const items = [...(event.dataTransfer?.items || [])];
    try {
      const entries = items.map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
      let files;
      if (entries.length === 1 && entries[0].isDirectory && entries[0].name.toLowerCase() === 'live2d') {
        files = await collectDirectory(entries[0], '');
      } else if (entries.length === 1 && entries[0].isFile) {
        files = await collectDirectory(entries[0], '');
      } else {
        files = [...(event.dataTransfer?.files || [])].map((file) => ({ file, path: file.name }));
      }
      setFiles(files);
    } catch {
      setError('读取拖入的文件失败，请重新选择文件或文件夹。');
    }
  };

  const chooseImage = (event) => {
    const file = event.target.files?.[0];
    if (file) setFiles([{ file, path: file.name }]);
    event.target.value = '';
  };

  const chooseFolder = (event) => {
    const files = [...(event.target.files || [])];
    const paths = files.map((file) => file.webkitRelativePath || file.name);
    if (!paths.length || paths.some((path) => path.split('/')[0].toLowerCase() !== 'live2d')) {
      setError('请选择文件夹名为 live2d 的文件夹。');
      setFiles([]);
    } else {
      setFiles(files.map((file, index) => ({ file, path: paths[index] })));
    }
    event.target.value = '';
  };

  const createAvatar = async (event) => {
    event.preventDefault();
    setError('');
    setMessage('');
    if (!avatarName.trim()) {
      setError('请填写桌宠文件夹名称。');
      return;
    }
    if (!uploadFiles.length) {
      setError('请先拖入桌宠图片或 live2d 文件夹。');
      return;
    }
    setBusy(true);
    try {
      const formData = new FormData();
      formData.append('name', avatarName.trim());
      for (const item of uploadFiles) {
        formData.append('paths', item.path);
        formData.append('files', item.file, item.file.name);
      }
      const response = await fetch('/api/avatars/create', { method: 'POST', body: formData });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || '创建桌宠失败');
      setAvatars(payload.avatars || []);
      setSelectedCharacterId(payload.avatar.characterId);
      setAvatarName('');
      setUploadFiles([]);
      setMessage(`已添加 ${payload.avatar.characterId}`);
      window.dispatchEvent(new CustomEvent('atri-avatars-updated', { detail: payload.avatars || [] }));
    } catch (uploadError) {
      setError(uploadError.message || '创建桌宠失败');
    } finally {
      setBusy(false);
    }
  };

  const selectCurrentAvatar = () => {
    if (!selectedAvatar) return;
    try { localStorage.setItem(AVATAR_KEY, selectedAvatar.id); } catch { /* Keep the selection for this page session. */ }
    setActiveAvatarId(selectedAvatar.id);
    window.dispatchEvent(new CustomEvent('atri-avatar-selected', { detail: selectedAvatar.id }));
  };

  const togglePetVisibility = () => {
    const next = !isPetVisible;
    setIsPetVisible(next);
    try { localStorage.setItem(VISIBILITY_KEY, String(next)); } catch { /* Keep the visibility setting for this page session. */ }
    window.dispatchEvent(new CustomEvent('atri-avatar-visibility-changed', { detail: next }));
  };

  const uploadBytes = uploadFiles.reduce((total, item) => total + item.file.size, 0);
  const isActive = selectedAvatar && (activeAvatarId === selectedAvatar.id || activeAvatarId === selectedAvatar.characterId);

  return createPortal(<div className="avatar-manager-backdrop" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="avatar-manager-page" role="dialog" aria-modal="true" aria-label="桌宠设置">
      <header className="avatar-manager-header">
        <div><PawPrint size={18} /><strong>桌宠设置</strong></div>
        <button type="button" className="icon-button" onClick={onClose} title="关闭" aria-label="关闭桌宠设置"><X size={17} /></button>
      </header>
      <div className="avatar-manager-layout">
        <aside className="avatar-manager-list" aria-label="桌宠文件夹">
          <div className="avatar-manager-list-heading"><strong>桌宠文件夹</strong><span>{pets.length}</span></div>
          <div className="avatar-manager-pet-list">
            {pets.map((avatar) => <button type="button" key={avatar.characterId} className={`avatar-manager-pet-row ${selectedCharacterId === avatar.characterId ? 'is-selected' : ''}`} onClick={() => setSelectedCharacterId(avatar.characterId)}>
              <span className="avatar-manager-pet-thumb">{avatar.type === 'image' ? <img src={avatar.assetUrl} alt="" /> : <PawPrint size={15} />}</span>
              <span className="avatar-manager-pet-text"><strong>{avatar.characterId}</strong><small>{avatar.type === 'image' ? 'PNG 图片' : 'Live2D'}</small></span>
              {(activeAvatarId === avatar.id || activeAvatarId === avatar.characterId) && <span className="avatar-manager-active-dot" title="当前桌宠" />}
            </button>)}
            {pets.length === 0 && !error && <p className="avatar-manager-empty">还没有可用桌宠</p>}
          </div>
        </aside>
        <main className="avatar-manager-main">
          <section className="avatar-manager-preview-section">
            <div className="avatar-manager-preview-heading"><div><strong>{selectedAvatar?.characterId || '桌宠预览'}</strong><span>{selectedAvatar ? selectedAvatar.name : '从左侧选择一个桌宠'}</span></div>
              <div className="avatar-manager-preview-actions">
                <button type="button" className="avatar-manager-visibility-button" onClick={togglePetVisibility} aria-pressed={isPetVisible}>{isPetVisible ? <><Eye size={14} />隐藏桌宠</> : <><EyeOff size={14} />显示桌宠</>}</button>
                {selectedAvatar && <button type="button" className={`avatar-manager-use-button ${isActive ? 'is-active' : ''}`} onClick={selectCurrentAvatar} disabled={isActive}>{isActive ? <><Check size={15} />当前桌宠</> : '设为当前桌宠'}</button>}
              </div>
            </div>
            <div className="avatar-manager-preview-stage">
              {selectedAvatar ? <AvatarPreview key={selectedAvatar.id} avatar={selectedAvatar} /> : <span>预览区域</span>}
            </div>
          </section>
          <form className="avatar-manager-create" onSubmit={createAvatar}>
            <div className="avatar-manager-create-heading"><strong>新建桌宠</strong><span>桌宠名称同时作为 data/pets 下的文件夹名</span></div>
            <label className="avatar-manager-name-field"><span>文件夹名称</span><input value={avatarName} maxLength={64} onChange={(event) => setAvatarName(event.target.value)} placeholder="例如：my-pet 或 亚托莉" autoComplete="off" /></label>
            <div className={`avatar-manager-dropzone ${dragging ? 'is-dragging' : ''} ${uploadFiles.length ? 'has-files' : ''}`} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false); }} onDrop={handleDrop}>
              {uploadFiles.length ? <div className="avatar-manager-upload-summary"><span className="avatar-manager-upload-icon"><Check size={17} /></span><div><strong>{uploadFiles[0].path === uploadFiles[0].file.name ? uploadFiles[0].file.name : `live2d 文件夹 · ${uploadFiles.length} 个文件`}</strong><small>{formatBytes(uploadBytes)}</small></div><button type="button" className="avatar-manager-clear-files" onClick={() => setFiles([])} aria-label="移除上传文件"><X size={14} /></button></div> : <div className="avatar-manager-drop-prompt"><ImagePlus size={19} /><strong>拖入 live2d 文件夹或图片</strong><span>支持 PNG、JPG、JPEG、GIF、WebP；图片会原样保存</span></div>}
              <div className="avatar-manager-file-actions">
                <button type="button" className="avatar-manager-file-button" onClick={() => imageInputRef.current?.click()}><ImagePlus size={14} />选择图片</button>
                <button type="button" className="avatar-manager-file-button" onClick={() => folderInputRef.current?.click()}><FolderOpen size={14} />选择 live2d 文件夹</button>
              </div>
              <input ref={imageInputRef} type="file" accept=".png,.jpg,.jpeg,.gif,.webp,image/png,image/jpeg,image/gif,image/webp" hidden onChange={chooseImage} />
              <input ref={folderInputRef} type="file" accept=".json,.png,.jpg,.jpeg,.gif,.webp,.moc3,.motion3,.exp3,.physics3,.pose3,.userdata3,.cdi3,.wav,.mp3,.ogg" webkitdirectory="" directory="" multiple hidden onChange={chooseFolder} />
            </div>
            <div className="avatar-manager-create-footer"><p className={error ? 'is-error' : 'is-message'} role={error ? 'alert' : 'status'}>{error || message}</p><button type="submit" className="avatar-manager-create-button" disabled={busy || !uploadFiles.length}>{busy ? '正在保存…' : '创建桌宠'}</button></div>
          </form>
        </main>
      </div>
    </section>
  </div>, document.body);
}

export default AvatarManagerPage;

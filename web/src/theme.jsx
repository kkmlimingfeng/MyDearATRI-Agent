import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Palette, RotateCcw, Upload, X } from 'lucide-react';

export const themePresets = {
  gray: { label: '浅绿', canvas: '#e8efea', panel: '#fbfdfb', accent: '#39836a', line: '#d8e2dc' },
  blue: { label: '浅蓝', canvas: '#e8eff4', panel: '#f9fcfe', accent: '#477f9f', line: '#d4e0e8' },
  yellow: { label: '浅黄', canvas: '#f1efdf', panel: '#fffef7', accent: '#8a7942', line: '#e4dfc7' },
  red: { label: '浅红', canvas: '#f2e9e8', panel: '#fffafa', accent: '#a96360', line: '#e7d7d5' },
};

export function registerTheme(id, definition) {
  if (!/^[a-z0-9_-]+$/i.test(id) || !definition?.label) throw new Error('主题需要有效 ID 和名称');
  for (const key of ['canvas', 'panel', 'accent', 'line']) {
    if (!CSS.supports('color', definition[key])) throw new Error(`主题颜色无效: ${key}`);
  }
  themePresets[id] = { ...definition };
}

const storageKey = 'atri.theme.v1';
const defaults = { ...themePresets.gray, image: '', chatImageOpacity: 22, workflowImageOpacity: 22 };

function applyTheme(theme) {
  const root = document.documentElement;
  root.style.setProperty('--canvas', theme.canvas);
  root.style.setProperty('--panel', theme.panel);
  root.style.setProperty('--green', theme.accent);
  root.style.setProperty('--line', theme.line);
  root.style.setProperty('--theme-accent', theme.accent);
  root.style.setProperty('--theme-image', theme.image ? `url("${theme.image}")` : 'none');
  const legacyOpacity = theme.imageOpacity ?? 22;
  root.style.setProperty('--theme-chat-image-opacity', `${Math.max(0, Math.min(100, Number(theme.chatImageOpacity ?? legacyOpacity))) / 100}`);
  root.style.setProperty('--theme-workflow-image-opacity', `${Math.max(0, Math.min(100, Number(theme.workflowImageOpacity ?? legacyOpacity))) / 100}`);
  root.dataset.theme = theme.id || 'custom';
}

function readTheme() {
  try { return { ...defaults, ...JSON.parse(localStorage.getItem(storageKey) || '{}') }; }
  catch { return defaults; }
}

async function encodeBackground(file) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 1920 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return canvas.toDataURL('image/webp', 0.82);
}

async function saveBackgroundToSystem(image) {
  const response = await fetch('/api/theme/background', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || '背景图片保存到系统失败');
  return result.url;
}

export function ThemePicker() {
  const [theme, setTheme] = useState(readTheme);
  const [open, setOpen] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [storageError, setStorageError] = useState(false);
  const fileInput = useRef(null);
  const migratingLegacyImage = useRef(false);

  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem(storageKey, JSON.stringify(theme));
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
    window.dispatchEvent(new CustomEvent('atri-theme-updated', { detail: theme }));
  }, [theme]);

  useEffect(() => {
    const update = (event) => setTheme((current) => current === event.detail ? current : event.detail);
    window.addEventListener('atri-theme-updated', update);
    return () => window.removeEventListener('atri-theme-updated', update);
  }, []);

  useEffect(() => {
    if (!theme.image?.startsWith('data:image/webp;base64,') || migratingLegacyImage.current) return;
    migratingLegacyImage.current = true;
    const legacyImage = theme.image;
    saveBackgroundToSystem(legacyImage).then((url) => {
      setTheme((current) => current.image === legacyImage ? { ...current, image: url } : current);
    }).catch((error) => {
      setUploadError(`${error.message}，旧图片暂时仍保存在浏览器中。`);
    });
  }, [theme.image]);

  const choosePreset = (id) => setTheme((current) => ({ ...themePresets[id], id, image: current.image, chatImageOpacity: current.chatImageOpacity, workflowImageOpacity: current.workflowImageOpacity }));
  const setColor = (key, value) => setTheme((current) => ({ ...current, id: 'custom', [key]: value }));
  const uploadBackground = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadError('');
    const imageFile = file.type.startsWith('image/') || /\.(avif|gif|jpe?g|png|webp|bmp)$/i.test(file.name);
    if (!imageFile) {
      setUploadError('请选择图片文件。');
      event.target.value = '';
      return;
    }
    setUploading(true);
    try {
      const image = await saveBackgroundToSystem(await encodeBackground(file));
      setTheme((current) => ({ ...current, id: 'custom', image }));
    } catch {
      setUploadError('图片处理或保存失败，请确认后端服务正在运行后重试。');
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  };

  return <div className="theme-control">
    <button className="icon-button" title="外观主题" aria-label="外观主题" onClick={() => setOpen((value) => !value)}><Palette size={16} /></button>
    {open && <section className="theme-popover" aria-label="外观主题设置">
      <header><strong>外观主题</strong><button className="icon-button" title="关闭" onClick={() => setOpen(false)}><X size={14} /></button></header>
      <div className="theme-presets">{Object.entries(themePresets).map(([id, preset]) => <button key={id} className={theme.id === id ? 'selected' : ''} onClick={() => choosePreset(id)}><span style={{ background: preset.canvas }} /><span>{preset.label}</span></button>)}</div>
      <div className="theme-colors">{[['canvas', '画布'], ['panel', '面板'], ['accent', '强调色']].map(([key, label]) => <label key={key}><span>{label}</span><input type="color" value={theme[key]} onChange={(event) => setColor(key, event.target.value)} /></label>)}</div>
      <div className="theme-image-opacity">
        <label htmlFor="theme-chat-image-opacity">对话页背景透明度</label>
        <input id="theme-chat-image-opacity" type="range" min="0" max="100" value={theme.chatImageOpacity ?? theme.imageOpacity ?? 22} disabled={!theme.image} onChange={(event) => setTheme((current) => ({ ...current, id: 'custom', chatImageOpacity: Number(event.target.value) }))} />
        <output>{theme.chatImageOpacity ?? theme.imageOpacity ?? 22}%</output>
      </div>
      <div className="theme-image-opacity">
        <label htmlFor="theme-workflow-image-opacity">工作流页背景透明度</label>
        <input id="theme-workflow-image-opacity" type="range" min="0" max="100" value={theme.workflowImageOpacity ?? theme.imageOpacity ?? 22} disabled={!theme.image} onChange={(event) => setTheme((current) => ({ ...current, id: 'custom', workflowImageOpacity: Number(event.target.value) }))} />
        <output>{theme.workflowImageOpacity ?? theme.imageOpacity ?? 22}%</output>
      </div>
      <button className="theme-upload" type="button" onClick={() => fileInput.current?.click()} disabled={uploading}>
        <Upload size={14} />{uploading ? '正在处理图片…' : theme.image ? '更换背景图片' : '上传背景图片'}
      </button>
      <input ref={fileInput} className="theme-file-input" type="file" accept="image/*" onChange={uploadBackground} />
      {uploadError && <p className="theme-error">{uploadError}</p>}
      {storageError && <p className="theme-error">主题无法保存到浏览器本地存储，请移除较大的背景图片后重试。</p>}
      {theme.image && <button className="theme-clear-image" onClick={() => setTheme((current) => ({ ...current, image: '' }))}><X size={13} />移除背景图片</button>}
      <button className="theme-reset" onClick={() => setTheme({ ...defaults, id: 'gray' })}><RotateCcw size={13} />恢复默认</button>
    </section>}
  </div>;
}

export function useTheme() {
  useLayoutEffect(() => { applyTheme(readTheme()); }, []);
}

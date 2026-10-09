import { useEffect, useState } from 'react';
import { Palette, RotateCcw, Upload, X } from 'lucide-react';

export const themePresets = {
  gray: { label: '雾灰', canvas: '#e8ebea', panel: '#fbfcfb', accent: '#39836a', line: '#d8dfdc' },
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
const defaults = { ...themePresets.gray, image: '' };

function applyTheme(theme) {
  const root = document.documentElement;
  root.style.setProperty('--canvas', theme.canvas);
  root.style.setProperty('--panel', theme.panel);
  root.style.setProperty('--green', theme.accent);
  root.style.setProperty('--line', theme.line);
  root.style.setProperty('--theme-accent', theme.accent);
  root.style.setProperty('--theme-image', theme.image ? `url("${theme.image}")` : 'none');
  root.dataset.theme = theme.id || 'custom';
}

function readTheme() {
  try { return { ...defaults, ...JSON.parse(localStorage.getItem(storageKey) || '{}') }; }
  catch { return defaults; }
}

export function ThemePicker() {
  const [theme, setTheme] = useState(readTheme);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem(storageKey, JSON.stringify(theme));
  }, [theme]);

  const choosePreset = (id) => setTheme({ ...themePresets[id], id, image: theme.image });
  const setColor = (key, value) => setTheme((current) => ({ ...current, id: 'custom', [key]: value }));
  const uploadBackground = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/') || file.size > 1_200_000) {
      event.target.value = '';
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setTheme((current) => ({ ...current, id: 'custom', image: reader.result }));
    reader.readAsDataURL(file);
    event.target.value = '';
  };

  return <div className="theme-control">
    <button className="icon-button" title="外观主题" aria-label="外观主题" onClick={() => setOpen((value) => !value)}><Palette size={16} /></button>
    {open && <section className="theme-popover" aria-label="外观主题设置">
      <header><strong>外观主题</strong><button className="icon-button" title="关闭" onClick={() => setOpen(false)}><X size={14} /></button></header>
      <div className="theme-presets">{Object.entries(themePresets).map(([id, preset]) => <button key={id} className={theme.id === id ? 'selected' : ''} onClick={() => choosePreset(id)}><span style={{ background: preset.canvas }} /><span>{preset.label}</span></button>)}</div>
      <div className="theme-colors">{[['canvas', '画布'], ['panel', '面板'], ['accent', '强调色']].map(([key, label]) => <label key={key}><span>{label}</span><input type="color" value={theme[key]} onChange={(event) => setColor(key, event.target.value)} /></label>)}</div>
      <label className="theme-upload"><Upload size={14} />{theme.image ? '更换背景图片' : '上传背景图片'}<input type="file" accept="image/*" onChange={uploadBackground} /></label>
      {theme.image && <button className="theme-clear-image" onClick={() => setTheme((current) => ({ ...current, image: '' }))}><X size={13} />移除背景图片</button>}
      <button className="theme-reset" onClick={() => setTheme({ ...defaults, id: 'gray' })}><RotateCcw size={13} />恢复默认</button>
    </section>}
  </div>;
}

export function useTheme() {
  useEffect(() => { applyTheme(readTheme()); }, []);
}

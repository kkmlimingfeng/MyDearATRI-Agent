import { useEffect, useState } from 'react';
import { ArrowUp, Folder, FolderUp, Plus, Save, Search, X } from 'lucide-react';
import SandboxPermissionMatrix, { permissionsForSandboxMode, updateSandboxPermission } from '../chat/SandboxPermissionMatrix';

export default function CapabilityPanel({ kind, onClose, onChanged }) {
  const [items, setItems] = useState([]);
  const [files, setFiles] = useState([]);
  const [selected, setSelected] = useState('');
  const [content, setContent] = useState('');
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savedContent, setSavedContent] = useState('');
  const [sandboxSettings, setSandboxSettings] = useState({
    workspace: '',
    permission: 'workspace',
    permissions: permissionsForSandboxMode('workspace'),
  });
  const [sandboxRuntime, setSandboxRuntime] = useState(null);
  const [sandboxBusy, setSandboxBusy] = useState(false);
  const [sandboxError, setSandboxError] = useState('');
  const [sandboxSaved, setSandboxSaved] = useState(false);
  const [sandboxBrowseOpen, setSandboxBrowseOpen] = useState(false);
  const [sandboxBrowsePath, setSandboxBrowsePath] = useState('');
  const [sandboxBrowseParent, setSandboxBrowseParent] = useState(null);
  const [sandboxDirectories, setSandboxDirectories] = useState([]);
  const [sandboxBrowseBusy, setSandboxBrowseBusy] = useState(false);
  const [sandboxBrowseError, setSandboxBrowseError] = useState('');
  const title = { skills: '技能配置', tools: '工具箱配置', memory: '记忆文件' }[kind];

  useEffect(() => {
    setError('');
    fetch(kind === 'memory' ? '/api/memories' : `/api/${kind}`)
      .then((response) => response.ok ? response.json() : response.json().then((result) => Promise.reject(new Error(result.error || '读取失败'))))
      .then((result) => {
        if (result.error) throw new Error(result.error);
        setItems(result.items || []);
        setFiles(result.files || []);
        setSelected(result.files?.[0] || '');
      })
      .catch((cause) => setError(cause.message));
  }, [kind]);

  useEffect(() => {
    if (kind !== 'tools') return;
    fetch('/api/sandbox/settings')
      .then((response) => response.ok ? response.json() : response.json().then((result) => Promise.reject(new Error(result.error || '读取沙箱设置失败'))))
      .then((result) => {
        setSandboxSettings(result.settings);
        setSandboxRuntime(result.runtime);
        setSandboxError('');
      })
      .catch((cause) => setSandboxError(cause.message));
  }, [kind]);

  useEffect(() => {
    if (!selected) return;
    fetch(`/api/memory?file=${encodeURIComponent(selected)}`)
      .then((response) => response.ok ? response.json() : response.json().then((result) => Promise.reject(new Error(result.error || '读取失败'))))
      .then((result) => { if (result.error) throw new Error(result.error); setContent(result.content); setSavedContent(result.content); })
      .catch((cause) => setError(cause.message));
  }, [selected]);

  const update = async (updates) => {
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/api/${kind}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ updates }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '保存失败');
      setItems(result.items);
      onChanged?.();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  };

  const saveMemory = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/memory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file: selected, content }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '保存失败');
      setSavedContent(content);
      onChanged?.();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  };

  const saveSandbox = async () => {
    setSandboxBusy(true);
    setSandboxError('');
    try {
      const response = await fetch('/api/sandbox/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sandboxSettings),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '保存沙箱设置失败');
      setSandboxSettings(result.settings);
      setSandboxRuntime(result.runtime);
      setSandboxSaved(true);
      window.dispatchEvent(new CustomEvent('atri-sandbox-settings', { detail: { settings: result.settings, runtime: result.runtime } }));
    } catch (cause) { setSandboxError(cause.message); }
    finally { setSandboxBusy(false); }
  };

  const loadSandboxDirectory = async (path) => {
    setSandboxBrowseBusy(true);
    setSandboxBrowseError('');
    try {
      const query = path ? `?path=${encodeURIComponent(path)}` : '';
      const response = await fetch(`/api/sandbox/directories${query}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '读取目录失败');
      setSandboxBrowsePath(result.path);
      setSandboxBrowseParent(result.parent);
      setSandboxDirectories(result.directories || []);
    } catch (cause) { setSandboxBrowseError(cause.message); }
    finally { setSandboxBrowseBusy(false); }
  };

  const openSandboxBrowser = () => {
    setSandboxBrowseOpen(true);
    void loadSandboxDirectory(sandboxSettings.workspace || undefined);
  };

  const useSandboxDirectory = () => {
    setSandboxSettings((current) => ({ ...current, workspace: sandboxBrowsePath }));
    setSandboxSaved(false);
    setSandboxBrowseOpen(false);
  };

  const visible = items.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase()));
  return <>
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="capability-modal" role="dialog" aria-modal="true" aria-label={title}>
      <header><div><span className="eyebrow">MODULE CONFIG</span><h2>{title}</h2></div><button className="icon-button" onClick={onClose} title="关闭"><X size={17} /></button></header>
      {kind === 'memory' ? <div className="memory-layout"><nav>{files.map((file) => <button key={file} className={file === selected ? 'selected' : ''} onClick={() => setSelected(file)}>{file}</button>)}</nav><textarea value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} aria-label="记忆内容" /></div> : <>
        <div className="capability-toolbar"><label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`搜索${kind === 'skills' ? '技能' : '工具'}`} /></label><button disabled={busy || !visible.length} onClick={() => update(Object.fromEntries(visible.map((item) => [item.id, true])))}>全部开启</button><button disabled={busy || !visible.length} onClick={() => update(Object.fromEntries(visible.map((item) => [item.id, false])))}>全部关闭</button></div>
        {kind === 'tools' && <section className="sandbox-settings" aria-label="代码沙箱设置">
          <div className="sandbox-settings-heading"><div><strong>代码沙箱</strong><small>Python：{sandboxRuntime?.python || '读取中…'}</small></div><span className={sandboxRuntime?.filesystem_permissions_available ? 'sandbox-runtime-ready' : 'sandbox-runtime-unavailable'}>{sandboxRuntime?.filesystem_permissions_available ? 'Firejail · Landlock 可用' : '需要 Linux / WSL 和 Landlock ABI 3'}</span></div>
          <div className="sandbox-workspace-row"><label><span>工作空间</span><input value={sandboxSettings.workspace} onChange={(event) => { setSandboxSettings((current) => ({ ...current, workspace: event.target.value })); setSandboxSaved(false); }} spellCheck={false} /></label><button type="button" className="secondary-button" onClick={openSandboxBrowser}><Folder size={15} />选择目录</button></div>
          <div className="sandbox-permission-options" role="radiogroup" aria-label="沙箱权限">
            <label className={sandboxSettings.permission === 'workspace' ? 'selected' : ''}><input type="radio" name="sandbox-permission" checked={sandboxSettings.permission === 'workspace'} onChange={() => { setSandboxSettings((current) => ({ ...current, permission: 'workspace', permissions: permissionsForSandboxMode('workspace') })); setSandboxSaved(false); }} /><span><strong>工作空间权限</strong><small>工作空间内可读写；外部只读</small></span></label>
            <label className={sandboxSettings.permission === 'custom' ? 'selected' : ''}><input type="radio" name="sandbox-permission" checked={sandboxSettings.permission === 'custom'} onChange={() => { setSandboxSettings((current) => ({ ...current, permission: 'custom' })); setSandboxSaved(false); }} /><span><strong>自定义</strong><small>按操作设置工作空间内外权限</small></span></label>
            <label className={`sandbox-permission-full ${sandboxSettings.permission === 'full' ? 'selected' : ''}`}><input type="radio" name="sandbox-permission" checked={sandboxSettings.permission === 'full'} onChange={() => { setSandboxSettings((current) => ({ ...current, permission: 'full', permissions: permissionsForSandboxMode('full') })); setSandboxSaved(false); }} /><span><strong>全部权限</strong><small>允许访问和修改工作空间外文件</small></span></label>
          </div>
          {sandboxSettings.permission === 'custom' && <SandboxPermissionMatrix settings={sandboxSettings} onChange={(scope, action, allowed) => { setSandboxSettings((current) => updateSandboxPermission(current, scope, action, allowed)); setSandboxSaved(false); }} />}
          <div className="sandbox-settings-actions"><span role={sandboxError ? 'alert' : 'status'}>{sandboxError || (sandboxSaved ? '已保存到本机设置' : '设置只保存在本机')}</span><button className="primary-button" disabled={sandboxBusy || sandboxSaved} onClick={saveSandbox}>{sandboxBusy ? <span className="spinner" /> : <Save size={14} />}{sandboxBusy ? '保存中…' : '保存沙箱设置'}</button></div>
        </section>}
        <div className="capability-list">{visible.map((item) => <label key={item.id}><div><strong>{item.name}</strong><p>{item.description || '暂无简介'}</p></div><input type="checkbox" checked={item.enabled} disabled={busy} onChange={(event) => update({ [item.id]: event.target.checked })} /></label>)}</div>
      </>}
      <footer><span>{error || (kind === 'memory' ? `${files.length} 个文件${content !== savedContent ? ' · 未保存' : ''}` : `${items.filter((item) => item.enabled).length} / ${items.length} 已启用`)}</span><div>{kind !== 'memory' && <button className="secondary-button" disabled title="创建功能尚未实现"><Plus size={14} />新建{kind === 'skills' ? '技能' : '工具'}</button>}{kind === 'memory' && <button className="primary-button" disabled={busy || !selected || content === savedContent} onClick={saveMemory}><Save size={14} />保存记忆</button>}</div></footer>
    </section>
    </div>
    {sandboxBrowseOpen && <div className="sandbox-picker-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSandboxBrowseOpen(false); }}><section className="sandbox-picker" role="dialog" aria-modal="true" aria-label="选择工作空间"><header><div><strong>选择工作空间</strong><small>{sandboxBrowsePath}</small></div><div><button className="icon-button" disabled={!sandboxBrowseParent || sandboxBrowseBusy} onClick={() => loadSandboxDirectory(sandboxBrowseParent)} title="上一级" aria-label="上一级"><FolderUp size={16} /></button><button className="icon-button" onClick={() => setSandboxBrowseOpen(false)} title="关闭" aria-label="关闭"><X size={16} /></button></div></header><div className="sandbox-directory-list">{sandboxBrowseBusy ? <span className="sandbox-picker-empty">正在读取目录…</span> : sandboxBrowseError ? <span className="sandbox-picker-error">{sandboxBrowseError}</span> : sandboxDirectories.length ? sandboxDirectories.map((directory) => <button key={directory.path} onClick={() => loadSandboxDirectory(directory.path)}><Folder size={15} /><span>{directory.name}</span><ArrowUp size={13} /></button>) : <span className="sandbox-picker-empty">此目录下没有子目录</span>}</div><footer><span>当前目录将作为命令的工作目录</span><button className="primary-button" disabled={!sandboxBrowsePath || sandboxBrowseBusy} onClick={useSandboxDirectory}><Folder size={14} />使用此目录</button></footer></section></div>}
  </>;
}

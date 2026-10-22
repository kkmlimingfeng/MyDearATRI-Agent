import { useEffect, useState } from 'react';
import { ArrowUp, FileUp, Folder, FolderUp, Plus, Save, Search, Trash2, X } from 'lucide-react';
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
  const [mcpServers, setMcpServers] = useState([]);
  const [mcpConfigText, setMcpConfigText] = useState('');
  const [mcpDraft, setMcpDraft] = useState({ name: '', transport: 'stdio', command: '', args: '[]', cwd: '', url: '', env: '{}', headers: '{}' });
  const [sandboxSettings, setSandboxSettings] = useState({
    workspace: '',
    permission: 'workspace',
    permissions: permissionsForSandboxMode('workspace'),
    allow_command_execution: false,
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
  const title = { skills: '技能配置', tools: '工具箱配置', memory: '记忆文件', mcp: 'MCP 服务' }[kind];

  useEffect(() => {
    setError('');
    fetch(kind === 'memory' ? '/api/memories' : `/api/${kind}`)
      .then((response) => response.ok ? response.json() : response.json().then((result) => Promise.reject(new Error(result.error || '读取失败'))))
      .then((result) => {
        if (result.error) throw new Error(result.error);
        setItems(result.items || []);
        setMcpServers(result.servers || []);
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

  const importSkills = async (file) => {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/skills/import', { method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '技能导入失败');
      setItems(result.items || []);
      onChanged?.();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  };

  const sendMcp = async (payload) => {
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/mcp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'MCP 配置保存失败');
      setMcpServers(result.servers || []);
      if (payload.action === 'import') setMcpConfigText('');
      onChanged?.();
      return true;
    } catch (cause) { setError(cause.message); return false; }
    finally { setBusy(false); }
  };

  const saveMcpDraft = async (event) => {
    event.preventDefault();
    try {
      const server = mcpDraft.transport === 'http'
        ? { url: mcpDraft.url.trim(), headers: JSON.parse(mcpDraft.headers), enabled: true }
        : { command: mcpDraft.command.trim(), args: JSON.parse(mcpDraft.args), cwd: mcpDraft.cwd.trim(), env: JSON.parse(mcpDraft.env), enabled: true };
      const saved = await sendMcp({ action: 'save', name: mcpDraft.name.trim(), server });
      if (saved) setMcpDraft({ name: '', transport: 'stdio', command: '', args: '[]', cwd: '', url: '', env: '{}', headers: '{}' });
    } catch (cause) { setError(`配置格式无效：${cause.message}`); }
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
      {kind === 'mcp' ? <div className="mcp-settings">
        <section className="mcp-import">
          <div><strong>导入已有配置</strong><small>支持 Claude 的 mcpServers JSON 和 Codex 的 mcp_servers TOML；同名服务会更新。密钥只保存在本机。</small></div>
          <textarea value={mcpConfigText} onChange={(event) => setMcpConfigText(event.target.value)} spellCheck={false} placeholder={'粘贴配置内容，或选择 .json / .toml 文件'} aria-label="MCP 配置" />
          <div className="mcp-actions"><label className="secondary-button"><FileUp size={14} />选择配置文件<input type="file" accept=".json,.toml,application/json" hidden onChange={async (event) => { const file = event.target.files?.[0]; if (file) setMcpConfigText(await file.text()); event.target.value = ''; }} /></label><button className="primary-button" disabled={busy || !mcpConfigText.trim()} onClick={() => sendMcp({ action: 'import', content: mcpConfigText })}>{busy ? '导入中…' : '导入配置'}</button></div>
        </section>
        <form className="mcp-add-form" onSubmit={saveMcpDraft}>
          <strong>添加 MCP 服务</strong>
          <div className="mcp-form-grid"><label>名称<input required value={mcpDraft.name} onChange={(event) => setMcpDraft((current) => ({ ...current, name: event.target.value }))} placeholder="filesystem" /></label><label>连接方式<select value={mcpDraft.transport} onChange={(event) => setMcpDraft((current) => ({ ...current, transport: event.target.value }))}><option value="stdio">本地 stdio（沙箱）</option><option value="http">远程 HTTP</option></select></label></div>
          {mcpDraft.transport === 'stdio' ? <><label>启动命令<input required value={mcpDraft.command} onChange={(event) => setMcpDraft((current) => ({ ...current, command: event.target.value }))} placeholder="npx" /></label><label>参数（JSON 数组）<input value={mcpDraft.args} onChange={(event) => setMcpDraft((current) => ({ ...current, args: event.target.value }))} spellCheck={false} placeholder='["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]' /></label><label>工作目录（可选）<input value={mcpDraft.cwd} onChange={(event) => setMcpDraft((current) => ({ ...current, cwd: event.target.value }))} spellCheck={false} /></label><label>环境变量（JSON 对象）<textarea value={mcpDraft.env} onChange={(event) => setMcpDraft((current) => ({ ...current, env: event.target.value }))} spellCheck={false} /></label></> : <><label>服务 URL<input required value={mcpDraft.url} onChange={(event) => setMcpDraft((current) => ({ ...current, url: event.target.value }))} placeholder="https://example.com/mcp" /></label><label>请求头（JSON 对象）<textarea value={mcpDraft.headers} onChange={(event) => setMcpDraft((current) => ({ ...current, headers: event.target.value }))} spellCheck={false} /></label></>}
          <div className="mcp-actions"><span>stdio 进程使用当前代码沙箱权限启动。</span><button className="primary-button" disabled={busy}><Plus size={14} />添加服务</button></div>
        </form>
        <div className="mcp-server-list">{mcpServers.map((server) => <article key={server.id}><div className="mcp-server-heading"><div><strong>{server.name}</strong><small>{server.transport === 'stdio' ? 'stdio' : 'HTTP'} · {server.command}</small></div><span className={`mcp-status mcp-status-${server.status}`}>{({ ready: '运行中', error: '启动失败', disabled: '已禁用', stopped: '待启动' })[server.status] || server.status}{server.status === 'ready' ? ` · ${server.tools} 个工具` : ''}</span></div>{server.error && <p className="mcp-server-error">{server.error}</p>}<div className="mcp-server-actions"><label><input type="checkbox" checked={server.enabled} disabled={busy} onChange={(event) => sendMcp({ action: 'toggle', name: server.id, enabled: event.target.checked })} />启用</label><button className="icon-button danger-button" title="删除服务" aria-label={`删除 ${server.name}`} disabled={busy} onClick={() => sendMcp({ action: 'delete', name: server.id })}><Trash2 size={15} /></button></div></article>)}{!mcpServers.length && <p className="mcp-empty">还没有 MCP 服务</p>}</div>
      </div> : kind === 'memory' ? <div className="memory-layout"><nav>{files.map((file) => <button key={file} className={file === selected ? 'selected' : ''} onClick={() => setSelected(file)}>{file}</button>)}</nav><textarea value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} aria-label="记忆内容" /></div> : <>
        <div className="capability-toolbar"><label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`搜索${kind === 'skills' ? '技能' : '工具'}`} /></label><button disabled={busy || !visible.length} onClick={() => update(Object.fromEntries(visible.map((item) => [item.id, true])))}>全部开启</button><button disabled={busy || !visible.length} onClick={() => update(Object.fromEntries(visible.map((item) => [item.id, false])))}>全部关闭</button></div>
        {kind === 'skills' && <div className="skill-import-row"><span>支持包含 SKILL.md 和 references/ 的技能 ZIP</span><label className="secondary-button"><FileUp size={14} />导入技能 ZIP<input type="file" accept=".zip,application/zip" hidden disabled={busy} onChange={(event) => { void importSkills(event.target.files?.[0]); event.target.value = ''; }} /></label></div>}
        {kind === 'tools' && <section className="sandbox-settings" aria-label="代码沙箱设置">
          <div className="sandbox-settings-heading"><div><strong>代码沙箱</strong><small>Python：{sandboxRuntime?.python || '读取中…'}</small></div><span className={sandboxRuntime?.filesystem_permissions_available ? 'sandbox-runtime-ready' : 'sandbox-runtime-unavailable'}>{sandboxRuntime?.filesystem_permissions_available ? 'Firejail · Landlock 可用' : '需要 Linux / WSL 和 Landlock ABI 3'}</span></div>
          <div className="sandbox-workspace-row"><label><span>工作空间</span><input value={sandboxSettings.workspace} onChange={(event) => { setSandboxSettings((current) => ({ ...current, workspace: event.target.value })); setSandboxSaved(false); }} spellCheck={false} /></label><button type="button" className="secondary-button" onClick={openSandboxBrowser}><Folder size={15} />选择目录</button></div>
          <div className="sandbox-permission-options" role="radiogroup" aria-label="沙箱权限">
            <label className={sandboxSettings.permission === 'workspace' ? 'selected' : ''}><input type="radio" name="sandbox-permission" checked={sandboxSettings.permission === 'workspace'} onChange={() => { setSandboxSettings((current) => ({ ...current, permission: 'workspace', permissions: permissionsForSandboxMode('workspace') })); setSandboxSaved(false); }} /><span><strong>工作空间权限</strong><small>工作空间内可读写；外部只读</small></span></label>
            <label className={sandboxSettings.permission === 'custom' ? 'selected' : ''}><input type="radio" name="sandbox-permission" checked={sandboxSettings.permission === 'custom'} onChange={() => { setSandboxSettings((current) => ({ ...current, permission: 'custom' })); setSandboxSaved(false); }} /><span><strong>自定义</strong><small>按操作设置工作空间内外权限</small></span></label>
            <label className={`sandbox-permission-full ${sandboxSettings.permission === 'full' ? 'selected' : ''}`}><input type="radio" name="sandbox-permission" checked={sandboxSettings.permission === 'full'} onChange={() => { setSandboxSettings((current) => ({ ...current, permission: 'full', permissions: permissionsForSandboxMode('full') })); setSandboxSaved(false); }} /><span><strong>全部权限</strong><small>允许访问和修改工作空间外文件</small></span></label>
          </div>
          {sandboxSettings.permission === 'custom' && <SandboxPermissionMatrix settings={sandboxSettings} onChange={(scope, action, allowed) => { setSandboxSettings((current) => updateSandboxPermission(current, scope, action, allowed)); setSandboxSaved(false); }} />}
          <label className={`sandbox-execution-toggle ${sandboxSettings.allow_command_execution ? 'is-enabled' : ''}`}>
            <input type="checkbox" checked={sandboxSettings.allow_command_execution} onChange={(event) => { setSandboxSettings((current) => ({ ...current, allow_command_execution: event.target.checked })); setSandboxSaved(false); }} />
            <span><strong>允许命令和 MCP 工具执行</strong><small>关闭时执行类调用默认拒绝；开启后仍受上方文件权限约束。</small></span>
          </label>
          <div className="sandbox-settings-actions"><span role={sandboxError ? 'alert' : 'status'}>{sandboxError || (sandboxSaved ? '已保存到本机设置' : '设置只保存在本机')}</span><button className="primary-button" disabled={sandboxBusy || sandboxSaved} onClick={saveSandbox}>{sandboxBusy ? <span className="spinner" /> : <Save size={14} />}{sandboxBusy ? '保存中…' : '保存沙箱设置'}</button></div>
        </section>}
        <div className="capability-list">{visible.map((item) => <label key={item.id}><div><strong>{item.name}</strong><p>{item.description || '暂无简介'}</p></div><input type="checkbox" checked={item.enabled} disabled={busy} onChange={(event) => update({ [item.id]: event.target.checked })} /></label>)}</div>
      </>}
      <footer><span>{error || (kind === 'memory' ? `${files.length} 个文件${content !== savedContent ? ' · 未保存' : ''}` : kind === 'mcp' ? `${mcpServers.length} 个 MCP 服务 · 配置保存在本机` : `${items.filter((item) => item.enabled).length} / ${items.length} 已启用`)}</span><div>{kind === 'memory' && <button className="primary-button" disabled={busy || !selected || content === savedContent} onClick={saveMemory}><Save size={14} />保存记忆</button>}</div></footer>
    </section>
    </div>
    {sandboxBrowseOpen && <div className="sandbox-picker-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSandboxBrowseOpen(false); }}><section className="sandbox-picker" role="dialog" aria-modal="true" aria-label="选择工作空间"><header><div><strong>选择工作空间</strong><small>{sandboxBrowsePath}</small></div><div><button className="icon-button" disabled={!sandboxBrowseParent || sandboxBrowseBusy} onClick={() => loadSandboxDirectory(sandboxBrowseParent)} title="上一级" aria-label="上一级"><FolderUp size={16} /></button><button className="icon-button" onClick={() => setSandboxBrowseOpen(false)} title="关闭" aria-label="关闭"><X size={16} /></button></div></header><div className="sandbox-directory-list">{sandboxBrowseBusy ? <span className="sandbox-picker-empty">正在读取目录…</span> : sandboxBrowseError ? <span className="sandbox-picker-error">{sandboxBrowseError}</span> : sandboxDirectories.length ? sandboxDirectories.map((directory) => <button key={directory.path} onClick={() => loadSandboxDirectory(directory.path)}><Folder size={15} /><span>{directory.name}</span><ArrowUp size={13} /></button>) : <span className="sandbox-picker-empty">此目录下没有子目录</span>}</div><footer><span>当前目录将作为命令的工作目录</span><button className="primary-button" disabled={!sandboxBrowsePath || sandboxBrowseBusy} onClick={useSandboxDirectory}><Folder size={14} />使用此目录</button></footer></section></div>}
  </>;
}

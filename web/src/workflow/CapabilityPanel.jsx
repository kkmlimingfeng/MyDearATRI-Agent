import { useEffect, useState } from 'react';
import { Plus, Save, Search, X } from 'lucide-react';

export default function CapabilityPanel({ kind, onClose, onChanged }) {
  const [items, setItems] = useState([]);
  const [files, setFiles] = useState([]);
  const [selected, setSelected] = useState('');
  const [content, setContent] = useState('');
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savedContent, setSavedContent] = useState('');
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

  const visible = items.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="capability-modal" role="dialog" aria-modal="true" aria-label={title}>
      <header><div><span className="eyebrow">MODULE CONFIG</span><h2>{title}</h2></div><button className="icon-button" onClick={onClose} title="关闭"><X size={17} /></button></header>
      {kind === 'memory' ? <div className="memory-layout"><nav>{files.map((file) => <button key={file} className={file === selected ? 'selected' : ''} onClick={() => setSelected(file)}>{file}</button>)}</nav><textarea value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} aria-label="记忆内容" /></div> : <>
        <div className="capability-toolbar"><label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`搜索${kind === 'skills' ? '技能' : '工具'}`} /></label><button disabled={busy || !visible.length} onClick={() => update(Object.fromEntries(visible.map((item) => [item.id, true])))}>全部开启</button><button disabled={busy || !visible.length} onClick={() => update(Object.fromEntries(visible.map((item) => [item.id, false])))}>全部关闭</button></div>
        <div className="capability-list">{visible.map((item) => <label key={item.id}><div><strong>{item.name}</strong><p>{item.description || '暂无简介'}</p></div><input type="checkbox" checked={item.enabled} disabled={busy} onChange={(event) => update({ [item.id]: event.target.checked })} /></label>)}</div>
      </>}
      <footer><span>{error || (kind === 'memory' ? `${files.length} 个文件${content !== savedContent ? ' · 未保存' : ''}` : `${items.filter((item) => item.enabled).length} / ${items.length} 已启用`)}</span><div>{kind !== 'memory' && <button className="secondary-button" disabled title="创建功能尚未实现"><Plus size={14} />新建{kind === 'skills' ? '技能' : '工具'}</button>}{kind === 'memory' && <button className="primary-button" disabled={busy || !selected || content === savedContent} onClick={saveMemory}><Save size={14} />保存记忆</button>}</div></footer>
    </section>
  </div>;
}

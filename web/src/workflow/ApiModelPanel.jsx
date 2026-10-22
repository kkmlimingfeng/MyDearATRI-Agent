import { useEffect, useState } from 'react';
import { Plus, Save, Trash2, X } from 'lucide-react';

const emptyModel = { id: '', model_name: '', base_url: 'https://api.openai.com/v1', api_style: 'chat_completions', supports_images: false, input_token_limit: '', max_output_tokens: '' };

export default function ApiModelPanel({ initialModelId, onClose, onChanged }) {
  const [models, setModels] = useState([]);
  const [selected, setSelected] = useState('');
  const [draft, setDraft] = useState(emptyModel);
  const [apiKey, setApiKey] = useState('');
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/api-models')
      .then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || '读取模型失败'); return data; })
      .then((data) => {
        const items = data.models || [];
        setModels(items);
        const initial = items.find((item) => item.id === initialModelId) || items[0];
        if (initial) { setSelected(initial.id); setDraft(initial); }
      })
      .catch((cause) => setError(cause.message));
  }, [initialModelId]);

  const choose = (item) => {
    setCreating(false);
    setSelected(item.id);
    setDraft(item);
    setApiKey('');
    setError('');
  };
  const add = () => {
    setCreating(true);
    setSelected('');
    setDraft(emptyModel);
    setApiKey('');
    setError('');
  };
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/api-models', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...draft, input_token_limit: draft.input_token_limit == null || draft.input_token_limit === '' ? null : Number(draft.input_token_limit), max_output_tokens: draft.max_output_tokens == null || draft.max_output_tokens === '' ? null : Number(draft.max_output_tokens), api_key: apiKey }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '保存失败');
      setModels(data.models);
      setSelected(draft.id);
      setDraft(data.models.find((item) => item.id === draft.id));
      setCreating(false);
      setApiKey('');
      onChanged?.();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  };
  const clearSavedKey = async () => {
    if (!draft.has_saved_key) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/api-models', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'clear-key', id: draft.id }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '清除密钥失败');
      setModels(data.models);
      const updated = data.models.find((item) => item.id === draft.id);
      setDraft((current) => ({ ...current, has_saved_key: updated?.has_saved_key, configured: updated?.configured }));
      setApiKey('');
      onChanged?.();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!draft.custom || !window.confirm(draft.builtin ? '恢复这个内置模型的默认配置？' : '删除这个自定义模型？')) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/api-models', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'delete', id: draft.id }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '删除失败');
      setModels(data.models);
      const next = data.models.find((item) => item.id === draft.id) || data.models[0];
      setSelected(next?.id || '');
      setDraft(next || emptyModel);
      setApiKey('');
      onChanged?.();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  };

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="capability-modal api-model-modal" role="dialog" aria-modal="true" aria-label="API 模型配置">
      <header><div><span className="eyebrow">API MODELS</span><h2>模型配置</h2></div><button className="icon-button" onClick={onClose} title="关闭" disabled={busy}><X size={17} /></button></header>
      <div className="api-model-layout">
        <nav aria-label="已配置模型">
          {models.map((item) => <button key={item.id} className={!creating && selected === item.id ? 'selected' : ''} onClick={() => choose(item)}>
            <strong>{item.model_name || item.id}</strong><small>{item.id} · {item.has_saved_key ? '已保存密钥' : item.configured ? '使用环境变量' : '未配置密钥'}</small>
          </button>)}
        </nav>
        <form id="api-model-form" onSubmit={submit}>
          <label>配置 ID<input value={draft.id} disabled={!creating} onChange={(event) => setDraft({ ...draft, id: event.target.value })} placeholder="例如 my-gpt-4o" required /></label>
          <label>提供商模型 ID<input value={draft.model_name || ''} onChange={(event) => setDraft({ ...draft, model_name: event.target.value })} placeholder="例如 gpt-4o" required /></label>
          <label>API 根地址<input value={draft.base_url || ''} onChange={(event) => setDraft({ ...draft, base_url: event.target.value })} placeholder="https://api.openai.com/v1" required /><small>填到 /v1；请求路径由下方格式自动拼接。</small></label>
          <label>请求格式<select value={draft.api_style || 'chat_completions'} onChange={(event) => setDraft({ ...draft, api_style: event.target.value })}><option value="chat_completions">Chat Completions · /chat/completions</option><option value="responses">Responses · /responses</option></select></label>
          <div className="api-model-key-row"><label>API Key<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={draft.has_saved_key ? '已保存；留空则保持不变' : '输入 API Key'} /></label>{!creating && <button className="secondary-button" type="button" onClick={clearSavedKey} disabled={busy || !draft.has_saved_key} title="立即删除本机保存的模型密钥；不保存其他编辑"><Trash2 size={14} />清除保存的密钥</button>}</div>
          <label className="api-model-toggle"><input type="checkbox" checked={draft.supports_images === true} onChange={(event) => setDraft({ ...draft, supports_images: event.target.checked })} />支持图片输入</label>
          <div className="api-model-token-row"><label>最大输入 token（参考）<input type="number" min="1" max="10000000" value={draft.input_token_limit ?? ''} onChange={(event) => setDraft({ ...draft, input_token_limit: event.target.value })} placeholder="提供商公布的上下文上限" /></label><label>最大输出 token（请求限制）<input type="number" min="1" max="10000000" value={draft.max_output_tokens ?? ''} onChange={(event) => setDraft({ ...draft, max_output_tokens: event.target.value })} placeholder="自动（由提供商决定）" /></label></div>
          <small className="api-model-hint">输入上限用于上下文圆环和自动压缩估算；API 不会自动报告上限，服务商部署限制也可能低于模型规格。输出上限留空时由提供商决定；手动填写后会发送给提供商。ModelScope Qwen 仅在手动设置输出上限时按所选强度分配思考预算，自动模式使用提供商默认预算。</small>
        </form>
      </div>
      <footer><span className={error ? 'api-model-error' : ''}>{error || `${models.length} 个 API 模型 · 密钥仅保存在本机`}</span><div>
        <button className="secondary-button" type="button" onClick={add} disabled={busy}><Plus size={14} />添加自定义模型</button>
        {!creating && draft.custom && <button className="secondary-button" type="button" onClick={remove} disabled={busy}><Trash2 size={14} />{draft.builtin ? '恢复默认' : '删除'}</button>}
        <button className="primary-button" form="api-model-form" type="submit" disabled={busy || !draft.id || !draft.model_name || !draft.base_url}><Save size={14} />{busy ? '保存中' : '保存配置'}</button>
      </div></footer>
    </section>
  </div>;
}

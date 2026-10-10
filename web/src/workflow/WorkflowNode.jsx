import { useEffect, useRef, useState } from 'react';
import { Handle, NodeResizer, Position } from '@xyflow/react';
import { Braces, GripVertical, Save, Settings2 } from 'lucide-react';
import { categoryMeta, getNodeDefinition } from './catalog';

function PortList({ ports, direction, category, offset = 0 }) {
  const isInput = direction === 'input';
  return ports.map((port, index) => {
    const side = isInput ? Position.Left : Position.Right;
    const top = offset + 6 + index * 27;
    return (
      <div className={`node-port ${isInput ? 'input' : 'output'}`} key={port.id} style={{ top }}>
        {isInput && <Handle type="target" position={side} id={port.id} />}
        <span className={`port-type ${category}`}>{port.type.slice(0, 1).toUpperCase()}</span>
        <span>{port.label}</span>
        {port.optional && <small>optional</small>}
        {!isInput && <Handle type="source" position={side} id={port.id} />}
      </div>
    );
  });
}

export default function WorkflowNode({ id, data, selected }) {
  const definition = getNodeDefinition(data.kind);
  const meta = categoryMeta[definition.category] ?? categoryMeta.control;
  const Icon = meta.icon;
  const inputs = definition.inputs ?? [];
  const outputs = definition.outputs ?? [];
  const isModelLoader = ['llm.gguf_loader', 'llm.openai_loader', 'llm.provider'].includes(data.kind);
  const expectedModelType = data.kind === 'llm.gguf_loader' ? 'gguf' : data.kind === 'llm.openai_loader' ? 'api' : null;
  const allModels = data.modelOptions ?? [];
  const modelOptions = allModels.filter((option) => !expectedModelType || option.type === expectedModelType);
  const mmprojOptions = allModels.filter((option) => option.type === 'mmproj');
  const currentModel = data.config?.model ?? '';
  const currentMmproj = data.config?.mmproj ?? '';
  const hasPreview = !definition.hideOutputPreview && !isModelLoader && !['llm.chat', 'agent.react_runtime', 'react.loop'].includes(data.kind) && (outputs.length > 0 || data.kind === 'core.chat_output');
  const rowCount = Math.max(inputs.length, outputs.length, 1);
  const editableInput = data.kind === 'core.chat_input' || data.kind === 'prompt.text';
  const inputKey = data.kind === 'prompt.text' ? 'text' : 'debug_input';
  const [draftInput, setDraftInput] = useState(data.config?.[inputKey] ?? '');
  const [apiKeyDraft, setApiKeyDraft] = useState('');
  const contentRef = useRef(null);
  useEffect(() => setDraftInput(data.config?.[inputKey] ?? ''), [data.config, inputKey]);
  useEffect(() => {
    const element = contentRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const reportSize = () => data.onContentSize?.(id, Math.ceil(element.getBoundingClientRect().height) + 2);
    const observer = new ResizeObserver(reportSize);
    observer.observe(element);
    reportSize();
    return () => observer.disconnect();
  }, [data.kind, data.outputPreview, data.previewExpanded, data.onContentSize, id]);
  const updateDraftInput = (value) => {
    setDraftInput(value);
    data.onDataChange?.(id, { config: { ...(data.config ?? {}), [inputKey]: value } });
  };
  const preview = data.outputPreview ?? (data.kind === 'tools.dispatch' ? '试运行后显示工具 / 技能执行结果。' : data.kind === 'core.chat_input' ? data.config?.debug_input ?? '' : data.kind === 'core.chat_output' ? '运行后显示完整回复。' : data.kind === 'prompt.text' ? data.config?.text ?? '' : '暂无内容');
  const debugHeight = editableInput ? 106 : 0;
  const modelSelectHeight = isModelLoader ? (data.kind === 'llm.gguf_loader' ? 114 : data.kind === 'llm.openai_loader' ? 200 : 62) : data.kind === 'prompt.markdown_file' ? 62 : 0;
  const apiFieldsHeight = data.kind === 'llm.openai_loader' ? 104 : 0;
  const configButtonHeight = ['skills.provider', 'tools.provider', 'memory.provider'].includes(data.kind) ? 46 : 0;
  const previewHeight = hasPreview ? 40 : 0;
  const footerHeight = data.module_id ? 30 : 0;
  const minNodeHeight = 54 + Math.max(52, rowCount * 27 + 10) + debugHeight + modelSelectHeight + apiFieldsHeight + configButtonHeight + previewHeight + footerHeight;

  return (
    <article
      className={`workflow-node ${meta.color} ${selected ? 'selected' : ''} ${data.executionStatus || ''}`}
      style={{ '--node-color': data.color || meta.hex }}
    >
      <div className="workflow-node-content" ref={contentRef}>
      <NodeResizer
        isVisible={selected}
        minWidth={216}
        maxWidth={680}
        minHeight={minNodeHeight}
        lineStyle={{ borderColor: data.color || meta.hex }}
        handleStyle={{ width: 9, height: 9, borderRadius: 3, background: data.color || meta.hex, border: '1px solid #fff' }}
        onResizeEnd={() => data.onResizeEnd?.(id)}
      />
      <header className="workflow-node-header">
        <span className="node-icon"><Icon size={16} strokeWidth={1.8} /></span>
        <div className="node-title-group">
          <strong>{data.label || definition.label}</strong>
          <span>{definition.type}</span>
        </div>
        <GripVertical className="drag-grip" size={16} />
      </header>
      <div className={`workflow-node-body ${inputs.length && outputs.length ? 'split-ports' : ''}`} style={{ minHeight: `${minNodeHeight - 54 - previewHeight - footerHeight}px` }}>
        {editableInput && <label className="node-debug-input"><span>{data.kind === 'prompt.text' ? '提示词内容' : '调试输入'}</span><textarea value={draftInput} onChange={(event) => updateDraftInput(event.target.value)} onPointerDown={(event) => event.stopPropagation()} /></label>}
        {data.kind === 'prompt.markdown_file' && <label className="node-model-select" onPointerDown={(event) => event.stopPropagation()}><span>Markdown 文件</span><select value={data.config?.file || ''} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config || {}), file: event.target.value } })}>{(data.promptFiles || []).map((file) => <option key={file} value={file}>{file}</option>)}</select></label>}
        {isModelLoader && <label className="node-model-select" onPointerDown={(event) => event.stopPropagation()}><span>主模型</span><select value={currentModel} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), model: event.target.value } })}><option value="" disabled>请选择{expectedModelType === 'api' ? ' API' : ' GGUF'}模型</option>{currentModel && !modelOptions.some((option) => option.value === currentModel) && <option value={currentModel}>当前模型不可用：{currentModel}</option>}{modelOptions.map((option) => <option key={option.value} value={option.value} disabled={option.ready === false}>{option.label}{option.ready === false ? ' · 未就绪' : ''}</option>)}</select></label>}
        {data.kind === 'llm.openai_loader' && <div className="node-api-fields" onPointerDown={(event) => event.stopPropagation()}><label><span>提供商端点</span><input value={data.config?.base_url || ''} placeholder={modelOptions.find((option) => option.value === currentModel)?.base_url || 'https://.../v1'} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config || {}), base_url: event.target.value } })} /></label><label><span>API Key {data.credentialConfigured?.includes(id) ? '· 已配置' : '· 未配置'}</span><input type="password" autoComplete="off" value={apiKeyDraft} onChange={(event) => setApiKeyDraft(event.target.value)} placeholder="仅保存在本机" /></label><button onClick={() => { data.onSaveCredential?.(id, apiKeyDraft); setApiKeyDraft(''); }} disabled={!apiKeyDraft}><Save size={13} />保存密钥</button></div>}
        {data.kind === 'llm.gguf_loader' && <label className="node-model-select secondary-model-select" onPointerDown={(event) => event.stopPropagation()}><span>视觉投影（mmproj，可选）</span><select value={currentMmproj} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), mmproj: event.target.value } })}><option value="">不使用（纯文本）</option>{currentMmproj && !mmprojOptions.some((option) => option.value === currentMmproj) && <option value={currentMmproj}>当前 mmproj 不可用：{currentMmproj}</option>}{mmprojOptions.map((option) => <option key={option.value} value={option.value} disabled={option.ready === false}>{option.label}{option.ready === false ? ' · 未就绪' : ''}</option>)}</select></label>}
        {['skills.provider', 'tools.provider', 'memory.provider'].includes(data.kind) && <button className="node-config-button" onClick={() => data.onOpenConfig?.(data.kind.split('.')[0])} onPointerDown={(event) => event.stopPropagation()}><Settings2 size={14} />详细配置</button>}
        {inputs.length > 0 && <PortList ports={inputs} direction="input" category={meta.color} offset={debugHeight + modelSelectHeight + apiFieldsHeight + configButtonHeight} />}
        {outputs.length > 0 && <PortList ports={outputs} direction="output" category={meta.color} offset={debugHeight + modelSelectHeight + apiFieldsHeight + configButtonHeight} />}
        {inputs.length === 0 && outputs.length === 0 && <span className="node-static-output"><Braces size={13} /> internal</span>}
      </div>
      {hasPreview && <details
        className="node-output-preview"
        open={Boolean(data.previewExpanded)}
        onToggle={(event) => data.onPreviewToggle?.(id, event.currentTarget.open)}
        onPointerDown={(event) => event.stopPropagation()}
      ><summary>{data.kind === 'tools.dispatch' ? '工具执行结果' : '输出预览'} <span>{data.previewUsage?.total_tokens ? `${data.previewUsage.total_tokens} tokens` : `${[...preview].length} 字符 · ${preview.match(/[A-Za-z]+(?:['-][A-Za-z]+)*/g)?.length || 0} 英文词`}</span></summary><pre>{preview}</pre></details>}
      {data.module_id && <footer className="workflow-node-footer"><span className="connected-dot" />{data.module_id} · 运行时绑定</footer>}
      </div>
      <span className="node-number">{id.slice(0, 2).toUpperCase()}</span>
    </article>
  );
}

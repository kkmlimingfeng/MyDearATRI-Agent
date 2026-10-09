import { useEffect, useRef, useState } from 'react';
import { Handle, NodeResizer, Position } from '@xyflow/react';
import { Braces, GripVertical } from 'lucide-react';
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
  const rowCount = Math.max(inputs.length, outputs.length, 1);
  const editableInput = data.kind === 'core.chat_input' || data.kind === 'prompt.text';
  const inputKey = data.kind === 'prompt.text' ? 'text' : 'debug_input';
  const [draftInput, setDraftInput] = useState(data.config?.[inputKey] ?? '');
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
  const preview = data.outputPreview || definition.preview || '运行后显示节点输出。';
  const debugHeight = editableInput ? 106 : 0;
  const modelSelectHeight = isModelLoader ? (data.kind === 'llm.gguf_loader' ? 114 : 62) : 0;
  const previewHeight = outputs.length > 0 ? 40 : 0;
  const footerHeight = data.module_id ? 30 : 0;
  const minNodeHeight = 54 + Math.max(52, rowCount * 27 + 10) + debugHeight + modelSelectHeight + previewHeight + footerHeight;

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
        {isModelLoader && <label className="node-model-select" onPointerDown={(event) => event.stopPropagation()}><span>主模型</span><select value={currentModel} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), model: event.target.value } })}><option value="" disabled>请选择 GGUF 模型</option>{currentModel && !modelOptions.some((option) => option.value === currentModel) && <option value={currentModel}>当前模型不可用：{currentModel}</option>}{modelOptions.map((option) => <option key={option.value} value={option.value} disabled={option.ready === false}>{option.label}{option.ready === false ? ' · 未就绪' : ''}</option>)}</select></label>}
        {data.kind === 'llm.gguf_loader' && <label className="node-model-select secondary-model-select" onPointerDown={(event) => event.stopPropagation()}><span>视觉投影（mmproj，可选）</span><select value={currentMmproj} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), mmproj: event.target.value } })}><option value="">不使用（纯文本）</option>{currentMmproj && !mmprojOptions.some((option) => option.value === currentMmproj) && <option value={currentMmproj}>当前 mmproj 不可用：{currentMmproj}</option>}{mmprojOptions.map((option) => <option key={option.value} value={option.value} disabled={option.ready === false}>{option.label}{option.ready === false ? ' · 未就绪' : ''}</option>)}</select></label>}
        {inputs.length > 0 && <PortList ports={inputs} direction="input" category={meta.color} offset={debugHeight + modelSelectHeight} />}
        {outputs.length > 0 && <PortList ports={outputs} direction="output" category={meta.color} offset={debugHeight + modelSelectHeight} />}
        {inputs.length === 0 && outputs.length === 0 && <span className="node-static-output"><Braces size={13} /> internal</span>}
      </div>
      {outputs.length > 0 && <details
        className="node-output-preview"
        open={Boolean(data.previewExpanded)}
        onToggle={(event) => data.onPreviewToggle?.(id, event.currentTarget.open)}
        onPointerDown={(event) => event.stopPropagation()}
      ><summary>输出预览</summary><pre>{preview}</pre></details>}
      {data.module_id && <footer className="workflow-node-footer"><span className="connected-dot" />{data.module_id} · 运行时绑定</footer>}
      </div>
      <span className="node-number">{id.slice(0, 2).toUpperCase()}</span>
    </article>
  );
}

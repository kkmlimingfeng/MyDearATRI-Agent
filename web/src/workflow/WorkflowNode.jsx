import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Handle, NodeResizer, Position, useUpdateNodeInternals } from '@xyflow/react';
import { Braces, GripVertical, Settings2 } from 'lucide-react';
import { categoryMeta, getNodeDefinition } from './catalog';
import { getPortTypeColor } from './portTypes';
import { portLabel } from './interfaceLanguage';
import IterationStepper from './IterationStepper';

function PortList({ ports, direction, connectionState, nodeType, language }) {
  const isInput = direction === 'input';
  return ports.map((port) => {
    const side = isInput ? Position.Left : Position.Right;
    const isOrigin = connectionState?.origin && connectionState.originHandle === port.id && connectionState.originDirection === (isInput ? 'target' : 'source');
    const isAvailable = connectionState?.[isInput ? 'eligibleInputs' : 'eligibleOutputs'].includes(port.id);
    const connectionClass = connectionState ? isOrigin ? 'connection-active-port' : isAvailable ? 'connection-available-port' : 'connection-unavailable-port' : '';
    const label = portLabel(nodeType, port, language);
    return (
      <div className={`node-port ${isInput ? 'input' : 'output'} ${connectionClass}`} key={port.id} style={{ '--port-color': getPortTypeColor(port.type) }}>
        {isInput && <Handle type="target" position={side} id={port.id} title={`${label} · ${port.type}`} />}
        <span className="port-type">{port.type.slice(0, 1).toUpperCase()}</span>
        <span className="port-label">{label}</span>
        {port.optional && <small>{language === 'en' ? 'optional' : '可选'}</small>}
        {!isInput && <Handle type="source" position={side} id={port.id} title={`${label} · ${port.type}`} />}
      </div>
    );
  });
}

export default function WorkflowNode({ id, data, selected }) {
  const definition = getNodeDefinition(data.kind);
  const meta = categoryMeta[definition.category] ?? categoryMeta.control;
  const Icon = meta.icon;
  const inputs = (definition.inputs ?? []).filter((port) => !port.hidden || data.connectedPorts?.inputs?.includes(port.id));
  const outputs = (definition.outputs ?? []).filter((port) => !port.hidden || data.connectedPorts?.outputs?.includes(port.id));
  const language = data.interfaceLanguage || 'zh';
  const portSignature = JSON.stringify([inputs, outputs]);
  const isModelLoader = ['llm.gguf_loader', 'llm.openai_loader', 'llm.provider'].includes(data.kind);
  const expectedModelType = data.kind === 'llm.gguf_loader' ? 'gguf' : data.kind === 'llm.openai_loader' ? 'api' : null;
  const allModels = data.modelOptions ?? [];
  const modelOptions = allModels.filter((option) => !expectedModelType || option.type === expectedModelType);
  const mmprojOptions = allModels.filter((option) => option.type === 'mmproj');
  const currentModel = data.config?.model ?? '';
  const currentMmproj = data.config?.mmproj ?? '';
  const reasoningEffort = data.config?.reasoning_effort ?? 'auto';
  const hasPreview = !definition.hideOutputPreview && !isModelLoader && !['llm.chat', 'control.loop', 'react.loop'].includes(data.kind) && (outputs.length > 0 || data.kind === 'core.chat_output');
  const editableInput = data.kind === 'core.chat_input' || data.kind === 'prompt.text';
  const inputKey = data.kind === 'prompt.text' ? 'text' : 'debug_input';
  const [draftInput, setDraftInput] = useState(data.config?.[inputKey] ?? '');
  const contentRef = useRef(null);
  const updateNodeInternals = useUpdateNodeInternals();
  const [contentHeight, setContentHeight] = useState(72);
  useEffect(() => setDraftInput(data.config?.[inputKey] ?? ''), [data.config, inputKey]);
  useLayoutEffect(() => {
    const element = contentRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const reportSize = () => {
      const height = element.offsetHeight + 2;
      setContentHeight((previous) => previous === height ? previous : height);
      data.onContentSize?.(id, height);
      updateNodeInternals(id);
    };
    const observer = new ResizeObserver(reportSize);
    observer.observe(element);
    reportSize();
    return () => observer.disconnect();
  }, [id, portSignature, data.onContentSize, updateNodeInternals]);
  const updateDraftInput = (value) => {
    setDraftInput(value);
    data.onDataChange?.(id, { config: { ...(data.config ?? {}), [inputKey]: value } });
  };
  const preview = data.outputPreview ?? (['capability.dispatch', 'tools.dispatch'].includes(data.kind) ? '试运行后显示能力执行结果。' : data.kind === 'core.chat_input' ? data.config?.debug_input ?? '' : data.kind === 'core.chat_output' ? '运行后显示完整回复。' : data.kind === 'prompt.text' ? data.config?.text ?? '' : '暂无内容');
  const isManual = data.sizeMode === 'manual';
  const connectionState = data.connectionState;
  const connectionClass = !connectionState ? '' : connectionState.origin || connectionState.eligibleInputs.length || connectionState.eligibleOutputs.length ? 'connection-compatible' : 'connection-incompatible';
  const ttsModels = data.ttsModels ?? [];
  const selectedTtsModel = data.config?.model ?? '';

  return (
    <article
      className={`workflow-node ${meta.color} ${isManual ? 'manual-size' : 'auto-size'} ${selected ? 'selected' : ''} ${data.executionStatus || ''} ${connectionClass}`}
      style={{ '--node-color': data.color || meta.hex, '--connection-color': getPortTypeColor(connectionState?.type) }}
    >
      <div className="workflow-node-content" ref={contentRef}>
      <NodeResizer
        isVisible={selected}
        minWidth={216}
        minHeight={Math.max(72, contentHeight)}
        lineStyle={{ borderColor: data.color || meta.hex }}
        handleStyle={{ width: 9, height: 9, borderRadius: 3, background: data.color || meta.hex, border: '1px solid #fff' }}
        onResizeStart={() => data.onResizeStart?.(id)}
        onResizeEnd={(_, dimensions) => data.onResizeEnd?.(id, dimensions)}
      />
        <header className="workflow-node-header">
        <span className="node-icon"><Icon size={16} strokeWidth={1.8} /></span>
        <div className="node-title-group">
          <strong>{data.label || definition.label}</strong>
          <span>{definition.type}</span>
        </div>
        {data.executionStatus === 'complete' && Number.isFinite(data.executionDurationMs) && <span className="node-duration">{data.executionDurationMs < 1000 ? `${data.executionDurationMs} ms` : `${(data.executionDurationMs / 1000).toFixed(2)} s`}</span>}
        <GripVertical className="drag-grip" size={16} />
      </header>
      <div className="workflow-node-body">
        {editableInput && <label className="node-debug-input"><span>{data.kind === 'prompt.text' ? '提示词内容' : '调试输入'}</span><textarea value={draftInput} onChange={(event) => updateDraftInput(event.target.value)} onPointerDown={(event) => event.stopPropagation()} /></label>}
        {data.kind === 'prompt.markdown_file' && <label className="node-model-select" onPointerDown={(event) => event.stopPropagation()}><span>Markdown 文件</span><select value={data.config?.file || ''} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config || {}), file: event.target.value } })}>{(data.promptFiles || []).map((file) => <option key={file} value={file}>{file}</option>)}</select></label>}
        {isModelLoader && <label className="node-model-select" onPointerDown={(event) => event.stopPropagation()}><span>主模型</span><select value={currentModel} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), model: event.target.value } })}><option value="" disabled>请选择{expectedModelType === 'api' ? ' API' : ' GGUF'}模型</option>{currentModel && !modelOptions.some((option) => option.value === currentModel) && <option value={currentModel}>当前模型不可用：{currentModel}</option>}{modelOptions.map((option) => <option key={option.value} value={option.value} disabled={option.ready === false}>{option.label}{option.ready === false ? ' · 未就绪' : ''}</option>)}</select></label>}
        {data.kind === 'audio.tts_model' && <label className="node-model-select" onPointerDown={(event) => event.stopPropagation()}><span>TTS 模型</span><select value={selectedTtsModel} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), model: event.target.value } })}>{selectedTtsModel && !ttsModels.some((option) => option.id === selectedTtsModel) && <option value={selectedTtsModel}>当前模型不可用：{selectedTtsModel}</option>}{ttsModels.map((option) => <option key={option.id} value={option.id} disabled={!option.available}>{option.label}{option.available ? '' : ' · 未就绪'}</option>)}</select></label>}
        {data.kind === 'audio.tts_model' && <label className="node-model-select" onPointerDown={(event) => event.stopPropagation()}><span>目标语言</span><select value={data.config?.language || 'Chinese'} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), language: event.target.value } })}><option value="Chinese">中文</option><option value="Japanese">日语</option><option value="English">英语</option></select></label>}
        {data.kind === 'audio.tts_model' && <label className="node-model-select" onPointerDown={(event) => event.stopPropagation()}><span>参考音色</span><select value={data.config?.reference || 'atri'} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), reference: event.target.value } })}>{data.config?.reference && !data.ttsReferences?.some((reference) => reference.id === data.config.reference) && <option value={data.config.reference}>当前参考不可用：{data.config.reference}</option>}{(data.ttsReferences || []).map((reference) => <option key={reference.id} value={reference.id}>{reference.label}{reference.duration_seconds ? ` · ${reference.duration_seconds}s` : ''}</option>)}</select></label>}
        {data.kind === 'llm.openai_loader' && <button className="node-config-button" onClick={() => data.onOpenConfig?.('api-models', currentModel)} onPointerDown={(event) => event.stopPropagation()}><Settings2 size={14} />配置模型</button>}
        {data.kind === 'llm.gguf_loader' && <label className="node-model-select secondary-model-select" onPointerDown={(event) => event.stopPropagation()}><span>视觉投影（mmproj，可选）</span><select value={currentMmproj} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), mmproj: event.target.value } })}><option value="">不使用（纯文本）</option>{currentMmproj && !mmprojOptions.some((option) => option.value === currentMmproj) && <option value={currentMmproj}>当前 mmproj 不可用：{currentMmproj}</option>}{mmprojOptions.map((option) => <option key={option.value} value={option.value} disabled={option.ready === false}>{option.label}{option.ready === false ? ' · 未就绪' : ''}</option>)}</select></label>}
        {data.kind === 'llm.chat' && <label className="node-model-select node-reasoning-select" onPointerDown={(event) => event.stopPropagation()}><span>思考强度（API）</span><select value={data.reasoningAvailable ? reasoningEffort : 'auto'} disabled={!data.reasoningAvailable} onChange={(event) => data.onDataChange?.(id, { config: { ...(data.config ?? {}), reasoning_effort: event.target.value } })}><option value="auto">{data.reasoningAvailable ? '自动' : 'GGUF 模型暂不支持'}</option>{data.reasoningAvailable && <><option value="minimal">极低</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">极高</option></>}</select><small>{data.reasoningAvailable ? '可在对话页临时覆盖' : '连接 API 运行时模型后可设置'}</small></label>}
        {['skills.provider', 'tools.provider', 'memory.provider'].includes(data.kind) && <button className="node-config-button" onClick={() => data.onOpenConfig?.(data.kind.split('.')[0])} onPointerDown={(event) => event.stopPropagation()}><Settings2 size={14} />详细配置</button>}
        {['control.loop', 'react.loop'].includes(data.kind) && <div className="node-loop-limit"><span>{language === 'en' ? 'Maximum iterations' : '最大循环次数'}</span><IterationStepper value={data.config?.max_iterations ?? 5} onChange={(value) => data.onDataChange?.(id, { config: { ...(data.config || {}), max_iterations: value } })} /></div>}
        {(inputs.length > 0 || outputs.length > 0) && <div className={`node-port-grid ${inputs.length && outputs.length ? 'split-ports' : outputs.length ? 'output-only' : ''}`}>
          {inputs.length > 0 && <div className="node-port-column"><PortList ports={inputs} direction="input" connectionState={data.connectionState} nodeType={data.kind} language={language} /></div>}
          {outputs.length > 0 && <div className="node-port-column"><PortList ports={outputs} direction="output" connectionState={data.connectionState} nodeType={data.kind} language={language} /></div>}
        </div>}
        {inputs.length === 0 && outputs.length === 0 && <span className="node-static-output"><Braces size={13} /> internal</span>}
      </div>
      {hasPreview && <div className="node-output-preview nodrag nowheel" onPointerDown={(event) => event.stopPropagation()}>
        <button type="button" className="node-preview-toggle" aria-expanded={Boolean(data.previewExpanded)} onClick={() => data.onPreviewToggle?.(id, !data.previewExpanded)}>{['capability.dispatch', 'tools.dispatch'].includes(data.kind) ? '能力执行结果' : '输出预览'} <span>{data.previewUsage?.total_tokens ? `${data.previewUsage.total_tokens} tokens` : `${[...preview].length} 字符 · ${preview.match(/[A-Za-z]+(?:['-][A-Za-z]+)*/g)?.length || 0} 英文词`}</span></button>
        <div className={`motion-collapse ${data.previewExpanded ? 'is-open' : ''}`} inert={!data.previewExpanded ? '' : undefined}><div><pre>{preview}</pre></div></div>
      </div>}
      {data.module_id && <footer className="workflow-node-footer"><span className="connected-dot" />{data.module_id} · 运行时绑定</footer>}
      </div>
      <span className="node-number">{id.slice(0, 2).toUpperCase()}</span>
    </article>
  );
}

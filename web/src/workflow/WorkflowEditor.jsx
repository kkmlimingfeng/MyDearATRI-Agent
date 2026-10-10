import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react';
import { ArrowDownToLine, ArrowUpFromLine, Check, ChevronDown, Code2, Copy, Expand, FilePlus2, Maximize2, Play, Save, Search, Square, Trash2, Workflow as WorkflowIcon, X } from 'lucide-react';
import WorkflowNode from './WorkflowNode';
import { categoryMeta, getNodeDefinition, hydrateNodeCatalog, modelChoices, nodeCatalog } from './catalog';
import { ThemePicker } from '../theme.jsx';
import CapabilityPanel from './CapabilityPanel';
import TraceView from './TraceView';
import { runWorkflowRequest } from './runApi';

const nodeTypes = { workflow: WorkflowNode };
const MIN_NODE_WIDTH = 216;
const MAX_NODE_WIDTH = 680;

function estimateTextWidth(value, fontSize = 14) {
  return [...String(value ?? '')].reduce((width, character) => (
    width + (/\p{Script=Han}/u.test(character) ? fontSize : fontSize * 0.62)
  ), 0);
}

function estimateNodeSize(node) {
  const kind = node.data?.kind || node.type;
  const definition = getNodeDefinition(kind);
  const data = node.data || {};
  const config = data.config || {};
  const titleLength = String(data.label || definition.label || '').length;
  const typeLength = String(kind || '').length;
  const measurePortColumn = (ports) => Math.max(0, ...ports.map((port) => (
    19 + 16 + estimateTextWidth(port.label, 14) + (port.optional ? 58 : 0) + 26
  )));
  const inputWidth = measurePortColumn(definition.inputs || []);
  const outputWidth = measurePortColumn(definition.outputs || []);
  const contentTextWidth = Math.max(0, ...[
    data.label || definition.label,
    ...Object.values(config),
    data.previewExpanded ? data.outputPreview : '',
  ].flatMap((value) => String(value ?? '').split(/\r?\n/)).map((line) => estimateTextWidth(line, 13)));
  const splitPortWidth = definition.inputs?.length && definition.outputs?.length
    ? inputWidth + outputWidth + 16
    : Math.max(inputWidth, outputWidth) + 16;
  const width = Math.max(MIN_NODE_WIDTH, Math.min(MAX_NODE_WIDTH, Math.max(
    230,
    80 + titleLength * 8,
    80 + typeLength * 7,
    splitPortWidth,
    58 + contentTextWidth,
  )));
  const rowCount = Math.max(definition.inputs?.length || 0, definition.outputs?.length || 0, 1);
  const editableInput = kind === 'core.chat_input' || kind === 'prompt.text';
  const modelSelect = ['llm.gguf_loader', 'llm.openai_loader', 'llm.provider'].includes(kind);
  const preview = !definition.hideOutputPreview && !modelSelect && !['llm.chat', 'agent.react_runtime', 'react.loop'].includes(kind) && (definition.outputs?.length || kind === 'core.chat_output') ? 40 : 0;
  const footer = data.module_id ? 30 : 0;
  const debugInput = editableInput ? 106 : 0;
  const modelSelectHeight = modelSelect ? (kind === 'llm.gguf_loader' ? 114 : kind === 'llm.openai_loader' ? 200 : 62) : kind === 'prompt.markdown_file' ? 62 : 0;
  const configButtonHeight = ['skills.provider', 'tools.provider', 'memory.provider'].includes(kind) ? 46 : 0;
  const apiFields = kind === 'llm.openai_loader' ? 104 : 0;
  const height = 54 + Math.max(52, rowCount * 27 + 10) + debugInput + modelSelectHeight + apiFields + configButtonHeight + preview + footer;
  return { width: Math.round(width), height: Math.round(height) };
}

function fromDocument(document) {
  return {
    nodes: document.nodes.map((node) => {
      const definition = getNodeDefinition(node.type);
      const { api_key, ...fileConfig } = node.data?.config || {};
      const nextNode = {
        ...node,
        type: 'workflow',
        data: {
          ...node.data,
          kind: node.type,
        config: {
          ...Object.fromEntries(Object.entries(definition.configSchema?.properties || {}).filter(([, field]) => Object.hasOwn(field, 'default')).map(([key, field]) => [key, field.default])),
          ...(definition.defaults || {}),
          ...fileConfig,
        },
        },
      };
      const estimated = estimateNodeSize(nextNode);
      return {
        ...nextNode,
        width: node.data?.sizeMode === 'manual' && typeof node.width === 'number'
          ? Math.min(node.width, MAX_NODE_WIDTH)
          : estimated.width,
        height: node.data?.sizeMode === 'manual' && typeof node.height === 'number'
          ? node.height
          : estimated.height,
      };
    }),
    edges: document.edges.map((edge) => {
      const color = edgeColors[edge.sourceHandle] || '#667d72';
      return { ...edge, label: undefined, type: 'smoothstep', animated: false, style: { stroke: color, strokeWidth: 2 }, markerEnd: { type: 'arrowclosed', color, width: 15, height: 15 } };
    }),
  };
}

const edgeColors = { message: '#4386a5', llm: '#7467a8', prompt: '#a66f4e', memory: '#368a74', skills: '#718e43', tools: '#bd7650', tool_calls: '#bd7650', tool_results: '#bd7650', answer: '#3f8b69', response: '#a078b5', model_response: '#a078b5', trace: '#667d72', loop: '#667d72' };

function toDocument(workflow, nodes, edges) {
  return {
    workflow_version: 2,
    id: workflow.id,
    name: workflow.name,
    description: workflow.description ?? '',
    nodes: nodes.map(({ type, ...node }) => {
      const { kind, executionStatus, onDataChange, onPreviewToggle, onContentSize, onResizeEnd, onOpenConfig, onSaveCredential, credentialConfigured, modelOptions, promptFiles, outputPreview, previewUsage, ...data } = node.data;
      const { api_key, ...config } = data.config || {};
      delete config.debug_input;
      return { ...node, type: kind, data: { ...data, config } };
    }),
    edges: edges.map(({ type, animated, selected, ...edge }) => edge),
    viewport: workflow.viewport ?? { x: 0, y: 0, zoom: 0.8 },
    metadata: workflow.metadata ?? { status: 'design', executable: false },
  };
}

function findPort(node, handle, direction) {
  const definition = getNodeDefinition(node?.data?.kind);
  const list = direction === 'source' ? definition.outputs : definition.inputs;
  return list.find((port) => port.id === handle);
}

function validateExecutionLayout(nodes, edges, nodeMap) {
  const types = new Set(nodes.map((node) => node.data.kind));
  const hasRouter = types.has('react.response_router');
  const hasDispatch = types.has('tools.dispatch');
  if (!hasRouter && !hasDispatch) return [];
  const issues = [];
  const edgeExists = (sourceType, sourceHandle, targetType, targetHandle) => edges.some((edge) => (
    nodeMap[edge.source]?.data.kind === sourceType
    && edge.sourceHandle === sourceHandle
    && nodeMap[edge.target]?.data.kind === targetType
    && edge.targetHandle === targetHandle
  ));
  if (hasRouter && !edgeExists('llm.chat', 'response', 'react.response_router', 'response')) issues.push('响应解析节点必须接收模型结构化响应');
  if (hasRouter && !edgeExists('react.response_router', 'answer', 'core.chat_output', 'answer')) issues.push('响应解析节点的回答出口必须连接回复输出');
  if (hasRouter && hasDispatch && !edgeExists('react.response_router', 'tool_calls', 'tools.dispatch', 'tool_calls')) issues.push('响应解析节点的工具出口必须连接工具 / 技能执行');
  if (hasDispatch && !edgeExists('tools.dispatch', 'tool_results', 'react.loop', 'tool_results')) issues.push('工具执行结果必须反馈到 ReAct 循环');
  if (hasDispatch && !edgeExists('react.loop', 'loop', 'llm.chat', 'loop')) issues.push('ReAct 循环必须回接模型对话节点');
  return issues;
}

function validateGraph(nodes, edges, modelOptions = []) {
  const issues = [];
  const incoming = new Set(edges.map((edge) => `${edge.target}:${edge.targetHandle}`));
  const nodeMap = Object.fromEntries(nodes.map((node) => [node.id, node]));
  for (const edge of edges) {
    const source = nodeMap[edge.source];
    const target = nodeMap[edge.target];
    const sourcePort = findPort(source, edge.sourceHandle, 'source');
    const targetPort = findPort(target, edge.targetHandle, 'target');
    if (!sourcePort || !targetPort) issues.push(`连接 ${edge.id} 引用了不存在的接口`);
    else if (sourcePort.type !== targetPort.type) issues.push(`连接 ${edge.id} 的接口类型不匹配`);
  }
  for (const node of nodes) {
    const definition = nodeCatalog.find((item) => item.type === node.data.kind);
    if (!definition) {
      issues.push(`${node.data.label}: 未知节点类型 ${node.data.kind}`);
      continue;
    }
    if (node.data.kind === 'retrieval.vector_store') issues.push(`${node.data.label}: 当前试运行器尚不支持此节点`);
    if (['llm.gguf_loader', 'llm.openai_loader', 'llm.provider'].includes(node.data.kind)) {
      const selectedModel = node.data.config?.model;
      const model = modelOptions.find((option) => option.value === selectedModel);
      if (!selectedModel || !model) issues.push(`${node.data.label}: 请选择模型下拉列表中的有效模型`);
      else if (model.ready === false) issues.push(`${node.data.label}: ${model.reason || '所选模型尚未就绪'}`);
      if (node.data.kind === 'llm.gguf_loader' && node.data.config?.mmproj) {
        const mmproj = modelOptions.find((option) => option.value === node.data.config.mmproj);
        if (!mmproj || mmproj.type !== 'mmproj') issues.push(`${node.data.label}: mmproj 选择无效，请重新选择或留空`);
        else if (mmproj.ready === false) issues.push(`${node.data.label}: ${mmproj.reason || '所选 mmproj 尚未就绪'}`);
      }
    }
    for (const port of definition.inputs) {
      if (!port.optional && !incoming.has(`${node.id}:${port.id}`)) {
        issues.push(`${node.data.label}: 缺少 ${port.label} 输入`);
      }
    }
  }
  if (!nodes.some((node) => ['agent.react_runtime', 'llm.chat'].includes(node.data.kind))) issues.push('工作流需要一个模型对话节点');
  if (!nodes.some((node) => node.data.kind === 'core.chat_input')) issues.push('工作流需要一个对话输入节点');
  if (!nodes.some((node) => node.data.kind === 'core.chat_output')) issues.push('工作流需要一个回复输出节点');
  issues.push(...validateExecutionLayout(nodes, edges, nodeMap));
  return issues;
}

function downloadDocument(document) {
  const blob = new Blob([JSON.stringify(document, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = window.document.createElement('a');
  anchor.href = url;
  anchor.download = `${document.id || 'workflow'}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function PaletteItem({ definition, onAdd }) {
  const meta = categoryMeta[definition.category] || categoryMeta.control;
  const Icon = meta.icon;
  return (
    <button className="palette-item" onClick={() => onAdd(definition)} title={`添加 ${definition.label}`}>
      <span className={`palette-icon ${meta.color}`}><Icon size={15} /></span>
      <span className="palette-label">{definition.label}</span>
      <span className="palette-add">+</span>
    </button>
  );
}

function Inspector({ node, modelOptions = modelChoices, promptFiles = [], credentialConfigured = [], onSaveCredential, onChange, onDelete, onClose }) {
  if (!node) return (
    <aside className="inspector empty-inspector">
      <div className="panel-heading"><div><span className="eyebrow">属性</span><h2>节点设置</h2></div><button className="icon-button" title="关闭属性面板" onClick={onClose}><X size={16} /></button></div>
      <div className="empty-selection"><WorkflowIcon size={24} /><strong>选择一个节点</strong><span>查看接口、绑定模块和配置项</span></div>
    </aside>
  );

  const definition = getNodeDefinition(node.data.kind);
  const meta = categoryMeta[definition.category] || categoryMeta.control;
  const Icon = meta.icon;
  const config = node.data.config ?? {};
  const setData = (patch) => onChange(node.id, { ...node.data, ...patch });
  const setConfig = (key, value) => setData({ config: { ...config, [key]: value } });
  const saveCredential = () => {
    const input = document.getElementById(`api-key-${node.id}`);
    onSaveCredential?.(node.id, input?.value || '');
    if (input) input.value = '';
  };

  return (
    <aside className="inspector">
      <div className="panel-heading"><div><span className="eyebrow">节点属性</span><h2>配置</h2></div><button className="icon-button" title="关闭属性面板" onClick={onClose}><X size={16} /></button></div>
      <div className="inspector-scroll">
        <div className="selected-node-summary">
          <span className={`palette-icon large ${meta.color}`}><Icon size={18} /></span>
          <div><strong>{node.data.label}</strong><span>{definition.type}</span></div>
        </div>
        <label className="field-label" htmlFor="node-label">显示名称</label>
        <input id="node-label" value={node.data.label ?? ''} onChange={(event) => setData({ label: event.target.value })} />
        <label className="field-label color-field" htmlFor="node-color">节点颜色</label>
        <input id="node-color" type="color" value={node.data.color || meta.hex} onChange={(event) => setData({ color: event.target.value })} />
        {definition.moduleId !== undefined && (
          <>
            <label className="field-label" htmlFor="module-id">模块 ID</label>
            <input id="module-id" value={node.data.module_id ?? ''} placeholder="可留空" onChange={(event) => setData({ module_id: event.target.value })} />
          </>
        )}
        {Object.entries(config).filter(([key]) => !(node.data.kind === 'prompt.markdown_file' && key === 'source')).map(([key, value]) => (
          <label className="field-label config-field" key={key}>
            <span>{definition.configSchema?.properties?.[key]?.title || key.replaceAll('_', ' ')}</span>
            {typeof value === 'boolean' ? (
              <input type="checkbox" checked={value} onChange={(event) => setConfig(key, event.target.checked)} />
            ) : typeof value === 'number' ? (
              <input type="number" value={value} onChange={(event) => setConfig(key, Number(event.target.value))} />
            ) : (key === 'model' && ['llm.gguf_loader', 'llm.openai_loader', 'llm.provider'].includes(node.data.kind)) || (key === 'mmproj' && node.data.kind === 'llm.gguf_loader') ? (
              (() => {
                const isMmproj = key === 'mmproj';
                const expectedType = isMmproj ? 'mmproj' : node.data.kind === 'llm.gguf_loader' ? 'gguf' : node.data.kind === 'llm.openai_loader' ? 'api' : null;
                const options = modelOptions.filter((option) => option.type === expectedType || (!option.type && !isMmproj && (expectedType === 'gguf' ? option.value.includes('q4') : !option.value.includes('q4'))));
                const current = value;
                const selected = modelOptions.find((option) => option.value === value);
                return <>
                  <select value={current} onChange={(event) => setConfig(key, event.target.value)}>
                    {isMmproj && <option value="">不使用 mmproj（纯文本）</option>}
                    {value && !options.some((option) => option.value === value) && <option value={value}>当前文件不可用：{value}</option>}
                    {options.map((option) => <option key={option.value} value={option.value} disabled={option.ready === false}>{option.label}{option.ready === false ? ' · 未就绪' : ''}</option>)}
                  </select>
                  {selected?.ready === false && <small className="field-hint">{selected.reason}</small>}
                </>;
              })()
            ) : key === 'file' && node.data.kind === 'prompt.markdown_file' ? (
              <select value={value} onChange={(event) => setConfig(key, event.target.value)}>{promptFiles.map((file) => <option key={file} value={file}>{file}</option>)}</select>
            ) : key === 'display_mode' ? (
              <select value={value} onChange={(event) => setConfig(key, event.target.value)}>
                {(key === 'display_mode' ? ['normal', 'transparent'] : ['CUDA', 'CPU', 'auto']).map((option) => <option key={option}>{option}</option>)}
              </select>
            ) : Array.isArray(definition.configSchema?.properties?.[key]?.enum) ? (
              <select value={value ?? ''} onChange={(event) => setConfig(key, event.target.value)}>
                {definition.configSchema.properties[key].enum.map((option) => <option key={String(option)} value={option}>{String(option)}</option>)}
              </select>
            ) : (
              <textarea rows={key === 'text' ? 5 : 1} value={value ?? ''} onChange={(event) => setConfig(key, event.target.value)} />
            )}
          </label>
        ))}
        {node.data.kind === 'llm.openai_loader' && <div className="api-key-field"><label htmlFor={`api-key-${node.id}`}>API Key {credentialConfigured.includes(node.id) ? '· 已配置' : '· 未配置'}</label><input id={`api-key-${node.id}`} type="password" autoComplete="off" placeholder="输入后点保存；不会写入工作流" /><div><button className="secondary-button" onClick={saveCredential}><Save size={14} />保存密钥</button><button className="secondary-button" onClick={() => onSaveCredential?.(node.id, '')}>清除</button></div></div>}
        <section className="port-section">
          <span className="eyebrow">接口定义</span>
          {[['输入', definition.inputs], ['输出', definition.outputs]].map(([title, ports]) => (
            <div className="port-group" key={title}>
              <strong>{title}</strong>
              {ports.length ? ports.map((port) => <div className="port-inspector-row" key={port.id}><span>{port.label}</span><code>{port.type}</code></div>) : <span className="muted-line">无</span>}
            </div>
          ))}
        </section>
        <div className="implementation"><span className="eyebrow">实现类</span><code>{node.data.implementation || definition.type}</code></div>
      </div>
      <div className="inspector-actions"><button className="danger-button" onClick={() => onDelete(node.id)}><Trash2 size={15} />删除节点</button></div>
    </aside>
  );
}

function WorkflowEditor({ initialDocument, onNavigate }) {
  const initialGraph = fromDocument(initialDocument);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialGraph.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialGraph.edges);
  const [workflow, setWorkflow] = useState(initialDocument);
  const [selectedId, setSelectedId] = useState(null);
  const [search, setSearch] = useState('');
  const [notice, setNotice] = useState('');
  const [jsonOpen, setJsonOpen] = useState(false);
  const [jsonText, setJsonText] = useState('');
  const [jsonCopied, setJsonCopied] = useState(false);
  const [runPanel, setRunPanel] = useState(false);
  const [runInput, setRunInput] = useState('你好，介绍一下你自己。');
  const [running, setRunning] = useState(false);
  const [agentRunning, setAgentRunning] = useState(false);
  const [agentModelLoaded, setAgentModelLoaded] = useState(false);
  const [serverWorkflowId, setServerWorkflowId] = useState(null);
  const [agentStarting, setAgentStarting] = useState(false);
  const [agentStopping, setAgentStopping] = useState(false);
  const [runResult, setRunResult] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const lastEventsRef = useRef([]);
  const [modelOptions, setModelOptions] = useState(modelChoices);
  const [promptFiles, setPromptFiles] = useState([]);
  const [credentialConfigured, setCredentialConfigured] = useState([]);
  const [configKind, setConfigKind] = useState(null);
  const [previewRevision, setPreviewRevision] = useState(0);
  const [collapsedGroups, setCollapsedGroups] = useState({});
  const { fitView, getViewport } = useReactFlow();

  const previewSignature = useMemo(() => JSON.stringify({
    nodes: nodes.map((node) => ({ id: node.id, type: node.data.kind, config: node.data.config })),
    edges: edges.map((edge) => ({ source: edge.source, target: edge.target, sourceHandle: edge.sourceHandle, targetHandle: edge.targetHandle })),
    input: runInput,
  }), [nodes, edges, runInput]);

  useEffect(() => {
    const timer = setTimeout(async () => {
      try {
        const response = await fetch('/api/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workflow: toDocument(workflow, nodes, edges), input: runInput }) });
        const result = await response.json();
        if (!response.ok) return;
        setNodes((current) => current.map((node) => {
          const hasPreview = Object.hasOwn(result.previews || {}, node.id);
          const nextPreview = node.data.kind === 'core.chat_input' ? runInput : node.data.kind === 'prompt.text' ? node.data.config?.text ?? '' : result.previews?.[node.id];
          if (!hasPreview && !['core.chat_input', 'prompt.text'].includes(node.data.kind) || node.data.outputPreview === nextPreview) return node;
          const data = { ...node.data, outputPreview: nextPreview };
          return { ...node, data, ...(data.sizeMode === 'manual' ? {} : estimateNodeSize({ ...node, data })) };
        }));
      } catch { /* Preview is optional while the API is restarting. */ }
    }, 260);
    return () => clearTimeout(timer);
  }, [previewSignature, previewRevision]);

  useEffect(() => {
    fetch('/api/models')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('模型目录不可用')))
      .then((payload) => {
        if (Array.isArray(payload.models) && payload.models.length) setModelOptions(payload.models.map((model) => ({ ...model, value: model.id })));
      })
      .catch(() => { /* 开发服务器未启动时保留内置模型目录 */ });
  }, []);

  useEffect(() => {
    fetch('/api/prompts').then((response) => response.json()).then((result) => setPromptFiles(result.files || [])).catch(() => {});
    fetch('/api/model-credentials').then((response) => response.json()).then((result) => setCredentialConfigured(result.configured || [])).catch(() => {});
  }, []);

  const saveCredential = async (nodeId, apiKey) => {
    try {
      const response = await fetch('/api/model-credentials', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ node_id: nodeId, api_key: apiKey }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '保存失败');
      setCredentialConfigured((current) => result.configured ? [...new Set([...current, nodeId])] : current.filter((id) => id !== nodeId));
      setAgentRunning(false);
      setAgentModelLoaded(false);
      window.dispatchEvent(new Event('atri-runtime-status'));
      setNotice(result.configured ? 'API Key 已保存到本机配置' : 'API Key 已清除');
    } catch (cause) { setNotice(cause.message); }
  };

  useEffect(() => {
    let disposed = false;
    const refreshStatus = () => fetch('/api/status')
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((status) => {
        if (disposed) return;
        setAgentRunning(Boolean(status.running));
        setAgentModelLoaded(Boolean(status.model_loaded));
        setServerWorkflowId(status.workflow_id || null);
      })
      .catch(() => { if (!disposed) { setAgentRunning(false); setAgentModelLoaded(false); setServerWorkflowId(null); } });
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 2500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, []);

  const selectedNode = nodes.find((node) => node.id === selectedId) ?? null;
  const issues = useMemo(() => validateGraph(nodes, edges, modelOptions), [nodes, edges, modelOptions, nodeCatalog.length]);
  const groups = useMemo(() => {
    const filtered = nodeCatalog.filter((node) => !node.legacy && (node.label.toLowerCase().includes(search.toLowerCase()) || node.type.toLowerCase().includes(search.toLowerCase())));
    const categories = [...new Set([...Object.keys(categoryMeta), ...nodeCatalog.map((node) => node.category)])];
    return categories.map((category) => ({ category, items: filtered.filter((node) => node.category === category) })).filter((group) => group.items.length);
  }, [search]);

  const onConnect = useCallback((connection) => {
    const sourceNode = nodes.find((node) => node.id === connection.source);
    const targetNode = nodes.find((node) => node.id === connection.target);
    const sourcePort = findPort(sourceNode, connection.sourceHandle, 'source');
    const targetPort = findPort(targetNode, connection.targetHandle, 'target');
    if (!sourcePort || !targetPort || sourcePort.type !== targetPort.type) {
      setNotice('接口类型不匹配，连接未建立');
      window.setTimeout(() => setNotice(''), 2400);
      return;
    }
    const color = edgeColors[connection.sourceHandle] || '#667d72';
    setEdges((current) => addEdge({ ...connection, id: `e_${crypto.randomUUID().slice(0, 8)}`, type: 'smoothstep', style: { stroke: color, strokeWidth: 2 }, markerEnd: { type: 'arrowclosed', color, width: 15, height: 15 } }, current));
  }, [nodes, setEdges]);

  const addNode = (definition) => {
    const id = `${definition.type.split('.').at(-1)}_${crypto.randomUUID().slice(0, 5)}`;
    const center = { x: 380 + Math.random() * 260, y: 140 + Math.random() * 320 };
    const node = {
      id,
      type: 'workflow',
      position: center,
      data: {
        kind: definition.type,
        label: definition.label,
        category: definition.category,
        module_id: definition.moduleId,
        config: {
          ...Object.fromEntries(Object.entries(definition.configSchema?.properties || {}).filter(([, field]) => Object.hasOwn(field, 'default')).map(([key, field]) => [key, field.default])),
          ...definition.defaults,
        },
      },
    };
    setNodes((current) => [...current, { ...node, ...estimateNodeSize(node) }]);
    setSelectedId(id);
  };

  const updateNode = useCallback((id, data) => setNodes((current) => current.map((node) => {
    if (node.id !== id) return node;
    const nextData = { ...node.data, ...data };
    const size = nextData.sizeMode === 'manual' ? {} : estimateNodeSize({ ...node, data: nextData });
    return { ...node, ...size, data: nextData };
  })), [setNodes]);
  const syncNodeHeight = useCallback((id, measuredHeight) => {
    setNodes((current) => current.map((node) => {
      if (node.id !== id || Math.abs((node.height || 0) - measuredHeight) < 2) return node;
      return { ...node, height: measuredHeight };
    }));
  }, [setNodes]);
  const markNodeManuallySized = useCallback((id) => {
    setNodes((current) => current.map((node) => node.id === id
      ? { ...node, data: { ...node.data, sizeMode: 'manual' } }
      : node));
  }, [setNodes]);
  const togglePreview = useCallback((id, expanded) => {
    setNodes((current) => current.map((node) => {
      if (node.id !== id || Boolean(node.data.previewExpanded) === expanded) return node;
      return {
        ...node,
        data: { ...node.data, previewExpanded: expanded },
      };
    }));
  }, [setNodes]);
  const autoSizeNodes = useCallback(() => {
    setNodes((current) => current.map((node) => {
      const data = { ...node.data, sizeMode: 'auto' };
      return { ...node, ...estimateNodeSize({ ...node, data }), data };
    }));
    setNotice('所有节点已按内容自适应尺寸');
    window.setTimeout(() => setNotice(''), 2400);
  }, [setNodes]);
  const displayNodes = useMemo(() => nodes.map((node) => ({ ...node, data: { ...node.data, modelOptions, promptFiles, credentialConfigured, onSaveCredential: saveCredential, onOpenConfig: setConfigKind, onDataChange: updateNode, onPreviewToggle: togglePreview, onContentSize: syncNodeHeight, onResizeEnd: markNodeManuallySized } })), [nodes, modelOptions, promptFiles, credentialConfigured, updateNode, togglePreview, syncNodeHeight, markNodeManuallySized]);
  const deleteNode = (id) => {
    setNodes((current) => current.filter((node) => node.id !== id));
    setEdges((current) => current.filter((edge) => edge.source !== id && edge.target !== id));
    setSelectedId(null);
  };
  const currentDocument = () => ({ ...toDocument(workflow, nodes, edges), viewport: getViewport() });
  const saveLocal = async () => {
    const document = currentDocument();
    const content = JSON.stringify(document, null, 2);
    let response;
    try {
      response = await fetch('/api/workflows/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: document }),
      });
    } catch {
      response = null;
    }
    if (response) {
      let result = {};
      try { result = await response.json(); } catch { /* Report the HTTP status below. */ }
      if (!response.ok) {
        setNotice(`保存失败：${result.error || `HTTP ${response.status}`}`);
        window.setTimeout(() => setNotice(''), 4000);
        return;
      }
      try { localStorage.setItem('atri.workflow.v2', content); } catch { /* The workflow file is the persistent copy. */ }
      setNotice(`已保存到 workflows/${document.id}.json，刷新页面可重新加载`);
      window.setTimeout(() => setNotice(''), 3200);
      return;
    }

    const filename = `${document.id || 'workflow'}.json`;
    try {
      if (window.showSaveFilePicker) {
        const handle = await window.showSaveFilePicker({
          suggestedName: filename,
          types: [{ description: 'ATRI 工作流', accept: { 'application/json': ['.json'] } }],
        });
        const writable = await handle.createWritable();
        await writable.write(content);
        await writable.close();
        setNotice(`工作流已保存到本地文件：${handle.name}`);
      } else {
        downloadDocument(document);
        setNotice(`工作流 JSON 已下载：${filename}`);
      }
    } catch (error) {
      if (error.name === 'AbortError') return;
      downloadDocument(document);
      setNotice(`无法直接写入所选位置，已下载工作流：${filename}`);
    }
    window.setTimeout(() => setNotice(''), 3200);
  };
  const openJson = () => {
    setJsonText(JSON.stringify(currentDocument(), null, 2));
    setJsonCopied(false);
    setJsonOpen(true);
  };
  const applyJson = () => {
    try {
      const parsed = JSON.parse(jsonText);
      if (parsed.workflow_version !== 2 || !Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) throw new Error('需要 workflow_version 2，且包含 nodes / edges 数组');
      const nextGraph = fromDocument(parsed);
      setWorkflow(parsed);
      setNodes(nextGraph.nodes);
      setEdges(nextGraph.edges);
      setSelectedId(null);
      setJsonOpen(false);
      setNotice('JSON 已载入画布');
      window.setTimeout(() => setNotice(''), 2400);
    } catch (error) {
      setNotice(`JSON 错误：${error.message}`);
      window.setTimeout(() => setNotice(''), 3200);
    }
  };
  const importFile = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setJsonText(await file.text());
    setJsonOpen(true);
    event.target.value = '';
  };
  const runValidation = () => {
    const currentIssues = validateGraph(nodes, edges, modelOptions);
    setNotice(currentIssues.length ? `发现 ${currentIssues.length} 个接口问题` : '接口完整，JSON 结构可导出');
    window.setTimeout(() => setNotice(''), 2800);
  };
  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(jsonText);
      setJsonCopied(true);
      setNotice('JSON 已复制到剪贴板');
    } catch {
      setJsonCopied(false);
      setNotice('复制失败，请检查浏览器剪贴板权限');
    }
    window.setTimeout(() => setNotice(''), 2800);
  };
  const exportJson = () => downloadDocument(currentDocument());
  const startAgent = async () => {
    if (issues.length) {
      setNotice(`先修复工作流问题：${issues[0]}`);
      window.setTimeout(() => setNotice(''), 2800);
      return;
    }
    const document = currentDocument();
    setAgentStarting(true);
    setNotice('正在启动工作流并加载模型…');
    try {
      const response = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: document }),
      });
      const raw = await response.text();
      let payload;
      try { payload = raw ? JSON.parse(raw) : {}; } catch { throw new Error(`服务返回了无效数据（HTTP ${response.status}）`); }
      if (!response.ok) throw new Error(payload.error || '工作流启动失败');
      localStorage.setItem('atri.active.workflow.v2', JSON.stringify(document));
      setWorkflow(document);
      setAgentRunning(true);
      setAgentModelLoaded(Boolean(payload.model_loaded));
      setServerWorkflowId(payload.workflow_id || document.id);
      window.dispatchEvent(new Event('atri-workflow-applied'));
      window.dispatchEvent(new Event('atri-runtime-status'));
      setNotice('工作流运行中，模型已加载');
      window.setTimeout(() => setNotice(''), 2800);
    } catch (error) {
      setAgentRunning(false);
      setAgentModelLoaded(false);
      setServerWorkflowId(null);
      localStorage.removeItem('atri.active.workflow.v2');
      window.dispatchEvent(new Event('atri-runtime-status'));
      setNotice(`启动失败：${error.message}`);
      window.setTimeout(() => setNotice(''), 5000);
    } finally {
      setAgentStarting(false);
    }
  };
  const stopAgent = async () => {
    setAgentStopping(true);
    try {
      const response = await fetch('/api/stop', { method: 'POST' });
      const raw = await response.text();
      let payload;
      try { payload = raw ? JSON.parse(raw) : {}; } catch { throw new Error(`服务返回了无效数据（HTTP ${response.status}）`); }
      if (!response.ok) throw new Error(payload.error || '停止失败');
      setAgentRunning(false);
      setAgentModelLoaded(false);
      setServerWorkflowId(null);
      localStorage.removeItem('atri.active.workflow.v2');
      window.dispatchEvent(new Event('atri-runtime-status'));
      setNotice('工作流已停止，模型资源已释放');
      window.setTimeout(() => setNotice(''), 2800);
    } catch (error) {
      setNotice(`停止失败：${error.message}`);
      window.setTimeout(() => setNotice(''), 5000);
    } finally {
      setAgentStopping(false);
    }
  };
  const runWorkflow = async () => {
    if (!runInput.trim()) return;
    setRunning(true);
    setRunResult(null);
    setLiveEvents([]);
    lastEventsRef.current = [];
    setNodes((current) => current.map((node) => ({ ...node, data: { ...node.data, executionStatus: undefined } })));
    try {
      const payload = await runWorkflowRequest({ workflow: currentDocument(), input: runInput, mode: 'transparent' }, (events) => { setLiveEvents(events); lastEventsRef.current = events; });
      setRunResult(payload);
      lastEventsRef.current = payload.events || [];
      setAgentModelLoaded(true);
      setNodes((current) => current.map((node) => {
        let data = node.data;
        if (Object.hasOwn(payload.previews || {}, node.id)) data = { ...node.data, outputPreview: payload.previews[node.id] };
        if (node.data.kind === 'tools.dispatch') {
          const results = payload.events.filter((event) => event.event_type === 'node_output' && event.node_id === 'tools.dispatch').map((event) => event.data.content);
          if (results.length) data = { ...data, outputPreview: results.join('\n\n') };
        }
        if (node.data.kind === 'core.chat_input') data = { ...data, config: { ...(data.config || {}), debug_input: runInput } };
        if (data === node.data) return node;
        const size = data.sizeMode === 'manual' ? {} : estimateNodeSize({ ...node, data });
        return { ...node, ...size, data };
      }));
      const providerByModule = Object.fromEntries(nodes.filter((node) => node.data.module_id).map((node) => [node.data.module_id, node.id]));
      const nodeById = Object.fromEntries(nodes.map((node) => [node.id, node]));
      setNodes((current) => current.map((node) => ({ ...node, data: { ...node.data, executionStatus: 'complete' } })));
      const failed = payload.events.some((event) => event.event_type === 'workflow_failed');
      if (failed) setNodes((current) => current.map((node) => ['agent.react_runtime', 'llm.chat'].includes(node.data.kind) ? { ...node, data: { ...node.data, executionStatus: 'failed' } } : node));
      const router = nodes.find((node) => node.data.kind === 'react.response_router');
      const dispatcher = nodes.find((node) => node.data.kind === 'tools.dispatch');
      const outputNode = nodes.find((node) => node.data.kind === 'core.chat_output');
      const setStatus = (id, status) => id && setNodes((current) => current.map((node) => node.id === id ? { ...node, data: { ...node.data, executionStatus: status } } : node));
      for (const event of payload.events) {
        const eventNode = nodeById[event.node_id];
        const moduleId = ['llm', 'tools', 'skills', 'memory', 'prompt'].includes(event.node_id) ? event.node_id : null;
        const nodeId = eventNode ? eventNode.id : moduleId ? providerByModule[moduleId] : null;
        if (nodeId) setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, executionStatus: event.event_type.includes('failed') ? 'failed' : 'complete' } } : node));
        if (['response_parsed', 'response_routed_to_tools', 'response_routed_to_answer'].includes(event.event_type)) setStatus(router?.id, 'complete');
        if (['tool_call_requested', 'tool_completed', 'node_output'].includes(event.event_type) && event.node_id === 'tools.dispatch') setStatus(dispatcher?.id, 'complete');
        if (event.event_type === 'workflow_completed') setStatus(outputNode?.id, 'complete');
      }
    } catch (error) {
      setRunResult({ error: error.message, events: lastEventsRef.current });
      setNodes((current) => current.map((node) => {
        if (node.data.kind !== 'tools.dispatch') return node;
        const results = lastEventsRef.current.filter((event) => event.event_type === 'node_output' && event.node_id === 'tools.dispatch').map((event) => event.data.content);
        return results.length ? { ...node, data: { ...node.data, outputPreview: results.join('\n\n') } } : node;
      }));
    } finally {
      setRunning(false);
      setLiveEvents([]);
    }
  };

  return (
    <div className="studio-shell">
      <header className="topbar">
        <div className="brand-lockup"><div className="brand-mark">A</div><div><strong>ATRI <span>STUDIO</span></strong><small>WORKFLOW DESIGNER</small></div></div>
        <div className="topbar-divider" />
        <nav className="app-nav"><button onClick={() => onNavigate('chat')}>对话</button><button className="active" onClick={() => onNavigate('workflow')}>工作流</button></nav>
        <div className="workflow-identity"><span className="crumb">工作流</span><span className="crumb-separator">/</span><input aria-label="工作流名称" value={workflow.name} onChange={(event) => setWorkflow((current) => ({ ...current, name: event.target.value }))} /></div>
        <div className="topbar-spacer" />
        <span className="draft-status"><span className={agentRunning && serverWorkflowId === workflow.id ? 'applied' : ''} />{agentRunning && serverWorkflowId === workflow.id ? '当前 Agent 配置' : agentRunning ? `运行中：${serverWorkflowId || '其他工作流'}` : '未启动 / 未应用'}</span>
        <button className="icon-button json-button" onClick={openJson} title="查看和编辑工作流 JSON"><Code2 size={16} /><span>JSON</span></button>
        <ThemePicker />
        <label className="icon-button" title="导入工作流 JSON"><ArrowUpFromLine size={16} /><input className="file-input" type="file" accept="application/json,.json" onChange={importFile} /></label>
        <button className="icon-button export-button" onClick={exportJson} title="导出工作流 JSON"><ArrowDownToLine size={16} /></button>
        <button className="secondary-button reset-workflow-button" onClick={() => { setWorkflow(initialDocument); const graph = fromDocument(initialDocument); setNodes(graph.nodes); setEdges(graph.edges); setSelectedId(null); }} title="重置示例工作流"><FilePlus2 size={15} /><span>重置</span></button>
        <button className="secondary-button save-draft-button" onClick={saveLocal} title="保存工作流草稿到本机"><Save size={15} /><span>保存</span></button>
      </header>

      <main className="workspace">
        <aside className="palette">
          <div className="panel-heading"><div><span className="eyebrow">工作流构建器</span><h2>节点库</h2></div></div>
          <div className="search-box"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索节点" /></div>
          <div className="palette-scroll">
            {groups.map((group) => {
              const meta = categoryMeta[group.category];
              const collapsed = Boolean(collapsedGroups[group.category]);
              return <section className="palette-group" key={group.category}><button className="group-heading" aria-expanded={!collapsed} onClick={() => setCollapsedGroups((current) => ({ ...current, [group.category]: !current[group.category] }))}><span className={`group-indicator ${meta.color}`} /><span>{meta.label}</span><span className="group-count">{group.items.length}</span><ChevronDown size={13} /></button>{!collapsed && group.items.map((definition) => <PaletteItem key={definition.type} definition={definition} onAdd={addNode} />)}</section>;
            })}
            {groups.length === 0 && <div className="no-results">没有匹配的节点</div>}
          </div>
          <div className="palette-footer"><span className="footer-dot" />节点接口由 registry 提供</div>
        </aside>

        <section className="canvas-area">
          <div className="canvas-toolbar">
            <div className="canvas-tab active"><WorkflowIcon size={15} />画布</div>
            <div className="canvas-toolbar-spacer" />
            <div className="graph-readout"><span>{nodes.length} 节点</span><span className="readout-separator">·</span><span>{edges.length} 连接</span></div>
            <button className="icon-button run-button" onClick={runValidation} title="检查接口"><Check size={15} /></button>
            <button className="secondary-button auto-size-button" onClick={autoSizeNodes} title="让所有节点按内容自适应长宽"><Maximize2 size={15} /><span>自适应</span></button>
            <button className="icon-button" onClick={() => fitView({ padding: 0.24, duration: 250 })} title="适配画布"><Expand size={15} /></button>
          </div>
          <div className="canvas-wrap">
            <div className="canvas-caption"><span className="caption-chip">GRAPH V2</span><span>能力模块通过类型化接口连接到运行时</span></div>
            <div className="workflow-run-controls" role="group" aria-label="工作流运行控制">
              <button className={`workflow-control-button start-control ${agentRunning ? 'is-running' : ''}`} disabled={agentRunning || agentStarting} onClick={startAgent} title={agentRunning ? '当前工作流正在运行' : '启动当前工作流并加载模型'}>
                {agentStarting ? <span className="spinner" /> : <Play size={15} fill="currentColor" />}{agentRunning ? '运行中' : agentStarting ? '启动中' : '启动'}
              </button>
              <button className="workflow-control-button stop-control" disabled={(!agentRunning && !agentModelLoaded) || agentStopping} onClick={stopAgent} title="停止工作流并卸载模型">
                {agentStopping ? <span className="spinner" /> : <Square size={14} fill="currentColor" />}{agentStopping ? '停止中' : '停止'}
              </button>
              <span className="workflow-control-divider" />
              <button className={`workflow-control-button test-control ${runPanel ? 'selected' : ''}`} onClick={() => setRunPanel((value) => !value)} title="打开工作流试运行面板"><Play size={14} />试运行</button>
            </div>
            <ReactFlow
              nodes={displayNodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={(_, node) => setSelectedId(node.id)}
              onPaneClick={() => setSelectedId(null)}
              onNodesDelete={(deleted) => { if (deleted.some((node) => node.id === selectedId)) setSelectedId(null); }}
              isValidConnection={() => true}
              fitView
              fitViewOptions={{ padding: 0.24 }}
              minZoom={0.25}
              maxZoom={1.6}
              deleteKeyCode={['Backspace', 'Delete']}
              defaultEdgeOptions={{ type: 'smoothstep', style: { strokeWidth: 2, stroke: '#667d72' }, markerEnd: { type: 'arrowclosed', color: '#667d72', width: 15, height: 15 } }}
            >
              <Background color="#b8c1bd" gap={22} size={1} />
              <Controls position="bottom-left" showInteractive={false} />
              <MiniMap position="bottom-right" pannable zoomable nodeColor={(node) => {
                const group = categoryMeta[getNodeDefinition(node.data?.kind).category] || categoryMeta.control;
                return ({ mint: '#62b9a1', coral: '#e48571', blue: '#719ad0', amber: '#d3aa61', green: '#72a97c', violet: '#9681bf' })[group.color] ?? '#90a09a';
              }} />
            </ReactFlow>
            {runPanel && <div className="run-drawer">
              <div className="run-drawer-heading"><div><span className="eyebrow">WORKFLOW RUN</span><strong>试运行</strong></div><span className="transparent-mode-label">透明模式</span><button className="icon-button" onClick={() => setRunPanel(false)} title="关闭试运行"><X size={15} /></button></div>
              <textarea value={runInput} onChange={(event) => setRunInput(event.target.value)} placeholder="输入一条消息…" />
              <div className="run-drawer-actions"><span>{issues[0] || '将使用当前画布配置运行 Agent'}</span><button className="run-top-button" disabled={running || issues.length > 0} onClick={runWorkflow}>{running ? <span className="spinner" /> : <Play size={13} fill="currentColor" />}{running ? '运行中…' : '运行工作流'}</button></div>
              {running && liveEvents.length > 0 && <TraceView events={liveEvents} />}
              {runResult && <div className={`run-output ${runResult.error ? 'has-error' : ''}`}><strong>{runResult.error ? '运行失败' : 'Agent 回复'}</strong><p>{runResult.error || runResult.answer}</p>{runResult.events?.length > 0 && <TraceView events={runResult.events} />}</div>}
            </div>}
            {notice && <div className={`toast ${notice.startsWith('发现') || notice.startsWith('JSON 错误') ? 'warning' : ''}`}>{notice}</div>}
          </div>
          <div className="canvas-status"><div className="status-left"><span className={`status-light ${issues.length ? 'warn' : 'ok'}`} />{issues.length ? `${issues.length} 项待检查` : '接口连接正常'}<span className="status-sep">|</span><span>自动布局关闭</span></div><button onClick={runValidation}><Check size={13} />验证图结构</button></div>
        </section>

        <Inspector node={selectedNode} modelOptions={modelOptions} promptFiles={promptFiles} credentialConfigured={credentialConfigured} onSaveCredential={saveCredential} onChange={updateNode} onDelete={deleteNode} onClose={() => setSelectedId(null)} />
      </main>

      <footer className="app-footer"><span>ATRI · LOCAL WORKSPACE</span><span className="execution-note"><span className="note-dot" />试运行调用当前 Agent · 应用后在对话页使用</span></footer>

      {jsonOpen && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setJsonOpen(false); }}><section className="json-modal"><header><div><span className="eyebrow">WORKFLOW DOCUMENT</span><h2>工作流 JSON</h2></div><button className="icon-button" onClick={() => setJsonOpen(false)} title="关闭"><X size={17} /></button></header><textarea spellCheck="false" value={jsonText} onChange={(event) => { setJsonText(event.target.value); setJsonCopied(false); }} /><div className="modal-footer"><span>版本 2 · 节点 {nodes.length} · 连接 {edges.length}</span><div><button className="secondary-button" onClick={copyJson}>{jsonCopied ? <Check size={14} /> : <Copy size={14} />}{jsonCopied ? '已复制' : '复制'}</button><button className="primary-button" onClick={applyJson}><Check size={14} />应用到画布</button></div></div></section></div>}
      {configKind && <CapabilityPanel kind={configKind} onClose={() => setConfigKind(null)} onChanged={() => setPreviewRevision((value) => value + 1)} />}
    </div>
  );
}

function EditorFrame({ initialDocument, onNavigate }) {
  return <WorkflowEditor initialDocument={initialDocument} onNavigate={onNavigate} />;
}

function isLegacyDefault(document) {
  return document?.id === 'atri_companion_graph' && !document.nodes?.some((node) => node.type === 'llm.chat');
}

export default function WorkflowApp({ onNavigate }) {
  const [document, setDocument] = useState(null);
  useEffect(() => {
    Promise.all([
      fetch('/api/nodes').then((response) => response.ok ? response.json() : Promise.reject()).catch(() => null),
      fetch('/api/workflows').then((response) => response.ok ? response.json() : Promise.reject()).catch(() => null),
    ]).then(([nodePayload, workflowPayload]) => {
      if (Array.isArray(nodePayload?.nodes) && nodePayload.nodes.length) hydrateNodeCatalog(nodePayload.nodes);
      const diskWorkflow = workflowPayload?.workflows?.[0]?.document;
      if (diskWorkflow) {
        setDocument(diskWorkflow);
        return;
      }
      try {
        const saved = JSON.parse(localStorage.getItem('atri.workflow.v2') || 'null');
        if (saved && !isLegacyDefault(saved)) { setDocument(saved); return; }
      } catch { /* Fall back to the bundled graph when no local workflow is readable. */ }
      fetch('/companion_graph.json').then((response) => response.json()).then(setDocument);
    });
  }, []);
  if (!document) return <div className="loading-screen">ATRI WORKFLOW STUDIO</div>;
  return <ReactFlowProvider><EditorFrame initialDocument={document} onNavigate={onNavigate} /></ReactFlowProvider>;
}

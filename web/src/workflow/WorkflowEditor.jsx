import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  ConnectionLineType,
  useEdgesState,
  useNodesState,
  useNodesInitialized,
  useReactFlow,
} from '@xyflow/react';
import { ArrowDownToLine, ArrowUpFromLine, Check, ChevronDown, Code2, Copy, Expand, FilePlus2, FolderOpen, Maximize2, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Play, Plus, Save, Search, Spline, Square, Trash2, Waypoints, Workflow as WorkflowIcon, X } from 'lucide-react';
import WorkflowNode from './WorkflowNode';
import { categoryMeta, getNodeDefinition, hydrateNodeCatalog, modelChoices, nodeCatalog } from './catalog';
import { getPortTypeColor, portsCompatible } from './portTypes';
import { portLabel, useInterfaceLanguage } from './interfaceLanguage';
import { ThemePicker } from '../theme.jsx';
import CapabilityPanel from './CapabilityPanel';
import ApiModelPanel from './ApiModelPanel';
import TraceView from './TraceView';
import IterationStepper from './IterationStepper';
import VoiceOutput from './VoiceOutput';
import { runWorkflowRequest } from './runApi';
import { primeAudioPlayback } from './streamingTts';

const nodeTypes = { workflow: WorkflowNode };
const MIN_NODE_WIDTH = 216;

function fromDocument(document) {
  return {
    nodes: document.nodes.map((node) => {
      const definition = getNodeDefinition(node.type);
      const { api_key, base_url, ...fileConfig } = node.data?.config || {};
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
          ...(node.type === 'llm.openai_loader' ? {} : base_url === undefined ? {} : { base_url }),
        },
        },
      };
      const { width, height, measured, selected, dragging, resizing, ...cleanNode } = nextNode;
      return node.data?.sizeMode === 'manual'
        ? { ...cleanNode, width: Math.max(MIN_NODE_WIDTH, width || measured?.width || MIN_NODE_WIDTH), height: Math.max(72, height || measured?.height || 72), data: { ...cleanNode.data, manualHeight: node.data.manualHeight || height || measured?.height || 72 } }
        : cleanNode;
    }),
    edges: document.edges.map((edge) => {
      const source = document.nodes.find((node) => node.id === edge.source);
      const target = document.nodes.find((node) => node.id === edge.target);
      const legacyExecutor = target?.type === 'capability.dispatch' && ((source?.type === 'tools.provider' && edge.targetHandle === 'tools') || (source?.type === 'skills.provider' && edge.targetHandle === 'skills'));
      const sourceHandle = legacyExecutor ? 'executor' : source?.type === 'llm.chat' && edge.sourceHandle === 'trace' ? 'response' : edge.sourceHandle;
      const targetHandle = legacyExecutor ? (edge.targetHandle === 'tools' ? 'tool_executor' : 'skill_executor') : ['control.loop', 'react.loop'].includes(target?.type) && edge.targetHandle === 'trace' ? 'response' : edge.targetHandle;
      const color = getPortTypeColor(getNodeDefinition(source?.type).outputs.find((port) => port.id === sourceHandle)?.type);
      const { strokeDasharray, ...style } = edge.style || {};
      return { ...edge, sourceHandle, targetHandle, label: undefined, animated: false, style: { ...style, stroke: color, strokeWidth: 2 }, markerEnd: { type: 'arrowclosed', color, width: 15, height: 15 } };
    }),
  };
}

function toDocument(workflow, nodes, edges) {
  return {
    workflow_version: 2,
    id: workflow.id,
    name: workflow.name,
    description: workflow.description ?? '',
    nodes: nodes.map(({ type, width, height, measured, selected, dragging, resizing, dragHandle, ...node }) => {
      const { kind, connectionState, connectedPorts, executionStatus, executionDurationMs, interfaceLanguage, onDataChange, onPreviewToggle, onContentSize, onResizeStart, onResizeEnd, onOpenConfig, onSaveCredential, credentialConfigured, modelOptions, promptFiles, outputPreview, previewUsage, ...data } = node.data;
      const { api_key, ...config } = data.config || {};
      return { ...node, ...(data.sizeMode === 'manual' ? { width, height } : {}), type: kind, data: { ...data, config } };
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

function connectionIssue(connection, nodes) {
  const sourcePort = findPort(nodes.find((node) => node.id === connection.source), connection.sourceHandle, 'source');
  const targetPort = findPort(nodes.find((node) => node.id === connection.target), connection.targetHandle, 'target');
  if (!portsCompatible(sourcePort?.type, targetPort?.type)) return '接口类型不匹配，连接未建立';
  return null;
}

function withoutTargetConnection(edges, connection, excludedEdgeId = null) {
  return edges.filter((edge) => edge.id !== excludedEdgeId
    && !(edge.target === connection.target && edge.targetHandle === connection.targetHandle));
}

function isFeedbackConnection(connection, nodes, edges) {
  const sourceNode = nodes.find((node) => node.id === connection.source);
  if (['control.loop', 'react.loop'].includes(sourceNode?.data.kind) && connection.sourceHandle === 'loop') return true;
  const visited = new Set();
  const pending = [connection.target];
  while (pending.length) {
    const id = pending.pop();
    if (id === connection.source) return true;
    if (visited.has(id)) continue;
    visited.add(id);
    pending.push(...edges.filter((edge) => edge.source === id && !edge.data?.feedback).map((edge) => edge.target));
  }
  return false;
}

function styleConnection(connection, feedback, nodes) {
  const source = nodes.find((node) => node.id === connection.source);
  const color = getPortTypeColor(findPort(source, connection.sourceHandle, 'source')?.type);
  const { strokeDasharray, ...existingStyle } = connection.style || {};
  return {
    ...connection,
    data: { ...(connection.data || {}), feedback },
    style: { ...existingStyle, stroke: color, strokeWidth: 2 },
    markerEnd: { type: 'arrowclosed', color, width: 15, height: 15 },
  };
}

function supportsReasoningForNode(node, nodes, edges, modelOptions) {
  if (node?.data?.kind !== 'llm.chat') return false;
  const connection = edges.find((edge) => edge.target === node.id && edge.targetHandle === 'llm');
  const source = nodes.find((item) => item.id === connection?.source);
  if (source?.data?.kind === 'llm.openai_loader') return true;
  if (source?.data?.kind !== 'llm.provider') return false;
  return modelOptions.some((model) => model.value === source.data.config?.model && model.type === 'api');
}

function validateGraph(nodes, edges, modelOptions = [], language = 'zh', ttsModels = []) {
  const issues = [];
  const incoming = new Set(edges.map((edge) => `${edge.target}:${edge.targetHandle}`));
  const nodeMap = Object.fromEntries(nodes.map((node) => [node.id, node]));
  for (const edge of edges) {
    const source = nodeMap[edge.source];
    const target = nodeMap[edge.target];
    const sourcePort = findPort(source, edge.sourceHandle, 'source');
    const targetPort = findPort(target, edge.targetHandle, 'target');
    if (!sourcePort || !targetPort) issues.push(`连接 ${edge.id} 引用了不存在的接口`);
    else if (!portsCompatible(sourcePort.type, targetPort.type)) issues.push(`连接 ${edge.id} 的接口类型不匹配`);
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
    if (node.data.kind === 'audio.tts_model') {
      const model = ttsModels.find((option) => option.id === node.data.config?.model);
      if (!model) issues.push(`${node.data.label}: 请选择 TTS 模型`);
      else if (!model.available) issues.push(`${node.data.label}: TTS 模型文件未就绪 (${model.id})`);
    }
    for (const port of definition.inputs) {
      if (!port.optional && !incoming.has(`${node.id}:${port.id}`)) {
        issues.push(`${node.data.label}: ${language === 'en' ? 'missing' : '缺少'} ${portLabel(node.data.kind, port, language)} ${language === 'en' ? 'input' : '输入'}`);
      }
    }
  }
  if (!nodes.some((node) => ['agent.react_runtime', 'llm.chat'].includes(node.data.kind)) && !nodes.some((node) => node.data.kind === 'audio.tts_model') && !isDirectChatGraph(nodes, edges)) issues.push('无模型工作流需要将对话输入直接连接到回复输出');
  if (!nodes.some((node) => node.data.kind === 'core.chat_input')) issues.push('工作流需要一个对话输入节点');
  if (!nodes.some((node) => node.data.kind === 'core.chat_output')) issues.push('工作流需要一个回复输出节点');
  return issues;
}

function applyExecutionEvents(current, events) {
  const latest = new Map();
  for (const event of events) {
    if (!['node_started', 'node_completed', 'node_failed'].includes(event.event_type) || !event.node_id) continue;
    const duration = event.data?.duration_ms;
    latest.set(event.node_id, {
      executionStatus: event.event_type === 'node_started' ? 'running' : event.event_type === 'node_failed' ? 'failed' : 'complete',
      ...(event.event_type === 'node_completed' && Number.isFinite(duration) ? { executionDurationMs: duration } : {}),
    });
  }
  return current.map((node) => latest.has(node.id) ? { ...node, data: { ...node.data, ...latest.get(node.id) } } : node);
}

function isDirectChatGraph(nodes, edges) {
  if (nodes.length !== 2 || edges.length !== 1) return false;
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node.data.kind]));
  const edge = edges[0];
  return new Set(Object.values(byId)).size === 2
    && byId[edge.source] === 'core.chat_input'
    && byId[edge.target] === 'core.chat_output'
    && edge.sourceHandle === 'message'
    && edge.targetHandle === 'answer';
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

function Inspector({ node, edges = [], language, modelOptions = modelChoices, ttsModels = [], promptFiles = [], reasoningAvailable = false, onOpenConfig, onChange, onDelete }) {
  if (!node) return (
    <aside className="inspector empty-inspector">
      <div className="panel-heading"><div><span className="eyebrow">属性</span><h2>节点设置</h2></div></div>
      <div className="empty-selection"><WorkflowIcon size={24} /><strong>选择一个节点</strong><span>查看接口、绑定模块和配置项</span></div>
    </aside>
  );

  const definition = getNodeDefinition(node.data.kind);
  const meta = categoryMeta[definition.category] || categoryMeta.control;
  const Icon = meta.icon;
  const config = { ...Object.fromEntries(Object.entries(definition.configSchema?.properties || {})
    .filter(([, field]) => Object.hasOwn(field, 'default'))
    .map(([key, field]) => [key, field.default])), ...(node.data.config ?? {}) };
  const visiblePorts = (ports, direction) => ports.filter((port) => !port.hidden || edges.some((edge) => direction === 'input'
    ? edge.target === node.id && edge.targetHandle === port.id
    : edge.source === node.id && edge.sourceHandle === port.id));
  const setData = (patch) => onChange(node.id, { ...node.data, ...patch });
  const setConfig = (key, value) => setData({ config: { ...config, [key]: value } });

  return (
    <aside className="inspector">
      <div className="panel-heading"><div><span className="eyebrow">节点属性</span><h2>配置</h2></div></div>
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
        {Object.entries(config).filter(([key]) => !(node.data.kind === 'prompt.markdown_file' && key === 'source') && !(node.data.kind === 'llm.openai_loader' && key === 'base_url')).map(([key, value]) => (
          <div className="field-label config-field" key={key}>
            <span>{definition.configSchema?.properties?.[key]?.title || key.replaceAll('_', ' ')}</span>
            {typeof value === 'boolean' ? (
              <input type="checkbox" checked={value} onChange={(event) => setConfig(key, event.target.checked)} />
            ) : key === 'max_iterations' && typeof value === 'number' ? (
              <IterationStepper value={value} onChange={(next) => setConfig(key, next)} />
            ) : typeof value === 'number' ? (
              <input type="number" value={value} min={definition.configSchema?.properties?.[key]?.minimum} max={definition.configSchema?.properties?.[key]?.maximum} onChange={(event) => {
                if (!event.target.value) return;
                const field = definition.configSchema?.properties?.[key] || {};
                const next = Number(event.target.value);
                if (Number.isFinite(next)) setConfig(key, Math.min(field.maximum ?? Infinity, Math.max(field.minimum ?? -Infinity, field.type === 'integer' ? Math.trunc(next) : next)));
              }} />
            ) : key === 'model' && node.data.kind === 'audio.tts_model' ? (
              <select value={value ?? ''} onChange={(event) => setConfig(key, event.target.value)}>
                {value && !ttsModels.some((option) => option.id === value) && <option value={value}>当前模型不可用：{value}</option>}
                {ttsModels.map((option) => <option key={option.id} value={option.id} disabled={!option.available}>{option.label}{option.available ? '' : ' · 未就绪'}</option>)}
              </select>
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
            ) : key === 'reasoning_effort' ? (
              <><select value={reasoningAvailable ? value ?? 'auto' : 'auto'} disabled={!reasoningAvailable} onChange={(event) => setConfig(key, event.target.value)}>
                <option value="auto">{reasoningAvailable ? '自动（由提供商决定）' : 'GGUF 模型暂不支持'}</option>{reasoningAvailable && <><option value="minimal">极低</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">极高</option></>}
              </select>{!reasoningAvailable && <small className="field-hint">连接 API 运行时模型后可设置</small>}</>
            ) : Array.isArray(definition.configSchema?.properties?.[key]?.enum) ? (
              <select value={value ?? ''} onChange={(event) => setConfig(key, event.target.value)}>
                {definition.configSchema.properties[key].enum.map((option) => <option key={String(option)} value={option}>{String(option)}</option>)}
              </select>
            ) : (
              <textarea rows={key === 'text' ? 5 : 1} value={value ?? ''} onChange={(event) => setConfig(key, event.target.value)} />
            )}
          </div>
        ))}
        {node.data.kind === 'llm.openai_loader' && <button className="secondary-button inspector-config-button" onClick={() => onOpenConfig?.('api-models', config.model)}>配置模型</button>}
        <section className="port-section">
          <span className="eyebrow">接口定义</span>
          {[[language === 'en' ? 'Inputs' : '输入', visiblePorts(definition.inputs, 'input')], [language === 'en' ? 'Outputs' : '输出', visiblePorts(definition.outputs, 'output')]].map(([title, ports]) => (
            <div className="port-group" key={title}>
              <strong>{title}</strong>
              {ports.length ? ports.map((port) => <div className="port-inspector-row" key={port.id}><span>{portLabel(node.data.kind, port, language)}</span><code>{port.type}</code></div>) : <span className="muted-line">{language === 'en' ? 'None' : '无'}</span>}
            </div>
          ))}
        </section>
        <div className="implementation"><span className="eyebrow">实现类</span><code>{node.data.implementation || definition.type}</code></div>
      </div>
      <div className="inspector-actions"><button className="danger-button" onClick={() => onDelete(node.id)}><Trash2 size={15} />删除节点</button></div>
    </aside>
  );
}

function WorkflowEditor({ initialDocument, savedDocument, persisted, openTabs, availableWorkflows, onRefreshWorkflows, onOpenDocument, onSwitchWorkflow, onCloseWorkflow, onSaved }) {
  const [interfaceLanguage, setInterfaceLanguage] = useInterfaceLanguage();
  const initialGraph = fromDocument(initialDocument);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialGraph.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialGraph.edges);
  const [connectionHint, setConnectionHint] = useState(null);
  const [edgeMode, setEdgeMode] = useState(() => {
    try { return localStorage.getItem('atri.workflow.edge-mode') === 'step' ? 'step' : 'curve'; }
    catch { return 'curve'; }
  });
  const [workflow, setWorkflow] = useState(initialDocument);
  const [selectedId, setSelectedId] = useState(null);
  const [search, setSearch] = useState('');
  const [nodePicker, setNodePicker] = useState(null);
  const [nodePickerSearch, setNodePickerSearch] = useState('');
  const [workflowMenuOpen, setWorkflowMenuOpen] = useState(false);
  const [workflowSearch, setWorkflowSearch] = useState('');
  const workflowMenuRef = useRef(null);
  const [paletteCollapsed, setPaletteCollapsed] = useState(true);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(true);
  const [notice, setNotice] = useState('');
  const [jsonOpen, setJsonOpen] = useState(false);
  const [jsonText, setJsonText] = useState('');
  const [jsonCopied, setJsonCopied] = useState(false);
  const [saveDialog, setSaveDialog] = useState(null);
  const [saving, setSaving] = useState(false);
  const [runPanel, setRunPanel] = useState(false);
  const [runInput, setRunInput] = useState('你好，介绍一下你自己。');
  const [running, setRunning] = useState(false);
  const [agentRunning, setAgentRunning] = useState(false);
  const [runtimeStatusLoaded, setRuntimeStatusLoaded] = useState(false);
  const [agentModelLoaded, setAgentModelLoaded] = useState(false);
  const [serverWorkflowId, setServerWorkflowId] = useState(null);
  const [agentStarting, setAgentStarting] = useState(false);
  const [agentStopping, setAgentStopping] = useState(false);
  const [runResult, setRunResult] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [liveDraft, setLiveDraft] = useState('');
  const lastEventsRef = useRef([]);
  const [modelOptions, setModelOptions] = useState(modelChoices);
  const [ttsModels, setTtsModels] = useState([]);
  const [promptFiles, setPromptFiles] = useState([]);
  const [configKind, setConfigKind] = useState(null);
  const [configModelId, setConfigModelId] = useState('');
  const [previewRevision, setPreviewRevision] = useState(0);
  const [collapsedGroups, setCollapsedGroups] = useState({});
  const { fitView, getViewport, screenToFlowPosition, setViewport } = useReactFlow();
  const nodesInitialized = useNodesInitialized();
  const didInitialFit = useRef(false);
  const canvasRef = useRef(null);

  useEffect(() => {
    try { localStorage.setItem('atri.workflow.edge-mode', edgeMode); } catch { /* Canvas preference is optional. */ }
  }, [edgeMode]);

  useEffect(() => {
    if (!nodesInitialized || didInitialFit.current) return;
    didInitialFit.current = true;
    requestAnimationFrame(() => initialDocument.viewport
      ? setViewport(initialDocument.viewport, { duration: 0 })
      : fitView({ padding: 0.24, duration: 0, maxZoom: 1 }));
  }, [nodesInitialized, fitView, initialDocument.viewport, setViewport]);

  useEffect(() => {
    if (!workflowMenuOpen) return undefined;
    const closeMenu = (event) => {
      if (!workflowMenuRef.current?.contains(event.target)) setWorkflowMenuOpen(false);
    };
    document.addEventListener('pointerdown', closeMenu);
    return () => document.removeEventListener('pointerdown', closeMenu);
  }, [workflowMenuOpen]);
  useEffect(() => {
    if (running || agentStarting || agentStopping) setWorkflowMenuOpen(false);
  }, [running, agentStarting, agentStopping]);

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
          return { ...node, data };
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
    fetch('/api/tts/models')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('TTS 模型目录不可用')))
      .then((payload) => setTtsModels((payload.models || []).map((model) => ({
        ...model,
        label: model.id === 'qwen3-0.6b-q8' ? 'Qwen3-TTS 0.6B · Q8' : model.id === 'qwen3-1.7b-q4' ? 'Qwen3-TTS 1.7B · Q4' : model.id,
      }))))
      .catch(() => setTtsModels([]));
  }, []);

  useEffect(() => {
    fetch('/api/prompts').then((response) => response.json()).then((result) => setPromptFiles(result.files || [])).catch(() => {});
  }, []);

  const refreshModelOptions = async () => {
    const response = await fetch('/api/models');
    if (!response.ok) return;
    const payload = await response.json();
    setModelOptions((payload.models || []).map((model) => ({ ...model, value: model.id })));
    window.dispatchEvent(new Event('atri-runtime-status'));
  };

  useEffect(() => {
    let disposed = false;
    const refreshStatus = () => fetch('/api/status')
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((status) => {
        if (disposed) return;
        setRuntimeStatusLoaded(true);
        setAgentRunning(Boolean(status.running));
        setAgentModelLoaded(Boolean(status.model_loaded));
        setServerWorkflowId(status.workflow_id || null);
      })
      .catch(() => { if (!disposed) { setRuntimeStatusLoaded(false); setAgentRunning(false); setAgentModelLoaded(false); setServerWorkflowId(null); } });
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 2500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, []);

  const selectedNode = nodes.find((node) => node.id === selectedId) ?? null;
  const selectedEdge = edges.find((edge) => edge.selected) ?? null;
  const connectionEligibility = useMemo(() => {
    if (!connectionHint) return null;
    const origin = nodes.find((node) => node.id === connectionHint.nodeId);
    const originPort = findPort(origin, connectionHint.handleId, connectionHint.handleType);
    if (!originPort) return null;
    const targetIsInput = connectionHint.handleType === 'source';
    return new Map(nodes.map((node) => {
      const definition = getNodeDefinition(node.data.kind);
      const eligibleInputs = targetIsInput ? definition.inputs.filter((port) => !port.hidden && portsCompatible(originPort.type, port.type)).map((port) => port.id) : [];
      const eligibleOutputs = targetIsInput ? [] : definition.outputs.filter((port) => !port.hidden && portsCompatible(port.type, originPort.type)).map((port) => port.id);
      return [node.id, {
        type: originPort.type,
        origin: node.id === origin.id,
        originHandle: node.id === origin.id ? connectionHint.handleId : null,
        originDirection: connectionHint.handleType,
        eligibleInputs,
        eligibleOutputs,
      }];
    }));
  }, [connectionHint, nodes, nodeCatalog.length]);
  const displayEdges = useMemo(() => {
    const pairCounts = new Map();
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    return edges.map((edge) => {
      const pair = `${edge.source}:${edge.target}`;
      const lane = pairCounts.get(pair) || 0;
      pairCounts.set(pair, lane + 1);
      const source = nodeById.get(edge.source);
      const color = getPortTypeColor(findPort(source, edge.sourceHandle, 'source')?.type);
      const { strokeDasharray, ...style } = edge.style || {};
      return {
        ...edge,
        type: edgeMode === 'curve' ? 'default' : 'smoothstep',
        ...(edgeMode === 'curve' ? { pathOptions: { curvature: Math.min(0.75, 0.28 + lane * 0.12) } } : {}),
        style: { ...style, stroke: color, strokeWidth: 2 },
        markerEnd: { type: 'arrowclosed', color, width: 15, height: 15 },
      };
    });
  }, [edges, nodes, edgeMode, nodeCatalog.length]);
  const issues = useMemo(() => validateGraph(nodes, edges, modelOptions, interfaceLanguage, ttsModels), [nodes, edges, modelOptions, interfaceLanguage, ttsModels, nodeCatalog.length]);
  const groups = useMemo(() => {
    const filtered = nodeCatalog.filter((node) => !node.legacy && (node.label.toLowerCase().includes(search.toLowerCase()) || node.type.toLowerCase().includes(search.toLowerCase())));
    const categories = [...new Set([...Object.keys(categoryMeta), ...nodeCatalog.map((node) => node.category)])];
    return categories.map((category) => ({ category, items: filtered.filter((node) => node.category === category) })).filter((group) => group.items.length);
  }, [search]);

  const onConnect = useCallback((connection) => {
    const issue = connectionIssue(connection, nodes);
    if (issue) {
      setNotice(issue);
      window.setTimeout(() => setNotice(''), 2400);
      return;
    }
    setEdges((current) => {
      const available = withoutTargetConnection(current, connection);
      const feedback = isFeedbackConnection(connection, nodes, available);
      return addEdge(styleConnection({ ...connection, id: `e_${crypto.randomUUID().slice(0, 8)}` }, feedback, nodes), available);
    });
  }, [nodes, setEdges]);

  const onReconnect = useCallback((oldEdge, connection) => {
    const issue = connectionIssue(connection, nodes);
    if (issue) {
      setNotice(issue);
      window.setTimeout(() => setNotice(''), 2400);
      return;
    }
    setEdges((current) => {
      const others = withoutTargetConnection(current, connection, oldEdge.id);
      const feedback = isFeedbackConnection(connection, nodes, others);
      return [...others, styleConnection({ ...oldEdge, ...connection }, feedback, nodes)];
    });
  }, [nodes, setEdges]);

  const onConnectStart = useCallback((_, params) => {
    setConnectionHint(params);
  }, []);
  const onConnectEnd = useCallback(() => setConnectionHint(null), []);
  const isValidConnection = useCallback((connection) => !connectionIssue(connection, nodes), [nodes]);
  const connectionSource = nodes.find((node) => node.id === connectionHint?.nodeId);
  const connectionColor = getPortTypeColor(findPort(connectionSource, connectionHint?.handleId, connectionHint?.handleType)?.type);

  const addNode = (definition, position) => {
    const id = `${definition.type.split('.').at(-1)}_${crypto.randomUUID().slice(0, 5)}`;
    const center = position ?? { x: 380 + Math.random() * 260, y: 140 + Math.random() * 320 };
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
    setNodes((current) => [...current, node]);
    setSelectedId(id);
  };
  const openNodePicker = (event) => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    if (!bounds) return;
    setSelectedId(null);
    setNodePickerSearch('');
    setNodePicker({
      x: Math.max(8, Math.min(event.clientX - bounds.left, bounds.width - 320)),
      y: Math.max(8, Math.min(event.clientY - bounds.top, bounds.height - 430)),
      position: screenToFlowPosition({ x: event.clientX, y: event.clientY }),
    });
  };
  const pickerGroups = [...new Set([...Object.keys(categoryMeta), ...nodeCatalog.map((item) => item.category)])].map((category) => ({ category, items: nodeCatalog.filter((item) => !item.legacy && item.category === category && `${item.label} ${item.type}`.toLowerCase().includes(nodePickerSearch.toLowerCase())) })).filter((group) => group.items.length);

  const updateNode = useCallback((id, data) => setNodes((current) => current.map((node) => {
    if (node.id !== id) return node;
    const nextData = { ...node.data, ...data };
    return { ...node, data: nextData };
  })), [setNodes]);
  const syncNodeHeight = useCallback((id, measuredHeight) => {
    setNodes((current) => {
      const target = current.find((node) => node.id === id);
      if (!target || target.data.sizeMode !== 'manual' || target.resizing) return current;
      const height = Math.max(target.data.manualHeight || 72, measuredHeight);
      if (Math.abs((target.height || 0) - height) < 2) return current;
      return current.map((node) => node.id === id ? { ...node, height } : node);
    });
  }, [setNodes]);
  const markNodeManuallySized = useCallback((id) => {
    setNodes((current) => {
      const target = current.find((node) => node.id === id);
      if (!target || (target.data.sizeMode === 'manual' && target.width && target.height)) return current;
      return current.map((node) => node.id === id
        ? { ...node, width: node.width || node.measured?.width || MIN_NODE_WIDTH, height: node.height || node.measured?.height || 72, data: { ...node.data, sizeMode: 'manual', manualHeight: node.height || node.measured?.height || 72 } }
        : node);
    });
  }, [setNodes]);
  const finishNodeResize = useCallback((id, dimensions) => {
    setNodes((current) => current.map((node) => node.id === id
      ? { ...node, data: { ...node.data, sizeMode: 'manual', manualHeight: dimensions?.height || node.height || 72 } }
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
      const { manualHeight, ...nodeData } = node.data;
      const data = { ...nodeData, sizeMode: 'auto' };
      const { width, height, measured, ...intrinsicNode } = node;
      return { ...intrinsicNode, data };
    }));
    setNotice('所有节点已按内容自适应尺寸');
    window.setTimeout(() => setNotice(''), 2400);
  }, [setNodes]);
  const displayNodes = useMemo(() => nodes.map((node) => ({ ...node, dragHandle: '.workflow-node-header', data: { ...node.data, interfaceLanguage, reasoningAvailable: supportsReasoningForNode(node, nodes, edges, modelOptions), connectedPorts: { inputs: edges.filter((edge) => edge.target === node.id).map((edge) => edge.targetHandle), outputs: edges.filter((edge) => edge.source === node.id).map((edge) => edge.sourceHandle) }, connectionState: connectionEligibility?.get(node.id) || null, modelOptions, ttsModels, promptFiles, onOpenConfig: (kind, modelId) => { setConfigModelId(modelId || ''); setConfigKind(kind); }, onDataChange: updateNode, onPreviewToggle: togglePreview, onContentSize: syncNodeHeight, onResizeStart: markNodeManuallySized, onResizeEnd: finishNodeResize } })), [nodes, edges, interfaceLanguage, connectionEligibility, modelOptions, ttsModels, promptFiles, updateNode, togglePreview, syncNodeHeight, markNodeManuallySized, finishNodeResize]);
  const deleteNode = (id) => {
    setNodes((current) => current.filter((node) => node.id !== id));
    setEdges((current) => current.filter((edge) => edge.source !== id && edge.target !== id));
    setSelectedId(null);
  };
  const currentDocument = () => ({ ...toDocument(workflow, nodes, edges), viewport: getViewport() });
  const openSaveDialog = (mode) => setSaveDialog({ mode, name: workflow.name, id: persisted ? workflow.id : '' });
  const saveDocument = async (document, mode = 'save') => {
    if (saving) return;
    setSaving(true);
    try {
      const response = await fetch('/api/workflows/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: document, previous_id: persisted ? workflow.id : null, create_only: !persisted }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      try { localStorage.setItem('atri.workflow.v2', JSON.stringify(document)); } catch { /* The workflow file is the persistent copy. */ }
      setWorkflow(document);
      setSaveDialog(null);
      onSaved(document, workflow.id);
      onRefreshWorkflows().catch(() => {});
      setNotice(`${mode === 'rename' ? '已重命名并保存' : '已保存'}：workflows/${document.id}.json`);
    } catch (error) {
      setNotice(`保存失败：${error.message}`);
    } finally {
      setSaving(false);
      window.setTimeout(() => setNotice(''), 4000);
    }
  };
  const saveLocal = () => persisted ? saveDocument(currentDocument()) : openSaveDialog('new');
  const submitSaveDialog = (event) => {
    event.preventDefault();
    const id = saveDialog.id.trim().replace(/\.json$/i, '');
    const name = saveDialog.name.trim();
    if (!name || !/^[A-Za-z0-9_-]+$/.test(id)) {
      setNotice('请输入名称；文件名只能使用英文字母、数字、下划线和连字符');
      return;
    }
    if (id !== workflow.id && openTabs.some((tab) => tab.id === id)) {
      setNotice('该文件名已在其他标签中打开');
      return;
    }
    if (agentRunning && serverWorkflowId === workflow.id && id !== workflow.id) {
      setNotice('请先停止运行中的工作流，再重命名文件');
      return;
    }
    saveDocument({ ...currentDocument(), id, name }, saveDialog.mode);
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
      if (!parsed.id || !parsed.name) throw new Error('工作流需要 id 和 name');
      if (parsed.id !== workflow.id) {
        if (openTabs.some((tab) => tab.id === parsed.id)) throw new Error('该工作流已在其他标签中打开');
        onOpenDocument(parsed, currentDocument(), false);
        return;
      }
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
    const currentIssues = validateGraph(nodes, edges, modelOptions, interfaceLanguage, ttsModels);
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
  const openWorkflowMenu = async () => {
    if (workflowMenuOpen) { setWorkflowMenuOpen(false); return; }
    setWorkflowSearch('');
    setWorkflowMenuOpen(true);
    try { await onRefreshWorkflows(); } catch { setNotice('无法读取工作流文件夹，请检查后端服务'); }
  };
  const createWorkflow = () => {
    const document = {
      workflow_version: 2,
      id: `workflow_${crypto.randomUUID().slice(0, 8)}`,
      name: '未命名工作流',
      description: '',
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      metadata: { status: 'design', executable: false },
    };
    onOpenDocument(document, currentDocument(), false);
  };
  const startAgent = async () => {
    if (issues.length) {
      setNotice(`先修复工作流问题：${issues[0]}`);
      window.setTimeout(() => setNotice(''), 2800);
      return;
    }
    const document = currentDocument();
    setAgentStarting(true);
    setNotice(isDirectChatGraph(nodes, edges) ? '正在启动直通工作流…' : '正在启动工作流并加载模型…');
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
      setNotice(payload.model_loaded ? '工作流运行中，模型已加载' : '直通工作流运行中');
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
    if (!runtimeStatusLoaded) {
      setNotice('正在确认后端运行状态，请稍后重试');
      return;
    }
    if (agentRunning && serverWorkflowId !== workflow.id) {
      setNotice(`请先停止运行中的工作流：${serverWorkflowId}`);
      return;
    }
    void primeAudioPlayback().catch(() => {});
    setRunning(true);
    setRunResult(null);
    setLiveEvents([]);
    setLiveDraft('');
    lastEventsRef.current = [];
    setNodes((current) => current.map((node) => ({ ...node, data: { ...node.data, executionStatus: undefined, executionDurationMs: undefined } })));
    try {
      const payload = await runWorkflowRequest({ workflow: currentDocument(), input: runInput, mode: 'transparent' }, (events, draft) => {
        setLiveDraft(draft);
        if (events.length !== lastEventsRef.current.length) {
          setLiveEvents(events);
          lastEventsRef.current = events;
          setNodes((current) => applyExecutionEvents(current, events));
        }
      });
      setRunResult(payload);
      lastEventsRef.current = payload.events || [];
      setAgentModelLoaded(nodes.some((node) => ['llm.chat', 'agent.react_runtime'].includes(node.data.kind)));
      setNodes((current) => current.map((node) => {
        let data = node.data;
        if (Object.hasOwn(payload.previews || {}, node.id)) data = { ...node.data, outputPreview: payload.previews[node.id] };
        if (['capability.dispatch', 'tools.dispatch'].includes(node.data.kind)) {
          const results = payload.events.filter((event) => event.event_type === 'node_output' && ['capability.dispatch', 'tools.dispatch'].includes(event.node_id)).map((event) => event.data.content);
          if (results.length) data = { ...data, outputPreview: results.join('\n\n') };
        }
        if (data === node.data) return node;
        return { ...node, data };
      }));
      setNodes((current) => applyExecutionEvents(current, payload.events || []));
      const failed = payload.events.some((event) => event.event_type === 'workflow_failed');
      if (failed) setNodes((current) => current.map((node) => ['agent.react_runtime', 'llm.chat'].includes(node.data.kind) ? { ...node, data: { ...node.data, executionStatus: 'failed' } } : node));
    } catch (error) {
      setRunResult({ error: error.message, events: lastEventsRef.current });
      setNodes((current) => current.map((node) => {
        if (!['capability.dispatch', 'tools.dispatch'].includes(node.data.kind)) return node;
        const results = lastEventsRef.current.filter((event) => event.event_type === 'node_output' && ['capability.dispatch', 'tools.dispatch'].includes(event.node_id)).map((event) => event.data.content);
        return results.length ? { ...node, data: { ...node.data, outputPreview: results.join('\n\n') } } : node;
      }));
    } finally {
      setRunning(false);
      setLiveEvents([]);
      setLiveDraft('');
    }
  };

  return (
    <div className="studio-shell">
      <header className="topbar">
        <div className="brand-lockup"><div className="brand-mark">A</div><div><strong>ATRI <span>STUDIO</span></strong><small>WORKFLOW DESIGNER</small></div></div>
        <div className="topbar-divider" />
        <div className="workflow-identity"><span className="crumb">工作流</span><span className="crumb-separator">/</span><button className="workflow-name-button" onClick={() => openSaveDialog('rename')} disabled={saving || agentStarting || agentStopping} title="点击重命名工作流和文件" aria-label={`重命名 ${workflow.name}`}>{workflow.name}</button></div>
        <div className="topbar-spacer" />
        <span className="draft-status" title={agentRunning && serverWorkflowId === workflow.id ? '当前 Agent 配置' : agentRunning ? `运行中：${serverWorkflowId || '其他工作流'}` : '未启动 / 未应用'}><span className={agentRunning && serverWorkflowId === workflow.id ? 'applied' : ''} />{agentRunning && serverWorkflowId === workflow.id ? '当前 Agent 配置' : agentRunning ? `运行中：${serverWorkflowId || '其他工作流'}` : '未启动 / 未应用'}</span>
        <button className="icon-button json-button" onClick={openJson} title="查看和编辑工作流 JSON"><Code2 size={16} /><span>JSON</span></button>
        <ThemePicker />
        <label className="icon-button" title="导入工作流 JSON"><ArrowUpFromLine size={16} /><input className="file-input" type="file" accept="application/json,.json" onChange={importFile} /></label>
        <button className="icon-button export-button" onClick={exportJson} title="导出工作流 JSON"><ArrowDownToLine size={16} /></button>
        <button className="secondary-button reset-workflow-button" onClick={() => { setWorkflow(savedDocument); const graph = fromDocument(savedDocument); setNodes(graph.nodes); setEdges(graph.edges); setSelectedId(null); }} title="恢复当前工作流的已保存版本"><FilePlus2 size={15} /><span>重置</span></button>
        <button className="secondary-button save-draft-button" onClick={saveLocal} disabled={saving} title="保存工作流到项目文件"><Save size={15} /><span>{saving ? '保存中' : '保存'}</span></button>
      </header>

      <div className="workflow-tabs">
        <div className="workflow-open" ref={workflowMenuRef}>
          <button className="workflow-open-button" onClick={openWorkflowMenu} disabled={running || agentStarting || agentStopping} aria-expanded={workflowMenuOpen} title="打开工作流"><FolderOpen size={16} /><span>打开工作流</span><ChevronDown size={14} /></button>
          {workflowMenuOpen && <div className="workflow-open-menu" onKeyDown={(event) => { if (event.key === 'Escape') setWorkflowMenuOpen(false); }}>
            <label><Search size={14} /><input autoFocus value={workflowSearch} onChange={(event) => setWorkflowSearch(event.target.value)} placeholder="搜索工作流" /></label>
            <div className="workflow-open-list">{availableWorkflows.filter((item) => `${item.name} ${item.id}`.toLowerCase().includes(workflowSearch.toLowerCase())).map((item) => <button key={item.id} onClick={() => { onOpenDocument(item.document, currentDocument(), true); setWorkflowMenuOpen(false); }} title={item.validation_error || item.id}><WorkflowIcon size={15} /><span><strong>{item.name}</strong><small>{item.validation_error ? `需要修复：${item.validation_error}` : item.id}</small></span>{openTabs.some((tab) => tab.id === item.id) && <small>已打开</small>}</button>)}
              {availableWorkflows.length === 0 && <span className="no-results">工作流文件夹为空</span>}
            </div>
            <button className="workflow-create-button" onClick={createWorkflow}><Plus size={16} />新建空白工作流</button>
          </div>}
        </div>
        <div className="workflow-tab-list" role="tablist" aria-label="已打开的工作流">
          {openTabs.map((tab) => <div className={`workflow-tab ${tab.id === initialDocument.id ? 'active' : ''}`} key={tab.id}>
            <button role="tab" aria-selected={tab.id === initialDocument.id} title={tab.id} disabled={running || agentStarting || agentStopping} onClick={() => onSwitchWorkflow(tab.id, currentDocument())}>
              {agentRunning && serverWorkflowId === tab.id && <span className="workflow-tab-running" />}
              <span>{tab.id === initialDocument.id ? workflow.name : tab.document.name}</span>
            </button>
            {openTabs.length > 1 && <button className="workflow-tab-close" title={`关闭 ${tab.document.name}`} aria-label={`关闭 ${tab.document.name}`} disabled={!runtimeStatusLoaded || running || agentStarting || agentStopping || (agentRunning && serverWorkflowId === tab.id)} onClick={() => onCloseWorkflow(tab.id, currentDocument())}><X size={13} /></button>}
          </div>)}
        </div>
      </div>

      <main className={`workspace ${paletteCollapsed ? 'palette-collapsed' : ''} ${inspectorCollapsed ? 'inspector-collapsed' : ''}`}>
        <aside className="palette">
          <div className="panel-heading"><div><span className="eyebrow">工作流构建器</span><h2>节点库</h2></div></div>
          <div className="search-box"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索节点" /></div>
          <div className="palette-scroll">
            {groups.map((group) => {
              const meta = categoryMeta[group.category] || categoryMeta.control;
              const collapsed = Boolean(collapsedGroups[group.category]);
              return <section className="palette-group" key={group.category}><button className="group-heading" aria-expanded={!collapsed} onClick={() => setCollapsedGroups((current) => ({ ...current, [group.category]: !current[group.category] }))}><span className={`group-indicator ${meta.color}`} /><span>{meta.label}</span><span className="group-count">{group.items.length}</span><ChevronDown size={13} /></button><div className={`motion-collapse ${collapsed ? '' : 'is-open'}`} inert={collapsed ? '' : undefined}><div>{group.items.map((definition) => <PaletteItem key={definition.type} definition={definition} onAdd={addNode} />)}</div></div></section>;
            })}
            {groups.length === 0 && <div className="no-results">没有匹配的节点</div>}
          </div>
          <div className="palette-footer"><span className="footer-dot" />节点接口由 registry 提供</div>
        </aside>

        <section className="canvas-area">
          <div className="canvas-toolbar">
            <button className="icon-button sidebar-toggle" onClick={() => setPaletteCollapsed((value) => !value)} title={paletteCollapsed ? '展开节点库' : '收起节点库'} aria-label={paletteCollapsed ? '展开节点库' : '收起节点库'} aria-expanded={!paletteCollapsed}>{paletteCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}</button>
            <div className="canvas-tab active"><WorkflowIcon size={15} />画布</div>
            <div className="canvas-toolbar-spacer" />
            <div className="graph-readout"><span>{nodes.length} 节点</span><span className="readout-separator">·</span><span>{edges.length} 连接</span></div>
            <div className="interface-language-control" role="group" aria-label="接口语言" title="节点接口与执行轨迹语言">
              <button className={interfaceLanguage === 'zh' ? 'active' : ''} onClick={() => setInterfaceLanguage('zh')} aria-pressed={interfaceLanguage === 'zh'}>中文</button>
              <button className={interfaceLanguage === 'en' ? 'active' : ''} onClick={() => setInterfaceLanguage('en')} aria-pressed={interfaceLanguage === 'en'}>EN</button>
            </div>
            <div className="edge-mode-control" role="group" aria-label="连线形状">
              <button className={edgeMode === 'curve' ? 'active' : ''} onClick={() => setEdgeMode('curve')} title="曲线连线" aria-label="曲线连线" aria-pressed={edgeMode === 'curve'}><Spline size={16} /></button>
              <button className={edgeMode === 'step' ? 'active' : ''} onClick={() => setEdgeMode('step')} title="直角折线" aria-label="直角折线" aria-pressed={edgeMode === 'step'}><Waypoints size={16} /></button>
            </div>
            {selectedEdge && <button className="icon-button delete-edge-button" onClick={() => setEdges((current) => current.filter((edge) => edge.id !== selectedEdge.id))} title="删除选中的连线" aria-label="删除选中的连线"><Trash2 size={15} /></button>}
            <button className="secondary-button auto-size-button" onClick={autoSizeNodes} title="让所有节点按内容自适应长宽"><Maximize2 size={15} /><span>自适应</span></button>
            <button className="icon-button" onClick={() => fitView({ padding: 0.24, duration: 250 })} title="适配画布"><Expand size={15} /></button>
            <button className="icon-button sidebar-toggle" onClick={() => setInspectorCollapsed((value) => !value)} title={inspectorCollapsed ? '展开节点属性' : '收起节点属性'} aria-label={inspectorCollapsed ? '展开节点属性' : '收起节点属性'} aria-expanded={!inspectorCollapsed}>{inspectorCollapsed ? <PanelRightOpen size={17} /> : <PanelRightClose size={17} />}</button>
          </div>
          <div className="canvas-wrap" ref={canvasRef}>
            <div className="canvas-caption"><span className="caption-chip">GRAPH V2</span><span>能力模块通过类型化接口连接到运行时</span></div>
            <div className="workflow-run-controls" role="group" aria-label="工作流运行控制">
              <button className={`workflow-control-button start-control ${agentRunning && serverWorkflowId === workflow.id ? 'is-running' : ''}`} disabled={!runtimeStatusLoaded || agentRunning || agentStarting} onClick={startAgent} title={agentRunning ? `正在运行：${serverWorkflowId}` : '启动当前工作流'}>
                {agentStarting ? <span className="spinner" /> : <Play size={15} fill="currentColor" />}{agentRunning ? serverWorkflowId === workflow.id ? '运行中' : '其他运行中' : agentStarting ? '启动中' : '启动'}
              </button>
              <button className="workflow-control-button stop-control" disabled={(!agentRunning && !agentModelLoaded) || agentStopping} onClick={stopAgent} title="停止工作流并卸载模型">
                {agentStopping ? <span className="spinner" /> : <Square size={14} fill="currentColor" />}{agentStopping ? '停止中' : '停止'}
              </button>
              <span className="workflow-control-divider" />
              <button className={`workflow-control-button test-control ${runPanel ? 'selected' : ''}`} onClick={() => setRunPanel((value) => !value)} title="打开工作流试运行面板"><Play size={14} />试运行</button>
            </div>
            <ReactFlow
              nodes={displayNodes}
              edges={displayEdges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onConnectStart={onConnectStart}
              onConnectEnd={onConnectEnd}
              onReconnect={onReconnect}
              onReconnectEnd={() => setConnectionHint(null)}
              edgesReconnectable
              reconnectRadius={20}
              connectionLineType={edgeMode === 'curve' ? ConnectionLineType.Bezier : ConnectionLineType.SmoothStep}
              connectionLineStyle={{ stroke: connectionColor, strokeWidth: 2.5 }}
              onEdgeClick={() => setSelectedId(null)}
              onNodeClick={(_, node) => setSelectedId(node.id)}
              onPaneClick={(event) => event.detail === 2 ? openNodePicker(event) : setSelectedId(null)}
              zoomOnDoubleClick={false}
              onNodesDelete={(deleted) => { if (deleted.some((node) => node.id === selectedId)) setSelectedId(null); }}
              isValidConnection={isValidConnection}
              minZoom={0.25}
              maxZoom={1.6}
              deleteKeyCode={['Backspace', 'Delete']}
              defaultEdgeOptions={{ style: { strokeWidth: 2, stroke: '#667d72' }, markerEnd: { type: 'arrowclosed', color: '#667d72', width: 15, height: 15 } }}
            >
              <Background color="#b8c1bd" gap={22} size={1} />
              <Controls position="bottom-left" showInteractive={false} />
              <MiniMap position="bottom-right" pannable zoomable nodeColor={(node) => {
                const group = categoryMeta[getNodeDefinition(node.data?.kind).category] || categoryMeta.control;
                return ({ mint: '#62b9a1', coral: '#e48571', blue: '#719ad0', amber: '#d3aa61', green: '#72a97c', violet: '#9681bf' })[group.color] ?? '#90a09a';
              }} />
            </ReactFlow>
            {nodePicker && <div className="node-picker-backdrop" onMouseDown={() => setNodePicker(null)}>
              <section className="node-picker" role="dialog" aria-label="添加节点" style={{ left: nodePicker.x, top: nodePicker.y }} onMouseDown={(event) => event.stopPropagation()} onKeyDown={(event) => { if (event.key === 'Escape') setNodePicker(null); }}>
                <label className="node-picker-search"><Search size={16} /><input autoFocus value={nodePickerSearch} onChange={(event) => setNodePickerSearch(event.target.value)} placeholder="搜索节点名称或类型" /></label>
                <div className="node-picker-list">{pickerGroups.map((group) => <section key={group.category}><span className="node-picker-category">{categoryMeta[group.category]?.label || group.category}</span>{group.items.map((definition) => {
                  const meta = categoryMeta[definition.category] || categoryMeta.control;
                  const Icon = meta.icon;
                  return <button key={definition.type} onClick={() => { addNode(definition, nodePicker.position); setNodePicker(null); }}><span className={`palette-icon ${meta.color}`}><Icon size={16} /></span><span><strong>{definition.label}</strong><small>{definition.type}</small></span><Plus size={15} /></button>;
                })}</section>)}{pickerGroups.length === 0 && <div className="no-results">没有匹配的节点</div>}</div>
              </section>
            </div>}
            {runPanel && <div className="run-drawer">
              <div className="run-drawer-heading"><div><span className="eyebrow">WORKFLOW RUN</span><strong>试运行</strong></div><span className="transparent-mode-label">透明模式</span><button className="icon-button" onClick={() => setRunPanel(false)} title="关闭试运行"><X size={15} /></button></div>
              <textarea value={runInput} onChange={(event) => setRunInput(event.target.value)} placeholder="输入一条消息…" />
              <div className="run-drawer-actions"><span>{agentRunning && serverWorkflowId !== workflow.id ? `请先停止运行中的工作流：${serverWorkflowId}` : issues[0] || '将使用当前画布配置运行工作流'}</span><button className="run-top-button" disabled={!runtimeStatusLoaded || running || issues.length > 0 || (agentRunning && serverWorkflowId !== workflow.id)} onClick={runWorkflow}>{running ? <span className="spinner" /> : <Play size={13} fill="currentColor" />}{running ? '运行中…' : '运行工作流'}</button></div>
              {running && liveDraft && <div className="run-output is-streaming"><strong>正在生成</strong><p>{liveDraft}<span className="stream-caret" aria-hidden="true" /></p></div>}
              {running && liveEvents.length > 0 && <TraceView events={liveEvents} />}
              {runResult && <div className={`run-output ${runResult.error ? 'has-error' : ''}`}><strong>{runResult.error ? '运行失败' : '工作流输出'}</strong><p>{runResult.error || runResult.answer}</p>{runResult.voice?.type === 'audio' && <VoiceOutput request={runResult.voice} />}{runResult.events?.length > 0 && <TraceView events={runResult.events} />}</div>}
            </div>}
            {notice && <div className={`toast ${notice.startsWith('发现') || notice.startsWith('JSON 错误') ? 'warning' : ''}`}>{notice}</div>}
          </div>
          <div className="canvas-status"><div className="status-left"><span className={`status-light ${issues.length ? 'warn' : 'ok'}`} />{issues.length ? `${issues.length} 项待检查` : '接口连接正常'}<span className="status-sep">|</span><span>自动布局关闭</span></div><button onClick={runValidation}><Check size={13} />验证图结构</button></div>
        </section>

        <Inspector node={selectedNode} edges={edges} language={interfaceLanguage} modelOptions={modelOptions} ttsModels={ttsModels} promptFiles={promptFiles} reasoningAvailable={supportsReasoningForNode(selectedNode, nodes, edges, modelOptions)} onOpenConfig={(kind, modelId) => { setConfigModelId(modelId || ''); setConfigKind(kind); }} onChange={updateNode} onDelete={deleteNode} />
      </main>

      <footer className="app-footer"><span>ATRI · LOCAL WORKSPACE</span><span className="execution-note"><span className="note-dot" />试运行调用当前 Agent · 应用后在对话页使用</span></footer>

      {jsonOpen && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setJsonOpen(false); }}><section className="json-modal"><header><div><span className="eyebrow">WORKFLOW DOCUMENT</span><h2>工作流 JSON</h2></div><button className="icon-button" onClick={() => setJsonOpen(false)} title="关闭"><X size={17} /></button></header><textarea spellCheck="false" value={jsonText} onChange={(event) => { setJsonText(event.target.value); setJsonCopied(false); }} /><div className="modal-footer"><span>版本 2 · 节点 {nodes.length} · 连接 {edges.length}</span><div><button className="secondary-button" onClick={copyJson}>{jsonCopied ? <Check size={14} /> : <Copy size={14} />}{jsonCopied ? '已复制' : '复制'}</button><button className="primary-button" onClick={applyJson}><Check size={14} />应用到画布</button></div></div></section></div>}
      {saveDialog && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) setSaveDialog(null); }}><form className="workflow-save-modal" onSubmit={submitSaveDialog} role="dialog" aria-label={saveDialog.mode === 'new' ? '保存新工作流' : '重命名工作流'}><header><h2>{saveDialog.mode === 'new' ? '保存新工作流' : '重命名工作流'}</h2><button type="button" className="icon-button" onClick={() => setSaveDialog(null)} disabled={saving} title="关闭"><X size={17} /></button></header><label>显示名称<input autoFocus value={saveDialog.name} onChange={(event) => setSaveDialog((current) => ({ ...current, name: event.target.value }))} placeholder="工作流名称" /></label><label>文件名<input value={saveDialog.id} onChange={(event) => setSaveDialog((current) => ({ ...current, id: event.target.value }))} placeholder="my_workflow" spellCheck="false" /><small>保存在 workflows/ 目录，自动添加 .json</small></label><footer><button type="button" className="secondary-button" onClick={() => setSaveDialog(null)} disabled={saving}>取消</button><button type="submit" className="primary-button" disabled={saving}><Save size={15} />{saving ? '保存中' : '保存'}</button></footer></form></div>}
      {configKind === 'api-models' && <ApiModelPanel initialModelId={configModelId} onClose={() => setConfigKind(null)} onChanged={() => { refreshModelOptions(); setPreviewRevision((value) => value + 1); }} />}
      {configKind && configKind !== 'api-models' && <CapabilityPanel kind={configKind} onClose={() => setConfigKind(null)} onChanged={() => setPreviewRevision((value) => value + 1)} />}
    </div>
  );
}

function EditorFrame(props) {
  return <WorkflowEditor {...props} />;
}

function isLegacyDefault(document) {
  return document?.id === 'atri_companion_graph' && !document.nodes?.some((node) => node.type === 'llm.chat');
}

export default function WorkflowApp() {
  const [workspaceState, setWorkspaceState] = useState(null);
  useEffect(() => {
    Promise.all([
      fetch('/api/nodes').then((response) => response.ok ? response.json() : Promise.reject()).catch(() => null),
      fetch('/api/workflows').then((response) => response.ok ? response.json() : Promise.reject()).catch(() => null),
    ]).then(([nodePayload, workflowPayload]) => {
      if (Array.isArray(nodePayload?.nodes) && nodePayload.nodes.length) hydrateNodeCatalog(nodePayload.nodes);
      const available = workflowPayload?.workflows || [];
      const openInitial = (document) => setWorkspaceState({ tabs: [{ id: document.id, document, savedDocument: document, persisted: true }], activeId: document.id, available });
      try {
        const previous = JSON.parse(localStorage.getItem('atri.open.workflow.tabs') || 'null');
        const tabs = previous?.ids?.map((id) => available.find((item) => item.id === id)).filter(Boolean).map((item) => ({ id: item.id, document: item.document, savedDocument: item.document, persisted: true }));
        if (tabs?.length) {
          setWorkspaceState({ tabs, activeId: tabs.some((tab) => tab.id === previous.activeId) ? previous.activeId : tabs[0].id, available });
          return;
        }
      } catch { /* Fall back to the newest workflow on disk. */ }
      const diskWorkflow = available[0]?.document;
      if (diskWorkflow) {
        openInitial(diskWorkflow);
        return;
      }
      try {
        const saved = JSON.parse(localStorage.getItem('atri.workflow.v2') || 'null');
        if (saved && !isLegacyDefault(saved)) { openInitial(saved); return; }
      } catch { /* Fall back to the bundled graph when no local workflow is readable. */ }
      fetch('/companion_graph.json').then((response) => response.json()).then(openInitial);
    });
  }, []);
  useEffect(() => {
    if (!workspaceState) return;
    try { localStorage.setItem('atri.open.workflow.tabs', JSON.stringify({ ids: workspaceState.tabs.map((tab) => tab.id), activeId: workspaceState.activeId })); } catch { /* Tab restoration is optional. */ }
  }, [workspaceState?.tabs, workspaceState?.activeId]);
  const rememberActive = (tabs, activeId, snapshot) => tabs.map((tab) => tab.id === activeId ? { ...tab, document: snapshot } : tab);
  const switchWorkflow = (id, snapshot) => setWorkspaceState((current) => current && current.tabs.some((tab) => tab.id === id)
    ? { ...current, tabs: rememberActive(current.tabs, current.activeId, snapshot), activeId: id }
    : current);
  const openDocument = (document, snapshot, persisted = false) => setWorkspaceState((current) => {
    if (!current) return current;
    const tabs = rememberActive(current.tabs, current.activeId, snapshot);
    if (!tabs.some((tab) => tab.id === document.id)) tabs.push({ id: document.id, document, savedDocument: document, persisted });
    return { ...current, tabs, activeId: document.id };
  });
  const closeWorkflow = (id, snapshot) => {
    const tab = workspaceState?.tabs.find((item) => item.id === id);
    if (!tab || workspaceState.tabs.length < 2) return;
    const document = id === workspaceState.activeId ? snapshot : tab.document;
    const comparable = (value) => {
      const graph = fromDocument(value);
      const { viewport, ...persisted } = toDocument(value, graph.nodes, graph.edges);
      return JSON.stringify(persisted);
    };
    if ((!tab.persisted || comparable(document) !== comparable(tab.savedDocument)) && !window.confirm(`关闭“${document.name}”？未保存的修改会丢失。`)) return;
    setWorkspaceState((current) => {
      const tabs = rememberActive(current.tabs, current.activeId, snapshot).filter((item) => item.id !== id);
      return { ...current, tabs, activeId: current.activeId === id ? tabs[Math.max(0, current.tabs.findIndex((item) => item.id === id) - 1)].id : current.activeId };
    });
  };
  const refreshWorkflows = async () => {
    const response = await fetch('/api/workflows');
    if (!response.ok) throw new Error('无法读取工作流文件夹');
    const payload = await response.json();
    setWorkspaceState((current) => current ? { ...current, available: payload.workflows || [] } : current);
  };
  const savedWorkflow = (document, previousId) => setWorkspaceState((current) => current ? {
    ...current,
    activeId: document.id,
    tabs: current.tabs.map((tab) => tab.id === current.activeId ? { ...tab, id: document.id, document, savedDocument: document, persisted: true } : tab),
    available: current.available.filter((item) => item.id !== previousId && item.id !== document.id).concat({ id: document.id, name: document.name, document }),
  } : current);
  if (!workspaceState) return <div className="loading-screen">ATRI WORKFLOW STUDIO</div>;
  const activeTab = workspaceState.tabs.find((tab) => tab.id === workspaceState.activeId);
  return <ReactFlowProvider key={activeTab.id}><EditorFrame initialDocument={activeTab.document} savedDocument={activeTab.savedDocument} persisted={activeTab.persisted} openTabs={workspaceState.tabs} availableWorkflows={workspaceState.available} onRefreshWorkflows={refreshWorkflows} onOpenDocument={openDocument} onSwitchWorkflow={switchWorkflow} onCloseWorkflow={closeWorkflow} onSaved={savedWorkflow} /></ReactFlowProvider>;
}

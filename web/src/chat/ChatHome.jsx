import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Activity, AlertCircle, AlertTriangle, ArrowUp, Bot, Check, ChevronDown, ChevronRight, FileClock, Folder, FolderUp, Image as ImageIcon, MessageSquarePlus, Minimize2, PanelLeftClose, Pencil, Plus, RotateCcw, Save, Settings2, Shield, Trash2, Upload, Workflow, X, Zap } from 'lucide-react';
import { ThemePicker } from '../theme.jsx';
import { modelChoices } from '../workflow/catalog';
import TraceView from '../workflow/TraceView';
import { useInterfaceLanguage } from '../workflow/interfaceLanguage';
import { runWorkflowRequest } from '../workflow/runApi';
import VoiceOutput from '../workflow/VoiceOutput';
import { createStreamingTtsSession, getSpeakableCharacterCount, LONG_REPLY_SPEECH, MAX_SPOKEN_CHARACTERS, primeAudioPlayback, splitSpeakableText } from '../workflow/streamingTts';
import { getChatActivity, getRecentActions } from './activityStatus';
import { createAvatarImage, readAvatarPreferences, removeAvatarPreference, saveAvatarPreference } from './avatarPreferences';
import SandboxPermissionMatrix, { permissionsForSandboxMode, updateSandboxPermission } from './SandboxPermissionMatrix';

const CHAT_STORAGE_KEY = 'atri.chat.sessions.v1';
const ACTIVE_CHAT_STORAGE_KEY = 'atri.chat.active.v1';
const CONTEXT_COMPRESSION_STORAGE_KEY = 'atri.chat.context-compression.v1';
const DEFAULT_CONTEXT_COMPRESSION = { enabled: true, keep_recent_turns: 6, threshold_percent: 75 };
function getVoiceRequest(workflow) {
  const nodes = workflow?.nodes || [];
  const output = nodes.find((node) => node.type === 'core.chat_output');
  if (!output) return null;
  const edge = (workflow?.edges || []).find((item) => item.target === output.id && item.targetHandle === 'voice');
  const ttsNode = nodes.find((node) => node.id === edge?.source && node.type === 'audio.tts_model');
  if (!ttsNode) return null;
  return {
    endpoint: '/api/tts/speech',
    model: ttsNode.data?.config?.model || 'qwen3-0.6b-q8',
    language: ttsNode.data?.config?.language || 'Chinese',
    reference: ttsNode.data?.config?.reference || 'atri',
  };
}
const STATIC_GREETING_MESSAGES = new Set([
  '早上好。我是 ATRI。今天有什么想聊的？',
  '新对话已开始。你想从哪里聊起？',
]);

const starter = {
  workflow_version: 2,
  id: 'atri_companion_graph',
  name: '陪伴型 Agent',
  nodes: [],
  edges: [],
  metadata: { executable: true },
};

const isLegacyDefault = (document) => document?.id === 'atri_companion_graph' && !document.nodes?.some((node) => node.type === 'llm.chat');

function createSession() {
  return {
    id: `chat_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    title: '新的对话',
    messages: [],
    updatedAt: Date.now(),
  };
}

function readContextCompressionSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONTEXT_COMPRESSION_STORAGE_KEY) || 'null');
    return {
      enabled: typeof saved?.enabled === 'boolean' ? saved.enabled : DEFAULT_CONTEXT_COMPRESSION.enabled,
      keep_recent_turns: Number.isInteger(saved?.keep_recent_turns) ? Math.min(30, Math.max(1, saved.keep_recent_turns)) : DEFAULT_CONTEXT_COMPRESSION.keep_recent_turns,
      threshold_percent: [50, 60, 70, 75, 80, 85, 90, 95].includes(saved?.threshold_percent) ? saved.threshold_percent : DEFAULT_CONTEXT_COMPRESSION.threshold_percent,
    };
  } catch {
    return DEFAULT_CONTEXT_COMPRESSION;
  }
}

function readChatState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) || 'null');
    const sessions = Array.isArray(parsed)
      ? parsed.filter((session) => session && typeof session.id === 'string' && Array.isArray(session.messages))
        .map((session) => {
          const conversationMessages = session.messages.filter((message) =>
            !message?.error && typeof message?.content === 'string' && ['user', 'assistant'].includes(message.role)
          );
          const savedOffset = Math.max(0, Number(session.contextMessageOffset) || 0);
          const removedFromSummary = conversationMessages.slice(0, savedOffset).filter((message) =>
            message.role === 'assistant' && STATIC_GREETING_MESSAGES.has(message.content)
          ).length;
          return {
            ...session,
            contextMessageOffset: Math.max(0, savedOffset - removedFromSummary),
            messages: session.messages.filter((message) => !(
              message?.role === 'assistant' && STATIC_GREETING_MESSAGES.has(message.content)
            )),
          };
        })
      : [];
    const usable = sessions.length ? sessions : [createSession()];
    const savedActiveId = localStorage.getItem(ACTIVE_CHAT_STORAGE_KEY);
    return {
      sessions: usable,
      activeSessionId: usable.some((session) => session.id === savedActiveId) ? savedActiveId : usable[0].id,
    };
  } catch {
    const session = createSession();
    return { sessions: [session], activeSessionId: session.id };
  }
}

function eventTime(event) {
  const time = Date.parse(event?.timestamp);
  return Number.isFinite(time) ? time : null;
}

function tokenCount(usage, primary, alternative) {
  const value = usage?.[primary] ?? usage?.[alternative];
  const count = Number(value);
  return value !== null && value !== undefined && value !== '' && Number.isFinite(count) && count >= 0 ? count : null;
}

function latestPromptTokenCount(events) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.event_type !== 'model_response' && event.event_type !== 'llm_completed') continue;
    const count = tokenCount(event.data?.usage, 'prompt_tokens', 'input_tokens');
    if (count !== null) return count;
  }
  return null;
}

function traceMetrics(events, durationMs) {
  let inputTokens = 0;
  let outputTokens = 0;
  let hasInput = false;
  let hasOutput = false;
  let modelDurationMs = 0;
  const requests = new Map();

  for (const event of events) {
    const type = event.event_type;
    const key = event.node_id || 'model';
    if (type === 'model_request' || type === 'model_thinking') {
      requests.set(key, eventTime(event));
      continue;
    }
    if (type !== 'model_response' && type !== 'llm_completed') continue;
    const usage = event.data?.usage;
    const input = tokenCount(usage, 'prompt_tokens', 'input_tokens');
    const output = tokenCount(usage, 'completion_tokens', 'output_tokens');
    if (input !== null) { inputTokens += input; hasInput = true; }
    if (output !== null) { outputTokens += output; hasOutput = true; }
    const started = requests.get(key);
    const finished = eventTime(event);
    if (output !== null && started !== null && started !== undefined && finished !== null && finished > started) {
      modelDurationMs += finished - started;
    }
    requests.delete(key);
  }

  const first = eventTime(events[0]);
  const last = eventTime(events[events.length - 1]);
  return {
    inputTokens: hasInput ? inputTokens : null,
    outputTokens: hasOutput ? outputTokens : null,
    outputSpeed: hasOutput && modelDurationMs > 0 ? outputTokens / (modelDurationMs / 1000) : null,
    durationMs: Number.isFinite(durationMs) ? durationMs : first !== null && last !== null && last >= first ? last - first : null,
  };
}

function formatDuration(durationMs) {
  if (durationMs === null) return '—';
  const seconds = durationMs / 1000;
  return seconds < 60 ? `${seconds.toFixed(1)} s` : `${Math.floor(seconds / 60)}m ${(seconds % 60).toFixed(1)}s`;
}

function formatMessageTime(sentAt, language) {
  if (!Number.isFinite(sentAt)) return null;
  const time = new Date(sentAt);
  const today = new Date();
  const sameDay = time.toDateString() === today.toDateString();
  const locale = language === 'en' ? 'en-US' : 'zh-CN';
  return {
    short: new Intl.DateTimeFormat(locale, { ...(sameDay ? {} : { year: 'numeric', month: '2-digit', day: '2-digit' }), hour: '2-digit', minute: '2-digit' }).format(time),
    full: new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'medium' }).format(time),
  };
}

function MessageTime({ message, language }) {
  const time = formatMessageTime(message.sentAt, language);
  return <div className="message-meta" title={time?.full || undefined}>
    <span>{message.role === 'assistant' ? 'ATRI' : language === 'en' ? 'You' : '你'}</span>
    <time dateTime={time ? new Date(message.sentAt).toISOString() : undefined}>
      {time?.short || (language === 'en' ? 'Time not recorded' : '时间未记录')}
    </time>
  </div>;
}

function MessageTrace({ events, mode, language, durationMs }) {
  const [open, setOpen] = useState(mode === 'transparent');
  useEffect(() => setOpen(mode === 'transparent'), [mode]);
  const metrics = traceMetrics(events, durationMs);
  const number = (value) => value === null ? '—' : value.toLocaleString();
  const speed = metrics.outputSpeed === null ? '—' : `${metrics.outputSpeed.toFixed(1)} token/s`;
  const labels = language === 'en' ? ['Input tokens', 'Output tokens', 'Output speed', 'Total time'] : ['输入 token', '输出 token', '输出速度', '总耗时'];
  return <div className="trace-details">
    <div className="trace-details-heading">
      <button type="button" className="trace-details-toggle" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <Activity size={14} />{language === 'en' ? 'Execution trace' : '执行轨迹'}
        <span>{events.length} {language === 'en' ? 'steps' : '步'}</span>
        <ChevronDown size={14} className={open ? 'is-open' : ''} />
      </button>
      <div className="trace-metrics" aria-label={language === 'en' ? 'Run metrics' : '运行统计'}>
        <span>{labels[0]} <strong>{number(metrics.inputTokens)}</strong></span>
        <span>{labels[1]} <strong>{number(metrics.outputTokens)}</strong></span>
        <span>{labels[2]} <strong>{speed}</strong></span>
        <span>{labels[3]} <strong>{formatDuration(metrics.durationMs)}</strong></span>
      </div>
    </div>
    <div className={`motion-collapse ${open ? 'is-open' : ''}`} inert={!open ? '' : undefined}>
      <div><TraceView events={events} /></div>
    </div>
  </div>;
}

export default function ChatHome({ onNavigate, active = true }) {
  const [interfaceLanguage] = useInterfaceLanguage();
  const [workflow, setWorkflow] = useState(null);
  const [runtimeStatus, setRuntimeStatus] = useState({ loading: true, running: false, workflow_id: null });
  const [chatState, setChatState] = useState(readChatState);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState('normal');
  const [reasoningEffort, setReasoningEffort] = useState('workflow');
  const [modelCatalog, setModelCatalog] = useState(modelChoices);
  const [busy, setBusy] = useState(false);
  const [busySessionId, setBusySessionId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [liveDraft, setLiveDraft] = useState('');
  const liveEventsRef = useRef([]);
  const threadRef = useRef(null);
  const contextRingRef = useRef(null);
  const contextPopoverRef = useRef(null);
  const sandboxPermissionTriggerRef = useRef(null);
  const sandboxPermissionPopoverRef = useRef(null);
  const followThreadRef = useRef(true);
  const [contextPopoverOpen, setContextPopoverOpen] = useState(false);
  const [sandboxPermissionOpen, setSandboxPermissionOpen] = useState(false);
  const [sandboxSettings, setSandboxSettings] = useState({
    workspace: '',
    permission: 'workspace',
    permissions: permissionsForSandboxMode('workspace'),
  });
  const [sandboxRuntime, setSandboxRuntime] = useState(null);
  const [sandboxPermissionBusy, setSandboxPermissionBusy] = useState(false);
  const [sandboxPermissionError, setSandboxPermissionError] = useState('');
  const [sandboxPermissionSaved, setSandboxPermissionSaved] = useState(true);
  const [sandboxPermissionPosition, setSandboxPermissionPosition] = useState({ left: 0, top: 0 });
  const [sandboxBrowseOpen, setSandboxBrowseOpen] = useState(false);
  const [sandboxBrowsePath, setSandboxBrowsePath] = useState('');
  const [sandboxBrowsePathDraft, setSandboxBrowsePathDraft] = useState('');
  const [sandboxBrowseParent, setSandboxBrowseParent] = useState(null);
  const [sandboxDirectories, setSandboxDirectories] = useState([]);
  const [sandboxBrowseBusy, setSandboxBrowseBusy] = useState(false);
  const [sandboxBrowseError, setSandboxBrowseError] = useState('');
  const [contextSettingsOpen, setContextSettingsOpen] = useState(false);
  const [contextCompression, setContextCompression] = useState(readContextCompressionSettings);
  const [contextCompressing, setContextCompressing] = useState(false);
  const [contextCompressionFeedback, setContextCompressionFeedback] = useState(null);
  const [contextPopoverPosition, setContextPopoverPosition] = useState({ left: 0, top: 0 });
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [pendingDeleteSessionId, setPendingDeleteSessionId] = useState(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileText, setProfileText] = useState('');
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileLoaded, setProfileLoaded] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [profileSaved, setProfileSaved] = useState(false);
  const [avatars, setAvatars] = useState(readAvatarPreferences);
  const [avatarPickerOpen, setAvatarPickerOpen] = useState(false);
  const [avatarError, setAvatarError] = useState('');
  const userAvatarInputRef = useRef(null);
  const agentAvatarInputRef = useRef(null);
  const { sessions, activeSessionId } = chatState;
  const activeSession = sessions.find((session) => session.id === activeSessionId) || sessions[0];
  const messages = activeSession?.messages || [];
  const recentActions = getRecentActions(liveEvents, interfaceLanguage);

  useEffect(() => {
    const thread = threadRef.current;
    if (thread && followThreadRef.current) thread.scrollTop = thread.scrollHeight;
  }, [activeSessionId, messages.length, busy, liveEvents.length, liveDraft]);

  useEffect(() => {
    try {
      const savedSessions = sessions.map((session) => ({
        ...session,
        messages: session.messages.map(({ voice, voiceBlob, voiceError, ...message }) => message),
      }));
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(savedSessions));
      localStorage.setItem(ACTIVE_CHAT_STORAGE_KEY, activeSessionId);
    } catch {
      // The conversation remains usable when browser storage is unavailable.
    }
  }, [sessions, activeSessionId]);

  useEffect(() => {
    try { localStorage.setItem(CONTEXT_COMPRESSION_STORAGE_KEY, JSON.stringify(contextCompression)); }
    catch { /* Keep this control usable when browser storage is unavailable. */ }
  }, [contextCompression]);

  useEffect(() => {
    let disposed = false;
    fetch('/api/sandbox/settings')
      .then((response) => response.ok ? response.json() : response.json().then((result) => Promise.reject(new Error(result.error || '读取沙箱设置失败'))))
      .then((result) => {
        if (disposed) return;
        setSandboxSettings(result.settings);
        setSandboxRuntime(result.runtime);
        setSandboxPermissionError('');
      })
      .catch((error) => { if (!disposed) setSandboxPermissionError(error.message); });
    return () => { disposed = true; };
  }, []);

  useEffect(() => {
    const syncSettings = (event) => {
      if (!event.detail?.settings) return;
      setSandboxSettings(event.detail.settings);
      if (event.detail.runtime) setSandboxRuntime(event.detail.runtime);
      setSandboxPermissionSaved(true);
      setSandboxPermissionError('');
    };
    window.addEventListener('atri-sandbox-settings', syncSettings);
    return () => window.removeEventListener('atri-sandbox-settings', syncSettings);
  }, []);

  useEffect(() => {
    if (!active) return undefined;
    const handleShortcut = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        clearConversation();
      }
    };
    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
  }, [active]);

  useEffect(() => {
    let disposed = false;
    const refresh = () => fetch('/api/status')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('无法读取运行状态')))
      .then((status) => {
        const active = localStorage.getItem('atri.active.workflow.v2');
        let activeId = null;
        try { activeId = active ? JSON.parse(active).id : null; } catch { localStorage.removeItem('atri.active.workflow.v2'); }
        if (!disposed) setRuntimeStatus({ ...status, running: Boolean(status.running && activeId === status.workflow_id), loading: false });
      })
      .catch(() => { if (!disposed) setRuntimeStatus({ loading: false, running: false, workflow_id: null }); });
    refresh();
    const timer = window.setInterval(refresh, 2500);
    const onStatusChange = () => refresh();
    window.addEventListener('atri-runtime-status', onStatusChange);
    return () => { disposed = true; window.clearInterval(timer); window.removeEventListener('atri-runtime-status', onStatusChange); };
  }, []);

  useEffect(() => {
    let disposed = false;
    fetch('/api/models')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('模型目录不可用')))
      .then((payload) => {
        if (!disposed && Array.isArray(payload.models) && payload.models.length) {
          setModelCatalog(payload.models.map((model) => ({ ...model, value: model.id })));
        }
      })
      .catch(() => { /* Keep the built-in labels available while the API is offline. */ });
    return () => { disposed = true; };
  }, []);

  useEffect(() => {
    const load = (preferApplied = false) => {
      const active = localStorage.getItem('atri.active.workflow.v2');
      if (preferApplied && active) {
        try {
          const parsed = JSON.parse(active);
          if (!isLegacyDefault(parsed)) { setWorkflow(parsed); return; }
          localStorage.removeItem('atri.active.workflow.v2');
        } catch { localStorage.removeItem('atri.active.workflow.v2'); }
      }
      fetch('/api/workflows')
        .then((response) => response.ok ? response.json() : Promise.reject())
        .then((payload) => {
          const savedWorkflow = payload.workflows?.[0]?.document;
          if (savedWorkflow) { setWorkflow(savedWorkflow); return; }
          if (active) {
            try { setWorkflow(JSON.parse(active)); return; } catch { /* Use the bundled workflow below. */ }
          }
          return fetch('/companion_graph.json').then((response) => response.json()).then(setWorkflow);
        })
        .catch(() => {
          if (active) {
            try { setWorkflow(JSON.parse(active)); return; } catch { /* Use the bundled workflow below. */ }
          }
          fetch('/companion_graph.json').then((response) => response.json()).then(setWorkflow).catch(() => setWorkflow(starter));
        });
    };
    load(true);
    const handleApplied = () => load(true);
    window.addEventListener('atri-workflow-applied', handleApplied);
    return () => window.removeEventListener('atri-workflow-applied', handleApplied);
  }, []);

  const activeModel = useMemo(() => {
    const runtime = workflow?.nodes?.find((item) => ['llm.chat', 'agent.react_runtime'].includes(item.type));
    const modelEdge = workflow?.edges?.find((edge) => edge.target === runtime?.id && edge.targetHandle === 'llm');
    const node = workflow?.nodes?.find((item) => item.id === modelEdge?.source);
    const modelId = node?.data?.config?.model;
    const direct = workflow?.nodes?.length === 2
      && workflow.nodes.some((item) => item.type === 'core.chat_input')
      && workflow.nodes.some((item) => item.type === 'core.chat_output')
      && workflow.edges?.length === 1;
    const choice = modelCatalog.find((option) => option.value === modelId);
    const rawContextWindow = node?.data?.config?.n_ctx ?? choice?.input_token_limit;
    const parsedContextWindow = Number(rawContextWindow);
    return {
      label: choice?.label || modelId || (direct ? '无模型直通' : '未选择模型'),
      hasModel: Boolean(node),
      supportsReasoning: node?.type === 'llm.openai_loader' || (node?.type === 'llm.provider' && choice?.type === 'api'),
      contextWindow: Number.isFinite(parsedContextWindow) && parsedContextWindow > 0 ? parsedContextWindow : null,
    };
  }, [workflow, modelCatalog]);

  const contextTokens = useMemo(() => {
    if (busy && busySessionId === activeSessionId) {
      const liveCount = latestPromptTokenCount(liveEvents);
      if (liveCount !== null) return liveCount;
    }
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role !== 'assistant') continue;
      const count = latestPromptTokenCount(message.events || []);
      if (count !== null) return count;
    }
    return null;
  }, [activeSessionId, busy, busySessionId, liveEvents, messages]);

  useLayoutEffect(() => {
    if (!contextPopoverOpen) return undefined;
    const updatePosition = () => {
      const anchor = contextRingRef.current?.getBoundingClientRect();
      const popover = contextPopoverRef.current?.getBoundingClientRect();
      if (!anchor || !popover) return;
      const gap = 8;
      const left = Math.max(8, Math.min(
        anchor.left + (anchor.width - popover.width) / 2,
        window.innerWidth - popover.width - 8,
      ));
      const top = Math.max(8, anchor.top - popover.height - gap);
      setContextPopoverPosition((current) => current.left === left && current.top === top ? current : { left, top });
    };
    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [contextPopoverOpen, contextSettingsOpen, contextTokens, activeModel.contextWindow, contextCompressing, contextCompressionFeedback]);

  useLayoutEffect(() => {
    if (!sandboxPermissionOpen) return undefined;
    const updatePosition = () => {
      const anchor = sandboxPermissionTriggerRef.current?.getBoundingClientRect();
      const popover = sandboxPermissionPopoverRef.current?.getBoundingClientRect();
      if (!anchor || !popover) return;
      const left = Math.max(8, Math.min(anchor.left + anchor.width / 2 - popover.width / 2, window.innerWidth - popover.width - 8));
      const top = Math.max(8, anchor.top - popover.height - 8);
      setSandboxPermissionPosition((current) => current.left === left && current.top === top ? current : { left, top });
    };
    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [sandboxPermissionOpen, sandboxSettings.permission, sandboxPermissionError, sandboxRuntime, sandboxBrowseOpen, sandboxBrowsePath, sandboxDirectories.length, sandboxBrowseBusy, sandboxBrowseError]);

  useEffect(() => {
    if (!contextPopoverOpen) setContextSettingsOpen(false);
  }, [contextPopoverOpen]);

  useEffect(() => {
    if (!contextPopoverOpen) return undefined;
    const closeOnOutsidePointer = (event) => {
      if (contextRingRef.current?.contains(event.target) || contextPopoverRef.current?.contains(event.target)) return;
      setContextPopoverOpen(false);
    };
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setContextPopoverOpen(false);
    };
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [contextPopoverOpen]);

  useEffect(() => {
    if (!sandboxPermissionOpen) return undefined;
    const closeOnOutsidePointer = (event) => {
      if (sandboxPermissionTriggerRef.current?.contains(event.target) || sandboxPermissionPopoverRef.current?.contains(event.target)) return;
      setSandboxPermissionOpen(false);
    };
    const closeOnEscape = (event) => { if (event.key === 'Escape') setSandboxPermissionOpen(false); };
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [sandboxPermissionOpen]);

  const appendMessage = (sessionId, message, title, contextUpdate) => {
    setChatState((current) => ({
      ...current,
      sessions: current.sessions.map((session) => session.id === sessionId
        ? {
          ...session,
          title: title && session.title === '新的对话' ? title.slice(0, 28) : session.title,
          messages: [...session.messages, message],
          ...(contextUpdate ? {
            contextSummary: typeof contextUpdate.context_summary === 'string' ? contextUpdate.context_summary : session.contextSummary || '',
            contextMessageOffset: (Number.isInteger(session.contextMessageOffset) ? session.contextMessageOffset : 0)
              + (Number.isInteger(contextUpdate.compressed_history_messages) ? contextUpdate.compressed_history_messages : 0),
          } : {}),
          updatedAt: Date.now(),
        }
        : session),
    }));
  };

  const compressContext = async () => {
    const session = activeSession;
    if (contextCompressing || busy || !session || !workflow || !runtimeStatus.running) return;
    const fullHistory = session.messages
      .filter((message) => !message.error && typeof message.content === 'string' && ['user', 'assistant'].includes(message.role))
      .map(({ role, content }) => ({ role, content }));
    const historyOffset = Math.min(fullHistory.length, Math.max(0, Number(session.contextMessageOffset) || 0));
    setContextCompressing(true);
    setContextCompressionFeedback(null);
    try {
      const response = await fetch('/api/context/compress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflow,
          history: fullHistory.slice(historyOffset),
          history_summary: session.contextSummary || '',
          keep_recent_turns: contextCompression.keep_recent_turns,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '压缩上下文失败');
      const compressedMessages = Number.isInteger(result.compressed_history_messages) ? result.compressed_history_messages : 0;
      if (compressedMessages > 0) {
        setChatState((current) => ({
          ...current,
          sessions: current.sessions.map((item) => item.id === session.id ? {
            ...item,
            contextSummary: result.context_summary || item.contextSummary || '',
            contextMessageOffset: (Number.isInteger(item.contextMessageOffset) ? item.contextMessageOffset : 0) + compressedMessages,
            updatedAt: Date.now(),
          } : item),
        }));
        setContextCompressionFeedback({ sessionId: session.id, type: 'success', text: `已压缩 ${compressedMessages} 条历史消息，保留最近 ${contextCompression.keep_recent_turns} 轮。` });
      } else {
        setContextCompressionFeedback({ sessionId: session.id, type: 'info', text: '当前没有可压缩的旧轮次。' });
      }
    } catch (error) {
      setContextCompressionFeedback({ sessionId: session.id, type: 'error', text: error.message || '压缩上下文失败' });
    } finally {
      setContextCompressing(false);
    }
  };

  const sendMessage = async () => {
    const text = input.trim();
    const sessionId = activeSession?.id;
    if (!text || busy || contextCompressing || !workflow || !sessionId) return;
    void primeAudioPlayback().catch(() => {});
    if (!runtimeStatus.running) {
      appendMessage(sessionId, { role: 'assistant', error: '工作流尚未启动，请先到工作流页点击“启动工作流”后再对话。', sentAt: Date.now() });
      return;
    }
    const sentAt = Date.now();
    const started = performance.now();
    setInput('');
    followThreadRef.current = true;
    appendMessage(sessionId, { role: 'user', content: text, sentAt }, text);
    setBusy(true);
    setBusySessionId(sessionId);
    setLiveEvents([]);
    setLiveDraft('');
    liveEventsRef.current = [];
    const voiceRequest = getVoiceRequest(workflow);
    let voiceAbort = new AbortController();
    let voiceSession = voiceRequest ? createStreamingTtsSession(voiceRequest, voiceAbort.signal) : null;
    let usingLongReplySpeech = false;
    let lastDraft = '';
    let pendingSpeechText = '';
    const useLongReplySpeech = () => {
      if (!voiceRequest || usingLongReplySpeech) return;
      usingLongReplySpeech = true;
      voiceAbort.abort();
      voiceSession?.stop();
      voiceAbort = new AbortController();
      voiceSession = createStreamingTtsSession(voiceRequest, voiceAbort.signal);
      pendingSpeechText = '';
      voiceSession.enqueue(LONG_REPLY_SPEECH);
    };
    const updateSpeechDraft = (draft) => {
      if (!voiceSession) return;
      if (getSpeakableCharacterCount(draft) > MAX_SPOKEN_CHARACTERS) {
        useLongReplySpeech();
        lastDraft = draft;
        return;
      }
      if (draft.startsWith(lastDraft)) {
        pendingSpeechText += draft.slice(lastDraft.length);
      } else {
        pendingSpeechText = draft;
      }
      lastDraft = draft;
      const { segments, remainder } = splitSpeakableText(pendingSpeechText);
      pendingSpeechText = remainder;
      segments.forEach((segment) => voiceSession.enqueue(segment));
    };
    try {
      const onProgress = (events, draft) => {
        if (events.length !== liveEventsRef.current.length) {
          liveEventsRef.current = events;
          setLiveEvents(events);
        }
        setLiveDraft(draft);
        updateSpeechDraft(draft);
      };
      const fullHistory = activeSession.messages
        .filter((message) => !message.error && typeof message.content === 'string' && ['user', 'assistant'].includes(message.role))
        .map(({ role, content }) => ({ role, content }));
      const historyOffset = Math.min(fullHistory.length, Math.max(0, Number(activeSession.contextMessageOffset) || 0));
      const history = fullHistory.slice(historyOffset);
      const result = await runWorkflowRequest({
        workflow,
        input: text,
        mode,
        require_started: true,
        history,
        history_summary: activeSession.contextSummary || '',
        context_compression: {
          ...contextCompression,
          context_window: activeModel.contextWindow,
          previous_input_tokens: contextTokens,
        },
        ...(activeModel.supportsReasoning && reasoningEffort !== 'workflow' ? { reasoning_effort: reasoningEffort } : {}),
      }, onProgress);
      if (!result.answer && result.error) throw new Error(result.error);
      let voiceBlob;
      let voiceError = '';
      if (voiceSession) {
        const answer = String(result.answer || '');
        if (!usingLongReplySpeech && getSpeakableCharacterCount(answer) > MAX_SPOKEN_CHARACTERS) {
          useLongReplySpeech();
        } else if (!usingLongReplySpeech) {
          pendingSpeechText = answer.startsWith(lastDraft) ? pendingSpeechText + answer.slice(lastDraft.length) : answer;
          lastDraft = answer;
          const { segments, remainder } = splitSpeakableText(pendingSpeechText, true);
          segments.forEach((segment) => voiceSession.enqueue(segment));
        }
        const voiceResult = await voiceSession.finish();
        voiceBlob = voiceResult.blob;
        voiceError = voiceResult.error?.message || '';
      }
      liveEventsRef.current = result.events || liveEventsRef.current;
      const voice = usingLongReplySpeech && voiceRequest
        ? { ...voiceRequest, text: LONG_REPLY_SPEECH }
        : result.voice || (voiceRequest ? { ...voiceRequest, text: result.answer } : undefined);
      appendMessage(sessionId, { role: 'assistant', content: result.answer, voice, voiceBlob, voiceError, events: result.events, sentAt: Date.now(), durationMs: performance.now() - started }, undefined, result);
    } catch (error) {
      voiceAbort.abort();
      voiceSession?.stop();
      appendMessage(sessionId, { role: 'assistant', error: error.message, events: liveEventsRef.current, sentAt: Date.now(), durationMs: performance.now() - started });
    } finally {
      setBusy(false);
      setBusySessionId(null);
      setLiveEvents(liveEventsRef.current);
      setLiveDraft('');
    }
  };

  const clearConversation = () => {
    const session = createSession();
    setChatState((current) => ({ sessions: [session, ...current.sessions], activeSessionId: session.id }));
  };

  const requestDeleteConversation = (event, sessionId) => {
    event.stopPropagation();
    setPendingDeleteSessionId(sessionId);
  };

  const deleteConversation = () => {
    const sessionId = pendingDeleteSessionId;
    if (!sessionId) return;
    setChatState((current) => {
      const remaining = current.sessions
        .filter((session) => session.id !== sessionId)
        .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
      if (!remaining.length) {
        const nextSession = createSession();
        remaining.push(nextSession);
      }
      return {
        sessions: remaining,
        activeSessionId: current.activeSessionId === sessionId ? remaining[0].id : current.activeSessionId,
      };
    });
    setPendingDeleteSessionId(null);
  };

  const openUserProfile = async () => {
    setProfileOpen(true);
    setProfileLoading(true);
    setProfileLoaded(false);
    setProfileError('');
    setProfileSaved(false);
    try {
      const response = await fetch('/api/user-profile');
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '读取用户信息失败');
      setProfileText(payload.content || '');
      setProfileLoaded(true);
    } catch (error) {
      setProfileError(error.message || '无法连接到本地 API');
    } finally {
      setProfileLoading(false);
    }
  };

  const saveUserProfile = async () => {
    if (!profileLoaded) return;
    setProfileSaving(true);
    setProfileError('');
    setProfileSaved(false);
    try {
      const response = await fetch('/api/user-profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: profileText }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '保存用户信息失败');
      setProfileSaved(true);
    } catch (error) {
      setProfileError(error.message || '无法连接到本地 API');
    } finally {
      setProfileSaving(false);
    }
  };

  const handleAvatarUpload = async (role, event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setAvatarError('');
    try {
      const image = await createAvatarImage(file);
      saveAvatarPreference(role, image);
      setAvatars((current) => ({ ...current, [role]: image }));
    } catch (error) {
      setAvatarError(error.message || '头像保存失败');
    }
  };

  const resetAvatar = (role) => {
    try {
      removeAvatarPreference(role);
      setAvatars((current) => ({ ...current, [role]: '' }));
      setAvatarError('');
    } catch {
      setAvatarError('无法重置头像，请检查浏览器存储空间');
    }
  };

  const loadSandboxDirectory = async (path) => {
    setSandboxBrowseBusy(true);
    setSandboxBrowseError('');
    try {
      const query = path ? `?path=${encodeURIComponent(path)}` : '';
      const response = await fetch(`/api/sandbox/directories${query}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '读取目录失败');
      setSandboxBrowsePath(result.path || '');
      setSandboxBrowsePathDraft(result.path || '');
      setSandboxBrowseParent(result.parent || null);
      setSandboxDirectories(result.directories || []);
    } catch (error) {
      setSandboxBrowseError(error.message || '读取目录失败');
    } finally {
      setSandboxBrowseBusy(false);
    }
  };

  const openSandboxDirectoryBrowser = () => {
    setSandboxBrowseOpen(true);
    void loadSandboxDirectory(sandboxSettings.workspace || undefined);
  };

  const goToSandboxDirectory = () => {
    const path = sandboxBrowsePathDraft.trim();
    if (!path) {
      setSandboxBrowseError('请输入目录路径');
      return;
    }
    void loadSandboxDirectory(path);
  };

  const useSandboxDirectory = () => {
    setSandboxSettings((current) => ({ ...current, workspace: sandboxBrowsePath }));
    setSandboxPermissionSaved(false);
    setSandboxPermissionError('');
    setSandboxBrowseOpen(false);
  };

  const saveSandboxPermissions = async () => {
    if (!sandboxRuntime?.filesystem_permissions_available) {
      setSandboxPermissionError('当前环境不支持安全执行沙箱命令，权限设置无法应用。');
      return;
    }
    setSandboxPermissionBusy(true);
    setSandboxPermissionError('');
    try {
      const response = await fetch('/api/sandbox/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sandboxSettings),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '保存沙箱权限失败');
      setSandboxSettings(result.settings);
      setSandboxRuntime(result.runtime);
      setSandboxPermissionSaved(true);
      setSandboxBrowseOpen(false);
      window.dispatchEvent(new CustomEvent('atri-sandbox-settings', { detail: { settings: result.settings, runtime: result.runtime } }));
    } catch (error) {
      setSandboxPermissionError(error.message);
    } finally {
      setSandboxPermissionBusy(false);
    }
  };

  const updateSandboxMode = (permission) => {
    setSandboxSettings((current) => ({
      ...current,
      permission,
      ...(permission === 'custom' ? {} : { permissions: permissionsForSandboxMode(permission) }),
    }));
    setSandboxPermissionError('');
    setSandboxPermissionSaved(false);
  };

  const updateSandboxAction = (scope, action, allowed) => {
    setSandboxSettings((current) => updateSandboxPermission(current, scope, action, allowed));
    setSandboxPermissionError('');
    setSandboxPermissionSaved(false);
  };

  const selectConversation = (sessionId) => {
    if (sessionId === activeSessionId) return;
    followThreadRef.current = true;
    setChatState((current) => ({ ...current, activeSessionId: sessionId }));
  };

  const recentSessions = sessions.filter((session) => session.messages.length > 0)
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  const pendingDeleteSession = sessions.find((session) => session.id === pendingDeleteSessionId);

  return (
    <div className={`chat-shell ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
      <aside className="chat-sidebar" aria-hidden={!sidebarOpen} inert={!sidebarOpen ? '' : undefined}>
        <div className="chat-brand"><div className="brand-mark">A</div><div><strong>ATRI <span>AGENT</span></strong><small>LOCAL WORKSPACE</small></div><button className="icon-button" title="收起侧栏" onClick={() => setSidebarOpen(false)}><PanelLeftClose size={15} /></button></div>
        <button className="new-chat-button" onClick={clearConversation}><MessageSquarePlus size={15} />新对话<span>Ctrl/⌘ K</span></button>
        <div className="sidebar-section-title">最近对话</div>
        {recentSessions.map((session, index) => <div className={`conversation-row ${session.id === activeSessionId ? 'active' : ''}`} key={session.id}>
          <button className={`conversation-item ${session.id === activeSessionId ? 'active' : ''}`} onClick={() => selectConversation(session.id)} title={session.title}>
            {index === 0 ? <MessageSquarePlus size={14} /> : <FileClock size={14} />}<span>{session.title || '新的对话'}</span>
          </button>
          <button className="conversation-delete" onClick={(event) => requestDeleteConversation(event, session.id)} title={`删除对话：${session.title || '新的对话'}`} aria-label={`删除对话：${session.title || '新的对话'}`}><Trash2 size={14} /></button>
        </div>)}
        <div className="sidebar-bottom">
          <button className="sidebar-workflow-link" onClick={() => onNavigate('workflow')}><Workflow size={16} /><span><strong>工作流编辑器</strong><small>调整 Agent 的底层逻辑</small></span><ChevronDown size={14} className="side-link-chevron" /></button>
          <button className="profile-row" onClick={openUserProfile} title="编辑 modules/prompt/SystemPrompt/USER.md"><div className="profile-avatar">{avatars.user ? <img src={avatars.user} alt="" /> : 'W'}</div><span><strong>编辑用户信息</strong><small>USER.md</small></span><Pencil size={15} /></button>
        </div>
      </aside>
      <main className="chat-main">
        <header className="chat-topbar">
          {!sidebarOpen && <button className="icon-button" onClick={() => setSidebarOpen(true)} title="展开侧栏"><PanelLeftClose size={15} /></button>}
          <div className="chat-agent-title"><button type="button" className="agent-status-icon" onClick={() => { setAvatarError(''); setAvatarPickerOpen(true); }} title="更换用户和 Agent 头像" aria-label="更换头像">{avatars.agent ? <img src={avatars.agent} alt="" /> : <Bot size={16} />}</button><div><strong>ATRI</strong><span>陪伴型 Agent</span></div></div>
          <div className="chat-top-spacer" />
          <ThemePicker />
          <div className="active-config" title={runtimeStatus.loading ? '检查工作流状态…' : runtimeStatus.running ? workflow?.name || '工作流已启动' : '工作流未启动'}><span className={`config-dot ${runtimeStatus.running ? '' : 'warn'}`} /><span>{runtimeStatus.loading ? '检查工作流状态…' : runtimeStatus.running ? workflow?.name || '工作流已启动' : '工作流未启动'}</span></div>
          <div className="mode-switch" role="group" aria-label="对话模式"><button className={mode === 'normal' ? 'selected' : ''} onClick={() => setMode('normal')}>正常</button><button className={mode === 'transparent' ? 'selected' : ''} onClick={() => setMode('transparent')}><Activity size={12} />透明</button></div>
          <button className="icon-button" title="新对话" onClick={clearConversation}><Plus size={16} /></button>
        </header>
        <section className="chat-thread" ref={threadRef} onScroll={(event) => {
          const thread = event.currentTarget;
          followThreadRef.current = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 100;
        }}>
          {messages.map((message, index) => <article className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
            {message.role === 'assistant' && <div className="message-avatar">{avatars.agent ? <img src={avatars.agent} alt="" /> : <Bot size={16} />}</div>}
            <div className={`message-content ${message.voice ? 'has-voice' : ''}`}>
              <MessageTime message={message} language={interfaceLanguage} />
              {message.error ? <div className="message-error">{message.error}</div> : message.voice ? <div className="message-bubble-row has-voice">
                <div className="message-bubble">{message.content}</div>
                <VoiceOutput request={message.voice} blob={message.voiceBlob} error={message.voiceError} autoGenerate={false} label="语音回复" />
              </div> : <div className="message-bubble">{message.content}</div>}
              {message.events?.length > 0 && <MessageTrace events={message.events} mode={mode} language={interfaceLanguage} durationMs={message.durationMs} />}
            </div>
            {message.role === 'user' && <div className="user-avatar">{avatars.user ? <img src={avatars.user} alt="" /> : 'W'}</div>}
          </article>)}
          {busy && busySessionId === activeSessionId && <div className="chat-message assistant">
            <div className="message-avatar">{avatars.agent ? <img src={avatars.agent} alt="" /> : <Bot size={16} />}</div>
            <div className="message-content">
              <div className="chat-live-panel">
                <div className="chat-live-status" role="status" aria-live="polite"><Activity size={15} aria-hidden="true" /><span className="chat-live-status-text">{liveDraft ? interfaceLanguage === 'en' ? 'Generating reply…' : '正在生成回复…' : getChatActivity(liveEvents, workflow, interfaceLanguage)}</span></div>
                {mode === 'normal' && recentActions.length > 0 && <div className="chat-live-actions">{recentActions.map((action) => <div key={action.id} className={action.failed ? 'is-error' : ''}>{action.failed ? <AlertCircle size={13} /> : <Check size={13} />}<span>{action.label}</span></div>)}</div>}
              </div>
              {liveDraft && <div className="message-bubble chat-stream-bubble">{liveDraft}<span className="stream-caret" aria-hidden="true" /></div>}
              {mode === 'transparent' && liveEvents.length > 0 && <TraceView events={liveEvents} />}
            </div>
          </div>}
        </section>
        <footer className="composer-area">
          <div className="composer-box">
            <textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } }} placeholder={runtimeStatus.running ? '给 ATRI 发消息…' : '请先在工作流页启动 Agent'} rows={1} />
            <div className="composer-tools">
              <span className="composer-model"><Zap size={13} />{activeModel.label}</span>
              {activeModel.hasModel && <label className={`composer-reasoning ${activeModel.supportsReasoning ? '' : 'is-unsupported'}`} title={activeModel.supportsReasoning ? '本次使用的思考强度' : '当前模型不支持思考强度'}>
                <select aria-label="思考强度" value={activeModel.supportsReasoning ? reasoningEffort : 'unsupported'} disabled={!activeModel.supportsReasoning} onChange={(event) => setReasoningEffort(event.target.value)}>
                  {activeModel.supportsReasoning ? <><option value="workflow">跟随</option><option value="auto">自动</option><option value="minimal">极低</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">极高</option></> : <option value="unsupported">不支持</option>}
                </select>
              </label>}
              {activeModel.hasModel && (() => {
                const contextRatio = contextTokens !== null && activeModel.contextWindow
                  ? Math.min(100, contextTokens / activeModel.contextWindow * 100)
                  : 0;
                return <span className="composer-context">
                  <button
                    ref={contextRingRef}
                    type="button"
                    className="context-ring-trigger"
                    aria-label="查看当前对话上下文"
                    aria-haspopup="dialog"
                    aria-expanded={contextPopoverOpen}
                    onClick={() => { setSandboxPermissionOpen(false); setContextSettingsOpen(false); setContextPopoverOpen((open) => !open); }}
                  ><span className="context-usage-ring" style={{ '--context-ratio': `${contextRatio}%` }} aria-hidden="true" /></button>
                </span>;
              })()}
              <button
                ref={sandboxPermissionTriggerRef}
                type="button"
                className={`composer-sandbox-trigger ${sandboxSettings.permission === 'full' ? 'is-full' : ''}`}
                aria-label={`沙箱权限：${sandboxSettings.permission === 'full' ? '全部权限' : sandboxSettings.permission === 'custom' ? '自定义权限' : '工作空间权限'}`}
                aria-haspopup="dialog"
                aria-expanded={sandboxPermissionOpen}
                title={sandboxSettings.permission === 'full' ? '全部权限：可修改工作空间外文件' : '调整沙箱执行权限'}
                onClick={() => { setContextPopoverOpen(false); setSandboxPermissionOpen((open) => !open); }}
              >{sandboxSettings.permission === 'full' ? <AlertTriangle size={15} /> : <Shield size={15} />}</button>
              <span className="composer-hint">Enter 发送 · Shift + Enter 换行</span>
              <button className="send-button" disabled={!input.trim() || busy || contextCompressing || runtimeStatus.loading || !runtimeStatus.running} onClick={sendMessage} title={runtimeStatus.running ? '发送消息' : '先启动工作流'}><ArrowUp size={17} /></button>
            </div>
          </div>
          <div className="composer-caption">ATRI 会根据当前激活的工作流配置运行。<button onClick={() => onNavigate('workflow')}>编辑工作流</button></div>
        </footer>
      </main>
      {contextPopoverOpen && createPortal(
        <div
          ref={contextPopoverRef}
          className="context-usage-popover"
          role="dialog"
          aria-label="当前对话上下文"
          style={{ left: `${contextPopoverPosition.left}px`, top: `${contextPopoverPosition.top}px` }}
        >
          <strong>当前对话上下文</strong>
          <span>{contextTokens === null ? '—' : contextTokens.toLocaleString()} / {activeModel.contextWindow === null ? '—' : activeModel.contextWindow.toLocaleString()}</span>
          <div className="context-compression-row">
            <button
              type="button"
              className="context-compress-now"
              onClick={compressContext}
              disabled={contextCompressing || busy || !runtimeStatus.running || !activeModel.hasModel}
              title={!runtimeStatus.running ? '请先启动当前工作流' : !activeModel.hasModel ? '当前工作流没有可用模型' : '立即压缩上下文'}
            >{contextCompressing ? <span className="spinner" /> : <Minimize2 size={13} aria-hidden="true" />}{contextCompressing ? '正在压缩' : '压缩上下文'}</button>
            <span className="context-compression-options">
              <button
                type="button"
                className={`context-auto-toggle ${contextCompression.enabled ? 'is-enabled' : ''}`}
                aria-pressed={contextCompression.enabled}
                onClick={() => setContextCompression((current) => ({ ...current, enabled: !current.enabled }))}
              >Auto</button>
              <button
                type="button"
                className={`context-settings-trigger ${contextSettingsOpen ? 'is-open' : ''}`}
                aria-label="上下文压缩设置"
                aria-expanded={contextSettingsOpen}
                title="上下文压缩设置"
                onClick={() => setContextSettingsOpen((open) => !open)}
              ><Settings2 size={14} aria-hidden="true" /></button>
            </span>
          </div>
          {contextSettingsOpen && <div className="context-compression-settings">
            <label><span>保留最近轮数</span><input type="number" min="1" max="30" value={contextCompression.keep_recent_turns} onChange={(event) => {
              const value = Number(event.target.value);
              setContextCompression((current) => ({ ...current, keep_recent_turns: Math.min(30, Math.max(1, Number.isFinite(value) ? value : 1)) }));
            }} /></label>
            <label><span>压缩阈值</span><select value={contextCompression.threshold_percent} onChange={(event) => setContextCompression((current) => ({ ...current, threshold_percent: Number(event.target.value) }))}>
              {[50, 60, 70, 75, 80, 85, 90, 95].map((value) => <option key={value} value={value}>{value}%</option>)}
            </select></label>
          </div>}
          {!runtimeStatus.loading && !runtimeStatus.running && <small className="context-compression-note">请先启动当前工作流，再手动压缩。</small>}
          {runtimeStatus.running && !activeModel.hasModel && <small className="context-compression-note">当前工作流没有可用模型，无法压缩。</small>}
          {contextCompressionFeedback?.sessionId === activeSessionId && <small className={`context-compression-feedback is-${contextCompressionFeedback.type}`} role={contextCompressionFeedback.type === 'error' ? 'alert' : 'status'}>{contextCompressionFeedback.text}</small>}
          {contextCompression.enabled && activeModel.contextWindow === null && <small className="context-compression-note">当前模型未配置上下文长度，自动压缩暂不可用。</small>}
          {contextCompression.enabled && activeModel.contextWindow !== null && contextTokens === null && <small className="context-compression-note">收到模型 token 用量后开始判断压缩时机。</small>}
        </div>,
        document.body,
      )}
      {sandboxPermissionOpen && createPortal(
        <div
          ref={sandboxPermissionPopoverRef}
          className={`sandbox-permission-popover ${sandboxSettings.permission === 'full' ? 'is-full' : ''}`}
          role="dialog"
          aria-label="沙箱执行权限"
          style={{ left: `${sandboxPermissionPosition.left}px`, top: `${sandboxPermissionPosition.top}px` }}
        >
          <strong><Shield size={14} aria-hidden="true" />沙箱执行权限</strong>
          <div className="sandbox-mode-options" role="group" aria-label="权限模式">
            <button type="button" className={sandboxSettings.permission === 'workspace' ? 'selected' : ''} aria-pressed={sandboxSettings.permission === 'workspace'} onClick={() => updateSandboxMode('workspace')}>工作空间</button>
            <button type="button" className={sandboxSettings.permission === 'custom' ? 'selected' : ''} aria-pressed={sandboxSettings.permission === 'custom'} onClick={() => updateSandboxMode('custom')}>自定义</button>
            <button type="button" className={sandboxSettings.permission === 'full' ? 'selected is-warning' : ''} aria-pressed={sandboxSettings.permission === 'full'} onClick={() => updateSandboxMode('full')}>全部权限</button>
          </div>
          {sandboxSettings.permission === 'workspace' && <p>工作空间内可读写；工作空间外只读。</p>}
          {sandboxSettings.permission === 'full' && <p className="sandbox-full-warning"><AlertTriangle size={13} aria-hidden="true" />工具可以修改工作空间外的文件。</p>}
          {sandboxSettings.permission === 'custom' && <SandboxPermissionMatrix settings={sandboxSettings} onChange={updateSandboxAction} />}
          <div className="sandbox-workspace-control">
            <div><span>工作空间</span><small title={sandboxSettings.workspace}>{sandboxSettings.workspace || '读取中…'}</small></div>
            <button type="button" className="secondary-button" onClick={openSandboxDirectoryBrowser}><Folder size={13} />更改工作空间</button>
          </div>
          {sandboxBrowseOpen && <div className="sandbox-inline-browser">
            <div className="sandbox-inline-browser-heading">
              <button type="button" className="secondary-button" disabled={!sandboxBrowseParent || sandboxBrowseBusy} onClick={() => loadSandboxDirectory(sandboxBrowseParent)}><FolderUp size={13} />上一级</button>
              <input aria-label="目录路径" value={sandboxBrowsePathDraft} disabled={sandboxBrowseBusy} onChange={(event) => setSandboxBrowsePathDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); goToSandboxDirectory(); } }} spellCheck={false} />
              <button type="button" className="secondary-button" disabled={sandboxBrowseBusy} onClick={goToSandboxDirectory}>前往</button>
            </div>
            <div className="sandbox-inline-directory-list">
              {sandboxBrowseBusy ? <span className="sandbox-inline-empty">正在读取目录…</span> : sandboxBrowseError ? <span className="sandbox-inline-error" role="alert">{sandboxBrowseError}</span> : sandboxDirectories.length ? sandboxDirectories.map((directory) => <button type="button" key={directory.path} onClick={() => loadSandboxDirectory(directory.path)}><Folder size={13} /><span>{directory.name}</span><ChevronRight size={12} /></button>) : <span className="sandbox-inline-empty">此目录下没有子目录</span>}
            </div>
            <div className="sandbox-inline-browser-actions"><span>将当前目录设为工作空间</span><button type="button" className="primary-button" disabled={!sandboxBrowsePath || sandboxBrowseBusy} onClick={useSandboxDirectory}><Folder size={12} />使用此目录</button></div>
          </div>}
          {sandboxRuntime && !sandboxRuntime.filesystem_permissions_available && <small className="sandbox-popover-error">当前环境没有可用的文件系统隔离；需要 Linux / WSL、Firejail 和 Landlock ABI 3。</small>}
          {sandboxPermissionError && <small className="sandbox-popover-error" role="alert">{sandboxPermissionError}</small>}
          <div className="sandbox-popover-actions"><span role={sandboxPermissionError ? 'alert' : 'status'}>{sandboxPermissionSaved ? '已保存到本机' : '有未保存的改动'}</span><button type="button" className="primary-button" disabled={sandboxPermissionBusy || sandboxPermissionSaved || !sandboxRuntime?.filesystem_permissions_available} onClick={saveSandboxPermissions}>{sandboxPermissionBusy ? <span className="spinner" /> : <Save size={13} />}{sandboxPermissionBusy ? '保存中…' : '应用权限'}</button></div>
        </div>,
        document.body,
      )}
      {avatarPickerOpen && <div className="profile-editor-backdrop avatar-picker-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setAvatarPickerOpen(false); }}><section className="avatar-picker-modal" role="dialog" aria-modal="true" aria-labelledby="avatar-picker-title" onKeyDown={(event) => { if (event.key === 'Escape') setAvatarPickerOpen(false); }}>
        <header><div><span className="eyebrow">CHAT AVATARS</span><h2 id="avatar-picker-title">对话头像</h2></div><button className="icon-button" onClick={() => setAvatarPickerOpen(false)} title="关闭" aria-label="关闭"><X size={17} /></button></header>
        <input ref={userAvatarInputRef} className="avatar-file-input" type="file" accept="image/*" onChange={(event) => handleAvatarUpload('user', event)} />
        <input ref={agentAvatarInputRef} className="avatar-file-input" type="file" accept="image/*" onChange={(event) => handleAvatarUpload('agent', event)} />
        <div className="avatar-picker-options">
          {[['user', '用户头像', userAvatarInputRef, 'W'], ['agent', 'Agent 头像', agentAvatarInputRef, <Bot size={20} />]].map(([role, label, inputRef, fallback]) => <div className="avatar-picker-row" key={role}>
            <div className={`avatar-picker-preview ${role}`}>{avatars[role] ? <img src={avatars[role]} alt="" /> : fallback}</div>
            <strong>{label}</strong>
            <button className="secondary-button" onClick={() => inputRef.current?.click()}><Upload size={14} />更换</button>
            <button className="icon-button" onClick={() => resetAvatar(role)} disabled={!avatars[role]} title="恢复默认头像" aria-label={`恢复默认${label}`}><RotateCcw size={15} /></button>
          </div>)}
        </div>
        <footer><span className={avatarError ? 'profile-editor-error' : 'profile-editor-status'} role={avatarError ? 'alert' : undefined}>{avatarError || '支持常见图片格式，图片保存在当前浏览器中'}</span><button className="secondary-button" onClick={() => setAvatarPickerOpen(false)}><ImageIcon size={15} />完成</button></footer>
      </section></div>}
      {profileOpen && <div className="profile-editor-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !profileSaving) setProfileOpen(false); }}><section className="profile-editor-modal" role="dialog" aria-modal="true" aria-labelledby="profile-editor-title">
        <header><div><span className="eyebrow">USER PROFILE</span><h2 id="profile-editor-title">编辑用户信息</h2><span className="profile-file-path">modules/prompt/SystemPrompt/USER.md</span></div><button className="icon-button" disabled={profileSaving} onClick={() => setProfileOpen(false)} title="关闭"><X size={17} /></button></header>
        <textarea spellCheck="false" value={profileText} onChange={(event) => { setProfileText(event.target.value); setProfileSaved(false); }} disabled={!profileLoaded || profileLoading || profileSaving} placeholder={profileLoading ? '正在读取 USER.md…' : ''} />
        <footer><div className={profileError ? 'profile-editor-error' : 'profile-editor-status'}>{profileError || (profileSaved ? '已保存到项目中的 USER.md' : '修改将直接写入项目文件')}</div><button className="primary-button" onClick={saveUserProfile} disabled={!profileLoaded || profileLoading || profileSaving}>{profileSaving ? <span className="spinner" /> : <Save size={15} />}{profileSaving ? '保存中…' : '保存'}</button></footer>
      </section></div>}
      {pendingDeleteSession && <div className="chat-delete-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setPendingDeleteSessionId(null); }}><section className="chat-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="chat-delete-title" aria-describedby="chat-delete-description" onKeyDown={(event) => { if (event.key === 'Escape') setPendingDeleteSessionId(null); }}>
        <h2 id="chat-delete-title">删除对话</h2>
        <p id="chat-delete-description">确定删除“{pendingDeleteSession.title || '新的对话'}”吗？删除后无法恢复。</p>
        <div className="chat-delete-actions"><button className="secondary-button" autoFocus onClick={() => setPendingDeleteSessionId(null)}>取消</button><button className="danger-button" onClick={deleteConversation}><Trash2 size={15} />删除</button></div>
      </section></div>}
    </div>
  );
}

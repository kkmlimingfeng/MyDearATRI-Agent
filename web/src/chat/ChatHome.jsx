import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, AlertCircle, ArrowUp, Bot, Check, ChevronDown, FileClock, MessageSquarePlus, PanelLeftClose, Pencil, Plus, Save, Trash2, Workflow, X, Zap } from 'lucide-react';
import { ThemePicker } from '../theme.jsx';
import { modelChoices } from '../workflow/catalog';
import TraceView from '../workflow/TraceView';
import { useInterfaceLanguage } from '../workflow/interfaceLanguage';
import { runWorkflowRequest } from '../workflow/runApi';
import VoiceOutput from '../workflow/VoiceOutput';
import { createStreamingTtsSession, primeAudioPlayback, splitSpeakableText } from '../workflow/streamingTts';
import { getChatActivity, getRecentActions } from './activityStatus';

const CHAT_STORAGE_KEY = 'atri.chat.sessions.v1';
const ACTIVE_CHAT_STORAGE_KEY = 'atri.chat.active.v1';

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
    reference: 'atri',
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

function readChatState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) || 'null');
    const sessions = Array.isArray(parsed)
      ? parsed.filter((session) => session && typeof session.id === 'string' && Array.isArray(session.messages))
        .map((session) => ({
          ...session,
          messages: session.messages.filter((message) => !(
            message?.role === 'assistant' && STATIC_GREETING_MESSAGES.has(message.content)
          )),
        }))
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
  const [busy, setBusy] = useState(false);
  const [busySessionId, setBusySessionId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [liveDraft, setLiveDraft] = useState('');
  const liveEventsRef = useRef([]);
  const threadRef = useRef(null);
  const followThreadRef = useRef(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [pendingDeleteSessionId, setPendingDeleteSessionId] = useState(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileText, setProfileText] = useState('');
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileLoaded, setProfileLoaded] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [profileSaved, setProfileSaved] = useState(false);
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
    const choice = modelChoices.find((option) => option.value === modelId);
    return { label: choice?.label || modelId || (direct ? '无模型直通' : '未选择模型'), hasModel: Boolean(node), supportsReasoning: node?.type === 'llm.openai_loader' || (node?.type === 'llm.provider' && choice?.type === 'api') };
  }, [workflow]);

  const appendMessage = (sessionId, message, title) => {
    setChatState((current) => ({
      ...current,
      sessions: current.sessions.map((session) => session.id === sessionId
        ? {
          ...session,
          title: title && session.title === '新的对话' ? title.slice(0, 28) : session.title,
          messages: [...session.messages, message],
          updatedAt: Date.now(),
        }
        : session),
    }));
  };

  const sendMessage = async () => {
    const text = input.trim();
    const sessionId = activeSession?.id;
    if (!text || busy || !workflow || !sessionId) return;
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
    const voiceAbort = new AbortController();
    const voiceSession = voiceRequest ? createStreamingTtsSession(voiceRequest, voiceAbort.signal) : null;
    let lastDraft = '';
    let pendingSpeechText = '';
    const updateSpeechDraft = (draft) => {
      if (!voiceSession) return;
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
      const history = activeSession.messages
        .filter((message) => !message.error && typeof message.content === 'string' && ['user', 'assistant'].includes(message.role))
        .map(({ role, content }) => ({ role, content }));
      const result = await runWorkflowRequest({ workflow, input: text, mode, require_started: true, history, ...(activeModel.supportsReasoning && reasoningEffort !== 'workflow' ? { reasoning_effort: reasoningEffort } : {}) }, onProgress);
      if (!result.answer && result.error) throw new Error(result.error);
      let voiceBlob;
      let voiceError = '';
      if (voiceSession) {
        const answer = String(result.answer || '');
        pendingSpeechText = answer.startsWith(lastDraft) ? pendingSpeechText + answer.slice(lastDraft.length) : answer;
        lastDraft = answer;
        const { segments, remainder } = splitSpeakableText(pendingSpeechText, true);
        segments.forEach((segment) => voiceSession.enqueue(segment));
        const voiceResult = await voiceSession.finish();
        voiceBlob = voiceResult.blob;
        voiceError = voiceResult.error?.message || '';
      }
      liveEventsRef.current = result.events || liveEventsRef.current;
      appendMessage(sessionId, { role: 'assistant', content: result.answer, voice: result.voice || (voiceRequest ? { ...voiceRequest, text: result.answer } : undefined), voiceBlob, voiceError, events: result.events, sentAt: Date.now(), durationMs: performance.now() - started });
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
          <button className="profile-row" onClick={openUserProfile} title="编辑 modules/prompt/SystemPrompt/USER.md"><div className="profile-avatar">W</div><span><strong>编辑用户信息</strong><small>USER.md</small></span><Pencil size={15} /></button>
        </div>
      </aside>
      <main className="chat-main">
        <header className="chat-topbar">
          {!sidebarOpen && <button className="icon-button" onClick={() => setSidebarOpen(true)} title="展开侧栏"><PanelLeftClose size={15} /></button>}
          <div className="chat-agent-title"><span className="agent-status-icon"><Bot size={16} /></span><div><strong>ATRI</strong><span>陪伴型 Agent</span></div></div>
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
            {message.role === 'assistant' && <div className="message-avatar"><Bot size={16} /></div>}
            <div className={`message-content ${message.voice ? 'has-voice' : ''}`}>
              <MessageTime message={message} language={interfaceLanguage} />
              {message.error ? <div className="message-error">{message.error}</div> : message.voice ? <div className="message-bubble-row has-voice">
                <div className="message-bubble">{message.content}</div>
                <VoiceOutput request={message.voice} blob={message.voiceBlob} error={message.voiceError} autoGenerate={false} label="语音回复" />
              </div> : <div className="message-bubble">{message.content}</div>}
              {message.events?.length > 0 && <MessageTrace events={message.events} mode={mode} language={interfaceLanguage} durationMs={message.durationMs} />}
            </div>
            {message.role === 'user' && <div className="user-avatar">W</div>}
          </article>)}
          {busy && busySessionId === activeSessionId && <div className="chat-message assistant">
            <div className="message-avatar"><Bot size={16} /></div>
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
          <div className="composer-box"><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } }} placeholder={runtimeStatus.running ? '给 ATRI 发消息…' : '请先在工作流页启动 Agent'} rows={1} /><div className="composer-tools"><span className="composer-model"><Zap size={13} />{activeModel.label}</span>{activeModel.hasModel && <label className="composer-reasoning" title={activeModel.supportsReasoning ? '本次对话的思考强度' : '当前 GGUF 模型暂不支持思考强度参数'}><span>思考强度</span><select aria-label="思考强度" value={activeModel.supportsReasoning ? reasoningEffort : 'unsupported'} disabled={!activeModel.supportsReasoning} onChange={(event) => setReasoningEffort(event.target.value)}>{activeModel.supportsReasoning ? <><option value="workflow">跟随工作流</option><option value="auto">自动</option><option value="minimal">极低</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">极高</option></> : <option value="unsupported">GGUF 暂不支持</option>}</select></label>}<span className="composer-hint">Enter 发送 · Shift + Enter 换行</span><button className="send-button" disabled={!input.trim() || busy || runtimeStatus.loading || !runtimeStatus.running} onClick={sendMessage} title={runtimeStatus.running ? '发送消息' : '先启动工作流'}><ArrowUp size={17} /></button></div></div>
          <div className="composer-caption">ATRI 会根据当前激活的工作流配置运行。<button onClick={() => onNavigate('workflow')}>编辑工作流</button></div>
        </footer>
      </main>
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

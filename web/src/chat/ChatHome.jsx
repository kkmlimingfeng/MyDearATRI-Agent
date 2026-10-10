import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowUp, Bot, ChevronDown, FileClock, MessageSquarePlus, PanelLeftClose, Pencil, Plus, Save, Trash2, Workflow, X, Zap } from 'lucide-react';
import { ThemePicker } from '../theme.jsx';
import { modelChoices } from '../workflow/catalog';

const CHAT_STORAGE_KEY = 'atri.chat.sessions.v1';
const ACTIVE_CHAT_STORAGE_KEY = 'atri.chat.active.v1';
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

function TraceList({ events }) {
  return <div className="chat-trace-list">{events.map((event, index) => <div className="chat-trace-event" key={`${event.event_type}-${index}`}><span className="trace-time">{String(index + 1).padStart(2, '0')}</span><span className="trace-event-name">{event.event_type}</span><span className="trace-event-node">{event.node_id || 'runtime'}</span></div>)}</div>;
}

export default function ChatHome({ onNavigate }) {
  const [workflow, setWorkflow] = useState(null);
  const [chatState, setChatState] = useState(readChatState);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState('normal');
  const [busy, setBusy] = useState(false);
  const [busySessionId, setBusySessionId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
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

  useEffect(() => {
    try {
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(sessions));
      localStorage.setItem(ACTIVE_CHAT_STORAGE_KEY, activeSessionId);
    } catch {
      // The conversation remains usable when browser storage is unavailable.
    }
  }, [sessions, activeSessionId]);

  useEffect(() => {
    const handleShortcut = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        clearConversation();
      }
    };
    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
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
    load(false);
    const handleApplied = () => load(true);
    window.addEventListener('atri-workflow-applied', handleApplied);
    return () => window.removeEventListener('atri-workflow-applied', handleApplied);
  }, []);

  const activeModel = useMemo(() => {
    const node = workflow?.nodes?.find((item) => ['llm.provider', 'llm.gguf_loader', 'llm.openai_loader'].includes(item.type));
    const modelId = node?.data?.config?.model;
    return modelChoices.find((option) => option.value === modelId)?.label || modelId || '未选择模型';
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
    setInput('');
    appendMessage(sessionId, { role: 'user', content: text }, text);
    setBusy(true);
    setBusySessionId(sessionId);
    try {
      const response = await fetch('/api/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow, input: text, mode, require_started: true }),
      });
      const raw = await response.text();
      let result;
      try { result = raw ? JSON.parse(raw) : {}; } catch { throw new Error(`服务返回了无效数据（HTTP ${response.status}）`); }
      if (!response.ok) throw new Error(result.error || 'Agent 运行失败');
      if (!result.answer && result.error) throw new Error(result.error);
      appendMessage(sessionId, { role: 'assistant', content: result.answer, events: result.events });
    } catch (error) {
      appendMessage(sessionId, { role: 'assistant', error: error.message });
    } finally {
      setBusy(false);
      setBusySessionId(null);
    }
  };

  const clearConversation = () => {
    const session = createSession();
    setChatState((current) => ({ sessions: [session, ...current.sessions], activeSessionId: session.id }));
  };

  const deleteConversation = (event, sessionId) => {
    event.stopPropagation();
    if (!window.confirm('确定删除这条对话吗？删除后无法恢复。')) return;
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
    setChatState((current) => ({ ...current, activeSessionId: sessionId }));
  };

  const recentSessions = [...sessions].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));

  return (
    <div className={`chat-shell ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
      {sidebarOpen && <aside className="chat-sidebar">
        <div className="chat-brand"><div className="brand-mark">A</div><div><strong>ATRI <span>AGENT</span></strong><small>LOCAL WORKSPACE</small></div><button className="icon-button" title="收起侧栏" onClick={() => setSidebarOpen(false)}><PanelLeftClose size={15} /></button></div>
        <button className="new-chat-button" onClick={clearConversation}><MessageSquarePlus size={15} />新对话<span>Ctrl/⌘ K</span></button>
        <div className="sidebar-section-title">最近对话</div>
        {recentSessions.map((session, index) => <div className={`conversation-row ${session.id === activeSessionId ? 'active' : ''}`} key={session.id}>
          <button className={`conversation-item ${session.id === activeSessionId ? 'active' : ''}`} onClick={() => selectConversation(session.id)} title={session.title}>
            {index === 0 ? <MessageSquarePlus size={14} /> : <FileClock size={14} />}<span>{session.title || '新的对话'}</span>
          </button>
          <button className="conversation-delete" onClick={(event) => deleteConversation(event, session.id)} title={`删除对话：${session.title || '新的对话'}`} aria-label={`删除对话：${session.title || '新的对话'}`}><Trash2 size={14} /></button>
        </div>)}
        <div className="sidebar-bottom">
          <button className="sidebar-workflow-link" onClick={() => onNavigate('workflow')}><Workflow size={16} /><span><strong>工作流编辑器</strong><small>调整 Agent 的底层逻辑</small></span><ChevronDown size={14} className="side-link-chevron" /></button>
          <button className="profile-row" onClick={openUserProfile} title="编辑 modules/prompt/SystemPrompt/USER.md"><div className="profile-avatar">W</div><span><strong>编辑用户信息</strong><small>USER.md</small></span><Pencil size={15} /></button>
        </div>
      </aside>}
      <main className="chat-main">
        <header className="chat-topbar">
          {!sidebarOpen && <button className="icon-button" onClick={() => setSidebarOpen(true)} title="展开侧栏"><PanelLeftClose size={15} /></button>}
          <div className="chat-agent-title"><span className="agent-status-icon"><Bot size={16} /></span><div><strong>ATRI</strong><span>陪伴型 Agent</span></div></div>
          <nav className="app-nav chat-nav"><button className="active" onClick={() => onNavigate('chat')}>对话</button><button onClick={() => onNavigate('workflow')}>工作流</button></nav>
          <div className="chat-top-spacer" />
          <ThemePicker />
          <div className="active-config"><span className="config-dot" /><span>{workflow?.name || '加载工作流'}</span></div>
          <div className="mode-switch" role="group" aria-label="对话模式"><button className={mode === 'normal' ? 'selected' : ''} onClick={() => setMode('normal')}>正常</button><button className={mode === 'transparent' ? 'selected' : ''} onClick={() => setMode('transparent')}><Activity size={12} />透明</button></div>
          <button className="icon-button" title="新对话" onClick={clearConversation}><Plus size={16} /></button>
        </header>
        <section className="chat-thread">
          <div className="chat-date-label"><span />今天<span /></div>
          {messages.map((message, index) => <article className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
            {message.role === 'assistant' && <div className="message-avatar"><Bot size={16} /></div>}
            <div className="message-content">
              {message.error ? <div className="message-error">{message.error}</div> : <div className="message-bubble">{message.content}</div>}
              {mode === 'transparent' && message.events?.length > 0 && <details className="trace-details" open><summary><Activity size={13} />执行轨迹 <span>{message.events.length} events</span></summary><TraceList events={message.events} /></details>}
              {message.role === 'assistant' && index === 0 && <div className="message-meta"><span>ATRI</span><span>·</span><span>刚刚</span></div>}
            </div>
            {message.role === 'user' && <div className="user-avatar">W</div>}
          </article>)}
          {busy && busySessionId === activeSessionId && <div className="chat-message assistant"><div className="message-avatar"><Bot size={16} /></div><div className="message-bubble thinking"><span /><span /><span />正在思考</div></div>}
        </section>
        <footer className="composer-area">
          <div className="composer-box"><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } }} placeholder="给 ATRI 发消息…" rows={1} /><div className="composer-tools"><span><Zap size={13} />{activeModel}</span><span className="composer-hint">Enter 发送 · Shift + Enter 换行</span><button className="send-button" disabled={!input.trim() || busy} onClick={sendMessage} title="发送消息"><ArrowUp size={17} /></button></div></div>
          <div className="composer-caption">ATRI 会根据当前激活的工作流配置运行。<button onClick={() => onNavigate('workflow')}>编辑工作流</button></div>
        </footer>
      </main>
      {profileOpen && <div className="profile-editor-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !profileSaving) setProfileOpen(false); }}><section className="profile-editor-modal" role="dialog" aria-modal="true" aria-labelledby="profile-editor-title">
        <header><div><span className="eyebrow">USER PROFILE</span><h2 id="profile-editor-title">编辑用户信息</h2><span className="profile-file-path">modules/prompt/SystemPrompt/USER.md</span></div><button className="icon-button" disabled={profileSaving} onClick={() => setProfileOpen(false)} title="关闭"><X size={17} /></button></header>
        <textarea spellCheck="false" value={profileText} onChange={(event) => { setProfileText(event.target.value); setProfileSaved(false); }} disabled={!profileLoaded || profileLoading || profileSaving} placeholder={profileLoading ? '正在读取 USER.md…' : ''} />
        <footer><div className={profileError ? 'profile-editor-error' : 'profile-editor-status'}>{profileError || (profileSaved ? '已保存到项目中的 USER.md' : '修改将直接写入项目文件')}</div><button className="primary-button" onClick={saveUserProfile} disabled={!profileLoaded || profileLoading || profileSaving}>{profileSaving ? <span className="spinner" /> : <Save size={15} />}{profileSaving ? '保存中…' : '保存'}</button></footer>
      </section></div>}
    </div>
  );
}

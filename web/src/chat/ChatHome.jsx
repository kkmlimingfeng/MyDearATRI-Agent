import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Activity, AlertCircle, AlertTriangle, ArrowUp, Bot, Check, ChevronDown, ChevronRight, FileClock, FileText, Film, Folder, FolderUp, Image as ImageIcon, MessageSquarePlus, Minimize2, Paperclip, PanelLeftClose, Pencil, Plus, RotateCcw, Save, Settings2, Shield, Trash2, Upload, Workflow, X, Zap } from 'lucide-react';
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
const CHAT_ATTACHMENT_DB = 'atri.chat.attachments.v1';
const CONTEXT_COMPRESSION_STORAGE_KEY = 'atri.chat.context-compression.v1';
const MEMORY_SETTINGS_STORAGE_KEY = 'atri.chat.memory-settings.v1';
const DEFAULT_CONTEXT_COMPRESSION = { enabled: true, keep_recent_turns: 6, threshold_percent: 75 };
const DEFAULT_MEMORY_SETTINGS = { summary_interval_turns: 8 };
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
  const now = Date.now();
  return {
    id: `chat_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    title: '新的对话',
    messages: [],
    createdAt: now,
    updatedAt: now,
  };
}

function readMemorySettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(MEMORY_SETTINGS_STORAGE_KEY) || 'null');
    const value = Number(saved?.summary_interval_turns);
    return {
      summary_interval_turns: Number.isInteger(value) ? Math.min(100, Math.max(1, value)) : DEFAULT_MEMORY_SETTINGS.summary_interval_turns,
    };
  } catch {
    return DEFAULT_MEMORY_SETTINGS;
  }
}

function conversationArchivePayload(session) {
  if (!session || session.isTestRun) return null;
  const messages = (session.messages || [])
    .filter((message) => !message?.error && typeof message?.content === 'string' && ['user', 'assistant'].includes(message.role))
    .map(({ role, content, contextContent, sentAt }) => ({ role, content: contextContent || content, sentAt }));
  if (!messages.length) return null;
  return {
    id: session.id,
    title: session.title || '新的对话',
    createdAt: session.createdAt,
    updatedAt: session.updatedAt,
    source: 'chat',
    test_run: false,
    messages,
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

const ATTACHMENT_LIMIT = 10;
const ATTACHMENT_FILE_LIMIT = 12 * 1024 * 1024;
const DOCUMENT_EXTENSIONS = new Set(['pdf', 'docx', 'docm', 'xlsx', 'xlsm', 'pptx', 'pptm', 'odt', 'ods', 'odp', 'txt', 'md', 'csv', 'tsv', 'json', 'log', 'py', 'js', 'jsx', 'ts', 'tsx', 'html', 'css', 'xml', 'yaml', 'yml', 'toml', 'ini', 'sql', 'sh', 'rs', 'java', 'go', 'c', 'h', 'cpp']);
const IMAGE_MIMES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp']);
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp']);
const VIDEO_EXTENSIONS = new Set(['mp4', 'webm', 'mov', 'm4v', 'ogv']);

function openChatAttachmentDb() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) {
      reject(new Error('浏览器不支持本地附件缓存'));
      return;
    }
    const request = window.indexedDB.open(CHAT_ATTACHMENT_DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore('attachments');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('打开附件缓存失败'));
  });
}

async function writeChatAttachment(key, value) {
  const database = await openChatAttachmentDb();
  await new Promise((resolve, reject) => {
    const transaction = database.transaction('attachments', 'readwrite');
    transaction.objectStore('attachments').put(value, key);
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(transaction.error || new Error('保存附件缓存失败'));
    transaction.onabort = () => reject(transaction.error || new Error('保存附件缓存失败'));
  }).finally(() => database.close());
}

async function readChatAttachment(key) {
  const database = await openChatAttachmentDb();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction('attachments', 'readonly');
    const request = transaction.objectStore('attachments').get(key);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error || new Error('读取附件缓存失败'));
    transaction.oncomplete = () => database.close();
    transaction.onerror = () => database.close();
  });
}

async function deleteChatAttachment(key) {
  try {
    const database = await openChatAttachmentDb();
    await new Promise((resolve, reject) => {
      const transaction = database.transaction('attachments', 'readwrite');
      transaction.objectStore('attachments').delete(key);
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error || new Error('删除附件缓存失败'));
      transaction.onabort = () => reject(transaction.error || new Error('删除附件缓存失败'));
    }).finally(() => database.close());
  } catch {
    // A missing local cache must not block deleting a conversation.
  }
}

function bytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const step = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += step) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + step));
  }
  return btoa(binary);
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] || '');
    reader.onerror = () => reject(new Error('读取附件失败'));
    reader.readAsDataURL(blob);
  });
}

async function makeVideoFrames(file) {
  const url = URL.createObjectURL(file);
  const video = document.createElement('video');
  video.preload = 'metadata';
  video.muted = true;
  video.playsInline = true;
  video.src = url;
  try {
    await new Promise((resolve, reject) => {
      video.onloadedmetadata = resolve;
      video.onerror = () => reject(new Error('浏览器无法读取该视频格式'));
    });
    if (video.readyState < 2) {
      await new Promise((resolve, reject) => {
        video.onloadeddata = resolve;
        video.onerror = () => reject(new Error('无法解码视频画面'));
      });
    }
    if (!Number.isFinite(video.duration) || video.duration <= 0 || video.duration > 20 * 60) {
      throw new Error('视频时长需要在 20 分钟以内');
    }
    const frameCount = Math.min(8, Math.max(1, Math.ceil(video.duration / 2)));
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    if (!context) throw new Error('浏览器无法创建视频画布');
    const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const frames = [];
    for (let index = 0; index < frameCount; index += 1) {
      const timestamp = frameCount === 1 ? 0 : (video.duration - 0.05) * index / (frameCount - 1);
      if (timestamp > 0) {
        video.currentTime = timestamp;
        await new Promise((resolve, reject) => {
          video.onseeked = resolve;
          video.onerror = () => reject(new Error('无法读取视频画面'));
        });
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.76));
      if (!blob) throw new Error('视频画面转换失败');
      frames.push({ timestamp, data: await blobToBase64(blob) });
    }
    return frames;
  } finally {
    video.pause();
    video.removeAttribute('src');
    video.load();
    URL.revokeObjectURL(url);
  }
}

async function prepareAttachment(file) {
  const extension = file.name.split('.').pop()?.toLowerCase() || '';
  const previewUrl = URL.createObjectURL(file);
  try {
    if (IMAGE_MIMES.has(file.type) || IMAGE_EXTENSIONS.has(extension)) {
      if (file.size > ATTACHMENT_FILE_LIMIT) throw new Error(`${file.name} 超过 12 MB`);
      let data;
      if (typeof createImageBitmap === 'function') {
        const bitmap = await createImageBitmap(file);
        const scale = Math.min(1, 2048 / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close();
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.86));
        if (!blob) throw new Error('图片转换失败');
        data = await blobToBase64(blob);
      } else {
        data = bytesToBase64(await file.arrayBuffer());
      }
      return { id: crypto.randomUUID(), name: file.name, kind: 'image', mimeType: file.type, data, previewUrl };
    }
    if (file.type.startsWith('video/') || VIDEO_EXTENSIONS.has(extension)) {
      if (file.size > 512 * 1024 * 1024) throw new Error('视频文件不能超过 512 MB');
      const frames = await makeVideoFrames(file);
      return { id: crypto.randomUUID(), name: file.name, kind: 'video', mimeType: file.type, frames, previewUrl };
    }
    if (DOCUMENT_EXTENSIONS.has(extension)) {
      if (file.size > ATTACHMENT_FILE_LIMIT) throw new Error(`${file.name} 超过 12 MB`);
      return { id: crypto.randomUUID(), name: file.name, kind: 'document', mimeType: file.type, data: bytesToBase64(await file.arrayBuffer()), previewUrl };
    }
    throw new Error(`暂不支持 ${file.name}，请选图片、视频、PDF、Office 或文本文件`);
  } catch (error) {
    URL.revokeObjectURL(previewUrl);
    throw error;
  }
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
  const [selectedAttachments, setSelectedAttachments] = useState([]);
  const [attachmentError, setAttachmentError] = useState('');
  const [attachmentBusy, setAttachmentBusy] = useState(false);
  const attachmentInputRef = useRef(null);
  const [mode, setMode] = useState('normal');
  const [reasoningEffort, setReasoningEffort] = useState('workflow');
  const [modelCatalog, setModelCatalog] = useState(modelChoices);
  const [busy, setBusy] = useState(false);
  const [busySessionId, setBusySessionId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [liveDraft, setLiveDraft] = useState('');
  const [pendingQuestion, setPendingQuestion] = useState(null);
  const [questionResponse, setQuestionResponse] = useState({ id: '', answers: {} });
  const [questionSubmitting, setQuestionSubmitting] = useState(false);
  const [questionError, setQuestionError] = useState('');
  const [answeredQuestionId, setAnsweredQuestionId] = useState('');
  const pendingQuestionRef = useRef(null);
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
    allow_command_execution: false,
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
  const [memorySettings, setMemorySettings] = useState(readMemorySettings);
  const [memoryConversations, setMemoryConversations] = useState([]);
  const [memorySummaryBusy, setMemorySummaryBusy] = useState(null);
  const [memorySummaryFeedback, setMemorySummaryFeedback] = useState(null);
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
  const archiveSyncRef = useRef(new Map());
  const archiveInFlightRef = useRef(new Map());
  const memorySummaryBusyRef = useRef(false);
  const memorySummaryQueueRef = useRef([]);
  const { sessions, activeSessionId } = chatState;
  const activeSession = sessions.find((session) => session.id === activeSessionId) || sessions[0];
  const messages = activeSession?.messages || [];
  const recentActions = getRecentActions(liveEvents, interfaceLanguage);
  const memoryConversationItems = useMemo(() => {
    const entries = new Map(memoryConversations.map((conversation) => [conversation.id, conversation]));
    for (const session of sessions) {
      const archive = conversationArchivePayload(session);
      if (!archive || entries.has(session.id)) continue;
      const completeMessages = archive.messages.slice(0, Math.max(
        0,
        archive.messages.reduce((last, message, index) => message.role === 'assistant' ? index + 1 : last, 0),
      ));
      entries.set(session.id, {
        id: session.id,
        title: session.title || '新的对话',
        turn_count: completeMessages.filter((message) => message.role === 'assistant').length,
        summary: '',
        summary_status: 'pending',
        updated_at: session.updatedAt || 0,
      });
    }
    return [...entries.values()].sort((left, right) => (right.updated_at || 0) - (left.updated_at || 0));
  }, [memoryConversations, sessions]);

  const saveConversationArchive = async (session) => {
    const conversation = conversationArchivePayload(session);
    if (!conversation) return { saved: false, empty: true };
    const response = await fetch('/api/memory/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'save', conversation }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '保存会话记忆失败');
    if (result.saved) archiveSyncRef.current.set(session.id, JSON.stringify(conversation));
    return result;
  };

  const refreshMemoryConversations = async () => {
    const response = await fetch('/api/memory/conversations', { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '读取会话摘要失败');
    setMemoryConversations(Array.isArray(result.conversations) ? result.conversations : []);
    return result.conversations || [];
  };

  const requestMemorySummaryUpdate = async ({ conversationIds, force = false, sourceSessions = sessions } = {}) => {
    if (memorySummaryBusyRef.current) {
      memorySummaryQueueRef.current.push({ conversationIds, force, sourceSessions });
      return;
    }
    memorySummaryBusyRef.current = true;
    setMemorySummaryBusy(conversationIds?.length === 1 ? conversationIds[0] : 'all');
    setMemorySummaryFeedback(null);
    try {
      for (const session of sourceSessions) {
        const conversation = conversationArchivePayload(session);
        if (!conversation) continue;
        if (archiveSyncRef.current.get(session.id) === JSON.stringify(conversation)) continue;
        await saveConversationArchive(session);
      }
      const response = await fetch('/api/memory/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'summarize', conversation_ids: conversationIds, force }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '更新会话摘要失败');
      const failures = (result.results || []).filter((item) => !item.updated);
      await refreshMemoryConversations();
      if (failures.length) {
        setMemorySummaryFeedback({
          type: 'error',
          text: `${result.updated || 0} 段已更新，${failures.length} 段失败：${failures[0].error || '模型未返回摘要'}`,
        });
      } else if (result.updated) {
        setMemorySummaryFeedback({ type: 'success', text: `已更新 ${result.updated} 段会话摘要。` });
      } else {
        setMemorySummaryFeedback({ type: 'info', text: force ? '没有可整理的会话。' : '没有待更新的会话摘要。' });
      }
    } catch (error) {
      setMemorySummaryFeedback({ type: 'error', text: error.message || '更新会话摘要失败' });
    } finally {
      memorySummaryBusyRef.current = false;
      setMemorySummaryBusy(null);
      const nextRequest = memorySummaryQueueRef.current.shift();
      if (nextRequest) window.setTimeout(() => requestMemorySummaryUpdate(nextRequest), 0);
    }
  };

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
    for (const session of sessions) {
      const conversation = conversationArchivePayload(session);
      if (!conversation) continue;
      const signature = JSON.stringify(conversation);
      if (archiveSyncRef.current.get(session.id) === signature || archiveInFlightRef.current.get(session.id) === signature) continue;
      archiveInFlightRef.current.set(session.id, signature);
      fetch('/api/memory/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'save', conversation }),
      })
        .then(async (response) => {
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || '保存会话记忆失败');
          if (result.saved || result.empty) archiveSyncRef.current.set(session.id, signature);
        })
        .catch(() => {})
        .finally(() => {
          if (archiveInFlightRef.current.get(session.id) === signature) archiveInFlightRef.current.delete(session.id);
        });
    }
  }, [sessions, runtimeStatus.running]);

  useEffect(() => {
    try { localStorage.setItem(CONTEXT_COMPRESSION_STORAGE_KEY, JSON.stringify(contextCompression)); }
    catch { /* Keep this control usable when browser storage is unavailable. */ }
  }, [contextCompression]);

  useEffect(() => {
    try { localStorage.setItem(MEMORY_SETTINGS_STORAGE_KEY, JSON.stringify(memorySettings)); }
    catch { /* Keep these controls usable when browser storage is unavailable. */ }
  }, [memorySettings]);

  useEffect(() => {
    let disposed = false;
    fetch('/api/memory/conversations', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('读取会话摘要失败')))
      .then((result) => { if (!disposed) setMemoryConversations(Array.isArray(result.conversations) ? result.conversations : []); })
      .catch(() => {});
    return () => { disposed = true; };
  }, [runtimeStatus.running]);

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
  }, [active, sessions]);

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
    const runtime = workflow?.nodes?.find((item) => item.type === 'llm.chat');
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
  }, [contextPopoverOpen, contextSettingsOpen, contextTokens, activeModel.contextWindow, contextCompressing, contextCompressionFeedback, memoryConversationItems.length, memorySummaryBusy, memorySummaryFeedback]);

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

  const handleAttachmentChange = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length) return;
    setAttachmentError('');
    setAttachmentBusy(true);
    const room = Math.max(0, ATTACHMENT_LIMIT - selectedAttachments.length);
    const prepared = [];
    const errors = [];
    for (const file of files.slice(0, room)) {
      try {
        prepared.push(await prepareAttachment(file));
      } catch (error) {
        errors.push(error.message || `无法读取 ${file.name}`);
      }
    }
    if (files.length > room) errors.push(`一次最多上传 ${ATTACHMENT_LIMIT} 个附件`);
    setSelectedAttachments((current) => [...current, ...prepared].slice(0, ATTACHMENT_LIMIT));
    setAttachmentError(errors.join('；'));
    setAttachmentBusy(false);
  };

  const removeSelectedAttachment = (attachmentId) => {
    setSelectedAttachments((current) => {
      const removed = current.find((item) => item.id === attachmentId);
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
      return current.filter((item) => item.id !== attachmentId);
    });
  };

  const submitQuestionAnswer = async () => {
    if (!pendingQuestion || questionSubmitting || answeredQuestionId === pendingQuestion.id) return;
    const answers = pendingQuestion.questions.map((question) => {
      const response = questionResponse.id === pendingQuestion.id
        ? questionResponse.answers[question.id] || { selected: [], custom: '' }
        : { selected: [], custom: '' };
      const custom = response.custom.trim();
      return {
        id: question.id,
        selected: custom && !question.multi_select ? [] : response.selected,
        ...(custom ? { custom } : {}),
      };
    });
    setQuestionSubmitting(true);
    setQuestionError('');
    try {
      const response = await fetch('/api/run/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question_id: pendingQuestion.id, answers }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '提交回答失败');
      setAnsweredQuestionId(pendingQuestion.id);
    } catch (error) {
      setQuestionError(error.message || '提交回答失败');
    } finally {
      setQuestionSubmitting(false);
    }
  };

  const sendMessage = async () => {
    const text = input.trim();
    const attachments = selectedAttachments;
    const sessionId = activeSession?.id;
    if ((!text && !attachments.length) || busy || attachmentBusy || contextCompressing || !workflow || !sessionId) return;
    void primeAudioPlayback().catch(() => {});
    if (!runtimeStatus.running) {
      appendMessage(sessionId, { role: 'assistant', error: '工作流尚未启动，请先到工作流页点击“启动工作流”后再对话。', sentAt: Date.now() });
      return;
    }
    const sentAt = Date.now();
    const started = performance.now();
    const attachmentNames = attachments.map((item) => item.name);
    const visualAttachments = attachments.filter((item) => ['image', 'video'].includes(item.kind));
    const attachmentRefs = visualAttachments.map((item) => `${sessionId}:${item.id}`);
    const storedUserText = text || `附件：${attachmentNames.join('、')}`;
    setInput('');
    setAttachmentError('');
    setSelectedAttachments([]);
    attachments.forEach((item) => { if (item.previewUrl) URL.revokeObjectURL(item.previewUrl); });
    followThreadRef.current = true;
    const userMessage = {
      role: 'user',
      content: storedUserText,
      displayContent: text,
      attachments: attachments.map(({ name, kind, mimeType }) => ({ name, kind, mimeType })),
      attachmentRefs,
      sentAt,
    };
    appendMessage(sessionId, userMessage, text || attachmentNames[0]);
    setBusy(true);
    setBusySessionId(sessionId);
    setLiveEvents([]);
    setLiveDraft('');
    setPendingQuestion(null);
    pendingQuestionRef.current = null;
    setQuestionResponse({ id: '', answers: {} });
    setAnsweredQuestionId('');
    setQuestionError('');
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
      const cacheResults = await Promise.allSettled(visualAttachments.map((item, index) => writeChatAttachment(
        attachmentRefs[index],
        { name: item.name, kind: item.kind, data: item.data, frames: item.frames },
      )));
      if (cacheResults.some((result) => result.status === 'rejected')) {
        setAttachmentError('附件本轮已发送，但浏览器无法保存附件缓存供后续追问使用。');
      }
      const onProgress = (events, draft, question) => {
        if (events.length !== liveEventsRef.current.length) {
          liveEventsRef.current = events;
          setLiveEvents(events);
        }
        setLiveDraft(draft);
        setPendingQuestion(question || null);
        if (question && question.id !== pendingQuestionRef.current?.id) {
          setQuestionResponse({
            id: question.id,
            answers: Object.fromEntries(question.questions.map((item) => [item.id, { selected: [], custom: '' }])),
          });
          setAnsweredQuestionId('');
          setQuestionSubmitting(false);
          setQuestionError('');
        }
        pendingQuestionRef.current = question || null;
        updateSpeechDraft(draft);
      };
      const fullHistory = activeSession.messages
        .filter((message) => !message.error && typeof message.content === 'string' && ['user', 'assistant'].includes(message.role))
        .map(({ role, content, contextContent, attachmentRefs: refs, sentAt }) => ({ role, content: contextContent || content, attachmentRefs: refs || [], sentAt }));
      const historyOffset = Math.min(fullHistory.length, Math.max(0, Number(activeSession.contextMessageOffset) || 0));
      const history = fullHistory.slice(historyOffset);
      let historyAttachmentBudget = attachments.length ? 0 : 3;
      let historyAttachmentBytes = 0;
      for (let index = history.length - 1; index >= 0 && historyAttachmentBudget > 0; index -= 1) {
        if (history[index].role !== 'user') continue;
        const cached = [];
        for (const ref of history[index].attachmentRefs) {
          if (historyAttachmentBudget <= 0) break;
          try {
            const value = await readChatAttachment(ref);
            if (value) {
              const base64Bytes = (value.data?.length || 0) + (value.frames || []).reduce((sum, frame) => sum + (frame.data?.length || 0), 0);
              if (historyAttachmentBytes + base64Bytes > 6 * 1024 * 1024) continue;
              cached.push(value);
              historyAttachmentBytes += base64Bytes;
              historyAttachmentBudget -= 1;
            }
          } catch {
            setAttachmentError('部分历史图片或视频缓存不可用，请重新上传后再询问。');
          }
        }
        if (cached.length) history[index].attachments = cached;
      }
      const requestHistory = history.map(({ attachmentRefs: _refs, ...message }) => message);
      const result = await runWorkflowRequest({
        workflow,
        conversation_id: sessionId,
        input: text,
        attachments: attachments.map(({ name, kind, data, frames }) => ({ name, kind, data, frames })),
        mode,
        require_started: true,
        history: requestHistory,
        client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || undefined,
        history_summary: activeSession.contextSummary || '',
        context_compression: {
          ...contextCompression,
          context_window: activeModel.contextWindow,
          previous_input_tokens: contextTokens,
        },
        ...(activeModel.supportsReasoning && reasoningEffort !== 'workflow' ? { reasoning_effort: reasoningEffort } : {}),
      }, onProgress);
      if (!result.answer && result.error) throw new Error(result.error);
      userMessage.contextContent = result.input_context || storedUserText;
      setChatState((current) => ({
        ...current,
        sessions: current.sessions.map((session) => session.id === sessionId ? {
          ...session,
          messages: session.messages.map((message) => message.sentAt === sentAt && message.role === 'user'
            ? { ...message, contextContent: userMessage.contextContent }
            : message),
        } : session),
      }));
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
      const assistantMessage = { role: 'assistant', content: result.answer, voice, voiceBlob, voiceError, events: result.events, sentAt: Date.now(), durationMs: performance.now() - started };
      appendMessage(sessionId, assistantMessage, undefined, result);
      const archivedTitle = activeSession.title === '新的对话' ? (text || attachmentNames[0]).slice(0, 28) : activeSession.title;
      const completedSession = {
        ...activeSession,
        title: archivedTitle,
        messages: [...activeSession.messages, userMessage, assistantMessage],
        updatedAt: assistantMessage.sentAt,
      };
      const completedTurns = completedSession.messages.filter((message) => message.role === 'assistant' && typeof message.content === 'string').length;
      const summarizedTurns = Number(memoryConversations.find((conversation) => conversation.id === sessionId)?.summary_turn_count) || 0;
      if (completedTurns - summarizedTurns >= memorySettings.summary_interval_turns) {
        void requestMemorySummaryUpdate({ conversationIds: [sessionId], force: false, sourceSessions: [completedSession] });
      }
    } catch (error) {
      voiceAbort.abort();
      voiceSession?.stop();
      appendMessage(sessionId, { role: 'assistant', error: error.message, events: liveEventsRef.current, sentAt: Date.now(), durationMs: performance.now() - started });
    } finally {
      setBusy(false);
      setBusySessionId(null);
      setPendingQuestion(null);
      pendingQuestionRef.current = null;
      setQuestionResponse({ id: '', answers: {} });
      setAnsweredQuestionId('');
      setQuestionSubmitting(false);
      setLiveEvents(liveEventsRef.current);
      setLiveDraft('');
    }
  };

  const clearConversation = () => {
    const session = createSession();
    setChatState((current) => ({ sessions: [session, ...current.sessions], activeSessionId: session.id }));
    void requestMemorySummaryUpdate({ force: false, sourceSessions: sessions });
  };

  const requestDeleteConversation = (event, sessionId) => {
    event.stopPropagation();
    setPendingDeleteSessionId(sessionId);
  };

  const deleteConversation = () => {
    const sessionId = pendingDeleteSessionId;
    if (!sessionId) return;
    const deletedSession = sessions.find((session) => session.id === sessionId);
    for (const message of deletedSession?.messages || []) {
      for (const ref of message.attachmentRefs || []) void deleteChatAttachment(ref);
    }
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
    setMemoryConversations((current) => current.filter((conversation) => conversation.id !== sessionId));
    void fetch('/api/memory/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'delete', id: sessionId }),
    }).catch(() => {});
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
          <button className="profile-row" onClick={openUserProfile} title="编辑 modules/prompt/SystemPrompt/USER-zh.md"><div className="profile-avatar">{avatars.user ? <img src={avatars.user} alt="" /> : 'W'}</div><span><strong>编辑用户信息</strong><small>USER-zh.md</small></span><Pencil size={15} /></button>
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
              </div> : <div className="message-bubble">
                {message.attachments?.length > 0 && <div className="message-attachments">{message.attachments.map((attachment, attachmentIndex) => <span className="message-attachment" key={`${attachment.name}-${attachmentIndex}`}>
                  {attachment.kind === 'image' ? <ImageIcon size={13} /> : attachment.kind === 'video' ? <Film size={13} /> : <FileText size={13} />}
                  <span>{attachment.name}</span>
                </span>)}</div>}
                {(message.displayContent ?? message.content) && <div className="message-text">{message.displayContent ?? message.content}</div>}
              </div>}
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
            {pendingQuestion && <section className="composer-question" role="dialog" aria-label="ATRI 正在等待回答">
              <strong>{answeredQuestionId === pendingQuestion.id ? '回答已提交' : 'ATRI 需要你回答'}</strong>
              <div className="composer-question-items">
                {pendingQuestion.questions.map((question, index) => {
                  const answer = questionResponse.id === pendingQuestion.id
                    ? questionResponse.answers[question.id] || { selected: [], custom: '' }
                    : { selected: [], custom: '' };
                  const disabled = questionSubmitting || answeredQuestionId === pendingQuestion.id;
                  return <div className="composer-question-item" key={question.id}>
                    <div className="composer-question-heading"><span>{question.header || `问题 ${index + 1}`}</span>{question.multi_select && <small>可多选</small>}</div>
                    <p>{question.question}</p>
                    {question.options.length > 0 && <div className="composer-question-options">
                      {question.options.map((option) => {
                        const selected = answer.selected.includes(option);
                        return <button
                          key={option}
                          type="button"
                          className={selected ? 'is-selected' : ''}
                          aria-pressed={selected}
                          disabled={disabled}
                          onClick={() => setQuestionResponse((current) => {
                            const currentAnswers = current.id === pendingQuestion.id ? current.answers : {};
                            const previous = currentAnswers[question.id] || { selected: [], custom: '' };
                            const nextSelected = question.multi_select
                              ? (selected ? previous.selected.filter((item) => item !== option) : [...previous.selected, option])
                              : (selected ? [] : [option]);
                            return { id: pendingQuestion.id, answers: { ...currentAnswers, [question.id]: { ...previous, selected: nextSelected } } };
                          })}
                        >{option}</button>;
                      })}
                    </div>}
                    <input
                      value={answer.custom}
                      onChange={(event) => setQuestionResponse((current) => {
                        const currentAnswers = current.id === pendingQuestion.id ? current.answers : {};
                        const previous = currentAnswers[question.id] || { selected: [], custom: '' };
                        return { id: pendingQuestion.id, answers: { ...currentAnswers, [question.id]: { ...previous, custom: event.target.value } } };
                      })}
                      onKeyDown={(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void submitQuestionAnswer(); } }}
                      placeholder="补充回答或跳过此题…"
                      aria-label={`问题 ${index + 1} 的补充回答`}
                      disabled={disabled}
                    />
                  </div>;
                })}
              </div>
              <div className="composer-question-actions">
                <small>未填写的问题会作为跳过提交</small>
                <button type="button" disabled={questionSubmitting || answeredQuestionId === pendingQuestion.id} onClick={() => void submitQuestionAnswer()}>
                  <Check size={14} />{questionSubmitting ? '提交中' : answeredQuestionId === pendingQuestion.id ? '已提交' : '提交全部'}
                </button>
              </div>
              {questionError && <small role="alert">{questionError}</small>}
            </section>}
            <textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } }} placeholder={pendingQuestion ? '请先回答上方问题' : runtimeStatus.running ? '给 ATRI 发消息…' : '请先在工作流页启动 Agent'} rows={1} disabled={Boolean(pendingQuestion)} />
            <input
              ref={attachmentInputRef}
              className="chat-attachment-input"
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp,image/gif,image/bmp,video/*,.pdf,.docx,.docm,.xlsx,.xlsm,.pptx,.pptm,.odt,.ods,.odp,.txt,.md,.csv,.tsv,.json,.log,.py,.js,.jsx,.ts,.tsx,.html,.css,.xml,.yaml,.yml,.toml,.ini,.sql,.sh,.rs,.java,.go,.c,.h,.cpp"
              onChange={handleAttachmentChange}
            />
            {(selectedAttachments.length > 0 || attachmentError) && <div className="composer-attachments">
              {selectedAttachments.map((attachment) => <div className="composer-attachment" key={attachment.id}>
                {attachment.kind === 'image' ? <img src={attachment.previewUrl} alt="" /> : attachment.kind === 'video' ? <Film size={14} /> : <FileText size={14} />}
                <span>{attachment.name}</span>
                <button type="button" onClick={() => removeSelectedAttachment(attachment.id)} aria-label={`移除附件：${attachment.name}`} title="移除附件"><X size={13} /></button>
              </div>)}
              {attachmentError && <div className="composer-attachment-error" role="alert">{attachmentError}</div>}
            </div>}
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
              <button
                type="button"
                className="composer-attachment-trigger"
                onClick={() => attachmentInputRef.current?.click()}
                disabled={attachmentBusy || busy || selectedAttachments.length >= ATTACHMENT_LIMIT}
                title="添加图片、视频或文档"
                aria-label="添加附件"
              >{attachmentBusy ? <span className="spinner" /> : <Paperclip size={15} />}</button>
              <span className="composer-hint">Enter 发送 · Shift + Enter 换行</span>
              <button className="send-button" disabled={(!input.trim() && !selectedAttachments.length) || busy || attachmentBusy || contextCompressing || runtimeStatus.loading || !runtimeStatus.running} onClick={sendMessage} title={runtimeStatus.running ? '发送消息' : '先启动工作流'}><ArrowUp size={17} /></button>
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
                aria-label="上下文和记忆设置"
                aria-expanded={contextSettingsOpen}
                title="上下文和记忆设置"
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
          {contextSettingsOpen && <section className="memory-settings" aria-label="会话记忆设置">
            <div className="memory-settings-heading">
              <strong>会话记忆</strong>
              <button type="button" className="memory-update-all" disabled={memorySummaryBusy !== null || memoryConversationItems.length === 0 || !runtimeStatus.running || !activeModel.hasModel} onClick={() => void requestMemorySummaryUpdate({ force: true })}>
                {memorySummaryBusy === 'all' ? <span className="spinner" /> : <RotateCcw size={12} aria-hidden="true" />}
                {memorySummaryBusy === 'all' ? '正在更新' : '更新全部'}
              </button>
            </div>
            <label className="memory-summary-interval"><span>自动摘要间隔</span><span><input type="number" min="1" max="100" value={memorySettings.summary_interval_turns} onChange={(event) => {
              const value = Number(event.target.value);
              setMemorySettings({ summary_interval_turns: Math.min(100, Math.max(1, Number.isFinite(value) ? value : 1)) });
            }} /><small>轮</small></span></label>
            <small className="context-compression-note">普通对话自动保存；工作流试运行不会保存。</small>
            <div className="memory-summary-list">
              {memoryConversationItems.length ? memoryConversationItems.map((conversation) => {
                const localSession = sessions.find((session) => session.id === conversation.id);
                const updating = memorySummaryBusy === conversation.id;
                return <article className="memory-summary-item" key={conversation.id}>
                  <div className="memory-summary-item-copy">
                    <strong title={conversation.title}>{conversation.title || '新的对话'}</strong>
                    <small>{conversation.turn_count || 0} 轮 · {conversation.summary_status === 'pending' ? '待更新' : '已整理'}</small>
                    <p>{conversation.summary || '暂无摘要'}</p>
                  </div>
                  <button type="button" className="memory-summary-refresh" disabled={memorySummaryBusy !== null || !runtimeStatus.running || !activeModel.hasModel} title="重新生成此会话摘要" aria-label={`重新生成摘要：${conversation.title || '新的对话'}`} onClick={() => void requestMemorySummaryUpdate({ conversationIds: [conversation.id], force: true, sourceSessions: localSession ? [localSession] : [] })}>
                    {updating ? <span className="spinner" /> : <RotateCcw size={13} aria-hidden="true" />}
                  </button>
                </article>;
              }) : <small className="memory-summary-empty">还没有已保存的会话。</small>}
            </div>
            {memorySummaryFeedback && <small className={`context-compression-feedback is-${memorySummaryFeedback.type}`} role={memorySummaryFeedback.type === 'error' ? 'alert' : 'status'}>{memorySummaryFeedback.text}</small>}
            {memoryConversationItems.length > 0 && (!runtimeStatus.running || !activeModel.hasModel) && <small className="context-compression-note">启动含语言模型的工作流后，才能生成会话摘要。</small>}
          </section>}
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
          <label className={`sandbox-execution-toggle ${sandboxSettings.allow_command_execution ? 'is-enabled' : ''}`}>
            <input type="checkbox" checked={sandboxSettings.allow_command_execution} onChange={(event) => { setSandboxSettings((current) => ({ ...current, allow_command_execution: event.target.checked })); setSandboxPermissionError(''); setSandboxPermissionSaved(false); }} />
            <span><strong>允许命令和 MCP 工具执行</strong><small>开启后，模型可以自动调用；命令仍受上方文件权限约束。</small></span>
          </label>
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
        <header><div><span className="eyebrow">USER PROFILE</span><h2 id="profile-editor-title">编辑用户信息</h2><span className="profile-file-path">modules/prompt/SystemPrompt/USER-zh.md</span></div><button className="icon-button" disabled={profileSaving} onClick={() => setProfileOpen(false)} title="关闭"><X size={17} /></button></header>
        <textarea spellCheck="false" value={profileText} onChange={(event) => { setProfileText(event.target.value); setProfileSaved(false); }} disabled={!profileLoaded || profileLoading || profileSaving} placeholder={profileLoading ? '正在读取 USER-zh.md…' : ''} />
        <footer><div className={profileError ? 'profile-editor-error' : 'profile-editor-status'}>{profileError || (profileSaved ? '已保存到项目中的 USER-zh.md' : '修改将直接写入项目文件')}</div><button className="primary-button" onClick={saveUserProfile} disabled={!profileLoaded || profileLoading || profileSaving}>{profileSaving ? <span className="spinner" /> : <Save size={15} />}{profileSaving ? '保存中…' : '保存'}</button></footer>
      </section></div>}
      {pendingDeleteSession && <div className="chat-delete-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setPendingDeleteSessionId(null); }}><section className="chat-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="chat-delete-title" aria-describedby="chat-delete-description" onKeyDown={(event) => { if (event.key === 'Escape') setPendingDeleteSessionId(null); }}>
        <h2 id="chat-delete-title">删除对话</h2>
        <p id="chat-delete-description">确定删除“{pendingDeleteSession.title || '新的对话'}”吗？删除后无法恢复。</p>
        <div className="chat-delete-actions"><button className="secondary-button" autoFocus onClick={() => setPendingDeleteSessionId(null)}>取消</button><button className="danger-button" onClick={deleteConversation}><Trash2 size={15} />删除</button></div>
      </section></div>}
    </div>
  );
}

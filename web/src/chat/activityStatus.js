const TOOL_LIST = 'atri_list_available_tools';
const TOOL_USAGE = 'atri_get_tool_usage';

function toolArguments(value) {
  if (typeof value !== 'string') return value || {};
  try { return JSON.parse(value); }
  catch { return {}; }
}

function toolIdentity(data, language) {
  const name = String(data.name || '');
  const argumentsValue = toolArguments(data.arguments);
  const target = String(data.target || argumentsValue.tool_name || '');
  const kind = data.kind || (name.startsWith('skill__') ? 'skill' : name.startsWith('mcp:') ? 'mcp' : 'tool');
  const displayName = target || name.replace(/^(?:tool|mcp|skill):|^skill__/, '') || (language === 'en' ? 'tool' : '工具');
  return { name, kind, displayName };
}

function toolStatus(data, language, completed = false) {
  const { name, kind, displayName } = toolIdentity(data, language);
  if (completed) {
    if (data.status === 'error' || data.status === 'denied') return language === 'en'
      ? `${displayName} failed; handling the result…`
      : `${displayName} 未完成，正在处理结果…`;
    return language === 'en' ? `${displayName} finished; processing the result…` : `${displayName} 已完成，正在处理结果…`;
  }
  if (name === TOOL_LIST) return language === 'en' ? 'Checking available tools…' : '正在查看可用工具…';
  if (name === TOOL_USAGE) return language === 'en' ? `Reading how to use ${displayName}…` : `正在查看 ${displayName} 的使用方式…`;
  if (kind === 'skill') return language === 'en' ? `Reading skill ${displayName}…` : `正在查看技能 ${displayName}…`;
  if (kind === 'mcp') return language === 'en' ? `Calling MCP tool ${displayName}…` : `正在调用 MCP 工具 ${displayName}…`;
  return language === 'en' ? `Calling tool ${displayName}…` : `正在调用工具 ${displayName}…`;
}

export function getRecentActions(events, language = 'zh') {
  const actions = [];
  for (let index = events.length - 1; index >= 0 && actions.length < 2; index -= 1) {
    const event = events[index];
    if (event.event_type !== 'tool_completed' && event.event_type !== 'tool_call_denied') continue;
    const data = event.data || {};
    const { name, kind, displayName } = toolIdentity(data, language);
    const label = name === TOOL_LIST
      ? language === 'en' ? 'Checked available tools' : '已查看可用工具'
      : name === TOOL_USAGE
        ? language === 'en' ? `Read ${displayName} usage` : `已查看 ${displayName} 的使用方式`
        : kind === 'skill'
          ? language === 'en' ? `Read skill ${displayName}` : `已查看技能 ${displayName}`
          : kind === 'mcp'
            ? language === 'en' ? `Called MCP tool ${displayName}` : `已调用 MCP 工具 ${displayName}`
            : language === 'en' ? `Called tool ${displayName}` : `已调用工具 ${displayName}`;
    actions.push({ id: `${data.call_id || name}-${index}`, label, failed: data.status === 'error' || data.status === 'denied' });
  }
  return actions.reverse();
}

function nodeStatus(node, language) {
  const type = node?.type || '';
  const config = node?.data?.config || {};
  const label = node?.data?.label || type;
  if (type === 'prompt.markdown_file') return language === 'en'
    ? `Reading prompt ${config.file || label}…` : `正在读取提示词 ${config.file || label}…`;
  const known = {
    'prompt.text': ['正在准备提示词…', 'Preparing prompt…'],
    'prompt.join': ['正在联结提示词…', 'Joining prompts…'],
    'memory.provider': ['正在读取记忆…', 'Reading memory…'],
    'skills.provider': ['正在读取技能目录…', 'Reading skill catalog…'],
    'tools.provider': ['正在读取工具目录…', 'Reading tool catalog…'],
    'context.merge': ['正在联结上下文…', 'Assembling context…'],
    'capability.schema_merge': ['正在整理能力使用方式…', 'Preparing capability definitions…'],
    'llm.gguf_loader': ['正在准备本地模型…', 'Preparing local model…'],
    'llm.openai_loader': ['正在准备 API 模型…', 'Preparing API model…'],
    'llm.chat': ['正在请求模型…', 'Requesting model response…'],
    'control.response_parser': ['正在解析模型回复…', 'Parsing model response…'],
    'capability.dispatch': ['正在处理能力请求…', 'Handling capability calls…'],
    'tools.dispatch': ['正在处理能力请求…', 'Handling capability calls…'],
    'control.loop': ['正在判断下一步…', 'Choosing next step…'],
    'react.loop': ['正在判断下一步…', 'Choosing next step…'],
    'core.chat_input': ['正在读取消息…', 'Reading message…'],
    'core.chat_output': ['正在整理回复…', 'Preparing answer…'],
  };
  if (known[type]) return known[type][language === 'en' ? 1 : 0];
  return language === 'en' ? `Running ${label || 'workflow'}…` : `正在运行 ${label || '工作流'}…`;
}

export function getChatActivity(events, workflow, language = 'zh') {
  const nodes = new Map((workflow?.nodes || []).map((node) => [node.id, node]));
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const data = event.data || {};
    switch (event.event_type) {
      case 'tool_call_requested': return toolStatus(data, language);
      case 'tool_completed':
      case 'tool_call_denied': return toolStatus(data, language, true);
      case 'model_request':
      case 'model_thinking': return language === 'en' ? 'Waiting for the model…' : '正在等待模型回复…';
      case 'model_response':
      case 'response_parsed': {
        const call = data.tool_calls?.[0];
        if (call) return toolStatus({ name: call.function?.name, arguments: call.function?.arguments }, language);
        return language === 'en' ? 'Parsing model response…' : '正在解析模型回复…';
      }
      case 'tool_call_adapted': {
        const call = data.calls?.[0];
        if (call) return toolStatus({ name: call.function?.name, arguments: call.function?.arguments }, language);
        break;
      }
      case 'loop_decision':
        if (data.continue) return language === 'en' ? 'Continuing with the next step…' : '正在继续下一步…';
        break;
      case 'node_started': return nodeStatus(nodes.get(event.node_id), language);
      case 'workflow_started': return language === 'en' ? 'Preparing workflow…' : '正在准备工作流…';
      default: break;
    }
  }
  return language === 'en' ? 'Preparing workflow…' : '正在准备工作流…';
}

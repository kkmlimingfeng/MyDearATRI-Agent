import {
  AudioLines, BrainCircuit, Boxes, Cable, CircleDot, Database, FileText, GitBranch, Merge,
  MessageSquareText, Wrench,
} from 'lucide-react';

export const categoryMeta = {
  io: { label: '输入与输出', color: 'mint', hex: '#57aa90', icon: MessageSquareText },
  prompt: { label: '提示词', color: 'coral', hex: '#d97968', icon: FileText },
  model: { label: '模型', color: 'blue', hex: '#6a91c5', icon: CircleDot },
  audio: { label: '音频', color: 'amber', hex: '#cb9c50', icon: AudioLines },
  memory: { label: '记忆', color: 'amber', hex: '#cb9c50', icon: Database },
  skills: { label: '技能', color: 'green', hex: '#70a276', icon: FileText },
  tools: { label: '工具', color: 'violet', hex: '#8b7bb7', icon: Wrench },
  context: { label: '上下文', color: 'cyan', hex: '#55a1a2', icon: Merge },
  control: { label: '流程控制', color: 'slate', hex: '#84928c', icon: GitBranch },
  runtime: { label: '兼容运行时', color: 'coral', hex: '#d97968', icon: BrainCircuit },
  retrieval: { label: '检索', color: 'cyan', hex: '#55a1a2', icon: Boxes },
};

const textOutput = { id: 'text', label: 'text', type: 'text' };
const promptOutput = { id: 'prompt', label: 'prompt', type: 'prompt' };

export const nodeCatalog = [
  { type: 'core.chat_input', label: '对话输入', category: 'io', inputs: [], outputs: [{ id: 'message', label: 'message', type: 'text' }], defaults: { placeholder: '说点什么…', debug_input: '你好，介绍一下你自己。' }, moduleId: '', preview: '来自用户的消息会从这里进入工作流。' },
  { type: 'prompt.markdown_file', label: 'Markdown 提示词', category: 'prompt', inputs: [], outputs: [promptOutput], defaults: { file: 'AGENT.md', source: 'modules/prompt/SystemPrompt' }, moduleId: 'prompt', preview: '从 Markdown 文件读取提示词片段。' },
  { type: 'prompt.provider', label: '旧版提示词提供方', category: 'prompt', inputs: [], outputs: [promptOutput], defaults: { prompt_name: 'default' }, moduleId: 'prompt', legacy: true, preview: '旧版工作流兼容节点。' },
  { type: 'prompt.text', label: '文本提示词', category: 'prompt', inputs: [], outputs: [promptOutput], defaults: { text: '你是一个可靠、自然的陪伴型 Agent。' }, moduleId: '', preview: '在节点内直接编辑一段提示词。' },
  { type: 'prompt.join', label: '提示词联结', category: 'prompt', inputs: [{ id: 'prompt_a', label: '片段 A', type: 'prompt', optional: true }, { id: 'prompt_b', label: '片段 B', type: 'prompt', optional: true }, { id: 'prompt_c', label: '片段 C', type: 'prompt', optional: true }, { id: 'prompt_d', label: '片段 D', type: 'prompt', optional: true }], outputs: [promptOutput], defaults: { separator: '\n\n' }, moduleId: '', preview: '按顺序拼接多个提示词片段。' },
  { type: 'memory.provider', label: '记忆读取', category: 'memory', inputs: [], outputs: [{ id: 'memory', label: 'memory', type: 'memory' }], defaults: { strategy: 'markdown' }, moduleId: 'memory', preview: '长期记忆内容将在这里进入上下文。' },
  { type: 'skills.provider', label: '技能目录', category: 'skills', inputs: [], outputs: [{ id: 'skills', label: 'skills', type: 'skills' }, { id: 'schemas', label: '技能使用方式', type: 'tool_schemas', optional: true }, { id: 'executor', label: '技能执行器', type: 'skill_executor', optional: true }], defaults: { source: 'modules/skills' }, moduleId: 'skills', preview: 'recommend_travel\nfile_operations' },
  { type: 'tools.provider', label: '工具箱', category: 'tools', inputs: [], outputs: [{ id: 'tools', label: '工具目录', type: 'tools' }, { id: 'schemas', label: '工具发现方式', type: 'tool_schemas', optional: true }, { id: 'executor', label: '工具执行器', type: 'tool_executor', optional: true }], defaults: { approval: 'risk-based' }, moduleId: 'tools', preview: '通过工具发现能力查询可用工具，并按需读取使用方式。' },
  { type: 'capability.schema_merge', label: '能力使用方式', category: 'tools', inputs: [{ id: 'schemas_a', label: '方式 A', type: 'tool_schemas', optional: true }, { id: 'schemas_b', label: '方式 B', type: 'tool_schemas', optional: true }, { id: 'schemas_c', label: '方式 C', type: 'tool_schemas', optional: true }, { id: 'schemas_d', label: '方式 D', type: 'tool_schemas', optional: true }, { id: 'loop', label: '新上下文', type: 'loop', optional: true }], outputs: [{ id: 'schemas', label: '能力使用方式', type: 'tool_schemas' }], defaults: {}, moduleId: '', preview: '初始提供工具发现能力；读取具体工具用法后，将其定义加入下一轮。' },
  { type: 'context.merge', label: '上下文联结', category: 'context', inputs: [{ id: 'skills', label: '技能目录', type: 'skills', optional: true }, { id: 'tools', label: '工具箱', type: 'tools', optional: true }, { id: 'mcp', label: 'MCP', type: 'mcp', optional: true }, { id: 'memory', label: '记忆', type: 'memory', optional: true }, { id: 'tool_results', label: '工具结果', type: 'tool_results', optional: true }, { id: 'context_a', label: '上下文 A', type: 'context', optional: true }, { id: 'context_b', label: '上下文 B', type: 'context', optional: true }, { id: 'loop', label: '新上下文', type: 'loop', optional: true }], outputs: [{ id: 'context', label: '上下文', type: 'context' }, { id: 'tool_schemas', label: '能力使用方式', type: 'tool_schemas', optional: true }, { id: 'loop', label: '下一轮上下文', type: 'loop', optional: true }], defaults: {}, moduleId: '', preview: '汇总技能、工具、MCP、记忆和循环结果，组织下一轮上下文。' },
  { type: 'llm.gguf_loader', label: 'GGUF 运行时模型', category: 'model', inputs: [], outputs: [{ id: 'llm', label: '模型', type: 'llm' }], defaults: { model: 'qwen3-1.7b-q4km', mmproj: '', n_gpu_layers: -1 }, moduleId: 'llm', preview: '主模型必选；视觉模型可选 mmproj，纯文本模型留空。', implementation: 'modules.llm.gguf_llm.GGUFLLM' },
  { type: 'llm.openai_loader', label: 'API 运行时模型', category: 'model', inputs: [], outputs: [{ id: 'llm', label: '模型', type: 'llm' }], defaults: { model: 'qwen3.5-35b' }, moduleId: 'llm', preview: '选择已配置的 API 模型；运行时连接提供商。', implementation: 'modules.llm.openai_llm.OpenAILLM' },
  { type: 'llm.provider', label: '旧版模型提供方', category: 'model', inputs: [], outputs: [{ id: 'llm', label: '模型', type: 'llm' }], defaults: { model: 'qwen3-1.7b-q4km' }, moduleId: 'llm', legacy: true, preview: '旧版工作流兼容节点。' },
  { type: 'audio.tts_model', label: 'Qwen3-TTS 音频模型', category: 'audio', inputs: [{ id: 'text', label: '文本', type: 'text' }], outputs: [{ id: 'audio', label: '语音', type: 'audio' }], defaults: { model: 'qwen3-0.6b-q8', language: 'Chinese', reference: 'atri' }, configSchema: { type: 'object', properties: { model: { type: 'string', title: 'TTS 模型', default: 'qwen3-0.6b-q8' }, language: { type: 'string', title: '目标语言', enum: ['Chinese', 'Japanese', 'English'], default: 'Chinese' }, reference: { type: 'string', title: '参考音色', default: 'atri' } } }, preview: '将连接的文本合成为流式语音。' },
  { type: 'llm.chat', label: '模型对话', category: 'model', inputs: [{ id: 'message', label: '消息', type: 'text' }, { id: 'prompt', label: '提示词', type: 'prompt' }, { id: 'context', label: '上下文', type: 'context', optional: true }, { id: 'llm', label: '模型', type: 'llm' }, { id: 'tool_schemas', label: '能力使用方式', type: 'tool_schemas', optional: true }, { id: 'loop', label: '下一轮上下文', type: 'loop', optional: true }], outputs: [{ id: 'answer', label: '回答', type: 'text' }, { id: 'response', label: '模型响应', type: 'model_response', optional: true }], defaults: { reasoning_effort: 'auto' }, configSchema: { type: 'object', properties: { reasoning_effort: { type: 'string', title: '默认思考强度（API）', enum: ['auto', 'minimal', 'low', 'medium', 'high', 'xhigh'], default: 'auto' } } }, moduleId: '', preview: '接收消息、提示词和上下文，返回模型回答。' },
  { type: 'control.response_parser', label: '响应解析', category: 'control', inputs: [{ id: 'response', label: '模型响应', type: 'model_response' }], outputs: [{ id: 'answer', label: '最终回答', type: 'text', optional: true }, { id: 'tool_calls', label: '能力调用', type: 'tool_calls', optional: true }, { id: 'response', label: '模型响应', type: 'model_response', optional: true }], defaults: {}, moduleId: '', preview: '最终回答直接输出；调用能力时同时传递调用指令和供循环使用的模型响应。', hideOutputPreview: true },
  { type: 'capability.dispatch', label: '能力分发', category: 'tools', inputs: [{ id: 'tool_calls', label: '能力调用', type: 'tool_calls' }, { id: 'skill_executor', label: '技能执行器', type: 'skill_executor', optional: true }, { id: 'tool_executor', label: '工具执行器', type: 'tool_executor', optional: true }, { id: 'skills', label: '兼容技能目录', type: 'skills', optional: true, hidden: true }, { id: 'tools', label: '兼容工具目录', type: 'tools', optional: true, hidden: true }, { id: 'mcp', label: 'MCP', type: 'mcp', optional: true }, { id: 'usage', label: '可调用方式', type: 'tool_schemas', optional: true }, { id: 'handlers', label: '扩展能力', type: 'capability_handlers', optional: true }], outputs: [{ id: 'tool_results', label: '执行结果', type: 'tool_results' }], defaults: {}, moduleId: '', preview: '接收能力调用和执行器；只有已读取用法的工具可被实际执行。' },
  { type: 'control.loop', label: '循环控制', category: 'control', inputs: [{ id: 'response', label: '模型响应', type: 'model_response', optional: true }, { id: 'tool_results', label: '反馈结果', type: 'tool_results', optional: true }, { id: 'value', label: '条件值', type: 'any', optional: true }], outputs: [{ id: 'loop', label: '新上下文', type: 'loop' }], defaults: { max_iterations: 5 }, configSchema: { type: 'object', properties: { max_iterations: { type: 'integer', title: '最大循环次数', minimum: 1, maximum: 500, default: 5 } } }, moduleId: '', preview: '根据结果和条件控制是否生成下一轮上下文。' },
  { type: 'control.branch', label: '条件分支', category: 'control', inputs: [{ id: 'value', label: '条件值', type: 'any' }], outputs: [{ id: 'true', label: '满足', type: 'any', optional: true }, { id: 'false', label: '不满足', type: 'any', optional: true }], defaults: { condition: 'truthy', compare_to: '' }, moduleId: '', preview: '把数据按条件送到不同出口，可用于规划和反思流程。' },
  { type: 'state.accumulator', label: '状态累积', category: 'context', inputs: [{ id: 'state', label: '已有状态', type: 'context', optional: true }, { id: 'item', label: '新结果', type: 'any', optional: true }], outputs: [{ id: 'state', label: '新状态', type: 'context' }], defaults: {}, moduleId: '', preview: '把计划、观察、工具结果或反思记录追加到状态。' },
  { type: 'core.chat_output', label: '回复输出', category: 'io', inputs: [{ id: 'answer', label: 'answer', type: 'text' }, { id: 'voice', label: '语音输出', labelZh: '语音输出', labelEn: 'Voice output', type: 'audio', optional: true }, { id: 'animation', label: '动画输出', labelZh: '动画输出', labelEn: 'Animation output', type: 'animation', optional: true }], outputs: [{ id: 'answer', label: 'answer', type: 'text', hidden: true }, { id: 'voice', label: 'voice', type: 'audio', optional: true, hidden: true }, { id: 'animation', label: 'animation', type: 'animation', optional: true, hidden: true }], defaults: { show_trace: false }, moduleId: '', preview: '工作流最终输出。' },
  // 保留旧版 JSON 的兼容节点，新工作流使用 llm.chat。
  { type: 'agent.react_runtime', label: '兼容 ReAct 运行时', category: 'runtime', inputs: [{ id: 'message', label: 'message', type: 'text' }, { id: 'llm', label: 'llm', type: 'llm' }, { id: 'prompt', label: 'prompt', type: 'prompt' }, { id: 'memory', label: 'memory', type: 'memory', optional: true }, { id: 'skills', label: 'skills', type: 'skills', optional: true }, { id: 'tools', label: 'tools', type: 'tools', optional: true }], outputs: [{ id: 'answer', label: 'answer', type: 'text' }, { id: 'trace', label: 'trace', type: 'trace' }], defaults: { max_iterations: 5, display_mode: 'normal', prompt_name: 'default' }, moduleId: '', preview: '仅用于兼容旧版工作流。' },
  { type: 'react.response_router', label: '兼容：响应解析与分流', category: 'runtime', inputs: [{ id: 'response', label: '结构化响应', type: 'model_response' }], outputs: [{ id: 'tool_calls', label: '工具 / 技能调用', type: 'tool_calls', optional: true }, { id: 'answer', label: '最终回答', type: 'text', optional: true }], defaults: {}, moduleId: '', preview: '旧版工作流兼容节点。', hideOutputPreview: true, legacy: true },
  { type: 'tools.dispatch', label: '兼容：工具 / 技能执行', category: 'runtime', inputs: [{ id: 'tool_calls', label: '工具 / 技能调用', type: 'tool_calls' }], outputs: [{ id: 'tool_results', label: '执行结果', type: 'tool_results' }], defaults: {}, moduleId: '', preview: '旧版工作流兼容节点。', legacy: true },
  { type: 'react.loop', label: '兼容：ReAct 循环', category: 'runtime', inputs: [{ id: 'response', label: '模型响应', type: 'model_response', optional: true }, { id: 'tool_results', label: '工具结果', type: 'tool_results', optional: true }], outputs: [{ id: 'loop', label: '继续 / 结束', type: 'loop' }], defaults: { max_iterations: 5 }, moduleId: '', preview: '旧版工作流兼容节点。', legacy: true },
  { type: 'retrieval.vector_store', label: '向量检索', category: 'retrieval', inputs: [{ id: 'query', label: 'query', type: 'text' }], outputs: [textOutput], defaults: { provider: 'local', top_k: 5 }, moduleId: '', preview: '从向量库检索相关上下文。' },
];

export function hydrateNodeCatalog(remoteNodes = []) {
  const existingByType = new Map(nodeCatalog.map((node) => [node.type, node]));
  const mergedByType = new Map(nodeCatalog.map((node) => [node.type, node]));
  for (const remote of remoteNodes) {
    if (!remote?.type) continue;
    const existing = existingByType.get(remote.type) || {};
    const mapPorts = (direction) => (remote[direction] || []).map((port) => {
      const knownPort = existing[direction]?.find((item) => item.id === port.name);
      return {
        id: port.name,
        label: knownPort?.label || port.description || port.name,
        labelZh: port.label_zh || knownPort?.labelZh,
        labelEn: port.label_en || knownPort?.labelEn,
        type: port.type || 'any',
        optional: port.required === false,
        hidden: port.hidden || knownPort?.hidden || false,
      };
    });
    const configSchema = Object.keys(remote.config_schema?.properties || {}).length ? remote.config_schema : existing.configSchema || remote.config_schema || { type: 'object', properties: {} };
    const schemaDefaults = Object.fromEntries(Object.entries(configSchema.properties || {})
      .filter(([, field]) => Object.hasOwn(field, 'default'))
      .map(([key, field]) => [key, field.default]));
    mergedByType.set(remote.type, {
      ...existing,
      type: remote.type,
      label: remote.title || existing.label || remote.type,
      category: remote.category || existing.category || 'control',
      description: remote.description || existing.description || '',
      inputs: mapPorts('inputs'),
      outputs: mapPorts('outputs'),
      defaults: { ...schemaDefaults, ...(existing.defaults || {}), ...(remote.defaults || {}) },
      moduleId: remote.module_id ?? existing.moduleId ?? '',
      preview: remote.preview || existing.preview || remote.description || '',
      implementation: remote.implementation || existing.implementation,
      hideOutputPreview: existing.hideOutputPreview || false,
      configSchema,
    });
  }
  const next = [...mergedByType.values()];
  nodeCatalog.splice(0, nodeCatalog.length, ...next);
  return nodeCatalog;
}

export const modelChoices = [
  { value: 'qwen3-1.7b-q4km', label: 'qwen3-1.7b-q4km · GGUF', type: 'gguf' },
  { value: 'qwen3.5-35b', label: 'qwen3.5-35b · API', type: 'api' },
  { value: 'qwen3.5-27b', label: 'qwen3.5-27b · API', type: 'api' },
  { value: 'qwen3.5-122b', label: 'qwen3.5-122b · API', type: 'api' },
  { value: 'qwen3.5-397b', label: 'qwen3.5-397b · API', type: 'api' },
  { value: 'gpt4o', label: 'gpt4o · API', type: 'api' },
];

export function getNodeDefinition(type) {
  return nodeCatalog.find((item) => item.type === type) ?? nodeCatalog.find((item) => item.type === 'agent.react_runtime');
}

import {
  BrainCircuit, Boxes, Cable, CircleDot, Database, FileText, GitBranch, Merge,
  MessageSquareText, Wrench,
} from 'lucide-react';

export const categoryMeta = {
  io: { label: '输入与输出', color: 'mint', hex: '#57aa90', icon: MessageSquareText },
  prompt: { label: '提示词', color: 'coral', hex: '#d97968', icon: FileText },
  model: { label: '模型', color: 'blue', hex: '#6a91c5', icon: CircleDot },
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
  { type: 'skills.provider', label: '技能目录', category: 'skills', inputs: [], outputs: [{ id: 'skills', label: 'skills', type: 'skills' }], defaults: { source: 'modules/skills' }, moduleId: 'skills', preview: 'recommend_travel\nfile_operations' },
  { type: 'tools.provider', label: '工具箱', category: 'tools', inputs: [], outputs: [{ id: 'tools', label: 'tools', type: 'tools' }], defaults: { approval: 'risk-based' }, moduleId: 'tools', preview: 'get_weather\nget_attraction\nget_current_*\nexec_sandbox_cmd' },
  { type: 'context.merge', label: '上下文联结', category: 'context', inputs: [{ id: 'memory', label: 'memory', type: 'memory', optional: true }, { id: 'skills', label: 'skills', type: 'skills', optional: true }, { id: 'tools', label: 'tools', type: 'tools', optional: true }], outputs: [{ id: 'context', label: 'context', type: 'context' }], defaults: {}, moduleId: '', preview: '把记忆、技能和工具描述汇总成上下文。' },
  { type: 'llm.gguf_loader', label: 'GGUF 运行时模型', category: 'model', inputs: [], outputs: [{ id: 'llm', label: '模型', type: 'llm' }], defaults: { model: 'qwen3-1.7b-q4km', mmproj: '', n_gpu_layers: -1 }, moduleId: 'llm', preview: '主模型必选；视觉模型可选 mmproj，纯文本模型留空。', implementation: 'modules.llm.gguf_llm.GGUFLLM' },
  { type: 'llm.openai_loader', label: 'API 运行时模型', category: 'model', inputs: [], outputs: [{ id: 'llm', label: '模型', type: 'llm' }], defaults: { model: 'qwen3.5-35b', base_url: '' }, moduleId: 'llm', preview: '首次运行时建立 API 模块；编辑画布不会发起请求。', implementation: 'modules.llm.openai_llm.OpenAILLM' },
  { type: 'llm.provider', label: '旧版模型提供方', category: 'model', inputs: [], outputs: [{ id: 'llm', label: '模型', type: 'llm' }], defaults: { model: 'qwen3-1.7b-q4km' }, moduleId: 'llm', legacy: true, preview: '旧版工作流兼容节点。' },
  { type: 'llm.chat', label: '模型对话', category: 'model', inputs: [{ id: 'message', label: '消息', type: 'text' }, { id: 'prompt', label: '提示词', type: 'prompt' }, { id: 'context', label: '上下文', type: 'context', optional: true }, { id: 'llm', label: '模型', type: 'llm' }, { id: 'loop', label: '循环控制', type: 'loop', optional: true }], outputs: [{ id: 'answer', label: 'answer', type: 'text' }, { id: 'trace', label: 'trace', type: 'trace', optional: true }, { id: 'response', label: '结构化响应', type: 'model_response', optional: true }], defaults: { max_iterations: 5, display_mode: 'normal' }, moduleId: '', preview: '接收消息、提示词和上下文，返回模型回答。' },
  { type: 'react.response_router', label: '响应解析与分流', category: 'control', inputs: [{ id: 'response', label: '结构化响应', type: 'model_response' }], outputs: [{ id: 'tool_calls', label: '工具 / 技能调用', type: 'tool_calls', optional: true }, { id: 'answer', label: '最终回答', type: 'text', optional: true }], defaults: {}, moduleId: '', preview: '解析模型结构化响应；存在调用时分发能力，无调用时送出最终回答。', hideOutputPreview: true },
  { type: 'tools.dispatch', label: '工具 / 技能执行', category: 'tools', inputs: [{ id: 'tool_calls', label: '工具 / 技能调用', type: 'tool_calls' }], outputs: [{ id: 'tool_results', label: '执行结果', type: 'tool_results' }], defaults: {}, moduleId: '', preview: '运行后显示每个工具的执行状态、结果和错误，并把结果反馈给下一轮模型。' },
  { type: 'react.loop', label: 'ReAct 循环', category: 'control', inputs: [{ id: 'trace', label: '推理轨迹', type: 'trace' }, { id: 'tool_results', label: '工具结果', type: 'tool_results', optional: true }], outputs: [{ id: 'loop', label: '继续 / 结束', type: 'loop' }], defaults: { max_iterations: 5 }, moduleId: '', preview: '工具调用完成后把结果交给下一轮模型推理，并受最大轮数限制。' },
  { type: 'core.chat_output', label: '回复输出', category: 'io', inputs: [{ id: 'answer', label: 'answer', type: 'text' }], outputs: [], defaults: { show_trace: false }, moduleId: '', preview: '工作流最终输出。' },
  // 保留旧版 JSON 的兼容节点，新工作流使用 llm.chat。
  { type: 'agent.react_runtime', label: '兼容 ReAct 运行时', category: 'runtime', inputs: [{ id: 'message', label: 'message', type: 'text' }, { id: 'llm', label: 'llm', type: 'llm' }, { id: 'prompt', label: 'prompt', type: 'prompt' }, { id: 'memory', label: 'memory', type: 'memory', optional: true }, { id: 'skills', label: 'skills', type: 'skills', optional: true }, { id: 'tools', label: 'tools', type: 'tools', optional: true }], outputs: [{ id: 'answer', label: 'answer', type: 'text' }, { id: 'trace', label: 'trace', type: 'trace' }], defaults: { max_iterations: 5, display_mode: 'normal', prompt_name: 'default' }, moduleId: '', preview: '仅用于兼容旧版工作流。' },
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
        type: port.type || 'any',
        optional: port.required === false,
      };
    });
    const configSchema = remote.config_schema || existing.configSchema || { type: 'object', properties: {} };
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

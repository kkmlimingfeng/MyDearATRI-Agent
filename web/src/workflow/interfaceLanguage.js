import { useEffect, useState } from 'react';

const LANGUAGE_KEY = 'atri.interface.language';
const LANGUAGE_EVENT = 'atri-interface-language-change';
let fallbackLanguage = 'zh';

const portNames = {
  answer: ['回答', 'Answer'], context: ['上下文', 'Context'], context_a: ['上下文 A', 'Context A'], context_b: ['上下文 B', 'Context B'],
  false: ['不满足', 'False'], handlers: ['扩展能力', 'Capability handlers'], item: ['新结果', 'New item'],
  llm: ['模型', 'Model'], loop: ['新上下文', 'Next context'], mcp: ['MCP', 'MCP'], memory: ['记忆', 'Memory'],
  message: ['消息', 'Message'], prompt: ['提示词', 'Prompt'], prompt_a: ['片段 A', 'Part A'],
  prompt_b: ['片段 B', 'Part B'], prompt_c: ['片段 C', 'Part C'], prompt_d: ['片段 D', 'Part D'],
  query: ['查询', 'Query'], response: ['模型响应', 'Model response'], schemas: ['能力使用方式', 'Capability usage'],
  schemas_a: ['方式 A', 'Usage A'], schemas_b: ['方式 B', 'Usage B'], schemas_c: ['方式 C', 'Usage C'],
  schemas_d: ['方式 D', 'Usage D'], skills: ['技能目录', 'Skills'], state: ['状态', 'State'],
  text: ['文本', 'Text'], tool_calls: ['能力调用', 'Capability calls'], tool_results: ['执行结果', 'Execution results'],
  skill_executor: ['技能执行器', 'Skill executor'], tool_executor: ['工具执行器', 'Tool executor'],
  usage: ['可调用方式', 'Available usage'],
  tool_schemas: ['能力使用方式', 'Capability usage'], tools: ['工具箱', 'Tools'], trace: ['执行轨迹', 'Execution trace'],
  true: ['满足', 'True'], value: ['条件值', 'Condition value'],
};

const nodePortNames = {
  'llm.chat:trace': ['本轮响应', 'Current response'],
  'control.loop:trace': ['本轮响应', 'Current response'],
  'react.loop:trace': ['本轮响应', 'Current response'],
  'skills.provider:schemas': ['技能使用方式', 'Skill usage'],
  'tools.provider:schemas': ['工具发现方式', 'Tool discovery'],
  'tools.provider:tools': ['工具目录', 'Tool catalog'],
  'tools.provider:executor': ['工具执行器', 'Tool executor'],
  'skills.provider:executor': ['技能执行器', 'Skill executor'],
  'context.merge:loop': ['新上下文', 'Next context'],
  'llm.chat:loop': ['下一轮上下文', 'Next context'],
  'control.response_parser:answer': ['最终回答', 'Final answer'],
  'react.response_router:answer': ['最终回答', 'Final answer'],
};

function readLanguage() {
  try { return localStorage.getItem(LANGUAGE_KEY) === 'en' ? 'en' : 'zh'; }
  catch { return fallbackLanguage; }
}

export function useInterfaceLanguage() {
  const [language, setLocalLanguage] = useState(readLanguage);
  useEffect(() => {
    const sync = () => setLocalLanguage(readLanguage());
    window.addEventListener(LANGUAGE_EVENT, sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(LANGUAGE_EVENT, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);
  const setLanguage = (value) => {
    const next = value === 'en' ? 'en' : 'zh';
    fallbackLanguage = next;
    try { localStorage.setItem(LANGUAGE_KEY, next); } catch { /* Language still works for this page. */ }
    setLocalLanguage(next);
    window.dispatchEvent(new Event(LANGUAGE_EVENT));
  };
  return [language, setLanguage];
}

export function portLabel(nodeType, port, language) {
  const names = nodePortNames[`${nodeType}:${port.id}`] || portNames[port.id];
  if (language === 'en') return port.labelEn || names?.[1] || port.id.replaceAll('_', ' ');
  return port.labelZh || names?.[0] || port.label || port.id;
}

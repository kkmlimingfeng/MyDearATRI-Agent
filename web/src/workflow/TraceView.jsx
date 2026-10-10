import { useState } from 'react';

const LANGUAGE_KEY = 'atri.trace.language';

const labels = {
  workflow_started: ['开始处理消息', 'Workflow started'], node_output: ['节点输出', 'Node output'],
  response_parsed: ['解析模型响应', 'Parse model response'], response_routed_to_tools: ['分发工具 / 技能调用', 'Dispatch tool / skill calls'], response_routed_to_answer: ['分发最终回答', 'Dispatch final answer'],
  model_loaded: ['加载模型', 'Model loaded'], message_context_ready: ['联结对话上下文', 'Conversation context assembled'],
  context_merged: ['联结上下文', 'Context merged'], prompt_joined: ['联结提示词', 'Prompt joined'], tools_injected: ['注入工具', 'Tools injected'],
  skills_injected: ['注入技能', 'Skills injected'], context_ready: ['上下文就绪（含记忆）', 'Context ready (with memory)'],
  node_started: ['开始模型轮次', 'Model iteration started'], model_thinking: ['模型推理中', 'Model reasoning'],
  llm_completed: ['模型输出', 'Model output'], loop_decision: ['循环决策', 'Loop decision'],
  tool_call_requested: ['调用工具', 'Tool called'], tool_completed: ['工具结果', 'Tool result'],
  tool_results_added: ['工具结果注入上下文', 'Tool results added'], loop_feedback: ['结果反馈下一轮', 'Feedback to next iteration'],
  legacy_observation_added: ['观察结果注入上下文', 'Observation added'], workflow_completed: ['完成回复', 'Answer complete'],
  workflow_failed: ['运行失败', 'Workflow failed'], tool_call_adapted: ['解析模型工具调用', 'Tool call parsed'],
};

function detail(event) {
  const data = event.data || {};
  if (event.event_type === 'node_output' || event.event_type === 'prompt_joined' || event.event_type === 'context_ready' || event.event_type === 'context_merged') return data.content || '';
  if (event.event_type === 'message_context_ready') return JSON.stringify(data.messages || [], null, 2);
  if (event.event_type === 'llm_completed') return data.content || (data.tool_calls?.length ? JSON.stringify(data.tool_calls, null, 2) : '');
  if (event.event_type === 'tool_call_requested' || event.event_type === 'tool_completed') return JSON.stringify(data, null, 2);
  if (event.event_type === 'response_parsed') return data.tool_calls?.length ? JSON.stringify(data.tool_calls, null, 2) : data.answer || '';
  if (event.event_type === 'response_routed_to_tools') return `${data.count || 0} 个工具 / 技能调用`;
  if (event.event_type === 'response_routed_to_answer') return data.content || '';
  if (event.event_type === 'workflow_completed') return data.answer || '';
  if (event.event_type === 'tool_results_added' || event.event_type === 'loop_feedback') return JSON.stringify(data.results || [], null, 2);
  if (event.event_type === 'loop_decision') return data.continue ? `继续第 ${data.iteration + 1} 轮 · ${data.tool_calls} 次工具调用` : '结束循环';
  if (event.event_type === 'workflow_failed') return data.error || '';
  return '';
}

export default function TraceView({ events = [], language: controlledLanguage, onLanguageChange }) {
  const [localLanguage, setLocalLanguage] = useState(() => localStorage.getItem(LANGUAGE_KEY) || 'zh');
  const language = controlledLanguage || localLanguage;
  const setLanguage = (value) => {
    if (onLanguageChange) onLanguageChange(value);
    else {
      localStorage.setItem(LANGUAGE_KEY, value);
      setLocalLanguage(value);
    }
  };
  return <div className="trace-view"><div className="trace-language" role="group" aria-label="轨迹语言"><button className={language === 'zh' ? 'selected' : ''} onClick={() => setLanguage('zh')}>中文</button><button className={language === 'en' ? 'selected' : ''} onClick={() => setLanguage('en')}>EN</button></div><div className="trace-steps">{events.map((event, index) => {
    const content = detail(event);
    const tokens = event.data?.usage?.total_tokens;
    return <details className="trace-step" key={`${event.event_type}-${index}`}><summary><span>{String(index + 1).padStart(2, '0')}</span><strong>{labels[event.event_type]?.[language === 'en' ? 1 : 0] || event.event_type}</strong><small>{event.node_id || 'runtime'}{tokens ? ` · ${tokens} tokens` : ''}</small></summary>{content && <pre>{content}</pre>}</details>;
  })}</div></div>;
}

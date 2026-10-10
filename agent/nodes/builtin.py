"""Initial node types for chat workflows and module-backed capabilities."""

from __future__ import annotations

from typing import Any, Mapping

from .base import BaseNode, NodeContext, NodeResult, PortDefinition
from .registry import node_registry


class ChatInputNode(BaseNode):
    node_type = "core.chat_input"
    title = "对话输入"
    category = "io"
    description = "工作流的用户消息入口。"
    defaults = {"placeholder": "说点什么…", "debug_input": "你好，介绍一下你自己。"}
    preview = "来自用户的消息会从这里进入工作流。"
    outputs = (PortDefinition("message", "text", description="用户消息"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        return NodeResult(outputs={"message": context.services.get("user_input", "")})


class ModuleProviderNode(BaseNode):
    category = "capability"
    module_kind = "module"
    output_name = "module"

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        module_id = self.config.get("module_id")
        if not module_id:
            raise ValueError(f"{self.node_type} 缺少 module_id")
        return NodeResult(outputs={self.output_name: context.get_module(module_id)})


class LLMProviderNode(ModuleProviderNode):
    node_type = "llm.provider"
    title = "模型提供方"
    category = "model"
    module_kind = "llm"
    module_id = "llm"
    output_name = "llm"
    outputs = (PortDefinition("llm", "llm"),)


class GGUFLoaderNode(LLMProviderNode):
    node_type = "llm.gguf_loader"
    title = "GGUF 模型加载"
    description = "加载本地 GGUF 模型。"
    defaults = {"model": "qwen3-1.7b-q4km", "mmproj": "", "n_gpu_layers": -1}
    preview = "主模型必选；视觉模型可选 mmproj，纯文本模型留空。"


class OpenAILoaderNode(LLMProviderNode):
    node_type = "llm.openai_loader"
    title = "API 模型加载"
    description = "连接 OpenAI 兼容 API 模型。"
    defaults = {"model": "qwen3.5-35b", "base_url": ""}
    preview = "首次运行时建立 API 模块；编辑画布不会发起请求。"


class PromptProviderNode(ModuleProviderNode):
    node_type = "prompt.provider"
    title = "提示词与人格"
    category = "prompt"
    module_kind = "prompt"
    module_id = "prompt"
    output_name = "prompt"
    outputs = (PortDefinition("prompt", "prompt"),)


class MarkdownPromptNode(PromptProviderNode):
    node_type = "prompt.markdown_file"
    title = "Markdown 提示词"
    description = "从 Markdown 文件加载一个提示词片段。"
    defaults = {"file": "AGENT.md", "source": "modules/prompt/SystemPrompt"}
    preview = "从 Markdown 文件读取提示词片段。"


class TextPromptNode(BaseNode):
    node_type = "prompt.text"
    title = "文本提示词"
    category = "prompt"
    defaults = {"text": "你是一个可靠、自然的陪伴型 Agent。"}
    preview = "在节点内直接编辑一段提示词。"
    outputs = (PortDefinition("prompt", "prompt"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        return NodeResult(outputs={"prompt": self.config.get("text", "")})


class PromptJoinNode(BaseNode):
    node_type = "prompt.join"
    title = "提示词联结"
    category = "prompt"
    defaults = {"separator": "\n\n"}
    preview = "按顺序拼接多个提示词片段。"
    inputs = (
        PortDefinition("prompt_a", "prompt", required=False),
        PortDefinition("prompt_b", "prompt", required=False),
        PortDefinition("prompt_c", "prompt", required=False),
        PortDefinition("prompt_d", "prompt", required=False),
    )
    outputs = (PortDefinition("prompt", "prompt"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        separator = str(self.config.get("separator", "\n\n"))
        parts = [str(inputs[name]) for name in ("prompt_a", "prompt_b", "prompt_c", "prompt_d") if inputs.get(name)]
        return NodeResult(outputs={"prompt": separator.join(parts)})


class MemoryProviderNode(ModuleProviderNode):
    node_type = "memory.provider"
    title = "记忆提供方"
    category = "memory"
    module_kind = "memory"
    module_id = "memory"
    defaults = {"strategy": "markdown"}
    preview = "长期记忆内容将在这里进入上下文。"
    output_name = "memory"
    outputs = (PortDefinition("memory", "memory"),)


class SkillsProviderNode(ModuleProviderNode):
    node_type = "skills.provider"
    title = "技能目录"
    category = "skills"
    module_kind = "skills"
    module_id = "skills"
    defaults = {"source": "modules/skills"}
    preview = "recommend_travel\nfile_operations"
    output_name = "skills"
    outputs = (PortDefinition("skills", "skills"),)


class ToolsProviderNode(ModuleProviderNode):
    node_type = "tools.provider"
    title = "工具箱"
    category = "tools"
    module_kind = "tools"
    module_id = "tools"
    defaults = {"approval": "risk-based"}
    preview = "get_weather\nget_attraction\nget_current_*\nexec_sandbox_cmd"
    output_name = "tools"
    outputs = (PortDefinition("tools", "tools"),)


class ContextMergeNode(BaseNode):
    node_type = "context.merge"
    title = "上下文联结"
    category = "context"
    preview = "把记忆、技能和工具描述汇总成上下文。"
    inputs = (
        PortDefinition("memory", "memory", required=False),
        PortDefinition("skills", "skills", required=False),
        PortDefinition("tools", "tools", required=False),
    )
    outputs = (PortDefinition("context", "context"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        return NodeResult(outputs={"context": dict(inputs)})


class ReactRuntimeNode(BaseNode):
    node_type = "agent.react_runtime"
    title = "ReAct Runtime"
    category = "runtime"
    description = "调用配置好的 Agent runtime 并返回答案和可观测轨迹。"
    defaults = {"max_iterations": 5, "display_mode": "normal", "prompt_name": "default"}
    preview = "仅用于兼容旧版工作流。"
    inputs = (
        PortDefinition("message", "text"),
        PortDefinition("llm", "llm"),
        PortDefinition("prompt", "prompt"),
        PortDefinition("memory", "memory", required=False),
        PortDefinition("skills", "skills", required=False),
        PortDefinition("tools", "tools", required=False),
    )
    outputs = (
        PortDefinition("answer", "text"),
        PortDefinition("trace", "trace", required=False),
    )
    config_schema = {
        "type": "object",
        "properties": {
            "max_iterations": {"type": "integer", "minimum": 1},
            "display_mode": {"type": "string", "enum": ["normal", "transparent"]},
            "prompt_name": {"type": "string"},
        },
    }

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        agent = context.services.get("agent")
        if agent is None:
            raise RuntimeError("NodeContext.services 中没有 Agent runtime")
        module_ids = {
            name: getattr(module, "module_id", None)
            for name, module in inputs.items()
            if name in {"llm", "prompt", "memory", "skills", "tools"} and module is not None
        }
        bindings = {f"{name}_id": module_id for name, module_id in module_ids.items() if module_id}
        answer = agent.run(
            user_input=str(inputs.get("message", "")),
            prompt_name=self.config.get("prompt_name", "default"),
            mode=self.config.get("display_mode", "normal"),
            **bindings,
        )
        events = agent.get_trace_events() if hasattr(agent, "get_trace_events") else []
        return NodeResult(outputs={"answer": answer, "trace": events})


class LLMChatNode(ReactRuntimeNode):
    node_type = "llm.chat"
    title = "模型对话"
    category = "model"
    defaults = {"max_iterations": 5, "display_mode": "normal"}
    preview = "接收消息、提示词和上下文，返回模型回答。"
    inputs = (
        PortDefinition("message", "text"),
        PortDefinition("prompt", "prompt"),
        PortDefinition("context", "context", required=False),
        PortDefinition("llm", "llm"),
        PortDefinition("loop", "loop", required=False),
    )
    outputs = (
        PortDefinition("answer", "text"),
        PortDefinition("trace", "trace", required=False),
        PortDefinition("response", "model_response", required=False),
    )


class ResponseRouterNode(BaseNode):
    node_type = "react.response_router"
    title = "响应解析与分流"
    category = "control"
    description = "解析模型结构化响应；工具或技能调用进入执行反馈循环，普通内容进入最终回答。"
    preview = "运行时按 tool_calls 分流：调用能力后反馈下一轮，无调用时输出回答。"
    inputs = (
        PortDefinition("response", "model_response"),
    )
    outputs = (
        PortDefinition("tool_calls", "tool_calls", required=False),
        PortDefinition("answer", "text", required=False),
    )

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        response = inputs.get("response")
        return NodeResult(outputs={
            "tool_calls": getattr(response, "tool_calls", []) if response is not None else [],
            "answer": getattr(response, "content", "") if response is not None else "",
        })


class ToolDispatchNode(BaseNode):
    node_type = "tools.dispatch"
    title = "工具 / 技能执行"
    category = "tools"
    description = "由运行时将解析出的工具或技能调用分发给已启用能力并返回结果。"
    preview = "技能通过工具调用协议加载或执行；结果返回 ReAct 循环。"
    inputs = (PortDefinition("tool_calls", "tool_calls"),)
    outputs = (PortDefinition("tool_results", "tool_results"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        return NodeResult(outputs={"tool_results": []})


class ReactLoopNode(BaseNode):
    node_type = "react.loop"
    title = "ReAct 循环"
    category = "control"
    description = "根据模型输出和工具结果决定继续推理或结束。"
    defaults = {"max_iterations": 5}
    inputs = (
        PortDefinition("trace", "trace", required=False),
        PortDefinition("tool_results", "tool_results", required=False),
    )
    outputs = (PortDefinition("loop", "loop"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        return NodeResult(outputs={"loop": {"max_iterations": self.config.get("max_iterations", 5)}})


class ChatOutputNode(BaseNode):
    node_type = "core.chat_output"
    title = "回复输出"
    category = "io"
    description = "对话工作流的最终输出。"
    defaults = {"show_trace": False}
    preview = "工作流最终输出。"
    inputs = (PortDefinition("answer", "text"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        return NodeResult(outputs={"answer": inputs.get("answer", "")})


node_registry.register_many((
    ChatInputNode,
    ReactLoopNode,
    ReactRuntimeNode,
    LLMChatNode,
    ResponseRouterNode,
    ToolDispatchNode,
    LLMProviderNode,
    GGUFLoaderNode,
    OpenAILoaderNode,
    PromptProviderNode,
    MarkdownPromptNode,
    TextPromptNode,
    PromptJoinNode,
    MemoryProviderNode,
    SkillsProviderNode,
    ToolsProviderNode,
    ContextMergeNode,
    ChatOutputNode,
))

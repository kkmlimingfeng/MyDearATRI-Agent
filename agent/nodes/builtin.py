"""Initial node types for chat workflows and module-backed capabilities."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from agent.tool_executor import ToolExecutor
from agent.tool_discovery import GET_TOOL_USAGE, LIST_TOOLS, TOOL_DISCOVERY_TEXT, discovery_schemas, merge_schemas
from agent.trace import trace_safe_messages

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
        module_id = context.services.get("node_module_id") or self.config.get("module_id") or self.module_id
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
    defaults = {"model": "qwen3.5-35b"}
    preview = "首次运行时建立 API 模块；编辑画布不会发起请求。"


class TTSAudioNode(BaseNode):
    node_type = "audio.tts_model"
    title = "Qwen3-TTS 音频模型"
    category = "audio"
    description = "从 models/TTS 选择本地 Qwen3-TTS GGUF，将文本合成为流式语音。"
    defaults = {"model": "qwen3-0.6b-q8", "language": "Chinese", "reference": "atri"}
    preview = "接收回复文本，输出流式语音。"
    inputs = (PortDefinition("text", "text", label_zh="文本", label_en="Text"),)
    outputs = (PortDefinition("audio", "audio", label_zh="语音", label_en="Voice"),)
    config_schema = {"type": "object", "properties": {
        "model": {"type": "string", "title": "TTS 模型", "default": "qwen3-0.6b-q8"},
        "language": {"type": "string", "title": "目标语言", "enum": ["Chinese", "Japanese", "English"], "default": "Chinese"},
        "reference": {"type": "string", "title": "参考音色", "default": "atri"},
    }}

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        text = inputs.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("音频模型需要非空文本")
        if len(text.strip()) > 1000:
            raise ValueError("语音文本不能超过 1000 字")
        language = self.config.get("language", "Chinese")
        if language not in {"Chinese", "Japanese", "English"}:
            raise ValueError("不支持的目标语言")
        tts_service = context.services.get("tts")
        if tts_service is None:
            raise RuntimeError("缺少 Qwen3-TTS 服务")
        model = self.config.get("model", "qwen3-0.6b-q8")
        available = {item["id"]: item["available"] for item in tts_service.models()["models"]}
        if model not in available:
            raise ValueError(f"未知 TTS 模型: {model}")
        if not available[model]:
            raise RuntimeError(f"TTS 模型文件不存在: {model}")
        return NodeResult(outputs={"audio": {
            "type": "audio",
            "content_type": "audio/pcm",
            "endpoint": "/api/tts/speech",
            "text": text.strip(),
            "model": model,
            "language": language,
            "reference": self.config.get("reference", "atri"),
        }})


class PromptProviderNode(ModuleProviderNode):
    node_type = "prompt.provider"
    title = "提示词与人格"
    category = "prompt"
    module_kind = "prompt"
    module_id = "prompt"
    output_name = "prompt"
    outputs = (PortDefinition("prompt", "prompt"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        agent = context.services["agent"]
        module_id = context.services.get("node_module_id") or self.module_id
        reply = agent.bus.request(source="agent", target=module_id, payload={"action": "get_system_prompt", "prompt_name": self.config.get("prompt_name", "default")})
        return NodeResult(outputs={"prompt": reply.payload.get("system_prompt", "")})


class MarkdownPromptNode(PromptProviderNode):
    node_type = "prompt.markdown_file"
    title = "Markdown 提示词"
    description = "从 Markdown 文件加载一个提示词片段。"
    defaults = {"file": "AGENT.md", "source": "modules/prompt/SystemPrompt"}
    preview = "从 Markdown 文件读取提示词片段。"

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        read_prompt = context.services.get("read_prompt")
        if read_prompt is None:
            raise RuntimeError("缺少 Markdown 提示词读取服务")
        return NodeResult(outputs={"prompt": read_prompt(self.config.get("file", "AGENT.md"))})


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
        separator = str(self.config.get("separator", "\n\n")).replace("\\n", "\n")
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

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        agent = context.services["agent"]
        module_id = context.services.get("node_module_id") or self.module_id
        reply = agent.bus.request(source="agent", target=module_id, payload={"action": "get_memory"})
        return NodeResult(outputs={"memory": reply.payload.get("memory", "")})


class SkillsProviderNode(ModuleProviderNode):
    node_type = "skills.provider"
    title = "技能目录"
    category = "skills"
    module_kind = "skills"
    module_id = "skills"
    defaults = {"source": "modules/skills"}
    preview = "recommend_travel\nfile_operations"
    output_name = "skills"
    outputs = (
        PortDefinition("skills", "skills"),
        PortDefinition("schemas", "tool_schemas", required=False),
        PortDefinition("executor", "skill_executor", required=False),
    )

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        agent = context.services["agent"]
        module_id = context.services.get("node_module_id") or self.module_id
        reply = agent.bus.request(source="agent", target=module_id, payload={"action": "format_skill_overview"})
        catalog = agent.bus.request(source="agent", target=module_id, payload={"action": "get_skill_descriptions"})
        schemas = [{"type": "function", "function": {
            "name": f"skill__{item['folder_name']}",
            "description": f"读取技能 {item['name']} 的完整说明。{item.get('description', '')}",
            "parameters": {"type": "object", "properties": {}},
        }} for item in catalog.payload.get("descriptions", []) if re.fullmatch(r"[A-Za-z0-9_-]+", item.get("folder_name", ""))]
        schemas.append({"type": "function", "function": {
            "name": "skill__read_resource",
            "description": "读取技能包内 SKILL.md 引用的文本资源，例如 references/ 下的说明。",
            "parameters": {"type": "object", "properties": {
                "skill_name": {"type": "string", "description": "技能名称"},
                "path": {"type": "string", "description": "相对于技能目录的文件路径"},
            }, "required": ["skill_name", "path"]},
        }})
        return NodeResult(outputs={"skills": {"module_id": module_id, "text": reply.payload.get("text", ""), "schemas": schemas}, "schemas": schemas, "executor": {"module_id": module_id}})


class MCPProviderNode(ModuleProviderNode):
    node_type = "mcp.provider"
    title = "MCP 服务"
    category = "tools"
    module_kind = "mcp"
    module_id = "mcp"
    defaults = {}
    preview = "提供已启用 MCP 服务的工具定义和调用执行器。"
    output_name = "mcp"
    outputs = (
        PortDefinition("mcp", "mcp"),
        PortDefinition("schemas", "tool_schemas", required=False),
    )

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        agent = context.services["agent"]
        module_id = context.services.get("node_module_id") or self.module_id
        reply = agent.bus.request(source="agent", target=module_id, payload={"action": "get_capabilities"})
        bundle = reply.payload.get("capabilities", {})
        return NodeResult(outputs={"mcp": bundle, "schemas": bundle.get("schemas", [])})


class ToolsProviderNode(ModuleProviderNode):
    node_type = "tools.provider"
    title = "工具箱"
    category = "tools"
    module_kind = "tools"
    module_id = "tools"
    defaults = {"approval": "risk-based"}
    preview = "提供工具目录查询、按需读取用法，以及独立的执行器引用。"
    output_name = "tools"
    outputs = (
        PortDefinition("tools", "tools"),
        PortDefinition("schemas", "tool_schemas", required=False),
        PortDefinition("executor", "tool_executor", required=False),
    )

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        module_id = context.services.get("node_module_id") or self.module_id
        schemas = discovery_schemas()
        return NodeResult(outputs={"tools": {"module_id": module_id, "text": TOOL_DISCOVERY_TEXT, "schemas": schemas}, "schemas": schemas, "executor": {"module_id": module_id}})


class SchemaMergeNode(BaseNode):
    node_type = "capability.schema_merge"
    title = "能力使用方式"
    category = "tools"
    description = "汇总模型可调用能力的名称、用途和参数定义。"
    preview = "初始提供工具发现方式；按需读取后加入具体工具定义。"
    inputs = (
        *(PortDefinition(f"schemas_{suffix}", "tool_schemas", required=False) for suffix in "abcd"),
        PortDefinition("loop", "loop", required=False),
    )
    outputs = (PortDefinition("schemas", "tool_schemas"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        groups = []
        for suffix in "abcd":
            value = inputs.get(f"schemas_{suffix}") or []
            if not isinstance(value, list):
                raise ValueError("能力使用方式输入必须是列表")
            groups.append(value)
        loop = inputs.get("loop") or {}
        response = loop.get("response") or {}
        previously_offered = response.get("tool_schemas") or []
        activated = [result["activated_schema"] for result in loop.get("tool_results", []) if result.get("activated_schema")]
        return NodeResult(outputs={"schemas": merge_schemas(*groups, previously_offered, activated)})


class ContextMergeNode(BaseNode):
    node_type = "context.merge"
    title = "上下文联结"
    category = "context"
    preview = "汇总技能、工具、MCP、记忆和循环结果，组织下一轮上下文。"
    inputs = (
        PortDefinition("skills", "skills", required=False),
        PortDefinition("tools", "tools", required=False),
        PortDefinition("mcp", "mcp", required=False),
        PortDefinition("memory", "memory", required=False),
        PortDefinition("tool_results", "tool_results", required=False),
        PortDefinition("context_a", "context", required=False),
        PortDefinition("context_b", "context", required=False),
        PortDefinition("loop", "loop", required=False),
    )
    outputs = (
        PortDefinition("context", "context"),
        PortDefinition("tool_schemas", "tool_schemas", required=False),
        PortDefinition("loop", "loop", required=False),
    )

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        parts = []
        schemas = []
        for name in ("skills", "tools", "mcp", "memory", "tool_results", "context_a", "context_b"):
            value = inputs.get(name)
            if not value:
                continue
            if name in {"skills", "tools", "mcp"} and isinstance(value, dict):
                if value.get("text"):
                    parts.append(str(value["text"]))
                definitions = value.get("schemas") or []
                if not isinstance(definitions, list):
                    raise ValueError(f"{name} 的能力使用方式必须是列表")
                schemas.extend(definitions)
            else:
                parts.append(str(value))
        loop = inputs.get("loop")
        if loop is not None and not isinstance(loop, dict):
            raise ValueError("新上下文必须是循环控制返回的数据包")
        if loop and loop.get("tool_results"):
            parts.append(json.dumps(loop["tool_results"], ensure_ascii=False, default=str))
        outputs = {"context": "\n\n".join(parts), "tool_schemas": schemas}
        if loop:
            outputs["loop"] = loop
        return NodeResult(outputs=outputs)


class LLMChatNode(BaseNode):
    node_type = "llm.chat"
    title = "模型对话"
    category = "model"
    defaults = {"reasoning_effort": "auto"}
    preview = "接收消息、提示词和上下文，返回模型回答。"
    config_schema = {"type": "object", "properties": {"reasoning_effort": {"type": "string", "title": "默认思考强度（API）", "enum": ["auto", "minimal", "low", "medium", "high", "xhigh"], "default": "auto"}}}
    inputs = (
        PortDefinition("message", "text"),
        PortDefinition("prompt", "prompt"),
        PortDefinition("context", "context", required=False),
        PortDefinition("llm", "llm"),
        PortDefinition("tool_schemas", "tool_schemas", required=False),
        PortDefinition("loop", "loop", required=False),
    )
    outputs = (
        PortDefinition("answer", "text"),
        PortDefinition("response", "model_response", required=False),
        PortDefinition("trace", "trace", required=False, hidden=True),
    )

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        agent = context.services["agent"]
        llm = inputs["llm"]
        if not getattr(llm, "_initialized", False):
            llm.ensure_initialized()
        feedback = inputs.get("loop")
        if feedback:
            messages = list(feedback["messages"])
            response = feedback["response"]
            calls = response.get("tool_calls") or []
            assistant_message = {"role": "assistant", "content": "" if "<tool_call>" in response.get("content", "") else response.get("content", "")}
            if calls:
                assistant_message["tool_calls"] = [ToolExecutor.from_provider_call(call).to_message_dict() for call in calls]
            messages.append(assistant_message)
            for result in feedback.get("tool_results", []):
                messages.append({"role": "tool", "tool_call_id": result.get("call_id", ""), "content": json.dumps(result, ensure_ascii=False, default=str)})
            if "feedback" in feedback:
                messages.append({"role": "user", "content": str(feedback["feedback"])})
        else:
            prompt = str(inputs.get("prompt", ""))
            extra = "\n\n".join(
                part for part in (
                    str(context.services.get("conversation_summary", "")),
                    str(inputs.get("context", "")),
                ) if part
            )
            tools_text = str(context.services.get("tools_text", ""))
            skills_text = str(context.services.get("skills_text", ""))
            prompt = prompt.replace("{{TOOLS}}", "" if tools_text and tools_text in extra else tools_text)
            prompt = prompt.replace("{{SKILLS}}", "" if skills_text and skills_text in extra else skills_text)
            system = "\n\n".join(part for part in (prompt, extra) if part)
            history = agent._history[-agent.max_history_turns * 2:]
            user_text = str(inputs["message"])
            user_content_parts = context.services.get("user_content_parts") or []
            user_content = [{"type": "text", "text": user_text}, *user_content_parts] if user_content_parts else user_text
            messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": user_content}]
        tool_schemas = inputs.get("tool_schemas", context.services.get("tool_schemas", []))
        if feedback:
            prior = feedback.get("response", {}).get("tool_schemas") or []
            activated = [item["activated_schema"] for item in feedback.get("tool_results", []) if item.get("activated_schema")]
            tool_schemas = merge_schemas(tool_schemas or [], prior, activated)
        stream_update = context.services.get("stream_update")
        if callable(stream_update):
            stream_update("")
        context.emit("model_request", context.node_id, {"messages": trace_safe_messages(messages), "tool_schemas": tool_schemas})
        request = {"action": "generate", "messages": messages, "tools": tool_schemas}
        request["reasoning_effort"] = context.services.get("reasoning_effort") or self.config.get("reasoning_effort", "auto")
        if callable(stream_update):
            request["on_progress"] = stream_update
        reply = agent.bus.request(source="agent", target=llm.module_id, payload=request)
        if reply.payload.get("error"):
            raise RuntimeError(reply.payload["error"])
        response = {
            "content": reply.payload.get("response", ""),
            "tool_calls": reply.payload.get("tool_calls", []),
            "usage": reply.payload.get("usage", {}),
            "messages": messages,
            "tool_schemas": tool_schemas,
        }
        if not response["tool_calls"] and response["content"]:
            response["tool_calls"] = agent._parse_embedded_tool_calls(response["content"])
        if "<tool_call>" in response["content"] and not response["tool_calls"]:
            raise ValueError("模型输出了工具调用，但参数格式无法解析；请检查模型的工具调用格式")
        if response["tool_calls"] and callable(stream_update):
            stream_update("")
        context.emit("model_response", context.node_id, {"content": response["content"], "tool_calls": response["tool_calls"], "usage": response["usage"]})
        return NodeResult(outputs={"answer": response["content"], "response": response, "trace": response})


class ResponseRouterNode(BaseNode):
    node_type = "control.response_parser"
    title = "响应解析"
    category = "control"
    description = "解析模型输出，将普通回答、工具调用和结构化结果分开。"
    preview = "把模型输出转换为可连接的回答、工具调用或其他结构化数据。"
    inputs = (
        PortDefinition("response", "model_response"),
    )
    outputs = (
        PortDefinition("tool_calls", "tool_calls", required=False),
        PortDefinition("answer", "text", required=False),
        PortDefinition("response", "model_response", required=False),
    )

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        response = inputs.get("response")
        if isinstance(response, dict):
            calls = response.get("tool_calls") or []
            content = response.get("content", "")
        else:
            calls = getattr(response, "tool_calls", []) if response is not None else []
            content = getattr(response, "content", "") if response is not None else ""
        if calls:
            return NodeResult(outputs={"tool_calls": calls, "response": response})
        return NodeResult(outputs={"answer": content})


class LegacyResponseRouterNode(ResponseRouterNode):
    """Compatibility alias for graph files using the old ReAct name."""

    node_type = "react.response_router"
    title = "兼容：响应解析与分流"


class ToolDispatchNode(BaseNode):
    node_type = "capability.dispatch"
    title = "能力分发"
    category = "tools"
    description = "把解析出的调用分发给工具、技能或 MCP 能力并返回统一结果。"
    preview = "根据模型调用选择技能、工具或 MCP 执行器，返回统一结果。"
    inputs = (
        PortDefinition("tool_calls", "tool_calls"),
        PortDefinition("skill_executor", "skill_executor", required=False),
        PortDefinition("tool_executor", "tool_executor", required=False),
        PortDefinition("skills", "skills", required=False, hidden=True),
        PortDefinition("tools", "tools", required=False, hidden=True),
        PortDefinition("mcp", "mcp", required=False),
        PortDefinition("usage", "tool_schemas", required=False),
        PortDefinition("handlers", "capability_handlers", required=False),
    )
    outputs = (PortDefinition("tool_results", "tool_results"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        agent = context.services["agent"]
        results = []
        mcp = inputs.get("mcp") or {}
        handlers = {
            **(context.services.get("capability_handlers") or {}),
            **((mcp.get("handlers") or {}) if isinstance(mcp, dict) else {}),
            **(inputs.get("handlers") or {}),
        }
        tools_ref = inputs.get("tool_executor") or inputs.get("tools")
        skills_ref = inputs.get("skill_executor") or inputs.get("skills")
        for raw in inputs.get("tool_calls") or []:
            call = ToolExecutor.from_provider_call(raw)
            if call.name in {LIST_TOOLS, GET_TOOL_USAGE}:
                target = call.arguments.get("tool_name") if call.name == GET_TOOL_USAGE else None
                context.emit("tool_call_requested", context.node_id, {
                    "call_id": call.call_id, "name": call.name, "arguments": call.arguments,
                    "kind": "tool_discovery", "target": target,
                })
                module_id = tools_ref.get("module_id") if isinstance(tools_ref, dict) else context.services.get("tools_id")
                if not module_id or self.node_type == "capability.dispatch" and not tools_ref:
                    raise RuntimeError("工具发现需要在工作流中连接工具箱")
                if call.name == LIST_TOOLS:
                    reply = agent.bus.request(source="agent", target=module_id, payload={"action": "get_tool_descriptions"})
                    catalog = [{"name": item["name"], "description": item.get("description", "")} for item in reply.payload.get("descriptions", [])]
                    results.append({"call_id": call.call_id, "name": call.name, "status": "success", "output": catalog})
                else:
                    tool_name = call.arguments.get("tool_name")
                    if not isinstance(tool_name, str) or not tool_name:
                        result = {"call_id": call.call_id, "name": call.name, "status": "error", "error": "缺少 tool_name"}
                        results.append(result)
                        context.emit("tool_completed", context.node_id, {**result, "kind": "tool_discovery", "target": target})
                        continue
                    reply = agent.bus.request(source="agent", target=module_id, payload={"action": "get_tool_usage", "tool_name": tool_name})
                    schema = reply.payload.get("schema")
                    result = {"call_id": call.call_id, "name": call.name, "status": "success" if schema else "error"}
                    if schema:
                        result["output"] = schema["function"]
                        result["activated_schema"] = schema
                    else:
                        result["error"] = reply.payload.get("error", "工具不可用")
                    results.append(result)
                context.emit("tool_completed", context.node_id, {**results[-1], "kind": "tool_discovery", "target": target})
                continue
            namespace, separator, name = call.name.partition(":")
            if not separator and "__" in call.name and call.name.split("__", 1)[0] in {"skill", *handlers}:
                namespace, separator, name = call.name.partition("__")
            if call.name.startswith("skill__") or separator and namespace == "skill":
                name = call.name[len("skill__"):] if call.name.startswith("skill__") else name
                context.emit("tool_call_requested", context.node_id, {
                    "call_id": call.call_id, "name": call.name, "arguments": call.arguments,
                    "kind": "skill", "target": name,
                })
                skills_id = skills_ref.get("module_id") if isinstance(skills_ref, dict) else context.services.get("skills_id")
                if not skills_id or self.node_type == "capability.dispatch" and not skills_ref:
                    raise RuntimeError("技能调用需要在工作流中连接技能目录")
                if name == "read_resource":
                    reply = agent.bus.request(source="agent", target=skills_id, payload={
                        "action": "get_skill_resource",
                        "skill_name": call.arguments.get("skill_name", ""),
                        "path": call.arguments.get("path", ""),
                    })
                    output = reply.payload.get("content")
                else:
                    reply = agent.bus.request(source="agent", target=skills_id, payload={"action": "get_skill_detail", "skill_name": name})
                    output = reply.payload.get("detail")
                result = {"call_id": call.call_id, "name": call.name, "status": "error" if "error" in reply.payload else "success", "output": output, "error": reply.payload.get("error")}
                results.append(result)
                context.emit("tool_completed", context.node_id, {**result, "kind": "skill", "target": name})
            elif separator and namespace != "tool":
                context.emit("tool_call_requested", context.node_id, {
                    "call_id": call.call_id, "name": call.name, "arguments": call.arguments,
                    "kind": namespace, "target": name,
                })
                handler = handlers.get(namespace)
                if handler is None:
                    raise RuntimeError(f"未注册能力类型: {namespace}")
                result = handler(name, call.arguments, call.call_id)
                results.append(result)
                context.emit("tool_completed", context.node_id, {
                    **(result if isinstance(result, dict) else {"output": result}),
                    "call_id": call.call_id, "name": call.name,
                    "kind": namespace, "target": name,
                })
            else:
                module_id = tools_ref.get("module_id") if isinstance(tools_ref, dict) else context.services.get("tools_id")
                if not module_id or self.node_type == "capability.dispatch" and not tools_ref:
                    raise RuntimeError("能力分发节点缺少已连接的工具箱")
                if separator:
                    call.name = name
                if "usage" in inputs and call.name not in {
                    schema.get("function", {}).get("name") for schema in (inputs.get("usage") or [])
                }:
                    result = {"call_id": call.call_id, "name": call.name, "status": "error", "error": "请先读取该工具的使用方式"}
                    results.append(result)
                    context.emit("tool_completed", context.node_id, result)
                    continue
                results.append(agent._get_tool_executor().execute(call, module_id).as_dict())
        return NodeResult(outputs={"tool_results": results})


class LegacyToolDispatchNode(ToolDispatchNode):
    """Compatibility alias for graph files using the old tools name."""

    node_type = "tools.dispatch"
    title = "兼容：工具 / 技能执行"


class ReactLoopNode(BaseNode):
    node_type = "control.loop"
    title = "循环控制"
    category = "control"
    description = "根据输入的条件或结果决定继续、结束或回到上游节点。"
    defaults = {"max_iterations": 5}
    config_schema = {"type": "object", "properties": {"max_iterations": {"type": "integer", "title": "最大循环次数", "minimum": 1, "maximum": 500, "default": 5}}}
    inputs = (
        PortDefinition("response", "model_response", required=False),
        PortDefinition("trace", "trace", required=False, hidden=True),
        PortDefinition("tool_results", "tool_results", required=False),
        PortDefinition("value", "any", required=False),
    )
    outputs = (PortDefinition("loop", "loop", label_zh="新上下文", label_en="Next context"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        results = inputs.get("tool_results")
        feedback = inputs.get("value")
        response = inputs.get("response", inputs.get("trace"))
        if not results and feedback is None or not isinstance(response, dict):
            return NodeResult()
        iteration = int(context.services.get("iteration", 1))
        limit = max(1, min(500, int(self.config.get("max_iterations", 5))))
        if iteration >= limit:
            raise RuntimeError(f"已达到最大循环次数 {limit}，任务未完成")
        value = {"messages": response["messages"], "response": response}
        if results:
            value["tool_results"] = results
        if feedback is not None:
            value["feedback"] = feedback
        return NodeResult(outputs={"loop": value})


class LegacyReactLoopNode(ReactLoopNode):
    """Compatibility alias for graph files using the old ReAct name."""

    node_type = "react.loop"
    title = "兼容：ReAct 循环"


class BranchNode(BaseNode):
    node_type = "control.branch"
    title = "条件分支"
    category = "control"
    description = "根据条件将数据送到满足条件或不满足条件的出口。"
    defaults = {"condition": "truthy", "compare_to": ""}
    inputs = (PortDefinition("value", "any"),)
    outputs = (
        PortDefinition("true", "any", required=False),
        PortDefinition("false", "any", required=False),
    )
    config_schema = {"type": "object", "properties": {"condition": {"type": "string", "enum": ["truthy", "empty", "equals", "contains", "not_contains"]}, "compare_to": {"type": "string"}}}

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        value = inputs.get("value")
        condition = self.config.get("condition", "truthy")
        compare_to = str(self.config.get("compare_to", ""))
        matched = {
            "truthy": lambda: bool(value),
            "empty": lambda: not bool(value),
            "equals": lambda: str(value) == compare_to,
            "contains": lambda: compare_to in str(value),
            "not_contains": lambda: compare_to not in str(value),
        }.get(condition)
        if matched is None:
            raise ValueError(f"未知分支条件: {condition}")
        return NodeResult(outputs={"true" if matched() else "false": value})


class StateAccumulatorNode(BaseNode):
    node_type = "state.accumulator"
    title = "状态累积"
    category = "context"
    description = "把当前状态与新结果合并，供下一轮模型或评估节点使用。"
    inputs = (
        PortDefinition("state", "context", required=False),
        PortDefinition("item", "any", required=False),
    )
    outputs = (PortDefinition("state", "context"),)

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        previous = inputs.get("state")
        state = list(previous) if isinstance(previous, list) else ([] if previous is None else [previous])
        if inputs.get("item") is not None:
            state.append(inputs["item"])
        return NodeResult(outputs={"state": state})


class ChatOutputNode(BaseNode):
    node_type = "core.chat_output"
    title = "回复输出"
    category = "io"
    description = "对话工作流的最终输出。"
    defaults = {"show_trace": False}
    preview = "工作流最终输出。"
    inputs = (
        PortDefinition("answer", "text"),
        PortDefinition("voice", "audio", required=False, label_zh="语音输出", label_en="Voice output"),
        PortDefinition("animation", "animation", required=False, label_zh="动画输出", label_en="Animation output"),
    )
    outputs = (
        PortDefinition("answer", "text", hidden=True),
        PortDefinition("voice", "audio", required=False, hidden=True),
        PortDefinition("animation", "animation", required=False, hidden=True),
    )

    def execute(self, inputs: Mapping[str, Any], context: NodeContext) -> NodeResult:
        outputs = {"answer": inputs.get("answer", "")}
        for name in ("voice", "animation"):
            if name in inputs:
                outputs[name] = inputs[name]
        return NodeResult(outputs=outputs)


node_registry.register_many((
    ChatInputNode,
    ReactLoopNode,
    LegacyReactLoopNode,
    LLMChatNode,
    ResponseRouterNode,
    LegacyResponseRouterNode,
    ToolDispatchNode,
    LegacyToolDispatchNode,
    BranchNode,
    StateAccumulatorNode,
    LLMProviderNode,
    GGUFLoaderNode,
    OpenAILoaderNode,
    TTSAudioNode,
    PromptProviderNode,
    MarkdownPromptNode,
    TextPromptNode,
    PromptJoinNode,
    MemoryProviderNode,
    SkillsProviderNode,
    MCPProviderNode,
    ToolsProviderNode,
    SchemaMergeNode,
    ContextMergeNode,
    ChatOutputNode,
))

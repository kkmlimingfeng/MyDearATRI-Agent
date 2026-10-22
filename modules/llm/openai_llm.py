"""
OpenAI风格LLM模块 - 通过OpenAI兼容API调用远程模型
支持OpenAI官方API以及所有兼容OpenAI接口的服务（如vLLM、Ollama、LocalAI等）
"""
import json
from typing import Optional, List, Dict, Any, Callable
from urllib.parse import urlparse
from agent.protocol import LLMResponse, ToolCall
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[misc, assignment]
from .base_llm import BaseLLM, StreamPreview


# ANSI颜色码，用于终端彩色输出
class Colors:
    RESET = "\033[0m"      # 重置颜色
    BLUE = "\033[94m"      # 蓝色
    GREEN = "\033[92m"     # 绿色
    YELLOW = "\033[93m"    # 黄色
    RED = "\033[91m"       # 红色
    CYAN = "\033[96m"      # 青色


class OpenAILLM(BaseLLM):
    """OpenAI风格LLM模块，通过HTTP API调用远程模型"""
    supports_reasoning_effort = True
    
    def __init__(
        self,
        module_id: str,
        bus,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",  # API地址，可替换为其他兼容服务
        model_name: str = "gpt-3.5-turbo",            # 模型名称
        temperature: Optional[float] = None,           # None 时由提供商决定
        max_tokens: Optional[int] = None,              # None 时由提供商决定
        api_style: str = "chat_completions",
    ):
        # 调用父类初始化
        super().__init__(module_id, bus)
        self.api_key = api_key            # API密钥
        self.base_url = base_url          # API基础URL
        self.model_name = model_name      # 模型名称
        self.temperature = temperature    # 显式设置的温度
        self.max_tokens = max_tokens      # 显式设置的最大输出 token
        self.api_style = api_style
        self.client: Optional[OpenAI] = None  # OpenAI客户端实例
    
    def initialize(self) -> None:
        """初始化：创建OpenAI客户端连接"""
        if OpenAI is None:
            raise ImportError(
                "使用 OpenAILLM 需要安装 openai 包，请运行: pip install openai"
            )
        # 蓝色输出：API连接开始
        print(f"{Colors.BLUE}[{self.module_id}] 正在连接API: {self.base_url}{Colors.RESET}")
        # 创建OpenAI客户端，传入API密钥和服务地址
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        self._initialized = True
        # 绿色输出：API连接完成
        print(f"{Colors.GREEN}[{self.module_id}] API连接完成，模型: {self.model_name}{Colors.RESET}")
    
    def generate_response(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: str = "auto",
    ) -> LLMResponse:
        """
        使用OpenAI API生成文本
        :param messages: 标准messages格式，如[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        :return: 模型生成的文本
        """
        if self.api_style == "responses":
            response = self.client.responses.create(**self._responses_request(messages, tools, reasoning_effort))
            return self._parse_responses_response(response)
        # 调用OpenAI的chat completion API
        request = self._chat_request(messages, reasoning_effort)
        if tools:
            request["tools"] = tools
        response = self.client.chat.completions.create(**request)
        message = response.choices[0].message
        calls = []
        for call in (getattr(message, "tool_calls", None) or []):
            function = call.function
            try:
                arguments = json.loads(function.arguments or "{}")
            except (TypeError, json.JSONDecodeError):
                arguments = {}
            calls.append(ToolCall(call_id=call.id, name=function.name, arguments=arguments))
        usage = response.usage.model_dump() if response.usage else {}
        return LLMResponse(
            content=message.content or "",
            tool_calls=calls,
            usage=usage,
            raw=response.model_dump(),
        )

    def generate(self, messages: List[Dict[str, str]]) -> str:
        return self.generate_response(messages).content

    def generate_response_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        on_progress: Callable[[str], None],
        reasoning_effort: str = "auto",
    ) -> LLMResponse:
        if self.api_style == "responses":
            return self._stream_responses(messages, tools, on_progress, reasoning_effort)
        request = self._chat_request(messages, reasoning_effort)
        if tools:
            request["tools"] = tools
        try:
            stream = self.client.chat.completions.create(
                **request, stream=True, stream_options={"include_usage": True}
            )
        except Exception as exc:
            message = str(exc).lower()
            if "stream_options" not in message:
                if "stream" in message and any(word in message for word in ("unsupported", "not supported", "not implemented")):
                    return self.generate_response(messages, tools=tools, reasoning_effort=reasoning_effort)
                raise
            try:
                stream = self.client.chat.completions.create(**request, stream=True)
            except Exception as fallback_exc:
                message = str(fallback_exc).lower()
                if "stream" in message and any(word in message for word in ("unsupported", "not supported", "not implemented")):
                    return self.generate_response(messages, tools=tools, reasoning_effort=reasoning_effort)
                raise

        preview = StreamPreview(on_progress)
        tool_parts = {}
        usage = {}
        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = chunk.usage.model_dump() if hasattr(chunk.usage, "model_dump") else dict(chunk.usage)
            for choice in (getattr(chunk, "choices", None) or []):
                delta = choice.delta
                if getattr(delta, "content", None):
                    preview.push(delta.content)
                for tool in (getattr(delta, "tool_calls", None) or []):
                    part = tool_parts.setdefault(tool.index, {"id": "", "name": "", "arguments": ""})
                    if tool.id:
                        part["id"] = tool.id
                    function = tool.function
                    if function:
                        part["name"] += function.name or ""
                        part["arguments"] += function.arguments or ""
        calls = []
        for part in tool_parts.values():
            try:
                arguments = json.loads(part["arguments"] or "{}")
            except (TypeError, json.JSONDecodeError):
                arguments = {}
            calls.append(ToolCall(call_id=part["id"], name=part["name"], arguments=arguments))
        return LLMResponse(content=preview.content, tool_calls=calls, usage=usage)

    def _chat_request(self, messages, reasoning_effort):
        request = {"model": self.model_name, "messages": messages}
        modelscope_qwen = urlparse(self.base_url).hostname == "api-inference.modelscope.cn" and self.model_name.lower().startswith("qwen/")
        if reasoning_effort == "auto":
            if self.temperature is not None:
                request["temperature"] = self.temperature
            if self.max_tokens is not None:
                request["max_tokens"] = self.max_tokens
        else:
            if self.max_tokens is not None:
                request["max_completion_tokens"] = self.max_tokens
            if not modelscope_qwen:
                request["reasoning_effort"] = reasoning_effort
        if modelscope_qwen and self.max_tokens is not None:
            if self.max_tokens < 2:
                raise ValueError("ModelScope 思考模型的最大输出 token 至少需要 2")
            fractions = {"auto": 0.4, "minimal": 0.125, "low": 0.25, "medium": 0.4, "high": 0.6, "xhigh": 0.75}
            budget = max(1, min(self.max_tokens - 1, int(self.max_tokens * fractions[reasoning_effort])))
            request["extra_body"] = {"thinking_budget": budget}
        return request

    def _responses_request(self, messages, tools, reasoning_effort="auto"):
        inputs = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                inputs.append({"type": "function_call_output", "call_id": message.get("tool_call_id", ""), "output": str(message.get("content", ""))})
                continue
            content = message.get("content")
            if isinstance(content, list):
                converted = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        converted.append({"type": "input_text", "text": str(part.get("text", ""))})
                    elif part.get("type") == "image_url":
                        image = part.get("image_url") or {}
                        image_url = image.get("url") if isinstance(image, dict) else image
                        if image_url:
                            converted.append({"type": "input_image", "image_url": image_url})
                content = converted
            if content:
                inputs.append({"role": role, "content": content})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                arguments = function.get("arguments") or "{}"
                inputs.append({"type": "function_call", "call_id": call.get("id", ""), "name": function.get("name", ""), "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)})
        request = {"model": self.model_name, "input": inputs}
        if self.max_tokens is not None:
            request["max_output_tokens"] = self.max_tokens
        if reasoning_effort != "auto":
            request["reasoning"] = {"effort": reasoning_effort}
        if tools:
            request["tools"] = [
                {"type": "function", "name": tool["function"]["name"],
                 "description": tool["function"].get("description", ""),
                 "parameters": tool["function"].get("parameters", {"type": "object", "properties": {}})}
                for tool in tools if tool.get("type") == "function" and tool.get("function")
            ]
        return request

    @staticmethod
    def _parse_responses_response(response):
        calls = []
        for item in response.output or []:
            if item.type != "function_call":
                continue
            try:
                arguments = json.loads(item.arguments or "{}")
            except (TypeError, json.JSONDecodeError):
                arguments = {}
            calls.append(ToolCall(call_id=item.call_id, name=item.name, arguments=arguments if isinstance(arguments, dict) else {}))
        usage = response.usage.model_dump() if response.usage else {}
        return LLMResponse(content=response.output_text or "", tool_calls=calls, usage=usage, raw=response.model_dump())

    def _stream_responses(self, messages, tools, on_progress, reasoning_effort="auto"):
        preview = StreamPreview(on_progress)
        completed = None
        try:
            stream = self.client.responses.create(**self._responses_request(messages, tools, reasoning_effort), stream=True)
        except Exception as exc:
            message = str(exc).lower()
            if "stream" in message and any(word in message for word in ("unsupported", "not supported", "not implemented")):
                return self.generate_response(messages, tools=tools, reasoning_effort=reasoning_effort)
            raise
        for event in stream:
            if event.type == "response.output_text.delta":
                preview.push(event.delta)
            elif event.type == "response.completed":
                completed = event.response
            elif event.type == "response.failed":
                error = getattr(event.response, "error", None)
                raise RuntimeError(str(error or "Responses API 生成失败"))
        if completed is None:
            raise RuntimeError("Responses API 流结束时未返回最终响应")
        result = self._parse_responses_response(completed)
        on_progress(result.content)
        return result
    
    def shutdown(self) -> None:
        """关闭客户端连接"""
        # OpenAI客户端不需要显式关闭，但置空引用以便垃圾回收
        self.client = None
        self._initialized = False
        # 黄色输出：API连接已关闭
        print(f"{Colors.YELLOW}[{self.module_id}] API连接已关闭{Colors.RESET}")

"""
OpenAI风格LLM模块 - 通过OpenAI兼容API调用远程模型
支持OpenAI官方API以及所有兼容OpenAI接口的服务（如vLLM、Ollama、LocalAI等）
"""
import json
from typing import Optional, List, Dict, Any
from agent.protocol import LLMResponse, ToolCall
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[misc, assignment]
from .base_llm import BaseLLM


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
    
    def __init__(
        self,
        module_id: str,
        bus,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",  # API地址，可替换为其他兼容服务
        model_name: str = "gpt-3.5-turbo",            # 模型名称
        temperature: float = 0.7,                      # 生成温度，越高越随机
        max_tokens: int = 4096                         # 最大生成token数
    ):
        # 调用父类初始化
        super().__init__(module_id, bus)
        self.api_key = api_key            # API密钥
        self.base_url = base_url          # API基础URL
        self.model_name = model_name      # 模型名称
        self.temperature = temperature    # 温度参数
        self.max_tokens = max_tokens      # 最大token数
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
    ) -> LLMResponse:
        """
        使用OpenAI API生成文本
        :param messages: 标准messages格式，如[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        :return: 模型生成的文本
        """
        # 调用OpenAI的chat completion API
        request = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
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
    
    def shutdown(self) -> None:
        """关闭客户端连接"""
        # OpenAI客户端不需要显式关闭，但置空引用以便垃圾回收
        self.client = None
        self._initialized = False
        # 黄色输出：API连接已关闭
        print(f"{Colors.YELLOW}[{self.module_id}] API连接已关闭{Colors.RESET}")

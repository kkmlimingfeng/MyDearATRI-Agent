"""
OpenAI风格LLM模块 - 通过OpenAI兼容API调用远程模型
支持OpenAI官方API以及所有兼容OpenAI接口的服务（如vLLM、Ollama、LocalAI等）
"""
from typing import Optional, List, Dict, Any
from openai import OpenAI
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
    
    def generate(self, messages: List[Dict[str, str]]) -> str:
        """
        使用OpenAI API生成文本
        :param messages: 标准messages格式，如[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        :return: 模型生成的文本
        """
        # 调用OpenAI的chat completion API
        response = self.client.chat.completions.create(
            model=self.model_name,           # 指定模型
            messages=messages,               # 对话消息列表（标准格式）
            temperature=self.temperature,    # 温度参数
            max_tokens=self.max_tokens       # 最大生成token数
        )
        # 提取并返回模型回复的内容
        return response.choices[0].message.content
    
    def shutdown(self) -> None:
        """关闭客户端连接"""
        # OpenAI客户端不需要显式关闭，但置空引用以便垃圾回收
        self.client = None
        self._initialized = False
        # 黄色输出：API连接已关闭
        print(f"{Colors.YELLOW}[{self.module_id}] API连接已关闭{Colors.RESET}")

"""
LLM模块基类 - 定义所有LLM模块的统一接口
"""
import html
import re
from typing import Dict, Any, List, Optional
from agent.protocol import LLMResponse
from modules.base import BaseModule
from bus.base import Message, MessageType


def _hide_reasoning_markup(content: str) -> str:
    """Remove leaked Qwen-style reasoning blocks and their encoded markers."""
    text = html.unescape(str(content or ""))
    escaped_prefix = r"\\*<"
    open_tag = escaped_prefix + r"\s*think\b[^>]*>"
    close_tag = escaped_prefix + r"/\s*think\s*>"
    text = re.sub(open_tag + r".*?" + close_tag, "", text, flags=re.DOTALL | re.IGNORECASE)

    # Some chat templates strip the opening marker but leave the reasoning and
    # closing marker in content. Treat that unmatched closing marker as a
    # boundary and keep only the user-facing text after it.
    closing = re.search(close_tag, text, flags=re.IGNORECASE)
    if closing:
        preceding_open = re.search(open_tag, text[:closing.start()], flags=re.IGNORECASE)
        if preceding_open:
            text = text[:preceding_open.start()] + text[closing.end():]
        else:
            text = text[closing.end():]

    # An unfinished reasoning block is never safe to show as an answer.
    opening = re.search(open_tag, text, flags=re.IGNORECASE)
    if opening:
        text = text[:opening.start()]
    return text.strip()


class BaseLLM(BaseModule):
    """LLM模块基类，所有LLM实现必须继承此类"""
    
    def initialize(self) -> None:
        """初始化LLM，子类应在完成初始化后设置 self._initialized = True"""
        pass

    def ensure_initialized(self) -> None:
        """Load the backend only when the first generation request arrives."""
        if not self._initialized:
            self.initialize()
    
    def handle_message(self, message: Message) -> None:
        """处理消息：根据消息类型和action分发到不同的处理方法"""
        # 只处理请求类型的消息
        if message.type == MessageType.REQUEST:
            # 如果action是generate，表示要求LLM生成文本
            if message.payload.get('action') == 'generate':
                self.ensure_initialized()
                # 从消息内容中提取messages列表（标准格式）
                messages = message.payload.get('messages', [])
                tools = message.payload.get('tools')
                # 统一使用结构化响应；旧后端默认由 generate() 包装。
                response = self.generate_response(messages, tools=tools)
                response.content = _hide_reasoning_markup(response.content)
                # 将生成结果作为响应消息发回给请求方
                self.send(
                    target=message.source,                        # 回复给原始请求方
                    payload={
                        'response': response.content,
                        'tool_calls': [
                            {
                                'id': call.call_id,
                                'type': 'function',
                                'function': {
                                    'name': call.name,
                                    'arguments': call.arguments,
                                },
                            }
                            for call in response.tool_calls
                        ],
                        'usage': response.usage,
                        'raw': response.raw,
                    },
                    msg_type=MessageType.RESPONSE,                # 消息类型为响应
                    correlation_id=message.correlation_id         # 携带原消息的correlation_id
                )
    
    def generate(self, messages: List[Dict[str, str]]) -> str:
        """
        生成文本，子类必须实现此方法
        :param messages: 标准messages格式，如[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        :return: 模型生成的文本
        """
        raise NotImplementedError

    def generate_response(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Generate a normalized response; subclasses may add native tool calls."""
        return LLMResponse(content=self.generate(messages))
    
    def shutdown(self) -> None:
        """关闭LLM，释放资源，子类应在完成清理后设置 self._initialized = False"""
        pass

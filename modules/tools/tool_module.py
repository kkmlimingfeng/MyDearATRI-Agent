"""
工具模块 - 可插拔的工具管理器
"""
from typing import Any
from .base_tool import BaseTool
from bus.base import Message, MessageType


class ToolModule(BaseTool):
    """工具模块，通过总线接收工具调用请求并执行已注册的工具函数"""

    def handle_message(self, message: Message) -> None:
        """
        处理来自总线的消息

        支持 action:
            - 'call': 调用指定工具，参数通过 tool_name 和 params 传递
            - 'get_tool_descriptions': 返回所有已注册工具的描述信息
            - 'format_tool_descriptions': 返回格式化的工具说明 Markdown 文本
        """
        if message.type != MessageType.REQUEST:
            return

        action = message.payload.get('action')
        if action == 'call':
            self._handle_call(message)
        elif action == 'get_tool_descriptions':
            self._handle_get_descriptions(message)
        elif action == 'format_tool_descriptions':
            self._handle_format_descriptions(message)

    def _handle_call(self, message: Message) -> None:
        """处理工具调用请求"""
        tool_name = message.payload.get('tool_name')
        tool_kwargs = message.payload.get('params', {})

        tool_func = self.get_tool(tool_name)
        if tool_func is None:
            self.send(
                target=message.source,
                payload={'error': f'工具 {tool_name} 不存在'},
                msg_type=MessageType.RESPONSE,
                correlation_id=message.correlation_id
            )
            return

        try:
            result = tool_func(**tool_kwargs)
            self.send(
                target=message.source,
                payload={'result': result},
                msg_type=MessageType.RESPONSE,
                correlation_id=message.correlation_id
            )
        except Exception as e:
            self.send(
                target=message.source,
                payload={'error': str(e)},
                msg_type=MessageType.RESPONSE,
                correlation_id=message.correlation_id
            )

    def _handle_get_descriptions(self, message: Message) -> None:
        """返回工具描述结构化数据"""
        self.send(
            target=message.source,
            payload={'descriptions': self.get_tool_descriptions()},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

    def _handle_format_descriptions(self, message: Message) -> None:
        """返回格式化后的工具说明文本"""
        self.send(
            target=message.source,
            payload={'text': self.format_tool_descriptions()},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

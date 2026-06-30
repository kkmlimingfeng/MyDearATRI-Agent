"""
工具模块 - 可插拔的工具管理器
"""
from .base_tool import BaseTool
from bus.base import Message, MessageType


class ToolModule(BaseTool):
    """工具模块，通过总线接收工具调用请求并执行已注册的工具函数"""

    def handle_message(self, message: Message) -> None:
        """
        处理来自总线的消息

        支持 action:
            - 'call': 调用指定工具，参数通过 tool_name 和 params 传递
            - 'list_tools': 列出所有工具及其启用状态
            - 'set_tool_enabled': 设置指定工具的启用状态
        """
        if message.type != MessageType.REQUEST:
            return

        action = message.payload.get('action')
        if action == 'call':
            self._handle_call(message)
        elif action == 'list_tools':
            self._handle_list_tools(message)
        elif action == 'set_tool_enabled':
            self._handle_set_enabled(message)
        elif action == 'get_tool_descriptions':
            self._handle_get_tool_descriptions(message)
        elif action == 'format_tool_descriptions':
            self._handle_format_tool_descriptions(message)

    def _handle_call(self, message: Message) -> None:
        """执行工具调用"""
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

        if not self.is_tool_enabled(tool_name):
            self.send(
                target=message.source,
                payload={'error': f'工具 {tool_name} 已被禁用'},
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

    def _handle_list_tools(self, message: Message) -> None:
        """返回工具列表及启用状态"""
        self.send(
            target=message.source,
            payload={'tools': self.list_tools()},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

    def _handle_get_tool_descriptions(self, message: Message) -> None:
        """返回所有已启用工具的结构化描述"""
        self.send(
            target=message.source,
            payload={'descriptions': self.get_tool_descriptions()},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

    def _handle_format_tool_descriptions(self, message: Message) -> None:
        """返回适合拼接到系统提示词的工具描述文本"""
        self.send(
            target=message.source,
            payload={'text': self.format_tool_descriptions()},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

    def _handle_set_enabled(self, message: Message) -> None:
        """设置工具启用状态"""
        tool_name = message.payload.get('tool_name')
        enabled = bool(message.payload.get('enabled', True))

        if tool_name not in self._tools:
            self.send(
                target=message.source,
                payload={'error': f'工具 {tool_name} 不存在'},
                msg_type=MessageType.RESPONSE,
                correlation_id=message.correlation_id
            )
            return

        self.set_tool_enabled(tool_name, enabled)
        self.send(
            target=message.source,
            payload={'success': True, 'tool_name': tool_name, 'enabled': enabled},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

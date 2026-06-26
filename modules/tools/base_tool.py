"""
工具模块基类
"""
from typing import Dict, Any, Callable
from modules.base import BaseModule
from bus.base import Message, MessageType


class BaseTool(BaseModule):
    """工具模块基类"""
    
    def __init__(self, module_id: str, bus):
        super().__init__(module_id, bus)
        self._tools: Dict[str, Callable] = {}
    
    def initialize(self) -> None:
        """初始化工具"""
        pass
    
    def register_tool(self, name: str, func: Callable) -> None:
        """注册工具函数"""
        self._tools[name] = func
    
    def handle_message(self, message: Message) -> None:
        """处理消息"""
        if message.type == MessageType.REQUEST:
            if message.payload.get('action') == 'call':
                tool_name = message.payload.get('tool_name')
                params = message.payload.get('params', {})
                
                if tool_name in self._tools:
                    try:
                        result = self._tools[tool_name](**params)
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
                            msg_type=MessageType.ERROR,
                            correlation_id=message.correlation_id
                        )
                else:
                    self.send(
                        target=message.source,
                        payload={'error': f'Tool {tool_name} not found'},
                        msg_type=MessageType.ERROR,
                        correlation_id=message.correlation_id
                    )
    
    def shutdown(self) -> None:
        """关闭工具"""
        self._tools.clear()

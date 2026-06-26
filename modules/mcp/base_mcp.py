"""
MCP模块基类 - Model Context Protocol
"""
from typing import Dict, Any, List
from modules.base import BaseModule
from bus.base import Message, MessageType


class BaseMCP(BaseModule):
    """MCP模块基类"""
    
    def initialize(self) -> None:
        """初始化MCP"""
        pass
    
    def handle_message(self, message: Message) -> None:
        """处理消息"""
        if message.type == MessageType.REQUEST:
            action = message.payload.get('action')
            
            if action == 'execute':
                context = message.payload.get('context')
                result = self.execute(context)
                self.send(
                    target=message.source,
                    payload={'result': result},
                    msg_type=MessageType.RESPONSE
                )
    
    def execute(self, context: Dict[str, Any]) -> Any:
        """执行MCP协议，子类必须实现"""
        raise NotImplementedError
    
    def shutdown(self) -> None:
        """关闭MCP"""
        pass

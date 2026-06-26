"""
记忆模块基类
"""
from typing import Dict, Any, List
from modules.base import BaseModule
from bus.base import Message, MessageType


class BaseMemory(BaseModule):
    """记忆模块基类"""
    
    def initialize(self) -> None:
        """初始化记忆"""
        pass
    
    def handle_message(self, message: Message) -> None:
        """处理消息"""
        if message.type == MessageType.REQUEST:
            action = message.payload.get('action')
            
            if action == 'store':
                key = message.payload.get('key')
                value = message.payload.get('value')
                self.store(key, value)
                self.send(
                    target=message.source,
                    payload={'status': 'ok'},
                    msg_type=MessageType.RESPONSE
                )
            
            elif action == 'recall':
                key = message.payload.get('key')
                value = self.recall(key)
                self.send(
                    target=message.source,
                    payload={'value': value},
                    msg_type=MessageType.RESPONSE
                )
    
    def store(self, key: str, value: Any) -> None:
        """存储记忆，子类必须实现"""
        raise NotImplementedError
    
    def recall(self, key: str) -> Any:
        """检索记忆，子类必须实现"""
        raise NotImplementedError
    
    def shutdown(self) -> None:
        """关闭记忆"""
        pass

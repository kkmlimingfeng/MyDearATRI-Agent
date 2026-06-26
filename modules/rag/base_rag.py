"""
RAG模块基类
"""
from typing import Dict, Any, List
from modules.base import BaseModule
from bus.base import Message, MessageType


class BaseRAG(BaseModule):
    """RAG模块基类"""
    
    def initialize(self) -> None:
        """初始化RAG"""
        pass
    
    def handle_message(self, message: Message) -> None:
        """处理消息"""
        if message.type == MessageType.REQUEST:
            action = message.payload.get('action')
            
            if action == 'retrieve':
                query = message.payload.get('query')
                results = self.retrieve(query)
                self.send(
                    target=message.source,
                    payload={'results': results},
                    msg_type=MessageType.RESPONSE
                )
    
    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        """检索相关文档，子类必须实现"""
        raise NotImplementedError
    
    def shutdown(self) -> None:
        """关闭RAG"""
        pass

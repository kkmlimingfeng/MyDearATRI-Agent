"""
模块基类 - 所有模块的接口定义
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from bus.base import BaseBus, Message, MessageType


class BaseModule(ABC):
    """模块基类，所有模块必须实现此接口"""
    
    def __init__(self, module_id: str, bus: BaseBus):
        self.module_id = module_id    # 模块的唯一标识ID
        self.bus = bus                # 总线引用，用于发送和接收消息
        self._initialized = False     # 模块是否已初始化的标志
    
    @abstractmethod
    def initialize(self) -> None:
        """初始化模块，子类实现具体的初始化逻辑（如加载模型、建立连接等）"""
        pass
    
    @abstractmethod
    def handle_message(self, message: Message) -> None:
        """处理接收到的消息，子类实现具体的消息处理逻辑"""
        pass
    
    @abstractmethod
    def shutdown(self) -> None:
        """关闭模块，子类实现清理资源的逻辑（如释放GPU、关闭连接等）"""
        pass
    
    def send(
        self,
        target: str,
        payload: Dict[str, Any],
        msg_type: MessageType = MessageType.REQUEST,
        correlation_id: str = None
    ) -> None:
        """发送消息到指定模块"""
        # 构造消息对象
        message = Message(
            type=msg_type,              # 消息类型，默认是请求
            source=self.module_id,      # 发送方是自己
            target=target,              # 目标模块ID
            payload=payload,            # 消息内容
            correlation_id=correlation_id  # 关联ID，用于请求-响应匹配
        )
        # 通过总线发布消息
        self.bus.publish(message)
    
    def broadcast(self, payload: Dict[str, Any], msg_type: MessageType = MessageType.EVENT) -> None:
        """广播消息给所有模块（target为None表示广播）"""
        # 构造广播消息
        message = Message(
            type=msg_type,              # 消息类型，默认是事件
            source=self.module_id,      # 发送方是自己
            target=None,                # target为None，总线会投递给所有订阅者
            payload=payload             # 消息内容
        )
        # 通过总线发布消息
        self.bus.publish(message)
    
    def register(self) -> None:
        """注册到总线：将自己的handle_message方法作为handler订阅到总线"""
        self.bus.subscribe(self.module_id, self.handle_message)

    def unregister(self) -> None:
        """从总线取消注册：不再接收任何消息"""
        self.bus.unsubscribe(self.module_id)

"""
总线接口协议定义
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Callable


class MessageType(Enum):
    """消息类型枚举，定义模块间通信的消息种类"""
    REQUEST = "request"                   # 请求消息：一个模块向另一个模块发起请求
    RESPONSE = "response"                 # 响应消息：被请求方返回结果给请求方
    EVENT = "event"                       # 事件消息：广播通知，任何感兴趣的模块都可以处理
    ERROR = "error"                       # 错误消息：通知某个操作发生了错误


@dataclass
class Message:
    """消息数据结构，总线上流转的所有数据都封装成Message"""
    type: MessageType                     # 消息类型（请求/响应/事件/错误）
    source: str                           # 发送方模块的唯一标识ID
    target: Optional[str]                 # 目标模块ID，为None时表示广播给所有模块
    payload: Dict[str, Any]               # 消息的实际内容，用字典存储任意键值对
    msg_id: Optional[str] = None          # 消息唯一ID，用于追踪和去重
    correlation_id: Optional[str] = None  # 关联ID，用于将响应与原始请求匹配


class BaseBus(ABC):
    """总线基类，定义模块间通信的接口协议，所有总线实现都必须继承此类"""
    
    @abstractmethod
    def publish(self, message: Message) -> None:
        """发布消息到总线，由总线负责将消息路由到目标模块"""
        pass
    
    @abstractmethod
    def subscribe(self, module_id: str, handler: Callable[[Message], None]) -> None:
        """订阅消息：将模块的handler注册到总线，收到消息时自动调用handler"""
        pass
    
    @abstractmethod
    def unsubscribe(self, module_id: str) -> None:
        """取消订阅：将模块从总线移除，不再接收任何消息"""
        pass
    
    @abstractmethod
    def request(self, source: str, target: str, payload: Dict[str, Any]) -> Message:
        """同步请求-响应模式：发送请求并阻塞等待目标模块返回响应"""
        pass

"""
事件总线实现 - 发布/订阅模式（纯同步）
"""
import uuid
from collections import defaultdict
from typing import Dict, List, Callable, Optional, Any
from .base import BaseBus, Message, MessageType


class EventBus(BaseBus):
    """事件总线，实现模块间的松耦合通信（纯同步）"""
    
    def __init__(self):
        # 订阅者字典：key是模块ID，value是该模块注册的所有handler列表
        self._subscribers: Dict[str, List[Callable[[Message], None]]] = defaultdict(list)
        # 响应结果字典：key是correlation_id，value是响应Message对象
        # 当handler同步处理完消息并回复时，响应会存到这里
        self._responses: Dict[str, Message] = {}
    
    def publish(self, message: Message) -> None:
        """发布消息到总线"""
        # 如果是响应消息且携带correlation_id，说明是某个请求的回复
        if message.type == MessageType.RESPONSE and message.correlation_id:
            # 将响应存入结果字典，request()方法会从这里取
            self._responses[message.correlation_id] = message
            # 响应消息直接返回给请求者，不再广播
            return
        
        # 遍历所有已注册的订阅者模块
        for module_id, handlers in self._subscribers.items():
            # 如果消息有明确的目标模块，且不是当前模块，则跳过（定向投递）
            if message.target and message.target != module_id:
                continue
            # 调用当前模块的每一个handler
            for handler in handlers:
                try:
                    handler(message)  # 执行模块的消息处理函数
                except Exception as e:
                    print(f"Error in handler for {module_id}: {e}")  # handler出错不影响其他模块
    
    def subscribe(self, module_id: str, handler: Callable[[Message], None]) -> None:
        """订阅消息：将handler添加到指定模块的handler列表中"""
        self._subscribers[module_id].append(handler)
    
    def unsubscribe(self, module_id: str) -> None:
        """取消订阅：将指定模块的所有handler从总线中移除"""
        if module_id in self._subscribers:
            del self._subscribers[module_id]
    
    def request(self, source: str, target: str, payload: Dict[str, Any], timeout: float = 30.0) -> Message:
        """
        同步请求-响应模式：发送请求并等待响应
        当前实现是纯同步的：publish()会同步调用handler，handler同步处理后回复，
        回复的RESPONSE消息会被publish()存入_responses字典，publish()返回后直接取出。
        """
        # 生成唯一的correlation_id，用于匹配请求和响应
        msg_id = str(uuid.uuid4())
        # 构造请求消息
        message = Message(
            type=MessageType.REQUEST,        # 类型为请求
            source=source,                   # 发送方
            target=target,                   # 接收方
            payload=payload,                 # 请求内容
            correlation_id=msg_id            # 关联ID，响应时会原样带回
        )
        
        # 将请求消息发布到总线
        # publish()内部会同步调用目标handler，handler处理后回复RESPONSE，
        # RESPONSE被存入self._responses[msg_id]
        self.publish(message)
        
        # 从结果字典中取出响应
        response = self._responses.pop(msg_id, None)
        # 如果没有收到响应，抛出超时异常
        if response is None:
            raise TimeoutError(f"请求超时: 模块 {target} 未响应 (correlation_id={msg_id})")
        # 返回响应消息
        return response
    
    def clear(self) -> None:
        """清空所有订阅和待处理请求，用于重置总线状态"""
        self._subscribers.clear()
        self._responses.clear()

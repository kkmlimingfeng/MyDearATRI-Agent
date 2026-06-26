"""
工具模块 - 可插拔的工具管理器
"""
from typing import Dict, Callable, Any
from modules.base import BaseModule
from bus.base import Message, MessageType


class ToolModule(BaseModule):
    """工具模块，管理可插拔的工具函数"""
    
    def __init__(self, module_id: str, bus):
        """
        初始化工具模块
        
        Args:
            module_id: 模块ID
            bus: 事件总线实例
        """
        super().__init__(module_id, bus)
        # 工具字典：key是工具名，value是工具函数
        self._tools: Dict[str, Callable] = {}
    
    def register_tool(self, name: str, func: Callable) -> None:
        """
        注册一个工具函数
        
        Args:
            name: 工具名称
            func: 工具函数
        """
        self._tools[name] = func
    
    def handle_message(self, message: Message) -> None:
        """
        处理来自总线的消息
        
        Args:
            message: 消息对象
        """
        # 只处理请求类型的消息
        if message.type == MessageType.REQUEST:
            action = message.payload.get('action')
            
            # 如果action是call，表示调用工具
            if action == 'call':
                # 从消息内容中提取工具名和参数
                tool_name = message.payload.get('tool_name')
                tool_kwargs = message.payload.get('params', {})
                
                # 检查工具是否存在
                if tool_name in self._tools:
                    try:
                        # 调用工具函数
                        result = self._tools[tool_name](**tool_kwargs)
                        # 将结果作为响应消息发回给请求方
                        self.send(
                            target=message.source,
                            payload={'result': result},
                            msg_type=MessageType.RESPONSE,
                            correlation_id=message.correlation_id
                        )
                    except Exception as e:
                        # 工具执行出错
                        self.send(
                            target=message.source,
                            payload={'error': str(e)},
                            msg_type=MessageType.ERROR,
                            correlation_id=message.correlation_id
                        )
                else:
                    # 工具不存在
                    self.send(
                        target=message.source,
                        payload={'error': f'工具 {tool_name} 不存在'},
                        msg_type=MessageType.ERROR,
                        correlation_id=message.correlation_id
                    )
    
    def initialize(self) -> None:
        """初始化工具模块（预留扩展点）"""
        # 当前无需特殊初始化，工具通过 register_tool 动态注册
        pass
    
    def shutdown(self) -> None:
        """关闭工具模块"""
        # 清空工具字典
        self._tools.clear()

"""
工具模块基类

提供工具注册、查找等公共能力，具体消息处理逻辑由子类实现。
"""
from abc import abstractmethod
from typing import Dict, Any, Callable
from modules.base import BaseModule
from bus.base import Message


class BaseTool(BaseModule):
    """工具模块基类，所有具体工具模块应继承此类"""

    def __init__(self, module_id: str, bus):
        super().__init__(module_id, bus)
        # 工具函数字典：key是工具名，value是工具函数
        self._tools: Dict[str, Callable] = {}

    def register_tool(self, name: str, func: Callable) -> None:
        """注册一个工具函数"""
        self._tools[name] = func

    def get_tool(self, name: str) -> Callable:
        """获取已注册的工具函数"""
        return self._tools.get(name)

    @abstractmethod
    def handle_message(self, message: Message) -> None:
        """处理来自总线的消息，子类实现"""
        pass

    def initialize(self) -> None:
        """初始化工具模块（子类可扩展）"""
        self._initialized = True

    def shutdown(self) -> None:
        """关闭工具模块，清空注册的工具"""
        self._tools.clear()
        self._initialized = False

"""
技能模块基类 - 高层能力编排
"""
from typing import Dict, Any, List
from modules.base import BaseModule
from bus.base import Message, MessageType


class BaseSkill(BaseModule):
    """技能模块基类"""
    
    def initialize(self) -> None:
        """初始化技能"""
        pass
    
    def handle_message(self, message: Message) -> None:
        """处理消息"""
        if message.type == MessageType.REQUEST:
            action = message.payload.get('action')
            
            if action == 'execute':
                skill_name = message.payload.get('skill_name')
                params = message.payload.get('params', {})
                result = self.execute(skill_name, params)
                self.send(
                    target=message.source,
                    payload={'result': result},
                    msg_type=MessageType.RESPONSE
                )
    
    def execute(self, skill_name: str, params: Dict[str, Any]) -> Any:
        """执行技能，子类必须实现"""
        raise NotImplementedError
    
    def shutdown(self) -> None:
        """关闭技能"""
        pass

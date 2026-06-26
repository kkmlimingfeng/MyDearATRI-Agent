"""
LLM模块基类 - 定义所有LLM模块的统一接口
"""
from typing import Dict, Any, List
from modules.base import BaseModule
from bus.base import Message, MessageType


class BaseLLM(BaseModule):
    """LLM模块基类，所有LLM实现必须继承此类"""
    
    def initialize(self) -> None:
        """初始化LLM"""
        pass
    
    def handle_message(self, message: Message) -> None:
        """处理消息：根据消息类型和action分发到不同的处理方法"""
        # 只处理请求类型的消息
        if message.type == MessageType.REQUEST:
            # 如果action是generate，表示要求LLM生成文本
            if message.payload.get('action') == 'generate':
                # 从消息内容中提取messages列表（标准格式）
                messages = message.payload.get('messages', [])
                # 调用子类的generate方法生成文本
                response = self.generate(messages)
                # 将生成结果作为响应消息发回给请求方
                self.send(
                    target=message.source,                        # 回复给原始请求方
                    payload={'response': response},               # 响应内容
                    msg_type=MessageType.RESPONSE,                # 消息类型为响应
                    correlation_id=message.correlation_id         # 携带原消息的correlation_id
                )
    
    def generate(self, messages: List[Dict[str, str]]) -> str:
        """
        生成文本，子类必须实现此方法
        :param messages: 标准messages格式，如[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        :return: 模型生成的文本
        """
        raise NotImplementedError
    
    def shutdown(self) -> None:
        """关闭LLM，释放资源"""
        pass

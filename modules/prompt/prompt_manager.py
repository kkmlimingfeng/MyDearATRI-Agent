"""
提示词管理器 - 从SystemPrompt文件夹读取markdown格式的系统提示词
"""
import os
from typing import Dict
from modules.base import BaseModule
from bus.base import Message, MessageType


class PromptManager(BaseModule):
    """提示词管理器，负责加载和提供系统提示词"""
    
    def __init__(self, module_id: str, bus, prompt_dir: str = None):
        # 调用父类初始化
        super().__init__(module_id, bus)
        # 设置提示词目录，默认为SystemPrompt文件夹
        if prompt_dir is None:
            prompt_dir = os.path.join(os.path.dirname(__file__), "SystemPrompt")
        self.prompt_dir = prompt_dir
        # 缓存已加载的提示词，key是提示词名称，value是提示词内容
        self._prompts: Dict[str, str] = {}
    
    def initialize(self) -> None:
        """初始化：扫描并加载SystemPrompt文件夹中的所有markdown文件"""
        # 如果目录存在，扫描所有.md文件
        if os.path.exists(self.prompt_dir):
            for filename in os.listdir(self.prompt_dir):
                # 只处理.md文件
                if filename.endswith(".md"):
                    # 去掉.md后缀作为提示词名称
                    prompt_name = filename[:-3]
                    # 读取文件内容
                    filepath = os.path.join(self.prompt_dir, filename)
                    with open(filepath, 'r', encoding='utf-8') as f:
                        self._prompts[prompt_name] = f.read()
        self._initialized = True
    
    def get_system_prompt(self, prompt_name: str = 'default') -> str:
        """
        获取系统提示词
        :param prompt_name: 提示词名称（对应SystemPrompt文件夹中的文件名，不含.md后缀）
        :return: 系统提示词内容
        """
        # 如果提示词名称不存在，返回默认提示词
        return self._prompts.get(prompt_name, self._prompts.get('default', ''))
    
    def list_prompts(self):
        """列出所有可用的提示词名称"""
        return list(self._prompts.keys())
    
    def handle_message(self, message: Message) -> None:
        """处理来自总线的消息"""
        # 只处理请求类型的消息
        if message.type == MessageType.REQUEST:
            action = message.payload.get('action')
            
            # 如果action是get_system_prompt，表示获取系统提示词
            if action == 'get_system_prompt':
                # 从消息内容中提取提示词名称
                prompt_name = message.payload.get('prompt_name', 'default')
                # 获取系统提示词
                system_prompt = self.get_system_prompt(prompt_name)
                # 将系统提示词作为响应消息发回给请求方
                self.send(
                    target=message.source,                        # 回复给原始请求方
                    payload={'system_prompt': system_prompt},     # 系统提示词内容
                    msg_type=MessageType.RESPONSE,                # 消息类型为响应
                    correlation_id=message.correlation_id         # 携带原消息的correlation_id
                )

            # 如果action是get_prompt_list，表示列出所有可用提示词
            elif action == 'get_prompt_list':
                # 获取所有可用提示词名称
                prompt_list = self.list_prompts()
                # 将提示词列表作为响应消息发回给请求方
                self.send(
                    target=message.source,                        # 回复给原始请求方
                    payload={'prompt_list': prompt_list},         # 提示词列表
                    msg_type=MessageType.RESPONSE,                # 消息类型为响应
                    correlation_id=message.correlation_id         # 携带原消息的correlation_id
                )
    
    def shutdown(self) -> None:
        """关闭提示词管理器"""
        self._prompts.clear()
        self._initialized = False

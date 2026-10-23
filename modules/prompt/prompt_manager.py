"""
提示词管理器 - 从SystemPrompt文件夹读取markdown格式的系统提示词

参考 OpenClaw 的 workspace 配置体系，将系统提示词拆分为：
- AGENT-zh.md / AGENT-en.md：Agent 运行规则、输出格式、可用工具与技能
- SOUL-zh.md / SOUL-en.md：Agent 人格、语气、价值观
- USER-zh.md：用户个人信息与偏好（各语言共用）
- HEARTBEAT-zh.md / HEARTBEAT-en.md：定时任务与主动行为（当前为空）
- reviewer-zh.md / reviewer-en.md：后台审查提示词

最终系统提示词按所选语言的 AGENT -> SOUL -> USER -> HEARTBEAT 顺序拼接。
"""
import os
from typing import Dict, List
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
        # 缓存已加载的提示词片段，key是文件名（不含.md），value是内容
        self._prompts: Dict[str, str] = {}
        # User profile and heartbeat are shared by both prompt languages.
        self._bootstrap_files: List[str] = ['USER-zh']

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

    def get_prompt(self, prompt_name: str) -> str:
        """
        获取单个提示词片段
        :param prompt_name: 提示词名称（对应SystemPrompt文件夹中的文件名，不含.md后缀）
        :return: 提示词内容，不存在则返回空字符串
        """
        resolved_name = self._resolve_prompt_name(prompt_name)
        return self._prompts.get(resolved_name, '')

    def _resolve_prompt_name(self, prompt_name: str) -> str:
        if prompt_name in self._prompts:
            return prompt_name
        legacy_names = {'AGENT': 'AGENT-zh', 'SOUL': 'SOUL-zh', 'reviewer': 'reviewer-zh'}
        localized_name = legacy_names.get(prompt_name, '')
        return localized_name if localized_name in self._prompts else ''

    def get_system_prompt(self, prompt_name: str = 'default') -> str:
        """
        获取完整的系统提示词。

        拼接规则：
        1. 基础规则层：优先使用 prompt_name 对应的文件；
           若 prompt_name 为 'default' 或对应文件不存在，则回退到 AGENT-zh.md。
        2. 追加相同语言的 AGENT、SOUL、HEARTBEAT，以及共享的 USER-zh.md。

        :param prompt_name: 基础提示词名称
        :return: 完整的系统提示词内容
        """
        # 确定基础规则文件
        resolved_name = self._resolve_prompt_name(prompt_name)
        base_name = resolved_name or 'AGENT-zh'
        language = 'en' if base_name.endswith('-en') else 'zh'
        bootstrap_files = [f'AGENT-{language}', f'SOUL-{language}', *self._bootstrap_files, f'HEARTBEAT-{language}']

        base_prompt = self._prompts.get(base_name, '')
        parts: List[str] = [base_prompt] if base_prompt else []

        # 按固定顺序追加其他 bootstrap 文件
        for name in bootstrap_files:
            # 基础文件已经作为 parts[0] 加入，避免重复
            if name == base_name:
                continue
            content = self._prompts.get(name, '')
            if content:
                parts.append(content)

        return "\n\n".join(parts).strip()

    def list_prompts(self):
        """列出所有可用的提示词片段名称"""
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

            # 获取单个提示词片段（用于前端分别编辑）
            elif action == 'get_prompt':
                prompt_name = message.payload.get('prompt_name', '')
                self.send(
                    target=message.source,
                    payload={'prompt': self.get_prompt(prompt_name)},
                    msg_type=MessageType.RESPONSE,
                    correlation_id=message.correlation_id
                )

    def shutdown(self) -> None:
        """关闭提示词管理器"""
        self._prompts.clear()
        self._initialized = False

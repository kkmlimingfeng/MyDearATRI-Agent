"""
Reviewer 模块 - 事后审查与总结

在一轮对话结束后，Reviewer 接收完整对话记录，调用 LLM 进行结构化总结，
输出需要写入长期记忆和用户画像的更新项。

该模块不直接操作文件，只返回结构化的审查结果，由 ReactAgent 负责应用。
"""
import json
import re
from typing import Dict, Any, List
from datetime import datetime
from modules.base import BaseModule
from bus.base import Message, MessageType


class ReviewerModule(BaseModule):
    """Reviewer 模块：审查对话并输出记忆/画像更新建议"""

    def __init__(self, module_id: str, bus, llm_id: str = 'llm'):
        super().__init__(module_id, bus)
        # 默认使用与主 Agent 相同的 LLM 模块
        self.llm_id = llm_id

    def initialize(self) -> None:
        """初始化 Reviewer 模块"""
        self._initialized = True

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """通过总线调用 LLM 生成回复"""
        try:
            response = self.bus.request(
                source=self.module_id,
                target=self.llm_id,
                payload={
                    'action': 'generate',
                    'messages': messages
                }
            )
            return response.payload.get('response', '')
        except Exception as e:
            raise RuntimeError(f"Reviewer 调用 LLM 失败: {e}")

    def _parse_review_result(self, text: str) -> Dict[str, Any]:
        """
        解析 LLM 输出的 JSON。

        会先尝试直接 json.loads，如果失败则尝试从文本中提取 JSON 代码块。
        """
        text = text.strip()
        if not text:
            return self._empty_result()

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 或 {...}
        code_block_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1))
            except json.JSONDecodeError:
                pass

        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return self._empty_result()

    def _empty_result(self) -> Dict[str, Any]:
        """返回空的审查结果"""
        return {
            'memory_entries': [],
            'user_profile_updates': {},
            'summary': ''
        }

    def review(
        self,
        system_prompt: str,
        conversation_text: str
    ) -> Dict[str, Any]:
        """
        审查对话并返回结构化结果。

        :param system_prompt: Reviewer 使用的系统提示词
        :param conversation_text: 需要审查的对话文本
        :return: 包含 memory_entries、user_profile_updates、summary 的字典
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": conversation_text}
        ]

        output = self._call_llm(messages)
        return self._parse_review_result(output)

    def handle_message(self, message: Message) -> None:
        """处理总线消息

        支持 action:
            - 'review': 审查对话
              payload 需包含:
                - 'system_prompt': Reviewer 系统提示词
                - 'conversation_text': 对话文本
        """
        if message.type != MessageType.REQUEST:
            return

        action = message.payload.get('action')
        if action != 'review':
            return

        system_prompt = message.payload.get('system_prompt', '')
        conversation_text = message.payload.get('conversation_text', '')

        try:
            result = self.review(system_prompt, conversation_text)
            self.send(
                target=message.source,
                payload={'result': result},
                msg_type=MessageType.RESPONSE,
                correlation_id=message.correlation_id
            )
        except Exception as e:
            self.send(
                target=message.source,
                payload={'error': str(e)},
                msg_type=MessageType.RESPONSE,
                correlation_id=message.correlation_id
            )

    def shutdown(self) -> None:
        """关闭 Reviewer 模块"""
        self._initialized = False

"""
技能模块 - 可插拔的技能管理器
"""
from .base_skill import BaseSkill
from bus.base import Message, MessageType


class SkillModule(BaseSkill):
    """技能模块，通过总线接收请求并返回已注册技能的描述信息"""

    def handle_message(self, message: Message) -> None:
        """
        处理来自总线的消息

        支持 action:
            - 'get_skill_descriptions': 返回所有已启用技能的结构化描述
            - 'format_skill_overview': 返回启用的技能目录简介（用于系统提示词）
            - 'format_skill_descriptions': 返回格式化的完整技能说明
            - 'get_skill_detail': 返回指定技能的完整 SKILL.md 内容
            - 'list_skills': 列出所有技能及其启用状态
            - 'set_skill_enabled': 设置指定技能的启用状态
        """
        if message.type != MessageType.REQUEST:
            return

        action = message.payload.get('action')
        if action == 'get_skill_descriptions':
            self._handle_get_descriptions(message)
        elif action == 'format_skill_overview':
            self._handle_format_overview(message)
        elif action == 'format_skill_descriptions':
            self._handle_format_descriptions(message)
        elif action == 'get_skill_detail':
            self._handle_get_detail(message)
        elif action == 'list_skills':
            self._handle_list_skills(message)
        elif action == 'set_skill_enabled':
            self._handle_set_enabled(message)

    def _handle_get_descriptions(self, message: Message) -> None:
        """返回技能描述结构化数据"""
        self.send(
            target=message.source,
            payload={'descriptions': self.get_skill_descriptions()},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

    def _handle_format_overview(self, message: Message) -> None:
        """返回用于系统提示词的技能目录简介"""
        self.send(
            target=message.source,
            payload={'text': self.format_skill_overview()},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

    def _handle_format_descriptions(self, message: Message) -> None:
        """返回格式化后的完整技能说明文本"""
        self.send(
            target=message.source,
            payload={'text': self.format_skill_descriptions()},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

    def _handle_get_detail(self, message: Message) -> None:
        """返回指定技能的完整内容"""
        skill_name = message.payload.get('skill_name', '')
        skill = self.get_skill(skill_name)
        if not skill:
            payload = {'error': f'技能 {skill_name} 不存在或没有 SKILL.md'}
        elif not self.is_skill_enabled(skill_name):
            payload = {'error': f'技能 {skill_name} 已被禁用'}
        else:
            payload = {'detail': self.get_skill_detail(skill_name)}
        self.send(
            target=message.source,
            payload=payload,
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

    def _handle_list_skills(self, message: Message) -> None:
        """返回技能列表及启用状态"""
        self.send(
            target=message.source,
            payload={'skills': self.list_skills()},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

    def _handle_set_enabled(self, message: Message) -> None:
        """设置技能启用状态"""
        skill_name = message.payload.get('skill_name', '')
        enabled = bool(message.payload.get('enabled', True))

        if skill_name not in self._skills:
            self.send(
                target=message.source,
                payload={'error': f'技能 {skill_name} 不存在'},
                msg_type=MessageType.RESPONSE,
                correlation_id=message.correlation_id
            )
            return

        self.set_skill_enabled(skill_name, enabled)
        self.send(
            target=message.source,
            payload={'success': True, 'skill_name': skill_name, 'enabled': enabled},
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id
        )

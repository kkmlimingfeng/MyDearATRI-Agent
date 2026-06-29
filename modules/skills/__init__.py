"""
技能模块包

提供技能的自动发现、描述提取和总线接入能力。
"""
from .base_skill import BaseSkill
from .skill_module import SkillModule

__all__ = ['BaseSkill', 'SkillModule']

"""
技能模块基类

提供技能注册、扫描、描述提取等公共能力，
具体消息处理逻辑由子类实现。

每个技能的 SKILL.md 支持 YAML frontmatter，例如：
---
name: recommend_travel
description: "推荐旅游地点，用于查询天气和景点"
---
"""
import os
from abc import abstractmethod
from typing import Dict, List, Any
from modules.base import BaseModule
from bus.base import Message


def _parse_frontmatter(content: str) -> tuple:
    """
    解析 SKILL.md 顶部的 YAML-like frontmatter。

    返回 (frontmatter_dict, body)，如果没有 frontmatter 则返回 ({}, content)。
    仅支持简单的 key: value 格式，嵌套结构会被跳过。
    """
    if not content.strip().startswith('---'):
        return {}, content

    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_text = parts[1].strip()
    body = parts[2].strip()
    data: Dict[str, str] = {}

    for line in frontmatter_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if ':' in stripped and not stripped.startswith('-'):
            key, value = stripped.split(':', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            data[key] = value

    return data, body


class BaseSkill(BaseModule):
    """技能模块基类，所有具体技能模块应继承此类"""

    def __init__(self, module_id: str, bus):
        super().__init__(module_id, bus)
        # 技能字典：key是技能文件夹名，value包含 frontmatter、body、full_content
        self._skills: Dict[str, Dict[str, Any]] = {}

    def register_skill(self, folder_name: str, content: str) -> None:
        """
        注册一个技能。

        :param folder_name: 技能所在文件夹名
        :param content: SKILL.md 完整内容
        """
        frontmatter, body = _parse_frontmatter(content)
        self._skills[folder_name] = {
            "frontmatter": frontmatter,
            "body": body,
            "full_content": content,
        }

    def get_skill(self, name: str) -> Dict[str, Any]:
        """获取指定技能的完整信息"""
        return self._skills.get(name, {})

    def get_skill_detail(self, name: str) -> str:
        """获取指定技能的完整 SKILL.md 内容"""
        skill = self._skills.get(name)
        if skill is None:
            return ""
        return skill.get("full_content", "")

    def register_skills_from_directory(self, directory: str) -> None:
        """
        自动扫描目录下的子文件夹，读取每个子文件夹中的 SKILL.md 并注册为技能。

        :param directory: 技能根目录，其下每个子文件夹代表一个技能
        """
        if not os.path.isdir(directory):
            return

        for item in os.listdir(directory):
            skill_path = os.path.join(directory, item)
            if not os.path.isdir(skill_path) or item.startswith('_'):
                continue

            skill_md = os.path.join(skill_path, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue

            with open(skill_md, 'r', encoding='utf-8') as f:
                self.register_skill(item, f.read())

    def _get_skill_name(self, folder_name: str) -> str:
        """获取技能的显示名称，优先使用 frontmatter 中的 name"""
        skill = self._skills.get(folder_name, {})
        return skill.get("frontmatter", {}).get("name") or folder_name

    def _get_skill_title(self, folder_name: str) -> str:
        """获取技能的标题（SKILL.md 中第一个 # 标题），如果没有则返回 name"""
        skill = self._skills.get(folder_name, {})
        body = skill.get("body", "")
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith('# '):
                return stripped[2:].strip()
        return self._get_skill_name(folder_name)

    def _get_skill_description(self, folder_name: str) -> str:
        """获取技能的简短描述，优先使用 frontmatter 中的 description"""
        skill = self._skills.get(folder_name, {})
        desc = skill.get("frontmatter", {}).get("description", "")
        if desc:
            return desc
        # 如果没有 frontmatter description，尝试取正文第一段非空文本
        body = skill.get("body", "")
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                return stripped
        return ""

    def get_skill_descriptions(self) -> List[Dict[str, str]]:
        """
        获取所有已注册技能的结构化描述信息。

        每个技能包含：folder_name, name, description
        """
        return [
            {
                "folder_name": folder_name,
                "name": self._get_skill_name(folder_name),
                "description": self._get_skill_description(folder_name),
            }
            for folder_name in self._skills
        ]

    def format_skill_overview(self) -> str:
        """
        输出技能目录简介，适合拼接到系统提示词。
        只包含技能名和一句话描述，不包含完整 SKILL.md。
        """
        if not self._skills:
            return ""

        lines = ["## 可用技能Skills\n"]
        for folder_name in self._skills:
            name = self._get_skill_name(folder_name)
            title = self._get_skill_title(folder_name)
            desc = self._get_skill_description(folder_name)
            if title and title != name:
                lines.append(f'- `{name}`（{title}）: {desc}')
            else:
                lines.append(f'- `{name}`: {desc}')

        return "\n".join(lines).strip()

    def format_skill_descriptions(self) -> str:
        """
        将所有技能描述格式化为 Markdown 字符串（包含完整内容）。
        适用于需要查看完整技能文档的场景。
        """
        if not self._skills:
            return ""

        lines = ["## 可用技能\n"]
        for folder_name, skill in self._skills.items():
            name = self._get_skill_name(folder_name)
            lines.append(f"### {name}\n")
            lines.append(skill.get("body", "").strip())
            lines.append("")

        return "\n".join(lines).strip()

    @abstractmethod
    def handle_message(self, message: Message) -> None:
        """处理来自总线的消息，子类实现"""
        pass

    def initialize(self) -> None:
        """初始化技能模块（子类可扩展）"""
        self._initialized = True

    def shutdown(self) -> None:
        """关闭技能模块，清空注册的技能"""
        self._skills.clear()
        self._initialized = False

"""
技能模块基类

提供技能注册、扫描、描述提取等公共能力，
支持通过配置文件控制每个技能的启用/禁用状态，
具体消息处理逻辑由子类实现。

每个技能的 SKILL.md 支持 YAML frontmatter，例如：
---
name: recommend_travel
description: "推荐旅游地点，用于查询天气和景点"
---
"""
import os
import json
from abc import abstractmethod
from typing import Dict, List, Any, Optional
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

    def __init__(self, module_id: str, bus, config_path: Optional[str] = None):
        super().__init__(module_id, bus)
        # 技能字典：key是技能文件夹名，value包含 frontmatter、body、full_content
        self._skills: Dict[str, Dict[str, Any]] = {}
        # 技能级开关配置文件路径（JSON），为空则不使用配置
        self._config_path: Optional[str] = config_path
        # 每个技能的启用状态，默认全部启用
        self._enabled_skills: Dict[str, bool] = {}

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
        # 新注册的技能默认启用
        if folder_name not in self._enabled_skills:
            self._enabled_skills[folder_name] = True

    def get_skill(self, name: str) -> Dict[str, Any]:
        """获取指定技能的完整信息"""
        return self._skills.get(name, {})

    def get_skill_detail(self, name: str) -> str:
        """获取指定技能的完整 SKILL.md 内容"""
        skill = self._skills.get(name)
        if skill is None:
            return ""
        return skill.get("full_content", "")

    def is_skill_enabled(self, name: str) -> bool:
        """查询指定技能是否启用，未配置则默认启用"""
        return self._enabled_skills.get(name, True)

    def set_skill_enabled(self, name: str, enabled: bool) -> None:
        """设置指定技能的启用状态（仅影响内存，不自动写文件）"""
        if name in self._skills:
            self._enabled_skills[name] = enabled

    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有技能及其启用状态，供前端页面读取"""
        return [
            {
                "folder_name": folder_name,
                "name": self._get_skill_name(folder_name),
                "enabled": self.is_skill_enabled(folder_name)
            }
            for folder_name in self._skills
        ]

    def _load_enabled_config(self) -> None:
        """
        从配置文件加载技能启用状态。

        如果配置文件不存在，则根据当前已注册技能自动生成一份全部启用的配置。
        如果配置文件中缺少某些已注册技能，则默认启用并合并到配置中。
        """
        if not self._config_path:
            for name in self._skills:
                if name not in self._enabled_skills:
                    self._enabled_skills[name] = True
            return

        config: Dict[str, bool] = {}
        if os.path.isfile(self._config_path):
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except Exception as e:
                print(f"[警告] 加载技能配置 {self._config_path} 失败: {e}")

        changed = False
        for name in self._skills:
            if name in config:
                self._enabled_skills[name] = bool(config[name])
            else:
                self._enabled_skills[name] = True
                config[name] = True
                changed = True

        if not os.path.isfile(self._config_path) or changed:
            try:
                os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
                with open(self._config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[警告] 保存技能配置 {self._config_path} 失败: {e}")

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
        body = skill.get("body", "")
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                return stripped
        return ""

    def get_skill_descriptions(self) -> List[Dict[str, str]]:
        """
        获取所有已启用技能的结构化描述信息。

        每个技能包含：folder_name, name, description
        """
        return [
            {
                "folder_name": folder_name,
                "name": self._get_skill_name(folder_name),
                "description": self._get_skill_description(folder_name),
            }
            for folder_name in self._skills
            if self.is_skill_enabled(folder_name)
        ]

    def format_skill_overview(self) -> str:
        """
        输出启用的技能目录简介，适合拼接到系统提示词。
        只包含技能名和一句话描述，不包含完整 SKILL.md。
        """
        if not self._skills:
            return ""

        lines = ["## 可用技能\n"]
        for folder_name in self._skills:
            if not self.is_skill_enabled(folder_name):
                continue
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
        将所有启用技能描述格式化为 Markdown 字符串（包含完整内容）。
        """
        if not self._skills:
            return ""

        lines = ["## 可用技能\n"]
        for folder_name, skill in self._skills.items():
            if not self.is_skill_enabled(folder_name):
                continue
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
        """初始化技能模块，加载技能级开关配置"""
        self._load_enabled_config()
        self._initialized = True

    def shutdown(self) -> None:
        """关闭技能模块，清空注册的技能"""
        self._skills.clear()
        self._enabled_skills.clear()
        self._initialized = False

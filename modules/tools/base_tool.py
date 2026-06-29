"""
工具模块基类

提供工具注册、查找、自动扫描、描述提取等公共能力，
支持通过配置文件控制每个工具的启用/禁用状态，
具体消息处理逻辑由子类实现。
"""
import importlib.util
import inspect
import json
import os
import re
from abc import abstractmethod
from typing import Dict, Any, Callable, List, Optional
from modules.base import BaseModule
from bus.base import Message


def system_tool(func: Callable) -> Callable:
    """
    标记一个函数为系统工具。

    被标记的函数会被 ToolModule 自动发现并注册到总线。
    """
    func.__tool__ = True  # type: ignore[attr-defined]
    return func


def _parse_docstring(func: Callable) -> Dict[str, Any]:
    """
    解析函数 docstring，提取描述、参数说明、返回值和示例。

    支持的段落标记：Args / Arguments / Returns / Return / Example / Examples
    """
    doc = inspect.getdoc(func) or ""
    lines = doc.splitlines()

    sections: Dict[str, Any] = {
        "description": "",
        "args": {},
        "returns": "",
        "example": "",
    }
    current = "description"

    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped in ("Args:", "Arguments:"):
            current = "args"
            continue
        if stripped in ("Returns:", "Return:"):
            current = "returns"
            continue
        if stripped in ("Example:", "Examples:"):
            current = "example"
            continue
        if not stripped:
            continue

        if current == "description":
            sections["description"] += raw_line.strip() + " "
        elif current == "args":
            # 支持 "name: description" 或 "name (type): description"
            match = re.match(r'(\w+)(?:\s*\([^)]*\))?\s*:\s*(.*)', stripped)
            if match:
                arg_name, arg_desc = match.groups()
                sections["args"][arg_name] = arg_desc
        elif current == "returns":
            sections["returns"] += raw_line.strip() + " "
        elif current == "example":
            sections["example"] += raw_line.strip() + " "

    sections["description"] = sections["description"].strip()
    sections["returns"] = sections["returns"].strip()
    sections["example"] = sections["example"].strip()
    return sections


class BaseTool(BaseModule):
    """工具模块基类，所有具体工具模块应继承此类"""

    def __init__(self, module_id: str, bus, config_path: Optional[str] = None):
        super().__init__(module_id, bus)
        # 工具函数字典：key是工具名，value是工具函数
        self._tools: Dict[str, Callable] = {}
        # 工具级开关配置文件路径（JSON），为空则不使用配置
        self._config_path: Optional[str] = config_path
        # 每个工具的启用状态，默认全部启用
        self._enabled_tools: Dict[str, bool] = {}

    def register_tool(self, name: str, func: Callable) -> None:
        """注册一个工具函数"""
        self._tools[name] = func
        # 新注册的工具默认启用
        if name not in self._enabled_tools:
            self._enabled_tools[name] = True

    def get_tool(self, name: str) -> Callable:
        """获取已注册的工具函数"""
        return self._tools.get(name)

    def is_tool_enabled(self, name: str) -> bool:
        """查询指定工具是否启用，未配置则默认启用"""
        return self._enabled_tools.get(name, True)

    def set_tool_enabled(self, name: str, enabled: bool) -> None:
        """设置指定工具的启用状态（仅影响内存，不自动写文件）"""
        if name in self._tools:
            self._enabled_tools[name] = enabled

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有工具及其启用状态，供前端页面读取"""
        return [
            {"name": name, "enabled": self.is_tool_enabled(name)}
            for name in self._tools
        ]

    def _load_enabled_config(self) -> None:
        """
        从配置文件加载工具启用状态。

        如果配置文件不存在，则根据当前已注册工具自动生成一份全部启用的配置。
        如果配置文件中缺少某些已注册工具，则默认启用并合并到配置中。
        """
        if not self._config_path:
            # 没有配置路径时，所有工具按默认启用处理
            for name in self._tools:
                if name not in self._enabled_tools:
                    self._enabled_tools[name] = True
            return

        config: Dict[str, bool] = {}
        if os.path.isfile(self._config_path):
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except Exception as e:
                print(f"[警告] 加载工具配置 {self._config_path} 失败: {e}")

        # 合并配置：已注册工具按配置项，未配置默认启用
        changed = False
        for name in self._tools:
            if name in config:
                self._enabled_tools[name] = bool(config[name])
            else:
                self._enabled_tools[name] = True
                config[name] = True
                changed = True

        # 如果配置文件不存在或缺少工具，自动生成/更新配置文件
        if not os.path.isfile(self._config_path) or changed:
            try:
                os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
                with open(self._config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[警告] 保存工具配置 {self._config_path} 失败: {e}")

    def register_tools_from_directory(
        self,
        directory: str,
        pattern: str = r'^(get_|tool_)'
    ) -> None:
        """
        自动扫描目录下的 .py 文件，注册符合条件的工具函数。

        注册规则（满足任一即可）：
        - 函数带有 @system_tool 装饰器（即 __tool__ = True）
        - 函数名匹配 pattern（默认以 get_ 或 tool_ 开头）

        :param directory: 工具脚本所在目录
        :param pattern: 函数名匹配正则，默认为 r'^(get_|tool_)'
        """
        if not os.path.isdir(directory):
            return

        for filename in os.listdir(directory):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue

            filepath = os.path.join(directory, filename)
            module_name = f"auto_tool_{filename[:-3]}"
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                # 某个工具依赖缺失或脚本本身有错误时，跳过该文件不影响其他工具
                print(f"[警告] 加载工具文件 {filepath} 失败: {e}")
                continue

            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if getattr(obj, '__tool__', False) or re.match(pattern, name):
                    self.register_tool(name, obj)

    def get_tool_descriptions(self) -> List[Dict[str, Any]]:
        """
        获取所有已启用工具的结构化描述信息。

        每个工具包含：name, description, params, args, returns, example
        """
        descriptions = []
        for name, func in self._tools.items():
            if not self.is_tool_enabled(name):
                continue

            sig = inspect.signature(func)
            params = []
            for param_name, param in sig.parameters.items():
                param_info: Dict[str, Any] = {"name": param_name}
                if param.annotation != inspect.Parameter.empty:
                    param_info["type"] = param.annotation
                if param.default != inspect.Parameter.empty:
                    param_info["default"] = param.default
                params.append(param_info)

            parsed = _parse_docstring(func)
            descriptions.append({
                "name": name,
                "description": parsed["description"],
                "params": params,
                "args": parsed["args"],
                "returns": parsed["returns"],
                "example": parsed["example"],
            })
        return descriptions

    @staticmethod
    def _format_type(annotation: Any) -> str:
        """将类型注解格式化为可读字符串"""
        if annotation is inspect.Parameter.empty:
            return "Any"
        if hasattr(annotation, '__name__'):
            return annotation.__name__
        if hasattr(annotation, '__origin__'):
            origin = getattr(annotation, '__origin__')
            args = getattr(annotation, '__args__', ())
            origin_name = getattr(origin, '__name__', str(origin))
            args_str = ", ".join(
                getattr(a, '__name__', str(a)) for a in args
            )
            return f"{origin_name}[{args_str}]"
        return str(annotation)

    def format_tool_descriptions(self) -> str:
        """
        将所有启用工具的描述格式化为适合拼接到系统提示词的 Markdown 字符串。
        """
        descs = self.get_tool_descriptions()
        if not descs:
            return ""

        lines = ["## 可用工具\n"]
        for desc in descs:
            params_str = ", ".join(
                f'{p["name"]}: {self._format_type(p.get("type"))}'
                for p in desc["params"]
            )
            lines.append(f'- `{desc["name"]}({params_str})`: {desc["description"]}')
            for param in desc["params"]:
                arg_desc = desc["args"].get(param["name"])
                if arg_desc:
                    lines.append(f'  - `{param["name"]}`: {arg_desc}')
            if desc["example"]:
                lines.append(f'  - 示例：`{desc["example"]}`')
            if desc["returns"]:
                lines.append(f'  - 返回值：{desc["returns"]}')
            lines.append("")

        return "\n".join(lines).strip()

    @abstractmethod
    def handle_message(self, message: Message) -> None:
        """处理来自总线的消息，子类实现"""
        pass

    def initialize(self) -> None:
        """初始化工具模块，加载工具级开关配置"""
        self._load_enabled_config()
        self._initialized = True

    def shutdown(self) -> None:
        """关闭工具模块，清空注册的工具"""
        self._tools.clear()
        self._enabled_tools.clear()
        self._initialized = False

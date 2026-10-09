"""Configuration driven module loading.

Modules are regular :class:`BaseModule` implementations.  The loader only
needs their import path and constructor arguments, so adding a module does not
require editing the application entry point.
"""
import importlib
import json
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from modules.base import BaseModule


class ModuleConfigError(ValueError):
    """Raised when the module configuration cannot be loaded."""


def load_module_specs(config_path: str) -> List[Dict[str, Any]]:
    """Load module specifications from a JSON file."""
    if not os.path.isfile(config_path):
        raise ModuleConfigError(f"模块配置文件不存在: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ModuleConfigError(f"加载模块配置失败: {exc}") from exc

    specs = config.get("modules") if isinstance(config, dict) else config
    if not isinstance(specs, list):
        raise ModuleConfigError("模块配置必须是数组，或包含 modules 数组的对象")
    if any(not isinstance(spec, dict) for spec in specs):
        raise ModuleConfigError("modules 中的每一项都必须是对象")
    return [dict(spec) for spec in specs]


def import_class(path: str) -> type:
    """Import a class from a dotted path such as ``pkg.module.Class``."""
    if not isinstance(path, str) or "." not in path:
        raise ModuleConfigError(f"无效的模块类路径: {path!r}")
    module_name, class_name = path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ModuleConfigError(f"无法加载模块类 {path}: {exc}") from exc
    if not isinstance(cls, type):
        raise ModuleConfigError(f"模块类路径不是类: {path}")
    return cls


def resolve_config_value(value: Any, project_root: str) -> Any:
    """Resolve environment and project-root references in JSON values.

    Supported forms are ``{"$env": "NAME", "default": "value"}`` and
    strings containing ``${PROJECT_ROOT}``.  Lists and dictionaries are
    resolved recursively.
    """
    if isinstance(value, dict):
        if "$env" in value:
            env_name = value["$env"]
            default = value.get("default", "")
            return os.environ.get(env_name, default)
        if "$path" in value:
            return resolve_config_value(
                os.path.join(project_root, str(value["$path"])), project_root
            )
        return {key: resolve_config_value(item, project_root) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_config_value(item, project_root) for item in value]
    if isinstance(value, str):
        return value.replace("${PROJECT_ROOT}", project_root)
    return value


def _run_setup(module: Any, setup: Iterable[Mapping[str, Any]], project_root: str) -> None:
    """Run optional, declarative setup hooks after construction."""
    if not isinstance(setup, list):
        raise ModuleConfigError(f"模块 {module.module_id} 的 setup 必须是数组")
    for hook in setup:
        if isinstance(hook, str):
            method_name, kwargs = hook, {}
        else:
            if not isinstance(hook, Mapping):
                raise ModuleConfigError(f"模块 {module.module_id} 的 setup 项必须是对象")
            method_name = hook.get("method")
            kwargs = hook.get("kwargs", {})
        if not method_name:
            raise ModuleConfigError(f"模块 {module.module_id} 的 setup 缺少 method")
        method = getattr(module, method_name, None)
        if not callable(method):
            raise ModuleConfigError(
                f"模块 {module.module_id} 不支持 setup 方法: {method_name}"
            )
        method(**resolve_config_value(kwargs, project_root))


def build_modules(
    specs: Iterable[Mapping[str, Any]],
    bus: Any,
    project_root: str,
    enabled_overrides: Optional[Mapping[str, bool]] = None,
) -> Tuple[Dict[str, Any], Dict[str, bool]]:
    """Instantiate configured modules and run their optional setup hooks.

    Every module receives ``(module_id, bus, **kwargs)``.  This is the only
    constructor contract required from a plugin.
    """
    enabled_overrides = enabled_overrides or {}
    modules: Dict[str, Any] = {}
    enabled: Dict[str, bool] = {}
    seen_ids = set()

    for raw_spec in specs:
        spec = dict(raw_spec)
        module_id = spec.get("id")
        class_path = spec.get("class")
        if not module_id or not class_path:
            raise ModuleConfigError("每个模块必须包含 id 和 class")
        if module_id in seen_ids:
            raise ModuleConfigError(f"模块 ID 重复: {module_id}")
        seen_ids.add(module_id)

        is_enabled = bool(spec.get("enabled", True))
        if module_id in enabled_overrides:
            is_enabled = bool(enabled_overrides[module_id])
        enabled[module_id] = is_enabled
        if not is_enabled:
            continue

        cls = import_class(class_path)
        if not issubclass(cls, BaseModule):
            raise ModuleConfigError(f"模块 {module_id} 必须继承 BaseModule")
        kwargs = resolve_config_value(spec.get("kwargs", {}), project_root)
        if not isinstance(kwargs, dict):
            raise ModuleConfigError(f"模块 {module_id} 的 kwargs 必须是对象")
        module = cls(module_id, bus, **kwargs)
        _run_setup(module, spec.get("setup", []), project_root)
        modules[module_id] = module

    return modules, enabled

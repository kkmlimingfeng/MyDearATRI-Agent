"""Registry for node implementations and editor-facing node descriptions."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import threading
from pathlib import Path
from typing import Dict, Iterable, Type

from .base import BaseNode


class NodeRegistry:
    """Maps stable node type identifiers to implementations."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Type[BaseNode]] = {}
        self._extension_nodes: Dict[Path, set[str]] = {}
        self._extension_mtimes: Dict[Path, int] = {}
        self._extension_errors: Dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def extension_dir(self) -> Path:
        return Path(__file__).resolve().parent / "extensions"

    def refresh_extensions(self) -> None:
        """Discover added or changed node extensions without restarting the API."""
        directory = self.extension_dir
        with self._lock:
            if not directory.is_dir():
                return
            paths = {path.resolve() for path in directory.glob("*.py") if not path.name.startswith("_")}
            for removed in set(self._extension_nodes) - paths:
                for node_type in self._extension_nodes.pop(removed):
                    self._nodes.pop(node_type, None)
                self._extension_mtimes.pop(removed, None)
                self._extension_errors.pop(str(removed), None)

            for path in sorted(paths):
                try:
                    mtime = path.stat().st_mtime_ns
                except OSError as exc:
                    self._extension_errors[str(path)] = str(exc)
                    continue
                if self._extension_mtimes.get(path) == mtime:
                    continue

                module_name = "atri_node_extension_" + hashlib.sha1(str(path).encode()).hexdigest()
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    self._extension_errors[str(path)] = "无法创建 Python 模块加载器"
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                try:
                    # Bypass timestamp-granularity in .pyc validation so rapid
                    # edits with an unchanged file size still reload correctly.
                    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
                    classes = getattr(module, "NODES", None)
                    if not isinstance(classes, (list, tuple)) or not classes:
                        raise ValueError("扩展文件必须导出非空 NODES = [NodeClass, ...]")
                    old_types = self._extension_nodes.get(path, set())
                    for node in classes:
                        if not isinstance(node, type) or not issubclass(node, BaseNode):
                            raise TypeError("NODES 中的每一项都必须是 BaseNode 子类")
                    replacements = {node.node_type: node for node in classes}
                    if len(replacements) != len(classes):
                        raise ValueError("同一扩展中的 node_type 不能重复")
                    for node_type in replacements:
                        existing = self._nodes.get(node_type)
                        if existing is not None and node_type not in old_types:
                            raise ValueError(f"节点类型已被占用: {node_type}")
                    for node_type in old_types:
                        self._nodes.pop(node_type, None)
                    self._nodes.update(replacements)
                    self._extension_nodes[path] = set(replacements)
                    self._extension_mtimes[path] = mtime
                    self._extension_errors.pop(str(path), None)
                except Exception as exc:
                    self._extension_errors[str(path)] = str(exc)
                    sys.modules.pop(module_name, None)

    def extension_errors(self) -> Dict[str, str]:
        self.refresh_extensions()
        with self._lock:
            return dict(self._extension_errors)

    def register(self, node_class: Type[BaseNode]) -> None:
        if not issubclass(node_class, BaseNode):
            raise TypeError("节点实现必须继承 BaseNode")
        node_type = node_class.node_type
        if not node_type or node_type == "base.node":
            raise ValueError("节点必须声明唯一的 node_type")
        with self._lock:
            existing = self._nodes.get(node_type)
            if existing is not None and existing is not node_class:
                raise ValueError(f"节点类型重复注册: {node_type}")
            self._nodes[node_type] = node_class

    def get(self, node_type: str) -> Type[BaseNode]:
        self.refresh_extensions()
        try:
            with self._lock:
                return self._nodes[node_type]
        except KeyError as exc:
            raise KeyError(f"未注册的节点类型: {node_type}") from exc

    def create(self, node_type: str, config=None) -> BaseNode:
        return self.get(node_type)(config)

    def describe(self) -> list[dict]:
        self.refresh_extensions()
        with self._lock:
            return [node_class.describe() for node_class in self._nodes.values()]

    def register_many(self, node_classes: Iterable[Type[BaseNode]]) -> None:
        for node_class in node_classes:
            self.register(node_class)


node_registry = NodeRegistry()

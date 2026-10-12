"""Stable contracts for authoring workflow nodes backed by modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


@dataclass(frozen=True)
class PortDefinition:
    """A named input or output on a node."""

    name: str
    data_type: str = "any"
    required: bool = True
    description: str = ""
    label_zh: str = ""
    label_en: str = ""
    hidden: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.data_type,
            "required": self.required,
            "description": self.description,
            "label_zh": self.label_zh,
            "label_en": self.label_en,
            "hidden": self.hidden,
        }


@dataclass
class NodeResult:
    """Named output values plus optional execution metadata."""

    outputs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeContext:
    """Services available to a node during one workflow run."""

    run_id: str
    node_id: str
    modules: Mapping[str, Any]
    emit: Any
    cancelled: Any = None
    services: Mapping[str, Any] = field(default_factory=dict)

    def get_module(self, module_id: str) -> Any:
        try:
            return self.modules[module_id]
        except KeyError as exc:
            raise KeyError(f"节点 {self.node_id} 绑定的模块不存在: {module_id}") from exc


class BaseNode(ABC):
    """Base class for executable graph nodes.

    Node configuration belongs to the workflow JSON. Reusable capabilities
    such as model providers or memory stores are supplied through NodeContext.
    """

    node_type = "base.node"
    title = "Base node"
    category = "core"
    description = ""
    defaults: Dict[str, Any] = {}
    module_id: Optional[str] = None
    preview = ""
    inputs: tuple[PortDefinition, ...] = ()
    outputs: tuple[PortDefinition, ...] = ()
    config_schema: Dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self, config: Optional[Mapping[str, Any]] = None) -> None:
        self.config = dict(config or {})

    @abstractmethod
    def execute(
        self,
        inputs: Mapping[str, Any],
        context: NodeContext,
    ) -> NodeResult:
        """Run this node and return values keyed by declared output ports."""

    @classmethod
    def describe(cls) -> Dict[str, Any]:
        return {
            "type": cls.node_type,
            "title": cls.title,
            "category": cls.category,
            "description": cls.description,
            "defaults": dict(cls.defaults),
            "module_id": cls.module_id,
            "preview": cls.preview,
            "implementation": f"{cls.__module__}.{cls.__name__}",
            "inputs": [port.as_dict() for port in cls.inputs],
            "outputs": [port.as_dict() for port in cls.outputs],
            "config_schema": cls.config_schema,
        }

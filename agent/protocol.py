"""Shared protocol objects for model calls, tools, and execution traces."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """A model-requested tool invocation in provider-neutral form."""

    call_id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)

    def to_message_dict(self) -> Dict[str, Any]:
        """Return the OpenAI-compatible assistant message fragment."""
        import json

        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class ToolResult:
    """A normalized result returned by a tool executor."""

    call_id: str
    name: str
    status: str
    output: Any = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LLMResponse:
    """Provider-neutral model response used by the Agent runtime."""

    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    raw: Any = None


@dataclass
class TraceEvent:
    """An observable execution event shared by CLI, web UI, and evaluation."""

    event_type: str
    run_id: str
    node_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

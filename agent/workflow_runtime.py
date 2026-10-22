"""Module host and trace services for graph-controlled workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base_agent import BaseAgent
from .protocol import TraceEvent
from .tool_executor import ToolExecutor
from .tool_call_parser import parse_embedded_tool_calls
from .trace import MemoryTraceSink


class WorkflowRuntime(BaseAgent):
    def __init__(self, max_iterations: int = 5, max_history_turns: int = 10, display_mode: str = "normal"):
        super().__init__()
        self.max_iterations = max_iterations
        self.max_history_turns = max_history_turns
        self.display_mode = display_mode
        self.trace_sink = MemoryTraceSink()
        self.tool_executor = None
        self.tool_approval_callback = None
        self._active_run_id = ""
        self._history: list[dict[str, Any]] = []

    def run(self, user_input: str, **kwargs) -> str:
        raise RuntimeError("图工作流须通过 GraphExecutor 运行")

    def _trace(self, event_type: str, data: dict, node_id: str | None = None) -> None:
        self.trace_sink.emit(TraceEvent(
            event_type=event_type,
            run_id=self._active_run_id,
            node_id=node_id,
            data=data,
            timestamp=datetime.now().astimezone().isoformat(),
        ))

    def get_trace_events(self) -> list[TraceEvent]:
        return self.trace_sink.snapshot()

    def _get_tool_executor(self) -> ToolExecutor:
        if self.tool_executor is None:
            self.tool_executor = ToolExecutor(
                bus=self.bus,
                enabled=lambda module_id: self._enabled.get(module_id, False),
                trace=self._trace,
                approve=self.tool_approval_callback,
            )
        return self.tool_executor

    def _parse_embedded_tool_calls(self, content: str) -> list[dict]:
        calls = parse_embedded_tool_calls(content, self._active_run_id)
        if calls:
            self._trace("tool_call_adapted", {"calls": calls})
        return calls

    def _add_to_history(self, user_input: str, answer: str) -> None:
        self._history.extend(({"role": "user", "content": user_input}, {"role": "assistant", "content": answer}))
        self._history = self._history[-self.max_history_turns * 2:]

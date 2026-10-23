"""Provider-neutral tool execution for Agent runtimes.

The model adapter produces a normalized call and this class owns the rest of
the boundary: module availability, dispatch, normalized errors, timing, and
trace events.  A future web runtime can reuse it without importing
the graph workflow runtime.
"""

from __future__ import annotations

import ast
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.protocol import ToolCall, ToolResult


class ToolExecutor:
    """Execute tools exposed by a configured tool module."""

    def __init__(
        self,
        bus: Any,
        enabled: Callable[[str], bool],
        trace: Optional[Callable[[str, Dict[str, Any], Optional[str]], None]] = None,
        show: Optional[Callable[..., None]] = None,
        approve: Optional[Callable[[ToolCall, Dict[str, Any]], bool]] = None,
    ) -> None:
        self.bus = bus
        self.enabled = enabled
        self.trace = trace or (lambda event_type, data, node_id=None: None)
        self.show = show or (lambda text, **kwargs: None)
        self.approve = approve

    @staticmethod
    def parse_legacy_action(action: str) -> Tuple[str, Dict[str, Any]]:
        """Parse the old ``name(key="value")`` compatibility format."""
        tool_name_match = re.search(r"(\w+)\(", action)
        if not tool_name_match:
            raise ValueError(f"无法解析工具调用 '{action}'")

        tool_name = tool_name_match.group(1)
        args_match = re.search(r"\((.*)\)", action)
        args_str = args_match.group(1).strip() if args_match else ""
        tool_kwargs: Dict[str, Any] = {}
        if not args_str:
            return tool_name, tool_kwargs

        for key, dquote, squote, bare in re.findall(
            r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^,]+))',
            args_str,
        ):
            value: Any = dquote or squote or bare.strip()
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                pass
            tool_kwargs[key] = value
        return tool_name, tool_kwargs

    def execute_legacy_action(self, action: str, tools_module_id: str) -> ToolResult:
        try:
            name, arguments = self.parse_legacy_action(action)
        except ValueError as exc:
            return ToolResult(call_id="legacy", name="", status="error", error=str(exc))
        return self.execute(
            ToolCall(call_id="legacy", name=name, arguments=arguments),
            tools_module_id,
        )

    def execute(
        self,
        call: ToolCall,
        tools_module_id: str = "tools",
        tool_context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Execute one call and always return a structured result."""
        started = time.perf_counter()
        if not self.enabled(tools_module_id):
            result = ToolResult(
                call_id=call.call_id,
                name=call.name,
                status="error",
                error="工具模块已禁用",
            )
            self.trace("tool_completed", result.as_dict(), "tools")
            return result

        try:
            metadata_response = self.bus.request(
                source="agent",
                target=tools_module_id,
                payload={"action": "get_tool_metadata", "tool_name": call.name},
            )
            metadata = metadata_response.payload.get("metadata", {})
        except Exception:
            metadata = {}
        risk = metadata.get("risk", "read")
        if risk in {"write", "execute", "sandbox"} and not (
            self.approve and self.approve(call, metadata)
        ):
            if risk == "execute":
                error = "命令执行未启用；请在沙箱设置中明确开启命令和 MCP 工具执行。"
            elif risk == "sandbox":
                error = "沙箱权限不允许此文件操作，或目标路径无法确认。"
            else:
                error = f"工具调用未获批准 (risk={risk})"
            result = ToolResult(
                call_id=call.call_id,
                name=call.name,
                status="denied",
                error=error,
            )
            self.trace("tool_call_denied", result.as_dict(), "tools")
            return result

        self.trace(
            "tool_call_requested",
            {"call_id": call.call_id, "name": call.name, "arguments": call.arguments},
            "tools",
        )
        self.show(f"正在调用工具: {call.name}({call.arguments})")
        try:
            response = self.bus.request(
                source="agent",
                target=tools_module_id,
                payload={
                    "action": "call",
                    "tool_name": call.name,
                    "params": call.arguments,
                    "tool_context": tool_context or {},
                },
            )
            if "error" in response.payload:
                result = ToolResult(
                    call_id=call.call_id,
                    name=call.name,
                    status="error",
                    error=str(response.payload["error"]),
                )
            else:
                result = ToolResult(
                    call_id=call.call_id,
                    name=call.name,
                    status="success",
                    output=response.payload.get("result"),
                )
        except Exception as exc:
            result = ToolResult(
                call_id=call.call_id,
                name=call.name,
                status="error",
                error=str(exc),
            )

        result.duration_ms = round((time.perf_counter() - started) * 1000)
        self.trace("tool_completed", result.as_dict(), "tools")
        if result.status == "error":
            self.show(result.error or "工具调用失败", level="error")
        return result

    @staticmethod
    def from_provider_call(raw: Dict[str, Any]) -> ToolCall:
        """Normalize an OpenAI/llama.cpp tool-call dictionary."""
        function = raw.get("function") or {}
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        return ToolCall(
            call_id=str(raw.get("id") or ""),
            name=str(function.get("name") or ""),
            arguments=arguments,
        )

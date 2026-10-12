"""Parse textual tool calls emitted by local chat templates."""

from __future__ import annotations

import html
import json
import re
from typing import Any


_TOOL_CALL = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_FUNCTION = re.compile(r"<function=([\w.:-]+)>\s*(.*?)\s*</function>", re.DOTALL)
_PARAMETER = re.compile(r"<parameter=([\w.-]+)>\s*(.*?)\s*</parameter>", re.DOTALL)


def _parameters(text: str) -> dict[str, Any] | None:
    arguments = {}
    end = 0
    for match in _PARAMETER.finditer(text):
        if text[end:match.start()].strip() or match.group(1) in arguments:
            return None
        value = html.unescape(match.group(2).strip())
        try:
            arguments[match.group(1)] = json.loads(value)
        except json.JSONDecodeError:
            arguments[match.group(1)] = value
        end = match.end()
    if text[end:].strip() or not arguments:
        return None
    return arguments


def parse_embedded_tool_calls(content: str, run_id: str) -> list[dict[str, Any]]:
    calls = []
    for index, match in enumerate(_TOOL_CALL.finditer(content)):
        body = match.group(1).strip()
        function = _FUNCTION.fullmatch(body)
        try:
            if function:
                name = function.group(1)
                argument_text = function.group(2).strip()
                if argument_text.startswith("<parameter="):
                    arguments = _parameters(argument_text)
                else:
                    arguments = json.loads(argument_text) if argument_text else {}
            else:
                payload = json.loads(body)
                name = payload.get("name") if isinstance(payload, dict) else None
                arguments = payload.get("arguments", {}) if isinstance(payload, dict) else None
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
        except (ValueError, TypeError):
            continue
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            continue
        calls.append({
            "id": f"embedded_{run_id}_{index}",
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        })
    return calls

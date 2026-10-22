"""Execution trace sinks used by the CLI and future web/evaluation runtimes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Protocol, TextIO

from .protocol import TraceEvent


def trace_safe_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Omit encoded image payloads from trace events sent to the browser."""
    result = []
    for message in messages:
        item = {key: value for key, value in message.items() if key != "content"}
        content = message.get("content")
        if isinstance(content, list):
            safe_content = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    safe_content.append({"type": "text", "text": str(part.get("text", ""))})
                elif part.get("type") == "image_url":
                    safe_content.append({"type": "image_url", "image_url": "[图片数据已省略]"})
                else:
                    safe_content.append({"type": part.get("type", "unknown")})
            item["content"] = safe_content
        else:
            item["content"] = content
        result.append(item)
    return result


class TraceSink(Protocol):
    """A destination for normalized execution events."""

    def emit(self, event: TraceEvent) -> None:
        ...


class MemoryTraceSink:
    """Keep events in memory for a web session or an evaluator."""

    def __init__(self) -> None:
        self.events: List[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()


class JsonlTraceSink:
    """Append trace events as JSONL without coupling the runtime to a database."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def emit(self, event: TraceEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event.as_dict(), ensure_ascii=False, default=str))
            stream.write("\n")


class CallbackTraceSink:
    """Adapt a UI/event callback to the trace sink protocol."""

    def __init__(self, callback: Callable[[TraceEvent], None]) -> None:
        self.callback = callback

    def emit(self, event: TraceEvent) -> None:
        self.callback(event)


class CompositeTraceSink:
    """Fan out one event to multiple sinks."""

    def __init__(self, sinks: Iterable[TraceSink]) -> None:
        self.sinks = list(sinks)

    def emit(self, event: TraceEvent) -> None:
        for sink in self.sinks:
            sink.emit(event)

    @property
    def events(self) -> List[TraceEvent]:
        return [
            event
            for sink in self.sinks
            for event in getattr(sink, "events", [])
        ]

    def clear(self) -> None:
        for sink in self.sinks:
            clear = getattr(sink, "clear", None)
            if callable(clear):
                clear()


class NullTraceSink:
    """No-op sink used when callers do not need to retain events."""

    def emit(self, event: TraceEvent) -> None:
        return None

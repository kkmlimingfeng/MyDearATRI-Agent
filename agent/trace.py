"""Execution trace sinks used by the CLI and future web/evaluation runtimes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Protocol, TextIO

from .protocol import TraceEvent


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

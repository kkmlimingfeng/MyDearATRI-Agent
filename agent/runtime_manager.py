"""Process-local lifecycle state for the active workflow runtime."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeState:
    agent: Any = None
    graph_key: str | None = None
    execution_key: str | None = None
    bindings: dict[str, str] = field(default_factory=dict)
    started: bool = False
    workflow_id: str | None = None


class RuntimeManager:
    """Own the active runtime and short-lived asynchronous run jobs."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.state = RuntimeState()
        self.jobs_lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}

    def clear_runtime(self) -> Any:
        """Detach the active runtime and stop its modules."""
        with self.lock:
            agent = self.state.agent
            self.state.agent = None
            self.state.graph_key = None
            self.state.execution_key = None
            self.state.bindings = {}
            self.state.started = False
            self.state.workflow_id = None
        if agent is not None:
            agent.stop()
        return agent

    def create_run_job(self, job_id: str) -> bool:
        with self.jobs_lock:
            if any(not job["done"] for job in self.jobs.values()):
                return False
            self.jobs.clear()
            self.jobs[job_id] = {
                "done": False,
                "result": None,
                "error": None,
                "trace_ready": False,
                "draft": "",
            }
        return True

    def update_run_job(self, job_id: str, **values: Any) -> bool:
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            job.update(values)
        return True

    def mark_run_trace_ready(self, job_id: str) -> bool:
        return self.update_run_job(job_id, trace_ready=True)

    def get_run_job(self, job_id: str) -> dict[str, Any] | None:
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            return dict(job) if job is not None else None

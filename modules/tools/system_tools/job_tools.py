"""Model-facing controls for conversation-owned sandbox jobs."""

from __future__ import annotations

import json

from modules.tools.base_tool import system_tool
from modules.tools.system_tools.job_manager import job_manager


@system_tool(timeout=10, retries=0, context_arguments=("owner_id",))
def job_list(owner_id: str = "") -> str:
    """List background jobs created by the current conversation."""
    return json.dumps(job_manager.list(owner_id), ensure_ascii=False)


@system_tool(timeout=35, retries=0, parallel=False, context_arguments=("owner_id",))
def job_output(job_id: str, wait_seconds: int = 0, owner_id: str = "") -> str:
    """Read new output from a background job, optionally waiting up to 30 seconds.

    Args:
        job_id: Job ID returned by exec_sandbox_cmd
        wait_seconds: Wait for new output or completion, from 0 to 30 seconds

    Returns:
        New stdout/stderr and the current job status.
    """
    return job_manager.output(owner_id, job_id, wait_seconds)


@system_tool(risk="execute", timeout=10, retries=0, parallel=False, context_arguments=("owner_id",))
def job_kill(job_id: str, owner_id: str = "") -> str:
    """Stop a running background job owned by the current conversation.

    Args:
        job_id: Job ID returned by exec_sandbox_cmd

    Returns:
        The final or current job status.
    """
    return job_manager.kill(owner_id, job_id)

"""Structured file tools enforced by the user's Firejail and Landlock policy."""

from __future__ import annotations

import json
import threading
import shutil
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

from modules.sandbox_config import load_sandbox_settings
from modules.sandbox_process import PROJECT_ROOT, sandbox_argv_process_options
from modules.sandbox_landlock import landlock_abi
from modules.tools.base_tool import system_tool


RUNNER = PROJECT_ROOT / "modules" / "sandbox_file_runner.py"
_OBSERVATION_LOCK = threading.RLock()
_OBSERVATIONS: OrderedDict[tuple[str, str], str] = OrderedDict()
_MAX_OBSERVATIONS = 2000


def _run(action: str, **values) -> str:
    payload = json.dumps({"action": action, **values}, ensure_ascii=False)
    try:
        args, environment, workspace = sandbox_argv_process_options(
            [sys.executable, str(RUNNER)],
            runtime_arg_count=2,
            settings=load_sandbox_settings(),
            firejail_path=shutil.which("firejail"),
            landlock_version=landlock_abi(),
        )
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            input=payload,
            timeout=15,
            cwd=workspace,
            env=environment,
        )
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return f"[沙箱文件工具错误] {exc}"
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode:
        return error or "[沙箱文件工具错误] 操作失败"
    return output


def _observation_key(owner_id: str, path: str) -> tuple[str, str]:
    settings = load_sandbox_settings()
    workspace = Path(settings.get("workspace") or PROJECT_ROOT).expanduser()
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = workspace / target
    return (owner_id or "default", str(target.resolve(strict=False)))


def _read_result(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) and isinstance(value.get("version"), str) else None


def _remember(owner_id: str, path: str, version: str) -> None:
    key = _observation_key(owner_id, path)
    with _OBSERVATION_LOCK:
        _OBSERVATIONS[key] = version
        _OBSERVATIONS.move_to_end(key)
        while len(_OBSERVATIONS) > _MAX_OBSERVATIONS:
            _OBSERVATIONS.popitem(last=False)


def _observed(owner_id: str, path: str) -> str | None:
    key = _observation_key(owner_id, path)
    with _OBSERVATION_LOCK:
        version = _OBSERVATIONS.get(key)
        if version:
            _OBSERVATIONS.move_to_end(key)
        return version


def _forget(owner_id: str, path: str) -> None:
    key = _observation_key(owner_id, path)
    with _OBSERVATION_LOCK:
        _OBSERVATIONS.pop(key, None)


@system_tool(risk="sandbox", timeout=20, parallel=False, sandbox_action="read", context_arguments=("owner_id",))
def read_file(path: str, start_line: int = 1, end_line: int = 200, owner_id: str = "") -> str:
    """Read a UTF-8 text file with optional one-based line bounds.

    Args:
        path: File path, relative to the configured workspace or an absolute path allowed by the sandbox
        start_line: First line to return, starting at 1
        end_line: Last line to return, capped to 2 MiB per file

    Returns:
        Numbered file lines.
    """
    raw = _run("read", path=path, start_line=start_line, end_line=end_line, include_version=True)
    result = _read_result(raw)
    if result is None or not isinstance(result.get("text"), str):
        return raw
    _remember(owner_id, path, result["version"])
    return result["text"]


@system_tool(risk="sandbox", timeout=20, parallel=False, sandbox_action="write", context_arguments=("owner_id",))
def write_file(path: str, content: str, owner_id: str = "") -> str:
    """Create a new UTF-8 text file inside a path permitted by the sandbox.

    Args:
        path: New file path, relative to the configured workspace or an absolute path allowed by the sandbox
        content: Complete UTF-8 text to write, up to 2 MiB

    Returns:
        Creation result.
    """
    return _run("write", path=path, content=content)


@system_tool(risk="sandbox", timeout=20, parallel=False, sandbox_action="edit", context_arguments=("owner_id",))
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False, owner_id: str = "") -> str:
    """Replace an exact text match in an existing UTF-8 file.

    Args:
        path: Existing file path, relative to the configured workspace or an absolute path allowed by the sandbox
        old_text: Exact text to replace; by default it must match exactly once
        new_text: Replacement text
        replace_all: Replace all matches when true

    Returns:
        Edit result or a clear match error.
    """
    expected_version = _observed(owner_id, path)
    if expected_version is None:
        return "修改被拒绝：请先使用 read_file 读取目标文件。"
    raw = _run(
        "edit", path=path, old_text=old_text, new_text=new_text,
        replace_all=replace_all, expected_version=expected_version, include_version=True,
    )
    result = _read_result(raw)
    if result is None:
        return raw
    _remember(owner_id, path, result["version"])
    return result.get("text", raw)


@system_tool(risk="sandbox", timeout=20, parallel=False, sandbox_action="delete", context_arguments=("owner_id",))
def delete_file(path: str, owner_id: str = "") -> str:
    """Delete one regular file when the sandbox grants delete permission.

    Args:
        path: Existing regular file path allowed by the sandbox

    Returns:
        Deletion result.
    """
    expected_version = _observed(owner_id, path)
    if expected_version is None:
        return "删除被拒绝：请先使用 read_file 读取目标文件。"
    result = _run("delete", path=path, expected_version=expected_version)
    if result.startswith("已删除"):
        _forget(owner_id, path)
    return result


@system_tool(risk="sandbox", timeout=20, sandbox_action="read", sandbox_path_arg="directory", context_arguments=("owner_id",))
def list_files(directory: str = ".", pattern: str = "**/*", max_results: int = 50, owner_id: str = "") -> str:
    """List files and directories under a sandbox-readable directory.

    Args:
        directory: Root directory to list
        pattern: Glob pattern relative to the root, such as **/*.py
        max_results: Maximum results from 1 to 200

    Returns:
        Matching relative paths.
    """
    return _run("list", directory=directory, pattern=pattern, max_results=max_results)


@system_tool(risk="sandbox", timeout=20, sandbox_action="read", sandbox_path_arg="directory", context_arguments=("owner_id",))
def search_files(query: str, directory: str = ".", pattern: str = "**/*", regex: bool = False, max_results: int = 50, owner_id: str = "") -> str:
    """Search UTF-8 text files inside a sandbox-readable directory.

    Args:
        query: Text to find, or a regular expression when regex is true
        directory: Root directory to search
        pattern: Glob pattern relative to the root, such as **/*.py
        regex: Interpret query as a regular expression
        max_results: Maximum matching lines from 1 to 200

    Returns:
        Matching relative paths, line numbers, and text.
    """
    return _run("search", query=query, directory=directory, pattern=pattern, regex=regex, max_results=max_results)

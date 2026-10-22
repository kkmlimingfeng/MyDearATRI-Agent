"""Build process launch settings that enforce the configured sandbox policy."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Mapping

from modules.sandbox_config import load_sandbox_settings
from modules.sandbox_landlock import landlock_abi


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sandbox_process_options(
    command: str,
    *,
    settings: Mapping | None = None,
    firejail_path: str | None = None,
    landlock_version: int | None = None,
    cwd: str | Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> tuple[list[str], dict[str, str], Path]:
    """Return argv, environment, and cwd for a command inside the file sandbox."""
    firejail_path = firejail_path or shutil.which("firejail")
    if not firejail_path:
        raise RuntimeError("沙箱执行需要安装 Firejail（Linux/WSL）")
    current = dict(settings or load_sandbox_settings())
    landlock_version = landlock_abi() if landlock_version is None else landlock_version
    if current.get("permission") in {"workspace", "custom"} and landlock_version < 3:
        raise RuntimeError("当前 Linux 内核不支持安全文件权限隔离（需要 Landlock ABI 3）")

    workspace = Path(current["workspace"])
    working_directory = Path(cwd).expanduser().resolve(strict=True) if cwd else workspace
    if cwd and not working_directory.is_dir():
        raise ValueError("MCP 工作目录必须是一个目录")

    args = [
        "env", "container=lxc", firejail_path, "--noprofile", "--seccomp", "--caps.drop=all",
    ]
    permissions = current["permissions"]
    outside_can_modify = any(permissions["outside"][action] for action in ("write", "edit", "delete"))
    workspace_can_modify = any(permissions["workspace"][action] for action in ("write", "edit", "delete"))
    if current["permission"] == "workspace" or (current["permission"] == "custom" and not outside_can_modify):
        args.append("--read-only=/")
        if workspace_can_modify:
            args.append(f"--read-write={workspace}")
    elif current["permission"] == "full":
        args.append("--read-write=/")

    runner = PROJECT_ROOT / "modules" / "sandbox_runner.py"
    args.extend([
        sys.executable,
        str(runner),
        command,
        json.dumps(current, ensure_ascii=False),
    ])

    environment = os.environ.copy()
    python_directory = str(Path(sys.executable).parent)
    environment["PATH"] = os.pathsep.join(
        part for part in (
            python_directory,
            str(workspace / ".cache" / "tools" / "bin"),
            environment.get("PATH", ""),
        ) if part
    )
    environment["PYTHON_BIN"] = sys.executable
    environment["PYTHON"] = sys.executable
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.setdefault("npm_config_cache", str(workspace / ".cache" / "npm"))
    environment.setdefault("UV_CACHE_DIR", str(workspace / ".cache" / "uv"))
    environment.setdefault("PIP_CACHE_DIR", str(workspace / ".cache" / "pip"))
    if extra_env:
        environment.update(extra_env)
    return args, environment, working_directory


def quote_command(command: str, args: list[str]) -> str:
    """Quote an executable and arguments for sandbox_runner's bash entrypoint."""
    return shlex.join([command, *args])

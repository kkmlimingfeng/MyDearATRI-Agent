"""
沙箱命令执行工具

基于 firejail 的进程级沙箱，允许技能执行脚本或命令。
需要在系统中安装 firejail：sudo apt install firejail -y
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from modules.sandbox_config import load_sandbox_settings
from modules.sandbox_landlock import landlock_abi
from modules.tools.base_tool import system_tool


@system_tool(risk="execute", timeout=35, retries=0, parallel=False)
def exec_sandbox_cmd(cmd: str, timeout: int = 30) -> str:
    """
    在 firejail 沙箱中执行 shell 命令。

    适用于技能需要执行脚本命令或者获取当前时间的场景。
    使用服务进程的 Python 环境，并在所选工作空间中执行命令。
    默认仅允许工作空间内写入；可在本地工具设置中选择全部文件权限。

    Args:
        cmd: 要在沙箱中执行的 bash 命令
        timeout: 最大执行时间（秒）默认为30秒

    Returns:
        命令的输出内容

    Example:
        exec_sandbox_cmd(cmd="python modules/skills/some_skill/script/step1.py")
        exec_sandbox_cmd(cmd="echo hello && pwd")
        exec_sandbox_cmd(cmd="date '+%Y-%m-%d'")
    """
    # Keep common network clients and permission-changing commands blocked.
    ban_list = {"curl", "wget", "ping", "nc", "sudo", "chmod", "rm -rf"}
    cmd_lower = cmd.lower()
    for word in ban_list:
        if word in cmd_lower:
            return f"[沙盒拦截] 禁止指令：{word}"

    if not shutil.which("firejail"):
        return "[沙盒错误] Firejail 仅支持 Linux/WSL；当前运行环境没有可用的 firejail。"

    try:
        settings = load_sandbox_settings()
    except ValueError as exc:
        return f"[沙盒错误] {exc}"
    workspace = Path(settings["workspace"])
    if settings["permission"] in {"workspace", "custom"} and landlock_abi() < 3:
        return "[沙盒错误] 当前 Linux 内核不支持安全文件权限隔离（需要 Landlock ABI 3）。"

    # WSL2 环境需要 container=lxc 才能正常启动 firejail
    args = [
        "env", "container=lxc",
        "firejail",
        "--noprofile",
        "--seccomp",
        "--caps.drop=all",
    ]
    permissions = settings["permissions"]
    outside_can_modify = any(
        permissions["outside"][action] for action in ("write", "edit", "delete")
    )
    workspace_can_modify = any(
        permissions["workspace"][action] for action in ("write", "edit", "delete")
    )
    if settings["permission"] == "workspace" or (settings["permission"] == "custom" and not outside_can_modify):
        args.append("--read-only=/")
        if workspace_can_modify:
            args.append(f"--read-write={workspace}")
    elif settings["permission"] == "full":
        args.append("--read-write=/")
    args.append(sys.executable)
    args.extend([
        str(Path(__file__).resolve().parents[2] / "sandbox_runner.py"),
        cmd,
        json.dumps(settings, ensure_ascii=False),
    ])

    environment = os.environ.copy()
    python_directory = str(Path(sys.executable).parent)
    environment["PATH"] = os.pathsep.join(
        part for part in (python_directory, environment.get("PATH", "")) if part
    )
    environment["PYTHON_BIN"] = sys.executable
    environment["PYTHON"] = sys.executable
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=workspace,
            env=environment,
        )
        out = proc.stdout
        err = proc.stderr
        return f"OUT:\n{out}\nother:\n{err}"
    except subprocess.TimeoutExpired:
        return "[沙盒错误] 命令执行超时"
    except Exception as e:
        return f"[沙盒错误] {str(e)}"

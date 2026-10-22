"""
沙箱命令执行工具

基于 firejail 的进程级沙箱，允许技能执行脚本或命令。
需要在系统中安装 firejail：sudo apt install firejail -y
"""
import shutil
import subprocess
import sys
from modules.tools.base_tool import system_tool
from modules.sandbox_config import load_sandbox_settings
from modules.sandbox_landlock import landlock_abi
from modules.sandbox_process import sandbox_process_options


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
            if word in {"curl", "wget"}:
                return (
                    f"[沙盒拦截] 禁止指令：{word}。访问网页请使用已安装的 bb-browser 技能，"
                    "例如 `bb-browser site weibo/hot`；微博脚本直连可能返回 HTTP 432，"
                    "可尝试通过已登录的浏览器会话读取。"
                )
            return f"[沙盒拦截] 禁止指令：{word}"

    try:
        args, environment, workspace = sandbox_process_options(
            cmd,
            settings=load_sandbox_settings(),
            firejail_path=shutil.which("firejail"),
            landlock_version=landlock_abi(),
        )
    except (RuntimeError, ValueError) as exc:
        return f"[沙盒错误] {exc}"

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

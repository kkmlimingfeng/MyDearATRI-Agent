"""
沙箱命令执行工具

基于 firejail 的进程级沙箱，允许技能执行脚本或命令。
需要在系统中安装 firejail：sudo apt install firejail -y
"""
import os
import shutil
import subprocess
from modules.tools.base_tool import system_tool


@system_tool
def exec_sandbox_cmd(cmd: str, timeout: int = 30) -> str:
    """
    在 firejail 沙箱中执行 shell 命令。

    适用于技能需要执行脚本或系统命令的场景。
    默认将 SANDBOX_WRITE_PATH（可在 config/.env 中配置）设为可写，其余目录只读。

    Args:
        cmd: 要在沙箱中执行的 shell 命令
        timeout: 最大执行时间（秒）

    Returns:
        命令的标准输出和错误输出

    Example:
        exec_sandbox_cmd(cmd="python modules/skills/some_skill/script/step1.py")
        exec_sandbox_cmd(cmd="echo hello && pwd")
    """
    # 命令黑名单：弥补 WSL2 网络隔离失效等场景
    ban_list = {"curl", "wget", "ping", "nc", "sudo", "rm -rf", "chmod"}
    cmd_lower = cmd.lower()
    for word in ban_list:
        if word in cmd_lower:
            return f"[沙盒拦截] 禁止指令：{word}"

    if not shutil.which("firejail"):
        return (
            "[沙盒错误] 未安装 firejail，请先执行：\n"
            "sudo apt install firejail -y"
        )

    # 从环境变量读取可写路径，默认当前用户主目录
    write_path = os.environ.get("SANDBOX_WRITE_PATH") or os.path.expanduser("~")
    write_path = os.path.abspath(write_path)

    # WSL2 环境需要 container=lxc 才能正常启动 firejail
    args = [
        "env", "container=lxc",
        "firejail",
        "--noprofile",
        "--seccomp",
        "--caps.drop=all",
        "--read-only=/",
        f"--read-write={write_path}",
        "--private-tmp",
        "bash", "-c", cmd
    ]

    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        out = proc.stdout
        err = proc.stderr
        return f"OUT:\n{out}\nother:\n{err}"
    except subprocess.TimeoutExpired:
        return "[沙盒错误] 命令执行超时"
    except Exception as e:
        return f"[沙盒错误] {str(e)}"

"""Compatibility adapter for Skills that declare a standard Bash tool."""

from modules.tools.base_tool import system_tool
from modules.tools.system_tools.bb_browser import bb_browser
from modules.tools.system_tools.exec_sandbox_cmd import exec_sandbox_cmd


@system_tool(risk="execute", timeout=140, retries=0, parallel=False)
def Bash(command: str, timeout: int = 30) -> str:
    """Run a Skill's Bash command through the configured project sandbox.

    Args:
        command: Shell command requested by the Skill.
        timeout: Maximum execution time in seconds, capped at 30.

    Returns:
        The sandbox command output.
    """
    if not isinstance(command, str) or not command.strip():
        return "[沙盒错误] 命令不能为空"
    if command.lstrip().startswith("bb-browser"):
        return bb_browser(command=command, timeout=max(1, min(int(timeout), 120)))
    return exec_sandbox_cmd(cmd=command, timeout=max(1, min(int(timeout), 30)))

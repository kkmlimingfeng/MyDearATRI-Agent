"""Run the installed bb-browser CLI as one sandboxed project tool."""

import ipaddress
import json
import os
import signal
import shlex
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from modules.sandbox_config import load_sandbox_settings
from modules.sandbox_process import PROJECT_ROOT, sandbox_argv_process_options
from modules.tools.base_tool import system_tool


BB_BROWSER_VERSION = "0.14.2"
MAX_OUTPUT_CHARS = 100_000
SHELL_OPERATORS = {"&&", "||", ";", "|", "&", ">", ">>", "<", "<<"}
DAEMON_PROCESSES: dict[str, subprocess.Popen] = {}


def _parse_command(command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip():
        raise ValueError("请提供 bb-browser 子命令")
    if len(command) > 16_000:
        raise ValueError("bb-browser 命令过长")
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ValueError(f"bb-browser 命令引号格式无效：{exc}") from exc
    if arguments and Path(arguments[0]).name == "bb-browser":
        arguments.pop(0)
    if not arguments:
        raise ValueError("请提供 bb-browser 子命令")
    if any(token in SHELL_OPERATORS for token in arguments):
        raise ValueError("一次只能执行一个 bb-browser 命令，不支持 shell 管道或重定向")
    return arguments


def _browser_cli() -> tuple[Path, str] | None:
    link = PROJECT_ROOT / ".cache" / "tools" / "bin" / "bb-browser"
    try:
        cli = link.resolve(strict=True)
        package_root = cli.parent.parent
        package = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    except (OSError, RuntimeError, json.JSONDecodeError):
        return None
    if package.get("name") != "bb-browser" or package.get("version") != BB_BROWSER_VERSION:
        return None
    if not cli.is_file() or PROJECT_ROOT.resolve() not in cli.parents:
        return None
    return cli, BB_BROWSER_VERSION


def _daemon_state(home: Path) -> tuple[dict | None, dict | None]:
    daemon_file = home / "daemon.json"
    try:
        info = json.loads(daemon_file.read_text(encoding="utf-8"))
        host = info["host"]
        port = int(info["port"])
        token = info["token"]
        if not isinstance(token, str) or not token or not 1 <= port <= 65535:
            return None, None
        if host not in {"localhost", "127.0.0.1", "::1"}:
            if not ipaddress.ip_address(host).is_loopback:
                return None, None
        url_host = f"[{host}]" if ":" in host else host
        request = urllib.request.Request(
            f"http://{url_host}:{port}/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=0.8) as response:
            status = json.loads(response.read().decode("utf-8"))
        return info, status
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError, json.JSONDecodeError):
        return None, None


def _healthy_daemon(home: Path) -> bool:
    info, status = _daemon_state(home)
    if not info or not status:
        return False
    return status.get("running") is True and status.get("cdpConnected") is True


def _browser_home(settings: dict, command_args: list[str] | None = None) -> Path:
    user_home = Path.home() / ".bb-browser"
    local_home = Path(settings["workspace"]) / ".cache" / "bb-browser"
    can_read_user_home = settings["permissions"]["outside"]["read"]
    daemon_action = command_args[1:2] if command_args and command_args[0] == "daemon" else []
    if can_read_user_home and _healthy_daemon(user_home):
        return user_home
    if _healthy_daemon(local_home):
        return local_home
    if (
        daemon_action in (["status"], ["stop"], ["shutdown"])
        and can_read_user_home
        and (user_home / "daemon.json").is_file()
    ):
        return user_home
    return local_home


def _cdp_endpoint(settings: dict) -> tuple[str, int, str]:
    configured = os.environ.get("BB_BROWSER_CDP_URL")
    if configured:
        parsed = urlsplit(configured)
        host = parsed.hostname
        port = parsed.port or 9222
        if parsed.scheme not in {"http", "https", "ws", "wss"} or not host:
            raise ValueError("BB_BROWSER_CDP_URL 必须是有效的浏览器调试地址")
        url_host = f"[{host}]" if ":" in host else host
        return host, port, f"http://{url_host}:{port}"

    if settings["permissions"]["outside"]["read"]:
        try:
            info = json.loads((Path.home() / ".bb-browser" / "daemon.json").read_text(encoding="utf-8"))
            host = info["cdpHost"]
            port = int(info["cdpPort"])
            if not 1 <= port <= 65535:
                raise ValueError("端口无效")
            if host not in {"localhost", "127.0.0.1", "::1"} and not ipaddress.ip_address(host).is_loopback:
                raise ValueError("调试地址不是本机地址")
            url_host = f"[{host}]" if ":" in host else host
            return host, port, f"http://{url_host}:{port}"
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
    return "127.0.0.1", 9222, "http://127.0.0.1:9222"


def _stop_local_daemon(home: Path) -> None:
    info, _status = _daemon_state(home)
    if not info:
        return
    url_host = f"[{info['host']}]" if ":" in info["host"] else info["host"]
    request = urllib.request.Request(
        f"http://{url_host}:{info['port']}/shutdown",
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {info['token']}"},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        opener.open(request, timeout=1.5).read()
    except (OSError, urllib.error.URLError):
        pass


def _ensure_browser_daemon(
    home: Path,
    settings: dict,
    node: str,
    daemon_script: Path,
    endpoint: tuple[str, int, str],
    startup_timeout: int = 12,
) -> str | None:
    outside_readable = settings["permissions"]["outside"]["read"]
    if home == Path.home() / ".bb-browser" and outside_readable and _healthy_daemon(home):
        return None
    if home != Path.home() / ".bb-browser" and _healthy_daemon(home):
        return None

    host, cdp_port, _cdp_url = endpoint
    if home != Path.home() / ".bb-browser":
        _stop_local_daemon(home)
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        daemon_port = sock.getsockname()[1]
    finally:
        sock.close()

    argv = [
        node,
        str(daemon_script),
        "--no-chrome",
        "--host",
        "127.0.0.1",
        "--port",
        str(daemon_port),
        "--cdp-host",
        host,
        "--cdp-port",
        str(cdp_port),
    ]
    try:
        args, environment, workspace = sandbox_argv_process_options(
            argv,
            runtime_arg_count=2,
            enforce_landlock=_requires_landlock(settings),
            settings=settings,
            firejail_path=shutil.which("firejail"),
            extra_env={"BB_BROWSER_HOME": str(home)},
        )
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=workspace,
            env=environment,
            start_new_session=True,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return f"[bb-browser 错误] daemon 启动失败：{exc}"

    DAEMON_PROCESSES[str(home)] = process
    deadline = time.monotonic() + max(1, min(startup_timeout, 12))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return "[bb-browser 错误] daemon 启动失败，请检查 Chrome/CDP 地址和工作空间写入权限。"
        if _healthy_daemon(home):
            return None
        time.sleep(0.2)

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
    return "[bb-browser 错误] daemon 未能在时限内连接 CDP；请检查浏览器调试端口。"


def _command_index(command_args: list[str]) -> int:
    index = 0
    while index < len(command_args):
        option = command_args[index]
        if option in {"--json", "--help", "-h", "--version"}:
            index += 1
        elif option in {"--tab", "--port"} and index + 1 < len(command_args):
            index += 2
        else:
            break
    return index


def _command_needs_daemon(command_args: list[str]) -> bool:
    index = _command_index(command_args)
    if index == len(command_args):
        return False
    first = command_args[index]
    subcommand = command_args[index + 1:index + 2]
    if first in {"status", "help", "guide", "star", "-h", "--help"}:
        return False
    if first == "daemon":
        return subcommand == ["start"]
    if first == "site" and subcommand and subcommand[0] in {
        "list", "search", "info", "update", "recommend",
    }:
        return False
    return True


def _requires_landlock(settings: dict) -> bool:
    # Firejail already enforces the standard workspace and full permission matrices.
    if settings["permission"] in {"workspace", "full"}:
        return False
    from modules.sandbox_config import FULL_PERMISSIONS, WORKSPACE_PERMISSIONS

    return not any(
        settings["permissions"] == permissions
        for permissions in (FULL_PERMISSIONS, WORKSPACE_PERMISSIONS)
    )


@system_tool(risk="execute", timeout=140, retries=0, parallel=False)
def bb_browser(command: str, timeout: int = 60) -> str:
    """Run any single bb-browser CLI command through the project sandbox.

    The command accepts the full CLI subcommand, including site, fetch, tabs,
    snapshots, interactions, network tools, traces, and daemon management.
    Files saved with relative paths are resolved inside the selected workspace.

    Args:
        command: bb-browser command and arguments, without shell operators; the `bb-browser` prefix is optional
        timeout: Maximum execution time in seconds, capped at 120

    Returns:
        The CLI output and any error details.

    Example:
        bb_browser(command='site list')
        bb_browser(command='open https://s.weibo.com/top/summary?cate=homepage')
        bb_browser(command='snap -i')
        bb_browser(command='open https://example.com')
        bb_browser(command='snap -i --tab 86c3')
    """
    try:
        timeout = max(1, min(int(timeout), 120))
        cli_info = _browser_cli()
        if cli_info is None:
            return (
                f"[bb-browser 未安装] 请在项目目录运行："
                f"npm install --global --prefix .cache/tools bb-browser@{BB_BROWSER_VERSION}"
            )
        cli, _version = cli_info
        command_args = _parse_command(command)
        node = shutil.which("node")
        if not node:
            return "[bb-browser 错误] 找不到 Node.js，请安装 Node.js 18 或更高版本"
        settings = load_sandbox_settings()
        endpoint = _cdp_endpoint(settings)
        home = _browser_home(settings, command_args)
        daemon_script = cli.parent / "daemon.js"
        if not daemon_script.is_file():
            return "[bb-browser 错误] 安装包缺少 daemon.js，请重新安装固定版本"
        if _command_needs_daemon(command_args):
            startup_error = _ensure_browser_daemon(
                home,
                settings,
                node,
                daemon_script,
                endpoint,
                startup_timeout=timeout,
            )
            if startup_error:
                return startup_error
            command_index = _command_index(command_args)
            if command_args[command_index:command_index + 2] == ["daemon", "start"]:
                command_args = [*command_args[:command_index], "daemon", "status"]
        environment_overrides = {
            "BB_BROWSER_HOME": str(home),
            "BB_BROWSER_CDP_URL": endpoint[2],
            "npm_config_offline": "true",
        }
        argv = [node, str(cli), *command_args]
        use_landlock = _requires_landlock(settings)
        args, environment, workspace = sandbox_argv_process_options(
            argv,
            runtime_arg_count=2,
            enforce_landlock=use_landlock,
            settings=settings,
            firejail_path=shutil.which("firejail"),
            extra_env=environment_overrides,
        )
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=workspace,
            env=environment,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if len(stdout) > MAX_OUTPUT_CHARS:
            stdout = stdout[:MAX_OUTPUT_CHARS] + "\n[输出已截断]"
        if len(stderr) > MAX_OUTPUT_CHARS:
            stderr = stderr[:MAX_OUTPUT_CHARS] + "\n[错误输出已截断]"
        result = f"OUT:\n{stdout}\nother:\n{stderr}"
        if proc.returncode:
            result += f"\nexit code: {proc.returncode}"
            if use_landlock and "EACCES" in stderr:
                result += (
                    "\n[提示] 当前自定义文件权限会阻止该 CLI 操作启动子进程。"
                    "切换到“工作空间”权限后重试。"
                )
        return result
    except subprocess.TimeoutExpired:
        return "[bb-browser 错误] 命令执行超时"
    except (ValueError, OSError, RuntimeError) as exc:
        return f"[bb-browser 错误] {exc}"

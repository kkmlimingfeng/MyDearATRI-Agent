"""Minimal MCP client transports for stdio and Streamable HTTP servers."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from modules.sandbox_process import quote_command, sandbox_process_options


MAX_PROTOCOL_LINE = 4 * 1024 * 1024
MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPProtocolError(RuntimeError):
    pass


class StdioMCPClient:
    def __init__(self, name: str, config: dict[str, Any], timeout: float = 60):
        command = config["command"]
        args = config["args"]
        extra_env = config.get("resolved_env") or {}
        sandbox_command = quote_command(command, args)
        argv, environment, working_directory = sandbox_process_options(
            sandbox_command,
            cwd=config.get("cwd") or None,
            extra_env=extra_env,
        )
        self.name = name
        self.timeout = timeout
        self.process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=working_directory,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=(os.name == "posix"),
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._stderr: list[str] = []
        self._lock = threading.Lock()
        self._next_id = 0
        self._reader_threads = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for thread in self._reader_threads:
            thread.start()

    def _read_stdout(self) -> None:
        stream = self.process.stdout
        if stream is None:
            self._lines.put(None)
            return
        try:
            for line in stream:
                if len(line.encode("utf-8")) > MAX_PROTOCOL_LINE:
                    self._lines.put(None)
                    return
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def _read_stderr(self) -> None:
        stream = self.process.stderr
        if stream is None:
            return
        for line in stream:
            self._stderr.append(line.rstrip()[:1000])
            if len(self._stderr) > 40:
                del self._stderr[:-40]

    def _send(self, message: dict[str, Any]) -> None:
        if self.process.poll() is not None or self.process.stdin is None:
            details = "\n".join(self._stderr[-8:])
            raise MCPProtocolError(f"MCP 服务进程已退出{': ' + details if details else ''}")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > MAX_PROTOCOL_LINE:
            raise MCPProtocolError("MCP 请求超过 4 MB")
        self.process.stdin.write(payload + "\n")
        self.process.stdin.flush()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                message["params"] = params
            self._send(message)
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPProtocolError(f"MCP 请求超时: {method}")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty as exc:
                    raise MCPProtocolError(f"MCP 请求超时: {method}") from exc
                if line is None:
                    details = "\n".join(self._stderr[-8:])
                    raise MCPProtocolError(f"MCP 服务关闭了标准输出{': ' + details if details else ''}")
                try:
                    response = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise MCPProtocolError("MCP 服务在标准输出中发送了无效 JSON-RPC") from exc
                if response.get("id") != request_id:
                    continue
                if response.get("error"):
                    error = response["error"]
                    raise MCPProtocolError(str(error.get("message", error)))
                result = response.get("result")
                if not isinstance(result, dict):
                    raise MCPProtocolError("MCP 服务返回了无效结果")
                return result

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.notify("notifications/exit")
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            if self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        try:
                            os.killpg(self.process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        self.process.kill()
                    self.process.wait(timeout=2)
        for thread in self._reader_threads:
            thread.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass


class HTTPMCPClient:
    def __init__(self, config: dict[str, Any], timeout: float = 60):
        self.url = config["url"]
        self.headers = dict(config.get("headers", {}))
        self.timeout = timeout
        self._next_id = 0
        self._session_id = ""
        self._protocol_version = MCP_PROTOCOL_VERSION
        self._lock = threading.Lock()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._post(message, expect_response=False)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            message: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
            if params is not None:
                message["params"] = params
            response = self._post(message, expect_response=True)
            if response is None:
                raise MCPProtocolError("MCP HTTP 服务没有返回 JSON-RPC 结果")
            if response.get("error"):
                error = response["error"]
                raise MCPProtocolError(str(error.get("message", error)))
            result = response.get("result")
            if not isinstance(result, dict):
                raise MCPProtocolError("MCP HTTP 服务返回了无效结果")
            return result

    def _post(self, message: dict[str, Any], expect_response: bool) -> dict[str, Any] | None:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
            headers["MCP-Protocol-Version"] = self._protocol_version
        request = urllib.request.Request(
            self.url,
            data=json.dumps(message, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise MCPProtocolError(f"MCP HTTP 错误 {exc.code}: {detail[:1000]}") from exc
        except (OSError, TimeoutError) as exc:
            raise MCPProtocolError(f"MCP HTTP 连接失败: {exc}") from exc
        with response:
            self._session_id = response.headers.get("Mcp-Session-Id", self._session_id)
            if response.status in {202, 204} or not expect_response:
                return None
            body = response.read(MAX_PROTOCOL_LINE + 1)
            if len(body) > MAX_PROTOCOL_LINE:
                raise MCPProtocolError("MCP HTTP 响应超过 4 MB")
            content_type = response.headers.get_content_type()
            if content_type == "text/event-stream":
                for line in body.decode("utf-8", errors="replace").splitlines():
                    if line.startswith("data:"):
                        try:
                            candidate = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if candidate.get("id") == message.get("id"):
                            return candidate
                raise MCPProtocolError("MCP SSE 响应中没有匹配的 JSON-RPC 结果")
            if not body:
                return None
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise MCPProtocolError("MCP HTTP 服务返回了无效 JSON-RPC") from exc

    def close(self) -> None:
        if not self._session_id:
            return
        request = urllib.request.Request(
            self.url,
            headers={**self.headers, "Mcp-Session-Id": self._session_id},
            method="DELETE",
        )
        try:
            urllib.request.urlopen(request, timeout=3).close()
        except Exception:
            pass


def initialize_client(client: Any) -> dict[str, Any]:
    result = client.request("initialize", {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "MyDearATRI-Agent", "version": "0.1.0"},
    })
    selected_version = result.get("protocolVersion")
    if isinstance(client, HTTPMCPClient) and isinstance(selected_version, str):
        client._protocol_version = selected_version
    client.notify("notifications/initialized")
    return result

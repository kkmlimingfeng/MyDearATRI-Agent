"""MCP server lifecycle and workflow capability provider."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from bus.base import Message, MessageType
from modules.base import BaseModule

from .client import HTTPMCPClient, MCPProtocolError, StdioMCPClient, initialize_client
from .configuration import CONFIG_PATH, load_servers, public_server_list, resolve_environment, resolve_values


MAX_TOOL_RESULT_CHARS = 80_000


def _tool_alias(server_name: str, tool_name: str) -> str:
    original = f"{server_name}__{tool_name}"
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", original)
    suffix = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]
    return f"mcp__{safe[:49]}__{suffix}"


def _function_schema(server_name: str, item: dict[str, Any]) -> dict[str, Any]:
    tool_name = item.get("name")
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("MCP 工具缺少名称")
    input_schema = item.get("inputSchema")
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}}
    if input_schema.get("type") != "object" or not isinstance(input_schema.get("properties", {}), dict):
        raise ValueError(f"MCP 工具 {tool_name} 的 inputSchema 无效")
    if len(json.dumps(input_schema, ensure_ascii=False, default=str)) > 256_000:
        raise ValueError(f"MCP 工具 {tool_name} 的 inputSchema 超过 256 KB")
    description = item.get("description") or ""
    return {
        "type": "function",
        "function": {
            "name": _tool_alias(server_name, tool_name),
            "description": f"MCP 服务 {server_name}：{description or tool_name}"[:4000],
            "parameters": input_schema,
        },
    }


def _tool_result_text(result: dict[str, Any]) -> str:
    chunks = []
    for part in result.get("content", []):
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            chunks.append(part["text"])
        elif part.get("type") == "image":
            chunks.append("[MCP 返回了一张图片，当前上下文不支持直接嵌入此图片]")
        elif part.get("type") == "resource":
            resource = part.get("resource") or {}
            text = resource.get("text")
            if isinstance(text, str):
                chunks.append(text)
    structured = result.get("structuredContent")
    if structured is not None:
        chunks.append(json.dumps(structured, ensure_ascii=False, default=str))
    text = "\n".join(chunks).strip()
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "\n[结果已截断]"
    return text or "MCP 工具已完成，没有返回文本内容。"


class MCPServerModule(BaseModule):
    """Starts configured MCP servers and exposes their tools to graph nodes."""

    def __init__(self, module_id: str, bus, config_path: str | None = None):
        super().__init__(module_id, bus)
        self.config_path = Path(config_path) if config_path else CONFIG_PATH
        self._servers: dict[str, dict[str, Any]] = {}
        self._statuses: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()

    def initialize(self) -> None:
        with self._lifecycle_lock:
            self._initialize_servers()

    def _initialize_servers(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._statuses.clear()
        try:
            configurations = load_servers(self.config_path)
        except ValueError as exc:
            with self._lock:
                self._statuses["configuration"] = {"status": "error", "error": str(exc)}
                self._initialized = True
            return

        for name, config in configurations.items():
            if not config["enabled"]:
                with self._lock:
                    self._statuses[name] = {"status": "disabled", "tools": 0}
                continue
            with self._lock:
                self._statuses[name] = {"status": "starting", "tools": 0}
            client = None
            try:
                if config["url"]:
                    http_config = dict(config)
                    headers = resolve_values(config["headers"])
                    token_variable = config.get("bearer_token_env_var")
                    if token_variable:
                        token = os.environ.get(token_variable)
                        if not token:
                            raise MCPProtocolError(f"环境变量 {token_variable} 未设置")
                        headers["Authorization"] = f"Bearer {token}"
                    http_config["headers"] = headers
                    client = HTTPMCPClient(http_config)
                else:
                    runtime_config = dict(config)
                    runtime_config["resolved_env"] = resolve_environment(config["env"])
                    client = StdioMCPClient(name, runtime_config)
                initialize_client(client)
                tools = self._load_tools(client)
                with self._lock:
                    self._servers[name] = {"config": config, "client": client, "tools": tools}
                    self._statuses[name] = {"status": "ready", "tools": len(tools)}
            except Exception as exc:
                if client is not None:
                    client.close()
                with self._lock:
                    self._statuses[name] = {"status": "error", "tools": 0, "error": str(exc)[:2000]}
        with self._lock:
            self._initialized = True

    def reload(self) -> list[dict[str, Any]]:
        """Restart configured MCP transports after local settings change."""
        with self._lifecycle_lock:
            with self._lock:
                servers, self._servers = self._servers, {}
                self._initialized = False
                self._statuses.clear()
            for state in servers.values():
                try:
                    state["client"].close()
                except Exception:
                    pass
            self._initialize_servers()
            return self.server_status()

    @staticmethod
    def _load_tools(client: Any) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor = None
        for _ in range(10):
            params = {"cursor": cursor} if cursor else {}
            result = client.request("tools/list", params)
            page = result.get("tools", [])
            if not isinstance(page, list):
                raise MCPProtocolError("MCP tools/list 没有返回工具数组")
            tools.extend(item for item in page if isinstance(item, dict))
            if len(tools) > 512:
                raise MCPProtocolError("MCP 服务暴露的工具超过 512 个")
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
        raise MCPProtocolError("MCP 工具分页超过 10 页")

    def server_status(self) -> list[dict[str, Any]]:
        try:
            configs = load_servers(self.config_path)
        except ValueError as exc:
            return [{"id": "configuration", "name": "配置文件", "status": "error", "error": str(exc), "enabled": False, "tools": 0, "transport": ""}]
        with self._lock:
            return public_server_list(configs, self._statuses)

    def capability_bundle(self) -> dict[str, Any]:
        schemas = []
        route_map: dict[str, tuple[str, str]] = {}
        descriptions = []
        with self._lock:
            active = list(self._servers.items())
        for server_name, state in active:
            for item in state["tools"]:
                try:
                    schema = _function_schema(server_name, item)
                except ValueError:
                    continue
                alias = schema["function"]["name"][len("mcp__"):]
                route_map[alias] = (server_name, item["name"])
                schemas.append(schema)
                descriptions.append(f"- `{server_name}/{item['name']}`: {item.get('description') or item['name']}")
        text = "## MCP 工具\n" + "\n".join(descriptions) if descriptions else ""
        return {
            "text": text,
            "schemas": schemas,
            "handlers": {"mcp": self._make_handler(route_map)},
        }

    def _make_handler(self, route_map: dict[str, tuple[str, str]]):
        def call_tool(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
            route = route_map.get(name)
            if route is None:
                return {"call_id": call_id, "status": "error", "error": "MCP 工具不存在或当前未启用"}
            server_name, tool_name = route
            try:
                with self._lock:
                    state = self._servers.get(server_name)
                    if state is None:
                        raise MCPProtocolError(f"MCP 服务未运行: {server_name}")
                    result = state["client"].request("tools/call", {
                        "name": tool_name,
                        "arguments": arguments,
                    })
                output = _tool_result_text(result)
                if result.get("isError"):
                    return {"call_id": call_id, "status": "error", "error": output}
                return {"call_id": call_id, "status": "success", "output": output}
            except Exception as exc:
                return {"call_id": call_id, "status": "error", "error": str(exc)}
        return call_tool

    def handle_message(self, message: Message) -> None:
        if message.type != MessageType.REQUEST:
            return
        action = message.payload.get("action")
        if action == "list_servers":
            payload = {"servers": self.server_status()}
        elif action == "get_capabilities":
            payload = {"capabilities": self.capability_bundle()}
        elif action == "call_tool":
            name = message.payload.get("name", "")
            arguments = message.payload.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                payload = {"error": "MCP 工具调用格式无效"}
            else:
                result = self.capability_bundle()["handlers"]["mcp"](name, arguments, message.correlation_id or "")
                payload = result
        else:
            return
        self.send(
            target=message.source,
            payload=payload,
            msg_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id,
        )

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                servers, self._servers = self._servers, {}
                self._statuses.clear()
                self._initialized = False
            for state in servers.values():
                try:
                    state["client"].close()
                except Exception:
                    pass

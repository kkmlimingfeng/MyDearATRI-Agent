"""Local MCP server configuration and import helpers."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SERVER_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_SERVERS = 32
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "mcp_servers.json"


def _validate_server(name: Any, value: Any) -> dict[str, Any]:
    if not isinstance(name, str) or not SERVER_NAME.fullmatch(name):
        raise ValueError(f"MCP 服务名称无效: {name!r}")
    if not isinstance(value, dict):
        raise ValueError(f"MCP 服务 {name} 的配置必须是对象")
    enabled = value.get("enabled", not value.get("disabled", False))
    if not isinstance(enabled, bool):
        raise ValueError(f"MCP 服务 {name} 的 enabled 必须是布尔值")

    url = value.get("url")
    command = value.get("command")
    if url:
        if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname:
            raise ValueError(f"MCP 服务 {name} 的 URL 无效")
        transport = "http"
        command = ""
        args = []
    else:
        transport = "stdio"
        if not isinstance(command, str) or not command.strip() or len(command) > 1024:
            raise ValueError(f"MCP 服务 {name} 缺少有效的 command")
        raw_args = value.get("args", [])
        if not isinstance(raw_args, list) or len(raw_args) > 128 or any(not isinstance(arg, str) or len(arg) > 8192 for arg in raw_args):
            raise ValueError(f"MCP 服务 {name} 的 args 必须是字符串数组")
        args = list(raw_args)

    env = value.get("env", {})
    headers = value.get("headers", value.get("http_headers", {}))
    env_headers = value.get("env_http_headers", {})
    bearer_token_env_var = value.get("bearer_token_env_var", "")
    if not isinstance(env, dict) or len(env) > 100 or any(
        not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
        or not isinstance(item, str) or len(item) > 8192
        for key, item in env.items()
    ):
        raise ValueError(f"MCP 服务 {name} 的 env 格式无效")
    if not isinstance(headers, dict) or len(headers) > 100 or any(
        not isinstance(key, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", key)
        or not isinstance(item, str) or "\r" in item or "\n" in item or len(item) > 8192
        for key, item in headers.items()
    ):
        raise ValueError(f"MCP 服务 {name} 的 headers 格式无效")
    if not isinstance(env_headers, dict) or len(env_headers) > 100 or any(
        not isinstance(key, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", key)
        or not isinstance(item, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item)
        for key, item in env_headers.items()
    ):
        raise ValueError(f"MCP 服务 {name} 的 env_http_headers 格式无效")
    headers = {**headers, **{key: f"${{env:{env_name}}}" for key, env_name in env_headers.items()}}
    if not isinstance(bearer_token_env_var, str) or (bearer_token_env_var and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", bearer_token_env_var)):
        raise ValueError(f"MCP 服务 {name} 的 bearer_token_env_var 无效")
    cwd = value.get("cwd", "")
    if not isinstance(cwd, str) or len(cwd) > 4096:
        raise ValueError(f"MCP 服务 {name} 的 cwd 无效")
    return {
        "command": command.strip() if command else "",
        "args": args,
        "env": dict(env),
        "cwd": cwd,
        "url": url or "",
        "headers": dict(headers),
        "bearer_token_env_var": bearer_token_env_var,
        "enabled": enabled,
    }


def normalize_servers(value: Any) -> dict[str, dict[str, Any]]:
    """Accept this app, Claude Desktop/Code, and Codex MCP server maps."""
    if isinstance(value, dict) and "mcpServers" in value:
        raw_servers = value["mcpServers"]
    elif isinstance(value, dict) and "mcp_servers" in value:
        raw_servers = value["mcp_servers"]
    elif isinstance(value, dict) and "servers" in value:
        raw_servers = value["servers"]
    else:
        raw_servers = value
    if not isinstance(raw_servers, dict) or len(raw_servers) > MAX_SERVERS:
        raise ValueError("MCP 配置必须包含不超过 32 个服务")
    return {name: _validate_server(name, item) for name, item in raw_servers.items()}


def parse_imported_config(content: str) -> dict[str, dict[str, Any]]:
    if not isinstance(content, str) or not content.strip() or len(content) > 1_000_000:
        raise ValueError("配置文件为空或超过 1 MB")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        try:
            import tomllib
        except ImportError as exc:
            raise ValueError("当前 Python 不支持 TOML 配置导入") from exc
        try:
            payload = tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError("配置不是有效的 Claude JSON 或 Codex TOML") from exc
    if not isinstance(payload, dict):
        raise ValueError("MCP 配置根节点必须是对象")
    if "mcp_servers" in payload and isinstance(payload.get("mcp_servers"), dict):
        payload = {"mcp_servers": payload["mcp_servers"]}
    elif "mcpServers" not in payload and "servers" not in payload:
        if "mcpServers" in payload.get("mcp", {}):
            payload = payload["mcp"]
    return normalize_servers(payload)


def load_servers(path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("MCP 服务配置无法读取") from exc
    return normalize_servers(payload)


def save_servers(servers: Any, path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    normalized = normalize_servers(servers)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix="mcp-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump({"mcpServers": normalized}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temporary, path)
    return normalized


def merge_imported_servers(content: str, path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    imported = parse_imported_config(content)
    current = load_servers(path)
    merged = {**current, **imported}
    return save_servers(merged, path)


def update_server(name: str, config: dict[str, Any], path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    if not isinstance(name, str) or not SERVER_NAME.fullmatch(name):
        raise ValueError(f"MCP 服务名称无效: {name!r}")
    current = load_servers(path)
    current[name] = config
    return save_servers(current, path)


def remove_server(name: str, path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    if not isinstance(name, str) or not SERVER_NAME.fullmatch(name):
        raise ValueError(f"MCP 服务名称无效: {name!r}")
    current = load_servers(path)
    if name not in current:
        raise ValueError(f"MCP 服务不存在: {name}")
    current.pop(name)
    return save_servers(current, path)


def public_server_list(servers: dict[str, dict[str, Any]], statuses: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    statuses = statuses or {}
    result = []
    for name, config in servers.items():
        status = statuses.get(name, {})
        url = config["url"]
        if url:
            parsed_url = urlsplit(url)
            safe_netloc = parsed_url.hostname or ""
            if parsed_url.port:
                safe_netloc += f":{parsed_url.port}"
            safe_url = urlunsplit((parsed_url.scheme, safe_netloc, parsed_url.path, "", ""))
        else:
            safe_url = ""
        secrets = [*config["env"].values(), *config["headers"].values()]
        bearer_variable = config.get("bearer_token_env_var")
        if bearer_variable and os.environ.get(bearer_variable):
            secrets.append(os.environ[bearer_variable])
        for value in (*config["env"].values(), *config["headers"].values()):
            for variable in re.findall(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}", value):
                if os.environ.get(variable):
                    secrets.append(os.environ[variable])
        def redact(value: Any) -> str:
            text = str(value or "")
            for secret in secrets:
                if len(secret) >= 4:
                    text = text.replace(secret, "[已隐藏]")
            text = re.sub(r"(?i)(--?(?:token|secret|password|api[-_]?key)(?:=|\s+))[^\s]+", r"\1[已隐藏]", text)
            return re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[已隐藏]", text)
        public_args = []
        redact_next = False
        for arg in config["args"]:
            redacted = redact_next or bool(re.search(r"token|secret|password|api[-_]?key", arg, re.I))
            public_args.append("[已配置]" if redacted else redact(arg))
            redact_next = bool(re.search(r"token|secret|password|api[-_]?key", arg, re.I)) and arg.startswith("-")
        result.append({
            "id": name,
            "name": name,
            "transport": "http" if config["url"] else "stdio",
            "command": redact(config["command"] or safe_url),
            "args": public_args,
            "env_keys": sorted(set(config["env"]) | ({config["bearer_token_env_var"]} if config["bearer_token_env_var"] else set())),
            "enabled": config["enabled"],
            "status": status.get("status", "stopped"),
            "tools": status.get("tools", 0),
            "error": redact(status.get("error", "")),
        })
    return result


def resolve_environment(config: dict[str, str], inherited: dict[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if inherited is None else inherited)
    pattern = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}")
    for key, value in config.items():
        environment[key] = pattern.sub(lambda match: environment.get(match.group(1), ""), value)
    return environment


def resolve_values(values: dict[str, str], inherited: dict[str, str] | None = None) -> dict[str, str]:
    environment = os.environ if inherited is None else inherited
    pattern = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}")
    return {
        key: pattern.sub(lambda match: environment.get(match.group(1), ""), value)
        for key, value in values.items()
    }

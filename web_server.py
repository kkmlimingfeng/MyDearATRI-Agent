"""Local API used by the workflow editor and the regular chat page."""

from __future__ import annotations

import json
import base64
import binascii
import os
import re
import threading
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from agent.graph_workflow import GraphWorkflowError, validate_graph_workflow
from agent.graph_executor import GraphExecutor
from agent.workflow_runtime import WorkflowRuntime
from agent.nodes import node_registry
from agent.protocol import TraceEvent
from agent.tool_discovery import TOOL_DISCOVERY_TEXT, discovery_schemas
from agent.workflow import load_workflow
from modules.module_loader import (
    ModuleConfigError,
    build_modules,
    load_module_specs,
    resolve_config_value,
)
from modules.tts.qwen_gguf import TTSRuntimeError, tts


ROOT = Path(__file__).resolve().parent
WORKFLOW_DIR = ROOT / "workflows"
USER_PROFILE_PATH = ROOT / "modules" / "prompt" / "SystemPrompt" / "USER.md"
THEME_BACKGROUND_PATH = ROOT / "data" / "theme" / "background.webp"
PROMPT_DIR = ROOT / "modules" / "prompt" / "SystemPrompt"
MEMORY_DIR = ROOT / "modules" / "mem"
CREDENTIAL_PATH = ROOT / "config" / "model_credentials.json"
API_MODELS_PATH = ROOT / "config" / "api_models.json"
_runtime_lock = threading.RLock()
_runtime_agent = None
_runtime_graph_key = None
_runtime_execution_key = None
_runtime_bindings: Dict[str, str] = {}
_runtime_started = False
_runtime_workflow_id = None
_run_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_workflow_file_lock = threading.Lock()
_model_config_lock = threading.Lock()


def _update_run_draft(job_id: str, content: str) -> None:
    with _jobs_lock:
        job = _run_jobs.get(job_id)
        if job is not None:
            job["draft"] = content


def _graph_workflow_documents() -> list[dict]:
    """Read editable graph workflows directly from workflows/ on each request."""
    documents = []
    if not WORKFLOW_DIR.is_dir():
        return documents
    for path in WORKFLOW_DIR.glob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("workflow_version") != 2:
                continue
            if not isinstance(document.get("id"), str) or not isinstance(document.get("name"), str):
                continue
            if not isinstance(document.get("nodes"), list) or not isinstance(document.get("edges"), list):
                continue
            try:
                validate_graph_workflow(document)
                validation_error = None
            except GraphWorkflowError as exc:
                validation_error = str(exc)
            modified = path.stat().st_mtime
        except (OSError, json.JSONDecodeError):
            continue
        documents.append({
            "id": document["id"],
            "name": document["name"],
            "document": document,
            "validation_error": validation_error,
            "modified": modified,
        })
    documents.sort(key=lambda item: item["modified"], reverse=True)
    return [{key: value for key, value in item.items() if key != "modified"} for item in documents]


def _save_graph_workflow(document: Any, previous_id: Any = None, create_only: bool = False) -> dict:
    graph = validate_graph_workflow(document)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", graph.workflow_id):
        raise GraphWorkflowError("工作流 ID 只能包含英文字母、数字、下划线和连字符")
    if previous_id is not None and (not isinstance(previous_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", previous_id)):
        raise GraphWorkflowError("原工作流 ID 无效")
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    destination = WORKFLOW_DIR / f"{graph.workflow_id}.json"
    source = WORKFLOW_DIR / f"{previous_id}.json" if previous_id and previous_id != graph.workflow_id else None
    with _workflow_file_lock:
        if source and not source.is_file():
            raise GraphWorkflowError(f"原工作流文件不存在: {source.name}")
        if (source or create_only) and destination.exists():
            raise GraphWorkflowError(f"工作流文件已存在: {destination.name}")
        if source and _runtime_started and _runtime_workflow_id == previous_id:
            raise GraphWorkflowError("请先停止运行中的工作流，再重命名文件")
        temporary = WORKFLOW_DIR / f".{graph.workflow_id}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(destination)
            if source:
                try:
                    source.unlink()
                except OSError:
                    destination.unlink(missing_ok=True)
                    raise
        finally:
            temporary.unlink(missing_ok=True)
    return {"id": graph.workflow_id, "name": graph.name, "path": str(destination)}


def _read_user_profile() -> dict:
    try:
        return {"content": USER_PROFILE_PATH.read_text(encoding="utf-8")}
    except OSError as exc:
        raise ValueError(f"读取 USER.md 失败: {exc}") from exc


def _save_user_profile(content: Any) -> dict:
    if not isinstance(content, str):
        raise ValueError("用户信息内容必须是文本")
    if len(content) > 500_000:
        raise ValueError("USER.md 内容不能超过 500 KB")
    temporary = USER_PROFILE_PATH.with_suffix(".md.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(USER_PROFILE_PATH)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"保存 USER.md 失败: {exc}") from exc
    return {"saved": True, "path": str(USER_PROFILE_PATH)}


def _save_theme_background(data_url: Any) -> dict:
    if not isinstance(data_url, str) or not data_url.startswith("data:image/webp;base64,"):
        raise ValueError("背景图片格式无效，请重新上传")
    try:
        image_data = base64.b64decode(data_url.partition(",")[2], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("背景图片数据无效，请重新上传") from exc
    if not image_data or len(image_data) > 15 * 1024 * 1024:
        raise ValueError("背景图片压缩后不能超过 15 MB")
    THEME_BACKGROUND_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = THEME_BACKGROUND_PATH.with_suffix(".webp.tmp")
    try:
        temporary.write_bytes(image_data)
        temporary.replace(THEME_BACKGROUND_PATH)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"背景图片保存失败: {exc}") from exc
    return {"saved": True, "url": f"/api/theme/background?v={THEME_BACKGROUND_PATH.stat().st_mtime_ns}"}


def _load_models() -> dict:
    """Load the declarative model catalog used by both the API and workflows."""
    models_path = ROOT / "config" / "models.json"
    if not models_path.exists():
        return {}
    try:
        payload = json.loads(models_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModuleConfigError(f"加载模型配置失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModuleConfigError("config/models.json 必须是对象")
    payload.update(_read_json_map(API_MODELS_PATH))
    # Local GGUF files are models too. Explicit config entries remain
    # authoritative, while new files in models/ become selectable automatically.
    models_dir = ROOT / "models"
    if models_dir.is_dir():
        for path in sorted(models_dir.glob("*.gguf")):
            is_mmproj = "mmproj" in path.stem.lower()
            stem = path.stem.lower().replace("_", "-")
            stem = re.sub(r"-q([2-8])-k-m$", r"-q\1km", stem)
            model_id = re.sub(r"[^a-z0-9.-]+", "-", stem).strip("-")
            if not model_id:
                continue
            relative_path = "${PROJECT_ROOT}/" + path.relative_to(ROOT).as_posix()
            payload.setdefault(model_id, {
                "class": "modules.llm.gguf_llm.GGUFLLM",
                "model_path": relative_path,
                "label": path.name,
                "projection": is_mmproj,
                "n_gpu_layers": -1,
            })
    return payload


def _read_json_map(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"配置文件格式错误: {path.name}")
    return value


def _write_json_map(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    if path == CREDENTIAL_PATH:
        path.chmod(0o600)


def _safe_markdown(directory: Path, filename: str) -> Path:
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.md", filename):
        raise ValueError("文件名无效")
    path = (directory / filename).resolve()
    if path.parent != directory.resolve() or not path.is_file():
        raise ValueError(f"文件不存在: {filename}")
    return path


def _capability_module(kind: str):
    from bus.event_bus import EventBus
    from modules.skills.skill_module import SkillModule
    from modules.tools.tool_module import ToolModule
    if kind == "skills":
        module = SkillModule("skills", EventBus(), str(ROOT / "config" / "skills.json"))
        module.register_skills_from_directory(str(ROOT / "modules" / "skills"))
    elif kind == "tools":
        module = ToolModule("tools", EventBus(), str(ROOT / "config" / "tools.json"))
        module.register_tools_from_directory(str(ROOT / "modules" / "tools" / "system_tools"))
    else:
        raise ValueError("未知模块类型")
    module._load_enabled_config()
    return module


def _capability_catalog(kind: str) -> dict:
    module = _capability_module(kind)
    if kind == "skills":
        items = [{"id": key, "name": module._get_skill_name(key),
                  "description": module._get_skill_description(key),
                  "enabled": module.is_skill_enabled(key)} for key in module._skills]
        text = module.format_skill_overview()
    else:
        from modules.tools.base_tool import _parse_docstring
        items = [{"id": key, "name": key,
                  "description": _parse_docstring(func)["description"],
                  "enabled": module.is_tool_enabled(key)} for key, func in module._tools.items()]
        text = module.format_tool_descriptions()
    return {"items": items, "text": text}


def _set_capability_items(kind: str, updates: Any) -> dict:
    if not isinstance(updates, dict) or not updates or any(not isinstance(v, bool) for v in updates.values()):
        raise ValueError("请提供要修改的开关")
    module = _capability_module(kind)
    known = module._skills if kind == "skills" else module._tools
    if set(updates) - set(known):
        raise ValueError("包含不存在的技能或工具")
    current = module._enabled_skills if kind == "skills" else module._enabled_tools
    current.update(updates)
    _write_json_map(ROOT / "config" / f"{kind}.json", current)
    with _runtime_lock:
        if _runtime_agent is not None:
            active = _runtime_agent.get_module(kind)
            if active is not None:
                for name, enabled in updates.items():
                    (active.set_skill_enabled if kind == "skills" else active.set_tool_enabled)(name, enabled)
    return _capability_catalog(kind)


def _graph_previews(graph: dict, user_input: str = "") -> dict:
    nodes = {node["id"]: node for node in graph["nodes"]}
    incoming = {(edge["target"], edge.get("targetHandle")): edge["source"] for edge in graph["edges"]}
    previews = {}
    active = set()

    def resolve(node_id: str) -> str:
        if node_id in previews:
            return previews[node_id]
        if node_id in active:
            raise GraphWorkflowError("提示词连接不能成环")
        active.add(node_id)
        node = nodes[node_id]
        kind = node["type"]
        config = node.get("data", {}).get("config", {})
        if kind == "prompt.markdown_file":
            value = _safe_markdown(PROMPT_DIR, config.get("file", "AGENT.md")).read_text(encoding="utf-8")
        elif kind == "prompt.text":
            value = str(config.get("text", ""))
        elif kind == "prompt.join":
            parts = [resolve(incoming[(node_id, port)]) for port in ("prompt_a", "prompt_b", "prompt_c", "prompt_d") if (node_id, port) in incoming]
            value = str(config.get("separator", "\\n\\n")).replace("\\n", "\n").join(filter(None, parts))
        elif kind == "prompt.provider":
            value = ""
        elif kind == "core.chat_input":
            value = user_input or str(config.get("debug_input", ""))
        elif kind == "memory.provider":
            value = (MEMORY_DIR / "memory.md").read_text(encoding="utf-8") if (MEMORY_DIR / "memory.md").is_file() else ""
        elif kind in {"skills.provider", "tools.provider"}:
            value = _capability_catalog(kind.split(".")[0])["text"]
        elif kind == "context.merge":
            parts = [resolve(incoming[(node_id, port)]) for port in ("tools", "skills", "memory", "tool_results", "context_a", "context_b") if (node_id, port) in incoming]
            value = "\n\n".join(filter(None, parts))
        else:
            value = ""
        previews[node_id] = value
        active.remove(node_id)
        return value

    for node in graph["nodes"]:
        if node["type"] in {"prompt.markdown_file", "prompt.text", "prompt.join", "core.chat_input", "memory.provider", "skills.provider", "tools.provider", "context.merge"}:
            resolve(node["id"])
    for edge in graph["edges"]:
        if edge.get("targetHandle") in {"prompt", "context", "message"}:
            source_id = edge["source"]
            if source_id in nodes:
                resolve(source_id)
    runtime_node = next((node for node in graph["nodes"] if node["type"] in {"llm.chat", "agent.react_runtime"}), None)
    if runtime_node:
        message_edge = next((edge for edge in graph["edges"] if edge["target"] == runtime_node["id"] and edge.get("targetHandle") == "message"), None)
        if message_edge:
            previews[message_edge["source"]] = user_input or str(nodes[message_edge["source"]].get("data", {}).get("config", {}).get("debug_input", ""))
    return previews


def _runtime_context_preview(graph: dict, previews: dict) -> str:
    runtime_node = next(node for node in graph["nodes"] if node["type"] in {"llm.chat", "agent.react_runtime"})
    edge = next((edge for edge in graph["edges"] if edge["target"] == runtime_node["id"] and edge.get("targetHandle") == "context"), None)
    return previews.get(edge["source"], "") if edge else ""


def _runtime_prompt_preview(graph: dict, previews: dict) -> str:
    runtime_node = next(node for node in graph["nodes"] if node["type"] in {"llm.chat", "agent.react_runtime"})
    edge = next((edge for edge in graph["edges"] if edge["target"] == runtime_node["id"] and edge.get("targetHandle") == "prompt"), None)
    return previews.get(edge["source"], "") if edge else ""


def _model_kind(config: dict) -> str:
    if config.get("projection"):
        return "mmproj"
    return "gguf" if config.get("model_path") else "api"


def _model_catalog() -> list[dict]:
    """Return safe, editor-facing model metadata without exposing secrets."""
    catalog = []
    credentials = _read_json_map(CREDENTIAL_PATH)
    for model_id, raw in _load_models().items():
        config = dict(raw) if isinstance(raw, dict) else {}
        kind = _model_kind(config)
        resolved_path = resolve_config_value(config.get("model_path", ""), str(ROOT))
        if kind in {"gguf", "mmproj"}:
            ready = bool(resolved_path) and os.path.isfile(resolved_path)
            reason = "" if ready else f"模型文件不存在: {resolved_path}"
            label_suffix = "mmproj" if kind == "mmproj" else "GGUF"
            label = f"{config.get('label', model_id)} · {label_suffix}"
        else:
            ready = True
            reason = "请在 API 模型配置中保存密钥，或设置 OPENAI_API_KEY"
            label = f"{config.get('model_name') or model_id} · API"
        catalog.append({
            "id": model_id,
            "label": label,
            "type": kind,
            "ready": ready,
            "reason": reason,
            "model_name": config.get("model_name", ""),
            "base_url": config.get("base_url", ""),
            "api_style": config.get("api_style", "chat_completions"),
            "supports_images": config.get("supports_images", False),
            "input_token_limit": config.get("input_token_limit", config.get("context_window")),
            "max_output_tokens": config.get("max_tokens"),
            "has_saved_key": bool(credentials.get(f"model:{model_id}")) if kind == "api" else False,
            "configured": bool(credentials.get(f"model:{model_id}") or os.environ.get("OPENAI_API_KEY")) if kind == "api" else False,
        })
    return catalog


def _api_model_catalog() -> list[dict]:
    overrides = _read_json_map(API_MODELS_PATH)
    builtins = _read_json_map(ROOT / "config" / "models.json")
    return [
        {**item, "custom": item["id"] in overrides,
         "builtin": item["id"] in builtins}
        for item in _model_catalog() if item["type"] == "api"
    ]


def _invalidate_active_model(model_id: str) -> None:
    with _runtime_lock:
        if not _runtime_graph_key:
            return
        graph = json.loads(_runtime_graph_key)
        if any(node.get("type") in {"llm.openai_loader", "llm.provider"}
               and node.get("data", {}).get("config", {}).get("model") == model_id
               for node in graph.get("nodes", [])):
            stop_runtime()


def _save_api_model(payload: dict) -> dict:
    model_id = payload.get("id")
    model_name = payload.get("model_name")
    base_url = payload.get("base_url")
    style = payload.get("api_style", "chat_completions")
    api_key = payload.get("api_key", "")
    input_token_limit = payload.get("input_token_limit")
    max_output_tokens = payload.get("max_output_tokens")
    if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}", model_id):
        raise ValueError("配置 ID 只能包含字母、数字、点、下划线、斜杠、冒号和连字符")
    if not isinstance(model_name, str) or not model_name.strip() or len(model_name) > 200:
        raise ValueError("请输入有效的提供商模型 ID")
    if not isinstance(base_url, str) or len(base_url) > 2048:
        raise ValueError("请输入有效的 API 根地址")
    base_url = base_url.strip().rstrip("/")
    if style not in {"chat_completions", "responses"}:
        raise ValueError("不支持的 API 格式")
    endpoint = "/responses" if style == "responses" else "/chat/completions"
    if base_url.endswith(endpoint):
        base_url = base_url[:-len(endpoint)]
    elif base_url.endswith("/responses") or base_url.endswith("/chat/completions"):
        raise ValueError("API 地址末尾与所选请求格式不一致")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API 根地址必须是有效的 http(s) 地址")
    if not isinstance(api_key, str) or len(api_key) > 4096:
        raise ValueError("API Key 无效")
    if input_token_limit not in (None, "") and (isinstance(input_token_limit, bool) or not isinstance(input_token_limit, int) or not 1 <= input_token_limit <= 10_000_000):
        raise ValueError("最大输入 token 必须是正整数")
    if max_output_tokens not in (None, "") and (isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or not 1 <= max_output_tokens <= 10_000_000):
        raise ValueError("最大输出 token 必须是正整数，或留空使用自动模式")
    with _model_config_lock:
        existing = _load_models().get(model_id)
        if existing and _model_kind(existing) != "api":
            raise ValueError("该配置 ID 已被本地模型占用")
        overrides = _read_json_map(API_MODELS_PATH)
        overrides[model_id] = {**(existing or {}),
            "model_name": model_name.strip(), "base_url": base_url,
            "api_style": style, "supports_images": payload.get("supports_images") is True,
            **({"input_token_limit": input_token_limit} if input_token_limit not in (None, "") else {}),
        }
        overrides[model_id].pop("context_window", None)
        overrides[model_id].pop("max_tokens", None)
        if max_output_tokens not in (None, ""):
            overrides[model_id]["max_tokens"] = max_output_tokens
        if input_token_limit in (None, ""):
            overrides[model_id].pop("input_token_limit", None)
        _write_json_map(API_MODELS_PATH, overrides)
        if api_key:
            credentials = _read_json_map(CREDENTIAL_PATH)
            credentials[f"model:{model_id}"] = api_key
            _write_json_map(CREDENTIAL_PATH, credentials)
    _invalidate_active_model(model_id)
    return {"models": _api_model_catalog()}


def _clear_api_model_key(model_id: Any) -> dict:
    model = _load_models().get(model_id) if isinstance(model_id, str) else None
    if not isinstance(model, dict) or _model_kind(model) != "api":
        raise ValueError("API 模型不存在")
    with _model_config_lock:
        credentials = _read_json_map(CREDENTIAL_PATH)
        credentials.pop(f"model:{model_id}", None)
        _write_json_map(CREDENTIAL_PATH, credentials)
    _invalidate_active_model(model_id)
    return {"models": _api_model_catalog()}


def _delete_api_model(model_id: Any) -> dict:
    if not isinstance(model_id, str):
        raise ValueError("缺少配置 ID")
    with _model_config_lock:
        overrides = _read_json_map(API_MODELS_PATH)
        if model_id not in overrides:
            raise ValueError("该模型没有本地自定义配置")
        overrides.pop(model_id)
        _write_json_map(API_MODELS_PATH, overrides)
        credentials = _read_json_map(CREDENTIAL_PATH)
        credentials.pop(f"model:{model_id}", None)
        _write_json_map(CREDENTIAL_PATH, credentials)
    _invalidate_active_model(model_id)
    return {"models": _api_model_catalog()}


def _load_env_file() -> None:
    env_path = ROOT / "config" / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value


def _graph_bindings(graph: dict) -> tuple[dict, dict]:
    node_map = {node["id"]: node for node in graph["nodes"]}
    runtime_nodes = [node for node in graph["nodes"] if node["type"] in {"agent.react_runtime", "llm.chat"}]
    if not runtime_nodes:
        raise GraphWorkflowError("工作流缺少模型对话节点")
    runtime_node = runtime_nodes[0]
    config = runtime_node.get("data", {}).get("config", {})
    bindings = {
        "prompt_name": config.get("prompt_name", "default"),
        "prompt_id": None,
        "llm_id": None,
        # These are optional capabilities. They are enabled only when their
        # provider is reachable from the runtime node in the graph.
        "tools_id": None,
        "skills_id": None,
        "memory_id": None,
        "reviewer_id": "reviewer",
    }
    providers = {}

    incoming = {}
    for edge in graph["edges"]:
        incoming.setdefault(edge.get("target"), []).append(edge)

    def register_provider(handle: str, source: dict) -> None:
        module_id = source.get("data", {}).get("module_id")
        if handle == "prompt" and not module_id:
            module_id = "prompt"
        if not module_id:
            raise GraphWorkflowError(f"{handle} 节点尚未绑定模块 ID")
        binding_key = f"{handle}_id"
        existing = providers.get(handle)
        if existing is not None and bindings.get(binding_key) != module_id:
            raise GraphWorkflowError(f"工作流为 {handle} 连接了多个不同模块")
        bindings[binding_key] = module_id
        providers[handle] = source

    def resolve_capabilities(source: dict, seen: set[str]) -> None:
        if source["id"] in seen:
            return
        seen.add(source["id"])
        capability = source["type"].split(".", 1)[0]
        if capability in {"memory", "skills", "tools"}:
            register_provider(capability, source)
        for upstream in incoming.get(source["id"], []):
            if (upstream.get("data") or {}).get("feedback"):
                continue
            resolve_capabilities(node_map[upstream["source"]], seen)

    for edge in graph["edges"]:
        if edge.get("target") != runtime_node["id"]:
            continue
        source = node_map[edge["source"]]
        handle = edge.get("targetHandle")
        if handle == "context":
            resolve_capabilities(source, set())
        elif handle in {"llm", "prompt", "memory", "skills", "tools"}:
            register_provider(handle, source)
    for node in graph["nodes"]:
        if node["type"] in {"capability.dispatch", "tools.dispatch"}:
            for edge in incoming.get(node["id"], []):
                provider_handle = {
                    "tools": "tools", "tool_executor": "tools",
                    "skills": "skills", "skill_executor": "skills",
                }.get(edge.get("targetHandle"))
                if provider_handle:
                    register_provider(provider_handle, node_map[edge["source"]])
    for required in ("llm", "prompt"):
        if required not in providers:
            raise GraphWorkflowError(f"模型节点缺少 {required} 能力连接")
    return bindings, providers


def _make_agent(graph: dict):
    workflow_file = ROOT / "workflows" / "default_react.json"
    base_workflow = load_workflow(str(workflow_file))
    bindings, providers = _graph_bindings(graph)
    runtime_node = next(node for node in graph["nodes"] if node["type"] in {"agent.react_runtime", "llm.chat"})
    runtime_config = runtime_node.get("data", {}).get("config", {})
    runtime_kwargs = dict(base_workflow.runtime_kwargs)
    for key in ("max_iterations", "max_history_turns"):
        if key in runtime_config:
            runtime_kwargs[key] = runtime_config[key]
    loop_edge = next((edge for edge in graph["edges"] if edge["target"] == runtime_node["id"] and edge.get("targetHandle") == "loop"), None)
    if loop_edge:
        loop_node = next(node for node in graph["nodes"] if node["id"] == loop_edge["source"])
        if loop_node["type"] == "context.merge":
            loop_edge = next((edge for edge in graph["edges"] if edge["target"] == loop_node["id"] and edge.get("targetHandle") == "loop"), None)
            if loop_edge:
                loop_node = next(node for node in graph["nodes"] if node["id"] == loop_edge["source"])
        if loop_node["type"] not in {"control.loop", "react.loop"}:
            raise GraphWorkflowError("循环输入必须连接循环控制节点或上下文联结节点")
        runtime_kwargs["max_iterations"] = max(1, min(500, int(loop_node.get("data", {}).get("config", {}).get("max_iterations", 5))))
    runtime_class = base_workflow.runtime_class if any(node["type"] == "agent.react_runtime" for node in graph["nodes"]) else WorkflowRuntime
    agent = runtime_class(**runtime_kwargs)

    specs = load_module_specs(str(ROOT / "config" / "modules.json"))
    models = _load_models()
    model_node = providers["llm"]
    model_config = model_node.get("data", {}).get("config", {})
    model_key = model_config.get("model", "")
    selected_model = dict(models.get(model_key, {}))
    if not model_key:
        raise GraphWorkflowError(
            f"模型节点没有选择模型，可选模型: {', '.join(models) or '无'}"
        )
    if not selected_model:
        raise GraphWorkflowError(
            f"模型配置不存在: {model_key}。可选模型: {', '.join(models) or '无'}"
        )
    expected_kind = "gguf" if model_node.get("type") == "llm.gguf_loader" else "api" if model_node.get("type") == "llm.openai_loader" else None
    actual_kind = _model_kind(selected_model)
    if expected_kind and expected_kind != actual_kind:
        expected_label = "GGUF" if expected_kind == "gguf" else "API"
        actual_label = "GGUF" if actual_kind == "gguf" else "API"
        raise GraphWorkflowError(
            f"模型节点类型与所选模型不匹配: {model_key} 是 {actual_label} 模型，请选择 {expected_label} 模型"
        )
    if actual_kind == "gguf":
        model_path = resolve_config_value(selected_model.get("model_path", ""), str(ROOT))
        if not model_path or not os.path.isfile(model_path):
            raise GraphWorkflowError(
                f"GGUF 模型文件不存在: {model_path or '(未配置路径)'}。请先放入 models 目录"
            )
        mmproj_key = str(model_config.get("mmproj", "") or "").strip()
        if mmproj_key:
            mmproj_config = models.get(mmproj_key)
            if not isinstance(mmproj_config, dict) or _model_kind(mmproj_config) != "mmproj":
                raise GraphWorkflowError(
                    f"mmproj 模型不存在或类型不正确: {mmproj_key}，请从下拉列表重新选择"
                )
            mmproj_path = resolve_config_value(mmproj_config.get("model_path", ""), str(ROOT))
            if not mmproj_path or not os.path.isfile(mmproj_path):
                raise GraphWorkflowError(f"mmproj 文件不存在: {mmproj_path or '(未配置路径)'}")
            selected_model["mmproj_path"] = mmproj_path
    implementation = model_node.get("data", {}).get("implementation")
    if implementation:
        selected_model["class"] = implementation
    if not selected_model:
        raise GraphWorkflowError(f"模型配置不存在: {model_key}")

    llm_spec = next((item for item in specs if item.get("id") == bindings["llm_id"]), None)
    if llm_spec is None:
        raise GraphWorkflowError(f"配置中没有模型模块: {bindings['llm_id']}")
    selected_class = selected_model.get("class")
    llm_kwargs = {} if selected_class else dict(llm_spec.get("kwargs", {}))
    llm_kwargs.update(selected_model.get("kwargs", {}))
    for key, value in selected_model.items():
        if key not in {"class", "provider", "kwargs", "label", "projection", "supports_images", "context_window", "input_token_limit"}:
            llm_kwargs[key] = value
    model_kwargs = model_config.get("kwargs", {})
    if isinstance(model_kwargs, dict):
        llm_kwargs.update({key: value for key, value in model_kwargs.items() if key != "model"})
    for key, value in model_config.items():
        if key not in {"model", "mmproj", "kwargs", "api_key"} and not (actual_kind == "api" and key == "base_url"):
            llm_kwargs[key] = value
    if actual_kind == "api":
        credentials = _read_json_map(CREDENTIAL_PATH)
        key = credentials.get(f"model:{model_key}") or os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise GraphWorkflowError("API 模型未配置密钥，请在模型配置中保存 API Key")
        llm_kwargs["api_key"] = key
        if not llm_kwargs.get("base_url"):
            llm_kwargs["base_url"] = selected_model.get("base_url") or "https://api.openai.com/v1"
    llm_spec["class"] = selected_class or llm_spec["class"]
    llm_spec["kwargs"] = llm_kwargs

    overrides = {}
    referenced_ids = {
        bindings[key]
        for key in ("prompt_id", "llm_id", "memory_id", "skills_id", "tools_id")
        if key in bindings
    }
    for item in specs:
        if item.get("id") in referenced_ids:
            overrides[item["id"]] = True
    modules, enabled = build_modules(specs, agent.bus, str(ROOT), overrides)
    for module_id, module in modules.items():
        agent.register_module(module, enabled=enabled.get(module_id, True))
    # Register the selected model now, but defer heavyweight GGUF/API
    # initialization until the first model request in the workflow.
    agent.start(defer_module_ids={bindings["llm_id"]})
    agent.display_mode = runtime_config.get("display_mode", "normal")
    agent.tool_approval_callback = lambda call, metadata: False
    return agent, bindings


def _validate_runtime_graph(graph_data: Any):
    graph = validate_graph_workflow(graph_data)
    if _is_direct_chat_graph(graph):
        return graph, {}
    registered_types = {item["type"] for item in node_registry.describe()}
    unsupported = sorted({node["type"] for node in graph.nodes} - registered_types)
    if unsupported:
        raise GraphWorkflowError(
            "当前运行器暂不支持这些节点: " + ", ".join(unsupported)
        )
    if not any(node["type"] in {"agent.react_runtime", "llm.chat"} for node in graph.nodes):
        raise GraphWorkflowError("无模型工作流目前支持：对话输入的 message 直接连接回复输出的 answer")
    bindings, _ = _graph_bindings(graph_data)
    node_map = {node["id"]: node for node in graph.nodes}
    for edge in graph.edges:
        if edge.get("target") != next(
            node["id"] for node in graph.nodes if node["type"] in {"agent.react_runtime", "llm.chat"}
        ):
            continue
        provider = node_map[edge["source"]]
        target_handle = edge.get("targetHandle")
        if target_handle not in {"llm", "prompt", "memory", "skills", "tools"}:
            continue
        provider_module_id = provider.get("data", {}).get("module_id")
        if target_handle == "prompt" and not provider_module_id:
            continue
        if provider_module_id != bindings.get(f"{target_handle}_id"):
            raise GraphWorkflowError("节点模块绑定与接口连接不一致")
    return graph, bindings


def _is_direct_chat_graph(graph) -> bool:
    if len(graph.nodes) != 2 or len(graph.edges) != 1:
        return False
    nodes = {node["id"]: node["type"] for node in graph.nodes}
    edge = graph.edges[0]
    return (
        set(nodes.values()) == {"core.chat_input", "core.chat_output"}
        and nodes.get(edge["source"]) == "core.chat_input"
        and nodes.get(edge["target"]) == "core.chat_output"
        and edge.get("sourceHandle") == "message"
        and edge.get("targetHandle") == "answer"
    )


def _runtime_model_loaded() -> bool:
    if _runtime_agent is None:
        return False
    llm = _runtime_agent.get_module(_runtime_bindings.get("llm_id", "llm"))
    return bool(getattr(llm, "_initialized", False))


def _execution_graph_key(graph_data: dict) -> str:
    ignored_node_fields = {
        "position", "width", "height", "measured", "selected", "dragging",
        "resizing", "outputPreview", "previewUsage", "previewExpanded",
        "executionStatus", "debug_input",
    }
    nodes = []
    for node in graph_data.get("nodes", []):
        data = node.get("data", {})
        normalized_data = {
            key: value
            for key, value in data.items()
            if key not in ignored_node_fields and key != "label"
        }
        if isinstance(normalized_data.get("config"), dict):
            normalized_data["config"] = {
                key: value
                for key, value in normalized_data["config"].items()
                if key != "debug_input"
            }
        nodes.append({
            "id": node.get("id"),
            "type": node.get("type"),
            "data": normalized_data,
        })
    edges = [
        {
            "id": edge.get("id"),
            "source": edge.get("source"),
            "target": edge.get("target"),
            "sourceHandle": edge.get("sourceHandle"),
            "targetHandle": edge.get("targetHandle"),
        }
        for edge in graph_data.get("edges", [])
    ]
    execution_graph = {
        "workflow_version": graph_data.get("workflow_version"),
        "id": graph_data.get("id"),
        "nodes": nodes,
        "edges": edges,
    }
    return json.dumps(execution_graph, ensure_ascii=False, sort_keys=True)


def start_graph(graph_data: Any) -> dict:
    """Activate a workflow and initialize its selected model without a prompt."""
    global _runtime_agent, _runtime_graph_key, _runtime_execution_key, _runtime_bindings, _runtime_started, _runtime_workflow_id
    graph, bindings = _validate_runtime_graph(graph_data)
    serialized_graph = json.dumps(graph_data, ensure_ascii=False, sort_keys=True)
    execution_key = _execution_graph_key(graph_data)
    with _runtime_lock:
        if _is_direct_chat_graph(graph):
            if _runtime_agent is not None:
                _runtime_agent.stop()
            _runtime_agent = None
            _runtime_bindings = {}
            _runtime_graph_key = serialized_graph
            _runtime_execution_key = execution_key
            _runtime_started = True
            _runtime_workflow_id = graph.workflow_id
            return {"running": True, "model_loaded": False, "workflow_id": graph.workflow_id}
        if _runtime_agent is None or _runtime_execution_key != execution_key:
            if _runtime_agent is not None:
                _runtime_agent.stop()
            _runtime_started = False
            _runtime_workflow_id = None
            _runtime_agent, _runtime_bindings = _make_agent(graph_data)
        _runtime_graph_key = serialized_graph
        _runtime_execution_key = execution_key
        try:
            llm = _runtime_agent.get_module(bindings["llm_id"])
            if hasattr(llm, "ensure_initialized"):
                llm.ensure_initialized()
            elif not getattr(llm, "_initialized", False):
                llm.initialize()
            _runtime_started = True
            _runtime_workflow_id = graph.workflow_id
        except Exception:
            _runtime_agent.stop()
            _runtime_agent = None
            _runtime_graph_key = None
            _runtime_execution_key = None
            _runtime_bindings = {}
            _runtime_started = False
            _runtime_workflow_id = None
            raise
        return {
            "running": True,
            "model_loaded": _runtime_model_loaded(),
            "workflow_id": graph.workflow_id,
        }


def stop_runtime() -> dict:
    """Stop the active Agent and release model resources."""
    global _runtime_agent, _runtime_graph_key, _runtime_execution_key, _runtime_bindings, _runtime_started, _runtime_workflow_id
    with _runtime_lock:
        agent = _runtime_agent
        try:
            if agent is not None:
                agent.stop()
        finally:
            _runtime_agent = None
            _runtime_graph_key = None
            _runtime_execution_key = None
            _runtime_bindings = {}
            _runtime_started = False
            _runtime_workflow_id = None
    return {"running": False, "model_loaded": False}


def run_graph(
    graph_data: Any,
    user_input: str,
    mode: str = "normal",
    require_started: bool = False,
    job_id: str | None = None,
    history: Any = None,
    reasoning_effort: Any = None,
) -> dict:
    global _runtime_agent, _runtime_graph_key, _runtime_execution_key, _runtime_bindings, _runtime_started, _runtime_workflow_id
    graph, bindings = _validate_runtime_graph(graph_data)
    if reasoning_effort is not None and (not isinstance(reasoning_effort, str) or reasoning_effort not in {"auto", "minimal", "low", "medium", "high", "xhigh"}):
        raise ValueError("思考强度无效")
    stream_update = (lambda content: _update_run_draft(job_id, content)) if job_id else None
    serialized_graph = json.dumps(graph_data, ensure_ascii=False, sort_keys=True)
    execution_key = _execution_graph_key(graph_data)
    with _runtime_lock:
        if require_started and (
            not _runtime_started or _runtime_execution_key != execution_key
        ):
            raise GraphWorkflowError(
                "Agent 尚未启动，或当前工作流与运行中的配置不同；请先在工作流页启动"
            )
        if _is_direct_chat_graph(graph):
            if _runtime_execution_key != execution_key:
                _runtime_started = False
                _runtime_workflow_id = None
            if _runtime_agent is not None:
                _runtime_agent.stop()
                _runtime_agent = None
                _runtime_bindings = {}
                _runtime_started = False
                _runtime_workflow_id = None
            _runtime_graph_key = serialized_graph
            _runtime_execution_key = execution_key
            input_id = next(node["id"] for node in graph.nodes if node["type"] == "core.chat_input")
            output_id = next(node["id"] for node in graph.nodes if node["type"] == "core.chat_output")
            run_id = uuid.uuid4().hex
            timestamp = datetime.now().astimezone().isoformat()
            events = [
                TraceEvent("workflow_started", run_id, data={"user_input": user_input}, timestamp=timestamp),
                TraceEvent("node_started", run_id, input_id, {"iteration": 1}, timestamp),
                TraceEvent("node_output", run_id, input_id, {"content": user_input}, timestamp),
                TraceEvent("node_completed", run_id, input_id, {"duration_ms": 0, "iteration": 1}, timestamp),
                TraceEvent("node_started", run_id, output_id, {"iteration": 1}, timestamp),
                TraceEvent("node_output", run_id, output_id, {"content": user_input}, timestamp),
                TraceEvent("node_completed", run_id, output_id, {"duration_ms": 0, "iteration": 1}, timestamp),
                TraceEvent("workflow_completed", run_id, output_id, {"answer": user_input}, timestamp),
            ]
            return {"answer": user_input, "run_id": run_id, "events": [event.as_dict() for event in events],
                    "previews": {input_id: user_input, output_id: user_input}, "workflow_id": graph.workflow_id}
        if _runtime_agent is None or _runtime_execution_key != execution_key:
            if _runtime_agent is not None:
                _runtime_agent.stop()
            _runtime_started = False
            _runtime_workflow_id = None
            _runtime_agent, _runtime_bindings = _make_agent(graph_data)
            _runtime_execution_key = execution_key
        _runtime_graph_key = serialized_graph
        if history is not None:
            if not isinstance(history, list):
                raise GraphWorkflowError("对话历史必须是数组")
            _runtime_agent._history = [
                {"role": item["role"], "content": item["content"]}
                for item in history
                if isinstance(item, dict)
                and item.get("role") in {"user", "assistant"}
                and isinstance(item.get("content"), str)
            ][-_runtime_agent.max_history_turns * 2:]
        if not any(node["type"] == "agent.react_runtime" for node in graph.nodes):
            agent = _runtime_agent
            agent.display_mode = mode
            agent.trace_sink.clear()
            run_id = uuid.uuid4().hex
            agent._active_run_id = run_id
            tool_schemas = []
            tools_id = _runtime_bindings.get("tools_id")
            if tools_id and agent._enabled.get(tools_id, False):
                tool_schemas = discovery_schemas()
            def capability_text(module_id: str | None, action: str) -> str:
                if not module_id or not agent._enabled.get(module_id, False):
                    return ""
                response = agent.bus.request(source="agent", target=module_id, payload={"action": action})
                return response.payload.get("text", "")
            services = {
                "agent": agent,
                "read_prompt": lambda filename: _safe_markdown(PROMPT_DIR, filename).read_text(encoding="utf-8"),
                "tools_text": TOOL_DISCOVERY_TEXT if tool_schemas else "",
                "skills_text": capability_text(_runtime_bindings.get("skills_id"), "format_skill_overview"),
                "tool_schemas": tool_schemas,
                "tools_id": tools_id,
                "skills_id": _runtime_bindings.get("skills_id"),
                "stream_update": stream_update,
                "reasoning_effort": reasoning_effort,
            }
            executor = GraphExecutor(graph, agent._modules, services, agent._trace)
            executor.run_id = run_id
            if job_id:
                with _jobs_lock:
                    _run_jobs[job_id]["trace_ready"] = True
            try:
                result = executor.run(user_input)
            except Exception as exc:
                agent._trace("workflow_failed", {"error": str(exc)})
                raise
            agent._add_to_history(user_input, result["answer"])
            result["events"] = [event.as_dict() for event in agent.get_trace_events()]
            return result
        previews = _graph_previews(graph_data, user_input)
        runtime_node = next(node for node in graph_data["nodes"] if node["type"] in {"llm.chat", "agent.react_runtime"})
        prompt_edge = next((edge for edge in graph_data["edges"] if edge["target"] == runtime_node["id"] and edge.get("targetHandle") == "prompt"), None)
        prompt_override = previews.get(prompt_edge["source"]) if prompt_edge else None
        context_override = _runtime_context_preview(graph_data, previews)
        prompt_preview = _runtime_prompt_preview(graph_data, previews)
        for edge in graph_data["edges"]:
            if edge["target"] == runtime_node["id"] and edge.get("targetHandle") == "message":
                previews[runtime_node["id"]] = previews.get(edge["source"], user_input)
                break
        if prompt_edge:
            previews[prompt_edge["source"]] = prompt_preview
        if job_id:
            _runtime_agent.trace_sink.clear()
            with _jobs_lock:
                _run_jobs[job_id]["trace_ready"] = True
        answer = _runtime_agent.run(
            user_input=user_input,
            mode=mode,
            prompt_override=prompt_override,
            context_override=context_override,
            graph_previews=previews,
            stream_update=stream_update,
            reasoning_effort=reasoning_effort if reasoning_effort is not None else runtime_node.get("data", {}).get("config", {}).get("reasoning_effort", "auto"),
            **_runtime_bindings,
        )
        previews[runtime_node["id"]] = answer
        output = next((node["id"] for node in graph_data["nodes"] if node["type"] == "core.chat_output"), None)
        if output:
            previews[output] = answer
        return {
            "answer": answer,
            "run_id": getattr(_runtime_agent, "_active_run_id", ""),
            "events": [event.as_dict() for event in _runtime_agent.get_trace_events()],
            "previews": previews,
            "workflow_id": graph.workflow_id,
        }


def _start_run_job(payload: dict) -> dict:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        if any(not job["done"] for job in _run_jobs.values()):
            raise GraphWorkflowError("已有工作流正在运行，请等待完成")
        _run_jobs.clear()
        _run_jobs[job_id] = {"done": False, "result": None, "error": None, "trace_ready": False, "draft": ""}

    def worker() -> None:
        try:
            result = run_graph(payload.get("workflow"), payload.get("input", "").strip(), payload.get("mode", "transparent"), bool(payload.get("require_started", False)), job_id, payload.get("history"), payload.get("reasoning_effort"))
            with _jobs_lock:
                _run_jobs[job_id].update(done=True, result=result)
        except Exception as exc:
            with _jobs_lock:
                events = [event.as_dict() for event in _runtime_agent.get_trace_events()] if _runtime_agent is not None else []
                _run_jobs[job_id].update(done=True, error=str(exc), events=events)

    threading.Thread(target=worker, daemon=True, name=f"atri-run-{job_id[:8]}").start()
    return {"job_id": job_id}


def _run_job_status(job_id: str) -> dict:
    with _jobs_lock:
        job = _run_jobs.get(job_id)
        if job is None:
            raise ValueError("运行任务不存在")
        snapshot = dict(job)
    if snapshot["done"]:
        return snapshot
    if not snapshot["trace_ready"]:
        return {"done": False, "events": [], "draft": snapshot["draft"]}
    agent = _runtime_agent
    events = [event.as_dict() for event in agent.get_trace_events()] if agent is not None else []
    return {"done": False, "events": events, "draft": snapshot["draft"]}


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "ATRIStudio/0.1"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_tts(self, payload: dict) -> None:
        response_format = payload.get("response_format", "pcm")
        with tts.speech(
            payload.get("text"),
            reference=payload.get("reference", "atri"),
            ref_text=payload.get("ref_text"),
            language=payload.get("language", "Chinese"),
            response_format=response_format,
            model=payload.get("model"),
        ) as response:
            if response_format == "wav":
                body = response.read()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(200)
            self.send_header("Content-Type", "audio/pcm")
            self.send_header("X-Sample-Rate", "24000")
            self.send_header("X-Channels", "1")
            self.send_header("X-Sample-Format", "s16le")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                while chunk := response.read(4096):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        query = parse_qs(parsed_url.query)
        if parsed_url.path == "/api/tts/status":
            self._send(200, tts.status())
            return
        if parsed_url.path == "/api/tts/models":
            self._send(200, tts.models())
            return
        if parsed_url.path == "/api/tts/references":
            self._send(200, {"references": tts.references()})
            return
        if parsed_url.path == "/api/prompts":
            self._send(200, {"files": sorted(path.name for path in PROMPT_DIR.glob("*.md"))})
            return
        if parsed_url.path == "/api/run/status":
            try:
                self._send(200, _run_job_status(query.get("id", [""])[0]))
            except ValueError as exc:
                self._send(404, {"error": str(exc)})
            return
        if parsed_url.path == "/api/model-credentials":
            self._send(200, {"configured": sorted(_read_json_map(CREDENTIAL_PATH))})
            return
        if parsed_url.path in {"/api/skills", "/api/tools"}:
            try:
                self._send(200, _capability_catalog(parsed_url.path.removeprefix("/api/")))
            except (ValueError, OSError) as exc:
                self._send(400, {"error": str(exc)})
            return
        if parsed_url.path == "/api/memories":
            self._send(200, {"files": sorted(path.name for path in MEMORY_DIR.glob("*.md"))})
            return
        if parsed_url.path == "/api/memory":
            try:
                path = _safe_markdown(MEMORY_DIR, query.get("file", [""])[0])
                self._send(200, {"file": path.name, "content": path.read_text(encoding="utf-8")})
            except (ValueError, OSError) as exc:
                self._send(400, {"error": str(exc)})
            return
        if self.path.startswith("/api/theme/background"):
            if not THEME_BACKGROUND_PATH.is_file():
                self._send(404, {"error": "尚未保存背景图片"})
                return
            image_data = THEME_BACKGROUND_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/webp")
            self.send_header("Content-Length", str(len(image_data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(image_data)
            return
        if self.path == "/api/health":
            self._send(200, {"status": "ready", "runtime_loaded": _runtime_model_loaded()})
            return
        if self.path == "/api/status":
            self._send(200, {
                "running": _runtime_started,
                "model_loaded": _runtime_model_loaded(),
                "workflow_id": _runtime_workflow_id,
            })
            return
        if self.path == "/api/nodes":
            self._send(200, {
                "nodes": node_registry.describe(),
                "extension_dir": str(node_registry.extension_dir),
                "extension_errors": node_registry.extension_errors(),
            })
            return
        if self.path == "/api/workflows":
            self._send(200, {"workflows": _graph_workflow_documents()})
            return
        if self.path == "/api/models":
            self._send(200, {"models": _model_catalog()})
            return
        if self.path == "/api/api-models":
            self._send(200, {"models": _api_model_catalog()})
            return
        if self.path == "/api/user-profile":
            try:
                self._send(200, _read_user_profile())
            except ValueError as exc:
                self._send(500, {"error": str(exc)})
            return
        self._send(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path not in {"/api/run", "/api/run/async", "/api/start", "/api/stop", "/api/workflows/save", "/api/user-profile", "/api/theme/background", "/api/preview", "/api/model-credentials", "/api/api-models", "/api/skills", "/api/tools", "/api/memory", "/api/tts/speech", "/api/tts/model"}:
            self._send(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size)) if size else {}
            if self.path == "/api/tts/speech":
                self._send_tts(payload)
                return
            if self.path == "/api/tts/model":
                self._send(200, tts.select_model(payload.get("model")))
                return
            if self.path == "/api/preview":
                if not isinstance(payload.get("workflow"), dict) or not isinstance(payload["workflow"].get("nodes"), list) or not isinstance(payload["workflow"].get("edges"), list):
                    raise ValueError("工作流格式无效")
                self._send(200, {"previews": _graph_previews(payload["workflow"], payload.get("input", ""))})
                return
            if self.path == "/api/run/async":
                if not isinstance(payload.get("input"), str) or not payload["input"].strip():
                    raise ValueError("请输入一条消息")
                self._send(200, _start_run_job(payload))
                return
            if self.path == "/api/model-credentials":
                node_id, key = payload.get("node_id"), payload.get("api_key")
                if not isinstance(node_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", node_id) or not isinstance(key, str) or len(key) > 4096:
                    raise ValueError("模型节点 ID 或密钥无效")
                credentials = _read_json_map(CREDENTIAL_PATH)
                if key:
                    credentials[node_id] = key
                else:
                    credentials.pop(node_id, None)
                _write_json_map(CREDENTIAL_PATH, credentials)
                stop_runtime()
                self._send(200, {"configured": bool(key)})
                return
            if self.path == "/api/api-models":
                action = payload.get("action")
                result = _delete_api_model(payload.get("id")) if action == "delete" else _clear_api_model_key(payload.get("id")) if action == "clear-key" else _save_api_model(payload)
                self._send(200, result)
                return
            if self.path in {"/api/skills", "/api/tools"}:
                self._send(200, _set_capability_items(self.path.removeprefix("/api/"), payload.get("updates")))
                return
            if self.path == "/api/memory":
                path = _safe_markdown(MEMORY_DIR, payload.get("file"))
                content = payload.get("content")
                if not isinstance(content, str) or len(content) > 500_000:
                    raise ValueError("记忆内容必须是小于 500 KB 的文本")
                temporary = path.with_suffix(".md.tmp")
                temporary.write_text(content, encoding="utf-8")
                temporary.replace(path)
                self._send(200, {"saved": True})
                return
            if self.path == "/api/theme/background":
                self._send(200, _save_theme_background(payload.get("image")))
                return
            if self.path == "/api/user-profile":
                self._send(200, _save_user_profile(payload.get("content")))
                return
            if self.path == "/api/workflows/save":
                self._send(200, _save_graph_workflow(payload.get("workflow"), payload.get("previous_id"), payload.get("create_only", False)))
                return
            if self.path == "/api/stop":
                self._send(200, stop_runtime())
                return
            if self.path == "/api/start":
                result = start_graph(payload.get("workflow"))
                self._send(200, result)
                return
            user_input = payload.get("input", "").strip()
            if not user_input:
                self._send(400, {"error": "请输入一条消息"})
                return
            result = run_graph(
                payload.get("workflow"),
                user_input,
                payload.get("mode", "normal"),
                require_started=bool(payload.get("require_started", False)),
                history=payload.get("history"),
                reasoning_effort=payload.get("reasoning_effort"),
            )
            self._send(200, result)
        except (GraphWorkflowError, ModuleConfigError, ValueError, KeyError) as exc:
            self._send(400, {"error": str(exc)})
        except TTSRuntimeError as exc:
            self._send(503, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": f"Agent 运行失败: {exc}"})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[web-api] {format % args}")


def main() -> None:
    _load_env_file()
    port = int(os.environ.get("ATRI_WEB_API_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), ApiHandler)
    print(f"ATRI Studio API listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        tts.close()
        if _runtime_agent is not None:
            _runtime_agent.stop()


if __name__ == "__main__":
    main()

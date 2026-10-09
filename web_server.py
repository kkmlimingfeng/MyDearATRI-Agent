"""Local API used by the workflow editor and the regular chat page."""

from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from agent.graph_workflow import GraphWorkflowError, validate_graph_workflow
from agent.nodes import node_registry
from agent.workflow import load_workflow
from modules.module_loader import (
    ModuleConfigError,
    build_modules,
    load_module_specs,
    resolve_config_value,
)


ROOT = Path(__file__).resolve().parent
WORKFLOW_DIR = ROOT / "workflows"
_runtime_lock = threading.RLock()
_runtime_agent = None
_runtime_graph_key = None
_runtime_bindings: Dict[str, str] = {}
_runtime_started = False


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
            validate_graph_workflow(document)
        except (OSError, json.JSONDecodeError, GraphWorkflowError):
            continue
        documents.append({
            "id": document["id"],
            "name": document["name"],
            "document": document,
            "modified": path.stat().st_mtime,
        })
    documents.sort(key=lambda item: item["modified"], reverse=True)
    return [{key: value for key, value in item.items() if key != "modified"} for item in documents]


def _save_graph_workflow(document: Any) -> dict:
    graph = validate_graph_workflow(document)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", graph.workflow_id):
        raise GraphWorkflowError("工作流 ID 只能包含英文字母、数字、下划线和连字符")
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    destination = WORKFLOW_DIR / f"{graph.workflow_id}.json"
    temporary = WORKFLOW_DIR / f".{graph.workflow_id}.json.tmp"
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return {"id": graph.workflow_id, "name": graph.name, "path": str(destination)}


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


def _model_kind(config: dict) -> str:
    if config.get("projection"):
        return "mmproj"
    return "gguf" if config.get("model_path") else "api"


def _model_catalog() -> list[dict]:
    """Return safe, editor-facing model metadata without exposing secrets."""
    catalog = []
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
            ready = bool(os.environ.get("OPENAI_API_KEY"))
            reason = "" if ready else "未配置 OPENAI_API_KEY（或兼容 API Token）"
            label = f"{model_id} · API"
        catalog.append({
            "id": model_id,
            "label": label,
            "type": kind,
            "ready": ready,
            "reason": reason,
            "model_name": config.get("model_name", ""),
            "base_url": config.get("base_url", ""),
        })
    return catalog


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
    if len(runtime_nodes) != 1:
        raise GraphWorkflowError("当前运行器要求工作流中恰有一个 ReAct Runtime")
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

    def resolve_context(source: dict) -> None:
        if source.get("type") != "context.merge":
            raise GraphWorkflowError("模型对话的上下文输入必须连接到上下文联结节点")
        for context_edge in incoming.get(source["id"], []):
            capability = context_edge.get("targetHandle")
            if capability not in {"memory", "skills", "tools"}:
                continue
            register_provider(capability, node_map[context_edge["source"]])

    for edge in graph["edges"]:
        if edge.get("target") != runtime_node["id"]:
            continue
        source = node_map[edge["source"]]
        handle = edge.get("targetHandle")
        if handle == "context":
            resolve_context(source)
        elif handle in {"llm", "prompt", "memory", "skills", "tools"}:
            register_provider(handle, source)
    for required in ("llm", "prompt"):
        if required not in providers:
            raise GraphWorkflowError(f"ReAct Runtime 缺少 {required} 能力连接")
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
    agent = base_workflow.runtime_class(**runtime_kwargs)

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
        if key not in {"class", "provider", "kwargs", "label", "projection"}:
            llm_kwargs[key] = value
    model_kwargs = model_config.get("kwargs", {})
    if isinstance(model_kwargs, dict):
        llm_kwargs.update({key: value for key, value in model_kwargs.items() if key != "model"})
    for key, value in model_config.items():
        if key not in {"model", "mmproj", "kwargs"}:
            llm_kwargs[key] = value
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
    supported_types = {
        "core.chat_input", "agent.react_runtime", "llm.chat", "llm.provider", "llm.gguf_loader", "llm.openai_loader",
        "prompt.provider", "prompt.markdown_file", "prompt.text", "prompt.join", "context.merge", "memory.provider", "skills.provider",
        "tools.provider", "core.chat_output",
    }
    unsupported = sorted({node["type"] for node in graph.nodes} - supported_types)
    if unsupported:
        raise GraphWorkflowError(
            "当前运行器暂不支持这些节点: " + ", ".join(unsupported)
        )
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


def _runtime_model_loaded() -> bool:
    if _runtime_agent is None:
        return False
    llm = _runtime_agent.get_module(_runtime_bindings.get("llm_id", "llm"))
    return bool(getattr(llm, "_initialized", False))


def start_graph(graph_data: Any) -> dict:
    """Activate a workflow and initialize its selected model without a prompt."""
    global _runtime_agent, _runtime_graph_key, _runtime_bindings, _runtime_started
    graph, bindings = _validate_runtime_graph(graph_data)
    serialized_graph = json.dumps(graph_data, ensure_ascii=False, sort_keys=True)
    with _runtime_lock:
        if _runtime_agent is None or _runtime_graph_key != serialized_graph:
            if _runtime_agent is not None:
                _runtime_agent.stop()
            _runtime_started = False
            _runtime_agent, _runtime_bindings = _make_agent(graph_data)
            _runtime_graph_key = serialized_graph
        try:
            llm = _runtime_agent.get_module(bindings["llm_id"])
            if hasattr(llm, "ensure_initialized"):
                llm.ensure_initialized()
            elif not getattr(llm, "_initialized", False):
                llm.initialize()
            _runtime_started = True
        except Exception:
            _runtime_agent.stop()
            _runtime_agent = None
            _runtime_graph_key = None
            _runtime_bindings = {}
            _runtime_started = False
            raise
        return {
            "running": True,
            "model_loaded": _runtime_model_loaded(),
            "workflow_id": graph.workflow_id,
        }


def stop_runtime() -> dict:
    """Stop the active Agent and release model resources."""
    global _runtime_agent, _runtime_graph_key, _runtime_bindings, _runtime_started
    with _runtime_lock:
        agent = _runtime_agent
        try:
            if agent is not None:
                agent.stop()
        finally:
            _runtime_agent = None
            _runtime_graph_key = None
            _runtime_bindings = {}
            _runtime_started = False
    return {"running": False, "model_loaded": False}


def run_graph(
    graph_data: Any,
    user_input: str,
    mode: str = "normal",
    require_started: bool = False,
) -> dict:
    global _runtime_agent, _runtime_graph_key, _runtime_bindings, _runtime_started
    graph, bindings = _validate_runtime_graph(graph_data)
    serialized_graph = json.dumps(graph_data, ensure_ascii=False, sort_keys=True)
    with _runtime_lock:
        if require_started and (
            not _runtime_started or _runtime_graph_key != serialized_graph
        ):
            raise GraphWorkflowError(
                "Agent 尚未启动，或当前工作流与运行中的配置不同；请先在工作流页启动"
            )
        if _runtime_agent is None or _runtime_graph_key != serialized_graph:
            if _runtime_agent is not None:
                _runtime_agent.stop()
            _runtime_started = False
            _runtime_agent, _runtime_bindings = _make_agent(graph_data)
            _runtime_graph_key = serialized_graph
        answer = _runtime_agent.run(
            user_input=user_input,
            mode=mode,
            **_runtime_bindings,
        )
        return {
            "answer": answer,
            "run_id": getattr(_runtime_agent, "_active_run_id", ""),
            "events": [event.as_dict() for event in _runtime_agent.get_trace_events()],
            "workflow_id": graph.workflow_id,
        }


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

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._send(200, {"status": "ready", "runtime_loaded": _runtime_model_loaded()})
            return
        if self.path == "/api/status":
            self._send(200, {
                "running": _runtime_started,
                "model_loaded": _runtime_model_loaded(),
                "workflow_id": getattr(_runtime_agent, "workflow_id", None),
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
        self._send(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path not in {"/api/run", "/api/start", "/api/stop", "/api/workflows/save"}:
            self._send(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size)) if size else {}
            if self.path == "/api/workflows/save":
                self._send(200, _save_graph_workflow(payload.get("workflow")))
                return
            if self.path == "/api/stop":
                self._send(200, stop_runtime())
                return
            if self.path == "/api/start":
                result = start_graph(payload.get("workflow"))
                if _runtime_agent is not None:
                    _runtime_agent.workflow_id = payload.get("workflow", {}).get("id")
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
            )
            self._send(200, result)
        except (GraphWorkflowError, ModuleConfigError, ValueError, KeyError) as exc:
            self._send(400, {"error": str(exc)})
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
        if _runtime_agent is not None:
            _runtime_agent.stop()


if __name__ == "__main__":
    main()

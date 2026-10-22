"""Command-line runner for workflow v2 graphs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value


def _model_summary(config: dict) -> str:
    if config.get("model_path"):
        return f"GGUF: {config['model_path']}"
    return f"{config.get('model_name', '')} @ {config.get('base_url', '')}"


def _select_model(models: dict) -> str:
    keys = list(models)
    if not keys:
        raise ValueError("没有可用的模型")
    print("\n请选择模型：")
    for index, key in enumerate(keys, 1):
        print(f"  {index}. {key}: {_model_summary(models[key])}")
    while True:
        try:
            selected = int(input("请输入编号: ").strip()) - 1
            if 0 <= selected < len(keys):
                return keys[selected]
        except ValueError:
            pass
        print("无效选择，请重新输入")


def _apply_model_override(workflow: dict, model_id: str, model_kind: str) -> None:
    model_nodes = [
        node for node in workflow.get("nodes", [])
        if node.get("type") in {"llm.gguf_loader", "llm.openai_loader", "llm.provider"}
    ]
    if not model_nodes:
        raise ValueError("所选工作流没有模型加载节点")
    model_node = model_nodes[0]
    model_node["type"] = "llm.gguf_loader" if model_kind == "gguf" else "llm.openai_loader"
    data = model_node.setdefault("data", {})
    data.pop("implementation", None)
    data.setdefault("config", {})["model"] = model_id


def main() -> None:
    parser = argparse.ArgumentParser(description="MyDearATRI-Agent 工作流命令行")
    parser.add_argument(
        "--workflow",
        default=str(ROOT / "workflows" / "atri_companion_graph.json"),
        help="workflow v2 JSON 路径",
    )
    parser.add_argument("--model", "-m", default="", help="覆盖工作流中的模型 ID")
    parser.add_argument("--select-model", action="store_true", help="交互选择一个已配置模型")
    parser.add_argument("--list-models", action="store_true", help="列出可用模型并退出")
    parser.add_argument(
        "--mode", choices=("normal", "transparent"), default="normal",
        help="normal 仅显示回答，transparent 显示工作流轨迹",
    )
    parser.add_argument("--trace-jsonl", default="", help="将每次运行的轨迹追加到 JSONL 文件")
    args = parser.parse_args()

    _load_env_file(ROOT / "config" / ".env")
    import web_server

    models = {
        key: config
        for key, config in web_server._load_models().items()
        if web_server._model_kind(config) in {"gguf", "api"}
    }
    if args.list_models:
        for key, config in models.items():
            print(f"{key}: {_model_summary(config)}")
        return

    try:
        workflow_path = Path(args.workflow).expanduser().resolve()
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict) or workflow.get("workflow_version") != 2:
            raise ValueError("CLI 只运行 workflow_version 2 图工作流")
        selected_model = args.model
        if args.select_model:
            selected_model = _select_model(models)
        if selected_model:
            config = models.get(selected_model)
            if not isinstance(config, dict):
                raise ValueError(f"模型配置不存在: {selected_model}")
            _apply_model_override(workflow, selected_model, web_server._model_kind(config))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"加载工作流失败: {exc}")

    try:
        web_server.start_graph(workflow)
        agent = web_server._runtime_manager.state.agent
        agent.display_mode = args.mode
        agent.tool_approval_callback = _approve_tool_call
        print("工作流已启动，输入 exit 或 quit 退出。")
        while True:
            try:
                user_input = input("你: ").strip()
            except EOFError:
                break
            if user_input.lower() in {"exit", "quit", "q"}:
                break
            if not user_input:
                continue
            result = web_server.run_graph(
                workflow,
                user_input,
                mode=args.mode,
                require_started=True,
            )
            print(f"\nATRI-Agent: {result['answer']}\n")
            if args.trace_jsonl:
                with open(args.trace_jsonl, "a", encoding="utf-8") as trace_file:
                    for event in result.get("events", []):
                        trace_file.write(json.dumps(event, ensure_ascii=False) + "\n")
    except KeyboardInterrupt:
        print("\n正在退出……")
    finally:
        web_server.stop_runtime()


def _approve_tool_call(call, metadata: dict) -> bool:
    risk = metadata.get("risk", "unknown")
    print(f"\n工具 {call.name} 请求执行操作 (risk={risk})")
    print(json.dumps(call.arguments, ensure_ascii=False, indent=2, default=str))
    return input("批准本次调用？[y/N]: ").strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    main()

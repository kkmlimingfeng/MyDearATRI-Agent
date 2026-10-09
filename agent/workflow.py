"""Load and validate declarative Agent workflow files."""
import json
import os
from dataclasses import dataclass
from typing import Any, Dict

from agent.base_agent import BaseAgent
from modules.module_loader import import_class


class WorkflowConfigError(ValueError):
    """Raised when a workflow definition is invalid."""


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    name: str
    runtime_class: type
    runtime_kwargs: Dict[str, Any]
    bindings: Dict[str, str]


def load_workflow(path: str) -> Workflow:
    """Load a workflow JSON file and validate its runtime and module bindings."""
    if not os.path.isfile(path):
        raise WorkflowConfigError(f"工作流文件不存在: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowConfigError(f"加载工作流失败: {exc}") from exc

    if not isinstance(config, dict):
        raise WorkflowConfigError("工作流配置必须是 JSON 对象")
    if config.get("workflow_version") != 1:
        raise WorkflowConfigError("不支持的 workflow_version，当前仅支持版本 1")

    runtime = config.get("runtime")
    if not isinstance(runtime, dict) or not runtime.get("class"):
        raise WorkflowConfigError("工作流必须声明 runtime.class")
    runtime_class = import_class(runtime["class"])
    if not issubclass(runtime_class, BaseAgent):
        raise WorkflowConfigError("工作流 runtime 必须继承 BaseAgent")

    runtime_kwargs = runtime.get("kwargs", {})
    if not isinstance(runtime_kwargs, dict):
        raise WorkflowConfigError("runtime.kwargs 必须是 JSON 对象")

    bindings = config.get("bindings")
    if not isinstance(bindings, dict):
        raise WorkflowConfigError("工作流必须声明 bindings 对象")
    allowed_bindings = {
        "prompt_name", "prompt_id", "llm_id", "tools_id", "skills_id",
        "memory_id", "reviewer_id",
    }
    unknown = set(bindings) - allowed_bindings
    if unknown:
        raise WorkflowConfigError(f"工作流包含未知绑定: {', '.join(sorted(unknown))}")
    if not isinstance(bindings.get("prompt_id"), str) or not bindings["prompt_id"]:
        raise WorkflowConfigError("bindings.prompt_id 必须指定提示词模块 ID")
    if not isinstance(bindings.get("llm_id"), str) or not bindings["llm_id"]:
        raise WorkflowConfigError("bindings.llm_id 必须指定模型模块 ID")
    for key, value in bindings.items():
        if not isinstance(value, str):
            raise WorkflowConfigError(f"bindings.{key} 必须是字符串")

    workflow_id = config.get("id")
    name = config.get("name")
    if not isinstance(workflow_id, str) or not workflow_id:
        raise WorkflowConfigError("工作流必须包含非空 id")
    if not isinstance(name, str) or not name:
        raise WorkflowConfigError("工作流必须包含非空 name")

    return Workflow(
        workflow_id=workflow_id,
        name=name,
        runtime_class=runtime_class,
        runtime_kwargs=runtime_kwargs,
        bindings=bindings,
    )

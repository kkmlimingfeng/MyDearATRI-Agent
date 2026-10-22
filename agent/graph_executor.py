"""Small data-flow executor for composable workflow nodes.

The executor deliberately knows nothing about ReAct, Reflection, or planning.
Those behaviours are assembled by connecting ordinary model, parser, dispatch,
state, branch, and loop nodes in a graph document.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Callable, Dict

from .graph_workflow import GraphWorkflow, GraphWorkflowError
from .nodes import NodeContext, NodeResult, node_registry


class GraphExecutor:
    def __init__(self, graph: GraphWorkflow, modules: Dict[str, Any], services: Dict[str, Any], emit: Callable):
        self.graph = graph
        self.modules = modules
        self.services = services
        self.emit = emit
        self.run_id = uuid.uuid4().hex
        self.values: Dict[tuple[str, str], Any] = {}
        self.previews: Dict[str, Any] = {}
        self.executions = defaultdict(int)
        self.nodes = {node["id"]: node for node in graph.nodes}
        self.descriptions = {item["type"]: item for item in node_registry.describe()}
        self.incoming = defaultdict(list)
        self.outgoing = defaultdict(list)
        for edge in graph.edges:
            self.incoming[edge["target"]].append(edge)
            self.outgoing[(edge["source"], edge.get("sourceHandle"))].append(edge)
        self.feedback_edges = [edge for edge in graph.edges if (edge.get("data") or {}).get("feedback") is True or (
            self.nodes[edge["source"]]["type"] in {"control.loop", "react.loop"} and edge.get("sourceHandle") == "loop"
        )]
        degree = {node_id: 0 for node_id in self.nodes}
        followers = defaultdict(list)
        for edge in graph.edges:
            if edge in self.feedback_edges:
                continue
            degree[edge["target"]] += 1
            followers[edge["source"]].append(edge["target"])
        pending = deque(node_id for node_id, count in degree.items() if count == 0)
        self.order = []
        while pending:
            node_id = pending.popleft()
            self.order.append(node_id)
            for target in followers[node_id]:
                degree[target] -= 1
                if degree[target] == 0:
                    pending.append(target)
        if len(self.order) != len(self.nodes):
            raise GraphWorkflowError("工作流存在未经过循环控制节点的环路")
        self.dynamic = set()
        pending = deque(edge["target"] for edge in self.feedback_edges)
        while pending:
            node_id = pending.popleft()
            if node_id in self.dynamic:
                continue
            self.dynamic.add(node_id)
            pending.extend(followers[node_id])

    def _event(self, event_type: str, node_id: str | None, data: dict | None = None):
        self.emit(event_type, data or {}, node_id)

    def _ready_inputs(self, node_id: str) -> dict | None:
        node_type = self.nodes[node_id]["type"]
        description = self.descriptions.get(node_type)
        inputs = {}
        for edge in self.incoming[node_id]:
            key = (edge["source"], edge.get("sourceHandle"))
            if key in self.values:
                inputs[edge.get("targetHandle")] = self.values[key]
        if description:
            for port in description["inputs"]:
                if port.get("required", True) and port["name"] not in inputs:
                    return None
        return inputs

    @staticmethod
    def _preview(value: Any) -> Any:
        if isinstance(value, dict) and value.get("type") == "audio":
            preview = {key: item for key, item in value.items() if key not in {"data_url", "text", "endpoint"}}
            return json.dumps(preview, ensure_ascii=False, indent=2)
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except Exception:
            return str(value)

    def _execute(self, node_id: str, iteration: int = 1) -> dict:
        node = self.nodes[node_id]
        if (node.get("data") or {}).get("skip_execution") is True:
            self.previews[node_id] = "节点已跳过"
            self._event("node_skipped", node_id, {"iteration": iteration})
            return {}
        node_type = node["type"]
        config = node.get("data", {}).get("config", {})
        inputs = self._ready_inputs(node_id)
        if inputs is None:
            return {}
        self.executions[node_id] += 1
        self._event("node_started", node_id, {"iteration": iteration})
        started = time.perf_counter()
        context = NodeContext(
            run_id=self.run_id,
            node_id=node_id,
            modules=self.modules,
            emit=self._event,
            services={**self.services, "iteration": iteration, "node_module_id": node.get("data", {}).get("module_id")},
        )
        try:
            result = node_registry.create(node_type, config).execute(inputs, context)
            if not isinstance(result, NodeResult):
                raise TypeError(f"节点 {node_id} 必须返回 NodeResult")
            declared = {port["name"] for port in self.descriptions[node_type]["outputs"]}
            unknown = set(result.outputs) - declared
            if unknown:
                raise GraphWorkflowError(f"节点 {node_id} 返回了未声明的输出接口: {', '.join(sorted(unknown))}")
        except Exception as exc:
            self._event("node_failed", node_id, {"error": str(exc), "iteration": iteration, "duration_ms": round((time.perf_counter() - started) * 1000)})
            raise
        elapsed = round((time.perf_counter() - started) * 1000)
        for port, value in result.outputs.items():
            self.values[(node_id, port)] = value
        preview = next(iter(result.outputs.values()), None)
        self.previews[node_id] = self._preview(preview)
        self._event("node_output", node_id, {"content": self.previews[node_id]})
        self._event("node_completed", node_id, {"duration_ms": elapsed, "iteration": iteration})
        return result.outputs

    def run(self, user_input: str) -> dict:
        self._event("workflow_started", None, {"user_input": user_input})
        self.services["user_input"] = user_input
        iteration = 1
        feedback = {}
        terminal_outputs = {}
        while True:
            if iteration > 1:
                self.values = {key: value for key, value in self.values.items() if key[0] not in self.dynamic}
            self.values.update(feedback)
            answer = None
            for node_id in self.order:
                if iteration > 1 and node_id not in self.dynamic:
                    continue
                if iteration > 1:
                    for key in [key for key in self.values if key[0] == node_id]:
                        del self.values[key]
                outputs = self._execute(node_id, iteration)
                if self.nodes[node_id]["type"] == "core.chat_output" and "answer" in outputs:
                    answer = str(outputs["answer"])
                    terminal_outputs = outputs
            if answer is not None:
                self._event("workflow_completed", None, {"answer": answer})
                result = {"answer": answer, "run_id": self.run_id, "previews": self.previews, "workflow_id": self.graph.workflow_id}
                result.update({key: terminal_outputs[key] for key in ("voice", "animation") if key in terminal_outputs})
                return result
            feedback = {}
            for edge in self.feedback_edges:
                source_key = (edge["source"], edge.get("sourceHandle"))
                if source_key in self.values:
                    feedback[source_key] = self.values[source_key]
            if not any(edge.get("sourceHandle") == "loop" and (edge["source"], "loop") in feedback for edge in self.feedback_edges):
                raise GraphWorkflowError("工作流没有产生回复，也没有可继续的循环反馈")
            iteration += 1

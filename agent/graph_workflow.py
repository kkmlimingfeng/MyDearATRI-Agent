"""Version 2 graph workflow document loading and structural validation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List

from agent.nodes import node_registry


class GraphWorkflowError(ValueError):
    """Raised when a graph workflow document is malformed."""


@dataclass(frozen=True)
class GraphWorkflow:
    workflow_id: str
    name: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    metadata: Dict[str, Any]


def validate_graph_workflow(config: Any) -> GraphWorkflow:
    if not isinstance(config, dict):
        raise GraphWorkflowError("工作流必须是 JSON 对象")
    if config.get("workflow_version") != 2:
        raise GraphWorkflowError("图工作流必须使用 workflow_version 2")

    workflow_id = config.get("id")
    name = config.get("name")
    nodes = config.get("nodes")
    edges = config.get("edges")
    if not isinstance(workflow_id, str) or not workflow_id:
        raise GraphWorkflowError("工作流必须包含非空 id")
    if not isinstance(name, str) or not name:
        raise GraphWorkflowError("工作流必须包含非空 name")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise GraphWorkflowError("workflow v2 必须包含 nodes 和 edges 数组")

    node_map: Dict[str, Dict[str, Any]] = {}
    node_descriptions = {
        description["type"]: description
        for description in node_registry.describe()
    }
    for node in nodes:
        if not isinstance(node, dict):
            raise GraphWorkflowError("每个节点必须是 JSON 对象")
        node_id = node.get("id")
        node_type = node.get("type")
        if not isinstance(node_id, str) or not node_id:
            raise GraphWorkflowError("每个节点必须包含非空 id")
        if node_id in node_map:
            raise GraphWorkflowError(f"节点 ID 重复: {node_id}")
        if not isinstance(node_type, str) or not node_type:
            raise GraphWorkflowError(f"节点 {node_id} 缺少 type")
        data = node.get("data", {})
        if not isinstance(data, dict):
            raise GraphWorkflowError(f"节点 {node_id} 的 data 必须是对象")
        config_data = data.get("config", {})
        if not isinstance(config_data, dict):
            raise GraphWorkflowError(f"节点 {node_id} 的 config 必须是对象")
        node_map[node_id] = node

    edge_ids = set()
    incoming_ports = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise GraphWorkflowError("每条连接必须是 JSON 对象")
        edge_id = edge.get("id")
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(edge_id, str) or not edge_id:
            raise GraphWorkflowError("每条连接必须包含非空 id")
        if edge.get("data") is not None and not isinstance(edge["data"], dict):
            raise GraphWorkflowError(f"连接 {edge_id} 的 data 必须是对象")
        if edge_id in edge_ids:
            raise GraphWorkflowError(f"连接 ID 重复: {edge_id}")
        edge_ids.add(edge_id)
        if source not in node_map or target not in node_map:
            raise GraphWorkflowError(f"连接 {edge_id} 引用了不存在的节点")
        if source == target:
            raise GraphWorkflowError(f"连接 {edge_id} 不能连接节点自身")
        source_node = node_map[source]
        target_node = node_map[target]
        source_description = node_descriptions.get(source_node["type"])
        target_description = node_descriptions.get(target_node["type"])
        if not source_description or not target_description:
            continue
        source_port = next(
            (port for port in source_description["outputs"] if port["name"] == edge.get("sourceHandle")),
            None,
        )
        target_port = next(
            (port for port in target_description["inputs"] if port["name"] == edge.get("targetHandle")),
            None,
        )
        if source_port is None or target_port is None:
            raise GraphWorkflowError(f"连接 {edge_id} 引用了不存在的节点接口")
        if source_port["type"] != target_port["type"] and "any" not in {source_port["type"], target_port["type"]}:
            raise GraphWorkflowError(f"连接 {edge_id} 的接口类型不匹配")
        input_key = (target, edge.get("targetHandle"))
        if input_key in incoming_ports:
            raise GraphWorkflowError(f"节点 {target} 的 {edge.get('targetHandle')} 输入只能连接一条线")
        incoming_ports.add(input_key)

    for node_id, node in node_map.items():
        description = node_descriptions.get(node["type"])
        if not description:
            continue
        for port in description["inputs"]:
            if port.get("required", True) and (node_id, port["name"]) not in incoming_ports:
                raise GraphWorkflowError(
                    f"节点 {node_id} 缺少必需输入: {port['name']}"
                )

    metadata = config.get("metadata", {})
    if not isinstance(metadata, dict):
        raise GraphWorkflowError("metadata 必须是 JSON 对象")
    return GraphWorkflow(
        workflow_id=workflow_id,
        name=name,
        nodes=nodes,
        edges=edges,
        metadata=metadata,
    )


def load_graph_workflow(path: str) -> GraphWorkflow:
    if not os.path.isfile(path):
        raise GraphWorkflowError(f"工作流文件不存在: {path}")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            config = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphWorkflowError(f"加载图工作流失败: {exc}") from exc
    return validate_graph_workflow(config)

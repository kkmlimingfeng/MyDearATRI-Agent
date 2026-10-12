# Node extensions

Put one Python file per extension in this directory. The API scans this folder
when `/api/nodes` is requested and again before a node is instantiated, so a
page refresh picks up added or edited node classes without restarting the API.

Each file exports a non-empty `NODES` list. A node class subclasses `BaseNode`,
declares a unique `node_type`, typed `inputs` and `outputs`, and implements
`execute`. `defaults` supplies initial editable values. `config_schema` may
declare `title`, `type`, `default`, and `enum` for editor controls.
Each `PortDefinition` can also set `label_zh` and `label_en` for bilingual
labels in the graph editor. Port names remain stable workflow JSON keys.

```python
from typing import Mapping

from agent.nodes import BaseNode, NodeContext, NodeResult, PortDefinition


class AddPrefixNode(BaseNode):
    node_type = "text.add_prefix"
    title = "添加前缀"
    category = "prompt"
    defaults = {"prefix": "ATRI: "}
    config_schema = {
        "type": "object",
        "properties": {
            "prefix": {"title": "前缀", "type": "string", "default": "ATRI: "}
        },
    }
    inputs = (PortDefinition("text", "text", label_zh="原文", label_en="Text"),)
    outputs = (PortDefinition("text", "text", label_zh="结果", label_en="Result"),)

    def execute(self, inputs: Mapping[str, object], context: NodeContext) -> NodeResult:
        value = str(inputs["text"])
        return NodeResult(outputs={"text": f"{self.config['prefix']}{value}"})


NODES = [AddPrefixNode]
```

`node_type` values must be unique across built-in and extension nodes. If an
extension cannot be loaded, `/api/nodes` returns its path and error under
`extension_errors`; the last successfully loaded version stays active when an
edited file contains an error. The graph executor calls `execute` for registered
extensions using their declared ports. A node runs when its required inputs
are available; only ports returned in `NodeResult.outputs` propagate to the
next nodes. This lets a branch omit an inactive output entirely.

Cycles must pass through a `control.loop` output or an edge with
`"data": {"feedback": true}`. Feedback values become inputs on the next
iteration. A loop node should enforce a finite iteration limit. Completed
nodes emit `node_completed` with `duration_ms`, while failures emit
`node_failed`. Extension nodes do not need to emit those lifecycle events.

`NodeContext.services` contains the current Agent, a Markdown prompt reader,
and capability descriptions. An extension node can output a dictionary of
handlers on a `capability_handlers` port and connect it to the dispatch node's
`handlers` input. A handler registered under a namespace such as `mcp` is
called for a model request named `mcp__capability_name`. It accepts
`(name, arguments, call_id)` and returns a normalized result dictionary.
The same extension can output a `tool_schemas` list directly to
`llm.chat.tool_schemas`. The built-in skills and tools providers expose catalog
bundles for `context.merge`, `schemas` ports for `capability.schema_merge`
(shown as "能力使用方式"), and `executor` ports for `capability.dispatch`. Tool
schemas initially contain only the list and usage lookup functions. Connect
the usage node's `loop` input to loop feedback so a requested tool's full
schema becomes available on the following model turn. Connect its `schemas`
output to both `llm.chat.tool_schemas` and `capability.dispatch.usage`; the
dispatcher checks that a concrete tool was offered before executing it. A
future MCP provider can output
`{"text": ..., "schemas": [...], "handlers": {"mcp": callable}}` on an `mcp`
port; connect it to both `context.merge.mcp` and `capability.dispatch.mcp`, and
its schemas to the usage node. The MCP port is a contract for extensions, not
an MCP client implementation.

For a ReAct graph, route `llm.chat.response` through `control.response_parser`.
The parser emits `answer` for a final response, or both `tool_calls` and
`response` for a capability request. Dispatch results reach `control.loop`,
which returns a `loop` packet through `context.merge.loop` to `llm.chat.loop`.
This packet preserves the model messages and structured tool results; the
context output separately exposes readable text for inspection.

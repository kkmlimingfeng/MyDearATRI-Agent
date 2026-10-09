# Node extensions

Put one Python file per extension in this directory. The API scans this folder
when `/api/nodes` is requested and again before a node is instantiated, so a
page refresh picks up added or edited node classes without restarting the API.

Each file exports a non-empty `NODES` list. A node class subclasses `BaseNode`,
declares a unique `node_type`, typed `inputs` and `outputs`, and implements
`execute`. `defaults` supplies initial editable values. `config_schema` may
declare `title`, `type`, `default`, and `enum` for editor controls.

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
    inputs = (PortDefinition("text", "text"),)
    outputs = (PortDefinition("text", "text"),)

    def execute(self, inputs: Mapping[str, object], context: NodeContext) -> NodeResult:
        value = str(inputs["text"])
        return NodeResult(outputs={"text": f"{self.config['prefix']}{value}"})


NODES = [AddPrefixNode]
```

`node_type` values must be unique across built-in and extension nodes. If an
extension cannot be loaded, `/api/nodes` returns its path and error under
`extension_errors`; the last successfully loaded version stays active when an
edited file contains an error. Extensions are discovered by the editor now;
the current web runner still adapts the supported built-in graph to ReAct, so
custom extension nodes are not executable in a workflow until a general graph
executor dispatches their `execute` method.

# Agent Runtime Architecture

## Product model

The product has two display modes over one execution runtime:

- `normal` shows the final answer and actionable errors.
- `transparent` shows verifiable execution events, model requests and responses,
  tool arguments and results, and timing.

Companion agents and model evaluation workflows are configurations of the same
runtime. Prompt and persona documents define behavior; modules provide
capabilities; workflow JSON chooses implementations and bindings.

## Current execution path

```text
Workflow JSON -> GraphExecutor -> workflow nodes -> WorkflowRuntime -> EventBus
                      ^                |                         |
                      +-- feedback ----+                model / tools / memory
```

The runtime accepts provider-neutral `LLMResponse` values. Tool calls use
`ToolCall`; execution results use `ToolResult`; observable events use
`TraceEvent`. OpenAI-compatible and llama.cpp backends translate provider
responses into this protocol. The legacy text ReAct parser remains available
for models that do not return native tool calls.

## Modules and workflow nodes

Modules are replaceable capability implementations. A module implements the
`BaseModule` lifecycle and is selected in `config/modules.json`. LLM, memory,
skills, tools, prompts, and retrieval implementations live in category
directories under `modules/`.

Nodes describe workflow behavior and typed ports. Implementations inherit
`BaseNode`, return named `NodeResult` outputs, and are registered by stable
`node_type` in `NodeRegistry`. `NodeContext` supplies module lookup, run
identity, trace emission, cancellation state, and runtime services. A node can
bind to a capability by module ID without importing a concrete model or memory
implementation. Initial port contracts live in `agent/nodes/`.

The workflow editor is separate from everyday chat. Applying a workflow selects
it as the active Agent configuration for the chat page. The workbench can also
run the graph and inspect its trace. Graph documents use `workflow_version: 2`;
the existing CLI continues to use v1. The web runner schedules registered node
implementations by their connected inputs. An inactive branch omits its output
port, so downstream nodes on that branch do not run. A connection marked
`data.feedback: true` is delivered on the next iteration. The loop node
enforces the iteration limit. The legacy `agent.react_runtime` still uses
`ReactAgent.run()` for old documents.

The web editor reads graph documents from `workflows/*.json` through the local
API whenever the page loads, and its save action writes back to that directory.
Node descriptions are fetched from the backend registry on page load. Python
extensions in `agent/nodes/extensions/*.py` are discovered on each registry
request and before node creation; adding or editing an extension therefore takes
effect after a page refresh without restarting the API. Extensions export a
`NODES` list of `BaseNode` subclasses. Their labels, typed ports, defaults, and
JSON-schema enum options drive the editor palette and inspector. A malformed
extension is skipped and its error is included in `/api/nodes` diagnostics.

The default visual graph uses explicit data-flow nodes: Markdown and text
prompt nodes feed a prompt join node; memory, skills, and tools feed a context
join node; discovery schemas and skill schemas pass through the "能力使用方式"
node into the model. Tool and skill executor references feed the dispatcher;
they are distinct from catalog text and schemas. A model loader feeds the
model conversation node. The response parser
routes a final answer to chat output or sends calls to the capability
dispatcher while passing the model response to loop control. Dispatch results
reach loop control as structured tool results. Its next-context packet passes
through the context join node before returning to the same model node. The
context join and dispatcher also reserve typed MCP inputs for extensions.
After a tool usage lookup, loop feedback adds that tool's schema to the next
model request. Other tool schemas stay unloaded.
The graph runner emits node start, output, completion, and failure events with
the elapsed time for every completed node.

## Tool call lifecycle

1. The model initially receives only `atri_list_available_tools` and
   `atri_get_tool_usage` definitions, plus any connected skill or MCP schemas.
2. A list call returns enabled tool names and short descriptions. A usage call
   returns one enabled tool's full schema and adds it to the next model request.
3. The model returns a structured call to that tool; it does not execute it.
4. The dispatcher checks that the tool was exposed and invokes the connected
   tool executor or an extension handler.
5. The result is appended as a `role=tool` message with its call ID.
6. The model continues until it returns a normal response or the iteration cap
   is reached.

`ToolExecutor` owns the Agent-to-tool boundary and emits normalized
`ToolResult` values. `ToolModule` validates arguments against the Python
signature, applies per-tool timeouts and retry counts, and returns results over
the event bus. Tool metadata can declare `risk`, `timeout`, `retries`, and
`parallel`. `read` and `network` calls run directly; `write` and `execute` calls
require an approval callback. The CLI asks for approval, while a future web
runtime can pause the workflow and present the same request in its UI. Python
threads cannot safely terminate a running function, so a timeout stops waiting
and reports an error but may leave the underlying call running. Timed-out calls
are not retried; retries should only be enabled for idempotent operations.

`TraceSink` decouples event collection from presentation. The default
`MemoryTraceSink` makes events available through `get_trace_events()` in both
display modes. A `JsonlTraceSink` can be enabled from the CLI with
`--trace-jsonl path`; a callback sink is available for a future web stream.
Transparent mode prints the same normalized events.

## Next architecture steps

1. Persist trace events and run snapshots so CLI and the web workbench share
   the same execution record.
2. Add pause, resume, cancellation, retry, and node-level replay.
3. Add dataset, experiment, evaluator, and result-store modules. Model tests are
   workflows that compose these modules, not a separate agent product.

## Transparency boundary

Transparency means showing inputs, outputs, configuration, tool requests,
results, timings, and state transitions that the runtime can verify. The system
must not depend on hidden model reasoning text as an explanation or control
signal.

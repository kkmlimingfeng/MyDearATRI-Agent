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
Workflow JSON -> ReactAgent -> EventBus -> Prompt / LLM / Tools / Skills / Memory
                                  ^                         |
                                  +--- structured results --+
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
run the supported ReAct graph and inspect its trace. Graph documents use
`workflow_version: 2`; the existing CLI continues to use v1. The current web
runner adapts the ReAct runtime and connected module providers; arbitrary nodes
need execution support before they can run.

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
join node; a model loader feeds the model conversation node; and the answer
ends at the chat output node. The legacy `agent.react_runtime` node remains a
compatibility adapter for older documents. Nodes expose collapsed output
previews, while input nodes can carry a debug value for workbench runs.

## Tool call lifecycle

1. The tool module exposes enabled tools as JSON Schema function definitions.
2. The runtime sends those definitions with the conversation to the LLM.
3. The model returns a structured tool call; it does not execute the tool.
4. The runtime dispatches the call through the configured ToolModule.
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

1. Implement a general graph executor using the node contracts and v2 format,
   preserving v1 workflow support in the CLI.
2. Persist trace events and run snapshots so CLI and the web workbench share
   the same execution record.
3. Add pause, resume, cancellation, retry, and node-level replay.
4. Add dataset, experiment, evaluator, and result-store modules. Model tests are
   workflows that compose these modules, not a separate agent product.

## Transparency boundary

Transparency means showing inputs, outputs, configuration, tool requests,
results, timings, and state transitions that the runtime can verify. The system
must not depend on hidden model reasoning text as an explanation or control
signal.

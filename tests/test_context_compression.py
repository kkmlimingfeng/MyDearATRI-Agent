import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.runtime_manager import RuntimeState
import web_server
from web_server import (
    _context_threshold_reached,
    _history_summary_boundary,
    _summarize_history,
    _validate_context_compression,
    compress_context_now,
    run_graph,
)


class FakeBus:
    def __init__(self):
        self.request_args = None
        self.requests = []

    def request(self, **kwargs):
        self.request_args = kwargs
        self.requests.append(kwargs)
        system = kwargs["payload"]["messages"][0]["content"]
        response = "用户偏好简短回复；项目使用 Qwen。" if "压缩一段持续对话" in system else "stub answer"
        return SimpleNamespace(payload={"response": response, "tool_calls": [], "usage": {}})


class FakeTraceSink:
    def clear(self):
        pass


class ContextCompressionTests(unittest.TestCase):
    def test_boundary_keeps_requested_recent_turns_verbatim(self):
        history = [
            {"role": role, "content": f"turn-{turn}-{role}"}
            for turn in range(4)
            for role in ("user", "assistant")
        ]

        boundary = _history_summary_boundary(history, 2)

        self.assertEqual(boundary, 4)
        self.assertEqual(history[boundary:], history[-4:])
        self.assertEqual(_history_summary_boundary(history[-4:], 2), 0)

    def test_threshold_requires_reported_usage_and_context_window(self):
        settings = _validate_context_compression({
            "enabled": True,
            "keep_recent_turns": 6,
            "threshold_percent": 75,
            "context_window": 1000,
            "previous_input_tokens": 749,
        })

        self.assertFalse(_context_threshold_reached(settings))
        settings["previous_input_tokens"] = 750
        self.assertTrue(_context_threshold_reached(settings))
        settings["context_window"] = None
        self.assertFalse(_context_threshold_reached(settings))

    def test_summary_uses_selected_llm_and_carries_prior_summary(self):
        bus = FakeBus()
        llm = SimpleNamespace(_initialized=True)
        agent = SimpleNamespace(
            _enabled={"selected-llm": True},
            get_module=lambda module_id: llm if module_id == "selected-llm" else None,
            bus=bus,
        )
        old_messages = [{"role": "user", "content": "我喜欢简短回答。"}]

        summary = _summarize_history(agent, "selected-llm", "已有摘要", old_messages)

        self.assertEqual(summary, "用户偏好简短回复；项目使用 Qwen。")
        self.assertEqual(bus.request_args["target"], "selected-llm")
        self.assertEqual(bus.request_args["payload"]["tools"], [])
        self.assertIn("已有摘要", bus.request_args["payload"]["messages"][1]["content"])

    def test_manual_compression_uses_active_runtime_and_keeps_recent_turns(self):
        bus = FakeBus()
        llm = SimpleNamespace(_initialized=True)
        agent = SimpleNamespace(
            _enabled={"selected-llm": True},
            get_module=lambda module_id: llm if module_id == "selected-llm" else None,
            bus=bus,
        )
        graph = SimpleNamespace(nodes=[], edges=[])
        workflow = {"id": "manual-compression-test", "nodes": [], "edges": []}
        history = [
            {"role": role, "content": f"turn-{turn}-{role}"}
            for turn in range(4)
            for role in ("user", "assistant")
        ]

        state = RuntimeState(agent=agent, execution_key="active-execution", bindings={"llm_id": "selected-llm"}, started=True)
        with patch.object(web_server._runtime_manager, "state", state), \
             patch("web_server._validate_runtime_graph", return_value=(graph, {"llm_id": "selected-llm"})), \
             patch("web_server._execution_graph_key", return_value="active-execution"):
            result = compress_context_now(workflow, history, "older summary", 2)

        self.assertEqual(result["compressed_history_messages"], 4)
        self.assertFalse(result["nothing_to_compress"])
        self.assertEqual(result["context_summary"], "用户偏好简短回复；项目使用 Qwen。")
        summary_input = json.loads(bus.request_args["payload"]["messages"][1]["content"])
        self.assertEqual(summary_input["existing_summary"], "older summary")
        self.assertEqual(summary_input["messages_to_absorb"], history[:4])

    def test_run_graph_summarizes_old_turns_and_injects_summary(self):
        bus = FakeBus()
        llm = SimpleNamespace(_initialized=True, ensure_initialized=lambda: None, module_id="selected-llm")

        class FakeAgent:
            def __init__(self):
                self._modules = {"selected-llm": llm}
                self._enabled = {"selected-llm": True}
                self._history = []
                self.max_history_turns = 1
                self.trace_sink = FakeTraceSink()
                self.bus = bus

            def get_module(self, module_id):
                return self._modules.get(module_id)

            def _trace(self, *_args):
                pass

            def _add_to_history(self, *_args):
                pass

            def _parse_embedded_tool_calls(self, _content):
                return []

            def get_trace_events(self):
                return []

        agent = FakeAgent()
        workflow = {
            "workflow_version": 2,
            "id": "compression-test",
            "name": "Compression test",
            "nodes": [
                {"id": "input", "type": "core.chat_input", "data": {"config": {}}},
                {"id": "prompt", "type": "prompt.text", "data": {"config": {"text": "Reply briefly."}}},
                {"id": "provider", "type": "llm.gguf_loader", "data": {"module_id": "selected-llm", "config": {"model": "stub"}}},
                {"id": "chat", "type": "llm.chat", "data": {"config": {}}},
                {"id": "output", "type": "core.chat_output", "data": {"config": {}}},
            ],
            "edges": [
                {"id": "input-chat", "source": "input", "sourceHandle": "message", "target": "chat", "targetHandle": "message"},
                {"id": "prompt-chat", "source": "prompt", "sourceHandle": "prompt", "target": "chat", "targetHandle": "prompt"},
                {"id": "provider-chat", "source": "provider", "sourceHandle": "llm", "target": "chat", "targetHandle": "llm"},
                {"id": "chat-output", "source": "chat", "sourceHandle": "answer", "target": "output", "targetHandle": "answer"},
            ],
        }
        history = [
            {"role": role, "content": f"turn-{turn}-{role}"}
            for turn in range(4)
            for role in ("user", "assistant")
        ]

        with patch.object(web_server._runtime_manager, "state", RuntimeState()), \
                patch("web_server._make_agent", return_value=(agent, {"llm_id": "selected-llm"})):
            result = run_graph(
                workflow,
                "new question",
                history=history,
                history_summary="older summary",
                context_compression={
                    "enabled": True,
                    "keep_recent_turns": 2,
                    "threshold_percent": 75,
                    "context_window": 1000,
                    "previous_input_tokens": 800,
                },
            )

        self.assertEqual(result["context_summary"], "用户偏好简短回复；项目使用 Qwen。")
        self.assertEqual(result["compressed_history_messages"], 4)
        model_messages = bus.requests[-1]["payload"]["messages"]
        self.assertIn("用户偏好简短回复", model_messages[0]["content"])
        self.assertNotIn("turn-0-user", str(model_messages))
        self.assertIn("turn-2-user", str(model_messages))
        self.assertIn("turn-3-assistant", str(model_messages))


if __name__ == "__main__":
    unittest.main()

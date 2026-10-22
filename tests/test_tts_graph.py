import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.graph_executor import GraphExecutor
from agent.graph_workflow import GraphWorkflowError, validate_graph_workflow
from agent.protocol import TraceEvent
from agent.runtime_manager import RuntimeState
import web_server
from web_server import ROOT, _is_tts_graph, _load_models, _model_catalog, _model_kind, _validate_runtime_graph, _voice_tts_model, run_graph
from modules.module_loader import resolve_config_value


class FakeTTS:
    def __init__(self):
        self.selected = None
        self.started = False
        self.closed = False

    def models(self):
        return {"models": [
            {"id": "qwen3-0.6b-q8", "available": True},
            {"id": "qwen3-1.7b-q4", "available": True},
        ]}

    def select_model(self, model):
        self.selected = model

    def ensure_started(self):
        self.started = True

    def close(self):
        self.closed = True


def tts_workflow():
    return {
        "workflow_version": 2,
        "id": "tts-test",
        "name": "TTS test",
        "nodes": [
            {"id": "input", "type": "core.chat_input", "data": {"config": {}}},
            {"id": "tts", "type": "audio.tts_model", "data": {"config": {
                "model": "qwen3-0.6b-q8",
                "language": "Chinese",
                "reference": "new-voice/greeting.wav",
            }}},
            {"id": "output", "type": "core.chat_output", "data": {"config": {}}},
        ],
        "edges": [
            {"id": "input-to-tts", "source": "input", "sourceHandle": "message", "target": "tts", "targetHandle": "text"},
            {"id": "input-to-answer", "source": "input", "sourceHandle": "message", "target": "output", "targetHandle": "answer"},
            {"id": "tts-to-voice", "source": "tts", "sourceHandle": "audio", "target": "output", "targetHandle": "voice"},
        ],
    }


def llm_tts_workflow():
    return {
        "workflow_version": 2,
        "id": "llm-tts-test",
        "name": "LLM and TTS test",
        "nodes": [
            {"id": "input", "type": "core.chat_input", "data": {"config": {}}},
            {"id": "prompt", "type": "prompt.text", "data": {"config": {"text": "回复用户。"}}},
            {"id": "llm-provider", "type": "llm.gguf_loader", "data": {"module_id": "llm", "config": {"model": "test"}}},
            {"id": "llm-chat", "type": "llm.chat", "data": {"config": {}}},
            {"id": "router", "type": "control.response_parser", "data": {"config": {}}},
            {"id": "tts", "type": "audio.tts_model", "data": {"config": {"model": "qwen3-0.6b-q8"}}},
            {"id": "output", "type": "core.chat_output", "data": {"config": {}}},
        ],
        "edges": [
            {"id": "input-message", "source": "input", "sourceHandle": "message", "target": "llm-chat", "targetHandle": "message"},
            {"id": "prompt-input", "source": "prompt", "sourceHandle": "prompt", "target": "llm-chat", "targetHandle": "prompt"},
            {"id": "llm-input", "source": "llm-provider", "sourceHandle": "llm", "target": "llm-chat", "targetHandle": "llm"},
            {"id": "llm-response", "source": "llm-chat", "sourceHandle": "response", "target": "router", "targetHandle": "response"},
            {"id": "answer-output", "source": "router", "sourceHandle": "answer", "target": "output", "targetHandle": "answer"},
            {"id": "answer-tts", "source": "router", "sourceHandle": "answer", "target": "tts", "targetHandle": "text"},
            {"id": "tts-output", "source": "tts", "sourceHandle": "audio", "target": "output", "targetHandle": "voice"},
        ],
    }


class FakeTraceSink:
    def clear(self):
        pass


class FakeBus:
    def request(self, **_kwargs):
        return SimpleNamespace(payload={"response": "早上好。", "tool_calls": [], "usage": {}})


class FakeLLM:
    module_id = "llm"
    _initialized = True


class FakeAgent:
    def __init__(self):
        self._modules = {"llm": FakeLLM()}
        self._enabled = {}
        self._history = []
        self.max_history_turns = 10
        self.trace_sink = FakeTraceSink()
        self.trace_events = []
        self.bus = FakeBus()

    def _trace(self, event_type, data, node_id=None):
        self.trace_events.append(TraceEvent(event_type, "test-run", node_id, data))

    def _parse_embedded_tool_calls(self, _content):
        return []

    def _add_to_history(self, *_args):
        pass

    def get_trace_events(self):
        return self.trace_events


class TTSGraphTests(unittest.TestCase):
    def test_no_model_tts_graph_is_accepted(self):
        graph, bindings = _validate_runtime_graph(tts_workflow())

        self.assertTrue(_is_tts_graph(graph))
        self.assertEqual(bindings, {})

    def test_reply_voice_connection_selects_configured_tts_model(self):
        graph, _ = _validate_runtime_graph(tts_workflow())

        self.assertEqual(_voice_tts_model(graph), "qwen3-0.6b-q8")

    def test_unconnected_tts_node_does_not_preload_a_model(self):
        workflow = tts_workflow()
        workflow["edges"] = [edge for edge in workflow["edges"] if edge["id"] != "tts-to-voice"]
        graph, _ = _validate_runtime_graph(workflow)

        self.assertIsNone(_voice_tts_model(graph))

    def test_skipped_tts_node_is_not_preloaded_or_executed(self):
        workflow = llm_tts_workflow()
        next(node for node in workflow["nodes"] if node["id"] == "tts")["data"]["skip_execution"] = True
        fake_tts = FakeTTS()
        fake_agent = FakeAgent()
        with patch.object(web_server._runtime_manager, "state", RuntimeState()), \
                patch("web_server._make_agent", return_value=(fake_agent, {"llm_id": "llm", "tools_id": None})), \
                patch("web_server.tts", fake_tts):
            result = run_graph(workflow, "你好")

        self.assertEqual(result["answer"], "早上好。")
        self.assertNotIn("voice", result)
        self.assertFalse(fake_tts.started)
        self.assertTrue(fake_tts.closed)
        self.assertTrue(any(event["event_type"] == "node_skipped" and event["node_id"] == "tts" for event in result["events"]))

    def test_main_chat_nodes_cannot_be_skipped(self):
        workflow = llm_tts_workflow()
        next(node for node in workflow["nodes"] if node["id"] == "llm-chat")["data"]["skip_execution"] = True

        with self.assertRaisesRegex(ValueError, "主流程节点，不能跳过"):
            _validate_runtime_graph(workflow)

    def test_skipped_node_cannot_supply_required_downstream_input(self):
        workflow = llm_tts_workflow()
        next(node for node in workflow["nodes"] if node["id"] == "router")["data"]["skip_execution"] = True

        with self.assertRaisesRegex(GraphWorkflowError, "缺少必需输入"):
            validate_graph_workflow(workflow)

    def test_audio_request_reaches_reply_output_without_buffering_wav(self):
        graph, _ = _validate_runtime_graph(tts_workflow())
        result = GraphExecutor(graph, {}, {"tts": FakeTTS()}, lambda *_args: None).run("你好")

        self.assertEqual(result["answer"], "你好")
        self.assertEqual(result["voice"]["type"], "audio")
        self.assertEqual(result["voice"]["text"], "你好")
        self.assertEqual(result["voice"]["endpoint"], "/api/tts/speech")
        self.assertEqual(result["voice"]["reference"], "new-voice/greeting.wav")
        self.assertNotIn("data_url", result["voice"])
        self.assertIsInstance(result["previews"]["tts"], str)
        self.assertNotIn("你好", result["previews"]["tts"])

    def test_llm_workflow_injects_and_starts_tts_service(self):
        fake_tts = FakeTTS()
        fake_agent = FakeAgent()
        with patch.object(web_server._runtime_manager, "state", RuntimeState()), \
                patch("web_server._make_agent", return_value=(fake_agent, {"llm_id": "llm", "tools_id": None})), \
                patch("web_server.tts", fake_tts):
            result = run_graph(llm_tts_workflow(), "你好")

        self.assertEqual(result["answer"], "早上好。")
        self.assertEqual(result["voice"]["text"], "早上好。")
        self.assertEqual(fake_tts.selected, "qwen3-0.6b-q8")
        self.assertTrue(fake_tts.started)

    def test_llm_gguf_discovery_does_not_include_tts_weights(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "config" / "models.json").write_text("{}", encoding="utf-8")
            (root / "models" / "LLM").mkdir(parents=True)
            (root / "models" / "TTS").mkdir(parents=True)
            (root / "models" / "LLM" / "chat-Q4_K_M.gguf").touch()
            (root / "models" / "TTS" / "qwen-talker.gguf").touch()

            with patch("web_server.ROOT", root), patch("web_server.API_MODELS_PATH", root / "config" / "api_models.json"):
                models = _load_models()

        self.assertIn("chat-q4km", models)
        self.assertFalse(any("qwen-talker" in model_id for model_id in models))

    def test_api_model_catalog_inherits_default_context_limit_unless_cleared(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "models.json").write_text(json.dumps({
                "provider-default": {
                    "base_url": "https://api.example.com/v1",
                    "model_name": "provider-default",
                    "input_token_limit": 262144,
                },
                "provider-cleared": {
                    "base_url": "https://api.example.com/v1",
                    "model_name": "provider-cleared",
                    "input_token_limit": 128000,
                },
            }), encoding="utf-8")
            (config_dir / "api_models.json").write_text(json.dumps({
                "provider-default": {"model_name": "provider-default-deployment"},
                "provider-cleared": {"input_token_limit": None},
            }), encoding="utf-8")
            (config_dir / "model_credentials.json").write_text("{}", encoding="utf-8")

            with patch.object(web_server, "ROOT", root), \
                    patch.object(web_server, "API_MODELS_PATH", config_dir / "api_models.json"), \
                    patch.object(web_server, "CREDENTIAL_PATH", config_dir / "model_credentials.json"):
                catalog = {item["id"]: item for item in _model_catalog()}

        self.assertEqual(catalog["provider-default"]["model_name"], "provider-default-deployment")
        self.assertEqual(catalog["provider-default"]["input_token_limit"], 262144)
        self.assertIsNone(catalog["provider-cleared"]["input_token_limit"])

    def test_existing_local_gguf_paths_resolve_from_llm_folder(self):
        models = _load_models()
        local_gguf_paths = [
            Path(resolve_config_value(config["model_path"], str(ROOT)))
            for config in models.values()
            if isinstance(config, dict)
            and _model_kind(config) in {"gguf", "mmproj"}
            and config.get("model_path")
            and os.path.isfile(resolve_config_value(config["model_path"], str(ROOT)))
        ]
        if not local_gguf_paths:
            self.skipTest("No local GGUF weights are installed")

        llm_dir = (ROOT / "models" / "LLM").resolve()
        self.assertTrue(all(path.is_relative_to(llm_dir) for path in local_gguf_paths))


if __name__ == "__main__":
    unittest.main()

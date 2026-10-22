import threading
import unittest
from unittest.mock import patch

import web_server
from agent.runtime_manager import RuntimeManager
from agent.graph_workflow import GraphWorkflowError
from agent.protocol import TraceEvent
from agent.workflow_runtime import WorkflowRuntime
from myagent import _apply_model_override


class RuntimeJobTests(unittest.TestCase):
    def test_run_status_reads_trace_without_waiting_for_runtime_lock(self):
        manager = RuntimeManager()
        agent = WorkflowRuntime()
        agent.trace_sink.emit(TraceEvent("node_started", "active-run", "llm"))
        manager.state.agent = agent
        job_id = "active-job"
        manager.create_run_job(job_id)
        manager.mark_run_trace_ready(job_id)
        lock_held = threading.Event()
        release_lock = threading.Event()
        status_read = threading.Event()
        result = {}

        def hold_runtime_lock():
            with manager.lock:
                lock_held.set()
                release_lock.wait(2)

        def read_status():
            result.update(web_server._run_job_status(job_id))
            status_read.set()

        with patch.object(web_server, "_runtime_manager", manager):
            lock_thread = threading.Thread(target=hold_runtime_lock)
            lock_thread.start()
            self.assertTrue(lock_held.wait(2), "runtime lock was not acquired")
            status_thread = threading.Thread(target=read_status)
            status_thread.start()
            completed_during_run = status_read.wait(0.5)
            release_lock.set()
            status_thread.join(2)
            lock_thread.join(2)

        self.assertTrue(completed_during_run, "trace polling waited for workflow execution to finish")
        self.assertEqual(result["events"], [{
            "event_type": "node_started",
            "run_id": "active-run",
            "node_id": "llm",
            "data": {},
            "timestamp": None,
        }])

    def test_background_job_passes_run_options_by_name(self):
        manager = RuntimeManager()
        completed = threading.Event()
        call = {}

        def fake_run_graph(workflow, user_input, **kwargs):
            call.update(workflow=workflow, user_input=user_input, **kwargs)
            completed.set()
            return {"answer": "done"}

        payload = {
            "workflow": {"id": "job-test"},
            "input": "  hello  ",
            "mode": "transparent",
            "require_started": True,
            "history": [{"role": "user", "content": "prior"}],
            "reasoning_effort": "low",
            "history_summary": "summary",
            "context_compression": {"enabled": False},
            "attachments": [],
        }

        with patch.object(web_server, "_runtime_manager", manager), patch(
            "web_server.run_graph", side_effect=fake_run_graph
        ):
            job = web_server._start_run_job(payload)["job_id"]
            self.assertTrue(completed.wait(2), "background job did not finish")
            result = web_server._run_job_status(job)

        self.assertEqual(call["workflow"], payload["workflow"])
        self.assertEqual(call["user_input"], "hello")
        self.assertEqual(call["mode"], "transparent")
        self.assertTrue(call["require_started"])
        self.assertEqual(call["reasoning_effort"], "low")
        self.assertEqual(result["result"], {"answer": "done"})

    def test_legacy_react_runtime_is_not_runnable(self):
        workflow = {
            "workflow_version": 2,
            "id": "legacy-runtime-test",
            "name": "Legacy runtime test",
            "nodes": [{"id": "runtime", "type": "agent.react_runtime", "data": {}}],
            "edges": [],
        }

        with self.assertRaisesRegex(GraphWorkflowError, "agent.react_runtime"):
            web_server._validate_runtime_graph(workflow)

    def test_cli_model_override_updates_loader_and_removes_stale_implementation(self):
        workflow = {
            "nodes": [{
                "type": "llm.openai_loader",
                "data": {
                    "implementation": "modules.llm.openai_llm.OpenAILLM",
                    "config": {"model": "old-api-model"},
                },
            }]
        }

        _apply_model_override(workflow, "local-gguf", "gguf")

        node = workflow["nodes"][0]
        self.assertEqual(node["type"], "llm.gguf_loader")
        self.assertNotIn("implementation", node["data"])
        self.assertEqual(node["data"]["config"]["model"], "local-gguf")


if __name__ == "__main__":
    unittest.main()

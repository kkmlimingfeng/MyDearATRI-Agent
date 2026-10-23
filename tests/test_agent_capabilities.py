import json
import os
import tempfile
import unittest
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

from agent.nodes.base import NodeContext
from agent.nodes.builtin import LLMChatNode, ToolsProviderNode, _runtime_time_message
from bus.event_bus import EventBus
from modules.sandbox_file_runner import run as run_file_operation
from modules.tools.system_tools.job_manager import BackgroundJobManager
from modules.tools.tool_module import ToolModule
from modules.sandbox_config import WORKSPACE_PERMISSIONS
from modules.sandbox_landlock import landlock_abi
from modules.tools.system_tools import workspace_files
from modules.tools.system_tools import web_access
from modules.tools.system_tools import question_state
from modules.tools.system_tools.ask_user import ask_user_question
from modules.tools.base_tool import system_tool
from bus.base import Message, MessageType
import web_server


class SandboxedFileRunnerTests(unittest.TestCase):
    def test_structured_file_operations_cover_read_write_edit_search_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "nested" / "notes.txt"
            self.assertIn("已创建", run_file_operation({"action": "write", "path": str(path), "content": "hello\nATRI"}))
            self.assertIn("文件已存在", self._error({"action": "write", "path": str(path), "content": "again"}))
            read = json.loads(run_file_operation({
                "action": "read", "path": str(path), "start_line": 2,
                "end_line": 2, "include_version": True,
            }))
            self.assertIn("2: ATRI", read["text"])
            edited = json.loads(run_file_operation({
                "action": "edit", "path": str(path), "old_text": "hello",
                "new_text": "goodbye", "expected_version": read["version"],
                "include_version": True,
            }))
            self.assertIn("已更新", edited["text"])
            self.assertIn("nested/notes.txt:1: goodbye", run_file_operation({"action": "search", "directory": directory, "query": "goodbye"}))
            self.assertIn("file nested/notes.txt", run_file_operation({"action": "list", "directory": directory}))
            self.assertIn("已删除", run_file_operation({
                "action": "delete", "path": str(path),
                "expected_version": edited["version"],
            }))
            self.assertFalse(path.exists())

    @staticmethod
    def _error(payload):
        with unittest.TestCase().assertRaises(ValueError) as caught:
            run_file_operation(payload)
        return str(caught.exception)

    def test_edit_and_delete_require_the_version_read_by_the_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.txt"
            path.write_text("original", encoding="utf-8")
            read = json.loads(run_file_operation({
                "action": "read", "path": str(path), "include_version": True,
            }))
            with self.assertRaisesRegex(ValueError, "先用 read_file"):
                run_file_operation({"action": "edit", "path": str(path), "old_text": "original", "new_text": "changed"})
            path.write_text("changed externally", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "重新读取"):
                run_file_operation({
                    "action": "edit", "path": str(path), "old_text": "changed externally",
                    "new_text": "overwritten", "expected_version": read["version"],
                })
            with self.assertRaisesRegex(ValueError, "重新读取"):
                run_file_operation({"action": "delete", "path": str(path), "expected_version": read["version"]})
            self.assertEqual(path.read_text(encoding="utf-8"), "changed externally")

    def test_edit_rejects_non_regular_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "folder"
            folder.mkdir()
            with self.assertRaisesRegex(ValueError, "普通文件"):
                run_file_operation({
                    "action": "edit", "path": str(folder),
                    "old_text": "x", "new_text": "y", "expected_version": "0" * 64,
                })


class FileObservationTests(unittest.TestCase):
    def test_reads_are_conversation_scoped_and_stale_edits_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            path = workspace / "notes.txt"
            path.write_text("one", encoding="utf-8")
            settings = {"workspace": str(workspace)}

            def local_run(action, **payload):
                try:
                    return run_file_operation({"action": action, **payload})
                except ValueError as exc:
                    return f"文件操作失败：{exc}"

            with patch.object(workspace_files, "load_sandbox_settings", return_value=settings), patch.object(
                workspace_files, "_run", side_effect=local_run
            ):
                workspace_files.read_file(str(path), owner_id="conversation-a")
                denied = workspace_files.edit_file(str(path), "one", "two", owner_id="conversation-b")
                self.assertIn("请先使用 read_file", denied)
                path.write_text("changed outside the tool", encoding="utf-8")
                stale = workspace_files.edit_file(str(path), "changed outside the tool", "overwrite", owner_id="conversation-a")
                self.assertIn("文件自上次读取后已更改", stale)
                self.assertEqual(path.read_text(encoding="utf-8"), "changed outside the tool")

@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("firejail"), "Firejail integration requires Linux")
class SandboxedFileToolIntegrationTests(unittest.TestCase):
    def test_structured_tool_executes_under_workspace_policy(self):
        if landlock_abi() < 3:
            self.skipTest("Landlock ABI 3 is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            settings = {
                "workspace": str(workspace),
                "permission": "workspace",
                "permissions": WORKSPACE_PERMISSIONS,
            }
            with patch.object(workspace_files, "load_sandbox_settings", return_value=settings):
                created = workspace_files._run("write", path="allowed.txt", content="inside")
                outside = workspace_files._run("write", path=str(root / "blocked.txt"), content="outside")
            self.assertIn("已创建", created)
            self.assertTrue((workspace / "allowed.txt").is_file())
            self.assertFalse((root / "blocked.txt").exists(), outside)


class AskUserQuestionTests(unittest.TestCase):
    def test_waiting_question_can_be_answered_and_releases_tool_call(self):
        result = {}
        questions = [
            {"id": "scope", "question": "选哪个？", "options": ["A", "B"], "multi_select": False},
            {"id": "features", "question": "选哪些？", "options": ["x", "y"], "multi_select": True},
        ]
        worker = threading.Thread(
            target=lambda: result.setdefault("answer", ask_user_question(questions, 30))
        )
        worker.start()
        try:
            question = None
            for _ in range(200):
                question = question_state.current_question()
                if question:
                    break
                time.sleep(0.01)
            self.assertIsNotNone(question)
            self.assertEqual(question["questions"], questions)
            answers = [
                {"id": "scope", "selected": ["B"]},
                {"id": "features", "selected": ["x", "y"]},
            ]
            self.assertTrue(question_state.answer_question(question["id"], answers))
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(json.loads(result["answer"]), {"answers": answers})
            self.assertIsNone(question_state.current_question())
        finally:
            question_state.cancel_pending_question()
            worker.join(2)

    def test_http_answer_endpoint_unblocks_question_tool(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.ApiHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        result = {}
        worker = threading.Thread(
            target=lambda: result.setdefault("answer", ask_user_question([
                {"id": "choice", "question": "选一个？", "options": ["完成"], "multi_select": False},
            ], 30))
        )
        worker.start()
        try:
            question = None
            for _ in range(200):
                question = question_state.current_question()
                if question:
                    break
                time.sleep(0.01)
            self.assertIsNotNone(question)
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/run/answer",
                data=json.dumps({
                    "question_id": question["id"],
                    "answers": [{"id": "choice", "selected": ["完成"]}],
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                self.assertEqual(json.loads(response.read()), {"answered": True})
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(json.loads(result["answer"]), {"answers": [{"id": "choice", "selected": ["完成"]}]})
        finally:
            question_state.cancel_pending_question()
            worker.join(2)
            server.shutdown()
            server.server_close()
            server_thread.join(2)

    def test_stopping_releases_a_waiting_question(self):
        result = {}
        worker = threading.Thread(
            target=lambda: result.setdefault("answer", ask_user_question([
                {"id": "continue", "question": "继续吗？", "options": [], "multi_select": False},
            ], timeout_seconds=30))
        )
        worker.start()
        try:
            for _ in range(200):
                question = question_state.current_question()
                if question:
                    break
                time.sleep(0.01)
            self.assertIsNotNone(question)
            question_state.cancel_pending_question()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertIn("运行已停止", result["answer"])
        finally:
            question_state.cancel_pending_question()
            worker.join(2)


class RuntimePromptTests(unittest.TestCase):
    def test_time_context_includes_zone_and_elapsed_time(self):
        previous = (datetime.now().astimezone() - timedelta(seconds=125)).timestamp() * 1000
        state = {"time_zone": "Asia/Shanghai", "previous_message_at": previous}
        message = _runtime_time_message(state)
        self.assertIn("时区：Asia/Shanghai", message)
        self.assertIn("2 分钟", message)
        self.assertIn("当前时间：", message)
        self.assertIn("last_step_at", state)

    def test_tool_provider_exposes_registered_tool_schemas_directly(self):
        agent = SimpleNamespace(bus=Mock())
        agent.bus.request.return_value = SimpleNamespace(payload={"tools": [{
            "type": "function",
            "function": {"name": "read_file", "description": "Read a file", "parameters": {"type": "object"}},
        }]})
        context = NodeContext(run_id="run", node_id="tools", modules={}, emit=lambda *_: None, services={"agent": agent})

        result = ToolsProviderNode().execute({}, context)

        names = {item["function"]["name"] for item in result.outputs["schemas"]}
        self.assertIn("read_file", names)
        self.assertIn("atri_list_available_tools", names)

    def test_registered_tool_schemas_preserve_python_string_annotation_types(self):
        module = ToolModule("tools-test", EventBus())
        module.register_tools_from_directory(str(Path(__file__).resolve().parents[1] / "modules" / "tools" / "system_tools"))
        try:
            schemas = {item["function"]["name"]: item["function"] for item in module.get_tool_schemas()}
        finally:
            module.shutdown()
        self.assertEqual(schemas["web_search"]["parameters"]["properties"]["max_results"]["type"], "integer")
        self.assertEqual(schemas["search_files"]["parameters"]["properties"]["regex"]["type"], "boolean")
        questions = schemas["ask_user_question"]["parameters"]["properties"]["questions"]
        self.assertEqual(questions["type"], "array")
        self.assertEqual(questions["items"]["type"], "object")
        self.assertEqual(questions["items"]["properties"]["options"]["items"]["type"], "string")

    def test_hidden_tool_context_is_not_exposed_and_invalid_params_return_an_error(self):
        module = ToolModule("tools-context-test", EventBus())

        @system_tool(context_arguments=("owner_id",))
        def example_tool(owner_id: str = "") -> str:
            return owner_id

        module.register_tool("example_tool", example_tool)
        try:
            schema = next(item["function"] for item in module.get_tool_schemas() if item["function"]["name"] == "example_tool")
            self.assertNotIn("owner_id", schema["parameters"]["properties"])
            module.send = Mock()
            module._handle_call(Message(
                type=MessageType.REQUEST,
                source="agent",
                target="tools-context-test",
                payload={"action": "call", "tool_name": "example_tool", "params": ["bad"]},
                correlation_id="call-1",
            ))
            self.assertEqual(module.send.call_args.kwargs["payload"], {"error": "工具参数必须是 JSON 对象"})
        finally:
            module.shutdown()


class BackgroundJobTests(unittest.TestCase):
    def setUp(self):
        self.manager = BackgroundJobManager()
        self.addCleanup(self.manager.stop_all)

    def test_job_output_and_status_are_private_to_the_creating_conversation(self):
        job_id = self.manager.start(
            "conversation-a", [sys.executable, "-c", "print('job done')"],
            os.getcwd(), os.environ.copy(), "test job",
        )
        output = self.manager.output("conversation-a", job_id, wait_seconds=5)
        self.assertIn("job done", output)
        self.assertIn("status: completed, exit code 0", output)
        self.assertEqual(self.manager.list("conversation-b"), [])
        self.assertIn("无权访问", self.manager.output("conversation-b", job_id))

    def test_job_can_be_stopped_by_its_owner(self):
        job_id = self.manager.start(
            "conversation-a", [sys.executable, "-c", "import time; time.sleep(30)"],
            os.getcwd(), os.environ.copy(), "long job",
        )
        self.assertIn("无权访问", self.manager.kill("conversation-b", job_id))
        self.assertIn("已停止", self.manager.kill("conversation-a", job_id))
        self.assertEqual(self.manager.list("conversation-a")[0]["status"], "cancelled")

    def test_job_tools_and_command_hide_owner_context(self):
        module = ToolModule("tools-job-schema-test", EventBus())
        module.register_tools_from_directory(str(Path(__file__).resolve().parents[1] / "modules" / "tools" / "system_tools"))
        try:
            schemas = {item["function"]["name"]: item["function"] for item in module.get_tool_schemas()}
            for name in ("exec_sandbox_cmd", "job_list", "job_output", "job_kill"):
                self.assertNotIn("owner_id", schemas[name]["parameters"]["properties"])
        finally:
            module.shutdown()

    def test_llm_chat_appends_runtime_time_on_each_model_step(self):
        bus = Mock()
        bus.request.return_value = SimpleNamespace(payload={"response": "完成", "tool_calls": [], "usage": {}})
        agent = SimpleNamespace(_history=[], max_history_turns=5, bus=bus, _parse_embedded_tool_calls=lambda _content: [])
        context = NodeContext(
            run_id="run", node_id="chat", modules={}, emit=lambda *_: None,
            services={"agent": agent, "runtime_time_context": {"time_zone": "Asia/Shanghai"}},
        )
        LLMChatNode().execute({
            "message": "现在几点？", "prompt": "{{TOOLS}}", "llm": SimpleNamespace(_initialized=True, module_id="llm"),
        }, context)
        messages = bus.request.call_args.kwargs["payload"]["messages"]
        self.assertIn("系统生成的时间上下文", messages[-1]["content"])


class WebToolSafetyTests(unittest.TestCase):
    def test_private_targets_and_nonstandard_ports_are_rejected(self):
        with self.assertRaises(ValueError):
            web_access._validate_public_url("http://127.0.0.1/admin")
        with self.assertRaises(ValueError):
            web_access._validate_public_url("https://example.com:8443/")

    def test_public_hostname_resolves_only_to_public_addresses(self):
        with patch.object(web_access.socket, "getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 443))]):
            self.assertEqual(web_access._validate_public_url("https://example.com").hostname, "example.com")
        with patch.object(web_access.socket, "getaddrinfo", return_value=[(None, None, None, None, ("10.0.0.1", 443))]):
            with self.assertRaises(ValueError):
                web_access._validate_public_url("https://example.com")

    def test_search_rss_extractor_keeps_title_url_and_snippet(self):
        from email.message import Message

        headers = Message()
        headers["Content-Type"] = "application/rss+xml; charset=utf-8"
        results = web_access._parse_search_results(
            b"<rss><channel><item><title>A title</title><link>https://example.org/</link><description>A useful snippet</description></item></channel></rss>",
            headers,
        )
        self.assertEqual(results[0], {"title": "A title", "url": "https://example.org/", "snippet": "A useful snippet"})

    def test_sandbox_file_tool_approval_uses_path_scope_and_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            settings = {
                "workspace": str(workspace),
                "permissions": {
                    "workspace": {"read": True, "write": True, "edit": True, "delete": True},
                    "outside": {"read": True, "write": False, "edit": False, "delete": False},
                },
            }
            with patch.object(web_server, "load_sandbox_settings", return_value=settings):
                inside = SimpleNamespace(name="write_file", arguments={"path": "new.txt"})
                outside = SimpleNamespace(name="write_file", arguments={"path": str(root / "outside.txt")})
                metadata = {"risk": "sandbox", "sandbox_action": "write", "sandbox_path_arg": "path"}
                self.assertTrue(web_server._approve_workflow_tool(inside, metadata))
                self.assertFalse(web_server._approve_workflow_tool(outside, metadata))


if __name__ == "__main__":
    unittest.main()

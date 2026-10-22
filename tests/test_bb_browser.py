import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules.tools.system_tools.bb_browser import _parse_command, bb_browser
from modules.sandbox_process import sandbox_argv_process_options
from modules.tools.tool_module import ToolModule
from bus.event_bus import EventBus
import web_server


class BbBrowserCommandTests(unittest.TestCase):
    def test_parser_accepts_cli_prefix_quotes_and_eval_expressions(self):
        self.assertEqual(
            _parse_command('bb-browser eval "document.title || document.URL"'),
            ["eval", "document.title || document.URL"],
        )

    def test_parser_rejects_shell_composition(self):
        with self.assertRaisesRegex(ValueError, "shell 管道"):
            _parse_command("site list && rm -rf /tmp/example")

    def test_tool_passes_each_cli_argument_without_shell_interpretation(self):
        settings = {
            "workspace": str(Path.cwd()),
            "permission": "workspace",
            "permissions": {"outside": {"read": True}},
        }
        completed = SimpleNamespace(stdout="done\n", stderr="", returncode=0)
        with patch("modules.tools.system_tools.bb_browser._browser_cli", return_value=(Path("/pkg/cli.js"), "0.14.2")), \
                patch("pathlib.Path.is_file", return_value=True), \
                patch("modules.tools.system_tools.bb_browser.shutil.which", return_value="/usr/bin/node"), \
                patch("modules.tools.system_tools.bb_browser.load_sandbox_settings", return_value=settings), \
                patch("modules.tools.system_tools.bb_browser._browser_home", return_value=Path("/workspace/.cache/bb-browser")), \
                patch("modules.tools.system_tools.bb_browser.sandbox_argv_process_options", return_value=([], {}, Path.cwd())) as sandbox, \
                patch("modules.tools.system_tools.bb_browser.subprocess.run", return_value=completed):
            result = bb_browser('site search "AI agents" --query "curl && wget"', timeout=200)

        self.assertIn("done", result)
        argv = sandbox.call_args.args[0]
        self.assertEqual(argv[2:], ["site", "search", "AI agents", "--query", "curl && wget"])
        self.assertEqual(sandbox.call_args.kwargs["runtime_arg_count"], 2)
        self.assertFalse(sandbox.call_args.kwargs["enforce_landlock"])
        self.assertEqual(sandbox.call_args.kwargs["extra_env"]["BB_BROWSER_HOME"], "/workspace/.cache/bb-browser")

    def test_direct_browser_tool_requires_command_approval(self):
        call = SimpleNamespace(name="bb_browser")
        with patch("web_server.load_sandbox_settings", return_value={"allow_command_execution": True}):
            self.assertTrue(web_server._approve_workflow_tool(call, {"risk": "execute"}))

    def test_tool_schema_exposes_one_command_string_and_numeric_timeout(self):
        module = ToolModule("test", EventBus())
        module.register_tool("bb_browser", bb_browser)
        try:
            schema = module.get_tool_schemas()[0]["function"]
        finally:
            module.shutdown()

        self.assertEqual(schema["name"], "bb_browser")
        self.assertEqual(schema["parameters"]["properties"]["command"]["type"], "string")
        self.assertEqual(schema["parameters"]["properties"]["timeout"]["type"], "integer")
        self.assertEqual(schema["parameters"]["required"], ["command"])

    def test_argv_runner_does_not_add_user_arguments_to_runtime_allowlist(self):
        base_args = ["env", "container=lxc", "firejail", "python", "runner.py", "runtime", "settings"]
        with patch(
            "modules.sandbox_process.sandbox_process_options",
            return_value=(base_args.copy(), {"PATH": "/usr/bin"}, Path("/workspace")),
        ) as build:
            args, _environment, _workspace = sandbox_argv_process_options(
                ["/usr/bin/node", "/workspace/cli.js", "fetch", "/tmp/secret.json"],
                runtime_arg_count=2,
            )

        self.assertEqual(build.call_args.args[0], "/usr/bin/node /workspace/cli.js")
        self.assertEqual(args[-3], str(Path(__file__).resolve().parents[1] / "modules" / "sandbox_argv_runner.py"))
        self.assertEqual(json.loads(args[-2]), ["/usr/bin/node", "/workspace/cli.js", "fetch", "/tmp/secret.json"])

    def test_custom_partial_permissions_keep_landlock_enabled(self):
        from modules.tools.system_tools.bb_browser import _requires_landlock

        settings = {
            "permission": "custom",
            "permissions": {
                "workspace": {"read": True, "write": True, "edit": False, "delete": False},
                "outside": {"read": True, "write": False, "edit": False, "delete": False},
            },
        }
        self.assertTrue(_requires_landlock(settings))

    def test_sandbox_rejects_skipping_landlock_for_partial_custom_permissions(self):
        from modules.sandbox_process import sandbox_process_options

        settings = {
            "workspace": str(Path.cwd()),
            "permission": "custom",
            "permissions": {
                "workspace": {"read": True, "write": True, "edit": False, "delete": False},
                "outside": {"read": True, "write": False, "edit": False, "delete": False},
            },
        }
        with self.assertRaisesRegex(ValueError, "不能跳过 Landlock"):
            sandbox_process_options("node --version", enforce_landlock=False, settings=settings, firejail_path="/usr/bin/firejail")


if __name__ == "__main__":
    unittest.main()

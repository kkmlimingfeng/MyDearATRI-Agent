import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from bus.event_bus import EventBus
from modules.mcp.client import StdioMCPClient, initialize_client
from modules.mcp.configuration import normalize_servers, parse_imported_config, public_server_list
from modules.mcp.server_manager import _function_schema, _tool_result_text
from modules.skills.skill_installer import install_skill_archive
from modules.skills.skill_module import SkillModule


class SkillPackageTests(unittest.TestCase):
    def _archive(self, entries):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return buffer.getvalue()

    def test_imports_standard_skill_and_reads_reference_resource(self):
        content = self._archive({
            "sample-skill/SKILL.md": "---\nname: sample-skill\ndescription: >-\n  Helps with a task\n  across multiple steps.\n---\nUse the guide when needed.\n",
            "sample-skill/references/guide.md": "Read this reference.\n",
        })
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "modules" / "skills"
            installed = install_skill_archive(content, root)
            module = SkillModule("skills", EventBus())
            module.register_skills_from_directory(str(root))

            self.assertEqual(installed[0]["id"], "sample-skill")
            self.assertEqual(module.get_skill("sample-skill")["frontmatter"]["description"], "Helps with a task across multiple steps.")
            self.assertEqual(module.get_skill_resource("sample-skill", "references/guide.md"), "Read this reference.\n")

    def test_rejects_zip_path_traversal(self):
        content = self._archive({
            "safe/SKILL.md": "---\nname: safe\ndescription: safe\n---\n",
            "../escape.txt": "outside",
        })
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            with self.assertRaisesRegex(ValueError, "不安全"):
                install_skill_archive(content, root)
            self.assertFalse((Path(temporary) / "escape.txt").exists())


class MCPConfigurationTests(unittest.TestCase):
    def test_imports_claude_json_and_codex_toml(self):
        claude = parse_imported_config(json.dumps({
            "mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "mcp-server-filesystem"], "env": {"TOKEN": "${TOKEN}"}}},
        }))
        codex = parse_imported_config('''
[mcp_servers.fetch]
command = "uvx"
args = ["mcp-server-fetch"]

[mcp_servers.remote]
url = "https://example.test/mcp"
bearer_token_env_var = "REMOTE_TOKEN"
''')

        self.assertEqual(claude["filesystem"]["command"], "npx")
        self.assertEqual(codex["fetch"]["args"], ["mcp-server-fetch"])
        self.assertEqual(codex["remote"]["bearer_token_env_var"], "REMOTE_TOKEN")

    def test_public_configuration_does_not_expose_credentials(self):
        servers = normalize_servers({"mcpServers": {
            "remote": {
                "url": "https://user:password@example.test/mcp?token=query-secret",
                "headers": {"Authorization": "Bearer header-secret"},
                "env": {"API_TOKEN": "environment-secret"},
                "args": ["environment-secret"],
            },
        }})
        rendered = json.dumps(public_server_list(servers), ensure_ascii=False)
        for secret in ("password", "query-secret", "header-secret", "environment-secret"):
            self.assertNotIn(secret, rendered)

    def test_stdio_client_initializes_lists_and_calls_tools(self):
        server_code = r'''
import json
import sys
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if "id" not in message:
        if method == "notifications/exit":
            break
        continue
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "test", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "hello", "description": "Say hello", "inputSchema": {"type": "object", "properties": {}}}]}
    else:
        result = {"content": [{"type": "text", "text": "tool result"}]}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
'''
        with patch("modules.mcp.client.sandbox_process_options", return_value=(
            [sys.executable, "-u", "-c", server_code], {}, Path.cwd(),
        )):
            client = StdioMCPClient("test", {"command": "test", "args": [], "env": {}, "cwd": ""})
            try:
                initialize_client(client)
                listed = client.request("tools/list")
                called = client.request("tools/call", {"name": "hello", "arguments": {}})
            finally:
                client.close()

        schema = _function_schema("test-server", listed["tools"][0])
        self.assertTrue(schema["function"]["name"].startswith("mcp__"))
        self.assertEqual(_tool_result_text(called), "tool result")


if __name__ == "__main__":
    unittest.main()

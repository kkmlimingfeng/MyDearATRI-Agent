import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from modules.prompt.prompt_manager import PromptManager


class PromptManagerLanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.prompt_dir = Path(self.temp_dir.name)
        for name, content in {
            "AGENT-zh.md": "agent-zh",
            "AGENT-en.md": "agent-en",
            "SOUL-zh.md": "soul-zh",
            "SOUL-en.md": "soul-en",
            "USER-zh.md": "shared-user",
            "HEARTBEAT-zh.md": "shared-heartbeat-zh",
            "HEARTBEAT-en.md": "shared-heartbeat-en",
            "reviewer-zh.md": "reviewer-zh",
            "reviewer-en.md": "reviewer-en",
        }.items():
            (self.prompt_dir / name).write_text(content, encoding="utf-8")

        self.manager = PromptManager("prompt", Mock(), prompt_dir=str(self.prompt_dir))
        self.manager.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_prompt_uses_chinese_rules_and_persona(self):
        prompt = self.manager.get_system_prompt()

        self.assertIn("agent-zh", prompt)
        self.assertIn("soul-zh", prompt)
        self.assertNotIn("agent-en", prompt)
        self.assertNotIn("soul-en", prompt)
        self.assertIn("shared-user", prompt)
        self.assertIn("shared-heartbeat-zh", prompt)
        self.assertNotIn("shared-heartbeat-en", prompt)

    def test_english_prompt_uses_matching_bootstrap_language(self):
        prompt = self.manager.get_system_prompt("reviewer-en")

        self.assertIn("reviewer-en", prompt)
        self.assertIn("agent-en", prompt)
        self.assertIn("soul-en", prompt)
        self.assertNotIn("agent-zh", prompt)
        self.assertNotIn("soul-zh", prompt)
        self.assertIn("shared-user", prompt)
        self.assertIn("shared-heartbeat-en", prompt)
        self.assertNotIn("shared-heartbeat-zh", prompt)

    def test_legacy_reviewer_name_resolves_to_chinese_prompt(self):
        self.assertEqual(self.manager.get_prompt("reviewer"), "reviewer-zh")
        self.assertIn("reviewer-zh", self.manager.get_system_prompt("reviewer"))

    def test_default_workflow_prompt_files_exist(self):
        root = Path(__file__).resolve().parents[1]
        workflow = json.loads((root / "workflows" / "atri_companion_graph.json").read_text(encoding="utf-8"))
        prompt_dir = root / "modules" / "prompt" / "SystemPrompt"

        for node in workflow["nodes"]:
            if node.get("type") != "prompt.markdown_file":
                continue
            filename = node.get("data", {}).get("config", {}).get("file")
            self.assertTrue((prompt_dir / filename).is_file(), filename)


if __name__ == "__main__":
    unittest.main()

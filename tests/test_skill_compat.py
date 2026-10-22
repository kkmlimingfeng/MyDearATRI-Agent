import unittest
from unittest.mock import patch

from modules.tools.system_tools.bash_compat import Bash


class SkillToolCompatibilityTests(unittest.TestCase):
    def test_bash_alias_routes_regular_commands_through_project_sandbox(self):
        with patch(
            "modules.tools.system_tools.bash_compat.exec_sandbox_cmd",
            return_value="sandbox output",
        ) as sandbox:
            result = Bash("python -c 'print(1)'", timeout=99)

        self.assertEqual(result, "sandbox output")
        sandbox.assert_called_once_with(cmd="python -c 'print(1)'", timeout=30)
        self.assertEqual(Bash.__tool_metadata__["risk"], "execute")

    def test_bash_alias_routes_bb_browser_commands_to_browser_tool(self):
        with patch(
            "modules.tools.system_tools.bash_compat.bb_browser",
            return_value="browser output",
        ) as browser:
            result = Bash("bb-browser site list", timeout=99)

        self.assertEqual(result, "browser output")
        browser.assert_called_once_with(command="bb-browser site list", timeout=99)

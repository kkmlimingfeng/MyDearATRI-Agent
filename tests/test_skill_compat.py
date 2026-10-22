import unittest
from unittest.mock import patch

from modules.tools.system_tools.bash_compat import Bash


class SkillToolCompatibilityTests(unittest.TestCase):
    def test_bash_alias_routes_commands_through_project_sandbox(self):
        with patch(
            "modules.tools.system_tools.bash_compat.exec_sandbox_cmd",
            return_value="sandbox output",
        ) as sandbox:
            result = Bash("bb-browser site list", timeout=99)

        self.assertEqual(result, "sandbox output")
        sandbox.assert_called_once_with(cmd="bb-browser site list", timeout=30)
        self.assertEqual(Bash.__tool_metadata__["risk"], "execute")

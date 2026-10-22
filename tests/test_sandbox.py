import os
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import modules.sandbox_landlock as sandbox_landlock
import modules.sandbox_config as sandbox_config
import modules.tools.system_tools.exec_sandbox_cmd as sandbox_tool


class SandboxConfigTests(unittest.TestCase):
    def test_settings_default_to_project_workspace_and_workspace_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(sandbox_config, "PROJECT_ROOT", root), \
                    patch.object(sandbox_config, "DEFAULT_SETTINGS", {"workspace": str(root), "permission": "workspace"}), \
                    patch.object(sandbox_config, "SANDBOX_CONFIG_PATH", root / "sandbox.json"):
                self.assertEqual(
                    sandbox_config.load_sandbox_settings(),
                    {
                        "workspace": str(root),
                        "permission": "workspace",
                        "permissions": sandbox_config.WORKSPACE_PERMISSIONS,
                    },
                )

    def test_settings_save_and_load_a_selected_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "selected"
            workspace.mkdir()
            with patch.object(sandbox_config, "PROJECT_ROOT", root), \
                    patch.object(sandbox_config, "SANDBOX_CONFIG_PATH", root / "config" / "sandbox.json"):
                saved = sandbox_config.save_sandbox_settings({
                    "workspace": str(workspace),
                    "permission": "full",
                })
                self.assertEqual(saved["workspace"], str(workspace))
                self.assertEqual(saved["permission"], "full")
                self.assertEqual(saved["permissions"], sandbox_config.FULL_PERMISSIONS)
                self.assertEqual(sandbox_config.load_sandbox_settings(), saved)

    def test_settings_accept_a_workspace_outside_the_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            external = root / "external"
            project.mkdir()
            external.mkdir()
            with patch.object(sandbox_config, "PROJECT_ROOT", project), \
                    patch.object(sandbox_config, "SANDBOX_CONFIG_PATH", project / "config" / "sandbox.json"):
                saved = sandbox_config.save_sandbox_settings({
                    "workspace": str(external),
                    "permission": "workspace",
                })
            self.assertEqual(saved["workspace"], str(external))

    def test_workspace_mode_rejects_filesystem_root(self):
        with self.assertRaisesRegex(ValueError, "根目录"):
            sandbox_config._validate_settings({"workspace": os.path.abspath(os.sep), "permission": "workspace"})

    def test_custom_permissions_are_validated_and_outside_cannot_exceed_workspace(self):
        permissions = {
            "workspace": {"read": True, "write": True, "edit": True, "delete": False},
            "outside": {"read": True, "write": False, "edit": False, "delete": False},
        }
        validated = sandbox_config._validate_settings({"workspace": ".", "permission": "custom", "permissions": permissions})
        self.assertEqual(validated["permissions"], permissions)

        permissions["outside"]["delete"] = True
        with self.assertRaisesRegex(ValueError, "不能高于"):
            sandbox_config._validate_settings({"workspace": ".", "permission": "custom", "permissions": permissions})

    def test_directory_browser_lists_only_child_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "child").mkdir()
            (root / "file.txt").write_text("not a directory", encoding="utf-8")
            with patch.object(sandbox_config, "SANDBOX_CONFIG_PATH", root / "missing.json"), \
                    patch.object(sandbox_config, "DEFAULT_SETTINGS", {"workspace": str(root), "permission": "workspace"}):
                result = sandbox_config.browse_sandbox_directories()
            self.assertEqual(result["path"], str(root))
            self.assertEqual([item["name"] for item in result["directories"]], ["child"])

    def test_directory_browser_can_open_a_path_outside_the_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            external = root / "external"
            project.mkdir()
            (external / "child").mkdir(parents=True)
            with patch.object(sandbox_config, "PROJECT_ROOT", project):
                result = sandbox_config.browse_sandbox_directories(str(external))
            self.assertEqual(result["path"], str(external))
            self.assertEqual([item["name"] for item in result["directories"]], ["child"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Landlock runtime paths require Linux")
    def test_runtime_paths_include_symlink_targets_from_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            linked_bin = root / "linked-bin"
            actual_bin = root / "node-runtime" / "bin"
            linked_bin.mkdir()
            actual_bin.mkdir(parents=True)
            target = actual_bin / "node"
            target.write_text("runtime", encoding="utf-8")
            target.chmod(0o755)
            (linked_bin / "node").symlink_to(target)

            with patch.dict(os.environ, {"PATH": str(linked_bin)}):
                self.assertIn(actual_bin, sandbox_landlock._runtime_paths("node --version"))

    @unittest.skipUnless(sys.platform.startswith("linux"), "WSL drive paths are Linux-only")
    def test_windows_drive_paths_map_to_wsl_mounts(self):
        self.assertEqual(
            sandbox_config._path_from_user_input(r"C:\Users\ATRI\Projects"),
            Path("/mnt/c/Users/ATRI/Projects"),
        )


class SandboxExecutionTests(unittest.TestCase):
    def _run_with_permission(self, permission):
        workspace = Path("/tmp/atri-sandbox-workspace")
        process = SimpleNamespace(stdout="sandbox output", stderr="")
        with patch.object(sandbox_tool.shutil, "which", return_value="/usr/bin/firejail"), \
                patch.object(sandbox_tool, "load_sandbox_settings", return_value={
                    "workspace": str(workspace),
                    "permission": permission,
                    "permissions": sandbox_config.WORKSPACE_PERMISSIONS if permission == "workspace" else sandbox_config.FULL_PERMISSIONS,
                }), \
                patch.object(sandbox_tool, "landlock_abi", return_value=3), \
                patch.object(sandbox_tool.subprocess, "run", return_value=process) as run:
            output = sandbox_tool.exec_sandbox_cmd("python -c 'print(1)'")
        return output, run

    def test_workspace_mode_limits_writes_and_uses_runtime_python_and_workspace(self):
        output, run = self._run_with_permission("workspace")
        args = run.call_args.args[0]
        kwargs = run.call_args.kwargs

        self.assertIn("sandbox output", output)
        self.assertIn("--read-only=/", args)
        self.assertIn("--read-write=/tmp/atri-sandbox-workspace", args)
        self.assertEqual(kwargs["cwd"], Path("/tmp/atri-sandbox-workspace"))
        self.assertEqual(kwargs["env"]["PYTHON_BIN"], sandbox_tool.sys.executable)
        self.assertEqual(kwargs["env"]["PYTHON"], sandbox_tool.sys.executable)
        self.assertEqual(kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(kwargs["env"]["PATH"].split(os.pathsep)[0], str(Path(sandbox_tool.sys.executable).parent))

    def test_full_mode_leaves_filesystem_unrestricted(self):
        _output, run = self._run_with_permission("full")
        args = run.call_args.args[0]

        self.assertNotIn("--read-only=/", args)
        self.assertIn("--read-write=/", args)

    def test_custom_mode_uses_landlock_runner_and_read_only_root_when_outside_is_read_only(self):
        permissions = {
            "workspace": {"read": True, "write": True, "edit": False, "delete": False},
            "outside": {"read": True, "write": False, "edit": False, "delete": False},
        }
        workspace = Path("/tmp/atri-sandbox-workspace")
        process = SimpleNamespace(stdout="", stderr="")
        with patch.object(sandbox_tool.shutil, "which", return_value="/usr/bin/firejail"), \
                patch.object(sandbox_tool, "load_sandbox_settings", return_value={
                    "workspace": str(workspace), "permission": "custom", "permissions": permissions,
                }), \
                patch.object(sandbox_tool, "landlock_abi", return_value=3), \
                patch.object(sandbox_tool.subprocess, "run", return_value=process) as run:
            sandbox_tool.exec_sandbox_cmd("touch file")
        args = run.call_args.args[0]
        self.assertIn("--read-only=/", args)
        self.assertIn(f"--read-write={workspace}", args)
        self.assertTrue(any(str(arg).endswith("modules/sandbox_runner.py") for arg in args))

    def test_custom_mode_requires_supported_landlock(self):
        with patch.object(sandbox_tool.shutil, "which", return_value="/usr/bin/firejail"), \
                patch.object(sandbox_tool, "load_sandbox_settings", return_value={
                    "workspace": "/tmp/atri-sandbox-workspace",
                    "permission": "custom",
                    "permissions": sandbox_config.WORKSPACE_PERMISSIONS,
                }), \
                patch.object(sandbox_tool, "landlock_abi", return_value=2):
            result = sandbox_tool.exec_sandbox_cmd("touch file")
        self.assertIn("Landlock ABI 3", result)


@unittest.skipUnless(sys.platform.startswith("linux"), "Landlock integration test requires Linux")
class LandlockIntegrationTests(unittest.TestCase):
    def test_custom_rules_allow_only_selected_workspace_operations(self):
        from modules.sandbox_landlock import landlock_abi

        if landlock_abi() < 3:
            self.skipTest("Landlock ABI 3 is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            (workspace / "existing.txt").write_text("old", encoding="utf-8")
            (workspace / "delete.txt").write_text("remove", encoding="utf-8")
            (outside / "existing.txt").write_text("outside", encoding="utf-8")
            settings = {
                "workspace": str(workspace),
                "permission": "custom",
                "permissions": {
                    "workspace": {"read": True, "write": True, "edit": False, "delete": False},
                    "outside": {"read": True, "write": False, "edit": False, "delete": False},
                },
            }
            command = (
                f"touch '{workspace}/new.txt' && echo created; "
                f"printf changed > '{workspace}/existing.txt' 2>/dev/null || echo edit-blocked; "
                f"rm '{workspace}/delete.txt' 2>/dev/null || echo delete-blocked; "
                f"touch '{outside}/new.txt' 2>/dev/null || echo outside-create-blocked"
            )
            runner = Path(__file__).resolve().parents[1] / "modules" / "sandbox_runner.py"
            process = subprocess.run(
                [sys.executable, str(runner), command, json.dumps(settings)],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("created", process.stdout)
            self.assertIn("edit-blocked", process.stdout)
            self.assertIn("delete-blocked", process.stdout)
            self.assertIn("outside-create-blocked", process.stdout)
            self.assertTrue((workspace / "new.txt").is_file())
            self.assertEqual((workspace / "existing.txt").read_text(encoding="utf-8"), "old")
            self.assertTrue((workspace / "delete.txt").is_file())
            self.assertFalse((outside / "new.txt").exists())

    def test_custom_rules_can_hide_outside_files_while_reading_workspace_files(self):
        from modules.sandbox_landlock import landlock_abi

        if landlock_abi() < 3:
            self.skipTest("Landlock ABI 3 is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            (workspace / "visible.txt").write_text("inside", encoding="utf-8")
            (outside / "hidden.txt").write_text("outside", encoding="utf-8")
            settings = {
                "workspace": str(workspace),
                "permission": "custom",
                "permissions": {
                    "workspace": {"read": True, "write": False, "edit": False, "delete": False},
                    "outside": {"read": False, "write": False, "edit": False, "delete": False},
                },
            }
            command = (
                f"cat '{workspace}/visible.txt'; "
                f"if cat '{outside}/hidden.txt' >/dev/null 2>&1; "
                "then echo outside-read-allowed; else echo outside-read-blocked; fi"
            )
            runner = Path(__file__).resolve().parents[1] / "modules" / "sandbox_runner.py"
            process = subprocess.run(
                [sys.executable, str(runner), command, json.dumps(settings)],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("inside", process.stdout)
            self.assertIn("outside-read-blocked", process.stdout)


@unittest.skipUnless(sys.platform.startswith("linux"), "Firejail integration test requires Linux")
class FirejailIntegrationTests(unittest.TestCase):
    def test_workspace_mode_writes_inside_and_blocks_writes_outside(self):
        if not shutil.which("firejail"):
            self.skipTest("Firejail is not installed")
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            with patch.object(sandbox_config, "SANDBOX_CONFIG_PATH", root / "settings.json"):
                sandbox_config.save_sandbox_settings({"workspace": str(workspace), "permission": "workspace"})
                result = sandbox_tool.exec_sandbox_cmd("touch allowed.txt && touch ../outside/blocked.txt")
            self.assertTrue((workspace / "allowed.txt").is_file())
            self.assertFalse((outside / "blocked.txt").exists(), result)

    def test_custom_mode_enforces_operation_matrix_through_firejail(self):
        if not shutil.which("firejail"):
            self.skipTest("Firejail is not installed")
        from modules.sandbox_landlock import landlock_abi

        if landlock_abi() < 3:
            self.skipTest("Landlock ABI 3 is unavailable")
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            (workspace / "existing.txt").write_text("old", encoding="utf-8")
            (workspace / "delete.txt").write_text("remove", encoding="utf-8")
            permissions = {
                "workspace": {"read": True, "write": True, "edit": False, "delete": False},
                "outside": {"read": True, "write": False, "edit": False, "delete": False},
            }
            command = (
                "touch new.txt && echo created; "
                "printf changed > existing.txt 2>/dev/null || echo edit-blocked; "
                "rm delete.txt 2>/dev/null || echo delete-blocked; "
                "touch ../outside/new.txt 2>/dev/null || echo outside-create-blocked"
            )
            with patch.object(sandbox_config, "SANDBOX_CONFIG_PATH", root / "settings.json"):
                sandbox_config.save_sandbox_settings({
                    "workspace": str(workspace), "permission": "custom", "permissions": permissions,
                })
                result = sandbox_tool.exec_sandbox_cmd(command)
            self.assertTrue((workspace / "new.txt").is_file(), result)
            self.assertEqual((workspace / "existing.txt").read_text(encoding="utf-8"), "old", result)
            self.assertTrue((workspace / "delete.txt").is_file(), result)
            self.assertFalse((outside / "new.txt").exists(), result)
            self.assertIn("edit-blocked", result)
            self.assertIn("delete-blocked", result)

    def test_full_mode_can_modify_outside_workspace_through_firejail(self):
        if not shutil.which("firejail"):
            self.skipTest("Firejail is not installed")
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            (outside / "edit.txt").write_text("old", encoding="utf-8")
            with patch.object(sandbox_config, "SANDBOX_CONFIG_PATH", root / "settings.json"):
                sandbox_config.save_sandbox_settings({"workspace": str(workspace), "permission": "full"})
                result = sandbox_tool.exec_sandbox_cmd(
                    "cat ../outside/edit.txt && printf changed > ../outside/edit.txt && touch ../outside/new.txt"
                )
            self.assertEqual((outside / "edit.txt").read_text(encoding="utf-8"), "changed", result)
            self.assertTrue((outside / "new.txt").is_file(), result)

    def test_custom_mode_allows_only_outside_creation_when_selected(self):
        if not shutil.which("firejail"):
            self.skipTest("Firejail is not installed")
        from modules.sandbox_landlock import landlock_abi

        if landlock_abi() < 3:
            self.skipTest("Landlock ABI 3 is unavailable")
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            (outside / "existing.txt").write_text("old", encoding="utf-8")
            permissions = {
                "workspace": {"read": True, "write": True, "edit": True, "delete": True},
                "outside": {"read": True, "write": True, "edit": False, "delete": False},
            }
            command = (
                "touch ../outside/new.txt && echo outside-create-ok; "
                "printf changed > ../outside/existing.txt 2>/dev/null || echo outside-edit-blocked; "
                "rm ../outside/existing.txt 2>/dev/null || echo outside-delete-blocked"
            )
            with patch.object(sandbox_config, "SANDBOX_CONFIG_PATH", root / "settings.json"):
                sandbox_config.save_sandbox_settings({
                    "workspace": str(workspace), "permission": "custom", "permissions": permissions,
                })
                result = sandbox_tool.exec_sandbox_cmd(command)
            self.assertTrue((outside / "new.txt").is_file(), result)
            self.assertEqual((outside / "existing.txt").read_text(encoding="utf-8"), "old", result)
            self.assertIn("outside-create-ok", result)
            self.assertIn("outside-edit-blocked", result)
            self.assertIn("outside-delete-blocked", result)


if __name__ == "__main__":
    unittest.main()

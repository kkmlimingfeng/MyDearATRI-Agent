import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.graph_workflow import GraphWorkflowError
import web_server


class WorkflowDeleteTests(unittest.TestCase):
    def create_workflow(self, directory, workflow_id="delete-test"):
        path = Path(directory) / f"{workflow_id}.json"
        path.write_text(json.dumps({
            "workflow_version": 2,
            "id": workflow_id,
            "name": "Delete test",
            "nodes": [],
            "edges": [],
        }), encoding="utf-8")
        return path

    def test_delete_removes_graph_workflow_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.create_workflow(directory)
            with patch.object(web_server, "WORKFLOW_DIR", Path(directory)), \
                    patch.object(web_server, "_runtime_started", False), \
                    patch.object(web_server, "_runtime_workflow_id", None):
                result = web_server._delete_graph_workflow("delete-test")

            self.assertEqual(result, {"id": "delete-test", "deleted": True})
            self.assertFalse(path.exists())

    def test_running_workflow_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.create_workflow(directory)
            with patch.object(web_server, "WORKFLOW_DIR", Path(directory)), \
                    patch.object(web_server, "_runtime_started", True), \
                    patch.object(web_server, "_runtime_workflow_id", "delete-test"):
                with self.assertRaisesRegex(GraphWorkflowError, "停止运行"):
                    web_server._delete_graph_workflow("delete-test")

            self.assertTrue(path.is_file())

    def test_invalid_ids_and_non_workflow_json_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "other.json"
            other.write_text("{}", encoding="utf-8")
            with patch.object(web_server, "WORKFLOW_DIR", Path(directory)), \
                    patch.object(web_server, "_runtime_started", False), \
                    patch.object(web_server, "_runtime_workflow_id", None):
                with self.assertRaises(GraphWorkflowError):
                    web_server._delete_graph_workflow("../other")
                with self.assertRaisesRegex(GraphWorkflowError, "图工作流"):
                    web_server._delete_graph_workflow("other")

            self.assertTrue(other.is_file())


if __name__ == "__main__":
    unittest.main()

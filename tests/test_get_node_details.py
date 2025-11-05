from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.get_node_details import build_get_node_details_tool


class GetNodeDetailsToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.graph_path = Path(self._tempdir.name, "graph.json")
        self.node_id = "python::module::Foo"
        payload = {
            "nodes": [
                {
                    "id": self.node_id,
                    "kind": "class",
                    "file_path": "module.py",
                    "label": "Foo",
                    "category": "integration",
                }
            ],
            "edges": [],
        }
        self.graph_path.write_text(json.dumps(payload), encoding="utf-8")

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_returns_node_attributes(self) -> None:
        tool = build_get_node_details_tool(self.graph_path)
        result = tool.invoke({"node_id": self.node_id})

        self.assertEqual(result["id"], self.node_id)
        self.assertEqual(result["kind"], "class")
        self.assertEqual(result["file_path"], "module.py")
        self.assertEqual(result["label"], "Foo")
        self.assertEqual(result["category"], "integration")

    def test_missing_node_raises_value_error(self) -> None:
        tool = build_get_node_details_tool(self.graph_path)
        with self.assertRaises(ValueError):
            tool.invoke({"node_id": "python::module::Missing"})


if __name__ == "__main__":
    unittest.main()


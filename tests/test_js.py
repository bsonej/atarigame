"""Runs the node tests in tests/js (the editor's model, engine and palette) as part of the Python suite."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "needs node")
class EditorJavaScript(unittest.TestCase):
    def test_node_tests_pass(self) -> None:
        files = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.mjs"))
        self.assertTrue(files)
        out = subprocess.run(["node", "--test", *files], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stdout[-4000:] + out.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()

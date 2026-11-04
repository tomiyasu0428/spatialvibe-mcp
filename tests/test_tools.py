"""End-to-end checks of the MCP tools and the reel validator. Run: .venv/bin/python -m unittest -v"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="svmcp-"))
os.environ["SPATIALVIBE_HOME"] = str(TMP / "home")
os.environ["SPATIALVIBE_PUBLISH"] = f"dir:{TMP / 'pub'}"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "reel"))

from spatialvibe_mcp import server  # noqa: E402
import make_reel  # noqa: E402

BOX = "from build123d import *\nparts = {'block': Box(20, 10, 5)}\ncontext = {'pipe': Pos(0, 30, 0) * Cylinder(3, 40)}\n"


class ToolTests(unittest.TestCase):
    def test_build_preview_publish(self):
        r = server.build_model("t-flow", BOX, "block")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["parts"]["block"]["bbox_mm"]["size"], [20.0, 10.0, 5.0])
        self.assertTrue(r["parts"]["block"]["valid"])
        self.assertEqual(r["interference"], [])
        img, text = server.preview("t-flow")
        self.assertTrue(Path(text.split(": ", 1)[1]).exists())
        pub = server.publish_ar("t-flow")
        self.assertTrue(Path(pub["published"]).exists())
        # block is 20 mm wide along X; USDZ must be in metres
        self.assertIn(0.02, pub["size_m"])
        self.assertLess(max(pub["size_m"]), 1.0)

    def test_versions_and_code(self):
        server.build_model("t-ver", BOX)
        server.build_model("t-ver", BOX.replace("20, 10, 5", "30, 10, 5"))
        self.assertEqual([v["version"] for v in server.list_projects("t-ver")["versions"]], [1, 2])
        self.assertIn("30, 10, 5", server.get_code("t-ver"))
        self.assertIn("20, 10, 5", server.get_code("t-ver", 1))

    def test_interference_detected(self):
        code = "from build123d import *\nparts = {'a': Box(10, 10, 10)}\ncontext = {'pipe': Cylinder(3, 30)}\n"
        r = server.build_model("t-hit", code)
        self.assertEqual(r["interference"][0]["b"], "context:pipe")

    def test_errors_are_reported(self):
        r = server.build_model("t-err", "raise ValueError('nope')")
        self.assertFalse(r["ok"])
        self.assertIn("nope", r["error"])
        with self.assertRaises(ValueError):
            server.preview("t-err")
        self.assertFalse(server.build_model("t-err", "x = 1")["ok"])  # no parts

    @unittest.skipUnless(sys.platform == "darwin", "sandbox-exec is macOS only")
    def test_sandbox_blocks_writes_outside(self):
        target = Path.home() / "svmcp_escape_test.txt"
        r = server.build_model("t-sbx", f"open({str(target)!r}, 'w').write('x')")
        self.assertFalse(r["ok"])
        self.assertFalse(target.exists())

    def test_bad_project_name(self):
        with self.assertRaises(ValueError):
            server.build_model("../escape", BOX)


class ReelTests(unittest.TestCase):
    def test_existing_reels_are_valid(self):
        for f in sorted((ROOT / "reels").glob("*/scenes.json")):
            self.assertEqual(make_reel.validate(json.loads(f.read_text(encoding="utf-8"))), [], f)

    def test_validator_rejects_wrong_total(self):
        reel = {"scenes": [{"type": "drop", "dur": 3000, "big": "あ"}] * 3 + [{"type": "final", "dur": 3000, "big": "い"}]}
        self.assertTrue(any("20000" in e for e in make_reel.validate(reel)))


if __name__ == "__main__":
    unittest.main()

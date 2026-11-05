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
        views, sheet, text = server.preview("t-flow")
        self.assertTrue(Path(views.path).exists())
        self.assertTrue(Path(sheet.path).exists())
        self.assertTrue(str(sheet.path).endswith("sheet.png"))
        pub = server.publish_ar("t-flow")
        self.assertTrue(Path(pub["published"]).exists())
        # block is 20 × 10 × 5 mm; reported in metres with labelled axes (x width, y depth, z height)
        self.assertEqual(pub["parts_size_m"], {"x_width": 0.02, "y_depth": 0.01, "z_height": 0.005})
        # the scene also holds the 40 mm tall context pipe (along Z, so it is the height)
        self.assertEqual(pub["scene_size_m"]["z_height"], 0.04)
        self.assertLess(max(pub["scene_size_m"].values()), 1.0)

    def test_holes_bed_and_lists(self):
        code = ("from build123d import *\n"
                "plate = Box(60, 20, 5) - Pos(-20, 0, 0) * Cylinder(2.75, 10) - Pos(20, 0, 0) * Cylinder(2.75, 10)\n"
                "parts = {'plate': plate, 'long': Pos(0, 50, 0) * Box(300, 10, 5)}\n"
                "hardware = ['M5×12 ボルト・ナット 2組']\n"
                "checks = ['穴の間隔 40 mm']\n")
        r = server.build_model("t-holes", code)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["parts"]["plate"]["holes"], [{"d": 5.5, "n": 2, "half": False}])
        self.assertTrue(r["parts"]["plate"]["fits_bed"])
        self.assertFalse(r["parts"]["long"]["fits_bed"])  # 300 mm > 256 mm bed
        self.assertEqual(r["hardware"], ["M5×12 ボルト・ナット 2組"])
        self.assertEqual(r["checks"], ["穴の間隔 40 mm"])
        self.assertEqual(r["parts_size_mm"], [300.0, 65.0, 5.0])

    def test_bad_hardware_list(self):
        r = server.build_model("t-hw", BOX + "hardware = 'M5'\n")
        self.assertFalse(r["ok"])
        self.assertIn("hardware", r["error"])

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



PARTIAL = (BOX.replace("parts = {'block': Box(20, 10, 5)}", "parts = {'a': Box(10, 10, 10), 'b': Pos(30, 0, 0) * Box(10, 10, 10)}")
           + "import build123d\n_orig = build123d.export_stl\n_n = [0]\n"
           "def _boom(*a, **k):\n    _n[0] += 1\n    if _n[0] == 2:\n        raise RuntimeError('injected')\n"
           "    return _orig(*a, **k)\nbuild123d.export_stl = _boom\n")


class FailureTests(unittest.TestCase):
    """A failed or odd build must never look finished (regressions from the verification rounds)."""

    def test_partial_build_leaves_nothing_and_cannot_be_shown(self):
        server.build_model("f-part", BOX)                       # v1 is fine
        r = server.build_model("f-part", PARTIAL)               # v2 dies after exporting part a
        self.assertFalse(r["ok"])
        v2 = Path(r["folder"])
        self.assertEqual(sorted(f.name for f in v2.iterdir()), ["model.py", "note.txt", "result.json"])
        with self.assertRaises(server.SpatialVibeError) as e:
            server.preview("f-part")
        self.assertIn("did not build", str(e.exception))
        with self.assertRaises(server.SpatialVibeError):
            server.publish_ar("f-part")
        self.assertEqual(server.list_projects("f-part")["versions"][1]["status"], "failed")
        server.preview("f-part", 1)                             # the good version still works

    def test_hard_crash_reports_exit_code(self):
        r = server.build_model("f-crash", "import os\nos._exit(3)\n")
        self.assertFalse(r["ok"])
        self.assertIn("code 3", r["error"])

    def test_script_output_cannot_fake_success(self):
        r = server.build_model("f-fake", 'print(\'{"ok": true, "parts": {}}\')\nimport os\nos._exit(1)\n')
        self.assertFalse(r["ok"])

    def test_print_without_newline_does_not_break_build(self):
        r = server.build_model("f-print", "import sys\nsys.stdout.write('building...')\n" + BOX)
        self.assertTrue(r["ok"], r)

    def test_interference_exception_is_unchecked_not_clear(self):
        code = BOX + ("import build123d\nfrom build123d.topology.composite import Compound\n"
                      "def _boom(*a, **k):\n    raise RuntimeError('injected boolean failure')\n"
                      "Compound.__and__ = _boom\nbuild123d.Shape.__and__ = _boom\n")
        r = server.build_model("f-int", code)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["interference"], [])
        self.assertEqual([(u["a"], u["b"]) for u in r["interference_unchecked"]], [("block", "context:pipe")])
        self.assertTrue(any("未判定" in w for w in r["warnings"]))

    def test_open_mesh_and_split_part_are_warned(self):
        code = "from build123d import *\nparts = {'t': Box(20, 20, 10) + Pos(15, 0, 0) * Cylinder(5, 10)}\n"
        r = server.build_model("f-mesh", code)
        p = r["parts"]["t"]
        self.assertFalse(p["watertight"])
        self.assertEqual(p["solids"], 2)
        self.assertTrue(any("閉じていない" in w for w in r["warnings"]))
        self.assertTrue(any("塊に分かれている" in w for w in r["warnings"]))

    def test_bad_names_are_rejected_with_a_message(self):
        for bad in ("a\n", "../x", "", "日本語"):
            with self.assertRaises(server.SpatialVibeError):
                server.build_model(bad, BOX)
        r = server.build_model("f-name", "from build123d import *\nparts = {'スプーン': Box(1, 1, 1)}\n")
        self.assertIn("ASCII", r["error"])

    def test_parallel_builds_get_their_own_versions(self):
        import threading
        out = []
        ts = [threading.Thread(target=lambda: out.append(server.build_model("f-par", BOX)["version"])) for _ in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(out), [1, 2, 3, 4, 5])


class HoleTests(unittest.TestCase):
    def test_positions_slots_split_holes_and_separate_clamps(self):
        code = ("from build123d import *\n"
                "p = Box(80, 30, 10)\n"
                "p -= Pos(-30, 0, 0) * Cylinder(2.75, 20)\n"                      # plain hole
                "p -= Pos(-15, 0, 0) * Cylinder(2.75, 20)\n"
                "p -= Pos(-15, 0, 0) * Box(9, 9, 3)\n"                            # nut pocket splits it
                "p -= Pos(15, 0, 0) * extrude(Plane.XY.offset(-10) * SlotOverall(14, 6), 20)\n"  # slot
                "bar = Box(200, 40, 30) - Rot(0, 90, 0) * Cylinder(10, 60)\n"
                "bar -= Pos(90, 0, 0) * Rot(0, 90, 0) * Cylinder(10, 21)\n"       # 2nd bore, same axis, far away
                "parts = {'plate': p, 'bar': bar}\n")
        r = server.build_model("h-mix", code)
        self.assertTrue(r["ok"], r)
        hl = r["parts"]["plate"]["hole_list"]
        holes = [h for h in hl if h.get("kind") != "slot"]
        self.assertEqual(sorted(h["at"][0] for h in holes), [-30.0, -15.0])  # split hole counted once
        self.assertTrue(all(not h["half"] and h["d"] == 5.5 and h["axis"] == "Z" for h in holes))
        slots = [h for h in hl if h.get("kind") == "slot"]
        self.assertEqual(len(slots), 1)
        self.assertEqual((slots[0]["d"], slots[0]["length"], slots[0]["at"][0]), (6.0, 14.0, 15.0))
        bores = [h for h in r["parts"]["bar"]["hole_list"] if h["d"] == 20.0]
        self.assertEqual(len(bores), 2)                                      # two bores, not merged

    def test_split_clamp_halves_both_report_the_bore(self):
        code = ("from build123d import *\n"
                "c = Box(20, 50, 40) - Rot(0, 90, 0) * Cylinder(13.8, 30)\n"
                "parts = {'upper': split(c, Plane.XY), 'lower': split(c, Plane.XY, keep=Keep.BOTTOM)}\n")
        r = server.build_model("h-clamp", code)
        for p in ("upper", "lower"):
            self.assertIn({"d": 27.6, "n": 1, "half": True}, r["parts"][p]["holes"], p)



DIMS_CODE = r"""
from build123d import *
import math
plate = Box(110, 5, 120)
for x in (-49, 49):
    for z in (-31, 31):
        plate -= Pos(x, 0, z) * Rot(90, 0, 0) * Cylinder(1.75, 20)
        plate -= Pos(x, 2.5, z) * Rot(90, 0, 0) * Cylinder(3.25, 2.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
comb = Pos(0, 100, 0) * (Box(60, 10, 15) - Pos(0, 0, 5) * Box(6, 20, 10))
t1 = 6 + 40 * math.tan(math.radians(7))
wedge = Pos(-30, -120, 0) * extrude(Plane.YZ * Polygon((0, 0), (40, 0), (40, t1), (0, 6), align=None), 60)
parts = {"plate": plate, "comb": comb, "wedge": wedge}
context = {"post": Pos(0, 47.5, 0) * Box(90, 90, 300)}
origin = "柱の正面の中心"
print_pose = {"wedge": Rot(0, 0, 90)}
dims = [
  {"label": "穴 横", "part": "plate", "kind": "distance", "a": (-48, 0, 30), "b": (50, 0, 30), "snap": "hole", "axis": "X", "expect": 98},
  {"label": "溝の幅", "part": "comb", "kind": "gap", "at": (0, 100, 6), "axis": "X", "expect": 6},
  {"label": "厚さ", "part": "comb", "kind": "thickness", "at": (20, 100, 0), "axis": "Y", "expect": 10},
  {"label": "傾き", "part": "wedge", "kind": "angle", "a": (0, -100, 7.5), "ref": "Z", "expect": 7},
  {"label": "柱", "part": "plate", "kind": "clearance", "to": "post"},
  {"label": "わざとずれ", "part": "comb", "kind": "gap", "at": (0, 100, 6), "axis": "X", "expect": 7},
  {"label": "溝がない所", "part": "comb", "kind": "gap", "at": (20, 100, 0), "axis": "X"},
]
"""


class DimsTests(unittest.TestCase):
    """Fit dimensions are measured on the shape, not copied from the script."""

    @classmethod
    def setUpClass(cls):
        cls.r = server.build_model("d-dims", DIMS_CODE)

    def dim(self, label):
        return next(d for d in self.r["dims"] if d["label"] == label)

    def test_measured_values(self):
        self.assertTrue(self.r["ok"], self.r)
        self.assertEqual(self.dim("穴 横")["value"], 98.0)        # snapped to the hole centres
        self.assertEqual(self.dim("溝の幅")["value"], 6.0)
        self.assertEqual(self.dim("厚さ")["value"], 10.0)
        self.assertAlmostEqual(self.dim("傾き")["value"], 7.0, places=1)
        self.assertEqual(self.dim("柱")["value"], 0.0)            # plate touches the post

    def test_mismatch_and_missing_gap_are_warned(self):
        self.assertFalse(self.dim("わざとずれ")["ok"])
        self.assertIsNone(self.dim("溝がない所")["value"])
        self.assertTrue(any("わざとずれ" in w for w in self.r["warnings"]))
        self.assertTrue(any("溝がない所" in w and "no gap" in w for w in self.r["warnings"]))

    def test_counterbore_spacing_origin_print_pose(self):
        plate = self.r["parts"]["plate"]
        self.assertEqual(len(plate["hole_list"]), 4)                     # counterbores merged, not 8 holes
        self.assertEqual(plate["hole_list"][0]["counterbore"]["d"], 6.5)
        self.assertEqual(plate["hole_spacing"][0]["along"], {"X": [98.0], "Z": [62.0]})
        self.assertEqual(self.r["origin"], "柱の正面の中心")
        w = self.r["parts"]["wedge"]
        self.assertEqual(w["print_size_mm"][:2], [40.0, 60.0])           # turned 90° for printing
        self.assertTrue((Path(self.r["folder"]) / "print_wedge.stl").exists())
        _, sheet, _ = server.preview("d-dims")
        self.assertTrue(Path(sheet.path).exists())

class StdioTests(unittest.TestCase):
    """Over a real MCP stdio connection the server's own error text must reach the client."""

    def test_error_text_reaches_client(self):
        import anyio
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        env = dict(os.environ, PYTHONPATH=str(ROOT), SPATIALVIBE_HOME=str(TMP / "stdio-home"))
        params = StdioServerParameters(command=sys.executable, args=["-m", "spatialvibe_mcp"], env=env, cwd=str(ROOT))

        async def go():
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    res = await s.call_tool("preview", {"project": "nothing-here"})
                    bad = await s.call_tool("build_model", {"project": "../x", "code": "x"})
                    ok = await s.call_tool("list_projects", {})
                    return res, bad, ok

        res, bad, ok = anyio.run(go)
        self.assertTrue(res.is_error)
        self.assertIn("no versions yet", res.content[0].text)
        self.assertTrue(bad.is_error)
        self.assertIn("ASCII", bad.content[0].text)
        self.assertFalse(ok.is_error)                                     # the session keeps working

class ReelTests(unittest.TestCase):
    def test_existing_reels_are_valid(self):
        for f in sorted((ROOT / "reels").glob("*/scenes.json")):
            self.assertEqual(make_reel.validate(json.loads(f.read_text(encoding="utf-8"))), [], f)

    def test_validator_rejects_wrong_total(self):
        reel = {"scenes": [{"type": "drop", "bars": 1, "big": "あ"}] * 3 + [{"type": "final", "bars": 2, "big": "い"}]}
        self.assertTrue(any("add up to 10" in e for e in make_reel.validate(reel)))

    def test_music_matches_timeline(self):
        import music
        scenes = json.loads((ROOT / "reels/2026-11-04-app-to-mcp/scenes.json").read_text(encoding="utf-8"))["scenes"]
        st, hits = music.render(scenes)
        self.assertAlmostEqual(len(st) / music.SR, 20.0, places=2)
        self.assertLessEqual(abs(st).max(), 1.0)
        kicks = [h["t"] for h in hits if h["k"] == "kick"]
        # every kick sits on the 32nd-note grid (62.5 ms at 120 BPM; the glitch stutter uses 32nds)
        self.assertTrue(all(abs(t / 62.5 - round(t / 62.5)) < 0.02 for t in kicks))


if __name__ == "__main__":
    unittest.main()

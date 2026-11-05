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
        views, sheet, detail, text = server.preview("t-flow")
        self.assertTrue(Path(views.path).exists())
        self.assertTrue(Path(sheet.path).exists())
        self.assertTrue(Path(detail.path).exists() and str(detail.path).endswith("sheet_detail.png"))
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
        _, sheet, _, _ = server.preview("d-dims")
        self.assertTrue(Path(sheet.path).exists())


FACE_CODE = r"""
from build123d import *
# L-bracket: wall plate at y 0..5 against a wall (y<0), arm with a sensor hole 40 from the wall, 25 up
plate = Box(55, 5, 45, align=(Align.CENTER, Align.MIN, Align.MIN))
arm = Pos(-25, 0, 0) * Box(5, 55, 45, align=(Align.CENTER, Align.MIN, Align.MIN))
br = plate + arm - Pos(-25, 40, 25) * Rot(0, 90, 0) * Cylinder(8.25, 20)
tray = Pos(100, 0, 0) * (Box(40, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
                         - Pos(0, 0, 2) * Box(36, 26, 30, align=(Align.CENTER, Align.CENTER, Align.MIN)))
parts = {"br": br, "tray": tray}
context = {"wall": Box(200, 10, 100, align=(Align.CENTER, Align.MAX, Align.MIN)),
           "rod": Pos(-25, 40, 25) * Rot(0, 90, 0) * Cylinder(8.0, 40)}
print_pose = {"br": "-X"}
dims = [
  {"label": "壁から穴", "part": "br", "kind": "distance", "a": (-25, 0, 25), "b": (-25, 40, 25),
   "snap_a": "context:wall", "snap_b": "hole", "axis": "Y", "expect": 40},
  {"label": "底から穴", "part": "br", "kind": "distance", "a": (-25, 40, 0), "b": (-25, 40, 25),
   "snap_a": "face", "snap_b": "hole", "axis": "Z", "expect": 25},
  {"label": "穴径", "part": "br", "kind": "diameter", "at": (-25, 40, 25), "expect": 16.5, "vs": 16, "vs_label": "筒"},
  {"label": "深さ", "part": "tray", "kind": "distance", "a": (100, 0, 2), "b": (100, 14, 20),
   "snap": "face", "axis": "Z", "expect": 18},
  {"label": "幅", "part": "tray", "kind": "size", "axis": "X", "expect": 40},
  {"label": "壁から", "part": "tray", "kind": "overhang", "to": "wall", "axis": "Z", "side": "+"},
  {"label": "筒とのすき間", "part": "br", "kind": "clearance", "to": "rod", "expect": 0.25, "tol": 0.05},
  {"label": "手入力", "part": "br", "kind": "distance", "a": (0, 0, 0), "b": (0, 0, 10)},
]
"""


class FaceSnapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = server.build_model("d-face", FACE_CODE)

    def dim(self, label):
        return next(d for d in self.r["dims"] if d["label"] == label)

    def test_face_and_hole_snaps_are_measured(self):
        self.assertTrue(self.r["ok"], self.r)
        self.assertEqual(self.dim("壁から穴")["value"], 40.0)
        self.assertTrue(self.dim("壁から穴")["measured"])
        self.assertEqual(self.dim("底から穴")["value"], 25.0)
        self.assertEqual(self.dim("深さ")["value"], 18.0)                  # open-top depth, floor to rim
        self.assertFalse(self.dim("手入力")["measured"])                    # typed points are marked

    def test_other_kinds(self):
        self.assertEqual(self.dim("穴径")["value"], 16.5)
        self.assertEqual(self.dim("穴径")["vs"], 16.0)
        self.assertEqual(self.dim("幅")["value"], 40.0)
        self.assertEqual(self.dim("壁から")["value"], -80.0)               # tray top is 80 below the wall top
        self.assertTrue(self.dim("筒とのすき間")["ok"])

    def test_intended_clearance_is_not_a_warning(self):
        self.assertFalse(any("rod とのすき間" in w for w in self.r["warnings"]), self.r["warnings"])

    def test_print_pose_by_face(self):
        self.assertEqual(self.r["parts"]["br"]["print_down"], "-X")
        _, sheet, _, _ = server.preview("d-face")
        self.assertTrue(Path(sheet.path).exists())

ROUND_CODE = """
from build123d import *
# stepped adapter: pump socket Ø20.8 depth 20, through bore Ø10, spigot Ø15.6 on top
body = Pos(0, 0, 11) * Cylinder(13, 22) + Pos(0, 0, 34) * Cylinder(7.8, 24)
body -= Pos(0, 0, 10) * Cylinder(10.4, 20) + Pos(0, 0, 23) * Cylinder(5, 46)
# C clip: ring Ø25.8 bore, open toward -Y
clip = Pos(60, 0, 0) * Cylinder(16, 15)
clip -= Pos(60, 0, 0) * Cylinder(12.9, 15) + Pos(60, -16, 0) * Box(21, 16, 15)
plate = Pos(0, 60, 3) * Box(40, 30, 6)
plate = plate.fillet(1, plate.edges().filter_by(Axis.Z))   # a bare Solid: & gives None when apart
parts = {"adapter": body, "clip": clip, "plate": plate}
context = {"block": Pos(0, 60, -5) * Box(40, 30, 10)}       # touches the plate's underside
dims = [
    {"label": "外径", "part": "adapter", "kind": "diameter", "outer": True, "at": (0, 0, 40), "expect": 15.6},
    {"label": "ソケット", "part": "adapter", "kind": "diameter", "at": (0, 0, 10), "expect": 20.8},
    {"label": "中の穴", "part": "adapter", "kind": "diameter", "at": (0, 0, 40), "expect": 10},
    {"label": "クリップ穴", "part": "clip", "kind": "diameter", "at": (60, 0, 0)},
]
"""


class RoundDimsTests(unittest.TestCase):
    """Fixes from dimension round D: outer Ø, stepped bores, clip bores, touching bare solids."""

    @classmethod
    def setUpClass(cls):
        cls.r = server.build_model("d-round", ROUND_CODE)

    def dim(self, label):
        return next(d for d in self.r["dims"] if d["label"] == label)

    def test_outer_and_stepped_diameters(self):
        self.assertTrue(self.r["ok"], self.r)
        self.assertAlmostEqual(self.dim("外径")["value"], 15.6, places=1)
        self.assertAlmostEqual(self.dim("ソケット")["value"], 20.8, places=1)
        self.assertAlmostEqual(self.dim("中の穴")["value"], 10.0, places=1)

    def test_clip_diameter_arrow_avoids_the_mouth(self):
        d = self.dim("クリップ穴")
        a, b = d["p"]
        self.assertLess(abs(a[1] - b[1]), 1e-6, d)       # drawn across X, not out through the -Y mouth

    def test_touching_bare_solid_is_not_unchecked(self):
        self.assertEqual(self.r["interference_unchecked"], [], self.r["warnings"])



class ArFloorTests(unittest.TestCase):
    """A part on a pipe must open in AR at its real height above the floor the user aims at."""

    def test_floor_plate_puts_origin_at_real_height(self):
        from pxr import Usd, UsdGeom
        code = ("from build123d import *\n"
                "parts = {'clip': Pos(0, 0, 20) * Box(30, 30, 10)}\n"
                "context = {'pipe': Rot(0, 90, 0) * Cylinder(12.7, 200)}\n"
                "ar_floor = -800\n")
        r = server.build_model("ar-floor", code)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["ar_floor_z"], -800.0)
        out = server.publish_ar("ar-floor")
        self.assertEqual(out["ar_floor_mm"], -800.0)
        stage = Usd.Stage.Open(out["usdz"])
        rng = UsdGeom.BBoxCache(0, ["default"]).ComputeWorldBound(stage.GetDefaultPrim()).ComputeAlignedRange()
        self.assertAlmostEqual(rng.GetMin()[1], -0.801, places=3)     # floor plate bottom (Y up, metres)
        clip = UsdGeom.BBoxCache(0, ["default"]).ComputeWorldBound(
            stage.GetPrimAtPath("/Root/m_part_clip")).ComputeAlignedRange()
        self.assertAlmostEqual(clip.GetMax()[1], 0.025, places=3)     # clip top stays at its real height

    def test_floor_standing_part_rests_on_the_real_floor(self):
        from pxr import Usd, UsdGeom
        code = ("from build123d import *\n"
                "parts = {'shim': Pos(0, 0, 2) * Box(50, 50, 4)}\n"
                "context = {'floor': Pos(0, 0, -5) * Box(200, 200, 10), 'leg': Pos(0, 0, 24) * Box(40, 40, 40)}\n"
                "ar_floor = 0\n")
        server.build_model("ar-floor0", code)
        out = server.publish_ar("ar-floor0")
        stage = Usd.Stage.Open(out["usdz"])
        rng = UsdGeom.BBoxCache(0, ["default"]).ComputeWorldBound(stage.GetDefaultPrim()).ComputeAlignedRange()
        self.assertAlmostEqual(rng.GetMin()[1], -0.001, places=3)   # the floor slab is gone; the shim sits on 0

    def test_floor_above_model_is_refused_with_text(self):
        code = ("from build123d import *\n"
                "parts = {'a': Box(10, 10, 10)}\n"
                "ar_floor = 0\n")
        server.build_model("ar-floor-bad", code)
        with self.assertRaises(server.SpatialVibeError) as cm:
            server.publish_ar("ar-floor-bad")
        self.assertIn("ar_floor", str(cm.exception))


class UseCaseRoundTests(unittest.TestCase):
    """Fixes from the 10-genre use-case round: sleeve is not a counterbore, blind holes are marked,
    "part" wildcards in dims, screws in the context (hw_*) do not warn, copies are recognised."""

    @classmethod
    def setUpClass(cls):
        code = (
            "from build123d import *\n"
            "cup = Cylinder(56, 80) - Pos(0, 0, 6) * Cylinder(52, 80) - Cylinder(4, 200)\n"   # Ø104 sleeve + Ø8 drain
            "blk = Pos(150, 0, 0) * Box(30, 30, 20) - Pos(150, 0, 5) * Cylinder(3, 10)\n"     # blind Ø6 from the top
            "hookL = Pos(0, 150, 0) * Box(20, 20, 20) - Pos(0, 150, 0) * Cylinder(3.3, 20)\n"
            "hookR = Pos(80, 150, 0) * Box(20, 20, 20) - Pos(80, 150, 0) * Cylinder(3.3, 20)\n"
            "parts = {'cup': cup, 'blk': blk, 'hook_L': hookL, 'hook_R': hookR}\n"
            "context = {'hw_bolt': Pos(0, 150, 0) * Cylinder(3.0, 30)}\n"
            "dims = [{'label': 'W', 'part': 'hook_*', 'kind': 'size', 'axis': 'X', 'expect': 20}]\n")
        cls.r = server.build_model("uc-round", code)

    def test_sleeve_is_not_a_counterbore(self):
        hl = self.r["parts"]["cup"]["hole_list"]
        self.assertTrue(all(not h.get("counterbore") for h in hl), hl)

    def test_blind_hole_is_marked(self):
        hl = self.r["parts"]["blk"]["hole_list"]
        self.assertEqual([h.get("through") for h in hl], [False], hl)
        self.assertTrue(self.r["parts"]["hook_L"]["hole_list"][0]["through"])

    def test_cut_that_removes_nothing_is_warned(self):
        code = ("from build123d import *\n"
                "blk = Box(20, 20, 20)\n"
                "blk = blk - Pos(100, 0, 0) * Cylinder(3, 30)\n"      # misses the part entirely
                "parts = {'blk': blk}\n")
        r = server.build_model("uc-noop", code)
        self.assertTrue(r["ok"], r)
        self.assertTrue(any("3 行目" in w and "削っていない" in w for w in r["warnings"]), r["warnings"])

    def test_changes_since_previous_version(self):
        server.build_model("uc-diff", "from build123d import *\nparts = {'p': Box(20, 20, 5) - Pos(5, 0, 0) * Cylinder(2, 10)}\n")
        r = server.build_model("uc-diff", "from build123d import *\nparts = {'p': Box(30, 20, 5) - Pos(8, 0, 0) * Cylinder(2, 10)}\n")
        ch = r["changes"]
        self.assertEqual(ch["since_version"], 1)
        self.assertTrue(any("size 20 × 20 × 5 → 30 × 20 × 5" in c and "holes moved" in c for c in ch["changed"]), ch)

    def test_poses_find_a_collision_when_flipped_up(self):
        code = ("from build123d import *\n"
                "arm = Pos(100, 0, 0) * Box(200, 20, 10)\n"
                "holder = Pos(180, 0, 20) * Box(30, 30, 30)\n"
                "parts = {'holder': holder}\n"
                "context = {'arm': arm, 'backrest': Pos(15, 0, 150) * Box(10, 100, 100)}\n"
                "up = Rot(0, -80, 0)\n"
                "poses = {'flipped_up': {'holder': up, 'arm': up}}\n")
        r = server.build_model("uc-pose", code)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["interference"], [])
        self.assertTrue(any(h["b"] == "context:backrest" for h in r["poses"]["flipped_up"]), r["poses"])
        self.assertTrue(any("flipped_up" in w for w in r["warnings"]))

    def test_clearance_to_another_part(self):
        code = ("from build123d import *\n"
                "parts = {'a': Box(10, 10, 10), 'b': Pos(13, 0, 0) * Box(10, 10, 10)}\n"
                "dims = [{'label': 'すき間', 'part': 'a', 'kind': 'clearance', 'to': 'b', 'expect': 3}]\n")
        r = server.build_model("uc-pp", code)
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(r["dims"][0]["value"], 3.0, places=2)

    def test_part_wildcard_and_hardware_context(self):
        self.assertEqual(sorted(d["part"] for d in self.r["dims"]), ["hook_L", "hook_R"])
        self.assertFalse(any("hw_bolt" in w for w in self.r["warnings"]), self.r["warnings"])
        _, sheet, _, _ = server.preview("uc-round")
        self.assertTrue(Path(sheet.path).exists())



class FlowRoundGTests(unittest.TestCase):
    """Round G: hinges off the origin, near misses, a slot narrower than the object, levers."""

    def test_pose_about_a_pivot_and_near_miss(self):
        # an arm hinged at x=0 (pin), a cup base at x=200; a handle that the base just misses
        code = ("from build123d import *\n"
                "arm = Pos(100, 0, 0) * Box(200, 20, 10)\n"
                "parts = {'base': Pos(200, 0, 15) * Box(20, 20, 20)}\n"
                "context = {'arm': arm, 'handle': Pos(-31.5, 0, 200) * Box(10, 40, 10)}\n"
                "up = {'rot': (0, -90, 0), 'pivot': (0, 0, 0)}\n"
                "poses = {'up': {'base': up, 'arm': up}}\n")
        r = server.build_model("g-pivot", code)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["poses"]["up"], [])
        g = r["pose_closest"]["up"]
        self.assertEqual(g["b"], "context:handle")
        self.assertLess(g["mm"], 3.0)
        self.assertTrue(any("すれすれ" in w for w in r["warnings"]), r["warnings"])

    def test_pivot_moves_about_the_hinge_not_the_origin(self):
        code = ("from build123d import *\n"
                "parts = {'p': Pos(110, 0, 0) * Box(10, 10, 10)}\n"
                "context = {'wall': Pos(100, 0, 60) * Box(40, 40, 4)}\n"
                "poses = {'up': {'p': {'rot': (0, -90, 0), 'pivot': (100, 0, 0)}}}\n")
        r = server.build_model("g-pivot2", code)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["poses"]["up"], [])     # turned about x=100 it stands at z≈10, below the wall

    def test_slot_narrower_than_the_object_warns(self):
        code = ("from build123d import *\n"
                "body = Box(30, 20, 20) - Pos(0, 0, 5) * Box(7, 30, 20)\n"
                "parts = {'hook': body}\n"
                "dims = [{'label': 'みぞ', 'part': 'hook', 'kind': 'gap', 'at': (0, 0, 8), 'axis': 'X',"
                " 'vs': 8, 'vs_label': 'ふち'}]\n")
        r = server.build_model("g-slot", code)
        self.assertTrue(r["ok"], r)
        self.assertTrue(any("入らない" in w for w in r["warnings"]), r["warnings"])

    def test_loads_report_the_lever(self):
        code = ("from build123d import *\n"
                "parts = {'clamp': Box(20, 20, 20)}\n"
                "context = {'box': Pos(0, 110, 40) * Box(100, 60, 40)}\n"
                "loads = {'box': 0.8}\n")
        r = server.build_model("g-load", code)
        self.assertTrue(r["ok"], r)
        L = r["loads"][0]
        self.assertAlmostEqual(L["lever_mm"], 110, delta=1)
        self.assertAlmostEqual(L["moment_Nm"], 0.86, delta=0.02)

    def test_labels_view_compare_to_and_sliding_context(self):
        base = ("from build123d import *\n"
                "parts = {'brace': Box(20, 20, 20), 'jaw': Pos(40, 0, 0) * Box(10, 10, {h})}\n"
                "context = {'sash': Pos(-40, 0, 0) * Box(20, 60, 60)}\n"
                "labels = {'brace': '下板', 'jaw': '後ろ当て'}\n"
                "user_view = '運転席に座って前を見たとき'\n"
                "poses = {'閉めた': {'sash': Pos(0, 0, 0)}, '10cm開けた': {'sash': Pos(-100, 0, 0)}}\n")
        r1 = server.build_model("g-labels", base.replace("{h}", "10"))
        self.assertTrue(r1["ok"], r1)
        server.build_model("g-labels", base.replace("{h}", "14"))          # a draft
        r3 = server.build_model("g-labels", base.replace("{h}", "16"), compare_to=1)
        self.assertEqual(r3["changes"]["since_version"], 1)
        self.assertIn("brace", r3["changes"]["unchanged_parts"])
        saved = json.loads((Path(r3["folder"]) / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["changes"]["since_version"], 1)
        self.assertEqual(saved["labels"]["brace"], "下板")
        _, sheet, _, _ = server.preview("g-labels")
        self.assertTrue(Path(sheet.path).exists())

    def test_print_plate_and_assembly_steps(self):
        import zipfile
        code = ("from build123d import *\n"
                "parts = {'rail': Box(20, 10, 80), 'case': Pos(0, -20, 0) * Box(40, 20, 60)}\n"
                "context = {'wall': Pos(0, 20, 0) * Box(100, 20, 300), 'hw_bolt': Pos(0, 0, 30) * Box(4, 20, 4)}\n"
                "labels = {'rail': 'レール'}\n"
                "print_pose = {'rail': '+Y', 'case': '+Y'}\n"
                "print_settings = {'material': 'PETG', 'infill': 30, 'supports': ['case']}\n"
                "steps = [{'text': 'レールを壁に留める', 'add': ['rail', 'hw_bolt'], 'from': {'rail': (0, -40, 0)}},\n"
                "         {'text': '手元でケースを用意', 'add': ['case'], 'at': {'case': (-80, 0, 0)}},\n"
                "         {'text': 'ケースを上から差す', 'from': {'case': (0, 0, 60)}}]\n")
        r = server.build_model("g-plate", code)
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["plate"]["fits_one_bed"])
        z = zipfile.ZipFile(Path(r["folder"]) / "print_plate.3mf")
        model = z.read("3D/3dmodel.model").decode()
        self.assertIn('name="レール"', model)
        self.assertEqual(model.count("<object "), 2)
        job = server.get_print_job("g-plate")
        self.assertEqual(job["schema"], "spatialvibe.print_job/1")
        self.assertEqual(job["settings"]["infill_percent"], 30)
        by = {p_["name"]: p_ for p_ in job["parts"]}
        self.assertTrue(by["case"]["supports"])
        self.assertFalse(by["rail"]["supports"])
        self.assertEqual(by["rail"]["label"], "レール")
        self.assertTrue(Path(by["rail"]["stl_path"]).exists())
        self.assertTrue(Path(job["plate"]["path"]).exists())
        self.assertEqual(job["assembly_steps"][0], "レールを壁に留める")
        out = server.preview("g-plate")
        self.assertEqual(len(out), 5)
        self.assertTrue((Path(r["folder"]) / "sheet_build.png").exists())

    def test_bad_step_name_fails(self):
        code = ("from build123d import *\nparts = {'a': Box(10, 10, 10)}\n"
                "steps = [{'text': 'x', 'add': ['nope']}]\n")
        r = server.build_model("g-badstep", code)
        self.assertFalse(r["ok"])
        self.assertIn("nope", r["error"])

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

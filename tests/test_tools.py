"""End-to-end checks of the MCP tools and the reel validator. Run: .venv/bin/python -m unittest -v"""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# test_isolation.py may already have chosen the suite's temp home (the server module is imported once)
TMP = Path(os.environ.setdefault("SPATIALVIBE_HOME", str(Path(tempfile.mkdtemp(prefix="svmcp-")) / "home"))).parent
os.environ.setdefault("SPATIALVIBE_PUBLISH", f"dir:{TMP / 'pub'}")
os.environ.pop("SPATIALVIBE_PRINTER", None)
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


TWO = ("from build123d import *\n"
       "parts = {'plate': Pos(0, 0, 50) * Box(20, 10, 5), 'peg': Pos(40, 0, 0) * Cylinder(3, 12)}\n"
       "context = {'wall': Pos(0, 300, 0) * Box(500, 10, 500)}\n"
       "print_orientation = {'plate': (0, 90, 0)}\n")


def zip_names(path):
    import zipfile
    with zipfile.ZipFile(path) as z:
        return z.namelist()


class PrintTests(unittest.TestCase):
    def test_printer_specs(self):
        from spatialvibe_mcp import printing
        for s in ("a1mini", "A1 mini", "Bambu Lab A1 mini", "a1-mini"):
            self.assertEqual(printing.parse_printer(s)["build_volume_mm"], [180.0, 180.0, 180.0], s)
        self.assertEqual(printing.parse_printer("256x256x256")["build_volume_mm"], [256.0] * 3)
        self.assertEqual(printing.parse_printer("220 × 220 × 250 mm")["build_volume_mm"], [220.0, 220.0, 250.0])
        for bad in ("A1", "x1c", "unknown", "0x10x10", "5x200x200", "1e9x1x1", "-5x10x10", "nanxnanxnan", "10x10"):
            with self.assertRaises(ValueError, msg=bad):
                printing.parse_printer(bad)
        with self.assertRaises(ValueError):
            server.build_model("t-badpr", BOX, printer="A1")  # never silently assume a printer
        self.assertFalse((TMP / "home" / "t-badpr").exists())

    def test_fit_inside_outside_unset(self):
        code = "from build123d import *\nparts = {'ok': Box(180, 180, 180), 'big': Box(180.004, 50, 10)}\n"
        r = server.build_model("t-fit", code, printer="a1mini")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["printer"]["build_volume_mm"], [180.0] * 3)
        self.assertEqual(r["parts"]["ok"]["print"]["fit"], "fits")
        big = r["parts"]["big"]["print"]
        # rounds to 180.0 but is over: judged on the unrounded size
        self.assertEqual(big["size_mm"][0], 180.0)
        self.assertEqual(big["fit"], "exceeds")
        self.assertIn("X", big["over_mm"])
        self.assertIn("hint", big)
        self.assertEqual(big["orientation"], "unconfirmed")
        # no printer anywhere: not set, which is neither fits nor exceeds
        r = server.build_model("t-fit", code)
        self.assertIsNone(r["printer"])
        self.assertEqual({p["print"]["fit"] for p in r["parts"].values()}, {"printer_not_set"})
        # environment default is honoured
        os.environ["SPATIALVIBE_PRINTER"] = "300x300x300"
        try:
            r = server.build_model("t-fit", code)
        finally:
            del os.environ["SPATIALVIBE_PRINTER"]
        self.assertEqual(r["parts"]["big"]["print"]["fit"], "fits")

    def test_exceeds_hint_does_not_claim_impossible(self):
        from spatialvibe_mcp import printing
        f = printing.fit({"rotate_xyz_deg": None, "size_mm_exact": [20, 250, 10]}, printing.parse_printer("250x200x150"))
        self.assertEqual(f["fit"], "exceeds")
        self.assertIn("turned by 90", f["hint"])
        f = printing.fit({"rotate_xyz_deg": None, "size_mm_exact": [133, 249.75, 40]}, printing.parse_printer("a1mini"))
        self.assertEqual(f["fit"], "exceeds")
        self.assertIn("may still fit", f["hint"])

    def test_print_pose_rotated_and_grounded(self):
        import trimesh
        r = server.build_model("t-pose", TWO, printer="a1mini")
        self.assertTrue(r["ok"], r)
        self.assertNotIn("wall", r["parts"])  # context is not size-checked
        plate = r["parts"]["plate"]
        self.assertEqual(plate["print"]["orientation"], "specified")
        self.assertEqual(plate["print"]["size_mm"], [5.0, 10.0, 20.0])
        self.assertEqual(plate["bbox_mm"]["size"], [20.0, 10.0, 5.0])  # assembled pose unchanged
        vdir = Path(r["folder"])
        m = trimesh.load(vdir / "print_plate.stl")
        self.assertAlmostEqual(m.bounds[0][2], 0.0, places=4)
        self.assertTrue(all(abs(a - b) < 1e-3 for a, b in zip(m.extents, [5, 10, 20])))
        a = trimesh.load(vdir / "part_plate.stl")
        self.assertAlmostEqual(a.bounds[0][2], 47.5, places=4)
        # unrotated part is grounded too but recorded as unconfirmed
        self.assertEqual(r["parts"]["peg"]["print"]["orientation"], "unconfirmed")
        self.assertAlmostEqual(trimesh.load(vdir / "print_peg.stl").bounds[0][2], 0.0, places=4)
        # AR stays in the assembled pose and never picks up print files
        pub = server.publish_ar("t-pose", include_context=False)
        # assembled Z span: peg -6..6, plate 47.5..52.5 -> 58.5 mm tall (Y-up in USDZ)
        self.assertAlmostEqual(pub["size_m"][1], 0.0585, places=4)
        img, _ = server.preview("t-pose")

    def test_bad_orientation_metadata(self):
        for meta in ("{'nope': (0, 0, 0)}", "{'wall': (0, 0, 0)}", "{'plate': (0, 90)}",
                     "{'plate': ('90', 0, 0)}", "{'plate': (float('nan'), 0, 0)}", "[(0, 0, 0)]"):
            code = TWO.replace("{'plate': (0, 90, 0)}", meta)
            r = server.build_model("t-meta", code)
            self.assertFalse(r["ok"], meta)
            self.assertIn("print_orientation", r["error"])

    def test_bundle_contents(self):
        r = server.build_model("t-bundle", TWO, printer="a1mini")
        out = server.export_print("t-bundle", quantities={"peg": 4}, material="PETG",
                                  hardware=["M3x10 ボルト 2 本"], notes=["屋外用"], part_notes={"plate": "上面が見える面"})
        self.assertTrue(out["ok"], out)
        # no ZIP unless asked: the folder is the deliverable
        self.assertIsNone(out["zip"])
        self.assertFalse(list((TMP / "home/t-bundle/v001").glob("*.zip")))
        folder = Path(out["folder"])
        names = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_./-]+", n) for n in names), names)
        self.assertEqual(names, sorted(["stl/plate.stl", "stl/peg.stl", "step/plate.step", "step/peg.step",
                                        "source/model.py", "manifest.json", "PRINT_GUIDE_ja.txt", "AI_HANDOFF.txt"]))
        self.assertFalse(any("wall" in n or "ctx" in n for n in names))
        import trimesh  # the context mesh is not hiding inside a part file either
        self.assertLess(max(trimesh.load(folder / "stl/plate.stl").extents), 25)
        man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(man["context_included"])
        self.assertEqual(man["units"], "mm")
        parts = {p["name"]: p for p in man["parts"]}
        self.assertEqual((parts["peg"]["quantity"], parts["peg"]["quantity_confirmed"]), (4, True))
        self.assertEqual((parts["plate"]["quantity"], parts["plate"]["quantity_confirmed"]), (1, False))
        self.assertEqual(parts["plate"]["print_size_mm"], [5.0, 10.0, 20.0])
        self.assertEqual(man["size_check"], "unconfirmed")  # peg's pose was never chosen
        self.assertIn("orientation:peg", man["unconfirmed"])
        self.assertIn("quantity:plate", man["unconfirmed"])
        self.assertNotIn("material", man["unconfirmed"])
        g = (folder / "PRINT_GUIDE_ja.txt").read_text(encoding="utf-8")
        for s in ("PETG", "M3x10", "屋外用", "上面が見える面", "4 個", "個数は未確認", "印刷姿勢: 未確認",
                  "印刷できるかは確定していません"):
            self.assertIn(s, g)
        self.assertNotIn("ご自身のスライサー", g)
        self.assertIn("スライス（サポート・充填など）、印刷時間や材料量の見積り、印刷はまだしていません", g)
        self.assertEqual((folder / "source/model.py").read_text(encoding="utf-8"), TWO)
        # re-export overwrites cleanly
        self.assertTrue(server.export_print("t-bundle", material="PLA")["ok"])

    def test_handoff_return_for_ai(self):
        server.build_model("t-handoff", TWO, printer="a1mini")
        out = server.export_print("t-handoff", quantities={"peg": 4}, material="PETG", hardware=[],
                                  notes=["屋外用"])
        folder = Path(out["folder"])
        # the returned manifest is exactly the file: one source of the conditions
        self.assertEqual(out["manifest"], json.loads(Path(out["manifest_path"]).read_text(encoding="utf-8")))
        man = out["manifest"]
        self.assertEqual(man["printer"]["build_volume_mm"], [180.0] * 3)
        self.assertEqual((man["material"], man["hardware"], man["notes"]), ("PETG", [], ["屋外用"]))
        self.assertEqual(man["unconfirmed"], ["orientation:peg", "quantity:plate"])
        self.assertEqual(out["unconfirmed"], man["unconfirmed"])
        for step in ("slicing", "supports", "print time estimate", "filament estimate", "printing"):
            self.assertIn(step, man["not_done"])
        # every file reachable by absolute path, and the same files the manifest names
        for p in man["parts"]:
            paths = out["files"]["parts"][p["name"]]
            self.assertEqual(Path(paths["stl"]), folder / p["stl"])
            self.assertEqual(Path(paths["step"]), folder / p["step"])
            self.assertTrue(Path(paths["stl"]).is_file() and Path(paths["step"]).is_file())
        self.assertEqual(Path(out["files"]["source"]).read_text(encoding="utf-8"), TWO)
        self.assertEqual(Path(out["guide_path"]).parent, folder)
        # hand-off text: what another AI needs, consistent with the guide the human reads
        h = out["handoff"]
        self.assertEqual(Path(out["handoff_path"]).read_text(encoding="utf-8"), h)
        for s in (str(folder), "manifest.json", "Bambu Lab A1 mini", "PETG", "peg ×4", "plate ×1(個数未確認)",
                  "peg の印刷姿勢", "plate の個数", "スライス", "得ていない見積りは書かないでください"):
            self.assertIn(s, h)
        g = Path(out["guide_path"]).read_text(encoding="utf-8")
        for s in ("peg の印刷姿勢", "plate の個数", "PETG", "Bambu Lab A1 mini"):
            self.assertIn(s, g)
        self.assertTrue(any("does not slice or print" in s for s in out["next_steps"]))
        # nothing pretends estimates exist
        self.assertFalse(any(k in json.dumps(man) for k in ("print_time_min", "filament_g")))

    def test_zip_only_when_asked_and_never_stale(self):
        server.build_model("t-zip", TWO, printer="a1mini")
        out = server.export_print("t-zip", include_zip=True)
        z = Path(out["zip"])
        self.assertTrue(z.is_file())
        names = zip_names(z)
        root = "t-zip_v001_print/"
        self.assertTrue(all(n.startswith(root) and ".." not in n and not n.startswith("/") for n in names))
        folder = Path(out["folder"])
        self.assertEqual(sorted(n[len(root):] for n in names),
                         sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()))
        self.assertFalse(any("wall" in n or "ctx" in n for n in names))
        # re-export without a ZIP: the old one would no longer match, so it is removed
        out = server.export_print("t-zip", material="PLA")
        self.assertIsNone(out["zip"])
        self.assertFalse(z.exists())
        self.assertEqual(out["manifest"]["material"], "PLA")
        # and asking again rebuilds it from the current folder
        out = server.export_print("t-zip", material="ASA", include_zip=True)
        import zipfile
        with zipfile.ZipFile(out["zip"]) as zf:
            self.assertEqual(json.loads(zf.read(root + "manifest.json"))["material"], "ASA")

    def test_bundle_names_never_collide(self):
        # used to map both parts to stl/block__orientation-unconfirmed.stl
        code = ("from build123d import *\n"
                "parts = {'block': Box(10, 10, 10), 'block__orientation-unconfirmed': Pos(30, 0, 0) * Box(20, 5, 5)}\n"
                "print_orientation = {'block__orientation-unconfirmed': (0, 0, 0)}\n")
        server.build_model("t-collide", code, printer="a1mini")
        out = server.export_print("t-collide")
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(list((Path(out["folder"]) / "stl").iterdir())), 2)
        man = json.loads((Path(out["folder"]) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len({p["stl"] for p in man["parts"]}), 2)
        sizes = {p["name"]: p["print_size_mm"] for p in man["parts"]}
        self.assertEqual(sizes, {"block": [10.0, 10.0, 10.0], "block__orientation-unconfirmed": [20.0, 5.0, 5.0]})
        import trimesh
        for p in man["parts"]:  # each file holds its own part
            ext = trimesh.load(Path(out["folder"]) / p["stl"]).extents
            self.assertTrue(all(abs(a - b) < 1e-3 for a, b in zip(ext, p["print_size_mm"])), p)

    def test_names_case_and_newline(self):
        for parts in ("{'Block': Box(1, 1, 1), 'block': Box(2, 2, 2)}", "{'a\\n': Box(1, 1, 1)}"):
            r = server.build_model("t-names", f"from build123d import *\nparts = {parts}\n")
            self.assertFalse(r["ok"], parts)
        r = server.build_model("t-names", "from build123d import *\nparts = {'a': Box(1, 1, 1)}\n"
                               "context = {'Wall': Box(1, 1, 1), 'wall': Box(2, 2, 2)}\n")
        self.assertIn("case", r["error"])
        with self.assertRaises(ValueError):
            server.build_model("t-names\n", BOX)
        # result.json that bypassed the runner is still rejected at export time
        from spatialvibe_mcp import printing
        r = server.build_model("t-names2", BOX)
        res = json.loads((Path(r["folder"]) / "result.json").read_text(encoding="utf-8"))
        for bad in ({"block\n": res["parts"]["block"]}, {"block": res["parts"]["block"], "BLOCK": res["parts"]["block"]}):
            with self.assertRaisesRegex(ValueError, "no valid part list"):
                printing.make_bundle("t-names2", Path(r["folder"]), dict(res, parts=bad), None)

    def test_bundle_fully_checked(self):
        code = TWO.replace("{'plate': (0, 90, 0)}", "{'plate': (0, 90, 0), 'peg': (0, 0, 0)}")
        server.build_model("t-checked", code, printer="a1mini")
        out = server.export_print("t-checked", quantities={"plate": 1, "peg": 2}, material="PLA", hardware=[])
        man = json.loads((Path(out["folder"]) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(man["size_check"], "all parts fit in their print pose")
        self.assertEqual(man["unconfirmed"], [])
        self.assertIn("stl/peg.stl", [p["stl"] for p in man["parts"]])

    def test_bundle_without_printer_is_marked(self):
        server.build_model("t-nopr", TWO)
        out = server.export_print("t-nopr")
        self.assertTrue(out["ok"])
        self.assertIn("printer", out["unconfirmed"])
        self.assertEqual(out["size_check"], "unconfirmed")
        self.assertEqual({p["fit"] for p in out["parts"]}, {"printer_not_set"})
        g = (Path(out["folder"]) / "PRINT_GUIDE_ja.txt").read_text(encoding="utf-8")
        self.assertIn("未設定", g)
        self.assertNotIn("造形範囲: 入る", g)
        for k in ("material", "hardware"):
            self.assertIn(k, out["unconfirmed"])
        # a printer given at export time is used
        self.assertEqual({p["fit"] for p in server.export_print("t-nopr", printer="a1mini")["parts"]}, {"fits"})

    def test_oversize_refused(self):
        code = "from build123d import *\nparts = {'long': Box(250, 20, 10), 'ok': Box(5, 5, 5)}\n"
        server.build_model("t-over", code, printer="a1mini")
        out = server.export_print("t-over")
        self.assertFalse(out["ok"])
        self.assertEqual(out["oversize"][0]["part"], "long")
        self.assertIn("exceed", out["error"])
        self.assertFalse(list((TMP / "home/t-over/v001").glob("*_print*")))
        self.assertTrue(server.export_print("t-over", printer="300x300x300")["ok"])

    def test_failed_and_partial_builds_refused(self):
        server.build_model("t-fail", "raise ValueError('nope')")
        with self.assertRaises(ValueError):
            server.export_print("t-fail")
        # first part exports, second blows up mid-export
        code = ("from build123d import *\nclass Bad:\n    wrapped = None\n"
                "parts = {'a': Box(1, 1, 1), 'z': Bad()}\n")
        r = server.build_model("t-partial", code)
        self.assertFalse(r["ok"])
        vdir = TMP / "home/t-partial/v001"
        self.assertEqual(list(vdir.glob("part_*")) + list(vdir.glob("print_*")), [])
        for call in (lambda: server.export_print("t-partial"), lambda: server.preview("t-partial"),
                     lambda: server.publish_ar("t-partial")):
            with self.assertRaises(ValueError):
                call()

    def test_old_version_needs_rebuild(self):
        r = server.build_model("t-old", BOX)
        res = json.loads((Path(r["folder"]) / "result.json").read_text(encoding="utf-8"))
        for p in res["parts"].values():
            del p["print"]
        res.pop("printer")
        (Path(r["folder"]) / "result.json").write_text(json.dumps(res), encoding="utf-8")
        server.preview("t-old")  # old versions still preview / publish
        server.publish_ar("t-old")
        with self.assertRaisesRegex(ValueError, "Rebuild"):
            server.export_print("t-old")

    def test_export_input_bounds(self):
        server.build_model("t-bounds", TWO, printer="a1mini")
        bad = [dict(quantities={"wall": 1}), dict(quantities={"nope": 1}), dict(quantities={"peg": 0}),
               dict(quantities={"peg": 1001}), dict(quantities={"peg": True}), dict(quantities={"peg": 1.5}),
               dict(material="x" * 101), dict(hardware="M3"), dict(hardware=["x"] * 51),
               dict(notes=["x" * 501]), dict(part_notes={"wall": "x"}), dict(printer="A1")]
        for kw in bad:
            with self.assertRaises(ValueError, msg=kw):
                server.export_print("t-bounds", **kw)
        for p in ("../x", "a/b", ""):
            with self.assertRaises(ValueError):
                server.export_print(p)
        with self.assertRaises(ValueError):
            server.export_print("t-bounds", version=9)

    def test_planted_symlink_not_exported(self):
        r = server.build_model("t-link", TWO)
        vdir = Path(r["folder"])
        secret = TMP / "secret.txt"
        secret.write_text("secret")
        (vdir / "print_peg.stl").unlink()
        (vdir / "print_peg.stl").symlink_to(secret)
        with self.assertRaisesRegex(ValueError, "not a plain file"):
            server.export_print("t-link")
        # a symlink planted where the zip goes is replaced, its target untouched
        (vdir / "print_peg.stl").unlink()
        server.build_model("t-link", TWO)
        v2 = TMP / "home/t-link/v002"
        zp = v2 / "t-link_v002_print.zip"
        zp.symlink_to(secret)
        self.assertTrue(server.export_print("t-link", include_zip=True)["ok"])
        self.assertEqual(secret.read_text(), "secret")
        self.assertFalse(zp.is_symlink())
        # without a ZIP the planted link is removed, again without touching its target
        zp.unlink()
        zp.symlink_to(secret)
        self.assertTrue(server.export_print("t-link")["ok"])
        self.assertFalse(zp.exists() or zp.is_symlink())
        self.assertEqual(secret.read_text(), "secret")

    def test_example_model(self):
        code = (ROOT / "examples/aio_mount/model.py").read_text(encoding="utf-8")
        r = server.build_model("t-example", code, printer="a1mini")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["parts"]["tray"]["bbox_mm"]["size"], [133.0, 249.75, 40.0])
        self.assertEqual(r["parts"]["tray"]["print"]["fit"], "exceeds")
        self.assertEqual(r["parts"]["tray"]["print"]["orientation"], "unconfirmed")
        cap = r["parts"]["clamp_cap_L"]["print"]
        self.assertEqual((cap["orientation"], cap["fit"]), ("specified", "fits"))
        self.assertEqual(r["parts"]["clamp_cap_L"]["bbox_mm"]["size"], [20.0, 51.5, 18.75])
        self.assertFalse(server.export_print("t-example")["ok"])


class DoctorTests(unittest.TestCase):
    def test_desktop_config(self):
        from spatialvibe_mcp import doctor
        cfg = doctor.desktop_config()
        s = cfg["mcpServers"]["spatialvibe"]
        self.assertTrue(Path(s["command"]).is_absolute())
        self.assertTrue(s["command"].endswith(".venv/bin/python"))
        self.assertEqual(s["args"], ["-m", "spatialvibe_mcp"])
        self.assertEqual(s["env"]["PYTHONPATH"], str(ROOT))
        self.assertNotIn("SPATIALVIBE_PRINTER", s["env"])
        self.assertEqual(doctor.desktop_config("a1mini")["mcpServers"]["spatialvibe"]["env"]["SPATIALVIBE_PRINTER"],
                         "a1mini")
        with self.assertRaises(ValueError):
            doctor.desktop_config("A1")
        self.assertIn("claude mcp add", doctor.claude_code_command())

    def _data_check(self, home):
        from spatialvibe_mcp import doctor
        old = os.environ.get("SPATIALVIBE_HOME")
        os.environ["SPATIALVIBE_HOME"] = str(home)
        try:
            return next(c for c in doctor.checks(smoke=False) if c[1] == "data folder")
        finally:
            os.environ["SPATIALVIBE_HOME"] = old

    def test_data_folder_first_install(self):
        base = Path(tempfile.mkdtemp(prefix="svdoc-"))
        ok, _, detail = self._data_check(base / "new/data/mcp_projects")  # no parents yet
        self.assertTrue(ok, detail)
        self.assertIn("not created yet", detail)
        self.assertFalse((base / "new").exists())  # the check creates nothing
        (base / "have").mkdir()
        self.assertTrue(self._data_check(base / "have")[0])
        (base / "file").write_text("x")  # a file in the middle of the path
        ok, _, detail = self._data_check(base / "file/data/mcp_projects")
        self.assertFalse(ok)
        self.assertIn("not a folder", detail)
        self.assertFalse(self._data_check(base / "file")[0])
        ro = base / "ro"
        ro.mkdir()
        ro.chmod(0o500)
        try:
            if not os.access(ro, os.W_OK):  # skip when running as root
                ok, _, detail = self._data_check(ro / "data/mcp_projects")
                self.assertFalse(ok)
                self.assertIn("not writable", detail)
        finally:
            ro.chmod(0o700)


class StdioTests(unittest.TestCase):
    """Over a real MCP stdio connection the tools answer and the server's own error text reaches
    the client (the API that Claude sees is unchanged by the isolation work)."""

    def test_tools_and_error_text_over_stdio(self):
        import anyio
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        env = dict(os.environ, PYTHONPATH=str(ROOT), SPATIALVIBE_HOME=str(TMP / "stdio-home"))
        params = StdioServerParameters(command=sys.executable, args=["-m", "spatialvibe_mcp"], env=env, cwd=str(ROOT))

        async def go():
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    tools = sorted(t.name for t in (await s.list_tools()).tools)
                    missing = await s.call_tool("preview", {"project": "nothing-here"})
                    bad = await s.call_tool("build_model", {"project": "../x", "code": "x"})
                    built = await s.call_tool("build_model", {"project": "stdio", "code": BOX})
                    listed = await s.call_tool("list_projects", {})
                    return tools, missing, bad, built, listed

        tools, missing, bad, built, listed = anyio.run(go)
        self.assertEqual(tools, ["build_model", "export_print", "get_code", "list_projects", "preview", "publish_ar"])
        self.assertTrue(missing.is_error)
        self.assertIn("no versions yet", missing.content[0].text)
        self.assertTrue(bad.is_error)
        self.assertIn("project must match", bad.content[0].text)
        self.assertFalse(built.is_error, built)
        self.assertTrue(json.loads(built.content[0].text)["ok"])
        self.assertFalse(listed.is_error)


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

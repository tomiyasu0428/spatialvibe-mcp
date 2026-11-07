"""Printer size checks, print_orientation and the export_print bundle."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

if "spatialvibe_mcp.server" not in sys.modules:  # run alone: never touch real data or iCloud
    _TMP = Path(tempfile.mkdtemp(prefix="svprint-"))
    os.environ["SPATIALVIBE_HOME"] = str(_TMP / "home")
    os.environ["SPATIALVIBE_PUBLISH"] = f"dir:{_TMP / 'pub'}"
os.environ.pop("SPATIALVIBE_PRINTER", None)

from spatialvibe_mcp import printing, server  # noqa: E402

HOME = server.HOME
BOX = "from build123d import *\nparts = {'block': Box(20, 10, 5)}\ncontext = {'pipe': Pos(0, 30, 0) * Cylinder(3, 40)}\n"
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
        for s in ("a1mini", "A1 mini", "Bambu Lab A1 mini", "a1-mini"):
            self.assertEqual(printing.parse_printer(s)["build_volume_mm"], [180.0, 180.0, 180.0], s)
        self.assertEqual(printing.parse_printer("256x256x256")["build_volume_mm"], [256.0] * 3)
        self.assertEqual(printing.parse_printer("220 × 220 × 250 mm")["build_volume_mm"], [220.0, 220.0, 250.0])
        for bad in ("A1", "x1c", "unknown", "0x10x10", "5x200x200", "1e9x1x1", "-5x10x10", "nanxnanxnan", "10x10"):
            with self.assertRaises(ValueError, msg=bad):
                printing.parse_printer(bad)
        with self.assertRaises(ValueError):
            server.build_model("t-badpr", BOX, printer="A1")  # never silently assume a printer
        self.assertFalse((HOME / "t-badpr").exists())

    def test_fit_inside_outside_unset(self):
        code = "from build123d import *\nparts = {'ok': Box(180, 180, 180), 'big': Box(180.004, 50, 10)}\n"
        r = server.build_model("t-fit", code, printer="a1mini")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["printer"]["build_volume_mm"], [180.0] * 3)
        self.assertEqual(r["parts"]["ok"]["print"]["fit"], "fits")
        big = r["parts"]["big"]["print"]
        self.assertEqual(big["size_mm"][0], 180.0)  # rounds to 180.0 but is over: judged unrounded
        self.assertEqual(big["fit"], "exceeds")
        self.assertIn("X", big["over_mm"])
        self.assertIn("hint", big)
        self.assertEqual(big["orientation"], "unconfirmed")
        r = server.build_model("t-fit", code)
        self.assertIsNone(r["printer"])
        self.assertEqual({p["print"]["fit"] for p in r["parts"].values()}, {"printer_not_set"})
        self.assertIn("printer_note", r)
        os.environ["SPATIALVIBE_PRINTER"] = "300x300x300"
        try:
            r = server.build_model("t-fit", code)
        finally:
            del os.environ["SPATIALVIBE_PRINTER"]
        self.assertEqual(r["parts"]["big"]["print"]["fit"], "fits")

    def test_exceeds_hint_does_not_claim_impossible(self):
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
        self.assertAlmostEqual(trimesh.load(vdir / "part_plate.stl").bounds[0][2], 47.5, places=4)
        self.assertEqual(r["parts"]["peg"]["print"]["orientation"], "unconfirmed")
        self.assertAlmostEqual(trimesh.load(vdir / "print_peg.stl").bounds[0][2], 0.0, places=4)
        pub = server.publish_ar("t-pose", include_context=False)  # AR stays in the assembled pose
        self.assertAlmostEqual(pub["size_m"][1], 0.0585, places=4)  # peg -6..6, plate 47.5..52.5 (Y-up)
        server.preview("t-pose")

    def test_print_pose_face_is_a_specified_orientation(self):
        code = "from build123d import *\nparts = {'bar': Box(40, 10, 5)}\nprint_pose = {'bar': '-X'}\n"
        r = server.build_model("t-face", code, printer="a1mini")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["parts"]["bar"]["print"]["orientation"], "specified")
        self.assertEqual(sorted(r["parts"]["bar"]["print"]["size_mm"]), [5.0, 10.0, 40.0])
        self.assertEqual(r["parts"]["bar"]["print_down"], "-X")
        both = code + "print_orientation = {'bar': (0, 90, 0)}\n"
        self.assertFalse(server.build_model("t-face", both)["ok"])

    def test_bad_orientation_metadata(self):
        for meta in ("{'nope': (0, 0, 0)}", "{'wall': (0, 0, 0)}", "{'plate': (0, 90)}",
                     "{'plate': ('90', 0, 0)}", "{'plate': (float('nan'), 0, 0)}", "[(0, 0, 0)]"):
            r = server.build_model("t-meta", TWO.replace("{'plate': (0, 90, 0)}", meta))
            self.assertFalse(r["ok"], meta)
            self.assertIn("print_orientation", r["error"])

    def test_bundle_contents(self):
        server.build_model("t-bundle", TWO, printer="a1mini")
        out = server.export_print("t-bundle", quantities={"peg": 4}, material="PETG",
                                  hardware=["M3x10 ボルト 2 本"], notes=["屋外用"], part_notes={"plate": "上面が見える面"})
        self.assertTrue(out["ok"], out)
        self.assertIsNone(out["zip"])  # no ZIP unless asked: the folder is the deliverable
        folder = Path(out["folder"])
        self.assertFalse(list(folder.parent.glob("*.zip")))
        names = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_./-]+", n) for n in names), names)
        self.assertEqual(names, sorted(["stl/plate.stl", "stl/peg.stl", "step/plate.step", "step/peg.step",
                                        "source/model.py", "manifest.json", "PRINT_GUIDE_ja.txt", "AI_HANDOFF.txt"]))
        import trimesh  # the context mesh is not hiding inside a part file either
        self.assertLess(max(trimesh.load(folder / "stl/plate.stl").extents), 25)
        man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(man["context_included"])
        parts = {p["name"]: p for p in man["parts"]}
        self.assertEqual((parts["peg"]["quantity"], parts["peg"]["quantity_confirmed"]), (4, True))
        self.assertEqual((parts["plate"]["quantity"], parts["plate"]["quantity_confirmed"]), (1, False))
        self.assertEqual(parts["plate"]["print_size_mm"], [5.0, 10.0, 20.0])
        self.assertEqual(man["size_check"], "unconfirmed")  # peg's pose was never chosen
        self.assertIn("orientation:peg", man["unconfirmed"])
        g = (folder / "PRINT_GUIDE_ja.txt").read_text(encoding="utf-8")
        for s in ("PETG", "M3x10", "屋外用", "上面が見える面", "4 個", "個数は未確認", "印刷姿勢: 未確認",
                  "印刷できるかは確定していません"):
            self.assertIn(s, g)
        self.assertEqual((folder / "source/model.py").read_text(encoding="utf-8"), TWO)
        self.assertTrue(server.export_print("t-bundle", material="PLA")["ok"])  # re-export replaces cleanly

    def test_handoff_return_for_ai(self):
        server.build_model("t-handoff", TWO, printer="a1mini")
        out = server.export_print("t-handoff", quantities={"peg": 4}, material="PETG", hardware=[], notes=["屋外用"])
        folder = Path(out["folder"])
        self.assertEqual(out["manifest"], json.loads(Path(out["manifest_path"]).read_text(encoding="utf-8")))
        man = out["manifest"]
        self.assertEqual(man["unconfirmed"], ["orientation:peg", "quantity:plate"])
        for step in ("slicing", "supports", "print time estimate", "filament estimate", "printing"):
            self.assertIn(step, man["not_done"])
        for p in man["parts"]:
            paths = out["files"]["parts"][p["name"]]
            self.assertEqual(Path(paths["stl"]), folder / p["stl"])
            self.assertTrue(Path(paths["stl"]).is_file() and Path(paths["step"]).is_file())
        self.assertEqual(Path(out["handoff_path"]).read_text(encoding="utf-8"), out["handoff"])
        self.assertTrue(any("does not slice or print" in s for s in out["next_steps"]))

    def test_zip_only_when_asked_and_never_stale(self):
        server.build_model("t-zip", TWO, printer="a1mini")
        out = server.export_print("t-zip", include_zip=True)
        z = Path(out["zip"])
        names = zip_names(z)
        root = f"t-zip_{Path(out['folder']).parent.name}_print/"
        self.assertTrue(all(n.startswith(root) and ".." not in n and not n.startswith("/") for n in names))
        self.assertFalse(any("wall" in n or "ctx" in n for n in names))
        out = server.export_print("t-zip", material="PLA")  # an old ZIP would no longer match: removed
        self.assertIsNone(out["zip"])
        self.assertFalse(z.exists())

    def test_version_built_by_an_older_server(self):
        """Older servers stored per-part bbox but no overall size: export, preview and AR still work,
        with real dimensions, and the user's result.json is never rewritten."""
        import hashlib
        r = server.build_model("t-legacy", TWO, printer="a1mini")
        vdir = Path(r["folder"])
        full = json.loads((vdir / "result.json").read_text(encoding="utf-8"))
        legacy = {"ok": True, "interference": full["interference"], "printer": full["printer"],
                  "parts": {n: {k: p[k] for k in ("valid", "solids", "volume_cm3", "bbox_mm", "print")}
                            for n, p in full["parts"].items()},
                  "context": {n: {"bbox_mm": c["bbox_mm"]} for n, c in full["context"].items()}}
        (vdir / "result.json").write_text(json.dumps(legacy, ensure_ascii=False, indent=1), encoding="utf-8")
        (vdir / "print_job.json").unlink()
        before = hashlib.sha256((vdir / "result.json").read_bytes()).hexdigest()
        server.preview("t-legacy")
        pub = server.publish_ar("t-legacy", include_context=False)
        # plate x -10..10, z 47.5..52.5; peg x 37..43, z -6..6 -> 53 x 10 x 58.5 mm
        self.assertEqual(pub["parts_size_m"], {"x_width": 0.053, "y_depth": 0.01, "z_height": 0.0585})
        self.assertTrue(server.export_print("t-legacy")["ok"])
        self.assertEqual(server.get_print_job("t-legacy")["parts"][0]["name"], "plate")
        self.assertEqual(hashlib.sha256((vdir / "result.json").read_bytes()).hexdigest(), before)
        self.assertIsNone(server._overall_size({"a": {"bbox_mm": {"min": [0, 0, float("nan")], "max": [1, 1, 1]}}}))
        self.assertIsNone(server._overall_size({"a": {"bbox_mm": {"min": [2, 0, 0], "max": [1, 1, 1]}}}))

    def test_bundle_fully_checked_and_without_printer(self):
        code = TWO.replace("{'plate': (0, 90, 0)}", "{'plate': (0, 90, 0), 'peg': (0, 0, 0)}")
        server.build_model("t-checked", code, printer="a1mini")
        out = server.export_print("t-checked", quantities={"plate": 1, "peg": 2}, material="PLA", hardware=[])
        man = json.loads((Path(out["folder"]) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(man["size_check"], "all parts fit in their print pose")
        self.assertEqual(man["unconfirmed"], [])
        server.build_model("t-nopr", TWO)
        out = server.export_print("t-nopr")
        self.assertTrue(out["ok"])
        self.assertIn("printer", out["unconfirmed"])
        self.assertEqual({p["fit"] for p in out["parts"]}, {"printer_not_set"})
        self.assertEqual({p["fit"] for p in server.export_print("t-nopr", printer="a1mini")["parts"]}, {"fits"})

    def test_oversize_refused(self):
        code = "from build123d import *\nparts = {'long': Box(250, 20, 10), 'ok': Box(5, 5, 5)}\n"
        server.build_model("t-over", code, printer="a1mini")
        out = server.export_print("t-over")
        self.assertFalse(out["ok"])
        self.assertEqual(out["oversize"][0]["part"], "long")
        self.assertFalse(list((HOME / "t-over/v001").glob("*_print*")))
        self.assertTrue(server.export_print("t-over", printer="300x300x300")["ok"])

    def test_failed_old_and_bad_inputs_refused(self):
        server.build_model("t-fail", "raise ValueError('nope')")
        with self.assertRaises(ValueError):
            server.export_print("t-fail")
        r = server.build_model("t-old", BOX)
        res = json.loads((Path(r["folder"]) / "result.json").read_text(encoding="utf-8"))
        for p in res["parts"].values():
            del p["print"]
        res.pop("printer")
        (Path(r["folder"]) / "result.json").write_text(json.dumps(res), encoding="utf-8")
        server.publish_ar("t-old")  # older versions still publish
        with self.assertRaisesRegex(ValueError, "Rebuild"):
            server.export_print("t-old")
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
        r = server.build_model("t-names2", BOX)
        res = json.loads((Path(r["folder"]) / "result.json").read_text(encoding="utf-8"))
        for parts in ({"block\n": res["parts"]["block"]}, {"block": res["parts"]["block"], "BLOCK": res["parts"]["block"]}):
            with self.assertRaisesRegex(ValueError, "no valid part list"):
                printing.make_bundle("t-names2", Path(r["folder"]), dict(res, parts=parts), None)

    def test_planted_symlink_not_exported(self):
        r = server.build_model("t-link", TWO)
        vdir = Path(r["folder"])
        secret = HOME.parent / "print-secret.txt"
        secret.write_text("secret")
        (vdir / "print_peg.stl").unlink()
        (vdir / "print_peg.stl").symlink_to(secret)
        with self.assertRaisesRegex(ValueError, "not a plain file"):
            server.export_print("t-link")
        r2 = server.build_model("t-link", TWO)
        v2 = Path(r2["folder"])
        (v2 / f"t-link_{v2.name}_print.zip").symlink_to(secret)
        self.assertTrue(server.export_print("t-link")["ok"])
        self.assertEqual(secret.read_text(), "secret")
        self.assertFalse((v2 / f"t-link_{v2.name}_print.zip").is_symlink())


if __name__ == "__main__":
    unittest.main()

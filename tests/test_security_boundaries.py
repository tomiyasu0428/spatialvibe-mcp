"""Exercise the generated-code boundary with synthetic local data only."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from spatialvibe_mcp import server
from spatialvibe_mcp._ar_export import export_snapshot


class ArtifactBoundaryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patch = mock.patch.object(server, "HOME", self.root / "projects")
        patch.start()
        self.addCleanup(patch.stop)
        server.HOME.mkdir()
        self.sentinel = self.root / "private-marker"
        self.sentinel.write_text("test-only marker")

    def test_project_and_version_links_are_not_traversed(self):
        (server.HOME / "alias").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(server.SpatialVibeError):
            server.get_code("alias", 1)
        p = server.HOME / "legacy"
        p.mkdir()
        (p / "v001").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(server.SpatialVibeError):
            server.get_code("legacy", 1)

    def test_hardlinked_mesh_is_not_exported(self):
        v = server.HOME / "legacy"
        v.mkdir()
        os.link(self.sentinel, v / "part_x.stl")
        with self.assertRaises(ValueError):
            export_snapshot(v)

    def test_generated_runtime_files_and_fake_plate_are_discarded(self):
        code = """
from build123d import Box
from pathlib import Path
import os
root = Path(__file__).parent
(root / 'sitecustomize.py').write_text("raise RuntimeError('poisoned')")
(root / '_build' / 'print_plate.3mf').write_bytes(b'arbitrary slicer commands')
try:
    pid = os.fork()
except (PermissionError, BlockingIOError):  # sandbox or RLIMIT_NPROC vetoed the fork
    pass
else:
    if pid == 0:
        os._exit(0)
    raise ValueError('fork unexpectedly succeeded')
parts = {'block': Box(10, 10, 5)}
"""
        built = server.build_model("test-plate", code)
        self.assertTrue(built["ok"], built)
        v = Path(built["folder"])
        self.assertFalse((v / "sitecustomize.py").exists())
        with zipfile.ZipFile(v / "print_plate.3mf") as z:
            self.assertEqual(set(z.namelist()), {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"})
        # An old or tampered job cannot supply an arbitrary external path or slicer project.
        (v / "print_plate.3mf").write_bytes(b"untrusted old plate")
        (v / "print_job.json").write_text(json.dumps({"parts": [{"stl": str(self.sentinel)}]}))
        job = server.get_print_job("test-plate")
        self.assertEqual(Path(job["parts"][0]["stl_path"]).parent, v)
        self.assertTrue(zipfile.is_zipfile(job["plate"]["path"]))
        # A legacy symlink at a preview output is replaced, not written through or returned.
        (v / "preview.png").symlink_to(self.sentinel)
        server.preview("test-plate")
        self.assertFalse((v / "preview.png").is_symlink())
        self.assertEqual(self.sentinel.read_text(), "test-only marker")

    def test_preview_titles_use_the_real_project_and_version(self):
        # Sheets are drawn in a scratch copy; its folder name must not become the title.
        vdir = server.HOME / "titled" / "v003"
        vdir.mkdir(parents=True)
        calls = []

        def fake_run(scratch, package_root, module, args, timeout):
            calls.append((module, [str(a) for a in args]))
            return mock.Mock(returncode=1, stderr="stop")

        with mock.patch.object(server, "_built_version_dir", return_value=vdir), \
                mock.patch.object(server, "_read_result", return_value={}), \
                mock.patch.object(server, "run_isolated", side_effect=fake_run):
            with self.assertRaises(server.SpatialVibeError):
                server.preview("titled", 3)
        self.assertEqual(calls[0][1][1:], ["titled", "v003"])

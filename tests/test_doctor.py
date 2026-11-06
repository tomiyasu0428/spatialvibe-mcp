"""doctor: prints the Claude connection settings and checks the install without editing anything."""
import os
import tempfile
import unittest
from pathlib import Path

from spatialvibe_mcp import doctor

ROOT = Path(__file__).resolve().parent.parent


class DoctorTests(unittest.TestCase):
    def test_desktop_config(self):
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
        old = os.environ.get("SPATIALVIBE_HOME")
        os.environ["SPATIALVIBE_HOME"] = str(home)
        try:
            return next(c for c in doctor.checks(smoke=False) if c[1] == "data folder")
        finally:
            if old is None:
                del os.environ["SPATIALVIBE_HOME"]
            else:
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

    def test_ar_target_names_cloudflare(self):
        old = os.environ.get("SPATIALVIBE_PUBLISH")
        os.environ["SPATIALVIBE_PUBLISH"] = "cloudflare"
        try:
            ok, _, detail = next(c for c in doctor.checks(smoke=False) if c[1] == "AR target")
        finally:
            if old is None:
                del os.environ["SPATIALVIBE_PUBLISH"]
            else:
                os.environ["SPATIALVIBE_PUBLISH"] = old
        self.assertIsNone(ok)
        self.assertIn("Cloudflare", detail)

    def test_smoke_build(self):
        ok, _, detail = doctor._smoke()
        self.assertTrue(ok, detail)
        self.assertIn("20x10x5", detail)


if __name__ == "__main__":
    unittest.main()

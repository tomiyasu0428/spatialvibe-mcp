"""Launcher for Cloudflare publish mode: config hygiene and a minimal server environment."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ar_mcp_launch", ROOT / "tools" / "ar_mcp_launch.py")
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)

GOOD = {"origin": "https://spatialvibe-ar.example.workers.dev", "keychain_service": "spatialvibe-ar-upload",
        "home": "/tmp/spatialvibe-projects", "bed": "256,256,256", "printer": "a1mini", "timeout": 180, "ttl": 3600}


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"

    def write(self, value, mode=0o600):
        self.path.write_text(json.dumps(value))
        os.chmod(self.path, mode)
        return self.path

    def test_valid_private_config_builds_only_the_allowed_environment(self):
        config = launch.load_config(self.write(GOOD))
        with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "admin-secret",
                                         "SPATIALVIBE_AR_UPLOAD_TOKEN": "U" * 43, "OTHER": "x"}):
            env = launch.server_environment(config)
        self.assertEqual(set(env), {"HOME", "PATH", "LANG", "PYTHONPATH", "SPATIALVIBE_PUBLISH",
                                    "SPATIALVIBE_AR_ORIGIN", "SPATIALVIBE_AR_KEYCHAIN_SERVICE",
                                    "SPATIALVIBE_HOME", "SPATIALVIBE_BED", "SPATIALVIBE_TIMEOUT",
                                    "SPATIALVIBE_AR_TTL", "SPATIALVIBE_PRINTER"})
        self.assertEqual(env["SPATIALVIBE_PUBLISH"], "cloudflare")
        self.assertEqual(env["PATH"], "/usr/bin:/bin")
        self.assertNotIn("admin-secret", json.dumps(env))

    def test_config_must_be_private_regular_and_well_formed(self):
        with self.assertRaises(launch.LaunchError):
            launch.load_config(self.write(GOOD, mode=0o644))
        link = Path(self.tmp.name) / "link.json"
        link.symlink_to(self.write(GOOD))
        with self.assertRaises(launch.LaunchError):
            launch.load_config(link)
        for bad in [{**GOOD, "token": "x"}, {"origin": GOOD["origin"]},
                    {**GOOD, "origin": "https://spatialvibe-ar.replace-subdomain.workers.dev"},
                    {**GOOD, "origin": "https://user@ar.example.test"}, {**GOOD, "origin": "https://localhost"},
                    {**GOOD, "origin": "http://insecure.example"}, {**GOOD, "origin": GOOD["origin"] + "/path"},
                    {**GOOD, "keychain_service": "bad service"}, {**GOOD, "home": "relative/path"},
                    {**GOOD, "ttl": "3600"}]:
            with self.subTest(bad=bad), self.assertRaises(launch.LaunchError):
                launch.load_config(self.write(bad))

    def test_main_execs_the_same_python_as_the_mcp_module(self):
        self.write(GOOD)
        with mock.patch.object(launch.os, "execve") as execve, mock.patch.object(launch.os, "chdir"):
            launch.main([str(self.path)])
        exe, argv, env = execve.call_args.args
        self.assertEqual(exe, sys.executable)
        self.assertEqual(argv, [sys.executable, "-m", "spatialvibe_mcp"])
        self.assertEqual(env["SPATIALVIBE_AR_KEYCHAIN_SERVICE"], "spatialvibe-ar-upload")

    def test_refusal_message_never_contains_config_values(self):
        with self.assertRaises(SystemExit) as caught:
            launch.main([str(self.write({**GOOD, "origin": "https://private-host.example.test/x"}, 0o600))])
        self.assertNotIn("private-host", str(caught.exception))

    def test_default_config_lies_outside_the_generated_code_sandbox_roots(self):
        # Sandbox read roots are the venv, the base Python and <repo>/spatialvibe_mcp only.
        self.assertEqual(launch.DEFAULT_CONFIG.parent, ROOT)
        self.assertNotIn(ROOT / "spatialvibe_mcp", launch.DEFAULT_CONFIG.parents)


if __name__ == "__main__":
    unittest.main()

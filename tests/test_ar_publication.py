"""Independent-copy integration tests; all credentials and models are synthetic."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import base64
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import shutil
import tempfile
import unittest
from unittest import mock
from urllib import error

import trimesh

# unittest discovers this module before test_tools. Establish a fresh suite-wide
# destination before importing server so later test module imports cannot fall
# back to a real iCloud destination or reuse project versions from a previous run.
SUITE_TEMP = tempfile.TemporaryDirectory(prefix="spatialvibe-ar-suite-")
os.environ["SPATIALVIBE_HOME"] = str(Path(SUITE_TEMP.name) / "projects")
os.environ["SPATIALVIBE_PUBLISH"] = "dir:" + str(Path(SUITE_TEMP.name) / "published")

from spatialvibe_mcp import server
from spatialvibe_mcp import _ar_publish as client

ORIGIN = "https://ar.example.test"
TOKEN = "T" * 43
META = {"parts_size_m": {"x_width": .1, "y_depth": .05, "z_height": .01},
        "scene_size_m": {"x_width": .1, "y_depth": .05, "z_height": .01},
        "include_context": False, "ar_floor_mm": None}
CONFIG = client.Settings(ORIGIN, TOKEN, 60, 10, 8 * 1024 * 1024)


class Response(io.BytesIO):
    status = 201


class Opener:
    def __init__(self, failures=(), result=None):
        self.failures = list(failures)
        self.result = result
        self.requests = []

    def open(self, req, timeout):
        self.requests.append(req)
        if self.failures:
            raise self.failures.pop(0)
        metadata = json.loads(req.get_header("X-ar-metadata"))
        result = {"url": ORIGIN + "/ar/" + "A" * 86, "expires_at": 1060,
                  "sha256": hashlib.sha256(req.data).hexdigest(), **metadata}
        return Response(json.dumps(self.result if self.result is not None else result).encode())


class ClientTests(unittest.TestCase):
    def test_explicit_keychain_service_is_read_only_by_parent_settings(self):
        with mock.patch.dict(os.environ, {"SPATIALVIBE_AR_ORIGIN": ORIGIN,
                                         "SPATIALVIBE_AR_KEYCHAIN_SERVICE": "spatialvibe-ar:example:upload"}, clear=True), \
             mock.patch.object(client, "read_upload_token", return_value=TOKEN) as read:
            result = client.settings()
        read.assert_called_once_with("spatialvibe-ar:example:upload")
        self.assertEqual(result.token, TOKEN)
        self.assertNotIn(TOKEN, repr(result))

    def test_request_contract_and_fixed_identity_during_retry(self):
        opener = Opener([error.URLError("synthetic failure " + TOKEN)])
        result = client.publish(b"synthetic-usdz", META, CONFIG, opener=opener, now=lambda: 1000)
        self.assertEqual(result["parts_size_m"], META["parts_size_m"])
        self.assertEqual(len(opener.requests), 2)
        one, two = opener.requests
        self.assertEqual(one.get_header("Idempotency-key"), two.get_header("Idempotency-key"))
        self.assertEqual(one.data, two.data)
        self.assertEqual(one.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(one.full_url, ORIGIN + "/api/publications")

    def test_request_sends_honest_application_user_agent_not_urllib_default(self):
        # Cloudflare's edge answers urllib's default agent with 403 (error 1010) before the Worker.
        opener = client._opener()
        recorder = Opener()
        client.publish(b"synthetic-usdz", META, CONFIG, opener=recorder, now=lambda: 1000)
        req = recorder.requests[0]
        self.assertEqual(req.get_header("User-agent"), client.USER_AGENT)
        self.assertTrue(client.USER_AGENT.startswith("SpatialVibe-"))
        self.assertNotIn("Mozilla", client.USER_AGENT)
        # The request-level header must win over the opener's Python-urllib default.
        self.assertTrue(any(name == "User-agent" for name, _ in opener.addheaders))
        self.assertTrue(req.has_header("User-agent"))

    def test_worker_503_retries_same_identity(self):
        exc = error.HTTPError(ORIGIN, 503, "synthetic", {}, None)
        opener = Opener([exc])
        client.publish(b"data", META, CONFIG, opener=opener, now=lambda: 1000)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(opener.requests[0].headers, opener.requests[1].headers)

    def test_redirect_auth_rejection_and_timeout_are_sanitized(self):
        for exc in [error.HTTPError(ORIGIN, 302, TOKEN, {}, None),
                    error.HTTPError(ORIGIN, 401, TOKEN, {}, None), error.URLError(TOKEN)]:
            opener = Opener([exc, exc])
            with self.assertRaises(client.PublicationError) as failure:
                client.publish(b"data", META, CONFIG, opener=opener, now=lambda: 1000)
            self.assertNotIn(TOKEN, str(failure.exception))
            self.assertNotIn(ORIGIN, str(failure.exception))

    def test_response_must_match_origin_hash_metadata_and_expiry(self):
        valid = {"url": ORIGIN + "/ar/" + "A" * 86, "expires_at": 1060,
                 "sha256": hashlib.sha256(b"data").hexdigest(), **META}
        for extra in [{"url": "https://evil.test/ar/" + "A" * 86},
                      {"expires_at": 999}, {"expires_at": 999999}, {"sha256": "wrong"},
                      {"include_context": True}, {"unexpected": "private"}]:
            with self.assertRaises(client.PublicationError):
                client.publish(b"data", META, CONFIG, opener=Opener(result={**valid, **extra}), now=lambda: 1000)

    def test_settings_reject_unsafe_origin_invalid_token_and_outside_ttl(self):
        base = {"SPATIALVIBE_AR_ORIGIN": ORIGIN, "SPATIALVIBE_AR_UPLOAD_TOKEN": TOKEN}
        for extra in [{"SPATIALVIBE_AR_ORIGIN": "http://ar.example.test"},
                      {"SPATIALVIBE_AR_ORIGIN": "https://user@ar.example.test"},
                      {"SPATIALVIBE_AR_ORIGIN": "https://ar.example.test:8443"},
                      {"SPATIALVIBE_AR_ORIGIN": "https://ar.example.test/path"},
                      {"SPATIALVIBE_AR_UPLOAD_TOKEN": "bad"}, {"SPATIALVIBE_AR_TTL": "1"}]:
            with mock.patch.dict(os.environ, {**base, **extra}, clear=True):
                with self.assertRaises(client.PublicationError) as failure:
                    client.settings()
                self.assertNotIn(TOKEN, str(failure.exception))
        self.assertNotIn(TOKEN, repr(CONFIG))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ar-integration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "projects"
        self.version = self.home / "calibration" / "v001"
        self.version.mkdir(parents=True)
        trimesh.creation.box([100, 50, 10]).export(self.version / "part_block.stl")
        trimesh.creation.box([200, 150, 100]).export(self.version / "ctx_surroundings.stl")
        (self.version / "result.json").write_text(json.dumps({"ok": True, "parts_size_mm": [100, 50, 10],
                                                           "ar_floor_z": -1100}))
        self.patch = mock.patch.object(server, "HOME", self.home)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def mock_publish(self, body, metadata, config):
        return {"url": ORIGIN + "/ar/" + "A" * 86, "sha256": hashlib.sha256(body).hexdigest(),
                "expires_at": 2000000060, **metadata}

    def test_cloudflare_preserves_public_metadata_and_placement(self):
        with mock.patch.object(server, "PUBLISH", "cloudflare"), \
             mock.patch.object(server, "cloud_settings", return_value=CONFIG), \
             mock.patch.object(server, "cloud_publish", side_effect=self.mock_publish) as upload:
            result = server.publish_ar("calibration")
        self.assertEqual(result["parts_size_m"], META["parts_size_m"])
        self.assertEqual(result["scene_size_m"], {"x_width": .2, "y_depth": .15, "z_height": .1})
        self.assertTrue(result["include_context"])
        self.assertEqual(result["ar_floor_mm"], -1100)
        self.assertIn("110 cm", result["how_to_open"])
        self.assertIn("未検証", result["how_to_open"])
        self.assertEqual(result["published"], ORIGIN + "/ar/" + "A" * 86)
        body, metadata, _ = upload.call_args.args
        self.assertEqual(result["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(metadata["parts_size_m"], META["parts_size_m"])
        self.assertNotIn("project", metadata)
        self.assertNotIn(str(self.root), json.dumps(metadata))

    def test_cloudflare_can_also_keep_a_local_copy(self):
        keep = self.root / "keep"
        with mock.patch.object(server, "PUBLISH", "cloudflare"), \
             mock.patch.object(server, "KEEP", "dir:" + str(keep)), \
             mock.patch.object(server, "cloud_settings", return_value=CONFIG), \
             mock.patch.object(server, "cloud_publish", side_effect=self.mock_publish) as upload:
            result = server.publish_ar("calibration")
        kept = keep / "calibration_v001.usdz"
        self.assertEqual(result["kept"], str(kept))
        self.assertEqual(result["published"], ORIGIN + "/ar/" + "A" * 86)   # the link is still the main result
        self.assertEqual(kept.read_bytes(), bytes(upload.call_args.args[0]))  # same bytes as uploaded
        self.assertIn("keep/", result["how_to_open"])
        with mock.patch.object(server, "PUBLISH", "cloudflare"), \
             mock.patch.object(server, "KEEP", "ftp:x"), \
             mock.patch.object(server, "cloud_settings", return_value=CONFIG), \
             mock.patch.object(server, "cloud_publish", side_effect=self.mock_publish):
            with self.assertRaises(server.SpatialVibeError):
                server.publish_ar("calibration")

    def test_parallel_variants_keep_independent_bytes_and_dimensions(self):
        captured = []
        def publish(body, metadata, config):
            captured.append((bytes(body), metadata.copy()))
            return self.mock_publish(body, metadata, config)
        with mock.patch.object(server, "PUBLISH", "cloudflare"), \
             mock.patch.object(server, "cloud_settings", return_value=CONFIG), \
             mock.patch.object(server, "cloud_publish", side_effect=publish):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda flag: server.publish_ar("calibration", include_context=flag), [True, False]))
        self.assertEqual(results[0]["scene_size_m"]["x_width"], .2)
        self.assertEqual(results[1]["scene_size_m"]["x_width"], .1)
        self.assertIsNone(results[1]["ar_floor_mm"])
        self.assertEqual(len({hashlib.sha256(body).hexdigest() for body, _ in captured}), 2)

    def test_existing_directory_and_icloud_targets_still_work(self):
        icloud = self.root / "icloud"
        icloud.mkdir()
        for target in ["dir:" + str(self.root / "published"), "icloud"]:
            with mock.patch.object(server, "PUBLISH", target), mock.patch.object(server, "ICLOUD", icloud), \
                 mock.patch.object(server, "cloud_publish") as upload:
                result = server.publish_ar("calibration", include_context=False)
            self.assertTrue(Path(result["published"]).is_file())
            self.assertTrue(result["published"].endswith("calibration_v001_parts-only.usdz"))
            self.assertNotIn("expires_at", result)
            upload.assert_not_called()

    def test_cloud_error_never_falls_back_or_exposes_a_token(self):
        with mock.patch.object(server, "PUBLISH", "cloudflare"), \
             mock.patch.object(server, "cloud_settings", return_value=CONFIG), \
             mock.patch.object(server, "cloud_publish", side_effect=client.PublicationError("Synthetic unavailable")):
            with self.assertRaises(server.SpatialVibeError) as failure:
                server.publish_ar("calibration")
            self.assertNotIn(TOKEN, str(failure.exception))

    def test_unsupported_isolation_rejects_before_credentials_are_read(self):
        with mock.patch.object(server, "PUBLISH", "cloudflare"), \
             mock.patch("spatialvibe_mcp._isolation.sys.platform", "linux"), \
             mock.patch.object(server, "cloud_settings") as settings:
            with self.assertRaises(server.SpatialVibeError):
                server.publish_ar("calibration")
            settings.assert_not_called()

    def test_parent_reads_reject_symlinks_and_writes_replace_them(self):
        canary = self.root / "credential-canary"
        canary.write_text("nonsecret-canary")
        link = self.version / "model.py"
        link.symlink_to(canary)
        with self.assertRaises(OSError):
            server.get_code("calibration")
        server._atomic_bytes(link, b"safe replacement")
        self.assertFalse(link.is_symlink())
        self.assertEqual(canary.read_text(), "nonsecret-canary")

    def test_generated_code_cannot_see_parent_auth_or_read_outside(self):
        canary = self.root / "credential-canary"
        canary.write_text("nonsecret-canary")
        code = ("import os\nfrom pathlib import Path\n"
                "assert 'SPATIALVIBE_AR_UPLOAD_TOKEN' not in os.environ\n"
                "assert 'CLOUDFLARE_API_TOKEN' not in os.environ\n"
                f"try:\n Path({str(canary)!r}).read_text()\nexcept PermissionError:\n pass\nelse:\n raise AssertionError('outside read allowed')\n"
                "from build123d import Box\nparts={'block':Box(10,10,10)}\n")
        with mock.patch.dict(os.environ, {"SPATIALVIBE_AR_UPLOAD_TOKEN": TOKEN, "CLOUDFLARE_API_TOKEN": TOKEN}):
            result = server.build_model("isolation", code)
        self.assertTrue(result["ok"], result)
        self.assertNotIn(TOKEN, json.dumps(result))

    def test_generated_metadata_symlinks_do_not_write_parent_credential_file(self):
        canary = self.root / "credential-canary"
        canary.write_text("nonsecret-canary")
        code = ("from pathlib import Path\n"
                f"p=Path(__file__).parent\n(p/'result.json').symlink_to({str(canary)!r})\n"
                f"(p/'print_job.json').symlink_to({str(canary)!r})\n"
                "from build123d import Box\nparts={'block':Box(10,10,10)}\n")
        result = server.build_model("metadata-links", code)
        self.assertTrue(result["ok"], result)
        self.assertEqual(canary.read_text(), "nonsecret-canary")
        self.assertFalse((Path(result["folder"]) / "result.json").is_symlink())
        self.assertFalse((Path(result["folder"]) / "print_job.json").is_symlink())

    def test_result_symlink_cannot_make_parent_read_an_outside_file(self):
        canary = self.root / "private-result-canary"
        canary.write_text(json.dumps({"ok": False, "error": "nonsecret-outside-canary"}))
        code = ("from pathlib import Path\nimport os\n"
                f"(Path(__file__).parent/'_build'/'_result.json').symlink_to({str(canary)!r})\n"
                "os._exit(0)\n")
        result = server.build_model("result-link", code)
        self.assertFalse(result["ok"])
        self.assertNotIn("nonsecret-outside-canary", json.dumps(result))

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / "cloudflare/ar-worker/node_modules/miniflare").exists(),
                         "optional Miniflare test dependency is absent (pnpm install in cloudflare/ar-worker)")
    def test_python_publish_ar_through_actual_local_worker(self):
        bridge = Path(__file__).resolve().parents[1] / "cloudflare/ar-worker/python-bridge.mjs"
        class BridgeOpener:
            def open(self, req, timeout):
                wire = {"url": req.full_url, "headers": dict(req.header_items()),
                        "body": base64.b64encode(req.data).decode("ascii")}
                child = subprocess.run([shutil.which("node"), str(bridge)],
                                       input=json.dumps(wire), capture_output=True, text=True, timeout=30,
                                       env={"PATH": "/usr/bin:/bin"}, cwd=bridge.parent)
                if child.returncode:
                    raise RuntimeError("Local test-only worker bridge failed: " + child.stderr[-6000:])
                result = json.loads(child.stdout)
                response = Response(result["body"].encode())
                response.status = result["status"]
                return response
        def send(body, metadata, config):
            return client.publish(body, metadata, config, opener=BridgeOpener())
        with mock.patch.object(server, "PUBLISH", "cloudflare"), \
             mock.patch.object(server, "cloud_settings", return_value=CONFIG), \
             mock.patch.object(server, "cloud_publish", side_effect=send):
            result = server.publish_ar("calibration", include_context=False)
        self.assertRegex(result["published"], r"https://ar\.example\.test/ar/[A-Za-z0-9_-]{86}\Z")
        self.assertEqual(result["parts_size_m"], META["parts_size_m"])
        self.assertEqual(result["scene_size_m"], META["scene_size_m"])
        self.assertEqual(result["sha256"], hashlib.sha256(Path(result["usdz"]).read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Streamable HTTP mode behind the gateway: settings hygiene, bearer check, Host check (synthetic values)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="svremote-"))
os.environ.setdefault("SPATIALVIBE_HOME", str(TMP / "home"))
os.environ.setdefault("SPATIALVIBE_PUBLISH", f"dir:{TMP / 'pub'}")
sys.path.insert(0, str(ROOT))

from starlette.testclient import TestClient  # noqa: E402

from spatialvibe_mcp import _remote, server  # noqa: E402

TOKEN = "A" * 43
HOST = "mcp.example.test"
ENV = {"SPATIALVIBE_HTTP_PUBLIC_HOST": HOST, "SPATIALVIBE_MCP_UPSTREAM_TOKEN": TOKEN}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "Host": HOST}


class SettingsTests(unittest.TestCase):
    def test_env_token_and_defaults(self):
        s = _remote.settings(ENV)
        self.assertEqual((s.port, s.public_host, s.token), (8765, HOST, TOKEN))
        self.assertNotIn(TOKEN, repr(s))

    def test_refusals_never_echo_values(self):
        bad = [{**ENV, "SPATIALVIBE_HTTP_PORT": "80"}, {**ENV, "SPATIALVIBE_HTTP_PORT": "x"},
               {**ENV, "SPATIALVIBE_HTTP_PUBLIC_HOST": "localhost"}, {**ENV, "SPATIALVIBE_HTTP_PUBLIC_HOST": "Mcp.Example"},
               {**ENV, "SPATIALVIBE_HTTP_PUBLIC_HOST": "mcp.replace-me.example"},
               {**ENV, "SPATIALVIBE_MCP_UPSTREAM_TOKEN": "short"},
               {**ENV, "SPATIALVIBE_MCP_UPSTREAM_KEYCHAIN_SERVICE": "svc"},   # two sources
               {"SPATIALVIBE_HTTP_PUBLIC_HOST": HOST}]                        # no source
        for env in bad:
            with self.subTest(env=env), self.assertRaises(_remote.RemoteError) as caught:
                _remote.settings(env)
            self.assertNotIn("A" * 10, str(caught.exception))

    def test_keychain_source_is_read_with_the_upstream_account(self):
        env = {"SPATIALVIBE_HTTP_PUBLIC_HOST": HOST, "SPATIALVIBE_MCP_UPSTREAM_KEYCHAIN_SERVICE": "spatialvibe-mcp-upstream"}
        with mock.patch.object(_remote, "read_upload_token", return_value=TOKEN) as read:
            self.assertEqual(_remote.settings(env).token, TOKEN)
        read.assert_called_once_with("spatialvibe-mcp-upstream", "mcp-upstream")
        with mock.patch.object(_remote, "read_upload_token", side_effect=_remote.KeychainError("x")), \
             self.assertRaises(_remote.RemoteError):
            _remote.settings(env)


class HttpAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _remote.app(server.mcp, _remote.settings(ENV))

    def post(self, client, **headers):
        return client.post("/mcp", json=INIT, headers={**HEADERS, **headers})

    def test_bearer_and_host_checks(self):
        with TestClient(self.app, base_url=f"http://{HOST}") as c:
            r = self.post(c)
            self.assertEqual(r.status_code, 401)
            self.assertIn("invalid_token", r.headers.get("www-authenticate", ""))
            self.assertNotIn("resource_metadata", r.headers.get("www-authenticate", ""))  # gateway owns OAuth
            self.assertEqual(self.post(c, Authorization="Bearer " + "B" * 43).status_code, 401)
            self.assertEqual(self.post(c, Authorization="Basic " + TOKEN).status_code, 401)
            ok = self.post(c, Authorization="Bearer " + TOKEN)
            self.assertEqual(ok.status_code, 200)
            self.assertTrue(ok.headers.get("mcp-session-id"))
            self.assertIn('"serverInfo"', ok.text)
            self.assertEqual(self.post(c, Authorization="Bearer " + TOKEN, Host="evil.example.test").status_code, 421)
            self.assertEqual(c.get("/.well-known/oauth-protected-resource/mcp").status_code, 404)

    def test_transport_security_allows_only_the_tunnel_host_and_loopback(self):
        s = _remote.transport_security(HOST)
        self.assertTrue(s.enable_dns_rebinding_protection)
        self.assertEqual(s.allowed_hosts, [HOST, "127.0.0.1:*", "localhost:*"])
        self.assertEqual(s.allowed_origins, [])


class LauncherHttpModeTests(unittest.TestCase):
    """The launcher maps the http keys onto the server environment and nothing else."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ar_mcp_launch", ROOT / "tools" / "ar_mcp_launch.py")
        self.launch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launch)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = {"origin": "https://spatialvibe-ar.example.workers.dev", "keychain_service": "spatialvibe-ar-upload"}
        self.http = {**self.base, "transport": "http", "public_host": "mcp.example.test",
                     "upstream_keychain_service": "spatialvibe-mcp-upstream", "http_port": 8765}

    def write(self, value):
        path = Path(self.tmp.name) / "config.json"
        path.write_text(json.dumps(value))
        os.chmod(path, 0o600)
        return path

    def test_http_keys_become_the_http_environment(self):
        env = self.launch.server_environment(self.launch.load_config(self.write(self.http)))
        self.assertEqual(env["SPATIALVIBE_TRANSPORT"], "http")
        self.assertEqual(env["SPATIALVIBE_HTTP_PUBLIC_HOST"], "mcp.example.test")
        self.assertEqual(env["SPATIALVIBE_HTTP_PORT"], "8765")
        self.assertEqual(env["SPATIALVIBE_MCP_UPSTREAM_KEYCHAIN_SERVICE"], "spatialvibe-mcp-upstream")
        self.assertNotIn("SPATIALVIBE_MCP_UPSTREAM_TOKEN", env)
        stdio = self.launch.server_environment(self.launch.load_config(self.write(self.base)))
        self.assertFalse({k for k in stdio if "HTTP" in k or "TRANSPORT" in k or "UPSTREAM" in k})

    def test_http_mode_validation(self):
        for bad in [{**self.http, "transport": "sse"}, {k: v for k, v in self.http.items() if k != "public_host"},
                    {**self.http, "public_host": "localhost"}, {**self.http, "public_host": "mcp.replace-me.example"},
                    {**self.http, "upstream_keychain_service": "spatialvibe-ar-upload"},
                    {**self.http, "http_port": 80}, {**self.http, "http_port": "8765"},
                    {**self.base, "public_host": "mcp.example.test"}]:
            with self.subTest(bad=bad), self.assertRaises(self.launch.LaunchError):
                self.launch.load_config(self.write(bad))


if __name__ == "__main__":
    unittest.main(verbosity=2)

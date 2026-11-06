"""Proxy-injected credential mode for cloud sessions (synthetic values only)."""
import io
import os
import unittest
from unittest import mock
from urllib import error, request

from spatialvibe_mcp import _ar_publish as client

ORIGIN = "https://ar.example.test"
PROXY = {"SPATIALVIBE_AR_ORIGIN": ORIGIN, "SPATIALVIBE_AR_CREDENTIAL": "proxy",
         "HTTPS_PROXY": "http://127.0.0.1:3128"}


def proxies_of(opener):
    return [h.proxies for h in opener.handlers if isinstance(h, request.ProxyHandler)]


class ProxyModeTests(unittest.TestCase):
    def test_proxy_mode_uses_placeholder_and_never_reads_a_local_key(self):
        with mock.patch.dict(os.environ, PROXY, clear=True), \
             mock.patch.object(client, "read_upload_token", side_effect=AssertionError("keychain read")):
            s = client.settings()
        self.assertTrue(s.via_proxy)
        self.assertEqual(s.token, client.PROXY_PLACEHOLDER)

    def test_proxy_mode_refuses_a_second_credential_source(self):
        for extra in ({"SPATIALVIBE_AR_UPLOAD_TOKEN": "T" * 43},
                      {"SPATIALVIBE_AR_KEYCHAIN_SERVICE": "spatialvibe-ar-upload"}):
            with mock.patch.dict(os.environ, {**PROXY, **extra}, clear=True), \
                 self.assertRaises(client.PublicationError):
                client.settings()

    def test_proxy_mode_needs_a_proxy_that_covers_the_host(self):
        no_proxy = {k: v for k, v in PROXY.items() if k != "HTTPS_PROXY"}
        for env in (no_proxy, {**PROXY, "NO_PROXY": "ar.example.test"}):
            with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(client.PublicationError):
                client.settings()

    def test_unknown_mode_and_placeholder_as_local_key_are_refused(self):
        for env in ({**PROXY, "SPATIALVIBE_AR_CREDENTIAL": "env"},
                    {"SPATIALVIBE_AR_ORIGIN": ORIGIN, "SPATIALVIBE_AR_UPLOAD_TOKEN": client.PROXY_PLACEHOLDER}):
            with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(client.PublicationError):
                client.settings()

    def test_local_mode_still_bypasses_proxies_and_proxy_mode_uses_them(self):
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:3128"}, clear=True):
            self.assertFalse(any(p_ for p_ in proxies_of(client._opener())))   # no proxy route at all
            self.assertEqual(proxies_of(client._opener(True))[0].get("https"), "http://127.0.0.1:3128")
        for op in (client._opener(), client._opener(True)):
            self.assertTrue(any(isinstance(h, client.NoRedirect) for h in op.handlers))

    def test_401_through_the_proxy_names_the_missing_injection(self):
        cfg = client.Settings(ORIGIN, client.PROXY_PLACEHOLDER, 60, 10, 1 << 20, True)

        class Refuse:
            def open(self, req, timeout):
                self.auth = req.get_header("Authorization")
                raise error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))
        op = Refuse()
        with self.assertRaisesRegex(client.PublicationError, "proxy did not add"):
            client.publish(b"x" * 200, {"include_context": False}, cfg, opener=op)
        self.assertEqual(op.auth, "Bearer " + client.PROXY_PLACEHOLDER)


if __name__ == "__main__":
    unittest.main(verbosity=2)

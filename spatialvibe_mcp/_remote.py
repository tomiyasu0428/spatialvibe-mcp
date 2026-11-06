"""Streamable HTTP mode behind a remote gateway (trusted parent only; never model code).

Topology: Claude / ChatGPT → gateway Worker (OAuth 2.1, `cloudflare/mcp-gateway`) → Cloudflare
Tunnel → this process on 127.0.0.1. The gateway signs the user in and sends one dedicated
upstream credential; this server accepts that credential and nothing else. Users and OAuth
tokens never reach this process, and the generated-code sandbox is unchanged.

The credential is a 43-character base64url value (32 random bytes), read from the macOS
Keychain (service `SPATIALVIBE_MCP_UPSTREAM_KEYCHAIN_SERVICE`, account `mcp-upstream`) or,
for tests only, `SPATIALVIBE_MCP_UPSTREAM_TOKEN`. Nothing here logs headers or the value.
"""
from dataclasses import dataclass
import logging
import os
import re
import secrets

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from ._ar_keychain import KeychainError, read_upload_token

TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
HOST = re.compile(r"[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)+\Z")
ACCOUNT = "mcp-upstream"
PATH = "/mcp"


class RemoteError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class RemoteSettings:
    port: int
    public_host: str   # the Tunnel hostname the gateway connects to (Host header on arrival)
    token: str


def settings(environ=os.environ) -> RemoteSettings:
    try:
        port = int(environ.get("SPATIALVIBE_HTTP_PORT", "8765"))
        if not 1024 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise RemoteError("SPATIALVIBE_HTTP_PORT must be an integer from 1024 to 65535") from None
    host = environ.get("SPATIALVIBE_HTTP_PUBLIC_HOST", "")
    if not HOST.fullmatch(host) or host.endswith(".localhost") or re.search(r"replace|your-", host):
        raise RemoteError("SPATIALVIBE_HTTP_PUBLIC_HOST must be the Tunnel hostname (lowercase DNS name)")
    token = environ.get("SPATIALVIBE_MCP_UPSTREAM_TOKEN")
    service = environ.get("SPATIALVIBE_MCP_UPSTREAM_KEYCHAIN_SERVICE")
    if token is not None and service is not None:
        raise RemoteError("Configure one upstream credential source, not both")
    if token is None:
        if not service:
            raise RemoteError("SPATIALVIBE_MCP_UPSTREAM_KEYCHAIN_SERVICE is required in http mode")
        try:
            token = read_upload_token(service, ACCOUNT)
        except KeychainError:
            raise RemoteError("upstream credential is unavailable in the Keychain") from None
    if not TOKEN.fullmatch(token):
        raise RemoteError("upstream credential must be 43 base64url characters")
    return RemoteSettings(port, host, token)


class UpstreamTokenVerifier:
    """Accepts exactly the gateway's upstream credential (constant-time comparison)."""

    def __init__(self, expected: str):
        if not TOKEN.fullmatch(expected):
            raise RemoteError("upstream credential must be 43 base64url characters")
        self._expected = expected

    async def verify_token(self, token: str) -> AccessToken | None:
        if not isinstance(token, str) or not secrets.compare_digest(token, self._expected):
            return None
        # The token field is not needed downstream; never keep a copy in request state.
        return AccessToken(token="", client_id="spatialvibe-gateway", scopes=["mcp"])


def transport_security(public_host: str) -> TransportSecuritySettings:
    # cloudflared forwards the public Host header unchanged; local checks use loopback.
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=[public_host, "127.0.0.1:*", "localhost:*"],
                                     allowed_origins=[])


def app(mcp, config: RemoteSettings):
    """Starlette app: Bearer-protected Streamable HTTP at /mcp, no OAuth metadata (the gateway owns it)."""
    mcp._token_verifier = UpstreamTokenVerifier(config.token)
    mcp.settings.auth = AuthSettings(issuer_url=f"https://{config.public_host}", resource_server_url=None,
                                     required_scopes=["mcp"])
    return mcp.streamable_http_app(streamable_http_path=PATH, host="127.0.0.1",
                                   transport_security=transport_security(config.public_host))


def serve(mcp, config: RemoteSettings) -> None:
    import uvicorn
    # No access log: request lines would record session ids; auth headers are never logged.
    logging.getLogger("uvicorn.access").disabled = True
    uvicorn.run(app(mcp, config), host="127.0.0.1", port=config.port, log_level="warning",
                access_log=False, server_header=False, date_header=False, proxy_headers=False)

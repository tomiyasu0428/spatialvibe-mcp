"""Trusted-parent client for the independent AR Worker. Never used by model scripts."""
from dataclasses import dataclass
import hashlib
import json
import os
import re
import secrets
import time
from urllib import error, parse, request
from ._ar_keychain import KeychainError, read_upload_token

TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
# Honest application identity. Cloudflare's edge rejects urllib's default agent with
# error 1010 before the Worker runs, so the request must not rely on that default.
USER_AGENT = "SpatialVibe-MCP-AR-Publisher/1"


class PublicationError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class Settings:
    origin: str
    token: str
    ttl: int
    timeout: int
    max_bytes: int


def settings() -> Settings:
    origin = os.environ.get("SPATIALVIBE_AR_ORIGIN", "")
    try:
        url = parse.urlsplit(origin)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.port is not None or url.path or url.query or url.fragment
                or origin != f"https://{url.hostname}"):
            raise ValueError
        token = os.environ.get("SPATIALVIBE_AR_UPLOAD_TOKEN")
        if token is None:
            service = os.environ.get("SPATIALVIBE_AR_KEYCHAIN_SERVICE")
            token = read_upload_token(service) if service else ""
        if not TOKEN.fullmatch(token):
            raise ValueError
        ttl = int(os.environ.get("SPATIALVIBE_AR_TTL", "3600"))
        timeout = int(os.environ.get("SPATIALVIBE_AR_TIMEOUT", "60"))
        maximum = int(os.environ.get("SPATIALVIBE_AR_MAX_BYTES", str(8 * 1024 * 1024)))
        if not (60 <= ttl <= 86400 and 1 <= timeout <= 300 and 128 <= maximum <= 16 * 1024 * 1024):
            raise ValueError
    except (ValueError, TypeError, KeychainError):
        raise PublicationError("AR publication configuration is missing or invalid; configure the trusted parent securely") from None
    return Settings(origin, token, ttl, timeout, maximum)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    # Do not send the bearer credential through inherited HTTP proxies or redirects.
    return request.build_opener(request.ProxyHandler({}), NoRedirect())


def publish(body: bytes, metadata: dict, config: Settings, *, opener=None, now=time.time) -> dict:
    if not body or len(body) > config.max_bytes:
        raise PublicationError("AR model exceeds the configured upload limit")
    checksum = hashlib.sha256(body).hexdigest()
    identity = secrets.token_urlsafe(32)
    headers = {"Authorization": f"Bearer {config.token}", "User-Agent": USER_AGENT,
               "Content-Type": "model/vnd.usdz+zip",
               "Idempotency-Key": identity, "X-Content-SHA256": checksum,
               "X-AR-TTL-Seconds": str(config.ttl),
               "X-AR-Metadata": json.dumps(metadata, separators=(",", ":"), allow_nan=False)}
    client = opener or _opener()
    for attempt in range(2):
        req = request.Request(config.origin + "/api/publications", data=body, headers=headers, method="POST")
        try:
            with client.open(req, timeout=config.timeout) as response:
                if response.status not in (200, 201):
                    raise PublicationError("AR publication returned an unexpected status")
                raw = response.read(16385)
                if len(raw) > 16384:
                    raise PublicationError("AR publication returned an invalid response")
                result = json.loads(raw)
            allowed = {"url", "expires_at", "sha256", *metadata}
            if (not isinstance(result, dict) or set(result) != allowed
                    or not isinstance(result.get("url"), str)
                    or not re.fullmatch(re.escape(config.origin) + r"/ar/[A-Za-z0-9_-]{86}", result["url"])
                    or type(result.get("expires_at")) is not int
                    or not now() < result["expires_at"] <= now() + config.ttl + 120
                    or result.get("sha256") != checksum
                    or any(result.get(key) != value for key, value in metadata.items())):
                raise PublicationError("AR publication returned an invalid response")
            return result
        except error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status in (429, 500, 502, 503, 504) and attempt == 0:
                continue
            if status in (301, 302, 303, 307, 308):
                raise PublicationError("AR publication refused a redirect") from None
            raise PublicationError(f"AR publication was not confirmed (HTTP {status}); no local fallback was used") from None
        except (error.URLError, TimeoutError, OSError):
            if attempt == 0:
                continue
            raise PublicationError("AR publication outcome is unknown after a temporary failure; a remote copy may exist until expiry") from None
        except (ValueError, TypeError):
            raise PublicationError("AR publication returned an invalid response") from None
    raise PublicationError("AR publication was not confirmed")

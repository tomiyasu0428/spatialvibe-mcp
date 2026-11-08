"""Start the MCP server in Cloudflare publish mode with a minimal, explicit environment.

Register it as the MCP command, using the same Python that owns the Keychain item:
    <venv>/bin/python -I <repo>/tools/ar_mcp_launch.py [config.json]

The config (default `<repo>/.spatialvibe-ar.local.json`, git-ignored) must be a regular
file owned by you with mode 0600. It holds no secret, only local settings:
    {"origin": "https://spatialvibe-ar.<subdomain>.workers.dev",
     "keychain_service": "spatialvibe-ar-upload",
     "home": "/absolute/path/to/project/data",      # SPATIALVIBE_HOME (optional)
     "bed": "256,256,256", "printer": "a1mini", "timeout": 180, "ttl": 3600,  # optional
     "transport": "http", "public_host": "mcp.example.com",                   # remote gateway mode
     "upstream_keychain_service": "spatialvibe-mcp-upstream", "http_port": 8765}
The repository root is outside the generated-code sandbox's readable roots.

Remote gateway mode (`transport: "http"`, see REMOTE_MCP.md) serves Streamable HTTP on
127.0.0.1:<http_port> for the Cloudflare Tunnel; `public_host` is the Tunnel hostname and
`upstream_keychain_service` names the Keychain item (account `mcp-upstream`) holding the
credential the gateway Worker presents. Without `transport` the server stays on stdio.

Like `env -i`, the server receives only the variables built here: no Cloudflare admin
token, no other credentials from the parent, and never SPATIALVIBE_AR_UPLOAD_TOKEN
(the server reads the dedicated upload credential from the Keychain).
"""
import json
import os
from pathlib import Path
import re
import stat
import sys

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / ".spatialvibe-ar.local.json"
ALLOWED = {"origin", "keychain_service", "home", "bed", "timeout", "ttl", "printer",
           "keep",
           "transport", "public_host", "upstream_keychain_service", "http_port"}
SERVICE = r"[A-Za-z0-9_.:-]{1,160}"
HOST = r"[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)+"


class LaunchError(RuntimeError):
    pass


def load_config(path: Path) -> dict:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise LaunchError(f"config not found: {path.name}") from None
    if not stat.S_ISREG(info.st_mode):
        raise LaunchError("config must be a regular file (no symlink)")
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise LaunchError("config must be owned by you with mode 0600")
    if info.st_size > 4096:
        raise LaunchError("config is unexpectedly large")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise LaunchError("config is not valid JSON") from None
    if not isinstance(value, dict) or set(value) - ALLOWED or not {"origin", "keychain_service"} <= set(value):
        raise LaunchError(f"config keys must be within {sorted(ALLOWED)} and include origin, keychain_service")
    origin = value["origin"]
    m = re.fullmatch(r"https://([a-z0-9-]+(?:\.[a-z0-9-]+)+)", origin) if isinstance(origin, str) else None
    if not m or re.search(r"replace|your-", m.group(1)):
        raise LaunchError("origin must be a bare https origin of the dedicated AR Worker")
    if not isinstance(value["keychain_service"], str) or not re.fullmatch(SERVICE, value["keychain_service"]):
        raise LaunchError("keychain_service is invalid")
    if "transport" in value:
        if value["transport"] != "http":
            raise LaunchError("transport must be http when set (omit it for stdio)")
        host = value.get("public_host")
        if not (isinstance(host, str) and re.fullmatch(HOST, host)) or re.search(r"replace|your-|localhost", host):
            raise LaunchError("http mode needs public_host, the Tunnel hostname")
        service = value.get("upstream_keychain_service")
        if not (isinstance(service, str) and re.fullmatch(SERVICE, service)) or service == value["keychain_service"]:
            raise LaunchError("http mode needs upstream_keychain_service, distinct from keychain_service")
        port = value.get("http_port", 8765)
        if not (isinstance(port, int) and 1024 <= port <= 65535):
            raise LaunchError("http_port must be an integer from 1024 to 65535")
    elif {"public_host", "upstream_keychain_service", "http_port"} & set(value):
        raise LaunchError("public_host, upstream_keychain_service and http_port need transport: http")
    if "home" in value and not (isinstance(value["home"], str) and Path(value["home"]).is_absolute()):
        raise LaunchError("home must be an absolute path")
    for key in ("timeout", "ttl"):
        if key in value and not (isinstance(value[key], int) and value[key] > 0):
            raise LaunchError(f"{key} must be a positive integer")
    if "keep" in value and not (isinstance(value["keep"], str) and (value["keep"] == "icloud" or (
            value["keep"].startswith("dir:") and Path(value["keep"][4:]).is_absolute()))):
        raise LaunchError("keep must be icloud or dir:/absolute/path")
    if "bed" in value and not (isinstance(value["bed"], str) and re.fullmatch(r"[0-9.,]{1,40}", value["bed"])):
        raise LaunchError("bed must look like 256,256,256")
    if "printer" in value and not (isinstance(value["printer"], str)
                                   and re.fullmatch(r"[A-Za-z0-9 ._x×*-]{1,40}", value["printer"])):
        raise LaunchError("printer must look like a1mini or 256x256x256")
    return value


def server_environment(config: dict) -> dict:
    env = {
        "HOME": str(Path.home()),
        "PATH": "/usr/bin:/bin",  # sandbox-exec lives in /usr/bin
        "LANG": "en_US.UTF-8",
        "PYTHONPATH": str(REPO),
        "SPATIALVIBE_PUBLISH": "cloudflare",
        "SPATIALVIBE_AR_ORIGIN": config["origin"],
        "SPATIALVIBE_AR_KEYCHAIN_SERVICE": config["keychain_service"],
    }
    optional = {"home": "SPATIALVIBE_HOME", "bed": "SPATIALVIBE_BED", "printer": "SPATIALVIBE_PRINTER",
                "timeout": "SPATIALVIBE_TIMEOUT", "ttl": "SPATIALVIBE_AR_TTL", "keep": "SPATIALVIBE_AR_KEEP"}
    for key, name in optional.items():
        if key in config:
            env[name] = str(config[key])
    if config.get("transport") == "http":
        env["SPATIALVIBE_TRANSPORT"] = "http"
        env["SPATIALVIBE_HTTP_PUBLIC_HOST"] = config["public_host"]
        env["SPATIALVIBE_HTTP_PORT"] = str(config.get("http_port", 8765))
        env["SPATIALVIBE_MCP_UPSTREAM_KEYCHAIN_SERVICE"] = config["upstream_keychain_service"]
    return env


def main(argv=None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        raise SystemExit("usage: ar_mcp_launch.py [config.json]")
    try:
        config = load_config(Path(args[0]) if args else DEFAULT_CONFIG)
    except LaunchError as exc:
        raise SystemExit(f"spatialvibe AR launch refused: {exc}") from None
    os.chdir(REPO)
    os.execve(sys.executable, [sys.executable, "-m", "spatialvibe_mcp"], server_environment(config))


if __name__ == "__main__":
    main()

"""macOS generated-code isolation; fail closed when unavailable.

Credentials must stay in the trusted parent process and outside these readable
runtime roots. No deployment/admin credential belongs in the MCP process.
This uses deprecated macOS sandbox-exec and fails closed on other platforms.
"""
import json
import os
from pathlib import Path
import shutil
import sys


def child_environment(version: Path, package_root: Path) -> dict[str, str]:
    version = version.resolve(strict=True)
    for folder in (".tmp", ".mpl"):
        target = version / folder
        if target.is_symlink():
            raise ValueError("Sandbox runtime folders must not be symlinks")
        target.mkdir(exist_ok=True, mode=0o700)
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(version),
        "TMPDIR": str(version / ".tmp"),
        "MPLCONFIGDIR": str(version / ".mpl"),
        "MPLBACKEND": "Agg",
        "PYTHONPATH": str(package_root.resolve(strict=True)),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "LANG": "en_US.UTF-8",
    }


def sandbox_command(version: Path, package_root: Path, argv: list[str]) -> list[str]:
    if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
        raise RuntimeError("Verified macOS sandbox required; refusing unsandboxed execution")
    version = version.resolve(strict=True)
    source = package_root.resolve(strict=True) / "spatialvibe_mcp"
    # Trusted roots contain code/dependencies only. Never store tokens in them.
    roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), source]
    if any(root in (Path("/"), Path("/Users"), Path.home(), package_root.resolve())
           for root in roots):
        raise ValueError("Refusing a broad trusted runtime root")
    if any(version == root or root in version.parents for root in roots):
        raise ValueError("Writable version must be outside trusted code roots")
    if not argv or Path(argv[0]).resolve() != Path(sys.executable).resolve():
        raise ValueError("Only the configured Python executable may be launched")
    quote = lambda path: json.dumps(str(path))
    reads = roots + [version, Path("/System/Library"), Path("/usr/lib"),
                     Path("/Library/Apple"), Path("/Library/Fonts"),
                     Path("/usr/share/zoneinfo"), Path("/private/var/db/timezone")]
    profile = [
        "(version 1)(allow default)",
        "(deny network*)(deny file-read*)(deny file-write*)",
        "(deny mach-lookup)(deny process-info*)(deny process-exec)",
        # Metadata supports Python path resolution but grants no file content.
        "(allow file-read-metadata)",
        # libSystem startup reads the root directory itself; no descendants.
        '(allow file-read* (literal "/"))',
        f"(allow file-read* (literal {quote(package_root.resolve())}))",
        "(allow file-read* " + " ".join(f"(subpath {quote(p)})" for p in reads) + ")",
        '(allow file-read-data (literal "/dev/null") (literal "/dev/urandom")'
        ' (literal "/dev/random") (literal "/private/etc/localtime"))',
        f"(allow file-write* (subpath {quote(version)}) (literal \"/dev/null\"))",
        f"(allow process-exec (literal {quote(Path(sys.executable).resolve())})"
        f" (literal {quote(sys.executable)}))",
    ]
    return ["sandbox-exec", "-p", "".join(profile), *argv]

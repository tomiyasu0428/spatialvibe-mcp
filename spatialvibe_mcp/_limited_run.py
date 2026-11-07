"""Trusted entry point for a size-limited CAD/render subprocess, inside sandbox-exec."""
import resource
import runpy
import sys

if __name__ == "__main__":
    module = sys.argv[1]
    if module not in {"_runner", "_render", "_sheet", "_steps", "_geometry_plate", "usdz"}:
        raise SystemExit("Unknown isolated module")
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 << 20, 64 << 20))
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    sys.argv = sys.argv[1:]
    runpy.run_module("spatialvibe_mcp." + module, run_name="__main__", alter_sys=True)

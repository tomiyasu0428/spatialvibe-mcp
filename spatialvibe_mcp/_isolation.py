"""Sandboxed child processes for generated code and for the helpers that parse what it produced.

`build_model` runs Python written by the AI. Everything that process can influence is treated as
hostile: its environment, its files, its exit code, the JSON it reports, and later the mesh files
that `preview` / `publish_ar` parse. The rules, in one place:

- Every child runs under macOS `sandbox-exec` (resolved `/usr/bin/sandbox-exec`) with a profile that
  denies network, Mach lookups, process-info about others, fork, exec (except this Python), hard
  links and signals to other processes; reads are limited to the interpreter, the venv, this
  package and the job's scratch folder; writes to the scratch folder only. If the sandbox cannot
  be set up, the job is refused — there is no unsandboxed fallback, on any platform.
- The child never sees the project folder. It gets an ephemeral scratch folder (cwd, HOME, TMPDIR,
  matplotlib config) that is deleted afterwards, a sanitised environment (no inherited variables),
  `python -P -s -B` so neither cwd nor the script folder reach `sys.path`, and `PYTHONPATH` set to
  this checkout only.
- After the child has run, nothing in the scratch folder is opened by path again: stderr is read
  through the descriptor created before the child started, outputs through `out_fd` with the
  plain-file rules of `_files`. Only expected, plain, single-linked, size-bounded files are copied
  ("admitted") into the trusted version folder, within a per-job budget; the file names come from
  validated part/context names, never from the child.
- Child stdout/stderr go to bounded files; a timeout kills the whole process group; the child
  applies RLIMIT_FSIZE / RLIMIT_CPU / RLIMIT_NPROC on itself before untrusted code runs.

Not covered: local denial of service inside those limits (CPU time up to the limit, RAM, scratch
disk up to RLIMIT_FSIZE per file), kernel or sandbox-exec bugs, and sandbox-exec being a deprecated
Apple interface. Metadata the child reports (error text, sizes, notes) is data for the AI to read,
never instructions, and never used to build paths without validation.
"""
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import _files as files
from ._files import BoundaryError

REPO = Path(__file__).resolve().parent.parent
PACKAGE = Path(__file__).resolve().parent
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
FILE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,120}$")   # file names the parent builds from validated names

MAX_MESH_BYTES = 256 * 1024 * 1024    # one STL/STEP (also RLIMIT_FSIZE in the child)
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_USDZ_BYTES = 128 * 1024 * 1024
MAX_TEXT_BYTES = 8 * 1024 * 1024      # model.py, note.txt, result.json
MAX_JOB_FILES = 256                   # inputs + outputs copied per job
MAX_JOB_BYTES = 1024 * 1024 * 1024    # likewise, in bytes
LOG_TAIL = 3000                       # characters of child stderr reported back

PYTHON_FLAGS = ["-P", "-s", "-B"]     # no cwd/script dir on sys.path, no user site, no .pyc


# ---- preconditions ------------------------------------------------------------------------

def sandbox_exec() -> Path:
    """The resolved sandbox binary, or BoundaryError. Never searched on PATH."""
    if sys.platform != "darwin":
        raise BoundaryError("generated code only runs inside the macOS sandbox (sandbox-exec); "
                            "this platform is not supported, so builds and previews are refused")
    try:
        st = os.stat(SANDBOX_EXEC)
    except OSError:
        raise BoundaryError(f"{SANDBOX_EXEC} is missing; builds and previews are refused") from None
    if not stat.S_ISREG(st.st_mode) or not os.access(SANDBOX_EXEC, os.X_OK):
        raise BoundaryError(f"{SANDBOX_EXEC} is not an executable file; builds and previews are refused")
    return SANDBOX_EXEC


def python() -> tuple[Path, Path]:
    """(interpreter as configured, resolved) — the only program the sandbox may exec."""
    exe = Path(sys.executable)
    if not exe.is_absolute():
        raise BoundaryError("sys.executable is not absolute")
    return exe, exe.resolve(strict=True)


def trusted_roots() -> list[Path]:
    """Read-only roots that hold code and libraries. Nothing private may live under them."""
    roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), PACKAGE]
    broad = {Path("/"), Path("/Users"), Path("/private"), Path.home().resolve(), REPO}
    for root in roots:
        if root in broad:
            raise BoundaryError(f"refusing to expose {root} to generated code")
    return roots


def _quote(p) -> str:
    return json.dumps(str(p))


def profile(scratch: Path, extra_write: list[Path] = ()) -> str:
    """The sandbox profile for one job. Later rules win over earlier ones."""
    roots = trusted_roots()
    exe, exe_real = python()
    scratch = scratch.resolve(strict=True)
    for root in roots:
        if scratch == root or root in scratch.parents:
            raise BoundaryError("scratch folder must not be inside a trusted root")
    reads = [*roots, scratch, Path("/System/Library"), Path("/usr/lib"), Path("/Library/Apple"),
             Path("/Library/Fonts"), Path("/usr/share/zoneinfo"), Path("/private/var/db/timezone"),
             *extra_write]
    writes = [scratch, *extra_write]
    return "".join([
        "(version 1)(allow default)",
        "(deny network*)",
        "(deny file-read*)(deny file-write*)(deny file-link)",
        "(deny mach-lookup)(deny process-exec)(deny process-fork)",
        "(deny process-info*)(allow process-info* (target self))",   # USD traps without self-info
        "(deny signal)(allow signal (target self))",
        "(allow file-read-metadata)",                       # path resolution; no file content
        '(allow file-read* (literal "/")',                 # libSystem reads the root itself
        f" (literal {_quote(REPO)}))",                      # the checkout folder itself (PYTHONPATH)
        "(allow file-read* " + " ".join(f"(subpath {_quote(p)})" for p in reads) + ")",
        '(allow file-read-data (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random")'
        ' (literal "/private/etc/localtime"))',
        "(allow file-write* " + " ".join(f"(subpath {_quote(p)})" for p in writes) + ' (literal "/dev/null"))',
        f"(allow process-exec (literal {_quote(exe)}) (literal {_quote(exe_real)}))",
    ])


# ---- the child's own limits (called by _runner / _render / usdz before anything untrusted) ---

def apply_child_limits() -> None:
    """RLIMIT_FSIZE / CPU / NPROC, soft = hard so the script cannot raise them. Exit if impossible."""
    import resource
    try:
        cpu = int(os.environ.get("SPATIALVIBE_CPU_SECONDS", "600"))
        cpu = min(max(cpu, 10), 36000)
        for res, val in ((resource.RLIMIT_FSIZE, MAX_MESH_BYTES), (resource.RLIMIT_CPU, cpu),
                         (resource.RLIMIT_NPROC, 0)):
            resource.setrlimit(res, (val, val))
    except (ValueError, OSError) as e:
        sys.stderr.write(f"refusing to run without resource limits: {e!r}\n")
        os._exit(70)


# ---- one job -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Run:
    returncode: int | None       # None when killed by the timeout
    timed_out: bool
    stderr_tail: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def _tail_of_fd(fd: int) -> str:
    """Last LOG_TAIL characters of the regular file behind fd, by bounded pread. The descriptor was
    created by us before the child ran, so its inode cannot have been swapped for a link or FIFO;
    a regular file never blocks a read."""
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return ""
        size = min(st.st_size, LOG_TAIL * 4)
        data = os.pread(fd, size, st.st_size - size)
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")[-LOG_TAIL:].strip()


class Job:
    """An ephemeral scratch folder plus the sandboxed run that uses it.

        with Job(timeout) as job:
            job.put_text("model.py", code)                       # into job.work
            run = job.run("spatialvibe_mcp._runner", [job.work / "model.py", job.out, job.out / "result.json"])
            raw = job.read_output("result.json", limit)          # bounded, plain files only
            job.admit("part_x.stl", version_fd, "part_x.stl", limit)   # copy into the trusted folder

    `work` is the child's cwd and holds inputs the parent wrote; `inp` holds mesh files copied from a
    version; `out` is where the child writes. All of it is deleted on exit, success or not.
    """

    def __init__(self, timeout: int, mpl_cache: Path | None = None):
        sandbox_exec()                       # fail closed before creating anything
        self.timeout = int(timeout)
        self.root = Path(tempfile.mkdtemp(prefix="spatialvibe-job-")).resolve(strict=True)
        os.chmod(self.root, 0o700)
        self.work, self.inp, self.out = self.root / "work", self.root / "in", self.root / "out"
        self.home, self.tmp = self.root / "home", self.root / "tmp"
        for d in (self.work, self.inp, self.out, self.home, self.tmp):
            d.mkdir(mode=0o700)
        self.mpl = mpl_cache if mpl_cache is not None else self.root / "mpl"
        if mpl_cache is None:
            self.mpl.mkdir(mode=0o700)
        self._extra_write = [mpl_cache] if mpl_cache is not None else []
        self.work_fd, self.inp_fd, self.out_fd = (files.open_dir(d) for d in (self.work, self.inp, self.out))
        self._runs = 0
        self.files = self.bytes = 0
        self.cleaned = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        for fd in (self.work_fd, self.inp_fd, self.out_fd):
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            self.cleaned = files.wipe(self.root)
        except Exception:  # noqa: BLE001 — cleanup never masks the job's own outcome
            self.cleaned = False

    def _account(self, nbytes: int) -> None:
        """Total artifact budget per job, inputs and outputs together, checked before copying."""
        if self.files + 1 > MAX_JOB_FILES or self.bytes + nbytes > MAX_JOB_BYTES:
            raise BoundaryError(f"job artifact budget exceeded ({MAX_JOB_FILES} files / {MAX_JOB_BYTES} bytes)")
        self.files += 1
        self.bytes += nbytes

    # inputs (before the child runs)
    def put_text(self, name: str, text: str) -> Path:
        if self._runs:
            raise BoundaryError("inputs must be placed before the child runs")
        files.write_file(name, self.work_fd, text.encode("utf-8"), replace=False)
        return self.work / name

    def put_file(self, src_name: str, src_dir_fd: int, limit: int) -> Path:
        """Copy a plain file from a version folder into `inp` (refuses links, pipes, big files)."""
        if self._runs:
            raise BoundaryError("inputs must be placed before the child runs")
        self._account(files.plain_stat(src_name, src_dir_fd, limit).st_size)
        files.copy_file(src_name, src_dir_fd, src_name, self.inp_fd, limit, replace=False)
        return self.inp / src_name

    # running
    def env(self) -> dict:
        cpu = max(60, 4 * self.timeout)
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home), "TMPDIR": str(self.tmp),
            "MPLCONFIGDIR": str(self.mpl), "MPLBACKEND": "Agg",
            "PYTHONPATH": str(REPO), "PYTHONSAFEPATH": "1", "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
            "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
            "SPATIALVIBE_CPU_SECONDS": str(cpu),
        }

    def command(self, module: str, args) -> list[str]:
        argv = [str(python()[0]), *PYTHON_FLAGS, "-m", module, *map(str, args)]
        return [str(sandbox_exec()), "-p", profile(self.root, self._extra_write), *argv]

    def run(self, module: str, args) -> Run:
        """Run `python -m module args...` sandboxed. stdout/stderr go to files created here and
        read back only through these descriptors."""
        self._runs += 1
        logs = []
        for n in ("stdout", "stderr"):
            fd = os.open(self.root / f"{n}-{self._runs}.log",
                         os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            logs.append(fd)
        timed_out, rc = False, None
        try:
            p = subprocess.Popen(self.command(module, args), stdin=subprocess.DEVNULL, stdout=logs[0],
                                 stderr=logs[1], cwd=self.work, env=self.env(), close_fds=True,
                                 start_new_session=True)
            try:
                rc = p.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait()
            tail = _tail_of_fd(logs[1])
        finally:
            for fd in logs:
                os.close(fd)
        return Run(None if timed_out else rc, timed_out, tail)

    # outputs (after the child ran; `out_fd` predates it)
    def read_output(self, name: str, limit: int) -> bytes | None:
        """Bounded bytes of a plain file in `out`, None if the child did not write it."""
        try:
            return files.read_file(name, self.out_fd, limit)
        except FileNotFoundError:
            return None

    def output_is_plain(self, name: str) -> bool:
        return files.is_plain_file(name, self.out_fd)

    def admit(self, name: str, dest_dir_fd: int, dest_name: str, limit: int) -> int:
        """Copy one expected output into a trusted folder (plain, single-linked, bounded, within
        the job budget). `name` is built by the caller from validated names, never by the child."""
        if not FILE.fullmatch(name) or not FILE.fullmatch(str(dest_name)):
            raise BoundaryError(f"unexpected output name {name!r}")
        try:
            self._account(files.plain_stat(name, self.out_fd, limit).st_size)
            return files.copy_file(name, self.out_fd, dest_name, dest_dir_fd, limit)
        except FileNotFoundError:
            raise BoundaryError(f"the build did not produce {name}") from None

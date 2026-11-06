"""The parent's own file handling at the trust boundary: never follow a link, never block, never
read or copy more than the stated limit.

Every routine takes a directory descriptor and a bare name, so a symlink planted in a version
folder (by an old server's script) or in a job's scratch folder (by the script that just ran)
is replaced or refused, never followed. Sizes are checked from the opened descriptor before any
copy starts and again while copying. `wipe` removes a folder the child may have shaped without
recursion and without opening any file.
"""
import os
import secrets
import stat
from pathlib import Path


class BoundaryError(RuntimeError):
    """A trust-boundary rule could not be upheld; the operation was refused."""


def open_dir(name, dir_fd=None, follow=False) -> int:
    """Open a directory by name (inside dir_fd when given). Symlinks are refused unless follow."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | (0 if follow else os.O_NOFOLLOW)
    try:
        return os.open(str(name), flags, dir_fd=dir_fd)
    except FileNotFoundError:
        raise
    except OSError as e:
        # macOS reports a symlinked folder under O_NOFOLLOW|O_DIRECTORY as ENOTDIR, Linux as ELOOP
        if isinstance(e, NotADirectoryError) and not stat.S_ISLNK(os.lstat(str(name), dir_fd=dir_fd).st_mode):
            raise
        raise BoundaryError(f"refusing {name}: not a plain folder ({e.strerror})") from None


def is_plain_dir(name, dir_fd) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(str(name), dir_fd=dir_fd).st_mode)
    except OSError:
        return False


def open_plain(name, dir_fd) -> tuple[int, os.stat_result]:
    """Open a regular, single-linked file owned by us, without following symlinks or blocking on
    FIFOs. FileNotFoundError if absent, BoundaryError for anything that is not a plain file."""
    try:
        fd = os.open(str(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
    except FileNotFoundError:
        raise
    except OSError as e:
        raise BoundaryError(f"{name} is not a plain file ({e.strerror}); refusing it") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid():
            raise BoundaryError(f"{name} is not a plain file (symlink, link, pipe or foreign owner); refusing it")
    except BaseException:
        os.close(fd)
        raise
    return fd, st


def plain_stat(name, dir_fd, limit: int | None = None) -> os.stat_result:
    """Stat of a plain file (see open_plain), optionally refused above `limit` bytes."""
    fd, st = open_plain(name, dir_fd)
    os.close(fd)
    if limit is not None and st.st_size > limit:
        raise BoundaryError(f"{name} is larger than {limit} bytes; refusing it")
    return st


def is_plain_file(name, dir_fd) -> bool:
    try:
        plain_stat(name, dir_fd)
    except (OSError, BoundaryError):
        return False
    return True


def read_file(name, dir_fd, limit: int) -> bytes:
    """Bounded read of a plain file inside dir_fd. FileNotFoundError if absent."""
    fd, st = open_plain(name, dir_fd)
    with os.fdopen(fd, "rb") as f:
        if st.st_size > limit:
            raise BoundaryError(f"{name} is larger than {limit} bytes; refusing it")
        data = f.read(limit + 1)
    if len(data) > limit:
        raise BoundaryError(f"{name} is larger than {limit} bytes; refusing it")
    return data


def read_text(name, dir_fd, limit: int) -> str:
    return read_file(name, dir_fd, limit).decode("utf-8", errors="replace")


def copy_file(src_name, src_dir_fd, dst_name, dst_dir_fd, limit: int, replace: bool = True) -> int:
    """Copy a plain file between folders by descriptor; the size is checked before the first byte
    and while copying. With replace, a planted entry at `dst_name` is swapped out, never followed;
    without it, `dst_name` must not exist. Returns the byte count."""
    fd, st = open_plain(src_name, src_dir_fd)
    if st.st_size > limit:
        os.close(fd)
        raise BoundaryError(f"{src_name} is larger than {limit} bytes; refusing it")
    total = 0
    with os.fdopen(fd, "rb") as src, create(dst_name, dst_dir_fd, replace) as dst:
        while chunk := src.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise BoundaryError(f"{src_name} grew past {limit} bytes; refusing it")
            dst.write(chunk)
    return total


def write_file(name, dir_fd, data: bytes, replace: bool = True) -> None:
    with create(name, dir_fd, replace) as f:
        f.write(data)


class create:
    """Open a new file in dir_fd for writing. replace=False creates `name` itself (O_EXCL, so a
    planted entry makes it fail); replace=True writes a temp entry and renames it over `name`,
    which swaps out a planted symlink instead of following it. Removes the temp on error."""

    def __init__(self, name, dir_fd, replace=True):
        self.name, self.dir_fd, self.replace = str(name), dir_fd, replace
        self.tmp = f".write-{secrets.token_hex(8)}" if replace else self.name

    def __enter__(self):
        fd = os.open(self.tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644,
                     dir_fd=self.dir_fd)
        self.f = os.fdopen(fd, "wb")
        return self.f

    def __exit__(self, et, ev, tb):
        self.f.close()
        if et is not None:
            self._discard()
            return False
        if self.replace:
            try:
                os.replace(self.tmp, self.name, src_dir_fd=self.dir_fd, dst_dir_fd=self.dir_fd)
            except OSError as e:
                self._discard()
                raise BoundaryError(f"could not place {self.name}: {e.strerror}") from None
        return False

    def _discard(self):
        try:
            os.unlink(self.tmp, dir_fd=self.dir_fd)
        except OSError:
            pass


def remove_entry(name, dir_fd) -> None:
    """Remove a file or symlink entry (never its target); directories are left alone."""
    try:
        st = os.lstat(str(name), dir_fd=dir_fd)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(st.st_mode):
        os.unlink(str(name), dir_fd=dir_fd)


def plain_cache_dir(base: Path, *names: str) -> Path:
    """Create base/names... as parent-owned real folders (no symlink in the part we create) and
    return the resolved path."""
    p = Path(base).resolve(strict=True)
    for n in names:
        p = p / n
        if p.is_symlink():
            raise BoundaryError(f"{p} is a symlink; refusing to use it as a cache folder")
        p.mkdir(exist_ok=True, mode=0o700)
        if not p.is_dir() or os.stat(p).st_uid != os.getuid():
            raise BoundaryError(f"{p} is not our folder; refusing to use it as a cache folder")
    return p


def wipe(root: Path, max_depth: int = 48, budget: int = 2_000_000) -> bool:
    """Delete a folder tree someone else may have shaped: iterative (no recursion limit),
    descriptor based (never follows a link), never opens a file (a FIFO cannot block), and a
    subtree deeper than max_depth is renamed up to the root instead of being descended, so open
    descriptors stay bounded. Gives up after `budget` entries and returns False, leaving the
    remnant rather than hanging. True when the folder is gone."""
    try:
        rfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return not os.path.lexists(root)
    stack = [(rfd, None, None)]            # (dir fd, its name in parent, parent fd)
    try:
        while stack and budget > 0:
            fd, name, pfd = stack[-1]
            pushed = progress = False
            with os.scandir(fd) as it:
                for e in it:
                    budget -= 1
                    if budget <= 0:
                        break
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if len(stack) >= max_depth:   # too deep: hoist it to the root and come back
                                os.rename(e.name, f".hoist-{secrets.token_hex(8)}", src_dir_fd=fd, dst_dir_fd=rfd)
                                progress = True
                                continue
                            cfd = os.open(e.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                            stack.append((cfd, e.name, fd))
                            pushed = True
                            break
                        os.unlink(e.name, dir_fd=fd)
                        progress = True
                    except OSError:
                        continue
            if pushed or progress:
                continue                   # rescan the same directory (entries may have been skipped)
            stack.pop()
            os.close(fd)
            try:
                os.rmdir(name, dir_fd=pfd) if pfd is not None else os.rmdir(root)
            except OSError:
                pass
    finally:
        for fd, _, _ in stack:
            try:
                os.close(fd)
            except OSError:
                pass
    return not os.path.lexists(root)

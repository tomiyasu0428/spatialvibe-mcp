"""Private temporary jobs with bounded cleanup of model-created directory trees."""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import tempfile


@contextmanager
def unchanged_directory(path: Path):
    """Pin the expected directory identity while untrusted code runs in it."""
    fd = os.open(path, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY)
    try:
        yield
        if not os.path.samestat(os.fstat(fd), os.stat(path, follow_symlinks=False)):
            raise ValueError("Job directory was replaced")
    finally:
        os.close(fd)


@contextmanager
def scratch_directory(prefix: str):
    path = Path(tempfile.mkdtemp(prefix=prefix)).resolve(strict=True)
    identity = path.stat()
    try:
        yield path
    finally:
        try:
            if os.path.samestat(identity, path.lstat()):
                wipe(path)
        except FileNotFoundError:
            pass


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

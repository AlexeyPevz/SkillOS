from __future__ import annotations

from contextlib import contextmanager
import os
import tempfile
from pathlib import Path
import time
from typing import Iterator

try:
    import msvcrt

    def _lock(fd: int) -> None:
        # LK_NBLCK is non-blocking on Windows
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

except ImportError:
    # Fallback for non-Windows (simplified, typically use fcntl)
    try:
        import fcntl

        def _lock(fd: int) -> None:
            fcntl.flock(fd, fcntl.LOCK_EX)

        def _unlock(fd: int) -> None:
            fcntl.flock(fd, fcntl.LOCK_UN)

    except ImportError:  # pragma: no cover
        def _lock(fd: int) -> None:
            pass

        def _unlock(fd: int) -> None:
            pass


@contextmanager
def file_lock(path: Path, timeout: float = 5.0) -> Iterator[None]:
    """Simple cross-platform file lock."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    start_time = time.time()
    
    # Ensure directory exists
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    
    while True:
        try:
            # Open for writing (creates if not exists)
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
            try:
                _lock(fd)
                yield
                try:
                    _unlock(fd)
                except (IOError, OSError):
                    pass # Best effort unlock before close
                break
            finally:
                os.close(fd)
        except (IOError, OSError):
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Could not acquire lock on {path} after {timeout}s")
            time.sleep(0.1)


def atomic_write_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(data)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass

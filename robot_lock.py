"""Cross-entry-point single-instance lock for the DEMEX robot."""
import fcntl
import os
from pathlib import Path


def acquire_robot_lock(lock_path=None):
    """Return a held lock handle, or None if another DEMEX instance owns it."""
    path = Path(lock_path) if lock_path is not None else (
        Path(__file__).resolve().parent / ".demex-robot.lock"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        handle.close()
        return None

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle

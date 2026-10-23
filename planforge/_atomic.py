"""Cross-platform atomic file replacement helpers.

On Windows, cloud sync clients (such as OneDrive) and real-time antivirus
scanners can briefly hold newly closed temporary files or target files open
without delete-sharing, causing transient ``PermissionError`` (for example
``[WinError 32]`` or ``[WinError 5]``) during ``os.replace`` or ``os.unlink``.
"""

from __future__ import annotations

import os
import time

_RETRY_DELAYS: tuple[float, ...] = (0.01, 0.02, 0.04, 0.08, 0.15, 0.25)


def _is_transient_lock_error(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in (5, 32)


def atomic_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    """Atomically replace ``dst`` with ``src``, retrying transient file locks."""
    for delay in _RETRY_DELAYS:
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            if not _is_transient_lock_error(exc):
                raise
            time.sleep(delay)
    os.replace(src, dst)


def best_effort_unlink(path: str | os.PathLike[str] | None) -> None:
    """Remove a temporary file without failing callers on cleanup errors."""
    if path is None:
        return
    for delay in _RETRY_DELAYS[:3]:
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if not _is_transient_lock_error(exc):
                return
            time.sleep(delay)
    try:
        os.unlink(path)
    except OSError:
        pass


__all__ = ["atomic_replace", "best_effort_unlink"]

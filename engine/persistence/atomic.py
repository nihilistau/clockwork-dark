"""
Atomic File Writes
==================

Crash-safe JSON persistence.

A half-written save is worse than no save: the player loses the run *and*
believes they still have it. Every write here lands whole or not at all.

Windows specifics that shaped this module:
  - ``os.replace`` fails with PermissionError if any handle holds the target,
    so nothing may keep a read handle open across a save.
  - The temp file must live in the destination directory; ``os.replace`` is
    only atomic within a single volume.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def write_json_atomic(path: Path, payload: Any, *, keep_backup: bool = True) -> None:
    """
    Write JSON to path atomically, optionally preserving the previous version.

    Args:
        path: Destination file.
        payload: JSON-serializable object.
        keep_backup: Copy the existing file to ``<name>.bak`` before replacing.

    Raises:
        OSError: If the write or replace fails. The destination is left
            untouched in that case.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if keep_backup and path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            backup.write_bytes(path.read_bytes())
        except OSError as exc:
            # A failed backup must not block the save itself.
            logger.warning(
                "[persistence] Backup failed (operation=write_json_atomic, path=%s): %s",
                backup,
                exc,
            )

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def read_json(path: Path, *, fallback_to_backup: bool = True) -> Any:
    """
    Read JSON, falling back to the ``.bak`` sibling if the primary is corrupt.

    Returns None when neither file is readable.
    """
    path = Path(path)
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        if not candidate.exists():
            continue
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if candidate != path:
                logger.warning(
                    "[persistence] Recovered from backup "
                    "(operation=read_json, path=%s)",
                    candidate,
                )
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "[persistence] Unreadable save (operation=read_json, path=%s): %s",
                candidate,
                exc,
            )
            if not fallback_to_backup:
                break
    return None


def append_jsonl(path: Path, record: Any) -> None:
    """Append one JSON record to a line-delimited log. Never raises."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        logger.warning(
            "[persistence] Transcript append failed "
            "(operation=append_jsonl, path=%s): %s",
            path,
            exc,
        )

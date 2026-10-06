"""
The Supervisor's Logs
=====================

Each child's stdout and stderr are read by the supervisor and written to
``<root>/hosting/logs/<process>.log`` (``worker-<slug>``, ``frontdoor``, and
``supervisor`` for its own), rotated at ``hosting.observability.log_max_mb``,
keeping ``log_keep`` rotated files (``<process>.log.1`` the newest), and
echoed to the supervisor's stdout prefixed ``[<process>]``, so ``docker
logs`` still shows everything (spec §14.3).

The files are the operator's to read on disk; the admin panel never shows log
text (spec §14.10). A line is read with a bounded ``readline`` so one child
that writes without newlines cannot grow the supervisor's memory.

NOTHING HERE MAY STOP THE SUPERVISOR (T10 fix round 1):

- THE ECHO NEVER BLOCKS. A line is put on a bounded queue with
  ``put_nowait`` and written to stdout by one echo thread. A stdout nobody
  reads (a Windows console in QuickEdit selection, a paused pager, a stuck
  log shipper) fills the queue and further lines are DROPPED from the echo
  and counted; the count is said once the echo moves again. The files get
  every line whatever the echo does.
- A FAILED ROTATION NEVER STOPS A LOG. On Windows a rename fails while
  another process holds the file open (an operator's ``Get-Content -Wait``,
  an antivirus scan): the log keeps writing to the file it has, past the
  cap, notes the failure once in the file, and tries again after
  ``ROTATE_RETRY_SECONDS``. ``RotatingLog.write`` never raises, and a capture
  thread keeps draining its child's pipe whatever happens to the file, so a
  child can never block on its own stdout.

Version: v0.2.0 [2026-10-01]
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Optional, TextIO

#: The longest line read from a child at once, in bytes; longer is split.
MAX_LINE_BYTES = 16 * 1024

#: Lines the echo holds before it drops (and counts) the rest.
ECHO_QUEUE_LINES = 10_000

#: How long a log waits after a failed rotation before it tries again.
ROTATE_RETRY_SECONDS = 30.0


class RotatingLog:
    """One process's log file, rotated by size. Thread-safe; ``write`` never raises."""

    def __init__(self, path: Path, max_bytes: int, keep: int) -> None:
        self.path = path
        self.max_bytes = max(1, int(max_bytes))
        self.keep = max(1, int(keep))
        self.retry_seconds = ROTATE_RETRY_SECONDS
        #: A leaf: held across one append (and a rotation's renames).
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file: Any = open(path, "ab")
        self._size = path.stat().st_size
        self._retry_at = 0.0
        self._closed = False
        #: Rotations that failed (for the tests and the operator's eye).
        self.failed_rotations = 0

    def write(self, line: bytes) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                if (
                    self._size
                    and self._size + len(line) > self.max_bytes
                    and time.monotonic() >= self._retry_at
                ):
                    self._rotate()
                if self._file is None:
                    self._file = open(self.path, "ab")
                self._file.write(line)
                self._file.flush()
                self._size += len(line)
            except Exception:  # noqa: BLE001 -- a log must never stop its caller
                self._reopen()

    def _rotate(self) -> None:
        """Rename the files along; on failure keep the open file and retry later."""
        try:
            self._file.close()
            for index in range(self.keep - 1, 0, -1):
                older = self.path.with_name(f"{self.path.name}.{index}")
                if older.exists():
                    os.replace(older, self.path.with_name(f"{self.path.name}.{index + 1}"))
            os.replace(self.path, self.path.with_name(f"{self.path.name}.1"))
        except OSError as exc:
            self.failed_rotations += 1
            self._retry_at = time.monotonic() + self.retry_seconds
            self._reopen()
            if self.failed_rotations == 1 or self.failed_rotations % 100 == 0:
                note = (
                    f"[log] rotation failed ({exc.strerror or exc}); still writing here, "
                    f"retrying in {int(self.retry_seconds)} s\n"
                )
                self._file.write(note.encode("utf-8", "replace"))
            return
        self._file = open(self.path, "ab")
        self._size = 0

    def _reopen(self) -> None:
        try:
            if self._file is not None:
                self._file.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._file = open(self.path, "ab")
            self._size = self.path.stat().st_size
        except OSError:
            self._file = None  # tried again on the next write

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._file is not None:
                try:
                    self._file.close()
                except OSError:
                    pass
                self._file = None


class LogHub:
    """
    The supervisor's log directory and its echo to stdout.

    ``line`` writes the file (local disk, synchronously) and QUEUES the echo:
    it never waits on stdout. One echo thread writes the queue out.
    """

    def __init__(self, directory: Path, *, max_mb: int, keep: int, echo: Optional[TextIO]) -> None:
        self.directory = directory
        self.max_bytes = int(max_mb) * 1024 * 1024
        self.keep = int(keep)
        self.echo = echo
        directory.mkdir(parents=True, exist_ok=True)
        self._logs: dict[str, RotatingLog] = {}
        #: A leaf: held while a process's file is looked up or first opened.
        self._logs_lock = threading.Lock()
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=ECHO_QUEUE_LINES)
        #: Lines dropped from the echo since the last report (the files have them).
        self.dropped = 0
        self._dropped_lock = threading.Lock()
        self._echo_thread: Optional[threading.Thread] = None
        if echo is not None:
            self._echo_thread = threading.Thread(target=self._echo_loop, name="log-echo", daemon=True)
            self._echo_thread.start()

    def log(self, process: str) -> RotatingLog:
        with self._logs_lock:
            found = self._logs.get(process)
            if found is None:
                found = RotatingLog(self.directory / f"{process}.log", self.max_bytes, self.keep)
                self._logs[process] = found
            return found

    def line(self, process: str, text: str) -> None:
        """One line from ``process``: to its file, and queued for the echo. Never blocks on stdout."""
        clean = text.rstrip("\r\n")
        self.log(process).write((clean + "\n").encode("utf-8", "replace"))
        if self._echo_thread is None:
            return
        try:
            self._queue.put_nowait(f"[{process}] {clean}\n")
        except queue.Full:
            with self._dropped_lock:
                self.dropped += 1

    def _echo_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            with self._dropped_lock:
                dropped, self.dropped = self.dropped, 0
            try:
                if dropped:
                    self.echo.write(  # type: ignore[union-attr]
                        f"[supervisor] {dropped} log lines were not echoed here (stdout was not "
                        "being read); the log files have them\n"
                    )
                self.echo.write(item)  # type: ignore[union-attr]
                self.echo.flush()  # type: ignore[union-attr]
            except (OSError, ValueError):
                pass

    def capture(self, process: str, stream: Any) -> threading.Thread:
        """Read a child's merged stdout/stderr until it closes, on a thread of its own."""
        self.log(process)

        def pump() -> None:
            try:
                while True:
                    try:
                        raw = stream.readline(MAX_LINE_BYTES)
                    except (OSError, ValueError):
                        return  # the pipe itself is gone
                    if not raw:
                        return
                    try:
                        self.line(process, raw.decode("utf-8", "replace"))
                    except Exception:  # noqa: BLE001 -- keep draining whatever the file does
                        pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        thread = threading.Thread(target=pump, name=f"log-{process}", daemon=True)
        thread.start()
        return thread

    def close(self, timeout: float = 2.0) -> None:
        """Flush what the echo can within ``timeout``, and close every file."""
        thread = self._echo_thread
        if thread is not None:
            try:
                self._queue.put(None, timeout=timeout)
            except queue.Full:
                pass
            thread.join(timeout)
        with self._logs_lock:
            logs = list(self._logs.values())
        for log in logs:
            log.close()


class HubHandler(logging.Handler):
    """The supervisor's own logging, into ``supervisor.log`` and the echo."""

    def __init__(self, hub: LogHub, process: str = "supervisor") -> None:
        super().__init__()
        self.hub = hub
        self.process = process
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.hub.line(self.process, self.format(record))
        except Exception:  # noqa: BLE001 -- logging must never raise
            self.handleError(record)


__all__ = ["ECHO_QUEUE_LINES", "HubHandler", "LogHub", "MAX_LINE_BYTES", "ROTATE_RETRY_SECONDS", "RotatingLog"]

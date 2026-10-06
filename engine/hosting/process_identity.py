"""
Hosted Mode: a Process Is Its Pid AND Its Creation Time
=======================================================

The operating system reuses pids -- Windows quickly, and under load within
seconds -- so a pid noted a while ago may by now name ANY process on the
machine. Nothing here signals a pid on its own (v0.20.0 T15 fix rounds 1-2):

- ``created(pid)``: when the RUNNING process holding ``pid`` started, or
  None (no such process, exited, a zombie, or no way to ask here);
- ``Identity(pid, created)``: one process, noted while it was certainly the
  one meant (a gunicorn worker notes its master at ``post_worker_init``; a
  test probe notes itself as it starts);
- ``alive(identity)``: the pid's process now has that creation time;
- ``terminate(identity)``: signal it ONLY if it does, checked and signalled
  through ONE handle where the platform has one (``OpenProcess`` on
  Windows, a pidfd on Linux), so the pid cannot change hands in between.
  An identity whose creation time is unknown is never signalled: it is
  logged and left.

WHAT "CREATION TIME" IS, AND THE TOLERANCE. Windows: ``GetProcessTimes``'
creation FILETIME, in seconds since the epoch -- exact, read from the
process object. Linux: ``/proc/<pid>/stat`` field 22, the start time in
clock ticks SINCE BOOT, as seconds since boot. ``btime`` (the boot time in
``/proc/stat``) is deliberately NOT added: it is computed by the kernel from
the wall clock and is known to wobble by about a second between reads on
some kernels (T15 fix round 2, N6), which would make two reads of one
process disagree. Without it both values are exact, so the comparison's
tolerance is ZERO, on purpose: a looser match would let a pid reused within
the window pass as the process it replaced, the one failure this module
exists to prevent. A mismatch only ever means "do not signal" (fail safe).
On any other platform (macOS) ``created`` is None and nothing is signalled.

Used by ``engine/hosting/boot.py`` (stopping the gunicorn master) and, through
``tests/process_identity.py``, by the suite's probes and orphan guard. Hosted
only: local mode never imports it.

Version: v0.1.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Windows' FILETIME of the Unix epoch (100 ns ticks since 1601-01-01).
_EPOCH_AS_FILETIME = 116444736000000000

_QUERY_LIMITED_INFORMATION = 0x1000
_TERMINATE = 0x0001
_STILL_ACTIVE = 259

#: How far apart two creation times of ONE process may read and still match:
#: zero (see the module docstring -- neither platform's value jitters, and a
#: wider match would let a reused pid through).
TOLERANCE_SECONDS = 0.0


@dataclass(frozen=True)
class Identity:
    """One process: its pid and its creation time (None: unknown, never signalled)."""

    pid: int
    created: Optional[float]


def _windows() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return ctypes, wintypes, kernel32


def _win_created(ctypes: Any, wintypes: Any, kernel32: Any, handle: Any) -> Optional[float]:
    """The creation time of the process ``handle`` names, while it is still running."""
    code = wintypes.DWORD()
    if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != _STILL_ACTIVE:
        return None
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        return None
    ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    return (ticks - _EPOCH_AS_FILETIME) / 1e7


def _linux_created(pid: int) -> Optional[float]:
    """``/proc/<pid>/stat`` field 22 as seconds since boot, while the process is not a zombie."""
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
    except (OSError, ValueError):
        return None
    fields = stat.rsplit(")", 1)[-1].split()
    if not fields or fields[0] in ("Z", "X"):
        return None
    try:
        start_ticks = int(fields[19])  # field 22 counted from 1; fields[0] is field 3
    except (IndexError, ValueError):
        return None
    return start_ticks / os.sysconf("SC_CLK_TCK")


def created(pid: int) -> Optional[float]:
    """The creation time of the RUNNING process ``pid``, or None (see the module docstring)."""
    if pid <= 0:
        return None
    if os.name == "nt":
        ctypes, wintypes, kernel32 = _windows()
        handle = kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            return _win_created(ctypes, wintypes, kernel32, handle)
        finally:
            kernel32.CloseHandle(handle)
    if Path("/proc/self/stat").exists():
        return _linux_created(pid)
    return None


def same(recorded: Optional[float], now: Optional[float]) -> bool:
    """Whether two creation times are one process's: both known and within ``TOLERANCE_SECONDS``."""
    return recorded is not None and now is not None and abs(recorded - now) <= TOLERANCE_SECONDS


def identify(pid: int) -> Identity:
    """``pid``'s identity NOW (call it while the process is certainly the one meant)."""
    return Identity(int(pid), created(int(pid)))


def me() -> Identity:
    """This process's identity."""
    return identify(os.getpid())


def alive(identity: Identity) -> bool:
    """Whether the process ``identity`` names is running (never True for an unknown creation time)."""
    return same(identity.created, created(identity.pid))


def terminate(identity: Identity, signum: int = signal.SIGTERM) -> bool:
    """
    Signal the process ``identity`` names (``signum``; on Windows, which has
    no signals to send, ``TerminateProcess``), IF the process holding its pid
    is still that one: True when signalled. Never signals a pid whose identity
    is unknown or does not match (it is logged and left).
    """
    if identity.created is None or identity.pid <= 1:
        logger.warning("[hosting] Not signalled: pid %d cannot be verified (operation=terminate)", identity.pid)
        return False
    if os.name == "nt":
        ctypes, wintypes, kernel32 = _windows()
        # One handle for the check and the kill: the process it names cannot
        # change while it is open, so the pid cannot be reused in between.
        handle = kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION | _TERMINATE, False, int(identity.pid))
        if not handle:
            return False
        try:
            if not same(identity.created, _win_created(ctypes, wintypes, kernel32, handle)):
                logger.warning("[hosting] Not signalled: pid %d is another process now (operation=terminate)", identity.pid)
                return False
            return bool(kernel32.TerminateProcess(handle, 1))
        finally:
            kernel32.CloseHandle(handle)
    pidfd_open = getattr(os, "pidfd_open", None)
    send = getattr(signal, "pidfd_send_signal", None)
    if pidfd_open is not None and send is not None:
        try:
            fd = pidfd_open(int(identity.pid))
        except OSError:
            return False
        try:
            # The pidfd names the process that held the pid when it was
            # opened; if that one still has the recorded start time, it is ours.
            if not same(identity.created, _linux_created(identity.pid)):
                logger.warning("[hosting] Not signalled: pid %d is another process now (operation=terminate)", identity.pid)
                return False
            send(fd, signum)
            return True
        except OSError:
            return False
        finally:
            os.close(fd)
    # No handle to hold: check, then signal (a window of microseconds).
    if not same(identity.created, created(identity.pid)):
        logger.warning("[hosting] Not signalled: pid %d is another process now (operation=terminate)", identity.pid)
        return False
    try:
        os.kill(int(identity.pid), signum)
    except OSError:
        return False
    return True


__all__ = ["Identity", "TOLERANCE_SECONDS", "alive", "created", "identify", "me", "same", "terminate"]

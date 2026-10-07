"""
Windows Job Objects for the suite (v0.21.1 T2): a process tree that ends
with the process holding it.

``Job`` is a Job Object with KILL_ON_JOB_CLOSE, held through its handle:
closing the handle (or the holder's exit, which closes it) ends every process
in the job. ``scripts/run_tests.py`` puts the pytest it starts in one (``adopt``,
on a SUSPENDED process), and ``contain_session`` puts the test session ITSELF
in one, so a bare ``pytest`` whose test hung or timed out (the thread
method's ``os._exit`` skips fixture finalizers) takes every descendant with
it when it ends, however it ends. A child started with
CREATE_NEW_PROCESS_GROUP (the hosted supervisor) is still in the job: only
CREATE_BREAKAWAY_FROM_JOB leaves it, and nothing here uses it (the job does
not allow it).

POSIX has no Job Object: ``contain_session`` does nothing there, and
run_tests.py uses a process group instead (its docstring).

No pid is ever signalled here: the job is reached only through its handle.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Optional

#: Where the session's job handle is kept for the life of the process
#: (``contain_session``): on ``sys``, so both imports of this module (as
#: ``tests.process_jobs`` and through a second conftest copy) share it.
_SESSION_ATTR = "_clockwork_session_job"

CREATE_SUSPENDED = 0x00000004


class Job:
    """A Windows Job Object with KILL_ON_JOB_CLOSE, held through its handle
    (not inheritable: no security attributes)."""

    _EXTENDED_LIMIT_INFORMATION = 9
    _KILL_ON_JOB_CLOSE = 0x2000

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
        ntdll.NtResumeProcess.restype = ctypes.c_long
        self._ctypes, self._k32, self._ntdll = ctypes, k32, ntdll

        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle: Optional[int] = handle
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = self._KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(handle, self._EXTENDED_LIMIT_INFORMATION,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(err)

    def _assign(self, process_handle: Any) -> None:
        if not self._k32.AssignProcessToJobObject(self.handle, process_handle):
            raise self._ctypes.WinError(self._ctypes.get_last_error())

    def adopt(self, proc: subprocess.Popen) -> None:
        """Put the SUSPENDED ``proc`` in the job, then let it run: it can have
        started nothing outside the job. Popen closes the main thread's
        handle, so the process is resumed whole (``NtResumeProcess``)."""
        raw = getattr(proc, "_handle", None)  # Popen's own process handle (private; 3.11-3.14)
        if raw is None:
            raise RuntimeError("subprocess.Popen has no _handle here: cannot put the run in a Job Object")
        self._assign(int(raw))
        status = self._ntdll.NtResumeProcess(int(raw))
        if status != 0:
            raise OSError(f"NtResumeProcess failed (NTSTATUS {status & 0xFFFFFFFF:#x})")

    def assign_current(self) -> None:
        """Put THIS process in the job (its pseudo-handle)."""
        self._assign(self._k32.GetCurrentProcess())

    def terminate(self, code: int) -> bool:
        """End every process in the job now; False when the call failed."""
        return bool(self.handle) and bool(self._k32.TerminateJobObject(self.handle, code))

    def close(self) -> None:
        """Close the job: KILL_ON_JOB_CLOSE ends every process still in it."""
        if self.handle:
            self._k32.CloseHandle(self.handle)
            self.handle = None


def wants_session_job(environ: Any = None, pid: Optional[int] = None) -> bool:
    """Whether this pytest process should take its own kill-on-close job
    (Windows): when the sandbox marker names THIS process -- a serial
    session, an xdist controller at configure time, and (T5 review F6) an
    xdist WORKER, whose own job nests in its controller's. A worker that
    dies (a thread-method timeout's ``os._exit``, a crash) then takes its
    hosted supervisor and children with it at once, not when the whole run
    ends. Never a sandboxed child (a marker another pid set)."""
    if os.name != "nt":
        return False
    environ = os.environ if environ is None else environ
    raw = str(environ.get("CLOCKWORK_TEST_SANDBOX", "") or "")
    return raw.partition(os.pathsep)[0].strip() == str(os.getpid() if pid is None else pid)


def contain_session() -> Optional[Job]:
    """Put this process in a kill-on-close Job Object (Windows; once per
    process), so every descendant ends when it does. The handle is kept on
    ``sys`` for the life of the process and NEVER closed explicitly: closing
    it would end this process too. The process's own exit closes it, an
    ``os._exit`` included. None on POSIX, or when the job cannot be made
    (reported on stderr; the session runs on without it)."""
    if os.name != "nt":
        return None
    held = getattr(sys, _SESSION_ATTR, None)
    if held is not None:
        return held
    job: Optional[Job] = None
    try:
        job = Job()
        job.assign_current()
    except OSError as exc:
        if job is not None:
            job.close()  # never assigned: closing it ends nothing
        sys.stderr.write(f"[tests] no session Job Object ({exc}); a hung test's children may outlive it\n")
        return None
    setattr(sys, _SESSION_ATTR, job)
    return job


__all__ = ["CREATE_SUSPENDED", "Job", "contain_session", "wants_session_job"]

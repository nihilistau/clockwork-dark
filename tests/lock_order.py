"""
A lock-order checker for the engine's named locks (v0.20.0 T6 fix round 1).

``engine/locks.py`` states ONE total order for every lock the engine names: a
thread holding a lock may take only a lock later in the list. This helper
wraps each of those locks in a ``TrackedLock`` that records, per thread, what
is held when another is taken, and records a violation whenever a lock is
taken while a LATER one is held (re-taking an ``RLock`` already held is fine).
It checks the order, not the luck: an inversion fails whether or not the
interleaving that would deadlock happened in this run.

``ORDER`` is spelled out here rather than read from ``engine/locks.py`` so the
checker also runs against an engine that predates that file (T6's canary on
3c0ca34); ``tests/test_thread_safety.py`` pins the two lists equal.

Module locks are replaced with ``monkeypatch.setattr``. The two INSTANCE locks
in the order (a backend's and an Oracle's) are made tracked by giving their
module a ``threading`` whose ``Lock()`` returns one, so every backend or Oracle
built while the checker is installed carries a tracked lock.

Version: v0.1.0 [2026-10-01]
"""

from __future__ import annotations

import importlib
import sys
import threading
import traceback
from types import SimpleNamespace
from typing import Any, Optional

import pytest

#: engine/locks.py's LOCK ORDER, outer first.
ORDER: tuple[str, ...] = (
    "engine.games.caches._warm_lock",
    "engine.games.registry._lock",
    "engine.game.quests._grammar_lock",
    "engine.llm.backend._backend_lock",
    "engine.llm.backend.LMStudioBackend._lock",
    "engine.llm.registry._registry_lock",
    "engine.llm.profiles._cache_lock",
    "engine.llm.gate._lanes_lock",
    "engine.agents.mechanics._ENGINES_LOCK",
    "engine.mcp.skills_server._server_lock",
    "engine.media.stt._provider_lock",
    "engine.media.stt_whisper._models_lock",
    "engine.llm.client._client_lock",
    "engine.llm.ollama._client_lock",
    "engine.lore.manager._manager_lock",
    "engine.mcp.scene_rules_engine._rules_lock",
    "engine.media.queue._queue_lock",
    "engine.media.providers._worker_lock",
    "engine.media.tts._worker_lock",
    "engine.scenes.default_scene._store_lock",
    "engine.telemetry.oracle._oracle_lock",
    "engine.persistence.saves._stores_lock",
    "engine.persistence.saves._migrated_lock",
    "engine.persistence.saves._index_locks_lock",
    "engine.telemetry.oracle.Oracle._lock",
    "engine.config._config_lock",
)

#: engine/locks.py's LEAF LOCKS: per-object locks under which no blocking
#: acquisition of any other lock is made.
LEAVES: tuple[str, ...] = (
    "engine.persistence.saves.SaveStore._lock",
    "engine.llm.registry.ModelRegistry._lock",
    "engine.lore.manager.LoreManager._write_lock",
    "engine.session.store.SessionStore._guard",
    "engine.hosting.limits.LoginLimiter._lock",
    "engine.hosting.limits.ActionLimiter._lock",
    "engine.hosting.sockets.SocketRegistry._lock",
    "engine.hosting.bus.BusClient._lock",
    "engine.hosting.supervisor.queue.LaneQueue._cond",
    "engine.hosting.limits.LongHolds._lock",
    "engine.hosting.admin.users.OneTimeShown._lock",
    "engine.hosting.supervisor.process.AuditWriter._lock",
    "engine.hosting.limits.TurnSlots._lock",
    "engine.hosting.lanes_remote.RemoteLanes._lock",
)

#: Instance locks: ``(module, name)``; the module's ``threading.Lock`` and
#: ``RLock``, called at run time, are what build them (every other lock in these
#: modules is built at import, before the checker is installed). A module named
#: ONCE has every lock it builds tracked under that one name; a module named
#: more than once (v0.20.0 T15: ``engine.hosting.limits``) has each lock named
#: by the class whose ``__init__`` builds it, and its other locks untracked.
INSTANCE_LOCKS: tuple[tuple[str, str], ...] = (
    ("engine.llm.backend", "engine.llm.backend.LMStudioBackend._lock"),
    ("engine.telemetry.oracle", "engine.telemetry.oracle.Oracle._lock"),
    ("engine.persistence.saves", "engine.persistence.saves.SaveStore._lock"),
    ("engine.llm.registry", "engine.llm.registry.ModelRegistry._lock"),
    ("engine.lore.manager", "engine.lore.manager.LoreManager._write_lock"),
    ("engine.session.store", "engine.session.store.SessionStore._guard"),
    ("engine.hosting.limits", "engine.hosting.limits.LoginLimiter._lock"),
    ("engine.hosting.sockets", "engine.hosting.sockets.SocketRegistry._lock"),
    # The supervisor's queue (T11 fix round 1): its condition's lock is an
    # RLock, built at run time, so a queue built under the checker is tracked.
    ("engine.hosting.supervisor.queue", "engine.hosting.supervisor.queue.LaneQueue._cond"),
    # v0.20.0 T15 (from T14's report and T13's): three more leaves, each
    # tracked by its class.
    ("engine.hosting.limits", "engine.hosting.limits.ActionLimiter._lock"),
    ("engine.hosting.limits", "engine.hosting.limits.LongHolds._lock"),
    ("engine.hosting.admin.users", "engine.hosting.admin.users.OneTimeShown._lock"),
    ("engine.hosting.supervisor.process", "engine.hosting.supervisor.process.AuditWriter._lock"),
    # The final review's leaves on the worker's turn path.
    ("engine.hosting.limits", "engine.hosting.limits.TurnSlots._lock"),
    ("engine.hosting.lanes_remote", "engine.hosting.lanes_remote.RemoteLanes._lock"),
)

#: The lane semaphores, one name for all (``engine/llm/gate.py``).
LANE = "engine.llm.gate.lane"

RANK = {name: i for i, name in enumerate(ORDER)}


class Checker:
    """Per-thread held stacks, and every out-of-order acquisition seen."""

    def __init__(self) -> None:
        self._held = threading.local()
        self.violations: list[str] = []
        self.acquired: set[str] = set()

    def _stack(self) -> list[str]:
        stack = getattr(self._held, "stack", None)
        if stack is None:
            stack = self._held.stack = []
        return stack

    def _violation(self, message: str) -> None:
        where = "".join(traceback.format_stack(limit=8)[:-3])
        self.violations.append(f"{threading.current_thread().name}: {message}\n{where}")

    def before(self, name: str, *, blocking: bool = True) -> None:
        for held in self._stack():
            if held == name:
                continue  # an RLock re-entered
            if held in LEAVES:
                if blocking:
                    self._violation(f"took {name} while holding the leaf {held}")
                continue
            if name == LANE:
                if held != LANE:
                    self._violation(f"took a lane semaphore while holding {held}")
                continue
            if held == LANE or name in LEAVES:
                continue  # anything may be taken under a lane; a leaf under anything
            if RANK[held] > RANK[name]:
                self._violation(
                    f"took {name} (#{RANK[name] + 1}) while holding {held} (#{RANK[held] + 1})"
                )

    def push(self, name: str) -> None:
        self._stack().append(name)
        self.acquired.add(name)

    def pop(self, name: str) -> None:
        stack = self._stack()
        for i in range(len(stack) - 1, -1, -1):
            if stack[i] == name:
                del stack[i]
                return


class TrackedLock:
    """A Lock or RLock that reports each acquisition to a ``Checker``."""

    def __init__(self, inner: Any, name: str, checker: Checker) -> None:
        self._inner = inner
        self.name = name
        self._checker = checker

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        self._checker.before(self.name, blocking=blocking)
        got = self._inner.acquire(blocking, timeout)
        if got:
            self._checker.push(self.name)
        return got

    def release(self) -> None:
        self._inner.release()
        self._checker.pop(self.name)

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *exc: Any) -> None:
        self.release()

    def locked(self) -> bool:
        return self._inner.locked()

    def _is_owned(self) -> bool:  # RLock's, used by Condition and by tests
        return self._inner._is_owned()


class TrackedSemaphore:
    """A lane semaphore that reports each acquisition to a ``Checker``."""

    def __init__(self, inner: Any, checker: Checker) -> None:
        self._inner = inner
        self._checker = checker

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        self._checker.before(LANE, blocking=blocking)
        got = self._inner.acquire(blocking, timeout)
        if got:
            self._checker.push(LANE)
        return got

    def release(self, n: int = 1) -> None:
        self._inner.release(n)
        self._checker.pop(LANE)

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *exc: Any) -> None:
        self.release()


def _stand_in_threading(**overrides: Any) -> Any:
    """A stand-in ``threading`` module with some factories replaced."""
    shim = SimpleNamespace(**{k: getattr(threading, k) for k in dir(threading) if not k.startswith("__")})
    for key, value in overrides.items():
        setattr(shim, key, value)
    return shim


def _class_name(name: str) -> str:
    """``engine.mod.Class._lock`` -> ``Class``."""
    return name.rsplit(".", 2)[-2]


def _threading_with_tracked_locks(names: list[str], checker: Checker) -> Any:
    """
    ``threading`` whose ``Lock()`` and ``RLock()`` are tracked: as the one
    name when ``names`` holds one, else as the name of the class (or a base
    of it) whose method builds the lock -- the caller's ``self`` -- and left
    untracked when no named class built it.
    """
    by_class = {_class_name(name): name for name in names}

    def pick(frame: Any) -> Optional[str]:
        if len(names) == 1:
            return names[0]
        owner = frame.f_locals.get("self") if frame is not None else None
        if owner is None:
            return None
        for cls in type(owner).__mro__:
            if cls.__name__ in by_class:
                return by_class[cls.__name__]
        return None

    def factory(real: Any) -> Any:
        def build() -> Any:
            name = pick(sys._getframe(1))
            return real() if name is None else TrackedLock(real(), name, checker)

        return build

    return _stand_in_threading(Lock=factory(threading.Lock), RLock=factory(threading.RLock))


def _threading_with_tracked_lock(name: str, checker: Checker) -> Any:
    """``threading`` whose ``Lock()`` and ``RLock()`` are tracked as ``name``."""
    return _threading_with_tracked_locks([name], checker)


def install(monkeypatch: pytest.MonkeyPatch, checker: Optional[Checker] = None) -> Checker:
    """Wrap every lock in ``ORDER`` that this engine has. Undone by ``monkeypatch``."""
    checker = checker or Checker()
    instance_names = {name for _module, name in INSTANCE_LOCKS}
    for name in ORDER:
        if name in instance_names:
            continue
        module_name, _, attr = name.rpartition(".")
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        real = getattr(module, attr, None)
        if real is None or isinstance(real, TrackedLock):
            continue
        monkeypatch.setattr(module, attr, TrackedLock(real, name, checker))
    by_module: dict[str, list[str]] = {}
    for module_name, name in INSTANCE_LOCKS:
        by_module.setdefault(module_name, []).append(name)
    for module_name, names in by_module.items():
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "threading", _threading_with_tracked_locks(names, checker))
    gate = importlib.import_module("engine.llm.gate")
    monkeypatch.setattr(
        gate,
        "threading",
        _stand_in_threading(
            BoundedSemaphore=lambda value=1: TrackedSemaphore(threading.BoundedSemaphore(value), checker)
        ),
    )
    return checker


def report(checker: Checker) -> str:
    """Every violation, once each, for an assertion message."""
    seen: list[str] = []
    for v in checker.violations:
        head = v.split("\n", 1)[0].split(": ", 1)[-1]
        if head not in [s.split("\n", 1)[0].split(": ", 1)[-1] for s in seen]:
            seen.append(v)
    return "\n\n".join(seen)


__all__ = [
    "Checker",
    "INSTANCE_LOCKS",
    "LANE",
    "LEAVES",
    "ORDER",
    "RANK",
    "TrackedLock",
    "TrackedSemaphore",
    "install",
    "report",
]

"""
Engine Locks: the order, and renewal after fork
===============================================

One process serves many sessions on threads (v0.20.0, spec §5.1-§5.2), and the
engine's module state is guarded by the locks below. Two locks taken in
opposite orders by two threads deadlock, so there is ONE TOTAL ORDER: a thread
holding a lock may take only a lock that comes AFTER it in this list, never
one before it (re-taking an RLock it already holds is fine).

LOCK ORDER (outer first):

1. engine.games.caches._warm_lock
2. engine.games.registry._lock
3. engine.game.quests._grammar_lock
4. engine.llm.backend._backend_lock
5. engine.llm.backend.LMStudioBackend._lock
6. engine.llm.registry._registry_lock
7. engine.llm.profiles._cache_lock
8. engine.llm.gate._lanes_lock
9. engine.agents.mechanics._ENGINES_LOCK
10. engine.mcp.skills_server._server_lock
11. engine.media.stt._provider_lock
12. engine.media.stt_whisper._models_lock
13. engine.llm.client._client_lock
14. engine.llm.ollama._client_lock
15. engine.lore.manager._manager_lock
16. engine.mcp.scene_rules_engine._rules_lock
17. engine.media.queue._queue_lock
18. engine.media.providers._worker_lock
19. engine.media.tts._worker_lock
20. engine.scenes.default_scene._store_lock
21. engine.telemetry.oracle._oracle_lock
22. engine.persistence.saves._stores_lock
23. engine.persistence.saves._migrated_lock
24. engine.persistence.saves._index_locks_lock
25. engine.telemetry.oracle.Oracle._lock
26. engine.net._lock
27. engine.config._config_lock

What the order means in practice:

* **The config lock is innermost.** Every other lock's holder may call
  ``get_config``, whose first build takes it; so nothing holding
  ``_config_lock`` takes any other lock. Its holders build the config, drop it
  (``reset_config``, ``set_overlay``) or fill ``_story_paths_by_slug`` on a
  miss, and call nothing that locks. ``reset_config`` walks the cache resets
  AFTER releasing it.
* **The shared HTTP client's lock is next-innermost** (``engine/net.py``,
  v0.21.1): its holder builds the process's one ``httpx.Client`` or SSL
  context and takes no other lock, so a request may be made holding any
  lock above it.
* **Warming is outermost.** ``warm_all_caches`` holds ``_warm_lock`` (not the
  config lock) while its loaders run, so they may take any lock after it: the
  registry's, the grammar's, a getter's, the config's.
* **Activation is next.** ``registry.activate`` holds the registry's lock
  across ``set_overlay`` and the whole reset walk (backend, LLM registry,
  profiles, lanes), all of which come after it.
* ``route_client`` holds a backend's own lock while it builds a client, and a
  client's build reads the config: 5, then 13 or 14, then 25.
* ``save_store_for`` holds ``_stores_lock`` while a store's first build runs
  the legacy migration and then finds its folder's index lock
  (``index_lock_for``): 22, then 23, then 24. The registry's holder only
  reads and fills a dict (v0.20.0 T8: one index lock per save folder, shared
  by every ``SaveStore`` over it).

LEAF LOCKS. Fourteen per-object locks sit outside the list because nothing is
ever taken under them: their holders make no BLOCKING acquisition of any
other lock (the config's included -- a caller reads what it needs from the
config before it takes one). A non-blocking try, which cannot wait, is the
one thing allowed under a leaf.

- engine.persistence.saves.SaveStore._lock
- engine.llm.registry.ModelRegistry._lock
- engine.lore.manager.LoreManager._write_lock
- engine.session.store.SessionStore._guard
- engine.hosting.limits.LoginLimiter._lock
- engine.hosting.limits.ActionLimiter._lock
- engine.hosting.sockets.SocketRegistry._lock
- engine.hosting.bus.BusClient._lock
- engine.hosting.supervisor.queue.LaneQueue._cond
- engine.hosting.limits.LongHolds._lock
- engine.hosting.admin.users.OneTimeShown._lock
- engine.hosting.supervisor.process.AuditWriter._lock
- engine.hosting.limits.TurnSlots._lock
- engine.hosting.lanes_remote.RemoteLanes._lock

(The last three joined the list in v0.20.0 T15, leaves since they were
built: ``LongHolds._lock`` (the front door's long holds, T13) and
``OneTimeShown._lock`` (the panel's one-time passwords, T14) only count,
look up and pop; ``AuditWriter._lock`` (the supervisor's audit writer, T14)
guards only the choice of who builds its thread (started with the lock
released, since T15), and the queue it feeds is a ``queue.Queue``,
``put_nowait`` under no lock of ours.
``tests/test_thread_safety.py`` exercises each under the checker, tracked
by its class.)
(``BusClient._lock``, a hosted worker's bus link, v0.20.0 T10, is held across
one frame's ``sendall`` and a pending-table change; the drain that a
``drain`` request runs holds nothing while it waits. Under the supervisor a
lane acquisition is a bus request (``RemoteLanes``, v0.20.0 T11): it takes
this leaf for one ``sendall`` and then waits on its own event holding
nothing, exactly where a lane semaphore would have been taken; a reply its
caller gave up on is handed to ``on_late`` with the lock released.)
(``SaveStore._lock`` is its save folder's one index lock, from
``index_lock_for``, shared by every store over that folder.)
(``SessionStore._guard``'s idle sweep and its one-session-per-account
release try-acquire each session's turn lock non-blocking: to see whether a
turn is running, and to take an idle or replaced run out of the store with
its turn lock held.) A leaf may be taken while any lock in the list is held.

PRIVATE COUNTERS, leaves in effect: a ``FifoSemaphore``'s condition lock
(hosted mode's lanes, ``engine/llm/gate.py``) is held only to count slots
and waiters, and waited on only to queue; its holder takes no other lock.
The same goes for the single-flight ``Event`` of ``ModelRegistry.models``
(``engine/llm/registry.py``), which a caller waits on holding no lock. A
turn's held-lane share (``gate._Held.share``, an ``RLock``) serialises the
calls made under one admitted turn's narration ticket and is taken, with a
timeout, exactly where that lane would have been.

NOT THREAD LOCKS, and leaves in effect: hosted mode's accounts lock
(``engine/hosting/accounts.py``, an operating-system lock on
``users.json.lock``) is held only across a read, an in-memory change and a
file write, and its holder takes no lock (the password is hashed before it is
taken); and its hashing slots (``AccountStore.hash_slots``, a
``BoundedSemaphore`` of ``hosting.max_concurrent_logins``) are held only
across one scrypt call, taken with a timeout and never while any lock above
is held.

TWO MORE, HELD ACROSS WHOLE OPERATIONS, and safe for a different reason:

* **A session's turn lock** (``GameSession.lock``) is held across a whole
  turn, and every lock above may be taken under it. It is only ever taken
  NON-BLOCKING (a second turn is refused, never queued), so a thread never
  waits for one and it can be in no deadlock.
* **The lane semaphores** (``engine/llm/gate.py``) are held across a model
  call, and the client, backend and config locks may be taken under them.
  One is only ever taken while the thread holds no lock in the list and no
  leaf (a lane may be taken inside another lane, or under a turn lock), and
  always with a timeout.

THE SUPERVISOR'S OWN PROCESS (v0.20.0 T10, ``engine/hosting/supervisor/``)
serves no turn and takes none of the locks above. Its story table's lock
(``Supervisor._lock``) is its one outer lock: its holder may take the bus
server's lock and the operations table's lock, each a leaf there
(``BusServer._lock``, ``Operations._lock``), and it NEVER logs (what it has
to say is queued and logged after release), and never waits on a process, a
socket or a bus reply. The log hub's locks (``RotatingLog._lock``,
``LogHub._logs_lock``, ``LogHub._dropped_lock``) are leaves taken by a
logger holding nothing else, and the echo to stdout goes through a bounded
queue, so no lock is ever held across a write to stdout (T10 fix round 1).
The signal handler takes no lock at all. Nothing takes ``Supervisor._lock``
under a leaf. The model server's queue (``LaneQueue._cond``, a condition
over an ``RLock`` it never re-enters, v0.20.0 T11) is a leaf there too, and
the one supervisor-process lock in the leaf list above (T11 fix round 1:
``tests/lock_order.py`` tracks it): its holder counts, appends and pops,
and never logs, sends a frame or calls back -- the answers a change
produces are sent, and ``on_reclaim`` called, after it is released, so the
bus server's lock and ``Supervisor._lock`` are never taken under it. The
supervisor calls ``pause``/``resume`` holding no lock of its own (they
log), and a drain waits on the condition holding nothing else. The model
server's cached health and model list (``ModelServer._cache_lock``,
``engine/hosting/supervisor/llm.py``, v0.20.0 T16) is a leaf there: held
only to read or replace the two cached answers, never across a probe; and
the model apply, on the operations thread, takes ``Supervisor._lock`` only
as the story operations do. The metrics store's two locks
(``MetricsStore._db_lock``, ``MetricsStore._counts_lock``,
``engine/hosting/supervisor/metrics.py``, v0.20.0 T17) are leaves there:
the first is held across one batch's inserts, a prune or a query (the writer
thread and the fan-out pool), the second across a counter's increment, and
neither holder takes anything else; ``record``, which the selector thread
and ``Supervisor._lock``'s holders call, validates and ``put_nowait``s on a
``queue.Queue`` and takes only the second. The other
supervisor-process locks named in this paragraph are outside the checker:
it runs in the worker's process.

``RemoteLanes`` (``engine/hosting/lanes_remote.py``) holds ``_lock`` only to
read or change its ``_held`` and ``_reclaimed`` sets, never across a bus call
or a lane wait: a leaf, checked above. ``CancelToken``'s hooks
(``engine/llm/gate.py``, T11 fix round 1) take no lock: each change is one
atomic list operation.

Further leaves sit outside the checked list, each real and each holding
nothing else: in the worker process ``DefaultScene._waiting_lock``
(``engine/scenes/default_scene.py``) and the stream-cut lock
(``engine/llm/client.py``); in the front door's process
``WebSocketRelay._lock``, ``_Link._lock`` and ``StoryTable._lock``
(``engine/hosting/frontdoor``). The checker runs in the worker, so it does
not see the front door's.

``tests/lock_order.py`` wraps every lock named here in a checker that records
each thread's acquisitions: it fails on one out of this order, on any
blocking acquisition under a leaf, and on a lane taken while an ordered lock
or a leaf is held; ``tests/test_thread_safety.py`` holds every acquisition of
a turn lock to ``blocking=False`` and runs the checker over the race tests and
over warming, activation, a reset, a Settings save and a turn's getters and
saves racing in parallel. A new module lock is added to this list (and to
that checker's) in the same change; a new per-object lock is a leaf, or has a
place in the list.

RENEWAL AFTER FORK. A process forked while another of its threads holds a lock
starts with that lock held forever (the thread that would release it does not
exist in the child). ``renew_after_fork`` registers each module lock to be
replaced by a fresh one in a forked child (``os.register_at_fork``, POSIX
only; Windows never forks, and the names are recorded there all the same).

Version: v0.1.0 [2026-10-01]
"""

from __future__ import annotations

import os
from typing import Any, Callable

#: ``(module, name)`` of every module lock ``renew_after_fork`` has registered,
#: in registration order. Read by the inventory tests.
RENEWED_AFTER_FORK: list[tuple[str, str]] = []


def renew_after_fork(namespace: dict[str, Any], **factories: Callable[[], Any]) -> None:
    """
    Replace each named module lock with a fresh one in a forked child.

    Args:
        namespace: The owning module's ``globals()``.
        **factories: ``name=threading.Lock`` (or ``RLock``), one per lock.
    """
    module = str(namespace.get("__name__", "?"))
    for name in factories:
        RENEWED_AFTER_FORK.append((module, name))

    def renew() -> None:
        for name, factory in factories.items():
            namespace[name] = factory()

    if hasattr(os, "register_at_fork"):  # POSIX only
        os.register_at_fork(after_in_child=renew)


__all__ = ["RENEWED_AFTER_FORK", "renew_after_fork"]

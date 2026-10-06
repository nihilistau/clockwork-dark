"""
The Supervisor's Operations
===========================

``stories.start``, ``stories.stop`` and ``stories.restart`` never hold the
front door's request open for a drain (spec §14.3): the supervisor answers
``{op_id}`` at once and runs the operation on its ONE operations thread, one
at a time. A second operation while one is queued or running is refused
("another operation is running"). The operations table keeps each one's
steps with the time of each, which the admin pages read with ``ops.list``:
``queued``, ``validating``, ``draining``, ``restarting``, ``done``,
``refused``, ``rolled_back`` (``validating`` and ``rolled_back`` are the
model apply's, ``llm.apply``, v0.20.0 T16: ``supervisor/llm.py``, whose
changes ride in ``Operation.payload``). ``draining`` is the supervisor's drain through
the model server's queue (``Supervisor._drain``, v0.20.0 T11): the story's
new turns paused, until it holds no lane ticket or ``drain_seconds`` run out.

The table holds metadata only: the operation, its story, the acting admin's
name as the front door passed it, the steps and a fixed reason (spec §14.10).

THE AUDIT (v0.20.0 T15, spec §14.11's write-first rule across two
processes): the front door writes an operation's ``started`` row BEFORE it
sends the op, and refuses it if that row cannot be written; the supervisor
writes the outcome (``ok`` when ``done``, ``refused`` otherwise) under the
same ``ref`` once the operation is final (``on_final``), on its audit
writer's thread.

Version: v0.3.0 [2026-10-06]
"""

from __future__ import annotations

import collections
import itertools
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Optional

logger = logging.getLogger(__name__)

#: The steps an operation passes through (spec §14.3), a closed set.
QUEUED = "queued"
VALIDATING = "validating"
DRAINING = "draining"
RESTARTING = "restarting"
DONE = "done"
REFUSED = "refused"
ROLLED_BACK = "rolled_back"
STEPS = (QUEUED, VALIDATING, DRAINING, RESTARTING, DONE, REFUSED, ROLLED_BACK)
FINAL = frozenset({DONE, REFUSED, ROLLED_BACK})

#: The operations ``ops.list`` keeps, newest last.
KEEP_OPERATIONS = 50

#: What a second operation is told.
ANOTHER_RUNNING = "another operation is running"


class OperationRefused(RuntimeError):
    """An operation that cannot be queued (one is running already)."""


@dataclass
class Operation:
    """One row of the operations table."""

    op_id: str
    kind: str
    slug: str
    actor: str
    steps: list[tuple[str, float]] = field(default_factory=list)
    reason: str = ""
    #: Who the outcome's audit row is written for (v0.20.0 T15): what the
    #: front door passed (the admin's id, name and address, and the ``ref``
    #: of the ``started`` row it wrote first) and the audit directory, both
    #: captured when the operation was queued. None: no row (a test's call
    #: with no actor). Never in ``row()``.
    audit: Optional[dict[str, Any]] = field(default=None, repr=False)
    #: What the operation acts on beyond its story (v0.20.0 T16: a model
    #: apply's validated-later changes and its "apply anyway"). Never in
    #: ``row()``: the table holds metadata only.
    payload: Optional[dict[str, Any]] = field(default=None, repr=False)

    @property
    def status(self) -> str:
        return self.steps[-1][0] if self.steps else QUEUED

    def row(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "kind": self.kind,
            "slug": self.slug,
            "actor": self.actor,
            "status": self.status,
            "steps": [{"status": s, "at": round(t, 3)} for s, t in self.steps],
            "reason": self.reason,
        }


Runner = Callable[[Operation, Callable[[str], None]], None]


class Operations:
    """
    The table and the one operations thread. ``runner(op, step)`` performs
    an operation, calling ``step(status)`` as it goes; it sets ``op.reason``
    and ends with ``done`` or ``refused`` (raising counts as ``refused``).
    """

    def __init__(self, runner: Runner, on_final: Optional[Callable[[Operation], None]] = None) -> None:
        self._runner = runner
        #: Called on the operations thread once an operation is final (its
        #: outcome's audit row, v0.20.0 T15); it must not block for long.
        self._on_final = on_final
        #: A leaf: guards the table and the running flag.
        self._lock = threading.Lock()
        self._table: Deque[Operation] = collections.deque(maxlen=KEEP_OPERATIONS)
        self._ids = itertools.count(1)
        self._busy = False
        self._queue: "queue.Queue[Optional[Operation]]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="supervisor-ops", daemon=True)
        self._thread.start()

    def submit(
        self,
        kind: str,
        slug: str,
        actor: str = "",
        audit: Optional[dict[str, Any]] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Queue one operation; its id at once. ``audit``: whom its outcome row
        is written for (``Operation.audit``); ``payload``: what it acts on
        (``Operation.payload``).

        Raises:
            OperationRefused: another operation is queued or running.
        """
        with self._lock:
            if self._busy:
                raise OperationRefused(ANOTHER_RUNNING)
            self._busy = True
            op = Operation(
                op_id=f"op-{next(self._ids)}", kind=kind, slug=slug, actor=actor, audit=audit, payload=payload
            )
            op.steps.append((QUEUED, time.time()))
            self._table.append(op)
        logger.info(
            "[supervisor] Operation queued (operation=%s, op_id=%s, story=%s)", kind, op.op_id, slug
        )
        self._queue.put(op)
        return op.op_id

    def rows(self) -> list[dict[str, Any]]:
        with self._lock:
            return [op.row() for op in self._table]

    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def close(self, timeout: float = 5.0) -> None:
        self._queue.put(None)
        if self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def _step(self, op: Operation, status: str) -> None:
        if status not in STEPS:
            raise ValueError(f"unknown step {status!r}")
        with self._lock:
            op.steps.append((status, time.time()))
        logger.info(
            "[supervisor] Operation %s (operation=%s, op_id=%s, story=%s%s)",
            status,
            op.kind,
            op.op_id,
            op.slug,
            f", reason={op.reason}" if op.reason and status in FINAL else "",
        )

    def _run(self) -> None:
        while True:
            op = self._queue.get()
            if op is None:
                return
            try:
                self._runner(op, lambda status, op=op: self._step(op, status))
            except Exception:  # noqa: BLE001 -- the thread must outlive one failure
                logger.exception("[supervisor] Operation failed (operation=%s, op_id=%s)", op.kind, op.op_id)
                if op.status not in FINAL:
                    op.reason = op.reason or "the operation failed"
                    self._step(op, REFUSED)
            finally:
                if op.status not in FINAL:
                    self._step(op, DONE)
                with self._lock:
                    self._busy = False
                if self._on_final is not None:
                    try:
                        self._on_final(op)
                    except Exception:  # noqa: BLE001 -- the thread must outlive one failure
                        logger.exception(
                            "[supervisor] An operation's outcome hook failed (operation=%s, op_id=%s)",
                            op.kind,
                            op.op_id,
                        )


__all__ = [
    "ANOTHER_RUNNING",
    "DONE",
    "DRAINING",
    "KEEP_OPERATIONS",
    "Operation",
    "OperationRefused",
    "Operations",
    "QUEUED",
    "REFUSED",
    "RESTARTING",
    "ROLLED_BACK",
    "STEPS",
    "VALIDATING",
]

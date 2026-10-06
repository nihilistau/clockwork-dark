"""
Hosted Mode: a Child's Metrics
==============================

How a worker or the front door sends its metrics to the supervisor, which
alone keeps them (spec §14.10; ``engine/hosting/supervisor/metrics.py``).

SENDING NEVER BLOCKS. ``emit(kind, **fields)`` puts one event on a bounded
queue and returns: when the queue is full the event is DROPPED and counted
(``dropped``), never waited for. One sender thread takes events off the queue
and sends each to the supervisor as a ``metric`` notification
(``engine/hosting/bus.py``); the supervisor stamps ``process`` and ``story``
from the connection, validates the event against the closed schema
(``metrics_schema.py``) and stores it or counts it rejected.

THREE STEPS, so nothing runs in a process the supervisor did not start:

1. ``enable()``: the queue. Called by ``boot.prepare_child``, a supervised
   child's first step, and nowhere else -- never in the test suite's own
   process, where an in-process front door or worker builds the same app
   (``emit`` is then a no-op: no queue).
2. ``attach(bus)``: once the child's bus is connected (``install`` for a
   worker, ``frontdoor.connect`` for the front door), the sender thread
   starts and the ERROR handler is installed. A no-op unless ``enable`` ran.
3. ``emit``: from anywhere in the process; a no-op until ``enable``.

THE ERROR HANDLER (``ErrorMetricHandler``) turns every ERROR log record into
an ``error`` event with the logger's NAME and the exception's CLASS, and
never reads the record's message (``getMessage()``, ``msg``, ``args``): a log
line may quote play text, a metric may not. A record already reported by
``errors.public_error`` (which sends its own event, with the player's
reference) carries ``METRIC_REPORTED`` and is skipped.

THE HOOKS. Two emitters live in engine modules local mode also loads, so they
are hooks ``install()`` sets, None by default, never imports of
``engine.hosting`` from engine code (spec §14.10; §1's no-import test):
``engine.scenes.default_scene.turn_metric`` (a hosted ``run_guarded``'s
admission wait, duration and outcome) and ``SessionStore.on_event``
(``engine/session/store.py``: ``created``, ``resumed``, ``released``,
``swept``, ``ended_by_admin``). ``hook_turn`` and ``hook_session`` are what
``install`` sets them to.

Version: v0.1.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Optional

from engine.hosting.metrics_schema import exception_name, safe_name

logger = logging.getLogger(__name__)

#: The most events a child holds before it drops new ones.
MAX_QUEUE = 1000

#: How often the sender says how many it dropped (at most), in seconds.
DROP_LOG_SECONDS = 60.0

#: The attribute a log record carries when ``public_error`` already sent its event.
METRIC_REPORTED = "hosting_metric_reported"

#: The logger name recorded for a record whose own name is not a NAME.
UNNAMED_LOGGER = "unnamed"

#: This process's event queue: None until ``enable`` (so ``emit`` is a no-op).
_queue: Optional["queue.Queue[Any]"] = None

#: The one sender thread (``attach``), and the ERROR handler it installed.
_sender: Optional[threading.Thread] = None
_handler: Optional[logging.Handler] = None

#: Events dropped: a full queue, or a send that failed. Written without a lock
#: (a race loses one count); said by the sender at most once a minute.
dropped = 0


def enable(maxsize: int = MAX_QUEUE) -> None:
    """The queue (a supervised child's first step, ``boot.prepare_child``)."""
    global _queue
    if _queue is None:
        _queue = queue.Queue(maxsize=max(1, int(maxsize)))


def enabled() -> bool:
    return _queue is not None


def emit(kind: str, **fields: Any) -> None:
    """
    Queue one ``kind`` event with ``fields`` (and ``ts`` now). Never blocks
    and never raises: a no-op before ``enable``, dropped and counted when the
    queue is full.
    """
    global dropped
    target = _queue
    if target is None:
        return
    event = {"kind": kind, "ts": round(time.time(), 3), **fields}
    try:
        target.put_nowait(event)
    except queue.Full:
        dropped += 1


def attach(bus: Any) -> None:
    """
    Start the sender over ``bus`` (a connected ``BusClient``) and install the
    ERROR handler. A no-op unless ``enable`` ran in this process; once only.
    """
    global _sender, _handler
    target = _queue
    if target is None or _sender is not None:
        return
    thread = threading.Thread(target=_send_loop, args=(target, bus), name="metrics-sender", daemon=True)
    _sender = thread
    thread.start()
    handler = ErrorMetricHandler(lambda fields: emit("error", **fields))
    _handler = handler
    logging.getLogger().addHandler(handler)


def stop(timeout: float = 5.0) -> None:
    """Stop the sender and remove the handler (the tests; a child just exits)."""
    global _queue, _sender, _handler, dropped
    handler, _handler = _handler, None
    if handler is not None:
        logging.getLogger().removeHandler(handler)
    target, sender = _queue, _sender
    _queue, _sender = None, None
    if target is not None and sender is not None:
        try:
            target.put(None, timeout=timeout)
        except queue.Full:
            pass
        sender.join(timeout)
    dropped = 0


def _send_loop(target: "queue.Queue[Any]", bus: Any) -> None:
    """The sender: one ``metric`` notification per event, until a None or the link is gone."""
    global dropped
    said_at = time.monotonic()
    said = 0
    while True:
        event = target.get()
        if event is None:
            return
        try:
            bus.notify("metric", {"event": event})
        except Exception:  # noqa: BLE001 -- the link is gone or the frame refused: counted, never raised
            dropped += 1
        now = time.monotonic()
        if dropped != said and now - said_at >= DROP_LOG_SECONDS:
            said, said_at = dropped, now
            logger.warning("[metrics] Metrics dropped so far (operation=emit, dropped=%d)", said)


class ErrorMetricHandler(logging.Handler):
    """
    An ERROR record as an ``error`` event: the logger's name and the
    exception's class, never the message (see the module docstring). ``sink``
    receives ``{"ref", "exc_class", "logger"}``.
    """

    def __init__(self, sink: Callable[[dict[str, Any]], None]) -> None:
        super().__init__(level=logging.ERROR)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, METRIC_REPORTED, False):
            return
        exc_info = record.exc_info
        exc_type = exc_info[0] if isinstance(exc_info, tuple) and exc_info else None
        try:
            self._sink(
                {
                    "ref": None,
                    "exc_class": exception_name(exc_type),
                    "logger": safe_name(record.name, UNNAMED_LOGGER),
                }
            )
        except Exception:  # noqa: BLE001 -- a metric must never break logging
            pass


def hook_turn(account: str, admit_wait_ms: float, duration_ms: float, outcome: str) -> None:
    """``default_scene.turn_metric``: one hosted turn (``install`` sets it)."""
    emit(
        "turn",
        account=account or None,
        admit_wait_ms=max(0.0, float(admit_wait_ms)),
        duration_ms=max(0.0, float(duration_ms)),
        outcome=outcome,
    )


def refused(account_id: str, outcome: str) -> None:
    """An action the limits refused (``refused_cap``, ``refused_rate``): a ``turn`` that never ran."""
    emit("turn", account=account_id or None, admit_wait_ms=0.0, duration_ms=0.0, outcome=outcome)


def hook_session(event: str, owner: str) -> None:
    """``SessionStore.on_event``: one session event (``install`` sets it)."""
    emit("session", account=owner or None, event=event)


def install_hooks(scene: Any) -> None:
    """Set the two engine hooks (``install()``, under the supervisor)."""
    from engine.scenes import default_scene

    default_scene.turn_metric = hook_turn
    store = getattr(scene, "store", None)
    if store is not None:
        store.on_event = hook_session


def reset_hooks() -> None:
    """Clear ``default_scene.turn_metric`` (a test that built a supervised app in-process)."""
    from engine.scenes import default_scene

    default_scene.turn_metric = None


__all__ = [
    "ErrorMetricHandler",
    "MAX_QUEUE",
    "METRIC_REPORTED",
    "attach",
    "emit",
    "enable",
    "enabled",
    "hook_session",
    "hook_turn",
    "install_hooks",
    "refused",
    "reset_hooks",
    "stop",
]

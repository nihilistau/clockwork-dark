"""
Hosted Mode: the Errors a Player Sees
=====================================

In local mode a failure's text goes to the owner's own screen, and an
exception's words (the model server's URL, a path, a class name) are useful
there. In hosted mode the same text reaches every player, so each door that
used to return ``str(exc)`` returns a generic sentence with a REFERENCE
instead, and the full exception is logged under the same reference (spec
§6.6, survey finding 9): a player can quote ``ref 3f9a1c2b`` and the operator
finds the traceback.

``public_error(exc, what)`` -> ``(text, ref)``: the reference is 8 hex digits
from ``secrets`` (rule 4), the text is ``"<what> (ref <ref>)"``.

The doors: ``run_guarded``'s turn failure (``TURN_FAILED``), the voice
route's transcription and Assistant reply (``TRANSCRIPTION_FAILED``,
``REPLY_FAILED``), the socket guard's last line (``REQUEST_FAILED``) and the
app's error handler for any HTTP route that raises (``install_error_handler``).
A save's ``MigrationError`` keeps its own words everywhere: they are about the
save's version, and tell a player why their run will not load.

Under the supervisor (v0.20.0 T17) each ``public_error`` -- and, since its
fix round 1, each ``public_message`` (no class) -- is also an ``error``
metric: the reference, the exception's class and the logger's name, so the
admin panel's Errors page finds a player's ``ref``; the traceback stays in
that process's log file.

Version: v0.2.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from flask import jsonify
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)

#: What a turn that failed is told.
TURN_FAILED = "The turn could not be completed"

#: What a transcription that failed is told.
TRANSCRIPTION_FAILED = "Transcription failed"

#: What an Assistant reply that failed is told.
REPLY_FAILED = "The reply could not be completed"

#: What any other failed request or socket event is told.
REQUEST_FAILED = "The request could not be completed"


def new_ref() -> str:
    """A fresh reference: 8 hex digits from ``secrets``."""
    return secrets.token_hex(4)


def public_error(exc: BaseException, what: str = REQUEST_FAILED, **context: Any) -> tuple[str, str]:
    """
    The words a player sees for ``exc``, and the reference they carry.

    Logs the full exception (with its traceback) under the reference, with
    ``context`` (``where=..., id=...``) beside it.
    """
    from engine.hosting import metrics_emit
    from engine.hosting.metrics_schema import exception_name

    ref = new_ref()
    details = ", ".join(f"{key}={str(value)[:80]}" for key, value in context.items())
    logger.error(
        "[hosting] Failed (operation=public_error, ref=%s%s)",
        ref,
        f", {details}" if details else "",
        exc_info=(type(exc), exc, exc.__traceback__),
        # Its `error` metric is the one below, with the reference: the ERROR
        # handler skips this record (v0.20.0 T17).
        extra={metrics_emit.METRIC_REPORTED: True},
    )
    # The reference, the exception's CLASS and this logger's name: never the
    # exception's words, which may quote what a player typed (spec §14.10).
    metrics_emit.emit("error", ref=ref, exc_class=exception_name(type(exc)), logger=logger.name)
    return f"{what} (ref {ref})", ref


def public_message(what: str, **context: Any) -> tuple[str, str]:
    """
    As ``public_error`` for a failure that is a value, not an exception (an
    STT result with ``success: false``): logged as a WARNING under the
    reference, with ``context``.
    """
    from engine.hosting import metrics_emit

    ref = new_ref()
    details = ", ".join(f"{key}={str(value)[:200]}" for key, value in context.items())
    logger.warning("[hosting] Failed (operation=public_message, ref=%s, %s)", ref, details)
    # Found on the Errors page by its reference too (T17 fix round 1, M4): no
    # exception class, never the context's words.
    metrics_emit.emit("error", ref=ref, exc_class=None, logger=logger.name)
    return f"{what} (ref {ref})", ref


def install_error_handler(app: Any) -> None:
    """
    Any exception an HTTP route raises is answered ``500 {"error": "The
    request could not be completed (ref ...)"}`` and logged under the
    reference; an ``HTTPException`` (a 404, a 405, a 413) is answered as
    Werkzeug answers it, which names nothing internal.
    """

    def handle(exc: Exception) -> Any:
        if isinstance(exc, HTTPException):
            return exc
        text, _ref = public_error(exc, REQUEST_FAILED, where="http")
        return jsonify({"error": text}), 500

    app.register_error_handler(Exception, handle)


__all__ = [
    "REPLY_FAILED",
    "REQUEST_FAILED",
    "TRANSCRIPTION_FAILED",
    "TURN_FAILED",
    "install_error_handler",
    "new_ref",
    "public_error",
    "public_message",
]

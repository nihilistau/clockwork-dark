"""
LM Studio Routes
================

Where the two LM Studio APIs live, derived once so nothing hand-concatenates a
third variant.

LM Studio serves two families on one port, and they are SIBLINGS:

    /v1/*        the OpenAI-compatible API. Real, and the only route that takes
                 ``tools`` and ``response_format`` -- so chat completions stay
                 here (``POST /v1/chat/completions``).
    /api/v1/*    LM Studio's own REST API. ``POST /api/v1/chat`` (the only route
                 where ``reasoning: "off"`` is honoured) and
                 ``GET /api/v1/models`` (the model list, with capabilities and
                 the loaded context length).

``lmstudio.base_url`` means the OpenAI-compat base and keeps that meaning. The
REST root is derived from it by dropping the trailing ``/v1``, which is what
``native.py`` has always done for ``/api/v1/chat``; this module is that
derivation, in one place, for every caller.

WHAT THIS FIXES. ``GET /v1/models`` is not an endpoint LM Studio owns. It
answers -- with an OpenAI-shaped list -- and logs, verbatim:

    [ERROR] Unexpected endpoint or method. (GET /v1/models). Returning 200 anyway

Every doctor run and every ``launcher.py --check`` put that line in the user's
server log. Worse, the "returning 200 anyway" is general: measured on the live
server, ``GET /v1/nonsense`` and ``GET /api/v9/models`` BOTH answer 200 with an
error body. A health check that reads the status code and stops cannot fail, so
it is not a health check. The model list is now asked for once, from
``/api/v1/models``, and the answer is validated by its SHAPE.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

from typing import Optional

from engine.config import get_config

#: The one route that answers "what models does this server have".
MODELS_PATH = "/api/v1/models"

#: The native chat route. Named here so the two ``/api/v1`` users agree.
CHAT_PATH = "/api/v1/chat"

#: The OpenAI-compatible completions route. Deliberately NOT on /api/v1 -- it is
#: genuinely served, logs no error, and is the only one that accepts tools and
#: structured output.
COMPAT_CHAT_PATH = "/chat/completions"


def compat_base(base_url: Optional[str] = None) -> str:
    """The OpenAI-compatible base, e.g. ``http://localhost:1234/v1``."""
    cfg_value = get_config().get("lmstudio.base_url", "http://localhost:1234/v1")
    return str(base_url or cfg_value).rstrip("/")


def rest_root(base_url: Optional[str] = None) -> str:
    """
    The server root that ``/api/v1/*`` hangs off.

    ``/api/v1`` is a sibling of ``/v1``, not a child, so the compat suffix comes
    off rather than being appended to.
    """
    compat = compat_base(base_url)
    return compat[: -len("/v1")] if compat.endswith("/v1") else compat


def models_url(base_url: Optional[str] = None) -> str:
    """Absolute URL of the model list."""
    return f"{rest_root(base_url)}{MODELS_PATH}"

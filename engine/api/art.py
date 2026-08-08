"""
Art HTTP API
============

Manifest art key -> served URL, and the bytes behind a story-owned URL.

    GET /api/art?id=&kind=&time_of_day=&evil_phase=
    GET /story-art/<path>

The client cannot read ``data/art/manifest.yaml``, so an encounter's
``art: "wolf"`` was unrenderable without the first route.

THE SECOND ROUTE IS WHY A SECOND STORY CAN SHIP ART AT ALL. Flask's ``/static``
handler is bound to the SCENE package (``content/scenes/clockwork/static``),
not to the active game -- so the flagship's pack is reachable at
``/static/art/...`` purely because it happens to live inside the scene's own
directory. A story that keeps its plates in ``games/<slug>/data/art/`` has no
such handler: the manifest resolved, the file existed on disk, and the browser
got a 404 from the scene's catch-all. Every Garden plate failed that way, which
is indistinguishable from having no art pack.

``/story-art/<path>`` serves ``paths.art_root`` -- the same directory the
shipped provider resolves manifest entries against -- so a story ships art by
declaring two paths and setting ``root: "/story-art"`` in its manifest. The
flagship keeps ``root: "/static/art"`` and keeps being served by Flask, so
nothing about the two shipped games changes.

Every story has an art pack (or fails through to the procedural provider), so
this is engine-shared rather than story-owned. ``shipped_art_url`` is exported
because the story view models -- codex, inventory, recipes, barter -- all need
the same lookup and had their own copy of it.

Wire it into a scene with one line in its ``register()``::

    from engine.api.art import art_blueprint
    app.register_blueprint(art_blueprint())

Version: v0.2.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

BLUEPRINT_NAME = "art"

# The URL prefix a story-owned art pack is served under. A manifest opts in by
# naming it as its ``root:``; the value is duplicated in exactly one other
# place, ``games/wicked-garden/data/art/manifest.yaml``, and that is the point
# of a manifest key rather than a convention.
STORY_ART_PREFIX = "/story-art"


def shipped_art_url(
    subject_id: str,
    kind: str = "enemy",
    time_of_day: str = "day",
    evil_phase: str = "dormant",
) -> str:
    """
    Manifest key -> served URL, or "" when the pack has no picture for it.

    Only the *shipped* provider is consulted. peek() would fall through to the
    procedural generator, which writes a file to disk -- far too much work for
    a UI that is perfectly happy to fall back to the scene still.
    """
    if not subject_id:
        return ""
    try:
        from engine.media.providers.base import ImageRequest
        from engine.media.providers.shipped import ShippedArtProvider

        result = ShippedArtProvider().generate(
            ImageRequest(
                subject_id=subject_id,
                kind=kind,
                time_of_day=time_of_day,
                evil_phase=evil_phase,
            )
        )
        return result.url if result.url else ""
    except Exception as exc:  # noqa: BLE001 — a missing picture is not an error
        logger.debug("[art] Art lookup failed for %s: %s", subject_id, exc)
        return ""


def art_blueprint(name: str = BLUEPRINT_NAME) -> Blueprint:
    """
    Build the art blueprint.

    A factory rather than a module-level singleton: Flask refuses to register
    the same blueprint object on two apps, and the test suite builds a fresh
    app per case.
    """
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/api/art")
    def api_art() -> Any:
        """
        Resolve a manifest art key to a URL.

        Returns an empty url rather than 404 so the caller falls back to its
        own visual instead of logging a failed request every turn.
        """
        return jsonify({"url": shipped_art_url(
            request.args.get("id", ""),
            request.args.get("kind", "enemy"),
            request.args.get("time_of_day", "day"),
            request.args.get("evil_phase", "dormant"),
        )})

    @blueprint.get(f"{STORY_ART_PREFIX}/<path:name>")
    def story_art(name: str) -> Any:
        """
        Serve a plate from the active story's own art tree.

        ``send_generated`` rather than ``send_from_directory`` because this is
        the same problem the generated-media routes have: the directory sits
        outside ``static/``, so nothing else is doing the traversal check.

        The root is resolved per request rather than captured at registration:
        the blueprint is built once per app, but the active game -- and with it
        ``paths.art_root`` -- can be swapped underneath it.
        """
        from engine.api.media import send_generated
        from engine.media.providers.shipped import art_root

        return send_generated(art_root(), name)

    return blueprint


__all__ = [
    "BLUEPRINT_NAME",
    "STORY_ART_PREFIX",
    "art_blueprint",
    "shipped_art_url",
]

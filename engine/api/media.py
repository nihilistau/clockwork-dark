"""
Generated-Media HTTP API
========================

    GET /api/audio/<name>    synthesized narration
    GET /api/media/<name>    generated stills and portraits

Generated assets live OUTSIDE ``static/`` so the code tree stays clean, which
means Flask's static handler is not doing the path-traversal check for us and
this module has to.

Shared rather than story-owned: the directories are the engine's own output
roots, not any story's content.

Wire it into a scene with one line in its ``register()``::

    from engine.api.media import media_blueprint
    app.register_blueprint(media_blueprint())

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, send_file

logger = logging.getLogger(__name__)

BLUEPRINT_NAME = "media"

# Where the image providers write. Relative to the process working directory,
# exactly as it was in the scene module -- not a config key, because moving it
# to one would be a behaviour change dressed up as a refactor.
MEDIA_DIR = Path("data/media")


def send_generated(root: Path, name: str) -> Any:
    """
    Serve a generated asset, refusing anything outside the root.

    Generated media lives outside static/ so the code tree stays clean, which
    means path traversal has to be rejected here rather than by Flask.
    """
    base = root.resolve()
    try:
        target = (base / name).resolve()
        target.relative_to(base)
    except (ValueError, OSError):
        return jsonify({"error": "not found"}), 404
    if not target.is_file():
        return jsonify({"error": "not found"}), 404
    return send_file(target, conditional=True)


def media_blueprint(name: str = BLUEPRINT_NAME) -> Blueprint:
    """Build the generated-media blueprint. Factory, not a singleton."""
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/api/audio/<path:name>")
    def api_audio(name: str) -> Any:
        """Serve synthesized narration. Generated audio never lives in static/."""
        from engine.media.tts import AUDIO_DIR

        return send_generated(AUDIO_DIR, name)

    @blueprint.get("/api/media/<path:name>")
    def api_media(name: str) -> Any:
        """Serve generated stills and portraits."""
        return send_generated(MEDIA_DIR, name)

    return blueprint


__all__ = ["BLUEPRINT_NAME", "MEDIA_DIR", "media_blueprint", "send_generated"]

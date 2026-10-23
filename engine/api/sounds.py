"""
Sound HTTP API (v0.24.0 spec §10): data and files only. The server never plays, mixes or synthesises.

    GET /api/sounds                 the running story's merged catalogue
    GET /api/sounds/catalog         the engine and every story, for the audition page
    GET /sound/<scope>/<path>       a file: scope `_engine` or a story slug declaring paths.sounds
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify

from engine.config import get_config

logger = logging.getLogger(__name__)
BLUEPRINT_NAME = "sounds"


def _hosted_slugs() -> list[str] | None:
    """`hosting.stories` when hosted, else None (local: every story). Read from config: local mode never imports
    engine.hosting."""
    if not get_config().get("hosting.enabled"):
        return None
    return [str(s) for s in (get_config().get("hosting.stories") or [])]


def _with_urls(catalogue: dict[str, Any]) -> dict[str, Any]:
    for row in catalogue["sounds"].values():
        if "file" in row:
            path = str(row["file"])
            scope, rel = ("_engine", path[len("engine:"):]) if path.startswith("engine:") else (row["scope"], path)
            row["url"] = f"/sound/{scope}/{rel}"
    return catalogue


def sounds_blueprint(name: str = BLUEPRINT_NAME) -> Blueprint:
    """Build the sound blueprint. A factory, not a singleton, like the art blueprint's."""
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/api/sounds")
    def api_sounds() -> Any:
        if not get_config().get("sound.enabled", True):
            return jsonify({"enabled": False})
        from engine.games import registry, sounds

        return jsonify({"enabled": True, **_with_urls(sounds.merged(registry.peek()))})

    @blueprint.get("/api/sounds/catalog")
    def api_catalog() -> Any:
        from engine.games import registry, sounds

        allowed = _hosted_slugs()
        engine = sounds.merged(None)
        stories = []
        for slug, manifest in sorted(registry.discover().items()):
            if allowed is not None and slug not in allowed:
                continue
            story = sounds.load_story(manifest)
            merged = _with_urls(sounds.merge(sounds.load_engine(), story))
            stories.append({"slug": slug, "title": manifest.title, "declares": story is not None,
                            "events": merged["events"], "sounds": merged["sounds"], "bind": merged["bind"],
                            "overrides": sorted(k for k, v in merged["sounds"].items() if v.get("overrides"))})
        return jsonify({"engine": _with_urls(engine), "stories": stories})

    @blueprint.get("/sound/<scope>/<path:name>")
    def sound_file(scope: str, name: str) -> Any:
        from flask import send_file

        from engine.games import registry, sounds

        if scope == sounds.ENGINE_SCOPE:
            root = sounds.engine_root()
        else:
            allowed = _hosted_slugs()
            manifest = registry.get(scope)
            if manifest is None or not (manifest.paths or {}).get("sounds") or (allowed is not None and scope not in allowed):
                return jsonify({"error": "not found"}), 404
            root = manifest.resolve(manifest.paths["sounds"])
        if not name.endswith(".ogg") or not sounds.exists_exact(root, name):
            return jsonify({"error": "not found"}), 404       # also refuses any '..' part: it is in no listing
        response = send_file(root / name, mimetype="audio/ogg", conditional=True)
        response.headers["Cache-Control"] = f"private, max-age={int(get_config().get('sound.cache_seconds', 3600))}"
        return response

    return blueprint


__all__ = ["BLUEPRINT_NAME", "sounds_blueprint"]

"""
Sound HTTP API (v0.24.0 spec §10): data and files only. The server never plays, mixes or synthesises.

    GET /api/sounds                 the running story's merged catalogue
    GET /api/sounds/catalog         the engine and every story, for the audition page
    GET /sound/<scope>/<path>       a file: scope `_engine` or a story slug declaring paths.sounds
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml
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


def _provenance(root: Any) -> dict[str, dict[str, Any]]:
    """`{path: {author, pack, licence}}` from `<root>/PROVENANCE.yaml`, read per request; {} when absent or unreadable."""
    from engine import yamlio

    try:
        with open(Path(root) / "PROVENANCE.yaml", encoding="utf-8") as handle:
            rows = (yamlio.safe_load(handle) or {}).get("files") or []
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return {str(r["path"]): {k: r.get(k) for k in ("author", "pack", "licence")}
            for r in rows if isinstance(r, dict) and "path" in r}


def _with_urls(catalogue: dict[str, Any], story_root: Any = None) -> dict[str, Any]:
    from engine.games import sounds

    tables: dict[str, dict[str, dict[str, Any]]] = {}

    def table(scope: str) -> dict[str, dict[str, Any]]:
        if scope not in tables:
            root = sounds.engine_root() if scope == "_engine" or story_root is None else story_root
            tables[scope] = _provenance(root)
        return tables[scope]

    for row in catalogue["sounds"].values():
        if "file" in row:
            path = str(row["file"])
            scope, rel = ("_engine", path[len("engine:"):]) if path.startswith("engine:") else (row["scope"], path)
            row["url"] = f"/sound/{scope}/{rel}"
            row["provenance"] = table(scope).get(rel) or None
    return catalogue


def _story_root(manifest: Any) -> Any:
    paths = getattr(manifest, "paths", None) or {}
    return manifest.resolve(paths["sounds"]) if manifest is not None and paths.get("sounds") else None


def sounds_blueprint(name: str = BLUEPRINT_NAME) -> Blueprint:
    """Build the sound blueprint. A factory, not a singleton, like the art blueprint's."""
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/api/sounds")
    def api_sounds() -> Any:
        if not get_config().get("sound.enabled", True):
            return jsonify({"enabled": False})
        from engine.games import registry, sounds

        manifest = registry.entry_manifest()
        return jsonify({"enabled": True, **_with_urls(sounds.merged(manifest), _story_root(manifest))})

    @blueprint.get("/api/sounds/catalog")
    def api_catalog() -> Any:
        from engine.games import registry, sounds

        allowed = _hosted_slugs()
        engine = sounds.merged(None)
        engine_file = sounds.load_engine()      # once per request, not once per story
        stories = []
        for slug, manifest in sorted(registry.discover().items()):
            if allowed is not None and slug not in allowed:
                continue
            try:
                story = sounds.load_story(manifest)
            except sounds.SoundError as exc:
                logger.warning("sounds catalogue: %s: %s", slug, exc)
                stories.append({"slug": slug, "title": manifest.title, "declares": True, "error": str(exc)})
                continue
            merged = _with_urls(sounds.merge(copy.deepcopy(engine_file), story), _story_root(manifest))
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
        target = (root / name).resolve()
        if not target.is_relative_to(root.resolve()):
            return jsonify({"error": "not found"}), 404       # a link inside the root that leaves it
        response = send_file(target, mimetype="audio/ogg", conditional=True)
        response.headers["Cache-Control"] = f"private, max-age={int(get_config().get('sound.cache_seconds', 3600))}"
        return response

    return blueprint


__all__ = ["BLUEPRINT_NAME", "sounds_blueprint"]

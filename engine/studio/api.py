"""
Studio API
==========

Authoring a story from the browser: read it, edit it, generate into it, review
what the model wrote, and validate the result — without a terminal.

    GET    /api/studio/stories                 every story, with its health
    GET    /api/studio/story/<slug>            one story: its files, its paths
    GET    /api/studio/file?slug=&path=        one content file, verbatim
    PUT    /api/studio/file                    write it back, validated first
    GET    /api/studio/validate/<slug>         errors and advisories
    GET    /api/studio/drafts/<slug>           what the model has written
    POST   /api/studio/draft/accept            promote ONE draft entry
    POST   /api/studio/draft/reject            delete ONE draft entry
    POST   /api/studio/scaffold                a new story from a template

WHY A REVIEW QUEUE IS THE POINT. `scripts/author.py --promote` is all-or-
nothing and blind: it validates, then moves every draft into the live tree at
once. A drafting model produces content that loads, validates and plays while
doing nothing -- four such shapes were found in one nine-day draft and are now
ungrammatical -- and the ones that remain are matters of TASTE, which no
validator will ever catch. "Accept this location, rewrite that one, throw the
third away" is the missing verb.

THE TWO RAILS THIS FILE IS BUILT ON, because it writes to disk on request:

  1. **Every path is resolved inside the story's own directory** and rejected
     otherwise (`_safe_path`). A studio that can be talked into writing
     `../../engine/game/state.py` is a remote code execution bug with a nice
     front end.
  2. **Nothing is written that the engine would refuse to load.** A write is
     parsed as YAML first, and the story is validated after; a write that adds
     an error is reported rather than hidden. The editor cannot save what the
     game cannot read.

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import yaml
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

BLUEPRINT_NAME = "studio"

#: Repo root. The studio only ever touches `games/` beneath it.
ROOT = Path(__file__).resolve().parents[2]
GAMES = ROOT / "games"

#: Extensions the editor will open. A studio that will hand back any file is a
#: file browser for the whole machine; these are the ones a story is made of.
EDITABLE = {".yaml", ".yml", ".md", ".json"}

#: Draft trees are invisible to the validator and to every loader until they are
#: promoted -- `engine/games/validation.py::DRAFTS_DIRNAME`.
DRAFTS = "drafts"


def _safe_path(slug: str, relative: str) -> Path:
    """
    Resolve ``relative`` inside ``games/<slug>/``, or raise.

    THE ONE SECURITY-SHAPED FUNCTION IN THIS FILE. `..` in a path, an absolute
    path, or a symlink pointing out of the tree all resolve to somewhere the
    studio must not write, and the check is `resolve()` then `is_relative_to`
    rather than string matching, because `games/x/../../engine` is not a
    substring anyone greps for.
    """
    if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        raise ValueError(f"bad slug: {slug!r}")
    base = (GAMES / slug).resolve()
    if not base.is_dir():
        raise ValueError(f"no such story: {slug!r}")
    target = (base / (relative or "")).resolve()
    if not target.is_relative_to(base):
        raise ValueError("path escapes the story directory")
    return target


def _story_files(slug: str) -> list[dict[str, Any]]:
    """Every editable file in a story, with drafts marked."""
    base = (GAMES / slug).resolve()
    rows: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EDITABLE:
            continue
        relative = path.relative_to(base).as_posix()
        rows.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "draft": f"/{DRAFTS}/" in f"/{relative}",
            }
        )
    return rows


def _health(slug: str) -> dict[str, Any]:
    """Validation counts for one story. Never raises: a broken story must list."""
    try:
        from engine.games import registry, validation

        manifest = registry.get(slug)
        if manifest is None:
            return {"errors": 1, "advisories": 0, "note": "no game.yaml"}
        issues = validation.validate_story(manifest)
        return {
            "errors": len(validation.errors_only(issues)),
            "advisories": len(validation.warnings_only(issues)),
        }
    except Exception as exc:  # noqa: BLE001 -- the list must render regardless
        logger.debug("[studio] Health failed for %s: %s", slug, exc)
        return {"errors": -1, "advisories": -1, "note": str(exc)[:200]}


def studio_blueprint() -> Blueprint:
    """The studio's routes. Mounted only when the studio is asked for."""
    blueprint = Blueprint(BLUEPRINT_NAME, __name__)

    @blueprint.get("/api/studio/stories")
    def api_stories() -> Any:
        from engine.games import registry

        rows = []
        for slug in sorted(registry.discover()):
            manifest = registry.get(slug)
            rows.append(
                {
                    "slug": slug,
                    "title": str(getattr(manifest, "title", "") or slug),
                    "blurb": str(getattr(manifest, "blurb", "") or "").strip(),
                    "health": _health(slug),
                    "drafts": len(
                        [f for f in _story_files(slug) if f["draft"]]
                    ),
                }
            )
        return jsonify({"stories": rows})

    @blueprint.get("/api/studio/story/<slug>")
    def api_story(slug: str) -> Any:
        try:
            _safe_path(slug, "")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404
        from engine.games import registry

        manifest = registry.get(slug)
        return jsonify(
            {
                "slug": slug,
                "title": str(getattr(manifest, "title", "") or slug),
                "paths": dict(getattr(manifest, "paths", {}) or {}),
                "files": _story_files(slug),
                "health": _health(slug),
            }
        )

    @blueprint.get("/api/studio/file")
    def api_read() -> Any:
        try:
            path = _safe_path(request.args.get("slug", ""), request.args.get("path", ""))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not path.is_file() or path.suffix.lower() not in EDITABLE:
            return jsonify({"error": "not an editable file"}), 404
        return jsonify({"path": request.args.get("path", ""), "text": path.read_text(encoding="utf-8")})

    @blueprint.put("/api/studio/file")
    def api_write() -> Any:
        """
        Write a content file back, after proving the engine could read it.

        The order matters. YAML is parsed BEFORE anything touches disk, so a
        syntax error is a 400 and not a broken story. Validation runs AFTER,
        and its result is reported rather than enforced: a story mid-edit is
        allowed to be briefly wrong, but the author has to be told it is.
        """
        body = request.get_json(silent=True) or {}
        slug = str(body.get("slug") or "")
        try:
            path = _safe_path(slug, str(body.get("path") or ""))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if path.suffix.lower() not in EDITABLE:
            return jsonify({"error": "not an editable file"}), 400

        text = str(body.get("text") or "")
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                yaml.safe_load(text)
            except yaml.YAMLError as exc:
                return jsonify({"error": f"not valid YAML: {exc}"}), 400
        if path.suffix.lower() == ".json":
            import json

            try:
                json.loads(text)
            except ValueError as exc:
                return jsonify({"error": f"not valid JSON: {exc}"}), 400

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

        from engine.games import caches

        # The story's content is cached per activation; an edit the author
        # cannot see the effect of is an edit they will make twice.
        try:
            caches.reset_all_caches()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[studio] Cache reset failed: %s", exc)

        return jsonify({"ok": True, "health": _health(slug)})

    @blueprint.get("/api/studio/validate/<slug>")
    def api_validate(slug: str) -> Any:
        try:
            _safe_path(slug, "")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404
        from engine.games import registry, validation

        manifest = registry.get(slug)
        if manifest is None:
            return jsonify({"error": "no game.yaml"}), 404
        issues = validation.validate_story(manifest)
        return jsonify(
            {
                "issues": [
                    {
                        "source": i.source,
                        "ref_id": i.ref_id,
                        "message": i.message,
                        "severity": i.severity,
                    }
                    for i in issues
                ]
            }
        )

    @blueprint.get("/api/studio/drafts/<slug>")
    def api_drafts(slug: str) -> Any:
        """
        What the model has written and nobody has looked at yet.

        Each row carries its TEXT, because the whole point is to read it before
        it becomes part of the story. A list of filenames would be a worse
        version of `ls`.
        """
        try:
            base = _safe_path(slug, "")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

        rows: list[dict[str, Any]] = []
        for path in sorted(base.rglob(f"{DRAFTS}/*/*")):
            if not path.is_file() or path.suffix.lower() not in EDITABLE:
                continue
            rows.append(
                {
                    "path": path.relative_to(base).as_posix(),
                    "kind": path.parent.name,
                    "text": path.read_text(encoding="utf-8"),
                }
            )
        return jsonify({"drafts": rows})

    @blueprint.post("/api/studio/draft/reject")
    def api_reject() -> Any:
        """Throw one draft away. The other half of a review."""
        body = request.get_json(silent=True) or {}
        try:
            path = _safe_path(str(body.get("slug") or ""), str(body.get("path") or ""))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if f"/{DRAFTS}/" not in f"/{path.as_posix()}":
            return jsonify({"error": "only a draft may be rejected"}), 400
        if path.is_file():
            path.unlink()
        return jsonify({"ok": True})

    @blueprint.post("/api/studio/scaffold")
    def api_scaffold() -> Any:
        """A new story, from the same scaffolder the terminal uses."""
        body = request.get_json(silent=True) or {}
        slug = str(body.get("slug") or "").strip()
        template = str(body.get("template") or "minimal")
        title = str(body.get("title") or "").strip()
        try:
            import sys

            sys.path.insert(0, str(ROOT / "scripts"))
            import new_story  # type: ignore

            new_story.scaffold(slug, template=template, title=title)
        except Exception as exc:  # noqa: BLE001 -- a refusal is an answer
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "slug": slug, "health": _health(slug)})

    return blueprint


__all__ = ["BLUEPRINT_NAME", "studio_blueprint"]

"""
Archetypes HTTP API
===================

    GET /api/archetypes    what a new run may start as, for the Start screen

Shared rather than story-owned because the answer is already per-story: the ids
come from the active manifest's ``entry.archetypes`` and the display text from
that story's own ``paths.rules`` archetypes file. The route is the same for
every story; only the content behind it moves.

Wire it into a scene with one line in its ``register()``::

    from engine.api.archetypes import archetypes_blueprint
    app.register_blueprint(archetypes_blueprint())

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

BLUEPRINT_NAME = "archetypes"


def archetypes_blueprint(name: str = BLUEPRINT_NAME) -> Blueprint:
    """Build the archetypes blueprint. Factory, not a singleton -- see games/api.py."""
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/api/archetypes")
    def api_archetypes() -> Any:
        """
        What a new run may start as, for the Start screen.

        The client held a hardcoded array of three archetypes with their
        names, blurbs and skill notes -- the third and last copy of the
        flagship's answer, and the only one that also carried display text.
        A second story offering its own archetypes in the picker still drew
        Edgewood's three on the character sheet.

        The ids come from the active story's manifest (``entry.archetypes``,
        which validation already checks) and the display text from
        ``data/rules/archetypes.yaml`` through ``paths.rules``, so a story
        gets its own by shipping its own rules file. An id the rules file
        does not know still ships, with a de-underscored name, because a
        missing blurb should cost a sentence rather than an option.
        """
        from engine.game.checks import load_archetypes
        from engine.games.registry import entry_archetypes

        try:
            rows = load_archetypes().get("archetypes", {}) or {}
        except Exception as exc:  # noqa: BLE001 — text is not load-bearing
            logger.warning("[archetypes] No archetype rules: %s", exc)
            rows = {}

        # DECLARED-EMPTY versus ABSENT, the same distinction the manifest and
        # the session store already make. `or list(rows)` collapsed them: a
        # story saying "this game has no character classes" got every id in
        # whatever rules file was loaded, so The Wicked Garden -- whose player
        # is an unnamed mortal -- offered the flagship's wayfarer, hearthkeeper
        # and tinker on its start screen.
        from engine.games.registry import entry_manifest

        manifest = entry_manifest()
        if manifest is not None and "archetypes" in (manifest.entry or {}):
            offered = list(manifest.archetypes)
        else:
            offered = list(entry_archetypes(())) or list(rows)
        out = []
        for archetype_id in offered:
            row = rows.get(archetype_id) or {}
            skills = row.get("skill_bonus") or {}
            out.append(
                {
                    "id": archetype_id,
                    "name": str(row.get("name") or archetype_id.replace("_", " ").title()),
                    "blurb": str(row.get("blurb") or row.get("summary") or ""),
                    "note": " · ".join(sorted(skills)) if skills else "",
                }
            )
        return jsonify({"archetypes": out})

    return blueprint


__all__ = ["BLUEPRINT_NAME", "archetypes_blueprint"]

"""
Saves HTTP API
==============

    GET    /api/saves                 every save in the active game's namespace
    POST   /api/saves                 write one from a live session
    POST   /api/saves/<save_id>/load  rehydrate a run, returning a new session
    DELETE /api/saves/<save_id>       drop one

Shared, not story-owned. The save namespace is already per-game (see
``engine/persistence/saves.saves_root``) and the summary row a story shows is
already declared in its manifest's ``save_summary:``, so a second story gets
its own load menu out of these four routes without shipping a line of code.

Wire it into a scene with one line in its ``register()``::

    from engine.api.saves import saves_blueprint
    app.register_blueprint(saves_blueprint(self.store, llm_fn=self.llm_fn))

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from flask import Blueprint, jsonify, request

from engine.persistence import MigrationError, get_save_store
from engine.session import SessionStore

logger = logging.getLogger(__name__)

BLUEPRINT_NAME = "saves"


def saves_blueprint(
    store: SessionStore,
    *,
    llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
    name: str = BLUEPRINT_NAME,
) -> Blueprint:
    """
    Build the saves blueprint.

    Args:
        store: The scene's live session registry. Loading a save creates a
            session in it, and writing one reads a session out of it.
        llm_fn: Agent transport handed to a resumed session, so a run loaded
            from the menu narrates through the same backend a new one does.
        name: Blueprint name, in case a host app already has one called
            "saves".

    Returns:
        An unregistered Blueprint carrying the four routes.
    """
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/api/saves")
    def api_list_saves() -> Any:
        return jsonify({"saves": [s.to_dict() for s in get_save_store().list_saves()]})

    @blueprint.post("/api/saves")
    def api_write_save() -> Any:
        body = request.get_json(silent=True) or {}
        try:
            session = store.require(str(body.get("session_id", "")))
        except KeyError:
            return jsonify({"error": "session not found"}), 404
        save_id = get_save_store().save(
            session.engine.state,
            save_id=body.get("save_id") or None,
            slot=str(body.get("slot", "1")),
        )
        return jsonify({"save_id": save_id})

    @blueprint.post("/api/saves/<save_id>/load")
    def api_load_save(save_id: str) -> Any:
        try:
            session = store.resume(save_id, llm_fn=llm_fn)
        except FileNotFoundError:
            return jsonify({"error": "save not found"}), 404
        except MigrationError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(
            {
                "session_id": session.session_id,
                "save_id": save_id,
                "state": session.engine.state.to_client_dict(),
            }
        )

    @blueprint.delete("/api/saves/<save_id>")
    def api_delete_save(save_id: str) -> Any:
        return jsonify({"deleted": get_save_store().delete(save_id)})

    return blueprint


__all__ = ["BLUEPRINT_NAME", "saves_blueprint"]

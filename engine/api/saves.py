"""
Saves HTTP API
==============

    GET    /api/saves                 every save in the active game's namespace
    POST   /api/saves                 write one from a live session
    POST   /api/saves/<save_id>/load  rehydrate a run, returning a new session
    DELETE /api/saves/<save_id>       drop one

In hosted mode every route reaches only the logged-in account's store
(``<root>/users/<id>/saves/<slug>/``), so naming another account's save id is
answered exactly as a missing one, and an error's words name nothing
internal: a save that will not load is "save could not be read", and only a
``MigrationError`` keeps its own text (spec §6.4, §6.6). Any other exception
is the hosted error handler's (``engine/hosting/errors.py``).

Shared, not story-owned. The save namespace is already per-game (see
``engine/persistence/saves.saves_root``) and per owner (``save_store_for``,
v0.20.0: the local player is owner ""), and the summary row a story shows is
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

from engine.persistence import MigrationError, save_store_for
from engine.persistence.saves import InvalidSaveId, SaveRoomFull
from engine.session import (
    OwnerUnset,
    SavesFull,
    SessionBusy,
    SessionStore,
    check_save_room,
    request_owner,
    save_room_limit,
)
from engine.session.store import saves_full_message

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

    # A save id the store refuses (``saves.InvalidSaveId``: a name, never a
    # path) is answered exactly as a missing save is, at every door: same
    # status, same body. Only that refusal: any other ValueError is a save
    # that exists and is broken, and is not dressed up as missing. An id that is not ours must look like one that does
    # not exist, not like a path the server thought about.
    def _missing() -> Any:
        return jsonify({"error": "save not found"}), 404

    # Whose saves a request reaches (v0.20.0, spec §4.4, §6.4): the local
    # player's, "", in local mode; in hosted mode the logged-in account's,
    # read from the request's owner (`request_owner`, set by the gate from the
    # cookie, never from the body), so another account's save id is simply
    # not there. Every route asks `save_store_for`, never a process singleton.
    def _owner() -> str:
        return request_owner() or ""

    def _store() -> Any:
        return save_store_for(_owner(), None)

    # Hosted mode with no owner set: a path that escaped the gate, refused.
    def _unowned() -> Any:
        return jsonify({"error": "login required"}), 401

    @blueprint.get("/api/saves")
    def api_list_saves() -> Any:
        try:
            saves = _store()
        except OwnerUnset:
            return _unowned()
        return jsonify({"saves": [s.to_dict() for s in saves.list_saves()]})

    @blueprint.post("/api/saves")
    def api_write_save() -> Any:
        body = request.get_json(silent=True) or {}
        try:
            # Hosted: only the account's own session is found (spec §6.4).
            session = store.require(str(body.get("session_id", "")))
        except KeyError:
            return jsonify({"error": "session not found"}), 404
        # Into the session's own store: the run's owner's, resolved when the
        # session was built.
        try:
            saves = session.saves if session.saves is not None else _store()
        except OwnerUnset:
            return _unowned()
        try:
            # Hosted (T9 fix round 1): a save under a NEW id is refused once
            # the account keeps `hosting.max_saves_per_story` in this story.
            check_save_room(saves, str(body.get("save_id") or "") or None)
        except SavesFull as exc:
            return jsonify({"error": str(exc)}), 409
        try:
            # The count and the write are one step under the folder's index
            # lock (v0.20.0 T15): the check above is the early answer, this
            # the guard two saves at once cannot both pass.
            room = save_room_limit() if session.owner else None
            # Under the run's turn lock, refused for a closed account
            # (v0.20.0 T15 fix round 2, N3; local mode: as before).
            save_id = store.owner_write(
                session,
                lambda: saves.save(
                    session.engine.state,
                    save_id=body.get("save_id") or None,
                    slot=str(body.get("slot", "1")),
                    max_rows=room,
                ),
            )
        except SaveRoomFull as exc:
            return jsonify({"error": saves_full_message(exc.limit)}), 409
        except SessionBusy as exc:
            # Hosted: a turn is running in this run, or its account was
            # closed (AccountClosed, a SessionBusy).
            return jsonify({"error": str(exc)}), 409
        except InvalidSaveId:
            return _missing()
        return jsonify({"save_id": save_id})

    @blueprint.post("/api/saves/<save_id>/load")
    def api_load_save(save_id: str) -> Any:
        try:
            session = store.resume(save_id, llm_fn=llm_fn, owner=_owner())
        except OwnerUnset:
            return _unowned()
        except SessionBusy as exc:
            # Hosted (spec §5.4): this account's other run is mid-turn.
            return jsonify({"error": str(exc)}), 409
        except (FileNotFoundError, InvalidSaveId):
            return _missing()
        except MigrationError as exc:
            # Kept in hosted mode too (spec §6.6): it is about the save's
            # version, and tells the player why their run will not load.
            return jsonify({"error": str(exc)}), 409
        except ValueError:
            # A save that IS there and will not load (a corrupt envelope, a
            # value its state cannot hold). Never "not found": the player's
            # run is in the menu, and the owner's log must say why it failed.
            logger.exception(
                "[saves] Save could not be loaded (operation=api_load_save, id=%s)",
                save_id,
            )
            return jsonify({"error": "save could not be read"}), 500
        return jsonify(
            {
                "session_id": session.session_id,
                "save_id": save_id,
                "state": session.engine.state.to_client_dict(),
            }
        )

    @blueprint.delete("/api/saves/<save_id>")
    def api_delete_save(save_id: str) -> Any:
        # Deleting a save that is not there answers ``{"deleted": false}``,
        # so a refused id answers that too.
        try:
            deleted = _store().delete(save_id)
        except OwnerUnset:
            return _unowned()
        except InvalidSaveId:
            deleted = False
        return jsonify({"deleted": deleted})

    return blueprint


__all__ = ["BLUEPRINT_NAME", "saves_blueprint"]

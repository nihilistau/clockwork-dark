"""
The phone's HTTP routes and socket event (v0.22.0 spec §3.2, §7.2): one
blueprint and one `phone_action` handler.

Registered by `DefaultScene.register` only when the active story declares
`paths.social` (the active story is fixed per process), so every other
story's app -- and `tests/fixtures/app_shape.json` -- is unchanged. Each task
adds its own routes here (T4: the creation form; T6: the phone action, over
HTTP and the socket; T10: a thread's pages, state then archive; T19: a run's
generated media, owner-scoped). The socket handler is registered through
`FlaskScene.on`, so hosted mode's socket door wraps it (the login, the
phone bucket, the text cap).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from flask import Blueprint, jsonify, request
from flask_socketio import emit

from engine.social import creation

logger = logging.getLogger(__name__)


def _run(scene: Any, session: Any, body: dict[str, Any], emit_callback: Optional[Any] = None) -> Any:
    """
    One phone action under the turn lock: `run_guarded` with the mechanics
    runner, no admission. `action` is the verb's name; its player label is
    read by `run_mechanics`, under the lock, since a label may read state.
    """
    from engine.scenes.default_scene import run_guarded
    from engine.social import intents as phone
    from engine.social.turn import run_mechanics

    parsed = phone.normalise_phone(body) or {"action": "", "target": "", "args": {}, "text": ""}
    # One line per action (v0.22.0 T30, spec §17.1): the cadence measurement reads these
    # `t=` values. The action's NAME only -- never its text, target or args -- and only a catalogue
    # verb's: anything else is the client's own text, logged as `?` (T30 review I1).
    action = str(parsed["action"] or "")
    logger.info("[social] Phone action (operation=phone_action, action=%s, t=%.3f)",
                action if phone.row(action) is not None else "?", time.monotonic())
    result = run_guarded(session, parsed["action"], parsed, emit_callback=emit_callback,
                         runner=run_mechanics, admit=False, metric="phone")
    # The lock released (spec §16.1): the due messages are voiced by a pass
    # the player never waits for.
    _request_pass(session)
    return result


def _request_pass(session: Any) -> None:
    """A voicing pass requested when anything is due (spec §16.1); never fails the action."""
    from engine.social import voicer

    try:
        voicer.request_if_due(session)
    except Exception as exc:  # noqa: BLE001 -- the action is done; the next one requests again
        logger.warning(
            "[social] Voicing pass not requested (operation=_request_pass, id=%s): %s", session.session_id, exc)


def blueprint(scene: Any) -> Blueprint:
    bp = Blueprint("social", __name__)

    @bp.get("/api/social/creation")
    def api_creation() -> Any:
        """The creation form, resolved: each `of_table` expanded to `{id, label}` rows."""
        return jsonify(creation.resolved_form())

    @bp.post("/api/phone/action")
    def api_phone_action() -> Any:
        """The HTTP twin of `phone_action` (spec §7.2): the turn payload, or a refusal inside it."""
        body = request.get_json(silent=True) or {}
        try:
            session = scene.store.require(str(body.get("session_id", "")))
        except KeyError:
            return jsonify({"error": "session not found"}), 404
        turn, error, busy = _run(scene, session, body)
        if busy:
            return jsonify({"error": error, "busy": True}), 409
        if turn is None:
            return jsonify({"error": error}), 500
        return jsonify(turn)

    @bp.get("/api/phone/thread/<thread_id>")
    def api_phone_thread(thread_id: str) -> Any:
        """
        One page of a thread, newest first (spec §17.2): state's rows, then
        the save's archive. Read-only and owner-checked: another account's
        run answers as a missing one. Read holding the turn lock (tried, never
        waited for), so no action changes the thread mid-read.
        """
        from engine.session.store import release_turn
        from engine.social import archive, matching, messaging

        try:
            session = scene.store.require(str(request.args.get("session_id", "")))
        except KeyError:
            return jsonify({"error": "session not found"}), 404
        try:
            limit = int(request.args.get("limit", archive.PAGE_MAX))
        except ValueError:
            limit = archive.PAGE_MAX
        if not session.lock.acquire(blocking=False):
            return jsonify({"error": "A turn is already in progress.", "busy": True}), 409
        try:
            state = session.engine.state
            t = messaging.thread(state, thread_id)
            if t is None or not matching.listed(t):
                return jsonify({"error": "thread not found"}), 404
            return jsonify(archive.page(archive.save_dir(session), state, thread_id,
                                        str(request.args.get("before", "")), limit))
        finally:
            release_turn(session)

    @bp.get("/api/phone/media/<save_id>/<name>")
    def api_phone_media(save_id: str, name: str) -> Any:
        """
        One of a run's generated media (spec §13.4 "Owner-scoped serving"):
        the OWNER is never read off the URL -- it is the request's (local:
        the local player; hosted: the logged-in account, through the gate's
        `current_owner`) -- the save must be one of that owner's, and the
        name a stored file's (`storage.check_name`). Anything else, another
        account's save included, answers as missing.
        """
        from engine.api.media import send_generated
        from engine.media.comfy import storage
        from engine.persistence.saves import save_store_for
        from engine.session.store import OwnerUnset, request_owner

        missing = (jsonify({"error": "not found"}), 404)
        try:
            owner = request_owner() or ""
            storage.check_name(name)
            folder = storage.phone_media_dir(owner, save_id)
            if not save_store_for(owner, None).exists(save_id):
                return missing
        except (ValueError, OwnerUnset):
            return missing
        return send_generated(folder, name)

    return bp


def _register_socket(scene: Any) -> None:
    @scene.on("phone_action")
    def on_phone_action(data: dict[str, Any]) -> None:
        session_id = str((data or {}).get("session_id", ""))
        try:
            session = scene.store.require(session_id)
        except KeyError:
            emit("turn_error", {"message": "session not found", "fatal": True})
            return

        def _emit(event: str, payload: dict[str, Any]) -> None:
            # Hosted: every socket in the room is re-checked first, as a
            # turn's emits are (a revoked login receives nothing more).
            room_check = scene._room_check
            if room_check is not None:
                room_check(session_id)
            emit(event, payload, room=session_id)

        _, error, busy = _run(scene, session, data if isinstance(data, dict) else {}, emit_callback=_emit)
        if error:
            emit("turn_error", {"message": error, "busy": busy})


def register(scene: Any) -> None:
    """Called by default_scene.register only when the active story declares paths.social."""
    from engine.social import voicer

    scene.app.register_blueprint(blueprint(scene))
    _register_socket(scene)
    # The voicing pass's pushes go through the scene's room-checked emitter (spec §17.1).
    voicer.set_emitter(scene.emit_to_session)
    # The media worker's finished jobs come back to the runs (spec §13.4 step 8): `media_ready`
    # goes out through the same emitter.
    from engine.social import media

    media.install()

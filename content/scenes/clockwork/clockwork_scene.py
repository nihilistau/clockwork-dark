"""
Clockwork Scene Server
======================

Flask + Socket.IO frontend for The Clockwork Dark.

WHAT IS LEFT HERE, AND WHY. This file was ~1500 lines and every one of them was
Clockwork's by accident of location rather than by nature. Three things moved
out in v0.2.0:

    engine/session/         the session store -- engine, agents, ledger, lock
    engine/api/             the routes every story serves (saves, settings,
                            art, metrics, games, archetypes, media, voice)
    clockwork_api.py        the routes only THIS story serves (journal, codex,
                            items, recipes, trade)

What remains is genuinely the scene: the page, the three turn routes, and the
socket handlers -- because a turn's shape is this story's (see ``run_turn`` in
clockwork_state.py, which has not been made generic and should not be until a
second story's turn is written to argue with it).

THE MOUNTING SEAM. ``blueprints()`` mounts the engine's shared set plus ONE
story blueprint, named by the active game's manifest under ``scene.blueprint``
and defaulting to this story's. A second story ships its own screens by naming
its own factory; it ships none by naming ``blueprint: ""``. See
``engine/scenes/spec.py``.

Version: v0.2.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from flask import Blueprint, jsonify, render_template, request
from flask_socketio import emit, join_room

from content.scenes.clockwork.clockwork_state import (
    SessionStore,
    resolve_player_action,
    run_turn,
)
from engine.api import shared_blueprints
from engine.persistence import MigrationError
from engine.scenes.flask_scene import FlaskScene
from engine.scenes.spec import (
    ensure_active_game,
    load_story_blueprint,
    resolve_scene,
    scene_host,
    scene_port,
)

logger = logging.getLogger(__name__)

_SCENE_DIR = Path(__file__).resolve().parent

SCENE_NAME = "clockwork"

# Identity only. The PORT is deliberately absent: it lives in
# ``config/default.yaml`` under ``scene.clockwork.port`` and is read through
# ``engine.scenes.spec.scene_port``. It used to be duplicated here, in
# ``FlaskScene.run``'s default argument and in the launcher's ``--list`` line,
# so editing the config moved one of four copies. This dict is what the page
# template renders, and the template reads ``display_name`` only.
SCENE_METADATA = {
    "name": SCENE_NAME,
    # Fallback only. See `scene_metadata()` -- this is what shows when no game
    # is active, which is a state a player never reaches.
    "display_name": "A story",
    "type": "rpg",
}


def scene_metadata() -> dict[str, Any]:
    """
    What the page template renders, with the ACTIVE STORY's name in it.

    ``display_name`` was the string "THE CLOCKWORK DARK", hardcoded. This scene
    package serves every story -- the flagship, The Wicked Garden, a scratch
    test story -- so every one of them opened a browser tab titled after the
    flagship. Reproduced by launching The Drowned Carillon and reading
    ``document.title``.

    That is the scene package being story-shaped, which is the deepest form of
    the problem this whole seam exists to fix: one story's package is where
    every story runs, so anything named in it is named for all of them.

    Read live rather than captured at import, because activation happens after
    this module is imported and a value frozen at import time would be the
    fallback forever.
    """
    from engine.games.registry import peek

    manifest = peek()
    if manifest is None:
        return dict(SCENE_METADATA)
    return {**SCENE_METADATA, "display_name": manifest.title}

_store: Optional[SessionStore] = None
_scene: Optional["ClockworkScene"] = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store


def reset_store() -> SessionStore:
    """Clear sessions — for tests."""
    global _store
    _store = SessionStore()
    return _store


class ClockworkScene(FlaskScene):
    """Clockwork Dark play scene."""

    def __init__(self, *, testing: bool = False, llm_fn: Any = None) -> None:
        self.llm_fn = llm_fn
        self.store = get_store()
        super().__init__(
            name=SCENE_NAME,
            static_folder=_SCENE_DIR / "static",
            template_folder=_SCENE_DIR / "templates",
            testing=testing,
        )

    def blueprints(self) -> list[Blueprint]:
        """
        The engine's shared routes, plus the active story's own screens.

        Activation runs FIRST. The story blueprint is chosen from the active
        manifest, and asking which game is active must not be the thing that
        decides it -- ``resolve_scene`` reads without activating, so an
        unactivated process would answer from ``resolve_slug()`` and could
        disagree with the game the routes then serve content from.
        """
        ensure_active_game()
        mounted: list[Blueprint] = list(
            shared_blueprints(self.store, llm_fn=self.llm_fn)
        )
        story = load_story_blueprint(resolve_scene().blueprint, self.store)
        if story is not None:
            mounted.append(story)
        return mounted

    def register(self) -> None:
        app = self.app
        socketio = self.socketio

        @app.get("/")
        def index() -> str:
            return render_template("clockwork.html", scene=scene_metadata())

        @app.post("/api/game/new")
        def api_new_game() -> Any:
            body = request.get_json(silent=True) or {}
            # No flagship default here: an omitted archetype falls through to
            # the session store, which asks the active story's manifest. This
            # route hardcoding "wayfarer" was one of three independent copies
            # of the flagship's answer, and it beat the manifest every time.
            session = self.store.create(
                player_name=str(body.get("player_name", "Traveler")),
                archetype=str(body.get("archetype") or "") or None,
                seed=body.get("seed"),
                llm_fn=self.llm_fn,
            )
            payload = {
                "session_id": session.session_id,
                "save_id": session.save_id,
                "state": session.engine.state.to_client_dict(),
                "opening": session.last_turn,
            }
            return jsonify(payload)

        @app.get("/api/game/state")
        def api_get_state() -> Any:
            session_id = request.args.get("session_id", "")
            try:
                session = self.store.require(session_id)
            except KeyError:
                return jsonify({"error": "session not found"}), 404
            return jsonify({"state": session.engine.state.to_client_dict()})

        @app.post("/api/game/choice")
        def api_choice() -> Any:
            body = request.get_json(silent=True) or {}
            session_id = str(body.get("session_id", ""))
            try:
                session = self.store.require(session_id)
            except KeyError:
                return jsonify({"error": "session not found"}), 404

            action = resolve_player_action(
                session,
                str(body.get("choice_id", "")),
                body.get("custom_text"),
            )
            turn = run_turn(session, action)
            return jsonify(turn)

        @socketio.on("connect")
        def on_connect() -> None:
            logger.debug("[clockwork_scene] Client connected (operation=connect)")

        @socketio.on("join_session")
        def on_join(data: dict[str, Any]) -> None:
            session_id = str(data.get("session_id", ""))
            if session_id:
                join_room(session_id)
                try:
                    session = self.store.require(session_id)
                    emit(
                        "game_started",
                        {
                            "session_id": session_id,
                            "save_id": session.save_id,
                            "state": session.engine.state.to_client_dict(),
                            "opening": session.last_turn,
                        },
                    )
                except KeyError:
                    emit("error", {"message": "session not found"})

        @socketio.on("player_choice")
        def on_player_choice(data: dict[str, Any]) -> None:
            session_id = str(data.get("session_id", ""))
            try:
                session = self.store.require(session_id)
            except KeyError:
                emit("turn_error", {"message": "session not found", "fatal": True})
                return

            def _emit(event: str, payload: dict[str, Any]) -> None:
                emit(event, payload, room=session_id)

            # One turn at a time per session. The client also guards, but a
            # double-click or a reconnect race must not reach the engine.
            if not session.lock.acquire(blocking=False):
                emit("turn_error", {"message": "A turn is already in progress."})
                return

            try:
                action = resolve_player_action(
                    session,
                    str(data.get("choice_id", "")),
                    data.get("custom_text"),
                )
                run_turn(session, action, emit_callback=_emit)
            except Exception as exc:  # noqa: BLE001 — last line of defence
                # Without this the handler raised into Socket.IO, no event was
                # emitted, and the client's busy flag never cleared: every
                # button disabled forever with no message on screen.
                logger.exception(
                    "[clockwork_scene] Turn failed (operation=player_choice, id=%s)",
                    session_id,
                )
                emit(
                    "turn_error",
                    {"message": f"The turn could not be completed: {exc}"},
                )
            finally:
                session.lock.release()

        @socketio.on("resume")
        def on_resume(data: dict[str, Any]) -> None:
            """Rehydrate a run from its save after a reconnect."""
            save_id = str(data.get("save_id", ""))
            if not save_id:
                emit("resume_failed", {"message": "save_id required"})
                return
            try:
                session = self.store.resume(save_id, llm_fn=self.llm_fn)
            except (FileNotFoundError, MigrationError) as exc:
                emit("resume_failed", {"message": str(exc)})
                return
            join_room(session.session_id)
            emit(
                "game_resumed",
                {
                    "session_id": session.session_id,
                    "save_id": save_id,
                    "state": session.engine.state.to_client_dict(),
                    # BUG THIS FIXES: game_resumed shipped no `opening` at all,
                    # and the client's reducer reads narration, choices and the
                    # scene still out of exactly that key. Every reload restored
                    # the run into a screen with no choices -- see
                    # clockwork_state.resume_opening for the other half.
                    "opening": session.last_turn,
                },
            )


def create_app(
    *,
    testing: bool = False,
    llm_fn: Any = None,
) -> tuple[ClockworkScene, Any]:
    """
    Application factory for tests and launcher.

    Returns:
        (ClockworkScene instance, Flask app)
    """
    global _scene
    _scene = ClockworkScene(testing=testing, llm_fn=llm_fn)
    return _scene, _scene.app


def run_scene(*, host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Start clockwork scene from launcher."""
    resolved_host = host or scene_host(SCENE_NAME)
    resolved_port = int(port or scene_port(SCENE_NAME))
    scene, _ = create_app()
    logger.info(
        "[clockwork_scene] Starting (operation=run_scene, host=%s, port=%s)",
        resolved_host,
        resolved_port,
    )
    scene.run(host=resolved_host, port=resolved_port)

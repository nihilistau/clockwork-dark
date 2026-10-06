"""
Default Scene Server
====================

Flask + Socket.IO frontend -- the scene every story runs on unless it ships
its own.

MOVED FROM ``content/scenes/clockwork/clockwork_scene.py`` in v0.3.0. It was
already serving every story: the page title follows the active manifest, the
opening frames are manifest-declared, and the turn it runs
(``engine/scenes/default_state.py::run_turn``) resolves everything through the
active game. Only its address said "Clockwork", and an engine default that
lives inside one story's package is a default that story can never be absent
from. The old module remains as a compatibility shim.

What is here is genuinely the scene: the page, the three turn routes, and the
socket handlers. Everything else moved out earlier:

    engine/session/             the session store -- engine, agents, ledger, lock
    engine/api/                 the routes every story serves (saves, settings,
                                art, metrics, games, archetypes, media, voice)
    engine/scenes/default_api.py  the default story screens (journal, codex,
                                items, recipes, trade), mounted only when the
                                manifest's ``scene.blueprint`` says so

THE MOUNTING SEAM. ``blueprints()`` mounts the engine's shared set plus ONE
story blueprint, named by the active game's manifest under ``scene.blueprint``
and defaulting to the engine's. A story ships its own screens by naming its
own factory; it ships none by naming ``blueprint: ""``. See
``engine/scenes/spec.py``.

HOSTED METRICS (v0.20.0 T17): ``turn_metric`` is a hook ``engine.hosting``
sets under the supervisor, None by default; this module never imports
``engine.hosting`` for it.

Version: v0.2.0 [2026-10-06]
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from flask import Blueprint, jsonify, render_template, request
from flask_socketio import emit, join_room

from engine.api import shared_blueprints
from engine.config import hosting_enabled
from engine.locks import renew_after_fork
from engine.persistence import MigrationError
from engine.persistence.saves import InvalidSaveId, missing_save_message
from engine.scenes.default_state import (
    SessionStore,
    resolve_authored_choice,
    resolve_player_action,
    resolve_player_intent,
    run_turn,
)
from engine.session.store import OTHER_WINDOW_BUSY, SavesFull, SessionBusy
from engine.scenes.flask_scene import FlaskScene
from engine.scenes.spec import (
    DEFAULT_SCENE_NAME,
    ensure_active_game,
    load_story_blueprint,
    resolve_scene,
    scene_host,
    scene_port,
)

logger = logging.getLogger(__name__)

# The client assets. They stay under content/scenes/clockwork/ because that is
# where ``ui/vite.config.js`` builds ``dist/`` (committed, so the game plays
# without node) and where the flagship's shipped art pack lives -- moving them
# is a ui-build change, not a scene change. The TREE is shared: the built app
# carries the core client plus every story's UI plugin, and the manifest's
# ``ui.plugin`` picks which one draws.
_SCENE_DIR = Path(__file__).resolve().parents[2] / "content" / "scenes" / "clockwork"

SCENE_NAME = DEFAULT_SCENE_NAME

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
#: Guards building ``_store`` (v0.20.0): two first requests on two threads
#: must not each make a store and lose the other's sessions.
_store_lock = threading.Lock()
renew_after_fork(globals(), _store_lock=threading.Lock)
_scene: Optional["DefaultScene"] = None


def get_store() -> SessionStore:
    """The process's session store (double-checked: no lock once built)."""
    global _store
    store = _store
    if store is not None:
        return store
    with _store_lock:
        if _store is None:
            _store = SessionStore()
        return _store


def reset_store() -> SessionStore:
    """Clear sessions — for tests."""
    global _store
    with _store_lock:
        _store = SessionStore()
        return _store


#: What a hosted turn that could not get the model server in time is told
#: (spec §5.3). ``busy``: the client keeps its state and the player retries.
STORYTELLER_BUSY = "The storyteller is busy with other players. Try again in a moment."

#: What a hosted turn whose player left while it waited is answered (to
#: nobody, in practice): it was skipped, unrun (T9 fix round 1).
PLAYER_GONE = "The turn was not played: the player left while it waited."


#: Hosted under the supervisor (v0.20.0 T17, spec §14.10): one turn's metric,
#: ``turn_metric(account, admit_wait_ms, duration_ms, outcome)`` -- numbers,
#: an account id and an outcome (``ok``, ``busy``, ``error``), never the
#: turn's text. A HOOK that ``engine.hosting.install`` sets (to
#: ``engine.hosting.metrics_emit.hook_turn``), None by default, so this module
#: never imports ``engine.hosting`` and local mode records nothing.
turn_metric: Optional[Callable[[str, float, float, str], None]] = None


def _report_turn(session: Any, admit_ms: float, run_ms: float, outcome: str) -> None:
    """Hand one turn's numbers to ``turn_metric``, if set. Never raises."""
    hook = turn_metric
    if hook is None:
        return
    try:
        hook(str(getattr(session, "owner", "") or ""), admit_ms, run_ms, outcome)
    except Exception:  # noqa: BLE001 -- a metric must never fail a turn
        logger.warning("[default_scene] A turn metric was not recorded (operation=run_guarded)")


def _turn_deadline_seconds() -> Optional[float]:
    """
    ``hosting.turn_deadline_seconds`` (hosted): an admitted turn's wall-clock
    budget (T11 fix round 1). Read once per turn; None if it cannot be read,
    which leaves the turn as T9 ran it (bounded by the supervisor's reclaim).
    """
    try:
        from engine.config import get_config

        value = get_config().get("hosting.turn_deadline_seconds", None)
        return float(value) if value is not None else None
    except Exception:  # noqa: BLE001 -- config must never stop a turn
        return None


def _still_present(present: Any) -> bool:
    """``present()``, where a check that fails counts as still there (never skip on doubt)."""
    try:
        return bool(present())
    except Exception:  # noqa: BLE001 -- a broken check must not drop a turn
        logger.exception("[default_scene] Presence check failed (operation=run_guarded)")
        return True


def _socket_presence(socketio: Any, sid: str, namespace: str = "/") -> Any:
    """``() -> bool``: whether socket ``sid`` is still connected."""

    def present() -> bool:
        return bool(socketio.server.manager.is_connected(sid, namespace))

    return present


def run_guarded(
    session: Any,
    action: str,
    intent: Any,
    *,
    authored: Optional[dict[str, Any]] = None,
    emit_callback: Optional[Any] = None,
    present: Optional[Any] = None,
    cancel: Optional[Any] = None,
) -> tuple[Optional[dict[str, Any]], str, bool]:
    """
    Run one turn under the session lock.

    BOTH turn entry points go through here. They did not: the socket handler
    took ``session.lock`` and wrapped the call, and ``POST /api/game/choice``
    did neither -- so two concurrent posts, or one post racing an in-flight
    socket turn, mutated a single ``GameState`` at the same time. The lock's own
    comment in ``engine/session/store.py`` says that corrupts state "in ways no
    test would reproduce", which is exactly why it must not be optional at one
    of the two doors.

    Args:
        session: The live session. Its lock is the mutex.
        action: The player's sentence for this turn.
        intent: The structured mechanic the chosen option declared, or None.
        authored: The chosen option's authored consequences
            (``resolve_authored_choice``), or None.
        emit_callback: Socket emitter, or None for the HTTP path.
        present: Hosted only: ``() -> bool``, whether the player is still
            there (the socket turn's connection). Asked once the turn is
            admitted; False skips the turn, unrun. None (the HTTP path, where
            a client that went away cannot be seen) never skips.
        cancel: Hosted only: an ``engine.llm.gate.CancelToken`` that calls
            the admission wait off (the socket turn's disconnect); a called
            off turn is answered as skipped, unrun.

    Returns:
        ``(payload, error, busy)``. Exactly one of ``payload`` and ``error`` is
        meaningful. ``busy`` marks CONTENTION rather than failure -- a turn is
        already running and this one never started, so the caller must report it
        without tearing down the running turn's UI.

    HOSTED MODE ADMITS THE TURN FIRST (v0.20.0, spec §5.3). Under the session
    lock, and before ``run_turn`` runs a single mechanic, the turn waits for a
    narration ticket (``engine.llm.gate.admit_turn``, up to
    ``hosting.queue_wait_seconds``) behind the other players. One that does not
    get one is refused as busy, ``STORYTELLER_BUSY``, with nothing changed:
    not the state, not the save, not the transcript. One that does narrates on
    its own ticket, so it can no longer reach the storyteller's
    ``fallback_narration`` through a busy gate. Local mode takes no ticket.
    The ticket is taken for the session's owner: under the supervisor an
    account holds one narration ticket at a time across every story, and a
    turn refused for that is told "A turn is still running in your other
    window." (``OTHER_WINDOW_BUSY``, busy as well). An admitted turn runs
    against ``hosting.turn_deadline_seconds`` (T11 fix round 1): past it no
    model call starts and the one running is cut, so a slow model ends the
    turn through the storyteller's own failure path (its engine-authored
    fallback narration) and the ticket is given back on time.

    Under the supervisor (v0.20.0 T17) each turn's admission wait, run time
    and outcome (``ok``, ``busy``, ``error``) go to the ``turn_metric`` hook,
    numbers and the account id only.
    """
    if not session.lock.acquire(blocking=False):
        _report_turn(session, 0.0, 0.0, "busy")
        return None, "A turn is already in progress.", True
    # Hosted (v0.20.0 T17): the admission wait and the run, for turn_metric.
    began = time.monotonic()
    admit_ms = 0.0
    try:
        if hosting_enabled():
            from engine.llm.gate import CANCELLED, OTHER_WINDOW, InferenceBusy, admit_turn

            try:
                admission = admit_turn(
                    label="turn",
                    account=str(getattr(session, "owner", "") or ""),
                    deadline_seconds=_turn_deadline_seconds(),
                    cancel=cancel,
                )
            except InferenceBusy as exc:
                _report_turn(session, (time.monotonic() - began) * 1000.0, 0.0, "busy")
                reason = getattr(exc, "reason", "")
                logger.warning(
                    "[default_scene] Turn refused before it ran (operation=run_guarded, "
                    "id=%s, reason=%s): %s",
                    getattr(session, "session_id", "") or "",
                    reason,
                    exc,
                )
                if reason == OTHER_WINDOW:
                    # The account's turn in another story's window holds or
                    # awaits its one narration ticket (spec §5.4, §14.4).
                    return None, OTHER_WINDOW_BUSY, True
                if reason == CANCELLED:
                    # Its socket went while it waited (T11 fix round 1).
                    return None, PLAYER_GONE, True
                return None, STORYTELLER_BUSY, True
            admitted = time.monotonic()
            admit_ms = (admitted - began) * 1000.0
            if present is not None and not _still_present(present):
                # The player left while the turn waited in line (T9 fix round
                # 1): nobody is there to read it, so it is not run, and the
                # slot goes straight to the next player. Nothing has changed.
                admission.release()
                logger.info(
                    "[default_scene] Turn skipped: its player left while it waited "
                    "(operation=run_guarded, id=%s)",
                    getattr(session, "session_id", "") or "",
                )
                _report_turn(session, admit_ms, 0.0, "busy")
                return None, PLAYER_GONE, True
            try:
                payload = run_turn(
                    session, action, intent=intent, authored=authored, emit_callback=emit_callback
                )
            finally:
                admission.release()
            _report_turn(session, admit_ms, (time.monotonic() - admitted) * 1000.0, "ok")
            return payload, "", False
        payload = run_turn(
            session, action, intent=intent, authored=authored, emit_callback=emit_callback
        )
        return payload, "", False
    except Exception as exc:  # noqa: BLE001 — last line of defence
        # Without this the socket handler raised into Socket.IO, no event was
        # emitted, and the client's busy flag never cleared: every button
        # disabled forever with no message on screen. The HTTP path had the
        # matching failure -- a Flask HTML 500 body returned to a JSON client.
        if hosting_enabled():
            # Hosted (spec §6.6): the exception names internals (the model
            # server's URL, a path) shown to every player, so the client gets
            # a reference and the log gets the exception under it.
            from engine.hosting.errors import TURN_FAILED, public_error

            text, _ref = public_error(
                exc, TURN_FAILED, where="run_guarded", id=getattr(session, "session_id", "")
            )
            _report_turn(session, admit_ms, max(0.0, (time.monotonic() - began) * 1000.0 - admit_ms), "error")
            return None, text, False
        logger.exception(
            "[default_scene] Turn failed (operation=run_guarded, id=%s)",
            getattr(session, "session_id", "") or "",
        )
        return None, f"The turn could not be completed: {exc}", False
    finally:
        session.lock.release()
        # Hosted (v0.20.0 T15 fix round 1): an admin ended this session's
        # account during the turn; it is released now the turn is over.
        after = getattr(session, "end_after_turn", None)
        if after is not None:
            after()


class DefaultScene(FlaskScene):
    """The engine's default play scene, serving whichever story is active."""

    def __init__(self, *, testing: bool = False, llm_fn: Any = None) -> None:
        self.llm_fn = llm_fn
        self.store = get_store()
        #: Hosted only: each socket turn still waiting for admission, by
        #: ``(sid, event number)`` -- per EVENT, not per socket (v0.20.0 T12,
        #: T11's N1): a double-clicked turn is two events on one sid, and
        #: both are called off when the socket goes (``cancel_waiting_turn``).
        #: Its own lock, a leaf (``_waiting_lock``).
        self._waiting_turns: dict[tuple[str, int], Any] = {}
        self._waiting_lock = threading.Lock()
        self._waiting_ids = itertools.count(1)
        super().__init__(
            name=SCENE_NAME,
            static_folder=_SCENE_DIR / "static",
            template_folder=_SCENE_DIR / "templates",
            testing=testing,
        )

    def cancel_waiting_turn(self, sid: str) -> bool:
        """
        Hosted: socket ``sid`` is gone, so its turn still waiting for a slot
        is called off at once -- under the supervisor its place in the queue
        and its account claim go with it, and nobody is told "a turn is still
        running in your other window" for a turn nobody will read. True when
        there was one.
        """
        with self._waiting_lock:
            keys = [key for key in self._waiting_turns if key[0] == sid]
            tokens = [self._waiting_turns.pop(key) for key in keys]
        for token in tokens:
            token.cancel()
        return bool(tokens)

    def _wait_begins(self, sid: str, token: Any) -> tuple[str, int]:
        """Record one socket event's waiting turn; the key ``_wait_ends`` takes."""
        with self._waiting_lock:
            key = (sid, next(self._waiting_ids))
            self._waiting_turns[key] = token
        return key

    def _wait_ends(self, key: tuple[str, int]) -> None:
        """That event's turn is admitted, refused or done: forget it (and only it)."""
        with self._waiting_lock:
            self._waiting_turns.pop(key, None)

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

        # THE STUDIO, ONLY WHEN ASKED FOR. It writes to `games/` -- correct for
        # an authoring tool, wrong for a machine somebody is only playing on --
        # so `launcher.py --studio` sets the flag and nothing else mounts it.
        # Read from the environment rather than config because it is a
        # per-invocation choice, not a property of the install.
        import os

        if os.environ.get("CLOCKWORK_STUDIO") == "1":
            try:
                from engine.studio import studio_blueprint

                mounted.append(studio_blueprint())
                logger.info("[scene] Studio mounted (operation=blueprints)")
            except Exception as exc:  # noqa: BLE001 -- never block play
                logger.warning("[scene] Studio unavailable: %s", exc)

        return mounted

    def register(self) -> None:
        app = self.app

        @app.get("/")
        def index() -> str:
            # `template_extras` is {} in local mode, so the page is unchanged;
            # hosted mode adds the logout form's block (spec §6.3).
            return render_template(
                "clockwork.html", scene=scene_metadata(), **self.template_extras
            )

        @app.post("/api/game/new")
        def api_new_game() -> Any:
            body = request.get_json(silent=True) or {}
            # No flagship default here: an omitted archetype falls through to
            # the session store, which asks the active story's manifest. This
            # route hardcoding "wayfarer" was one of three independent copies
            # of the flagship's answer, and it beat the manifest every time.
            try:
                session = self.store.create(
                    player_name=str(body.get("player_name", "Traveler")),
                    archetype=str(body.get("archetype") or "") or None,
                    seed=body.get("seed"),
                    llm_fn=self.llm_fn,
                )
            except (SessionBusy, SavesFull) as exc:
                # Hosted: this account's other run is mid-turn (spec §5.4),
                # or its saves in this story are at the cap (T9 fix round 1).
                return jsonify({"error": str(exc)}), 409
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

            choice_id = str(body.get("choice_id", ""))
            action = resolve_player_action(
                session, choice_id, body.get("custom_text")
            )
            # The mechanic the option declared, alongside the sentence it
            # became. Both come from the same choice; only one of them used to
            # exist.
            intent = resolve_player_intent(
                session, choice_id, body.get("custom_text")
            )
            # And what an authored opening choice does beyond its intent --
            # read from the manifest, never from the choice dict.
            authored = resolve_authored_choice(
                session, choice_id, body.get("custom_text")
            )
            turn, error, busy = run_guarded(session, action, intent, authored=authored)
            if busy:
                return jsonify({"error": error}), 409
            if turn is None:
                return jsonify({"error": error}), 500
            return jsonify(turn)

        @self.on("connect")
        def on_connect() -> None:
            logger.debug("[default_scene] Client connected (operation=connect)")

        @self.on("join_session")
        def on_join(data: dict[str, Any]) -> None:
            session_id = str(data.get("session_id", ""))
            if session_id:
                # Found FIRST, joined second (v0.20.0): joining before the
                # check let any socket sit in any room -- one for a session
                # not yet created included -- and receive its stream.
                try:
                    session = self.store.require(session_id)
                except KeyError:
                    emit("error", {"message": "session not found"})
                    return
                join_room(session_id)
                emit(
                    "game_started",
                    {
                        "session_id": session_id,
                        "save_id": session.save_id,
                        "state": session.engine.state.to_client_dict(),
                        "opening": session.last_turn,
                    },
                )

        @self.on("player_choice")
        def on_player_choice(data: dict[str, Any]) -> None:
            session_id = str(data.get("session_id", ""))
            try:
                session = self.store.require(session_id)
            except KeyError:
                emit("turn_error", {"message": "session not found", "fatal": True})
                return

            def _emit(event: str, payload: dict[str, Any]) -> None:
                # Hosted: every socket in the room is re-checked first, so one
                # whose login was revoked (a password change, a disable) is
                # disconnected before it can receive this (v0.20.0 T8).
                room_check = self._room_check
                if room_check is not None:
                    room_check(session_id)
                emit(event, payload, room=session_id)

            choice_id = str(data.get("choice_id", ""))
            action = resolve_player_action(
                session, choice_id, data.get("custom_text")
            )
            intent = resolve_player_intent(
                session, choice_id, data.get("custom_text")
            )
            authored = resolve_authored_choice(
                session, choice_id, data.get("custom_text")
            )
            # One turn at a time per session. The client also guards, but a
            # double-click or a reconnect race must not reach the engine.
            # Hosted: a turn that waited in the queue is skipped if this
            # socket has gone by the time it is admitted (T9 fix round 1).
            sid = str(getattr(request, "sid", "") or "")
            present = cancel = waiting = None
            if self._socket_guard is not None:
                from engine.llm.gate import CancelToken

                present = _socket_presence(self.socketio, sid)
                # Called off by this socket's disconnect (T11 fix round 1),
                # keyed per event so a second one cannot drop it (T12).
                cancel = CancelToken()
                waiting = self._wait_begins(sid, cancel)
            try:
                _, error, busy = run_guarded(
                    session,
                    action,
                    intent,
                    authored=authored,
                    emit_callback=_emit,
                    present=present,
                    cancel=cancel,
                )
            finally:
                if waiting is not None:
                    self._wait_ends(waiting)
            if error:
                # `busy` is the difference between "your keypress did nothing"
                # and "the turn died". The client tears down the in-flight
                # stream on a turn_error, so a stray second press used to
                # delete the prose the FIRST turn had already put on screen.
                # Flagged, the reducer keeps the stream and shows the message.
                emit("turn_error", {"message": error, "busy": busy})

        @self.on("resume")
        def on_resume(data: dict[str, Any]) -> None:
            """Rehydrate a run from its save after a reconnect."""
            save_id = str(data.get("save_id", ""))
            if not save_id:
                emit("resume_failed", {"message": "save_id required"})
                return
            try:
                session = self.store.resume(save_id, llm_fn=self.llm_fn)
            except SessionBusy as exc:
                # Hosted (spec §5.4): this account's other run is mid-turn.
                emit("resume_failed", {"message": str(exc)})
                return
            except MigrationError as exc:
                # Kept in hosted mode too (spec §6.6): it is about the save's
                # version, and tells the player why their run will not load.
                emit("resume_failed", {"message": str(exc)})
                return
            except FileNotFoundError as exc:
                # Hosted: the missing save's own words, never an OS error's
                # text (which can name a path).
                message = missing_save_message(save_id) if hosting_enabled() else str(exc)
                emit("resume_failed", {"message": message})
                return
            except InvalidSaveId:
                # An id the store refuses (a path, not a name) or a save whose
                # session id is one: answered in the missing save's words.
                emit("resume_failed", {"message": missing_save_message(save_id)})
                return
            except ValueError:
                # A save that is there and will not load: logged, and never
                # answered as missing (the run is in the player's menu).
                logger.exception(
                    "[default_scene] Save could not be loaded (operation=resume, id=%s)",
                    save_id,
                )
                emit("resume_failed", {"message": f"Save could not be read: {save_id}"})
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
) -> tuple[DefaultScene, Any]:
    """
    Application factory for tests and launcher.

    Returns:
        (DefaultScene instance, Flask app)
    """
    global _scene
    _scene = DefaultScene(testing=testing, llm_fn=llm_fn)
    return _scene, _scene.app


def run_scene(*, host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Start the default scene from the launcher."""
    resolved_host = host or scene_host(SCENE_NAME)
    resolved_port = int(port or scene_port(SCENE_NAME))
    scene, _ = create_app()
    logger.info(
        "[default_scene] Starting (operation=run_scene, host=%s, port=%s)",
        resolved_host,
        resolved_port,
    )
    scene.run(host=resolved_host, port=resolved_port)

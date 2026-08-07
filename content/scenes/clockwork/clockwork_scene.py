"""
Clockwork Scene Server
======================

Flask + Socket.IO frontend for The Clockwork Dark.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from flask import jsonify, render_template, request, send_file
from flask_socketio import emit, join_room

from content.scenes.clockwork.clockwork_state import (
    SessionStore,
    resolve_player_action,
    run_turn,
)
from engine.config import get_config
from engine.game.engine import active_engine
from engine.media.stt import transcribe_audio
from engine.media.tts import AUDIO_DIR
from engine.persistence import MigrationError, get_save_store
from engine.scenes.flask_scene import FlaskScene

logger = logging.getLogger(__name__)

_SCENE_DIR = Path(__file__).resolve().parent

SCENE_METADATA = {
    "name": "clockwork",
    "display_name": "THE CLOCKWORK DARK",
    "port": 5573,
    "type": "rpg",
}

MEDIA_DIR = Path("data/media")

_store: Optional[SessionStore] = None
_scene: Optional["ClockworkScene"] = None


def _send_generated(root: Path, name: str) -> Any:
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


# ---------------------------------------------------------------------------
# Reference data for the journal / codex / barter screens
#
# These read content and engine tables directly. They are deliberately pure
# functions of a (possibly absent) GameState so they can be unit-tested without
# a Flask request, and so a missing session degrades to the undiscovered view
# instead of an error page.
# ---------------------------------------------------------------------------


def shipped_art_url(
    subject_id: str,
    kind: str = "enemy",
    time_of_day: str = "day",
    evil_phase: str = "dormant",
) -> str:
    """
    Manifest key -> served URL, or "" when the pack has no picture for it.

    Only the *shipped* provider is consulted. peek() would fall through to the
    procedural generator, which writes a file to disk -- far too much work for
    a UI that is perfectly happy to fall back to the scene still.
    """
    if not subject_id:
        return ""
    try:
        from engine.media.providers.base import ImageRequest
        from engine.media.providers.shipped import ShippedArtProvider

        result = ShippedArtProvider().generate(
            ImageRequest(
                subject_id=subject_id,
                kind=kind,
                time_of_day=time_of_day,
                evil_phase=evil_phase,
            )
        )
        return result.url if result.url else ""
    except Exception as exc:  # noqa: BLE001 — a missing picture is not an error
        logger.debug("[clockwork_scene] Art lookup failed for %s: %s", subject_id, exc)
        return ""


def quest_journal(state: Any) -> dict[str, Any]:
    """
    Everything the journal screen renders.

    Objective lines come from QuestEngine so the player reads exactly what the
    Storyteller reads -- a journal that paraphrases the prompt is a journal
    that will eventually disagree with it.
    """
    from engine.game.quests import (
        QuestEngine,
        load_arcs,
        load_quests,
        progress_records,
    )

    definitions = load_quests()
    arcs = load_arcs()
    quests: list[dict[str, Any]] = []

    for quest_id, record in progress_records(state).items():
        definition = definitions.get(quest_id, {})
        stages = definition.get("stages") or []
        stage = QuestEngine.current_stage(definition, record) if definition else None
        quests.append(
            {
                "id": quest_id,
                "title": str(definition.get("name") or quest_id.replace("_", " ").title()),
                "arc": str(definition.get("arc") or ""),
                "arc_title": str(
                    (arcs.get(str(definition.get("arc"))) or {}).get("name")
                    or definition.get("arc")
                    or ""
                ),
                "summary": str(definition.get("summary") or "").strip(),
                "status": record.status,
                "stage_index": record.stage_index,
                "stage_count": len(stages),
                "stage_id": str((stage or {}).get("id") or ""),
                "objective": str((stage or {}).get("objective") or "").strip(),
                "started_day": record.started_day,
            }
        )

    active_arc = str(getattr(state, "active_arc", ""))
    return {
        "active_arc": active_arc,
        "active_arc_title": str((arcs.get(active_arc) or {}).get("name") or active_arc),
        "active_arc_blurb": str((arcs.get(active_arc) or {}).get("blurb") or "").strip(),
        "arcs_unlocked": [
            {
                "id": str(arc_id),
                "title": str((arcs.get(str(arc_id)) or {}).get("name") or arc_id),
                "blurb": str((arcs.get(str(arc_id)) or {}).get("blurb") or "").strip(),
            }
            for arc_id in (getattr(state, "arcs_unlocked", None) or [])
        ],
        "objectives": QuestEngine.active_objectives(state),
        "quests": quests,
    }


def codex_places(state: Any) -> list[dict[str, Any]]:
    """
    The Atlas. Every canonical location, gated on having been there.

    Undiscovered places still appear -- the shape of the map is not a secret,
    only what is in it -- but carry no picture and no description.
    """
    from engine.game.locations import LOCATIONS

    visited: set[str] = set()
    time_of_day = "day"
    evil_phase = "dormant"
    if state is not None:
        # The quest engine's own visited ledger; see quests.py::_meta, whose
        # reserved block is the `_meta` key inside state.quests.
        meta = (getattr(state, "quests", None) or {}).get("_meta") or {}
        visited = {str(v) for v in (meta.get("visited") or [])}
        visited.add(str(state.location_id))
        time_of_day = state.time_of_day
        evil_phase = state.evil_phase.value

    places: list[dict[str, Any]] = []
    for place_id, row in LOCATIONS.items():
        discovered = not state or place_id in visited
        places.append(
            {
                "id": place_id,
                "name": str(row.get("name") or place_id.replace("_", " ").title()),
                "ring": int(row.get("ring", 0)),
                "discovered": discovered,
                "here": bool(state is not None and state.location_id == place_id),
                "image": shipped_art_url(place_id, "location", time_of_day, evil_phase)
                if discovered
                else "",
                "roads": [
                    {
                        "to": str(other),
                        "name": str(
                            (LOCATIONS.get(str(other)) or {}).get("name") or other
                        ),
                        "hours": int(edge.get("hours", 0)),
                        "danger_dc": int(edge.get("danger_dc", 0)),
                    }
                    for other, edge in (row.get("connections") or {}).items()
                ],
            }
        )
    return places


def codex_souls(state: Any, ledger: Any = None) -> dict[str, Any]:
    """
    The Souls. Villagers met, plus the Assistant's five canonical forms.

    An unmet NPC is listed by role and place only. Naming everyone up front
    would hand the player a cast list the fiction has not introduced.
    """
    from engine.game.locations import LOCATIONS

    relations = getattr(ledger, "relations", {}) or {}
    npcs = list(getattr(getattr(state, "procgen", None), "npcs", []) or [])
    if not npcs:
        # No session: fall back to the canon cast from the procgen templates so
        # the codex is still worth opening from a menu.
        from engine.game.procgen import load_templates

        npcs = list(load_templates().get("canon_npcs", []) or [])

    souls: list[dict[str, Any]] = []
    for npc in npcs:
        npc_id = str(npc.get("id") or "")
        relation = relations.get(npc_id)
        met = bool(state is None or getattr(relation, "met", False))
        place_id = str(npc.get("location_id") or "")
        souls.append(
            {
                "id": npc_id,
                "name": str(npc.get("name") or npc_id) if met else "Someone",
                "role": str(npc.get("role") or "villager").replace("_", " "),
                "place": str((LOCATIONS.get(place_id) or {}).get("name") or place_id),
                "traits": [str(t) for t in (npc.get("traits") or [])] if met else [],
                "canon": bool(npc.get("canon")),
                "met": met,
                "disposition": int(getattr(relation, "disposition", 0) or 0),
                "first_met_day": int(getattr(relation, "first_met_day", 0) or 0),
                "portrait": shipped_art_url(npc_id, "portrait") if met else "",
            }
        )

    from engine.media.providers.shipped import load_manifest

    forms = [
        {
            "form": str(form),
            "portrait": shipped_art_url(str(form), "portrait"),
            "current": bool(
                state is not None
                and getattr(state.assistant_mind, "current_form", "") == form
            ),
        }
        for form in (load_manifest().get("assistant_forms") or {})
    ]
    return {"souls": souls, "forms": forms}


def codex_things(state: Any) -> list[dict[str, Any]]:
    """
    The Things. Everything the art pack knows about, priced where a vendor
    trades in it, and marked when the player is carrying one.
    """
    import yaml

    from engine.config import project_root
    from engine.media.providers.shipped import load_manifest

    prices: dict[str, dict[str, Any]] = {}
    try:
        with (project_root() / "data" / "economy.yaml").open(encoding="utf-8") as handle:
            economy = yaml.safe_load(handle) or {}
        for vendor_id, vendor in economy.items():
            for side in ("sells", "buys"):
                for item_id, row in (vendor.get(side) or {}).items():
                    prices.setdefault(
                        str(item_id),
                        {
                            "name": str(row.get("name") or item_id),
                            "price": int(row.get("price", 0)),
                            "from": str(vendor_id).replace("npc_", "").title(),
                        },
                    )
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[clockwork_scene] Economy unreadable: %s", exc)

    carried = {i.id: i.qty for i in (getattr(state, "inventory", None) or [])}
    things: list[dict[str, Any]] = []
    for item_id in (load_manifest().get("items") or {}):
        row = prices.get(str(item_id), {})
        things.append(
            {
                "id": str(item_id),
                "name": str(row.get("name") or str(item_id).replace("_", " ").title()),
                "price": int(row.get("price", 0)),
                "from": str(row.get("from") or ""),
                "carried": int(carried.get(str(item_id), 0)),
                "image": shipped_art_url(str(item_id), "item"),
            }
        )
    return things


def trade_offer(state: Any) -> dict[str, Any]:
    """
    Who will barter with the player right now, and at what price.

    Presentation only: nothing here moves an item or a coin. The engine's
    `trade` skill is the single writer, and it runs inside a turn.
    """
    import yaml

    from engine.config import project_root
    from engine.game.procgen import npcs_at_location

    try:
        with (project_root() / "data" / "economy.yaml").open(encoding="utf-8") as handle:
            economy = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[clockwork_scene] Economy unreadable: %s", exc)
        economy = {}

    here = npcs_at_location(state.procgen, state.location_id)
    carried = {i.id: {"name": i.name, "qty": i.qty} for i in state.inventory}

    vendors: list[dict[str, Any]] = []
    for npc in here:
        npc_id = str(npc.get("id") or "")
        row = economy.get(npc_id)
        if not row:
            continue
        vendors.append(
            {
                "npc_id": npc_id,
                "name": str(npc.get("name") or npc_id),
                "role": str(npc.get("role") or "").replace("_", " "),
                "sells": [
                    {
                        "id": str(item_id),
                        "name": str(item.get("name") or item_id),
                        "price": int(item.get("price", 0)),
                        "image": shipped_art_url(str(item_id), "item"),
                    }
                    for item_id, item in (row.get("sells") or {}).items()
                ],
                # Only what the player is actually holding: an offer to sell
                # something you do not have is an offer the engine will refuse.
                "buys": [
                    {
                        "id": str(item_id),
                        "name": str(carried[str(item_id)]["name"]),
                        "price": int(item.get("price", 0)),
                        "qty": int(carried[str(item_id)]["qty"]),
                        "image": shipped_art_url(str(item_id), "item"),
                    }
                    for item_id, item in (row.get("buys") or {}).items()
                    if str(item_id) in carried
                ],
            }
        )

    return {
        "location": state.location_id,
        "gold": int(state.stats.gold),
        "vendors": vendors,
    }


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
            name="clockwork",
            static_folder=_SCENE_DIR / "static",
            template_folder=_SCENE_DIR / "templates",
            testing=testing,
        )

    def register(self) -> None:
        app = self.app
        socketio = self.socketio

        @app.get("/")
        def index() -> str:
            return render_template("clockwork.html", scene=SCENE_METADATA)

        @app.post("/api/game/new")
        def api_new_game() -> Any:
            body = request.get_json(silent=True) or {}
            session = self.store.create(
                player_name=str(body.get("player_name", "Traveler")),
                archetype=str(body.get("archetype", "wayfarer")),
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

        # -- read-only reference APIs (P10 screens) ----------------------
        #
        # The journal, the codex and the barter overlay all need content the
        # browser cannot see: quest definitions, the location graph, procgen
        # NPCs, economy prices and data/art/manifest.yaml. None of it belongs
        # in to_client_dict() -- it is static reference material, not turn
        # state, and shipping it on every turn would bloat every payload.
        #
        # Every route here is a GET that mutates nothing. `session_id` is
        # optional: without a session the codex degrades to "show everything"
        # rather than 404ing, so the screens are still browsable from a menu.

        def _optional_session(session_id: str) -> Any:
            try:
                return self.store.require(session_id) if session_id else None
            except KeyError:
                return None

        @app.get("/api/quests")
        def api_quests() -> Any:
            """Quest journal: active objectives plus per-quest stage detail."""
            try:
                session = self.store.require(request.args.get("session_id", ""))
            except KeyError:
                return jsonify({"error": "session not found"}), 404
            return jsonify(quest_journal(session.engine.state))

        @app.get("/api/codex/places")
        def api_codex_places() -> Any:
            session = _optional_session(request.args.get("session_id", ""))
            return jsonify({"places": codex_places(session.engine.state if session else None)})

        @app.get("/api/codex/souls")
        def api_codex_souls() -> Any:
            session = _optional_session(request.args.get("session_id", ""))
            return jsonify(
                codex_souls(
                    session.engine.state if session else None,
                    session.ledger if session else None,
                )
            )

        @app.get("/api/codex/things")
        def api_codex_things() -> Any:
            session = _optional_session(request.args.get("session_id", ""))
            return jsonify({"things": codex_things(session.engine.state if session else None)})

        @app.get("/api/art")
        def api_art() -> Any:
            """
            Resolve a manifest art key to a URL.

            The client cannot read data/art/manifest.yaml, so an encounter's
            `art: "wolf"` was unrenderable without this. Returns an empty url
            rather than 404 so the caller falls back to its own visual instead
            of logging a failed request every turn.
            """
            return jsonify({"url": shipped_art_url(
                request.args.get("id", ""),
                request.args.get("kind", "enemy"),
                request.args.get("time_of_day", "day"),
                request.args.get("evil_phase", "dormant"),
            )})

        @app.get("/api/trade")
        def api_trade() -> Any:
            """Vendors standing where the player is, with prices and stock."""
            try:
                session = self.store.require(request.args.get("session_id", ""))
            except KeyError:
                return jsonify({"error": "session not found"}), 404
            return jsonify(trade_offer(session.engine.state))

        @app.get("/api/saves")
        def api_list_saves() -> Any:
            return jsonify({"saves": [s.to_dict() for s in get_save_store().list_saves()]})

        @app.post("/api/saves")
        def api_write_save() -> Any:
            body = request.get_json(silent=True) or {}
            try:
                session = self.store.require(str(body.get("session_id", "")))
            except KeyError:
                return jsonify({"error": "session not found"}), 404
            save_id = get_save_store().save(
                session.engine.state,
                save_id=body.get("save_id") or None,
                slot=str(body.get("slot", "1")),
            )
            return jsonify({"save_id": save_id})

        @app.post("/api/saves/<save_id>/load")
        def api_load_save(save_id: str) -> Any:
            try:
                session = self.store.resume(save_id, llm_fn=self.llm_fn)
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

        @app.delete("/api/saves/<save_id>")
        def api_delete_save(save_id: str) -> Any:
            return jsonify({"deleted": get_save_store().delete(save_id)})

        @app.get("/api/audio/<path:name>")
        def api_audio(name: str) -> Any:
            """Serve synthesized narration. Generated audio never lives in static/."""
            return _send_generated(AUDIO_DIR, name)

        @app.get("/api/media/<path:name>")
        def api_media(name: str) -> Any:
            """Serve generated stills and portraits."""
            return _send_generated(MEDIA_DIR, name)

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

        @app.post("/api/voice/transcribe")
        def api_transcribe() -> Any:
            session_id = request.form.get("session_id", "")
            audio = request.files.get("audio")
            if audio is None:
                return jsonify({"error": "audio file required"}), 400
            try:
                session = self.store.require(session_id)
            except KeyError:
                return jsonify({"error": "session not found"}), 404

            audio_bytes = audio.read()
            with active_engine(session.engine):
                # Transcribe once. This used to call transcribe_audio here AND
                # again inside process_voice_input -- two full ASR round trips
                # per push-to-talk, which could disagree with each other.
                stt = transcribe_audio(audio_bytes)
                assistant = session.assistant.process_voice_input(
                    audio_bytes,
                    scene_context=session.last_turn.get("narration", ""),
                    transcript=stt.get("transcript", ""),
                )
            return jsonify({"stt": stt, "assistant": assistant.to_dict()})

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
    cfg = get_config()
    scene_cfg = cfg.get("scene.clockwork", {}) or {}
    resolved_host = host or str(scene_cfg.get("host", "0.0.0.0"))
    resolved_port = int(port or scene_cfg.get("port", SCENE_METADATA["port"]))
    scene, _ = create_app()
    logger.info(
        "[clockwork_scene] Starting (operation=run_scene, host=%s, port=%s)",
        resolved_host,
        resolved_port,
    )
    scene.run(host=resolved_host, port=resolved_port)
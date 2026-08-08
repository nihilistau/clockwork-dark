"""
Clockwork Session State
=======================

In-memory session store for active games.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from engine.agents.assistant import AssistantAgent
from engine.agents.storyteller import StorytellerAgent
from engine.game.engine import GameEngine, active_engine
from engine.game.procgen import new_game_state
from engine.game.state import GameState
from engine.memory import StoryLedger, TurnRecord, present_npc_ids, summarize
from engine.persistence import get_save_store
from engine.world.world_sim import WorldSim

logger = logging.getLogger(__name__)

def nominal_tick_hours() -> float:
    """
    In-game hours one background tick is worth, from config.

    Was a module constant of 6.0, which made it the single largest term in the
    game's clock and impossible to tune without an edit (issue R-03). It reads
    ``world.tick_hours`` now, so the pace slider on the pause menu and
    ``scripts/simulate.py`` cannot disagree with the running game.
    """
    from engine.config import get_config

    return float(get_config().get("world.tick_hours", 2.0))


def scene_image_url(state: GameState) -> str:
    """
    The still for wherever the player currently is.

    Resolves instantly from the shipped art pack; never generates.
    """
    from engine.media.providers import ImageRequest, peek

    try:
        return peek(
            ImageRequest(
                subject_id=state.location_id,
                kind="location",
                time_of_day=state.time_of_day,
                evil_phase=state.evil_phase.value,
            )
        ).url
    except Exception as exc:  # noqa: BLE001 — a missing picture must not block play
        logger.debug("[clockwork_state] No scene image: %s", exc)
        return ""

def assistant_portrait_url(form: str) -> str:
    """
    The painted portrait for one of the Assistant's five forms.

    data/art/manifest.yaml has carried `assistant_forms:` -> five real files in
    static/art/souls/ since the art pack shipped, and the companion column
    rendered the emoji "🐈". Only the shipped provider is consulted: a missing
    picture must never start a generation job inside a turn.
    """
    if not form:
        return ""
    try:
        from engine.media.providers.base import ImageRequest
        from engine.media.providers.shipped import ShippedArtProvider

        result = ShippedArtProvider().generate(
            ImageRequest(subject_id=str(form), kind="portrait")
        )
        return result.url or ""
    except Exception as exc:  # noqa: BLE001 — a missing face is not an error
        logger.debug("[clockwork_state] No portrait for form %s: %s", form, exc)
        return ""


def assistant_presence(state: GameState, result: Any = None) -> dict[str, Any]:
    """
    What the companion column renders, beyond the line it just spoke.

    Awareness itself is a HIDDEN stat -- state.to_client_dict() withholds it on
    purpose, because DESIGN.md says the player meets it as fiction and never as
    a number. So the two awareness gates ship as booleans: the player learns
    that something has opened, not how many points opened it. Trust is the
    Assistant's own regard and ships as a number, exactly as the Codex already
    prints NPC regard.
    """
    from engine.config import get_config

    cfg = get_config()
    mind = state.assistant_mind
    form = str(getattr(result, "form", "") or mind.current_form)
    # result is None for an opening or a resume: there has been no turn yet,
    # but the companion is already standing there and the column must be able
    # to draw it before the player's first move.
    spoken = result.to_dict() if result is not None else {
        "text": "",
        "voice_style": "",
        "spoke": False,
        "hint_tier": 0,
        "tool_receipts": [],
        "transcript": "",
        "decision": {},
    }

    # The director's choices, flattened out of `decision`. Two consumers need
    # them at the top level: engine/telemetry reads `intent`/`reliable`/`gift`
    # from exactly here, and the companion column can say WHY it turned up.
    # `reliable` is deliberately shipped -- the player is not told, but the
    # column can colour a warning it does not vouch for, and without it the
    # "low trust can mislead you" mechanic is invisible in the metrics too.
    decision = spoken.get("decision") or {}
    return {
        **spoken,
        "intent": str(decision.get("intent", "silent")),
        "reliable": bool(decision.get("reliable", True)),
        "gift": decision.get("gift_item") or None,
        "form": form,
        "portrait": assistant_portrait_url(form),
        "trust": round(float(mind.trust_level), 1),
        "patience": round(float(mind.patience), 1),
        "help_probability": round(float(mind.help_probability), 2),
        "unveiled": bool(
            state.awareness >= float(cfg.get("awareness.reveal_threshold", 20))
        ),
        "reflection_unlocked": bool(
            state.awareness >= float(cfg.get("awareness.reflection_form_min", 40))
        ),
    }


OPENING_NARRATION = (
    "You wake beneath birch trees at the forest's edge. "
    "Mist clings to the ferns; somewhere ahead, hearth smoke threads the grey."
)
OPENING_CHOICES = [
    {"id": "a", "text": "Follow the smoke toward Edgewood"},
    {"id": "b", "text": "Search the clearing for supplies"},
    {"id": "c", "text": "Listen — something watches without moving"},
]


def resume_opening(state: GameState, ledger: StoryLedger) -> dict[str, Any]:
    """
    The scene a reloading player lands in.

    BUG THIS FIXES: resume() built `last_turn` with an empty narration and an
    EMPTY CHOICE LIST, and that dict is what both the `game_resumed` socket
    event and the join_session `game_started` event ship as the opening. On
    every reload the run came back correctly -- right day, right inventory --
    into a screen with no narration and no choices at all, just the compose
    box, until the player typed something to force a turn.

    Choices cannot be restored, because they are never persisted: they are the
    Storyteller's output for a turn that has already been consumed. So they are
    rebuilt from the engine instead -- take stock, the roads actually leaving
    this location, and waiting -- which is grounded in real world state rather
    than invented, and each one runs as an ordinary turn.
    """
    narration = ""
    buffer = list(getattr(ledger, "turn_buffer", []) or [])
    if buffer:
        narration = str(getattr(buffer[-1], "narration", "") or "").strip()
    if not narration:
        narration = (
            "You pick up the thread where you left it. The hour has not moved "
            "while you were away, and neither has anything else."
        )

    choices: list[dict[str, str]] = [
        {"id": "resume_look", "text": "Take stock of where you are"},
    ]
    try:
        from engine.game.locations import LOCATIONS

        row = LOCATIONS.get(state.location_id) or {}
        for other in list((row.get("connections") or {}))[:2]:
            name = str((LOCATIONS.get(str(other)) or {}).get("name") or other)
            choices.append({"id": f"resume_go_{other}", "text": f"Set out for {name}"})
    except Exception as exc:  # noqa: BLE001 — a missing road must not cost the resume
        logger.debug("[clockwork_state] No roads for resume choices: %s", exc)
    choices.append({"id": "resume_wait", "text": "Wait, and listen"})

    return {
        "narration": narration,
        "choices": choices,
        "state": state.to_client_dict(),
        "scene_image": scene_image_url(state),
        "assistant": assistant_presence(state),
        "resumed": True,
    }


@dataclass
class GameSession:
    """One player session bound to engine and agents."""

    engine: GameEngine
    storyteller: StorytellerAgent
    assistant: AssistantAgent
    last_turn: dict[str, Any] = field(default_factory=dict)
    save_id: str = ""
    # Narrative memory. Persisted beside the save rather than inside it, so
    # save.json stays small and diffable.
    ledger: StoryLedger = field(default_factory=StoryLedger)
    # Held for the duration of a turn. A second choice arriving mid-turn is
    # rejected rather than interleaved -- two turns mutating one GameState
    # concurrently corrupts it in ways no test would reproduce.
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def session_id(self) -> str:
        return self.engine.state.session_id


class SessionStore:
    """In-memory session registry backed by on-disk saves."""

    def __init__(self) -> None:
        self._sessions: dict[str, GameSession] = {}
        self._guard = threading.RLock()

    def _build(
        self,
        state: GameState,
        *,
        llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
        save_id: str = "",
        ledger: Optional[StoryLedger] = None,
    ) -> GameSession:
        engine = GameEngine(state)
        resolved_ledger = ledger or StoryLedger()
        session = GameSession(
            engine=engine,
            # One ledger object shared with the agent, not a copy: what the
            # session records after a turn is what the agent reads before the
            # next one.
            storyteller=StorytellerAgent(engine, llm_fn=llm_fn, ledger=resolved_ledger),
            assistant=AssistantAgent(engine, llm_fn=llm_fn),
            save_id=save_id,
            ledger=resolved_ledger,
        )
        with self._guard:
            self._sessions[state.session_id] = session
        return session

    def create(
        self,
        *,
        player_name: str = "Traveler",
        archetype: str = "wayfarer",
        seed: Optional[int] = None,
        llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
    ) -> GameSession:
        """Create a new procgen-backed session and write its first save."""
        state = new_game_state(
            player_name=player_name,
            archetype=archetype,
            seed=seed,
        )
        session = self._build(state, llm_fn=llm_fn)
        session.last_turn = {
            "narration": OPENING_NARRATION,
            "choices": OPENING_CHOICES,
            "state": state.to_client_dict(),
            # The opening is a scene like any other and needs its picture.
            # image_ready only fires from run_turn, so without this the very
            # first thing a player sees is an empty frame.
            "scene_image": scene_image_url(state),
            # The companion is present from the first frame. Without this the
            # column had nothing to draw until the first turn completed.
            "assistant": assistant_presence(state),
        }
        try:
            session.save_id = get_save_store().save(state)
        except OSError as exc:
            logger.warning(
                "[clockwork_state] Initial save failed (operation=create): %s", exc
            )
        logger.info(
            "[clockwork_state] Session created (operation=create, id=%s, save=%s)",
            state.session_id,
            session.save_id,
        )
        return session

    def resume(
        self,
        save_id: str,
        *,
        llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
    ) -> GameSession:
        """
        Rehydrate a run from disk.

        This is what makes a dropped socket survivable. The client previously
        called /api/game/new on every reconnect, silently discarding the run.
        """
        state, memory = get_save_store().load(save_id)
        session = self._build(
            state,
            llm_fn=llm_fn,
            save_id=save_id,
            ledger=StoryLedger.from_dict(memory),
        )
        session.last_turn = resume_opening(state, session.ledger)
        logger.info(
            "[clockwork_state] Session resumed (operation=resume, save=%s, day=%s)",
            save_id,
            state.world_day,
        )
        return session

    def get(self, session_id: str) -> Optional[GameSession]:
        with self._guard:
            return self._sessions.get(session_id)

    def require(self, session_id: str) -> GameSession:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"Unknown session: {session_id}")
        return session

    def delete(self, session_id: str) -> None:
        with self._guard:
            self._sessions.pop(session_id, None)


def resolve_player_action(
    session: GameSession,
    choice_id: str,
    custom_text: Optional[str] = None,
) -> str:
    """Map choice id or custom text to Storyteller user message."""
    if custom_text and custom_text.strip():
        return custom_text.strip()

    choices = session.last_turn.get("choices", [])
    for choice in choices:
        if choice.get("id") == choice_id:
            return f"The player chooses: {choice.get('text', choice_id)}"
    return f"The player chooses option {choice_id}"


def _evaluate_quests(session: GameSession) -> list[dict[str, Any]]:
    """
    Advance quest state after a turn.

    Runs here rather than inside the agent because quest progress is an engine
    fact: it must not depend on the narrator having noticed. Idempotent and
    cheap, so calling it every turn is safe.
    """
    try:
        from engine.game.quests import QuestEngine

        events = QuestEngine.evaluate(session.engine.state, session.ledger)
        for event in events:
            # Completions are engine-sourced facts and do not decay -- the
            # Storyteller should still know about them fifty turns later.
            session.ledger.add_fact(
                event.text,
                kind="event",
                turn=session.engine.state.turn_number,
                day=session.engine.state.world_day,
                source="engine",
            )
        return [
            {"kind": e.kind, "quest_id": e.quest_id, "text": e.text} for e in events
        ]
    except Exception as exc:  # noqa: BLE001 — a quest bug must not lose the turn
        logger.warning(
            "[clockwork_state] Quest evaluation failed (operation=_evaluate_quests): %s",
            exc,
        )
        return []


def _summarizer_fn() -> Optional[Callable[[list[dict[str, Any]]], str]]:
    """
    Dedicated summarization call on the "small" (reasoning-off) profile.

    THIS WAS THE CALL IN THE USER'S SERVER LOG. It asked for 400 tokens from a
    reasoning model, the model spent all 400 thinking, and ``.content`` was the
    empty string. Narrowing the LMSResponse to ``str`` right there made
    ``finish_reason`` unreachable, so the summarizer upstream could not tell a
    truncated generation from a model that had nothing to say -- it just fell
    back to deterministic compression in silence.

    Three things changed. It routes through ``engine.lmstudio.backend``, which
    sends ``reasoning: "off"`` on the native transport so the cap buys answer
    rather than deliberation. The cap comes from the profile instead of a
    hardcoded 400. And a starved response is logged and reported as empty on
    purpose, so the summarizer's own loud fallback fires.

    Returns None when LM Studio is unreachable, which makes the summarizer fall
    back to deterministic compression rather than freezing the memory.
    """
    try:
        from engine.lmstudio.backend import get_backend
        from engine.lmstudio.client import get_lms_client

        if not get_lms_client().is_available():
            return None
        backend = get_backend()

        def _call(messages: list[dict[str, Any]]) -> str:
            response = backend.chat(
                messages,
                profile="small",
                temperature=0.2,
                label="summarize",
            )
            if response.starved_by_reasoning:
                logger.error(
                    "[clockwork_state] Summarizer starved by reasoning "
                    "(operation=_summarizer_fn, model=%s, reasoning_tokens=%s, "
                    "output_tokens=%s) — the summary will be deterministic",
                    response.model,
                    response.reasoning_tokens,
                    response.output_tokens,
                )
                return ""
            if response.truncated:
                logger.warning(
                    "[clockwork_state] Summary truncated at the token cap "
                    "(operation=_summarizer_fn, model=%s, chars=%s)",
                    response.model,
                    len(response.content),
                )
            return response.content

        return _call
    except Exception as exc:  # noqa: BLE001 — memory is best-effort
        logger.debug("[clockwork_state] No summarizer available: %s", exc)
        return None


def _record_memory(
    session: GameSession,
    player_action: str,
    result: Any,
) -> None:
    """
    Fold the completed turn into narrative memory.

    Without this the Storyteller starts every turn with no idea what it said
    last turn, which choice the player took, or who they have met.
    """
    state = session.engine.state
    ledger = session.ledger

    outcomes = [
        str(r.get("result", {}).get("summary", ""))
        for r in getattr(result, "tool_receipts", [])
        if r.get("type") == "dice" and r.get("success")
    ]

    evicted = ledger.record_turn(
        TurnRecord(
            turn=state.turn_number,
            day=state.world_day,
            location_id=state.location_id,
            player_action=player_action,
            narration=result.narration,
            outcomes=[o for o in outcomes if o],
        )
    )

    # Anyone present has now been met.
    for npc_id in present_npc_ids(state):
        ledger.meet(npc_id, day=state.world_day, location_id=state.location_id)

    ledger.decay(days=nominal_tick_hours() / 24.0)
    ledger.expire_promises(state.world_day)

    if evicted is not None:
        # Runs after the turn and behind the inference gate; summarizing during
        # a narration stream visibly stalls the text on screen.
        #
        # NOT the Storyteller's llm_fn: that one is prompted to produce game
        # turns and answers a summarization request with narration JSON, which
        # then becomes the summary verbatim.
        summarize(ledger, [evicted], llm_fn=_summarizer_fn())


def _autosave(session: GameSession, player_action: str, narration: str) -> None:
    """
    Persist after every completed turn.

    Never raises: a disk problem must cost the player the save, not the turn
    they just played.
    """
    state = session.engine.state
    try:
        store = get_save_store()
        session.save_id = store.save(
            state,
            save_id=session.save_id or None,
            memory=session.ledger.to_dict(),
        )
        store.append_transcript(
            session.save_id,
            {
                "turn": state.turn_number,
                "day": state.world_day,
                "hour": state.world_hour,
                "location": state.location_id,
                "action": player_action,
                "narration": narration,
            },
        )
    except (OSError, ValueError) as exc:
        logger.warning(
            "[clockwork_state] Autosave failed (operation=_autosave, id=%s): %s",
            session.session_id,
            exc,
        )


def run_turn(
    session: GameSession,
    player_action: str,
    *,
    emit_callback: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """
    Execute Storyteller + Assistant turn and build turn_update payload.

    Args:
        session: Active game session.
        player_action: Resolved player action text.
        emit_callback: Optional (event_name, payload) emitter for Socket.IO.

    Returns:
        turn_update dict.
    """
    state = session.engine.state
    started_at = time.perf_counter()

    with active_engine(session.engine):
        # Ask the world how much time it has actually earned rather than
        # granting a flat block. This was the R-03 bug: a fixed 6 hours per
        # turn, which was 60% of every hour the clock ever advanced and, at 2.0
        # hunger per hour, put 12 hunger on the player before they had done
        # anything. It is proportional to real elapsed time now, and capped.
        tick_hours = WorldSim.realtime_tick_hours(state.last_sim_tick_at)
        if tick_hours > 0:
            WorldSim.on_tick(state, hours=tick_hours)

        # Push narration to the browser as it is generated. Without this the
        # player watches a frozen screen for the whole completion, then the
        # paragraph appears at once.
        stream_to_client = None
        if emit_callback is not None:
            turn_index = state.turn_number + 1

            def stream_to_client(text: str) -> None:
                emit_callback(
                    "narration_delta",
                    {
                        "session_id": state.session_id,
                        "turn": turn_index,
                        "text": text,
                    },
                )

            # The reasoning channel, on its own event.
            #
            # The backend already separates reasoning from narration and
            # StorytellerAgent already accepts an on_reasoning sink -- nothing
            # consumed it, so on this hardware the player watched a blank
            # screen for the 10-14 seconds before the first narration token
            # while the model was, in fact, saying interesting things about
            # their game the whole time.
            #
            # Deliberately NOT merged into narration_delta: reasoning must
            # never reach the narration decoder or the tag buffer, or a model
            # musing "maybe [IMAGE:forest]" fires a real image generation.
            def stream_reasoning(text: str) -> None:
                emit_callback(
                    "reasoning_delta",
                    {
                        "session_id": state.session_id,
                        "turn": turn_index,
                        "text": text,
                    },
                )

            session.storyteller.on_reasoning = stream_reasoning

        try:
            storyteller_result = session.storyteller.run_turn(
                player_action,
                on_delta=stream_to_client,
            )
        finally:
            # The agent outlives the turn. Leaving the sink attached would have
            # a later non-socket turn (the HTTP route, a test) emit into a
            # callback closed over a dead request context.
            session.storyteller.on_reasoning = None

        assistant_result = session.assistant.run_turn(storyteller_result.narration)

    turn_payload = {
        "session_id": state.session_id,
        "save_id": session.save_id,
        "narration": storyteller_result.narration,
        "choices": storyteller_result.choices,
        "state": state.to_client_dict(),
        "tool_receipts": storyteller_result.tool_receipts,
        "evaluation": storyteller_result.evaluation.to_dict(),
        "media": storyteller_result.media,
        # Presence, not just the line: portrait, form, trust and the two
        # awareness gates, so the companion column has something to be even on
        # a turn the Assistant chooses to stay silent for.
        "assistant": assistant_presence(state, assistant_result),
        "llm_unavailable": storyteller_result.llm_unavailable,
        # False when the accepted narration survived a cut-short generation and
        # had its unfinished tail trimmed off. The client uses it to decide
        # nothing visual; it exists so a truncation is visible in the payload
        # and the logs rather than only as a sentence that stops dead.
        "narration_complete": storyteller_result.narration_complete,
        "finish_reason": storyteller_result.finish_reason,
        # Rule breaches from the governance chain (R001-R005). Almost always
        # empty; carried so the client can surface a failing turn instead of
        # the player noticing something is wrong three turns later.
        "governance": storyteller_result.governance,
    }
    session.last_turn = turn_payload

    quest_events = _evaluate_quests(session)
    if quest_events:
        turn_payload["quest_events"] = quest_events

    # Fold the finished turn into the process-wide aggregates behind
    # /api/metrics. Never allowed to fail a turn: a telemetry collector that
    # can break the game it is measuring is worse than no telemetry.
    try:
        from engine.telemetry import get_oracle

        get_oracle().record_turn(
            turn_payload,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            evil_progress=float(state.evil_progress),
        )
    except Exception as exc:  # noqa: BLE001 -- measurement must not break play
        logger.warning(
            "[clockwork_state] Telemetry failed, continuing "
            "(operation=run_turn): %s",
            exc,
        )

    _record_memory(session, player_action, storyteller_result)
    _autosave(session, player_action, storyteller_result.narration)

    if emit_callback:
        # streamed=True tells the client the narration text already arrived via
        # narration_delta, so it finalizes the live entry instead of appending
        # the whole paragraph a second time.
        #
        # `narration` in this payload is AUTHORITATIVE and the client replaces
        # the streamed entry's text with it. That is not belt-and-braces: the
        # evaluator retry deliberately does not stream, so on a retried turn
        # the text the player watched appear is a REJECTED draft, and until now
        # it was the only thing they ever saw. It is also the point at which a
        # narration trimmed back to its last complete sentence lands.
        emit_callback("turn_update", {**turn_payload, "streamed": stream_to_client is not None})
        for receipt in storyteller_result.tool_receipts:
            if receipt.get("type") == "dice":
                emit_callback("dice_result", receipt.get("result", {}))
        # portrait_ready was in the client's INBOUND table with nothing emitting
        # it and no reducer case, so it was dead in both directions -- and its
        # presence in INBOUND suppressed the socket.onAny drift warning built
        # to catch exactly that. It carries the companion's painted face now.
        portrait = turn_payload["assistant"].get("portrait", "")
        if portrait:
            emit_callback(
                "portrait_ready",
                {
                    "kind": "assistant",
                    "form": turn_payload["assistant"].get("form", ""),
                    "url": portrait,
                },
            )
        if assistant_result.spoke:
            emit_callback(
                "assistant_speak",
                {
                    "text": assistant_result.text,
                    "form": assistant_result.form,
                    "voice_style": assistant_result.voice_style,
                    # The column re-renders on this event alone when the turn
                    # payload has not landed yet; without the portrait here the
                    # face would blink out for the duration of a spoken line.
                    "portrait": portrait,
                    "trust": turn_payload["assistant"].get("trust", 0),
                    "hint_tier": assistant_result.hint_tier,
                },
            )
        for img in storyteller_result.media.get("images", []):
            emit_callback(
                "image_ready",
                {
                    "url": img.get("url", ""),
                    "location_id": img.get("payload", {}).get("location_id", ""),
                },
            )
        for cut in storyteller_result.media.get("cutscenes", []):
            emit_callback(
                "cutscene_start",
                {
                    "id": cut.get("payload", {}).get("cutscene_id", ""),
                    "video_url": cut.get("url", ""),
                    "captions": cut.get("payload", {}).get("captions", []),
                },
            )

    return turn_payload
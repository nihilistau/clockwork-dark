"""
Clockwork Session State
=======================

In-memory session store for active games.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
import threading
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

# In-game hours advanced per real-time background tick.
REALTIME_TICK_HOURS = 6.0


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

OPENING_NARRATION = (
    "You wake beneath birch trees at the forest's edge. "
    "Mist clings to the ferns; somewhere ahead, hearth smoke threads the grey."
)
OPENING_CHOICES = [
    {"id": "a", "text": "Follow the smoke toward Edgewood"},
    {"id": "b", "text": "Search the clearing for supplies"},
    {"id": "c", "text": "Listen — something watches without moving"},
]


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
        session.last_turn = {
            "narration": "",
            "choices": [],
            "state": state.to_client_dict(),
            "scene_image": scene_image_url(state),
        }
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
    Dedicated summarization call on the small profile.

    Returns None when LM Studio is unreachable, which makes the summarizer fall
    back to deterministic compression rather than freezing the memory.
    """
    try:
        from engine.lmstudio.client import get_lms_client
        from engine.lmstudio.gate import inference_slot
        from engine.lmstudio.profiles import resolve_profile

        client = get_lms_client()
        if not client.is_available():
            return None
        profile = resolve_profile("small")

        def _call(messages: list[dict[str, Any]]) -> str:
            with inference_slot(label="summarize"):
                return client.chat(
                    messages,
                    model=profile.model,
                    temperature=0.2,
                    max_tokens=400,
                ).content

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

    ledger.decay(days=REALTIME_TICK_HOURS / 24.0)
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

    with active_engine(session.engine):
        if WorldSim.should_run_realtime_tick(state.last_sim_tick_at):
            # Six in-game hours per real-time tick. This used to pass
            # days_elapsed=0.25 into an int() cast, so it advanced nothing.
            WorldSim.on_tick(state, hours=REALTIME_TICK_HOURS)

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

        storyteller_result = session.storyteller.run_turn(
            player_action,
            on_delta=stream_to_client,
        )
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
        "assistant": assistant_result.to_dict(),
        "llm_unavailable": storyteller_result.llm_unavailable,
    }
    session.last_turn = turn_payload

    quest_events = _evaluate_quests(session)
    if quest_events:
        turn_payload["quest_events"] = quest_events

    _record_memory(session, player_action, storyteller_result)
    _autosave(session, player_action, storyteller_result.narration)

    if emit_callback:
        # streamed=True tells the client the narration text already arrived via
        # narration_delta, so it finalizes the live entry instead of appending
        # the whole paragraph a second time.
        emit_callback("turn_update", {**turn_payload, "streamed": stream_to_client is not None})
        for receipt in storyteller_result.tool_receipts:
            if receipt.get("type") == "dice":
                emit_callback("dice_result", receipt.get("result", {}))
        if assistant_result.spoke:
            emit_callback(
                "assistant_speak",
                {
                    "text": assistant_result.text,
                    "form": assistant_result.form,
                    "voice_style": assistant_result.voice_style,
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
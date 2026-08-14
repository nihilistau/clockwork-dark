"""
Default Turn State
==================

The engine's default turn, and the two frames every run opens on.

MOVED FROM ``content/scenes/clockwork/clockwork_state.py`` in v0.3.0, by
copy rather than rewrite: this module was already the turn handler for EVERY
story -- the flagship, The Wicked Garden, and any story that declares no
``scene:`` block -- and nothing left in it was Clockwork's. The opening frame
is read from the active manifest's ``entry.opening``; the safety review, the
plan->negotiate->commit pipeline, quest evaluation, telemetry, memory and
autosave all resolve through the active game. What made it "Clockwork's" was
only its address, and one story owning the file every story runs on is the
defect the engine/story seam exists to remove. The old module remains as a
compatibility shim re-exporting everything here.

``GameSession`` and ``SessionStore`` live in ``engine/session/`` (since
v0.2.0): a session is engine machinery (engine, agents, ledger, save id, turn
lock). ``DefaultSessionStore`` below binds the manifest-declared opening
frames into that generic store.

ON ``run_turn``'S SHAPE. It is a single straight-line function whose steps --
background tick, safety review, narration stream, reasoning stream, quest
evaluation, telemetry, memory fold, autosave, then the socket emissions -- are
deliberately not split into a pipeline of extension points nobody has asked
for. Both shipped stories run it as-is; the pipeline seam it already carries
(``run_pipeline``/``agreed``) is where a story's own agents change the turn.

Version: v0.1.0 [2026-08-13]
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from engine.agents.character import CharacterTurn
from engine.agents.pipeline import merge_choices, narration_block, run_pipeline
from engine.game import epilogue as epilogue_module
from engine.game.engine import active_engine
from engine.game.state import GameState
from engine.memory import StoryLedger, TurnRecord, present_npc_ids, summarize
from engine.persistence import get_save_store
from engine.session import GameSession
from engine.session import SessionStore as EngineSessionStore
from engine.session import default_archetype
from engine.world.world_sim import WorldSim

logger = logging.getLogger(__name__)

def _review_input(session: GameSession, player_action: str) -> dict[str, Any]:
    """
    Run the safety gate over what the player just asked for.

    Returns a small dict rather than the Verdict object so the turn payload can
    carry it without the scene layer importing safety types, and so a build
    without the safety package degrades to an empty dict rather than an
    ImportError on the hot path.

    Never raises. The gate has its own fallbacks, and this adds one more:
    a safety layer that can stop a player typing is a worse outcome than one
    that occasionally fails open on input, which is the seam where a false
    positive costs the most and protects the least.
    """
    try:
        from engine.safety import SafetyGate

        gate = SafetyGate.for_state(session.engine.state)
        if gate.inert:
            return {}
        verdict = gate.review_input(player_action)
        if verdict.allowed:
            return {}
        logger.info(
            "[default_state] Safety verdict on input "
            "(operation=_review_input, disposition=%s)",
            verdict.disposition,
        )
        return {
            "disposition": str(verdict.disposition),
            # The redirect BEAT, not the reasons. `verdict.reasons` names the
            # player's own limit topics, and putting those anywhere near prose
            # would echo back the thing they asked not to read.
            "redirect": verdict.redirect,
            "fallback": verdict.fallback,
        }
    except Exception as exc:  # noqa: BLE001 -- see docstring
        logger.debug("[default_state] Safety gate unavailable: %s", exc)
        return {}


def _character_agent(session: GameSession) -> Any:
    """
    The active story's character agent, built once per session.

    Cached on the session rather than per turn: constructing it reads the
    roster and the persona file, and doing that on every turn would put two
    file reads inside the hot path for no benefit.
    """
    if not hasattr(session, "_character"):
        try:
            from engine.agents.character import character_for

            session._character = character_for(
                session.engine, llm_fn=session.storyteller.llm_fn
            )
        except Exception as exc:  # noqa: BLE001 -- fall back to the companion
            logger.debug("[default_state] No character agent: %s", exc)
            session._character = None
    return session._character


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
        logger.debug("[default_state] No scene image: %s", exc)
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
        logger.debug("[default_state] No portrait for form %s: %s", form, exc)
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


# The opening frame is DECLARED, not written here.
#
# It lives in games/clockwork-dark/game.yaml under `entry.opening`, and these
# two names read it back so nothing that imported them has to change. The move
# matters because this file is the scene EVERY story runs on until it ships its
# own: while these were module constants, a second story's player woke beneath
# Edgewood's birch trees, which is the same defect as the archetype default --
# one story's answer reachable from a place another story cannot override
# without writing code.
def _declared_entry_opening() -> dict[str, Any]:
    from engine.games.registry import entry_manifest

    try:
        manifest = entry_manifest()
        declared = (manifest.entry or {}).get("opening") if manifest else None
        return declared if isinstance(declared, dict) else {}
    except Exception as exc:  # noqa: BLE001 — a missing opening is not fatal
        logger.debug("[default_state] No declared opening: %s", exc)
        return {}


def opening_narration() -> str:
    return str(_declared_entry_opening().get("narration") or "")


def opening_choices() -> list[dict[str, Any]]:
    """
    The options the very first frame offers, as the manifest declares them.

    An opening choice may declare an ``intent`` exactly as a narrated one does,
    and the flagship's first option -- "Follow the smoke toward Edgewood" --
    is the reason. It was the choice in the original bug report: the model
    narrated the walk, the engine was never asked, and the save read
    ``forest_clearing`` afterwards. The opening is written by an author rather
    than sampled from a grammar, so nothing constrains it here; `execute_intent`
    re-checks it against the live graph like any other, and an author who
    mistypes a destination gets a refusal in the log rather than a phantom walk.
    """
    rows = _declared_entry_opening().get("choices") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("text"):
            continue
        choice: dict[str, Any] = {
            "id": str(row.get("id") or ""),
            "text": str(row.get("text") or ""),
        }
        if isinstance(row.get("intent"), dict):
            choice["intent"] = dict(row["intent"])
        out.append(choice)
    return out


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

    choices: list[dict[str, Any]] = [
        {"id": "resume_look", "text": "Take stock of where you are"},
    ]
    try:
        from engine.game.locations import LOCATIONS

        row = LOCATIONS.get(state.location_id) or {}
        for other in list((row.get("connections") or {}))[:2]:
            name = str((LOCATIONS.get(str(other)) or {}).get("name") or other)
            choices.append(
                {
                    "id": f"resume_go_{other}",
                    "text": f"Set out for {name}",
                    # The intent is what makes this option a road rather than a
                    # sentence. Without it a reloaded run offered "Set out for
                    # Edgewood Square" and going nowhere was the only thing it
                    # could do -- the same defect the whole mechanism exists to
                    # close, rebuilt on the resume path where nobody would look.
                    "intent": {"action": "travel", "target": str(other)},
                }
            )
    except Exception as exc:  # noqa: BLE001 — a missing road must not cost the resume
        logger.debug("[default_state] No roads for resume choices: %s", exc)
    choices.append({"id": "resume_wait", "text": "Wait, and listen"})

    return {
        "narration": narration,
        "choices": choices,
        "state": state.to_client_dict(),
        "scene_image": scene_image_url(state),
        "assistant": assistant_presence(state),
        "resumed": True,
    }


def opening(state: GameState) -> dict[str, Any]:
    """
    The frame a brand-new Clockwork run opens on.

    One of the two story seams ``engine.session.SessionStore`` takes; see that
    module's docstring for the other.
    """
    return {
        "narration": opening_narration(),
        "choices": opening_choices(),
        "state": state.to_client_dict(),
        # The opening is a scene like any other and needs its picture.
        # image_ready only fires from run_turn, so without this the very
        # first thing a player sees is an empty frame.
        "scene_image": scene_image_url(state),
        # The companion is present from the first frame. Without this the
        # column had nothing to draw until the first turn completed.
        "assistant": assistant_presence(state),
    }


class DefaultSessionStore(EngineSessionStore):
    """
    The engine's session store with the manifest-declared frames bound in.

    ``save_store`` is passed as a lambda over this module's own
    ``get_save_store`` rather than the function object, on purpose: the name is
    resolved at call time, so the process-wide store is looked up late -- and a
    test that redirects saves by patching this module's attribute keeps working
    across the move to ``engine/session/``.
    """

    def __init__(self) -> None:
        super().__init__(
            opening=opening,
            resume_opening=resume_opening,
            save_store=lambda: get_save_store(),
        )


# The name every caller and test already imports from the scene package. Kept
# so the move into the engine costs no import site anywhere else in the repo.
SessionStore = DefaultSessionStore


def _chosen(session: GameSession, choice_id: str) -> dict[str, Any]:
    """The option the player picked, out of the turn they picked it from."""
    for choice in session.last_turn.get("choices", []) or []:
        if isinstance(choice, dict) and choice.get("id") == choice_id:
            return choice
    return {}


def resolve_player_action(
    session: GameSession,
    choice_id: str,
    custom_text: Optional[str] = None,
) -> str:
    """Map choice id or custom text to Storyteller user message."""
    if custom_text and custom_text.strip():
        return custom_text.strip()

    choice = _chosen(session, choice_id)
    if choice:
        return f"The player chooses: {choice.get('text', choice_id)}"
    return f"The player chooses option {choice_id}"


def resolve_player_intent(
    session: GameSession,
    choice_id: str,
    custom_text: Optional[str] = None,
) -> dict[str, Any]:
    """
    The mechanic the chosen option declared, if it declared one.

    THIS IS THE MISSING HALF OF ``resolve_player_action``. That function turns a
    choice into a SENTENCE, and for the whole life of the project a sentence was
    all a choice ever became -- ``f"The player chooses: {text}"`` went to the
    narrator and nothing went to the engine. The model then wrote the player
    walking into Edgewood while the save still said ``forest_clearing``, because
    the only channel that could have moved them (a ``tool_calls`` array) is
    forbidden by the turn grammar and has been since structured output landed.

    A choice now carries an ``intent`` (see ``engine/game/intents.py``), and
    ``run_turn`` executes it through the ordinary skills before a word of the
    next beat is written.

    Args:
        session: Active session, whose ``last_turn`` holds the options the
            player was actually shown.
        choice_id: The option they picked.
        custom_text: Free text, if they typed instead of picking. Typed input
            declares no intent by definition -- nobody wrote an option for it,
            so there is nothing pre-authorised to run.

    Returns:
        The intent object, or ``{}``. Empty is the ordinary case: an option
        that is pure conversation stays pure, and a model or a save that
        carries no intent at all degrades to exactly the old behaviour.
    """
    if custom_text and custom_text.strip():
        return {}
    intent = _chosen(session, choice_id).get("intent")
    return intent if isinstance(intent, dict) else {}


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
            "[default_state] Quest evaluation failed (operation=_evaluate_quests): %s",
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
                    "[default_state] Summarizer starved by reasoning "
                    "(operation=_summarizer_fn, model=%s, reasoning_tokens=%s, "
                    "output_tokens=%s) — the summary will be deterministic",
                    response.model,
                    response.reasoning_tokens,
                    response.output_tokens,
                )
                return ""
            if response.truncated:
                logger.warning(
                    "[default_state] Summary truncated at the token cap "
                    "(operation=_summarizer_fn, model=%s, chars=%s)",
                    response.model,
                    len(response.content),
                )
            return response.content

        return _call
    except Exception as exc:  # noqa: BLE001 — memory is best-effort
        logger.debug("[default_state] No summarizer available: %s", exc)
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

    # The model's proposed memory -- facts it noticed, names it learned,
    # promises it made, how an NPC now regards the player.
    #
    # THIS HAD NEVER RUN. `ledger_delta` is in the turn schema, the model fills
    # it in every turn, `parse_storyteller_response` defaults it, and then it
    # was dropped on the floor: `apply_ledger_delta`'s only caller was
    # `turn_loop.commit_ledger`, in a module nothing imported (retired since, to
    # `turn_loop.py.bak`). So the Storyteller could observe "Maris does not
    # trust you now" and the ledger would never hear about it.
    #
    # It is applied here rather than inside the agent because the ledger belongs
    # to the session, and because `apply_ledger_delta` is the validating layer:
    # it caps facts per turn, truncates them, drops any whose subject is not a
    # known NPC, and clamps disposition steps. The model proposes; the engine
    # decides what is admitted.
    delta = getattr(result, "parsed", {}).get("ledger_delta") or {}
    if delta:
        from engine.memory.ledger import apply_ledger_delta

        accepted = apply_ledger_delta(
            ledger,
            delta,
            turn=state.turn_number,
            day=state.world_day,
            known_npc_ids={
                str(n.get("id")) for n in state.procgen.npcs if n.get("id")
            },
        )
        logger.debug(
            "[default_state] Ledger delta applied (operation=_record_memory, "
            "accepted=%s)",
            accepted,
        )

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
            "[default_state] Autosave failed (operation=_autosave, id=%s): %s",
            session.session_id,
            exc,
        )


def run_turn(
    session: GameSession,
    player_action: str,
    *,
    intent: Optional[dict[str, Any]] = None,
    emit_callback: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """
    Execute Storyteller + Assistant turn and build turn_update payload.

    Args:
        session: Active game session.
        player_action: Resolved player action text.
        intent: The mechanic the chosen option declared, from
            ``resolve_player_intent``. Executed by the ENGINE below, before
            anything plans or narrates. Optional throughout: a caller that
            passes none, a model that declares none and a save written before
            intents existed all take the path the turn took before.
        emit_callback: Optional (event_name, payload) emitter for Socket.IO.

    Returns:
        turn_update dict.
    """
    state = session.engine.state
    started_at = time.perf_counter()

    # Player input, inspected before anything plans against it. This seam did
    # not exist -- `player_action` went straight from the socket handler into
    # the Storyteller with nothing looking at it.
    #
    # Reviewed HERE rather than at the two call sites of
    # `resolve_player_action` because both of them end up in this function, and
    # a check that has to be remembered twice is a check that will be forgotten
    # once. A hard-no hit is a REDIRECT, not a refusal: the turn still runs and
    # the fiction declines, which is the difference between a story and a
    # dialog box.
    safety = _review_input(session, player_action)

    with active_engine(session.engine):
        # Ask the world how much time it has actually earned rather than
        # granting a flat block. This was the R-03 bug: a fixed 6 hours per
        # turn, which was 60% of every hour the clock ever advanced and, at 2.0
        # hunger per hour, put 12 hunger on the player before they had done
        # anything. It is proportional to real elapsed time now, and capped.
        tick_hours = WorldSim.realtime_tick_hours(state.last_sim_tick_at)
        if tick_hours > 0:
            WorldSim.on_tick(state, hours=tick_hours)

        # THE PLAYER'S CHOICE, RESOLVED BY THE ENGINE.
        #
        # This is the line the game did not have. A choice was a sentence handed
        # to a narrator; the world it described was never asked to change, and
        # the only channel that could have changed it -- a `tool_calls` array --
        # is unsamplable under the turn grammar.
        #
        # It runs HERE, after the background tick and before anything plans or
        # writes, for three reasons. The agents must negotiate against the state
        # the player's action produced rather than the one it replaced. The
        # narrator must be told the outcome instead of inventing it. And it must
        # be outside the narration transaction, so a draft the evaluator rejects
        # cannot un-walk a walk that was really taken.
        #
        # Legality is re-checked inside `execute_intent` against the live state,
        # so an intent that has gone illegal since it was written comes back as
        # an engine-authored refusal -- which is narration input, never silence.
        intent_receipts: list[dict[str, Any]] = []
        if intent:
            from engine.agents.tool_dispatcher import execute_intent

            intent_receipts = execute_intent(intent, session.engine)

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

        # PLAN -> NEGOTIATE -> COMMIT, ahead of narration.
        #
        # Every declared agent proposes against the SAME pre-commit state and
        # the same player action, seeing only what its knowledge scopes allow;
        # the story's rule table decides whose intent leads and which choices
        # survive; the accepted effects land in one atomic commit through the
        # single writer, with the proposing agent recorded.
        #
        # The ordering is the whole point. Until now the narrator ran to
        # completion and committed, and the second agent was handed the finished
        # prose -- an agent that has already written cannot be argued with. So
        # nothing is written until the argument is over, and the narrator then
        # writes ONCE, knowing the answer.
        #
        # `ran=False` for a story declaring fewer than two agents -- the
        # flagship, which declares no roster: `agreed` is empty, the block is
        # empty, and the turn below is byte-for-byte the turn it had. The
        # Wicked Garden declares two agents and takes the pipeline path.
        # A non-empty `safety` means the gate refused this direction --
        # `_review_input` returns {} when the input is allowed. The REDIRECT
        # beat is passed, never `reasons`: those name the player's own declared
        # limits, and routing them into a prompt would echo back the thing they
        # asked not to read.
        agreed = run_pipeline(
            state,
            player_action,
            ledger=session.ledger,
            safety_block=str(
                (safety or {}).get("redirect") or (safety or {}).get("disposition") or ""
            ),
        )

        try:
            storyteller_result = session.storyteller.run_turn(
                player_action,
                on_delta=stream_to_client,
                agreed_block=narration_block(agreed),
                intent_receipts=intent_receipts,
            )
        finally:
            # The agent outlives the turn. Leaving the sink attached would have
            # a later non-socket turn (the HTTP route, a test) emit into a
            # callback closed over a dead request context.
            session.storyteller.on_reasoning = None

        # The second voice.
        #
        # When the pipeline ran, she has ALREADY SPOKEN -- her words came out of
        # her plan, before the narrator wrote, and the narrator was handed them
        # verbatim. So there is nothing left to ask her: calling her again here
        # would be a second model call producing a second line for a turn that
        # already has hers, and the two would disagree.
        #
        # A story with no roster falls through to exactly what it had: its own
        # character agent reacting to finished prose, or the companion.
        speaker = agreed.speaker() if agreed.ran else None
        if speaker is not None:
            character_result = CharacterTurn(
                agent=speaker.agent, text=speaker.line, spoke=True
            )
            assistant_result = None
        elif agreed.ran:
            # The pipeline ran and nobody chose to speak. Silence is a real
            # outcome and the companion must not be summoned to fill it.
            character_result = CharacterTurn(agent=agreed.lead)
            assistant_result = None
        else:
            character = _character_agent(session)
            if character is not None:
                character_result = character.run_turn(storyteller_result.narration)
                assistant_result = None
            else:
                character_result = None
                assistant_result = session.assistant.run_turn(storyteller_result.narration)

    turn_payload = {
        "session_id": state.session_id,
        "save_id": session.save_id,
        "narration": storyteller_result.narration,
        # The narrator's options plus whatever the agents' plans put on the
        # table, deduped and renumbered. Identical to the narrator's own list
        # when no pipeline ran.
        "choices": merge_choices(agreed, storyteller_result.choices),
        "state": state.to_client_dict(),
        "tool_receipts": storyteller_result.tool_receipts,
        "evaluation": storyteller_result.evaluation.to_dict(),
        "media": storyteller_result.media,
        # Presence, not just the line: portrait, form, trust and the two
        # awareness gates, so the companion column has something to be even on
        # a turn the Assistant chooses to stay silent for.
        # The companion column. For a story running a CHARACTER instead, the
        # same slot carries her line -- the column is "the other voice", and
        # giving her a second one would mean the client had to learn which
        # stories have which. `character` marks who it is.
        "assistant": (
            assistant_presence(state, assistant_result)
            if character_result is None
            else {
                **assistant_presence(state),
                "character": character_result.agent,
                "text": character_result.text,
                "spoke": character_result.spoke,
            }
        ),
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
    # What the engine was asked to do and what it decided. Present only on a
    # turn that actually carried a mechanic, same rule as `safety` -- a pure
    # conversation turn ships the payload it always shipped.
    #
    # `resolved` is the honest half: an intent can be declared, re-checked
    # against a world that has moved, and REFUSED, and a client or a transcript
    # that only saw `intent` would have no way to tell the two apart.
    if intent:
        turn_payload["intent"] = dict(intent)
        turn_payload["intent_resolved"] = bool(
            intent_receipts and all(r.get("success") for r in intent_receipts)
        )

    # Only when the gate had something to say -- an inert policy adds no key at
    # all, so both shipped stories ship the payload they shipped before.
    if safety:
        turn_payload["safety"] = safety
    # The narration review's half of the same layer (attach point 4): the
    # verdict on what was actually written, and the summary card when the
    # scene was faded. Separate keys because the shapes differ -- `safety` is
    # the input review's redirect beat, `safety_narration` is a serialised
    # verdict -- and merging them would make the client guess which fired.
    if storyteller_result.safety:
        turn_payload["safety_narration"] = storyteller_result.safety
    if storyteller_result.fade_card:
        turn_payload["fade_card"] = storyteller_result.fade_card

    # The turn journal: who proposed what, which rule fired, what it cost the
    # loser, and every effect the commit applied or refused. Added only when a
    # negotiation actually happened, same as `safety` -- a turn where one agent
    # narrated has nothing to report and should not carry an empty block.
    #
    # `to_dict()` never includes a plan's `private`. A character's real motive
    # reaching the payload is a motive the browser has, the logs have, and
    # telemetry has.
    if agreed.ran:
        turn_payload["negotiation"] = agreed.to_dict()

    # The run is over, and here is what it reads like.
    #
    # Rides on turn_update rather than a new socket event: the client's INBOUND
    # table is asserted against every server emit (tests/test_ui_contract.py),
    # and an ending is a property of the turn that ended the story rather than
    # a thing that happens on its own schedule. Absent while a run is running
    # and absent forever for a story that declares no endings, so both shipped
    # games send exactly the payload they sent before.
    ending = epilogue_module.for_state(state)
    if ending is not None:
        turn_payload["ending"] = ending.to_dict()

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
            "[default_state] Telemetry failed, continuing "
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
        # Three of the four branches above leave `assistant_result` None, and
        # BOTH of the ones a pipeline story takes are among them -- so every
        # Wicked Garden turn raised here, after the payload was already built
        # and the player had already watched the narration stream in.
        #
        # A character's line needs no event of its own: it rides in the turn
        # payload's `assistant` block, which the client's turn_update reducer
        # renders. This event exists for the companion, who speaks on an agency
        # roll the payload alone does not announce.
        if assistant_result is not None and assistant_result.spoke:
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


__all__ = [
    "DefaultSessionStore",
    "opening_choices",
    "opening_narration",
    # Re-exported from engine.session, which is now their home. Anything that
    # imported them from here keeps working.
    "GameSession",
    "SessionStore",
    "assistant_portrait_url",
    "assistant_presence",
    "default_archetype",
    "nominal_tick_hours",
    "opening",
    "resolve_player_action",
    "resolve_player_intent",
    "resume_opening",
    "run_turn",
    "scene_image_url",
]

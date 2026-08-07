"""
Agent Prompt Templates
======================

Blocks are ordered stable-first so the KV prefix caches across turns: block 0
is byte-identical every turn, and volatile state comes last. The previous
prompt interleaved HP and the hour with the standing rules, which defeats
prefix caching on every single turn -- a real cost on local inference.

What changed and why:

  - No output-format instructions. The JSON schema carries the contract now
    (engine/lmstudio/schemas.py), so the model is not asked to describe its own
    output shape in prose.
  - No double generation. The old prompt demanded the narration twice: once as
    prose and again inside a JSON ``narration`` field. That roughly doubled
    output tokens and created a divergence class where the two disagreed.
  - Few-shot examples. For a 7-20B local model this is the highest-leverage
    thing a prompt can carry, and there were none.
  - An explicit length target. The evaluator secretly scored 40-200 words and
    the model was never told.
  - Memory. The Storyteller now sees what it said, who it met, and what it owes.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from engine.game.locations import LOCATIONS
from engine.game.state import GameState
from engine.lore.interceptors import mark_spoiler

if TYPE_CHECKING:  # pragma: no cover
    # Type-only. A real import here closes a cycle:
    # prompts -> memory -> memory.context -> prompts.
    from engine.memory.ledger import StoryLedger

# ---------------------------------------------------------------------------
# Block 0 -- stable. Must not interpolate anything volatile.
# ---------------------------------------------------------------------------

STORYTELLER_PERSONA = """\
You are the STORYTELLER of "The Clockwork Dark", a grounded dark-fantasy RPG.

VOICE
- Second person, present tense. "You step into..." never "The player steps".
- Plain, concrete, sensory. Name specific things: hinges, flour, wet wool.
- Frontier life first, dread underneath. The horror is that ordinary work
  continues while something goes quietly wrong at the edge of the field.
- Magic is costly, rare, and never flashy. No fireballs. No spell names.
- 90-150 words of narration. Shorter when the beat is small.

NEVER
- Never invent a dice result, a stat change, or an item. The engine decides
  those and hands you the outcome before you write. Narrate what you are given.
- Never state a number the engine did not give you.
- Never break the fourth wall or mention rules, mechanics, or "the player".
- Never introduce a named character who is not present in WORLD STATE.
- Never contradict LORE CONTEXT or THE STORY SO FAR.

CHOICES
Offer 2-4. Each must be a genuinely different intention, not three phrasings of
"go forward". At least one should be quiet or domestic where the scene allows
it -- a baker's life is a valid way to play this game. Keep each under 8 words.

CONTINUITY
You are given a running summary, recent turns, and a list of remembered facts
and names. Use them. If a character was called Maris Hearth, she is Maris
Hearth every time. If the player was promised something, that promise is real.
"""

# Built from real dicts and serialized, rather than hand-written JSON inside
# Python string literals. Nested quotes and escapes in narration prose make the
# literal form easy to break and impossible to review.
_EXAMPLE_BAKERY = {
    "narration": (
        "Maris does not stop working while she answers. Her hands go on shaping "
        "the dough, one turn and a press, one turn and a press, and the smell of "
        'it fills the low room. "Chimney\'s drawing wrong," she says. "Has been '
        'since the frost broke." She tips her chin at the flue without looking '
        "up. There is a dark rime along the iron where the soot has gone "
        'grey-green instead of black. "Odran says it\'s the wind. Odran says a '
        'lot of things." The oven ticks as it heats.'
    ),
    "choices": [
        {"id": "a", "text": "Look closer at the flue", "hint": "unknown"},
        {"id": "b", "text": "Offer to help with the batch", "hint": "safe"},
        {"id": "c", "text": "Ask what else Odran says", "hint": "safe"},
    ],
    "npc_voices": [{"npc_id": "npc_maris", "line": "Chimney's drawing wrong."}],
    "ledger_delta": {
        "facts": [
            {
                "text": "The bakery flue has grey-green rime, since the frost broke.",
                "subject_id": "npc_maris",
            }
        ]
    },
    "mood": "uneasy",
}

_EXAMPLE_GATE = {
    "narration": (
        "You are more tired than you let yourself think. The gravel gives under "
        "your heel with a sound like a small bone breaking, and the watchman's "
        "lamp swings round before you have finished flinching. He is not "
        'alarmed. That is somehow worse. "Bit late for the road," he says, and '
        "waits, and the waiting goes on long enough that you understand you are "
        "being counted."
    ),
    "choices": [
        {"id": "a", "text": "Give him a name", "hint": "risky"},
        {"id": "b", "text": "Turn back toward Edgewood", "hint": "safe"},
        {"id": "c", "text": "Pay the late toll", "hint": "costly"},
    ],
    "npc_voices": [{"npc_id": "npc_sera", "line": "Bit late for the road."}],
    "ledger_delta": {"npc_disposition": {"npc_sera": -2}},
    "mood": "tense",
}

STORYTELLER_EXAMPLES: list[dict[str, str]] = [
    # A quiet domestic beat with no roll -- the register the game is actually
    # about, and the one a model will otherwise skip straight past.
    {"role": "user", "content": "The player chooses: Ask Maris about the smoke."},
    {"role": "assistant", "content": json.dumps(_EXAMPLE_BAKERY, ensure_ascii=False)},
    # A failed check, narrated from a result the engine already decided.
    {
        "role": "system",
        "content": (
            "MECHANICAL RESULTS -- AUTHORITATIVE. Narrate these outcomes.\n"
            "- stealth (standard): d20 6, +2 agility, -3 exhausted = 5 vs DC 13. "
            "FAILURE by 8."
        ),
    },
    {"role": "user", "content": "The player chooses: Slip past the gate watch."},
    {"role": "assistant", "content": json.dumps(_EXAMPLE_GATE, ensure_ascii=False)},
]


# ---------------------------------------------------------------------------
# Volatile blocks
# ---------------------------------------------------------------------------


def _npcs_present_block(state: GameState) -> str:
    """List NPCs present, with what they are doing."""
    from engine.world.world_sim import merge_npcs_at_location

    if not state.procgen.npcs:
        return "PEOPLE HERE: (world not yet generated)"
    present = merge_npcs_at_location(state, state.location_id)
    if not present:
        return "PEOPLE HERE: nobody."

    lines = []
    for npc in present:
        bits = [f"- {npc.get('id')}: {npc.get('name')} ({npc.get('role')})"]
        activity = npc.get("activity")
        if activity:
            bits.append(f" -- {activity}")
        if npc.get("visiting"):
            bits.append(" [visiting]")
        lines.append("".join(bits))
    return "PEOPLE HERE:\n" + "\n".join(lines)


def _events_block(state: GameState) -> str:
    if not state.world_events:
        return ""
    lines = [
        f"- {e.get('event_id')} at {e.get('location_id')} (since day {e.get('day')})"
        for e in state.world_events
    ]
    return "HAPPENING NOW:\n" + "\n".join(lines)


def _rumors_block(state: GameState) -> str:
    if not state.rumors:
        return ""
    lines = [f"- {r}" for r in state.rumors[-3:]]
    return "RUMORS IN THE AIR:\n" + "\n".join(lines)


def _objectives_block(state: GameState) -> str:
    """
    What the player is currently trying to do, and the flags that record it.

    This is what turns "the model improvises forever" into "the model steers
    toward a goal". The flag vocabulary is listed because the model's only
    lever on quest progress is set_narrative_flag, and it cannot use a
    vocabulary it has never been shown.
    """
    try:
        from engine.game.quests import QuestEngine

        objectives = QuestEngine.active_objectives(state)
        allowed = QuestEngine.allowed_narrative_flags(state)
    except Exception:  # noqa: BLE001 — the prompt must build without quests
        return ""

    if not objectives:
        return ""

    lines = ["OBJECTIVES (the player's current threads):"]
    lines += [f"- {text}" for text in objectives[:6]]
    if allowed:
        lines.append(
            "Call set_narrative_flag ONLY when the fiction has genuinely reached "
            "one of these beats: " + ", ".join(sorted(allowed)[:12])
        )
    return "\n".join(lines)


def _encounter_block(state: GameState) -> str:
    """The scene the road produced, if one is unresolved."""
    scene = getattr(state, "encounter", None)
    if not scene:
        return ""
    lines = [
        "HAPPENING RIGHT NOW: " + str(scene.get("intro", scene.get("id", "something"))),
        "The player must deal with this before anything else. Their options are "
        "fixed by the engine -- narrate them, do not invent others.",
    ]
    for approach in scene.get("approaches", []) or []:
        if isinstance(approach, dict):
            lines.append(f"- {approach.get('id')}: {approach.get('text', '')}")
    return "\n".join(lines)


def _condition_block(state: GameState) -> str:
    """Only mention conditions that are actually true, to save tokens and noise."""
    bits = []
    if state.stats.stamina <= 20:
        bits.append("exhausted")
    if state.stats.hp <= state.stats.max_hp * 0.4:
        bits.append("hurt")
    if state.hunger >= 60:
        bits.append("hungry")
    for wound in state.wounds:
        bits.append(wound.text)
    return "CONDITION: " + ", ".join(bits) if bits else ""


def world_state_block(state: GameState, evil_snapshot: dict[str, Any]) -> str:
    """Block 1 -- volatile world facts."""
    loc = LOCATIONS.get(state.location_id, {})
    parts = [
        "WORLD STATE",
        f"Player: {state.player_name}, {state.archetype}",
        f"Place: {loc.get('name', state.location_id)} ({state.location_id})",
        f"Time: day {state.world_day}, {state.world_hour:02d}:00 ({state.time_of_day})",
        f"Body: hp {state.stats.hp}/{state.stats.max_hp}, "
        f"stamina {state.stats.stamina}/{state.stats.max_stamina}, "
        f"gold {state.stats.gold}",
    ]
    condition = _condition_block(state)
    if condition:
        parts.append(condition)
    for block in (
        _npcs_present_block(state),
        _encounter_block(state),
        _objectives_block(state),
        _events_block(state),
        _rumors_block(state),
    ):
        if block:
            parts.append(block)

    # GM-only. Wrapped for the awareness gate so a low-awareness run cannot have
    # the antagonist named back at it, and phrased qualitatively -- raw floats
    # invite the model to paraphrase them as "about forty percent along".
    phase = str(evil_snapshot.get("evil_phase", "dormant"))
    pressure = float(evil_snapshot.get("story_pressure", 0.0))
    tone = "quiet" if pressure < 25 else "restless" if pressure < 55 else "urgent"
    parts.append(
        mark_spoiler(
            "GM ONLY (never state or hint at these as numbers): "
            f"the pattern is {phase}; the story wants to be {tone}."
        )
    )
    return "\n".join(parts)


def memory_blocks(
    ledger: "StoryLedger",
    *,
    present_npc_ids: tuple[str, ...] = (),
) -> tuple[str, str]:
    """
    Blocks 2 and 3 -- the running summary and the live threads.

    Returns (summary_block, threads_block); either may be empty.
    """
    summary_block = ""
    if ledger.summary.strip():
        summary_block = "THE STORY SO FAR\n" + ledger.summary.strip()

    lines: list[str] = []

    facts = ledger.salient_facts(limit=6, subject_ids=present_npc_ids)
    if facts:
        lines.append("REMEMBERED")
        lines.extend(f"- {f.text}" for f in facts)

    if ledger.names:
        lines.append("NAMES ALREADY GIVEN (use these exactly)")
        lines.extend(f"- {n}: {g}" for n, g in list(ledger.names.items())[:10])

    promises = ledger.open_promises()
    if promises:
        lines.append("OUTSTANDING")
        for promise in promises[:4]:
            due = f" (by day {promise.due_day})" if promise.due_day else ""
            lines.append(f"- {promise.from_id} owes {promise.to_id}: {promise.text}{due}")

    for npc_id in present_npc_ids:
        rel = ledger.relations.get(npc_id)
        if rel is None or not rel.met:
            continue
        mood = (
            "warm toward you"
            if rel.disposition >= 30
            else "wary of you"
            if rel.disposition <= -30
            else "neutral toward you"
        )
        lines.append(f"- {npc_id} has met you and is {mood}.")

    return summary_block, "\n".join(lines)


def receipts_block(receipts: list[dict[str, Any]]) -> str:
    """
    Phase B input: what the engine actually resolved.

    This is the block that makes "never invent dice results" achievable. The
    old prompt asked for tool calls and narration in the same message, so the
    model could not possibly know an outcome it was forbidden to invent.
    """
    if not receipts:
        return ""

    lines = ["MECHANICAL RESULTS -- AUTHORITATIVE. Narrate these outcomes.",
             "Do not restate the numbers; render them as events."]
    for receipt in receipts:
        result = receipt.get("result") or {}
        if not receipt.get("success", False):
            lines.append(f"- {receipt.get('skill')} failed: {result.get('error', 'unknown')}")
            continue

        skill = receipt.get("skill")
        if receipt.get("type") == "dice":
            summary = result.get("summary")
            if summary:
                lines.append(f"- {summary}")
            else:
                lines.append(f"- {skill} -> {result}")
        elif skill == "move_to":
            lines.append(
                f"- travelled to {result.get('to_id')} "
                f"({result.get('hours', 0)}h, {result.get('stamina_cost', 0)} stamina)"
            )
        elif skill == "trade":
            lines.append(f"- trade: {result}")
        else:
            lines.append(f"- {skill} -> {result}")
    return "\n".join(lines)


def assistant_system_prompt(state: GameState, *, hint_tier: int) -> str:
    """
    Assistant prompt -- in-world presence, not a tutorial.

    Deliberately still short and stateless. The Assistant is meant to be a
    voice at the edge of the scene, and giving it history would make it
    conversational, which is exactly what it must not be.
    """
    from engine.skills.builtin.assistant import ASSISTANT_FORMS

    mind = state.assistant_mind
    form = mind.current_form

    return f"""\
You are the ASSISTANT in "The Clockwork Dark" -- an in-world presence, NOT a
tutorial and NOT an AI. In Edgewood folklore you are the Grey Wanderer, the Cat
Who Knows, the Tinker's Shadow. You may help, mislead by omission, or say
nothing worth acting on.

VOICE
- 1-3 sentences. Never more.
- Folklore register: oblique, concrete, a little wry. Speak in images.
- Never mention dice, stats, rules, or outcomes.
- Never address the player as a player. You are speaking to a person.
- You may be wrong. You are never earnest.

Good: "The smoke is bread, not burning. Probably."
Good: "Wheat remembers what the field forgets."
Bad:  "You should try a stealth check here!"
Bad:  "As your assistant, I recommend..."

FORMS: {", ".join(ASSISTANT_FORMS)}
CURRENT FORM: {form} -- speak as this.
HINT TIER: {hint_tier} (0 says almost nothing; 3 may name places and people)

PLAYER: {state.player_name}
PLACE: {state.location_id}, day {state.world_day}, {state.time_of_day}

You may use [VOICE:whisper] or [VOICE:urgent] to colour the delivery.
"""


def evaluator_retry_prompt(eval_notes: list[str], rejected_draft: str = "") -> str:
    """
    Feedback for a rejected draft.

    The draft is included. The old version said "fix these issues" while the
    model had no access to the text it was being asked to fix -- a scolding
    prefix on a blind re-roll, not a repair loop.
    """
    issues = "\n".join(f"- {n}" for n in eval_notes) or "- unspecified"
    parts = ["Your previous draft was rejected."]
    if rejected_draft:
        excerpt = rejected_draft.strip()
        if len(excerpt) > 1200:
            excerpt = excerpt[:1200] + "..."
        parts.append(f"REJECTED DRAFT:\n{excerpt}")
    parts.append(f"PROBLEMS:\n{issues}")
    parts.append(
        "Rewrite it. Keep whatever worked. Do not claim any outcome the "
        "MECHANICAL RESULTS block did not give you."
    )
    return "\n\n".join(parts)


def storyteller_system_prompt(state: GameState, evil_snapshot: dict) -> str:
    """
    Backwards-compatible single-string prompt.

    The two-phase loop assembles blocks itself via engine/memory/context.py;
    this remains for direct callers and tests.
    """
    return f"{STORYTELLER_PERSONA}\n\n{world_state_block(state, evil_snapshot)}"

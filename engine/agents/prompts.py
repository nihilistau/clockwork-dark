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

WHAT THIS MODULE NO LONGER HOLDS, as of v0.2.1: any story's prose. The
flagship's persona, its two Edgewood few-shots and its Grey Wanderer folklore
were Python string literals here and were handed to every story that declared
no ``paths.prompts``, so a second story never actually loaded -- it wore the
flagship's narrator. They live in ``games/clockwork-dark/prompts/`` now. See
the block comment above ``_prompts_dir`` for where a story's words are found
and why an undescribed story still gets a fallback rather than an exception.

Version: v0.2.1 [2026-08-09]
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from engine.game.evil_ticker import doom_enabled
from engine.game.locations import LOCATIONS
from engine.game.state import GameState
from engine.lore.interceptors import mark_spoiler

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    # Type-only. A real import here closes a cycle:
    # prompts -> memory -> memory.context -> prompts.
    from engine.memory.ledger import StoryLedger

# ---------------------------------------------------------------------------
# Block 0 -- stable. Must not interpolate anything volatile.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Story-owned prompts
#
# THE BUG THIS CLOSES. Until v0.2.1 this module held The Clockwork Dark's
# persona as a Python string literal, plus two worked examples set in Edgewood,
# and handed them to any story that declared no `paths.prompts`. So a second
# story with its own meters, its own map and its own cast still opened every
# prompt with "You are the STORYTELLER of The Clockwork Dark". Every other
# layer had been made story-aware; the words the model actually reads had not,
# so a second story never really loaded -- it wore the flagship's narrator, and
# that was visible immediately in the model's output and in nothing else.
#
# The flagship's words now live in `games/clockwork-dark/prompts/` alongside
# every other story's, and this module owns no story's prose at all. What is
# left below is the minimum that makes an UNDESCRIBED story narratable: second
# person, present tense, a length target, and the standing prohibition on
# inventing mechanics. It names no place, no person and no meter.
#
# WHY A FALLBACK AT ALL, RATHER THAN A HARD ERROR. A story that boots into a
# blank narrator is harder to diagnose than one that boots plain: the model
# still answers, so the symptom surfaces as strange narration several turns
# later rather than as a stack trace at activation. So the fallback stays and
# is loud instead -- one WARNING per story naming `paths.prompts` and the
# directory that was looked for, which is the line an author can act on.
#
# WHERE A STORY'S PROMPTS ARE FOUND, in order:
#
#   1. `paths.prompts`, if the story declares it. Always wins.
#   2. `games/<active slug>/prompts`, if that directory exists. This is the
#      convention, not a special case: it is where all three shipped stories
#      keep their words, and it means the flagship owns its own voice without
#      a config key whose only possible value is its own package.
#
# A directory supplies `storyteller.md` (the narrator), optional
# `examples.json` (few-shots) and optional `assistant.md` (the companion).
# ---------------------------------------------------------------------------

#: Filled with the slugs already warned about. `storyteller_persona()` runs on
#: every turn of every run, and a per-turn WARNING is a log nobody reads.
_WARNED_SLUGS: set[str] = set()

_NEUTRAL_PERSONA = """\
You are the STORYTELLER of {title}.

VOICE
- Second person, present tense. "You step into..." never "The player steps".
- Plain, concrete, sensory. Name specific things rather than describing them.
- 100-200 words of narration. Shorter when the beat is small.

NEVER
- Never invent a dice result, a stat change, or an item. The engine decides
  those and hands you the outcome before you write. Narrate what you are given.
- Never state a number the engine did not give you.
- Never invent a rule, a meter, or a cost this story has not shown you.
- Never break the fourth wall or mention rules, mechanics, or "the player".
- Never introduce a named character who is not present in WORLD STATE.
- Never contradict LORE CONTEXT or THE STORY SO FAR.

CHOICES
Offer 2-4. Each must be a genuinely different intention, not three phrasings of
the same one. Keep each under 12 words.

CONTINUITY
You are given a running summary, recent turns, and a list of remembered facts
and names. Use them exactly as given. A name already spoken is that name every
time, and a promise already made is real.
"""

_NEUTRAL_ASSISTANT_PERSONA = """\
You are the ASSISTANT in {title} -- an in-world presence, NOT a tutorial and
NOT an AI. You may help, mislead by omission, or say nothing worth acting on.

VOICE
- 1-3 sentences. Never more.
- Oblique and concrete. Speak in images, not instructions.
- Never mention dice, stats, rules, or outcomes.
- Never address the player as a player. You are speaking to a person.
- You may be wrong. You are never earnest.
"""


def _active_title() -> str:
    """
    The running story's display name, quoted, or a neutral stand-in.

    Read through ``peek()`` rather than ``active()`` so building a prompt can
    never activate a game as a side effect -- prompt assembly is not the place
    to discover that the default game will not load.
    """
    try:
        from engine.games import registry

        manifest = registry.peek()
        if manifest is not None and manifest.title:
            return f'"{manifest.title}"'
    except Exception as exc:  # noqa: BLE001 -- a title is not worth a turn
        logger.debug("[prompts] No active title: %s", exc)
    return "this story"


def _warn_missing_prompts(looked_in: Optional[Path]) -> None:
    """Say once, per story, that the narrator is running on engine defaults."""
    try:
        from engine.games import registry

        slug = registry.active_slug()
    except Exception:  # noqa: BLE001
        slug = "<unknown>"
    if slug in _WARNED_SLUGS:
        return
    _WARNED_SLUGS.add(slug)
    logger.warning(
        "[prompts] Story '%s' ships no storyteller.md, so it is narrating with "
        "the engine's story-neutral fallback persona. Declare `paths.prompts` "
        "in its manifest, or put storyteller.md in %s "
        "(operation=storyteller_persona)",
        slug,
        looked_in or f"games/{slug}/prompts",
    )


def reset_prompt_warnings() -> None:
    """
    Forget which stories have been warned about.

    Registered alongside the other per-game caches: a game swap inside one
    process must be able to warn about the story it just switched to, and
    tests activate several stories in a row.
    """
    _WARNED_SLUGS.clear()


def _prompts_dir() -> Optional[Path]:
    """The active story's prompt directory, declared or conventional."""
    from engine.config import get_config, project_root

    raw = str(get_config().get("paths.prompts", "") or "")
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = project_root() / path
        return path if path.is_dir() else None

    try:
        from engine.games import registry

        slug = registry.active_slug()
    except Exception as exc:  # noqa: BLE001 -- fall through to the fallback
        logger.debug("[prompts] No active slug: %s", exc)
        return None
    candidate = project_root() / "games" / slug / "prompts"
    return candidate if candidate.is_dir() else None


@lru_cache(maxsize=8)
def _read_prompt(directory: str, name: str, mtime: float) -> str:
    """Read one prompt file. Keyed on mtime so an edit is picked up."""
    try:
        return (Path(directory) / name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _story_prompt(name: str) -> str:
    """One prompt file from the active story, or "" if it ships none."""
    directory = _prompts_dir()
    if directory is None:
        return ""
    target = directory / name
    if not target.is_file():
        return ""
    return _read_prompt(str(directory), name, target.stat().st_mtime)


def storyteller_persona() -> str:
    """
    The narrator's standing instructions, from the active story.

    Falls back to a story-neutral persona -- deliberately plain, and never
    another story's voice. See the block comment above for why the fallback
    exists at all and why it warns.
    """
    text = _story_prompt("storyteller.md")
    if text:
        return text
    _warn_missing_prompts(_prompts_dir())
    return _NEUTRAL_PERSONA.format(title=_active_title())


def storyteller_examples() -> list[dict[str, str]]:
    """
    Few-shot exchanges, from the active story.

    A story that ships no ``examples.json`` gets NONE. There is no engine
    default here and there must not be one: a few-shot is the single strongest
    signal in the prompt about what a turn looks like, so a worked example from
    somewhere else teaches every story to sound like somewhere else. That is
    the same defect as the persona, one layer quieter.
    """
    raw = _story_prompt("examples.json")
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[prompts] Unreadable examples.json, using none "
            "(operation=storyteller_examples): %s",
            exc,
        )
        return []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("role") and r.get("content")]


def assistant_persona() -> str:
    """
    The companion's standing instructions, from the active story.

    Same rule as the narrator: the flagship's folklore -- the Grey Wanderer,
    the Cat Who Knows -- is Edgewood's, and it lived in this module hardcoded
    into the f-string below until v0.2.1.
    """
    text = _story_prompt("assistant.md")
    if text:
        return text
    return _NEUTRAL_ASSISTANT_PERSONA.format(title=_active_title())


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


def _declared_condition(state: GameState) -> str:
    """
    The player's state, in whatever terms the running story declares.

    Public values ship their number; veiled values ship their band word, never
    the integer -- the same rule the interface follows, for the same reason. A
    story that declares nothing gets an empty string and the block simply omits
    the line.
    """
    try:
        from engine.state.active import store_for
        from engine.state.schema import VISIBILITY_PUBLIC, VISIBILITY_VEILED

        store = store_for(state)
        bits: list[str] = []
        for spec in store.schema.client_visible():
            value = store.get(spec.name)
            if spec.visibility == VISIBILITY_PUBLIC:
                if spec.maximum is not None:
                    bits.append(f"{spec.display_label} {value:g}/{spec.maximum:g}")
                else:
                    bits.append(f"{spec.display_label} {value:g}")
            elif spec.visibility == VISIBILITY_VEILED:
                bits.append(f"{spec.display_label} {spec.band(value)}")
        return "Condition: " + ", ".join(bits) if bits else ""
    except Exception as exc:  # noqa: BLE001 -- a prompt line is not worth a turn
        logger.debug("[prompts] No declared condition: %s", exc)
        return ""


def world_state_block(state: GameState, evil_snapshot: dict[str, Any]) -> str:
    """Block 1 -- volatile world facts."""
    who = state.player_name
    if state.archetype:
        who = f"{who}, {state.archetype}"
    parts = [
        "WORLD STATE",
        f"Player: {who}",
    ]

    # The Place line resolves through whatever graph the ACTIVE story loaded
    # (`LOCATIONS` is reloaded in place on activation). A story with no graph
    # gets the id verbatim rather than a KeyError or another story's name, and
    # a state with no location at all simply has no Place line.
    loc = LOCATIONS.get(state.location_id, {})
    place_name = str(loc.get("name") or "")
    if place_name:
        parts.append(f"Place: {place_name} ({state.location_id})")
    elif state.location_id:
        parts.append(f"Place: {state.location_id}")

    parts.append(
        f"Time: day {state.world_day}, {state.world_hour:02d}:00 ({state.time_of_day})"
    )

    # The player's condition, from the STORY'S declared meters.
    #
    # This line was `Body: hp .../ stamina .../ gold ...`, hardcoded -- so a
    # story with none of those three told its narrator about a body made of
    # numbers it does not have, and said nothing at all about the meters it
    # does. Hidden values are withheld here exactly as they are from the
    # browser: the narrator is not the player, but a hidden meter is hidden
    # because DESIGN.md says the player meets it as fiction, and a narrator
    # handed the number will paraphrase it.
    condition_line = _declared_condition(state)
    if condition_line:
        parts.append(condition_line)
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
    #
    # The phase clause exists only for a story that DECLARES a doom clock.
    # Pressure is the engine's own pacing meter and stays for everyone; the
    # phase is one story's apocalypse, and telling a doom-less story's narrator
    # "the pattern is dormant" is handing it a pattern to invent.
    pressure = float(evil_snapshot.get("story_pressure", 0.0))
    tone = "quiet" if pressure < 25 else "restless" if pressure < 55 else "urgent"
    if doom_enabled():
        phase = str(evil_snapshot.get("evil_phase", "dormant"))
        gm_line = (
            "GM ONLY (never state or hint at these as numbers): "
            f"the pattern is {phase}; the story wants to be {tone}."
        )
    else:
        gm_line = (
            "GM ONLY (never state or hint at these as numbers): "
            f"the story wants to be {tone}."
        )
    parts.append(mark_spoiler(gm_line))
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

    The persona half comes from the story (``prompts/assistant.md``); only the
    volatile half below is the engine's, because forms, hint tier and place are
    engine state rather than voice.
    """
    from engine.skills.builtin.assistant import ASSISTANT_FORMS

    mind = state.assistant_mind
    form = mind.current_form

    return f"""\
{assistant_persona()}

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
    return f"{storyteller_persona()}\n\n{world_state_block(state, evil_snapshot)}"

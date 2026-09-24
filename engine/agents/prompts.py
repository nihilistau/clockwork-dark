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

Version: v0.4.0 [2026-09-24]
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
from engine.state.schema import VEILED_BANDS

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

A choice that MOVES, SPENDS or RISKS anything also declares an `intent`, chosen
from WHAT A CHOICE CAN MAKE HAPPEN THIS TURN. That is a declaration, not a
result: the ENGINE resolves it after the player picks it and hands you the
outcome before you write the next beat. Never write the outcome yourself, and
never write a choice as though it has already been taken. A choice that is only
talk or only looking declares no intent at all.

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


#: How many generated household people (procgen NPCs carrying a ``premise``
#: key) PEOPLE HERE names one by one before the rest collapse into a single
#: line. HUE & CRY's thirty-one houses put ~80 such people into its districts,
#: and a market at three in the afternoon held fifteen of them at once -- a
#: prompt block the size of a parish register, every line of it a stranger.
MAX_GENERATED_PRESENT = 4


def _npcs_present_block(state: GameState) -> str:
    """
    List NPCs present, with what they are doing.

    The cast comes from the schedules. This used to bail out with "(world not
    yet generated)" whenever procgen had made no villagers -- true of every
    story but the flagship -- so a vendor standing at her own stall was offered
    by the buy intent and invisible to the narrator, and the cast gate then
    failed any prose that named her.

    THE CAP. Every scheduled cast member is listed individually, always --
    they are the story. Generated household people (a ``premise`` key on
    their procgen row, engine/world/premises.py) are listed individually up
    to ``MAX_GENERATED_PRESENT``, in the order presence returns them, and the
    remainder become one "and N more townsfolk" line. Procgen people without
    a ``premise`` key -- the flagship's villagers -- are untouched, so a story
    that declares no premises builds the byte-identical block.
    """
    from engine.world import npc_sim
    from engine.world.world_sim import merge_npcs_at_location

    present = merge_npcs_at_location(state, state.location_id)
    if not present:
        return "PEOPLE HERE: nobody."

    lines = []
    generated_listed = generated_more = 0
    for npc in present:
        if npc.get("premise") and not npc_sim.is_scheduled(str(npc.get("id") or "")):
            if generated_listed >= MAX_GENERATED_PRESENT:
                generated_more += 1
                continue
            generated_listed += 1
        npc_id = str(npc.get("id") or "")
        name = npc.get("name") or npc_sim.display_name(npc_id, state)
        role = f" ({npc.get('role')})" if npc.get("role") else ""
        bits = [f"- {npc_id}: {name}{role}"]
        activity = npc.get("activity")
        if activity:
            bits.append(f" -- {activity}")
        if npc.get("visiting"):
            bits.append(" [visiting]")
        lines.append("".join(bits))
    if generated_more:
        noun = "townsfolk" if generated_more > 1 else "townsperson"
        lines.append(f"- and {generated_more} more {noun} about their business")
    return "PEOPLE HERE:\n" + "\n".join(lines)


def district_block(state: GameState) -> str:
    """
    The houses in this district and what the player has learned of each.

    KNOWN INTEL ONLY. A narrator handed a house's full contents writes the
    dog into the yard before anybody has watched it -- the spoiler the
    casing verb exists to earn. So each line carries only what
    ``state.premise_intel`` records, an unknown line is not mentioned at all,
    and ids and tiers never appear: the house's name is how the prose refers
    to it. Empty for a story that declares no premises, which keeps its prompt
    byte-identical.
    """
    from engine.world import premises

    if not premises.declared():
        return ""
    here = premises.at(state, state.location_id)
    if not here:
        return ""
    lines = ["PREMISES HERE (what you know):"]
    for prem in here:
        premise_id = str(prem.get("id") or "")
        spec = premises.spec(str(prem.get("type") or ""))
        label = str(spec.get("label") or prem.get("type") or "house").replace("_", " ")
        learned = set(premises.known(state, premise_id))
        texts = [
            row["text"]
            for row in premises.intel_for(state, premise_id)
            if row["id"] in learned
        ] if learned else []
        known_text = "; ".join(texts) if texts else "nothing known yet"
        lines.append(f"- {prem.get('name') or label} ({label}): {known_text}")
    return "\n".join(lines)


#: The most HAPPENING NOW carries. The world block is non-evictable, and
#: permanent clock marks accumulate for the whole run.
MAX_EVENT_LINES = 3


def _events_block(state: GameState) -> str:
    """
    What is going on around the player, in the story's own words.

    WHAT IT USED TO PRINT: "- forecast_traffic_spike at None (since day 14)" --
    an id, a location that was often None, and nothing an author wrote. The
    authored sentence sat on the same row, unread. It is filtered to events the
    player could see from here, capped, and it never renders a row that has no
    words: a forced scene is the director's business, and an id is not prose.
    """
    here = str(state.location_id or "")
    lines: list[str] = []
    for event in reversed(state.world_events):
        if event.get("forces_scene"):
            continue
        where = str(event.get("location_id") or "")
        if where and where != here:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        text = str(event.get("text") or payload.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"- {text}")
        if len(lines) >= MAX_EVENT_LINES:
            break
    if not lines:
        return ""
    return "HAPPENING NOW:\n" + "\n".join(reversed(lines))


def moved_block(state: GameState, ledger: Any = None) -> str:
    """
    What changed since the narrator last looked. Each line once, never again.

    Fed by engine/game/moved.py, which the system that caused each change
    writes to in its own words. The instruction is to USE what fits rather than
    recite it: a narrator handed a list will read the list out.
    """
    from engine.game import moved

    rows = moved.visible(state)
    if not rows:
        return ""
    return "SINCE YOU LAST LOOKED (work in what fits; never list it):\n" + "\n".join(
        f"- {row['text']}" for row in rows
    )


def _rumors_block(state: GameState) -> str:
    if not state.rumors:
        return ""
    lines = [f"- {r}" for r in state.rumors[-3:]]
    return "RUMORS IN THE AIR:\n" + "\n".join(lines)


def _law_clarity(precision: float) -> str:
    """Two words, never a number: a hop-1 sighting is either full or partial."""
    return "clearly" if precision >= 1.0 else "only a glimpse"


def _law_last_deed_witnesses(state: GameState) -> list[dict[str, Any]]:
    """
    The hop-1 witness rows of a deed committed THIS TURN, or ``[]``.

    FRESHNESS IS THE TURN. ``commit_deed`` records every deed, seen or not,
    in ``state.law["last_deed"]`` (the ``law_last_deed`` effect): a seen one
    stamped with ``state.turn_number`` -- which the storyteller advances only
    after the turn's narration is committed, so a stamp equal to the current
    counter is a deed this turn's intent committed -- and an unseen one by
    removing the stamp, so it names nobody. A turn that committed no deed
    leaves an older stamp, and names nobody either. Reading "the newest
    witnessed deed of today" instead named an earlier lift's witnesses all day
    after an unseen one, people who were not even in the room. HOP 1 ONLY: a
    propagated copy is someone ELSE'S account reaching a third party, not the
    player being seen.
    """
    last = state.law.get("last_deed") or {}
    deed_id = str(last.get("id") or "")
    if not deed_id or last.get("turn") != state.turn_number:
        return []
    return [
        r for r in (state.law.get("witnessed") or [])
        if int(r.get("hop") or 1) == 1 and str(r.get("deed_id") or "") == deed_id
    ]


def law_block(state: GameState) -> str:
    """
    What the Law knows and does about the player, right now.

    "" for a story that declares no ``paths.law`` -- the flagship's prompt
    stays byte-identical (Global Constraints, the v0.10.0 plan). Otherwise,
    only the lines that apply:

      - who saw the deed committed this turn, if any
        (``_law_last_deed_witnesses``), by display name, never an id;
      - the wanted band for the guise currently worn, in words, in THIS
        jurisdiction -- and only when it is above the story's own floor band
        (typically "unknown"), since "nobody is looking for you" is not a
        line worth the narrator's attention every turn;
      - the law-role people standing here, by display name;
      - custody, if held: the fine in the story's own money and the days in
        words.

    NEVER A NUMBER FROM THE LAW (Global Constraints): no score, no precision,
    no id. The fine is money, which the narrator already sees in plain
    figures everywhere else in this prompt (a quest reward, a sale) -- it is
    the Law's own arithmetic that stays hidden, not the story's currency.
    """
    from engine.game.trade import currency_label
    from engine.world import law, npc_sim

    if not law.declared():
        return ""

    lines: list[str] = []

    seen = _law_last_deed_witnesses(state)
    if seen:
        bits = [
            f"{npc_sim.display_name(str(row.get('npc') or ''), state)} saw you "
            f"{_law_clarity(float(row.get('precision') or 0.0))}"
            for row in seen
        ]
        lines.append("You were seen: " + "; ".join(bits) + ".")

    jurisdiction = law.jurisdiction_at(state.location_id)
    spec = law.load_spec()
    bands = (spec.get("wanted") or {}).get("bands") or []
    if jurisdiction and bands:
        guise = law.current_guise(state)
        band = law.wanted_band(state, guise, jurisdiction)
        if band and band != bands[0]:
            where = law.jurisdiction_label(jurisdiction)
            lines.append(
                f"The watch in {where} is looking for {law.guise_label(guise)}: {band}."
            )

    roles = set(spec.get("roles") or [])
    watch_here = [
        npc_sim.display_name(person.npc_id, state)
        for person in npc_sim.npcs_at(state, state.location_id)
        if person.available and person.role in roles
    ]
    if watch_here:
        lines.append("Standing here, watching: " + ", ".join(watch_here) + ".")

    held = law.custody(state)
    if held:
        fine = currency_label(int(held.get("fine") or 0))
        days = _days(held.get("days"))
        lines.append(f"You are held: {fine} pays your way out, or {days} served.")

    if not lines:
        return ""
    return "THE LAW:\n" + "\n".join(lines)


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
    except Exception as exc:  # noqa: BLE001 — the prompt must build without quests
        # Logged, not swallowed: a quest bug here silently removed the
        # player's objectives from the prompt with no trace anywhere.
        logger.warning("[prompts] Objectives unavailable (operation=_objectives_block): %s", exc)
        return ""
    # A flag already raised is not a beat still to reach.
    allowed = [flag for flag in allowed if not state.flags.get(flag)]

    if not objectives:
        return ""

    lines = ["OBJECTIVES (the player's current threads):"]
    lines += [f"- {text}" for text in objectives[:6]]
    if allowed:
        # The lever is the `flag` INTENT on a choice. `set_narrative_flag` is
        # the skill behind it, which the turn grammar gives the model no way to
        # call -- this line named a tool the narrator could not reach.
        lines.append(
            "Give a choice the `flag` intent ONLY when taking it would genuinely "
            "reach one of these beats: " + ", ".join(sorted(allowed)[:12])
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


def obligations_block(state: GameState) -> str:
    """
    Contracts the player has actually sealed, with their terms and their due day.

    THE GAP THIS CLOSES. ``engine/game/threads.py`` is 1,220 lines and three
    shipped stories declare a ``threads.yaml``. A sealed thread gates choices,
    charges its terms and comes due on a named day -- and until now the narrator
    was never told any thread existed. ``threads.summary`` has said in its own
    docstring since it was written that it is "trimmed for a prompt block or a
    UI list"; only the UI half was ever built, so the engine enforced bargains
    the prose could not refer to.

    NOT GM-ONLY, and not spoiler-wrapped. The player was there when they sealed
    it: a contract is the one piece of world state they are guaranteed to know
    better than the narrator does. What stays out is what ``summary`` already
    withholds -- the effect hooks -- because a model handed the numbers will
    narrate the numbers.
    """
    from engine.game import threads as threads_module

    if not threads_module.is_declared():
        return ""
    rows = threads_module.summary(state)
    if not rows:
        return ""

    lines = ["CONTRACTS YOU ARE UNDER (the player sealed these; honour them):"]
    for row in rows:
        # The terms on their own line, with their own punctuation intact. They
        # are AUTHORED prose -- a sentence somebody wrote for this bargain --
        # and running the bookkeeping onto the end of it with a semicolon read
        # as "...at their convenience.; made with sophia".
        lines.append(f"- {str(row.get('terms') or '').strip() or row.get('id')}")
        aside: list[str] = []
        source = str(row.get("source") or "").strip()
        if source:
            aside.append(f"with {source}")
        sealed = str(row.get("sealed_by") or "").strip()
        if sealed:
            aside.append(f"sealed by {sealed}")
        due = row.get("due_day")
        if due is not None:
            aside.append(f"due day {due}")
        cutters = [str(c) for c in (row.get("can_cut_with") or []) if c]
        if cutters:
            aside.append("severed only by " + ", ".join(cutters))
        if aside:
            lines.append(f"  ({', '.join(aside)})")
    return "\n".join(lines)


def _clocks_block(state: GameState) -> str:
    """
    What the story's named clocks are doing, as words rather than as readings.

    GM-ONLY, and the caller spoiler-wraps it. A clock is the engine building
    pressure on a schedule; before this the narrator could not feel it coming,
    so THE LONG CON's `the_frame` filled in silence and then dealt an authored
    interrogation out of a clear sky.

    THE LABEL WAS ALREADY WRITTEN AND NOBODY READ IT. Each clock carries a
    `label:` in the story's own clocks.yaml -- "How this ends up being your
    fault", "The roots are counting", "Winter, being patient" -- eight of them
    across five shipped games, and nothing in the engine had ever loaded one.
    They are GM-facing by construction: they say what the clock MEANS, which is
    exactly what a narrator needs and exactly what the player-facing label in
    state.yaml ("The frame") does not say.

    The reading is banded through the same `Spec.band` the client projects a
    veiled meter with, so the GM and the player never hold two vocabularies for
    one number, and a clock still at its floor is left out entirely rather than
    announced as nothing.
    """
    from engine.game import clocks as clocks_module

    names = clocks_module.clock_names()
    if not names:
        return ""

    store = None
    try:
        from engine.state.active import store_for

        store = store_for(state)
    except Exception as exc:  # noqa: BLE001 -- a prompt block must not kill a turn
        logger.debug("[prompts] No state store for clocks: %s", exc)
    if store is None:
        return ""

    table = clocks_module.load_clocks()
    lines: list[str] = []
    for name in names:
        spec = store.schema.get(name)
        if spec is None:
            continue
        value = clocks_module.value_of(state, name)
        band = spec.band(value)
        if band == VEILED_BANDS[0]:
            continue
        label = str((table.get(name) or {}).get("label") or "").strip()
        lines.append(f"- {label or spec.display_label}: {band}")

    if not lines:
        return ""
    return "WHAT IS CLOSING IN (never name these, never count them aloud):\n" + "\n".join(
        lines
    )


def _scene_block(state: GameState) -> str:
    """
    The authored card in front of the player, if a scene is open.

    Same contract as ``_encounter_block``: the text is AUTHORED, the options are
    engine-fixed, and the narrator renders them rather than inventing. This is
    the whole point of dealing a hand before narration -- the card's prose is a
    writer's, not a sampler's, and a narrator told to "narrate the scene" with
    no card in the prompt would write its own.

    Empty string for a story that declares no decks, which is the same
    contribution ``_intents_block`` makes for a story with no legal intents.
    """
    try:
        from engine.content import director

        card = director.current_card(state)
        if card is None:
            return ""
        rows = director.options(state)
    except Exception as exc:  # noqa: BLE001 -- a story with no decks
        logger.debug("[prompts] No scene director: %s", exc)
        return ""

    lines = ["THE SCENE IN FRONT OF THE PLAYER, AUTHORED -- render it, do not replace it:"]
    if card.title:
        lines.append(str(card.title))
    if card.text:
        lines.append(str(card.text))
    if rows:
        lines.append(
            "Their options are fixed by the engine. Offer these and no others:"
        )
        for row in rows:
            lines.append(f"- {row['id']}: {row['text']}")
    return "\n".join(lines)


def _intents_block(state: GameState) -> str:
    """
    What a choice is allowed to make happen this turn, in words.

    The grammar already forbids everything else -- the ``intent`` enums are
    built from this same catalogue, so an unreachable destination cannot be
    sampled at all. This block exists because a constraint is not an
    instruction: the sampler can stop the model naming a road that is not
    there, and only the prompt can tell it that naming the road it IS on is how
    a choice becomes a walk.

    Empty for a story the engine can honour nothing for, which keeps that
    story's prompt byte-identical to the one it had.
    """
    try:
        from engine.game.intents import legal_intents

        verbs = legal_intents(state)
    except Exception as exc:  # noqa: BLE001 -- a prompt line is not worth a turn
        logger.debug("[prompts] No intent catalogue: %s", exc)
        return ""
    if not verbs:
        return ""

    lines = [
        "WHAT A CHOICE CAN MAKE HAPPEN THIS TURN",
        "A choice that MOVES, SPENDS or RISKS anything carries an `intent` "
        "naming one of these. The ENGINE resolves it and tells you the outcome "
        "next turn -- you never decide it and never write it as already done. "
        "A choice that is only talk or only looking carries no intent.",
    ]
    for verb in verbs:
        if not verb.options:
            lines.append(f"- {verb.action}")
            continue
        rendered = ", ".join(
            f"{target} ({label})" if label != target else target
            for target, label in verb.options
        )
        lines.append(f"- {verb.action}: {rendered}")
    return "\n".join(lines)


def _condition_block(state: GameState) -> str:
    """Only mention conditions that are actually true, to save tokens and noise."""
    bits = []
    if state.stats.stamina <= 20:
        bits.append("exhausted")
    if state.stats.hp <= state.stats.max_hp * 0.4:
        bits.append("hurt")
    # The story's own thresholds, and its word for the stage. This was a bare
    # `hunger >= 60`, which ignored a story's survival.yaml and could never say
    # "starving" -- the stage that actually costs hit points.
    try:
        from engine.game.survival import hunger_stage

        stage = hunger_stage(state)
    except Exception as exc:  # noqa: BLE001 -- a condition line is not worth a turn
        logger.debug("[prompts] No hunger stage: %s", exc)
        stage = ""
    if stage in ("hungry", "starving"):
        bits.append(stage)
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
        district_block(state),
        law_block(state),
        _encounter_block(state),
        _scene_block(state),
        _intents_block(state),
        _objectives_block(state),
        _events_block(state),
        moved_block(state),
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

    # DIRECTION, not only level. "restless" and "restless, and rising" are
    # different scenes from the same number, and the level alone was all a
    # narrator ever got -- so a story easing off after a crisis and a story
    # winding toward one read identically. The threshold is deliberately coarse
    # for the same reason the tone words are: a band that flickers every turn
    # is noise the model will narrate.
    drift = pressure - float(getattr(state, "story_pressure_prev", 0.0) or 0.0)
    if drift > 2.0:
        tone = f"{tone}, and rising"
    elif drift < -2.0:
        tone = f"{tone}, and easing"

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
    clocks = _clocks_block(state)
    if clocks:
        gm_line = f"{gm_line}\n{clocks}"
    parts.append(mark_spoiler(gm_line))
    return "\n".join(parts)


def _mood(disposition: int) -> str:
    if disposition >= 60:
        return "close to you"
    if disposition >= 30:
        return "warm toward you"
    if disposition <= -60:
        return "hostile to you"
    if disposition <= -30:
        return "wary of you"
    return "neutral toward you"


def _dossier(
    ledger: "StoryLedger", npc_id: str, *, state: Optional[GameState] = None
) -> list[str]:
    """
    One character, as much as the narrator needs and no more.

    WHAT THIS REPLACES. The whole of a relation used to reach the model as a
    single sentence -- "maris has met you and is neutral toward you" -- while
    every fact filed against that person sat in the ledger unread. The engine
    remembered; the narrator was not told. That is why a character could greet
    you as a stranger on your fourth visit and invent a name for the thing you
    gave them.

    TWO FIELDS ARE DELIBERATELY NOT HERE. ``known_facts`` holds fact IDs, not
    prose -- it is an index into ``ledger.facts``, so rendering it printed
    ``knows: 208572d68f9613c9`` at the model, and the facts it indexes are
    already on the ``remembers:`` lines below in readable form. ``debts`` has
    no writer anywhere in the engine; showing an always-empty field would be a
    promise the ledger does not keep. Wire a writer first, then render it.
    """
    record = ledger.relations.get(npc_id)
    if record is None or not record.met:
        return []

    # A NAME, never the id. `ledger.names` is keyed by proper noun, so looking
    # an npc id up in it always missed and this printed "npc_maris
    # (npc_maris)"; the PEOPLE HERE block already maps id to name for the
    # model, so the prose half needs only the name.
    from engine.world import npc_sim

    name = npc_sim.display_name(npc_id, state)
    if name == "somebody":
        name = ledger.names.get(npc_id) or name
    head = f"- {name} has met you and is {_mood(record.disposition)}."
    if record.last_seen_location:
        place = (LOCATIONS.get(record.last_seen_location) or {}).get("name")
        head += f" Last seen at {place or record.last_seen_location}, day {record.last_seen_day}."
    out = [head]

    for fact in ledger.recall(npc_id, limit=3):
        out.append(f"    remembers: {fact.text}")
    for note in record.notes[-2:]:
        out.append(f"    about them: {note}")
    if record.owed:
        out.append(f"    you owe them: {', '.join(record.owed[-2:])}")
    if record.tags:
        out.append(f"    they are: {', '.join(record.tags[-3:])}")
    return out


def memory_blocks(
    ledger: "StoryLedger",
    *,
    present_npc_ids: tuple[str, ...] = (),
    location_id: str = "",
    topic_ids: tuple[str, ...] = (),
    state: Optional[GameState] = None,
) -> tuple[str, str]:
    """
    Blocks 2 and 3 -- the running summary and everything remembered.

    SUBJECTS, NOT JUST PEOPLE. This took ``present_npc_ids`` alone, so the only
    thing the engine could recall on purpose was a person. A fact filed against
    a room was stored correctly, ranked against every other fact in one shared
    top-six, and reached the prompt only if it happened to win -- which is why
    returning somewhere never felt like returning. A place and a topic now get
    their own budgeted section, and a talkative NPC can no longer crowd out the
    room the player is standing in.

    Args:
        present_npc_ids: Who is in the room. Each gets a dossier.
        location_id: Where the player is. Gets its own recall and notes.
        topic_ids: Story-declared subjects worth carrying (a case, a rumour).

    Returns:
        (summary_block, memory_block); either may be empty.
    """
    summary_block = ""
    if ledger.summary.strip():
        summary_block = "THE STORY SO FAR\n" + ledger.summary.strip()

    lines: list[str] = []

    # The global layer stays, smaller: it is what carries a detail that belongs
    # to no subject in particular. The per-subject sections below are what make
    # a specific person or room reliable.
    subjects = tuple(present_npc_ids) + ((location_id,) if location_id else ()) + tuple(topic_ids)
    facts = ledger.salient_facts(limit=4, subject_ids=subjects)
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

    dossiers: list[str] = []
    for npc_id in present_npc_ids:
        dossiers.extend(_dossier(ledger, npc_id, state=state))
    if dossiers:
        lines.append("WHO IS HERE, AND WHAT THEY REMEMBER")
        lines.extend(dossiers)

    if location_id:
        here: list[str] = [f"    {f.text}" for f in ledger.recall(location_id, limit=3)]
        record = ledger.relations.get(location_id)
        if record is not None:
            here.extend(f"    {note}" for note in record.notes[-3:])
        if here:
            lines.append("THIS PLACE, AS YOU LEFT IT")
            lines.extend(here)

    for topic_id in topic_ids:
        rows = ledger.recall(topic_id, limit=3)
        if rows:
            lines.append(f"ON {topic_id.replace('_', ' ').upper()}")
            lines.extend(f"    {f.text}" for f in rows)

    return summary_block, "\n".join(lines)


def mechanics_prompt(state: GameState) -> str:
    """
    Phase A's system prompt: resolve the turn, do not write it.

    Short on purpose. This call has tools and no grammar, and its entire product
    is receipts -- so every sentence spent describing prose style is a sentence
    inviting it to spend its token cap on prose nobody reads. The counterpart to
    ``receipts_block``, which feeds what this phase resolved into Phase B.

    STORY-NEUTRAL. No persona, no place-name, no tone: a narrator's voice
    belongs to Phase B and is loaded from the story's own ``prompts/``. Naming
    the flagship here would rebuild, in the mechanics half, exactly the bug that
    gave every story The Clockwork Dark's narrator.

    "Call nothing" is stated as a legitimate answer because it usually is. Most
    turns are conversation, and a model that believes it must call something
    will roll dice at a greeting.
    """
    return f"""\
You are the mechanics resolver for a text RPG. You do not narrate.

Your only job is to decide which engine tools this player action requires, call
them, and stop. The engine owns every outcome: dice, movement, stamina, time,
inventory, trade, quests. Never state a result you did not get back from a tool.

PLAYER: {state.player_name}
PLACE: {state.location_id}, day {state.world_day}, {state.time_of_day}

RULES
- Call a tool for anything with a mechanical result. Read a value rather than
  assuming it.
- CALL NOTHING if the action needs nothing mechanical. Most turns are talk, and
  an unnecessary roll is worse than no roll.
- Do not write prose, scene description, or dialogue. Anything you write here is
  discarded; only the tool results are kept.
- When you are finished calling tools, reply with the single word DONE.
"""


def receipts_block(receipts: list[dict[str, Any]]) -> str:
    """
    Phase B input: what the engine actually resolved.

    This is the block that makes "never invent dice results" achievable. The
    old prompt asked for tool calls and narration in the same message, so the
    model could not possibly know an outcome it was forbidden to invent.

    IT HAD NEVER BEEN POPULATED IN PRODUCTION. The only receipts that reached it
    came from a ``tool_calls`` array the turn grammar forbids, so on a live turn
    this function was handed an empty list and returned "". It carries the
    player's own resolved intent now (``engine/game/intents.py``), which is what
    turns the block from a promise into an input.

    TWO SOURCES FEED IT NOW, and they are different in kind. An INTENT receipt is
    what the player's chosen option declared and the engine ran before a word was
    written. A ``phase: mechanics`` receipt is what the MODEL chose to look up or
    do in Phase A over MCP (``engine/agents/mechanics.py``). Both are already
    true by the time this block is built, which is the only property the block
    cares about -- it renders facts the narration must report rather than decide.

    A REFUSAL IS RENDERED LOUDLY, and that is the point of the first branch. An
    intent can be legal when it is written and illegal by the time it runs --
    the stamina spent, the hour gone, the road closed. The one sentence a player
    must never read is that they walked somewhere they did not, so the engine's
    "no" is stated as a no rather than left to be inferred from a missing line.
    """
    if not receipts:
        return ""

    lines = ["MECHANICAL RESULTS -- AUTHORITATIVE. Narrate these outcomes.",
             "Do not restate the numbers; render them as events."]
    for receipt in receipts:
        result = receipt.get("result") or {}
        if receipt.get("refused"):
            lines.append(
                f"- REFUSED: the {receipt.get('skill')} did NOT happen. "
                f"Reason: {result.get('error', 'the engine declined')}. "
                "Write the attempt and why it came to nothing. Do not write it "
                "as succeeding."
            )
            continue
        if not receipt.get("success", False):
            lines.append(f"- {receipt.get('skill')} failed: {result.get('error', 'unknown')}")
            continue

        line = summarise_receipt(receipt)
        if line:
            lines.append(f"- {line}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# One sentence per receipt
# ---------------------------------------------------------------------------
#
# WHAT THIS REPLACES. Every skill without a special case fell through to
# `f"- {skill} -> {result}"`: a Python dict, printed at the model. A forage
# receipt measured ~1,600 characters including the DC, every roll and "stamina
# 94" -- numbers the block's own header tells the narrator not to restate, and
# in a veiled story numbers it must never see. Each summariser below says what
# HAPPENED in words, and the fallback for a skill nobody wrote one for says
# only that it happened: an unknown skill leaks nothing rather than everything.

_DEGREE_WORDS = {
    "crit_success": "brilliantly",
    "success": "well",
    "partial": "only partly",
    "failure": "badly",
    "crit_failure": "disastrously",
}


def _degree(result: dict[str, Any]) -> str:
    degree = str(result.get("degree") or (result.get("check") or {}).get("degree") or "")
    return _DEGREE_WORDS.get(degree, "")


def _money(amount: Any) -> str:
    from engine.game.trade import currency_label

    try:
        value = int(amount)
    except (TypeError, ValueError):
        return ""
    return currency_label(value)


def _place(location_id: Any) -> str:
    return str((LOCATIONS.get(str(location_id or "")) or {}).get("name") or location_id or "")


def _names(rows: Any) -> str:
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            name = row.get("name") or str(row.get("item_id") or "").replace("_", " ")
            qty = int(row.get("qty", 1) or 1)
            out.append(f"{name} x{qty}" if qty > 1 else str(name))
    return ", ".join(o for o in out if o)


def _authored(result: dict[str, Any]) -> str:
    """The skill's own prose line, when it wrote one."""
    return str(result.get("text") or "").strip()


def _sum_rest(result: dict[str, Any]) -> str:
    hours = result.get("hours")
    head = f"rested for {hours:g} hours" if isinstance(hours, (int, float)) else "rested"
    return " ".join(x for x in (head + ".", _authored(result)) if x)


def _sum_eat(result: dict[str, Any]) -> str:
    return " ".join(x for x in (f"ate the {result.get('name') or 'food'}.", _authored(result)) if x)


def _sum_forage(result: dict[str, Any]) -> str:
    found = _names(result.get("found") or result.get("items"))
    how = _degree(result)
    head = f"searched {_place(result.get('location_id'))}".strip()
    if how:
        head += f" and did {how}"
    tail = f"; found {found}" if found else "; found nothing worth carrying"
    return head + tail + "."


def _sum_work(result: dict[str, Any]) -> str:
    head = f"worked: {result.get('name') or 'a shift'}"
    how = _degree(result)
    if how:
        head += f", and did {how}"
    pay = _money(result.get("wage")) if result.get("wage") else ""
    kind = _names(result.get("in_kind"))
    paid = " and ".join(x for x in (pay, kind) if x)
    parts = [head + (f"; paid {paid}" if paid else "; paid nothing") + "."]
    if _authored(result):
        parts.append(_authored(result))
    return " ".join(parts)


def _sum_buy(result: dict[str, Any]) -> str:
    return (
        f"bought {result.get('name') or 'it'} from {result.get('vendor') or 'the vendor'}"
        f" for {_money(result.get('gold_spent'))}."
    )


def _sum_sell(result: dict[str, Any]) -> str:
    return (
        f"sold {result.get('name') or 'it'} to {result.get('vendor') or 'the buyer'}"
        f" for {_money(result.get('gold_gained'))}."
    )


def _sum_move(result: dict[str, Any]) -> str:
    hours = result.get("hours")
    where = _place(result.get("to_id"))
    return f"travelled to {where}" + (f", {hours:g} hours on the road." if hours else ".")


def _sum_thread(verb: str):
    def summarise(result: dict[str, Any]) -> str:
        thread = result.get("thread") if isinstance(result.get("thread"), dict) else {}
        terms = str(thread.get("terms") or result.get("terms") or "").strip()
        return f"{verb}: {terms}" if terms else f"{verb}."

    return summarise


def _sum_scene_begin(result: dict[str, Any]) -> str:
    # Never the hand. The card ids are the scene's future; the narrator is
    # handed each card as it is played.
    return "a new scene begins."


_HOURS_WORDS = {1: "an hour", 2: "two hours", 3: "three hours"}


def _sum_case(result: dict[str, Any]) -> str:
    # Words, not "2 of 5": the receipt's counts are for the casing board, and a
    # narrator handed them writes "the third of five things you noticed".
    where = result.get("premise") or "the house"
    hours = _HOURS_WORDS.get(result.get("hours"), "a while")
    learned = str(result.get("learned") or "").strip()
    head = f"watched {where} for {hours}"
    tail = f"; learned: {learned}." if learned else "."
    more = (
        " There is nothing more to learn by watching it."
        if result.get("known") is not None and result.get("known") == result.get("of")
        else ""
    )
    return head + tail + more


def _sum_lift(result: dict[str, Any]) -> str:
    # The mark by name, never the id; coin as the story's currency, never the
    # roll. A caught hand says "noticed" -- the one fact the narrator must not
    # soften into a clean getaway.
    from engine.world import npc_sim

    mark = str(result.get("mark") or "") or npc_sim.display_name(str(result.get("npc_id") or ""))
    if result.get("noticed"):
        return f"tried to lift {mark}'s purse and was noticed; took nothing."
    coin = _money(result.get("gold")) if result.get("gold") else ""
    took = [x for x in (coin, str(result.get("item") or "")) if x]
    # The mark not feeling it is not the same as nobody seeing it: with a
    # witness on the receipt (``seen_by``), "unnoticed" would be the one word
    # the evaluator exists to catch, handed to the narrator by the engine.
    witnessed = bool(result.get("seen_by"))
    if not took:
        if witnessed:
            return f"tried to lift {mark}'s purse; came away with nothing, and was seen trying."
        return f"tried to lift {mark}'s purse; came away with nothing, unnoticed."
    how = "fumbled a little loose coin" if result.get("degree") == "partial" else "lifted"
    if witnessed:
        return f"{how} from {mark}'s purse -- the mark never felt it, but it was seen: {' and '.join(took)}."
    return f"{how} from {mark}'s purse unnoticed: {' and '.join(took)}."


def _sum_change_guise(result: dict[str, Any]) -> str:
    # Never the id: only the authored label reaches the narrator, and the
    # sentence never distinguishes `self` from any other guise -- the label
    # alone (e.g. "your own face") already reads that way.
    label = str(result.get("label") or "").strip()
    base = f"You change into {label}" if label else "You change how you look"
    return base + (", and someone saw you do it." if result.get("seen") else ".")


def _sum_recognition(result: dict[str, Any]) -> str:
    # The officer by name and the face by its label -- never an id, never the
    # band or the chance, and never "the watch": a story's law may be a
    # constabulary, a temple guard or a corporate security detail, and only
    # its own names say which. The scene it opened is on the table; the
    # narrator writes the stop, not its outcome.
    who = str(result.get("name") or "").strip() or "someone"
    face = str(result.get("label") or "").strip() or "you"
    return f"{who} knows {face} and moves to stop you."


_DAY_WORDS = {
    1: "one day", 2: "two days", 3: "three days", 4: "four days", 5: "five days",
    6: "six days", 7: "seven days", 8: "eight days", 9: "nine days", 10: "ten days",
}


def _days(n: Any) -> str:
    # Words, for the `case` reason: a narrator handed "15" writes a tally.
    try:
        value = int(n)
    except (TypeError, ValueError):
        return "some days"
    return _DAY_WORDS.get(value, "many days" if value > 10 else "no time at all")


def _sum_pay_fine(result: dict[str, Any]) -> str:
    where = str(result.get("gaol") or "the cells")
    paid = _money(result.get("paid")) if result.get("paid") else ""
    head = f"paid the fine of {paid}" if paid else "was let go without a fine"
    return f"{head} and walked out of {where}, the charge closed."


def _sum_serve(result: dict[str, Any]) -> str:
    where = str(result.get("gaol") or "the cells")
    if result.get("served_out") is False:
        # Carried out mid-sentence (a death's respawn ends custody).
        return f"was carried out of {where} before the sentence ran out."
    return f"served {_days(result.get('days'))} in {where} and was let out, the charge closed."


_SUMMARISERS: dict[str, Any] = {
    "rest": _sum_rest,
    "eat": _sum_eat,
    "forage": _sum_forage,
    "work": _sum_work,
    "trade": _sum_buy,
    "trade_sell": _sum_sell,
    "move_to": _sum_move,
    "strike_bargain": _sum_thread("agreed"),
    "discharge_thread": _sum_thread("settled"),
    "scene_begin": _sum_scene_begin,
    "case_premise": _sum_case,
    "lift_purse": _sum_lift,
    "change_guise": _sum_change_guise,
    "law_recognition": _sum_recognition,
    "pay_fine": _sum_pay_fine,
    "serve_sentence": _sum_serve,
}

#: Keys whose value is a sentence written for a reader, in order of preference.
#: The fallback reads ONLY these; everything else on a result is bookkeeping.
_PROSE_KEYS = ("summary", "text", "outcome_text", "message")


def summarise_receipt(receipt: dict[str, Any]) -> str:
    """
    One plain sentence for one successful receipt. "" when there is nothing to say.

    A dice receipt keeps its CheckResult ``summary`` -- the line
    engine/game/checks.py writes for exactly this block.
    """
    skill = str(receipt.get("skill") or "")
    result = receipt.get("result") if isinstance(receipt.get("result"), dict) else {}
    if skill == "set_narrative_flag":
        return ""
    fn = _SUMMARISERS.get(skill)
    if fn is not None:
        return fn(result)
    for key in _PROSE_KEYS:
        text = str(result.get(key) or "").strip()
        if text:
            return text
    # No sentence written for it. Keep the short WORD facts -- a Phase A lookup
    # such as query_evil_state exists so the narrator reports "stirring"
    # instead of guessing -- and drop every number and every nested structure,
    # which is where the DCs, rolls and meter readings live.
    facts = [
        f"{key.replace('_', ' ')} {value}"
        for key, value in result.items()
        if isinstance(value, str)
        and value.strip()
        and len(value) <= 60
        and key not in ("error", "raw")
        and not key.endswith("_id")
    ]
    label = skill.replace("_", " ")
    return f"{label}: {', '.join(facts)}." if facts else f"{label}: done."


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

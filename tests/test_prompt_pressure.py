"""
What the engine simulates must reach the prose that narrates it.

THE GAP THESE CLOSE. Overhaul III fixed "built but unreachable". What survived
it is a quieter thing: systems that ARE reached, are mechanically live, and are
invisible to the narrator -- so the engine builds pressure the prose cannot
spend.

  * ``engine/game/threads.py`` is 1,220 lines and three shipped stories declare
    a ``threads.yaml``. A sealed contract gates choices, charges its terms and
    comes due on a named day. ``threads.summary`` has said since it was written
    that it is "trimmed for a prompt block or a UI list" -- only the UI half was
    built, so no narrator had ever been told a bargain existed.
  * ``engine/game/clocks.py`` is 844 lines. THE LONG CON's whole pitch is that
    ``the_frame`` fills and deals an authored interrogation; the narrator was
    never told the frame was filling, so it landed out of a clear sky.
  * ``story_pressure`` reached the prompt as one of three words. A story easing
    off after a crisis and a story winding toward one read identically.

WHAT THE FLAGSHIP PAYS. It declares neither threads nor clocks, so it gains
neither block -- asserted here rather than assumed, which is the bar
``tests/test_scene_director.py`` holds the scene director to. Its prompt is NOT
byte identical, and deliberately so: the direction clause rides on
``story_pressure``, which the existing GM line already calls "the engine's own
pacing meter" and keeps for every story, doom clock or not.

Version: v0.1.0 [2026-09-20]
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from engine.agents import prompts
from engine.config import set_overlay
from engine.game import clock as clock_module
from engine.game import clocks, threads
from engine.game.state import GameState
from engine.state import active as active_state
from engine.state.schema import load_schema

GARDEN_SCHEMA = Path("games/wicked-garden") / "state.yaml"


def _story_paths(slug: str) -> dict[str, str]:
    """That story's own ``paths:``, read from the manifest that ships them."""
    from engine.games.registry import discover

    manifest = discover()[slug]
    return {k: str(v) for k, v in (manifest.paths or {}).items()}


@pytest.fixture()
def garden() -> Iterator[GameState]:
    """The Wicked Garden's shipped rules, through the real loaders."""
    set_overlay({"paths": _story_paths("wicked-garden")})
    active_state._schema = load_schema(GARDEN_SCHEMA, slug="wicked-garden")
    state = GameState(rng_seed=42)
    try:
        yield state
    finally:
        active_state.reset_schema()
        set_overlay(None)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


def test_a_sealed_contract_reaches_the_narrator(garden: GameState) -> None:
    """The bargain the engine will enforce is the bargain the prose can name."""
    assert prompts.obligations_block(garden) == "", "nothing sealed yet"

    proposal = threads.offer(garden, "obligation_gift", source="sophia")
    assert proposal is not None
    threads.seal(garden, proposal)

    block = prompts.obligations_block(garden)
    assert block, "a sealed contract produced no prompt block"
    assert "CONTRACTS YOU ARE UNDER" in block
    assert "sophia" in block

    # The terms are the point. A block that said only "a bargain is open" would
    # let the narrator invent what was promised, which is the failure the
    # engine's whole intent loop exists to prevent.
    row = threads.summary(garden)[0]
    assert str(row["terms"]) in block


def test_the_contract_block_withholds_the_machinery(garden: GameState) -> None:
    """
    ``summary`` drops the effect hooks; the block must not put them back.

    A model handed the numbers narrates the numbers, which is the same reason
    the GM line says "never state these as numbers".
    """
    threads.seal(garden, threads.offer(garden, "obligation_gift", source="sophia"))
    block = prompts.obligations_block(garden)
    assert "effects" not in block
    assert "on_due" not in block


def test_a_story_with_no_threads_adds_no_block() -> None:
    """The flagship declares none, and pays nothing for the feature."""
    assert prompts.obligations_block(GameState(rng_seed=1)) == ""


# ---------------------------------------------------------------------------
# Clocks
# ---------------------------------------------------------------------------


def test_a_filling_clock_reaches_the_gm_line(garden: GameState) -> None:
    """Rising pressure the narrator can feel before it arrives."""
    assert prompts._clocks_block(garden) == "", "every clock is still at its floor"

    clocks.advance(garden, "briar_hunger", 3)
    block = prompts._clocks_block(garden)
    assert block, "an advanced clock produced no block"
    assert "never name these" in block


def test_the_clock_block_uses_the_label_nothing_else_reads(
    garden: GameState,
) -> None:
    """
    The GM-facing label in clocks.yaml, live at last.

    Every shipped clock table carries a ``label:`` -- "The roots are counting",
    "How this ends up being your fault" -- and no engine module had ever loaded
    one. They say what a clock MEANS, which is what a narrator needs and what
    the player-facing label in state.yaml deliberately does not say.
    """
    label = str((clocks.load_clocks().get("briar_hunger") or {}).get("label") or "")
    assert label, "the Garden's briar_hunger declares no label to test with"

    clocks.advance(garden, "briar_hunger", 3)
    assert label in prompts._clocks_block(garden)


def test_a_story_with_no_clocks_adds_no_block() -> None:
    assert prompts._clocks_block(GameState(rng_seed=1)) == ""


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------


def _tone(state: GameState) -> str:
    return prompts.world_state_block(state, {"story_pressure": state.story_pressure})


def test_pressure_reports_which_way_it_is_moving() -> None:
    """"restless" and "restless, and rising" are different scenes."""
    state = GameState(rng_seed=1)
    state.story_pressure = 40.0

    state.story_pressure_prev = 10.0
    assert "and rising" in _tone(state)

    state.story_pressure_prev = 70.0
    assert "and easing" in _tone(state)

    state.story_pressure_prev = 40.5
    text = _tone(state)
    assert "and rising" not in text and "and easing" not in text


def test_only_advance_time_writes_the_previous_reading() -> None:
    """
    One writer, for the reason the field's own note gives.

    ``update_story_pressure`` runs several times in a turn. If each call moved
    the previous reading, it would compare a turn against itself and report
    every story as steady -- the bug this guards is a feature that silently
    does nothing, which is the shape this repo keeps finding.
    """
    from engine.game.plot import PlotFormula

    state = GameState(rng_seed=1)
    state.story_pressure = 30.0
    state.story_pressure_prev = 5.0

    PlotFormula.update_story_pressure(state)
    assert state.story_pressure_prev == 5.0, "recompute moved the previous reading"

    clock_module.advance_time(state, 1.0)
    assert state.story_pressure_prev != 5.0, "advance_time did not capture it"


def test_a_save_without_the_field_loads_at_neutral_zero() -> None:
    """A state that predates the field and a fresh one must agree."""
    assert GameState(rng_seed=1).story_pressure_prev == 0.0


# ---------------------------------------------------------------------------
# The companion's face
# ---------------------------------------------------------------------------


def test_a_story_character_gets_her_own_portrait(garden: GameState) -> None:
    """
    Sophia has a painted portrait that had never once been shown.

    `assistant_presence` resolves `portrait` from `form` -- the Assistant
    MIND's current face, one of The Clockwork Dark's five, defaulting to "cat".
    The Wicked Garden's art manifest keys her portrait on `sophia`, so the
    lookup asked for a cat, got "", and the companion column fell back to its
    wash. `games/wicked-garden/data/art/plates/portraits/sophia.jpg` has been
    on disk the whole time.

    This is the same disease `Companion.jsx` already documents for the `form`
    CAPTION -- "the flagship's state leaking through a slot this story shares
    with it". The caption was fixed; nobody noticed the portrait had it too.
    """
    from engine.scenes.default_state import portrait_url

    assert portrait_url("sophia").endswith("portraits/sophia.jpg")
    # The flagship's vocabulary finds nothing here, which is the bug's whole
    # mechanism and why it was invisible: an empty string is a legal answer.
    assert portrait_url("cat") == ""


# ---------------------------------------------------------------------------
# A choice the player can read
# ---------------------------------------------------------------------------


def test_a_choice_that_echoes_its_own_intent_id_is_relabelled() -> None:
    """
    The button says what the AUTHOR wrote, not what the enum is called.

    Measured in a live Wicked Garden turn on a 3B model: the choices rendered
    as `follow_the_scent`, `name_it_aloud`, `turn_away_hard` -- the model had
    echoed the intent enum's target ids straight into the display text. The
    beats they came from carry authored prose ("Walk toward it without arguing.
    Curiosity as the first sin, and the cheapest one."), and the engine had it
    the whole time: `legal_intents` builds the enum from `(id, label)` pairs and
    the label IS the authored text.

    So this is not a model problem to be prompted around. The engine holds
    better text than the model produced and was showing the model's -- the same
    "engine resolves, LLM narrates" split the whole intent loop is built on.

    Only when the text IS the id. A model that writes its own prose keeps it;
    nothing here second-guesses a real sentence.
    """
    from engine.games.registry import activate, deactivate
    from engine.scenes.default_state import _label_intents

    activate("clockwork-dark")
    try:
        state = GameState(rng_seed=1)
        state.location_id = "forest_clearing"

        echoed, authored = _label_intents(
            state,
            [
                {"text": "edgewood_square", "intent": {"action": "travel", "target": "edgewood_square"}},
                {"text": "Follow the smoke", "intent": {"action": "travel", "target": "edgewood_square"}},
            ],
        )

        assert echoed["text"] == "Edgewood Square, 1h", echoed
        # Untouched: a real sentence is the narrator's job and stays its work.
        assert authored["text"] == "Follow the smoke"
    finally:
        deactivate()


# ---------------------------------------------------------------------------
# The companion's voice rule
# ---------------------------------------------------------------------------


def test_the_companion_line_is_held_to_its_declared_cap() -> None:
    """
    The "1-3 sentences" rule was carried by prose alone, and did not hold.

    `ASSISTANT_TURN_SCHEMA` was written to enforce it -- its `maxLength: 240`
    comment says the cap "enforces the '1-3 sentences' voice rule that prose
    alone never reliably holds" -- and nothing ever passed it to a model. It
    turned up in the v0.5.0 audit as an unreferenced constant.

    IT CANNOT BE WIRED AS WRITTEN, which is the finding. A `response_format`
    forces the OpenAI-compatible transport (`backend.use_native` returns False
    the moment one is set), and the companion is deliberately on the native
    route: "156 of this call's 200 tokens went to REASONING and the reply was
    cut off mid-sentence" is measured, in a comment, at that call site. Wiring
    the schema would buy the cap and pay for it with the starvation somebody
    already fixed.

    So the RULE is enforced where it costs nothing -- after the line comes
    back, at a sentence boundary, which is what a maxLength could never do: a
    JSON string truncated at 240 stops mid-word.
    """
    from engine.agents.assistant import enforce_voice_rule

    short = "She watches the door. She says nothing."
    assert enforce_voice_rule(short) == short

    long = ("The lantern gutters and she counts the steps again. " * 12).strip()
    held = enforce_voice_rule(long)
    assert len(held) <= 240
    # A whole sentence, not a severed one.
    assert held.endswith(".")
    assert "counts the steps again." in held


def test_a_capless_line_with_no_sentence_end_is_still_cut() -> None:
    """
    A run-on with no full stop still has to stop somewhere.

    Falling through and returning the whole thing would make the cap advisory,
    which is the state this fixes.
    """
    from engine.agents.assistant import enforce_voice_rule

    held = enforce_voice_rule("and on and on " * 40)
    assert len(held) <= 240

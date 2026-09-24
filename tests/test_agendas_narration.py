"""
Agendas, part four: the narrator and the player see only what they could know.

WHAT REACHES THE PROSE, AND HOW:

* A PRIVATE trace waits where it was left. ``agenda_block`` ("SIGNS HERE")
  shows the unseen ones at the player's location. Prompt assembly marks what
  it rendered, and the turn records them seen through ``agenda_trace_seen``
  once the narrator has written. This is the moved journal's two-step
  lifecycle, so an evaluator retry sees the same signs.
* A PUBLIC trace is common talk. ``agenda_trace`` journalled it unlocated, and
  it never appears again as a sign.
* PROGRESS reaches the narrator only through ``_clocks_block``: the clock's
  label and band, inside the GM-only spoiler region. Never the goal.
* THE SECRET IS THE LINK, NOT THE NAME. Until a role's ``unmask_when`` holds,
  no agenda-authored text (sign or journalled public trace) names the chosen
  NPC. Their display name, and the aliases the role declares for them, reads
  as ``mask.instead``. The other candidates are never touched, and the cast
  block, storyteller prompt and narration are never touched either. Once
  ``unmask_when`` holds, the GM line gains one sentence saying who the role
  is, and agenda text names them normally.
* A story without ``paths.agendas`` is byte-identical.

Version: v0.1.0 [2026-09-25]
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from engine.agents import prompts
from engine.game import moved
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.clock import set_clock
from engine.game.state import GameState
from engine.lore.interceptors import SPOILER_CLOSE, SPOILER_OPEN
from engine.world import agendas

from test_agendas import CANDIDATES
from test_agendas_moves import (
    MARKET, NO_AGENDAS, SQUARE, _fails, _run, _world, no_agendas_story, story,
)

NAMES = {"npc_wren": "Wren", "npc_silas": "Silas Crook", "npc_imelda": "Lady Imelda"}
GOAL = "steal every shining thing in the city"
HEADER = "SIGNS HERE (the world moved without you; work in what fits, never explain it):"

MASK = {"instead": "the Magpie", "unmask_when": {"flag": "magpie_unmasked"},
        "aliases": {"npc_wren": ["the lamplighter"], "npc_silas": ["the Dapper"],
                    "npc_imelda": ["Vessaline"]}}

CHALK = {"id": "chalk", "every_hours": 1,
         "trace": {"text": "fresh chalk marks by the well", "where": SQUARE}}
CRY = {"id": "cry", "every_hours": 1,
       "trace": {"text": "the crier calls the hour", "where": SQUARE, "public": True}}
TELLS = {"id": "tells", "every_hours": 1, "select": {"witness": {"knows": "magpie"}},
         "trace": {"text": "{target_name} swears the thief wore a porter's smock",
                   "where": "target"}}
SHOUTS = {**TELLS, "id": "shouts",
          "trace": {**TELLS["trace"], "public": True}}


def _spec(*moves: dict[str, Any], mask: Any = MASK) -> dict[str, Any]:
    role: dict[str, Any] = {"from": list(CANDIDATES)}
    if mask is not None:
        role["mask"] = copy.deepcopy(mask)
    return {"roles": {"magpie": role},
            "agendas": {"the_magpie": {"owner": {"role": "magpie"}, "goal": GOAL,
                                       "clock": "magpie_spree",
                                       "moves": [copy.deepcopy(m) for m in moves]}}}


def _chosen(state: GameState) -> str:
    return agendas.role(state, "magpie")


def _others(state: GameState) -> list[str]:
    return [c for c in CANDIDATES if c != _chosen(state)]


def _sighting(state: GameState, npc: str) -> None:
    row = apply_effect(state, {"type": "witness", "deed": "fencing", "guise": "self",
                               "npc": npc, "where": SQUARE})
    assert row["ok"], row


# ---------------------------------------------------------------------------
# Signs where they were left
# ---------------------------------------------------------------------------


def test_a_sign_appears_only_at_its_location_and_only_until_shown(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CHALK)):
        state = _world()
        state.location_id = MARKET
        _run(state, 1)
        assert len(state.agendas["traces"]) == 1
        assert prompts.agenda_block(state) == ""  # it was left in the square

        state.location_id = SQUARE
        block = prompts.agenda_block(state)
        assert block == f"{HEADER}\n- fresh chalk marks by the well"
        assert block in prompts.world_state_block(state, {})

        # Marked when the prompt is built, not drained: a retry sees it again.
        agendas.mark_shown(state)
        assert prompts.agenda_block(state) == block
        assert state.agendas["traces"][0]["seen"] is False
        agendas.clear_shown(state)
        assert state.agendas["traces"][0]["seen"] is True
        assert prompts.agenda_block(state) == ""
        assert HEADER not in prompts.world_state_block(state, {})


def test_a_sign_left_after_the_prompt_waits_for_the_next_one(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CHALK)):
        state = _world()
        _run(state, 1)
        agendas.mark_shown(state)
        _run(state, 1)  # a second sign, after the prompt was built
        agendas.clear_shown(state)
        assert [t["seen"] for t in state.agendas["traces"]] == [True, False]
        assert prompts.agenda_block(state).count("\n- ") == 1


def test_seen_goes_through_the_effect(tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.game.effects as effects_module

    with story(tmp_path, _spec(CHALK)):
        state = _world()
        _run(state, 1)
        applied: list[dict[str, Any]] = []
        real = effects_module.apply_effect

        def spy(st: GameState, effect: dict[str, Any], *a: Any, **k: Any) -> Any:
            applied.append(effect)
            return real(st, effect, *a, **k)

        monkeypatch.setattr(effects_module, "apply_effect", spy)
        agendas.mark_shown(state)
        agendas.clear_shown(state)
        assert applied == [{"type": "agenda_trace_seen", "ids": ["t1"]}]


def test_agenda_trace_seen_refuses_what_it_cannot_record(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CHALK)):
        state = _world()
        _run(state, 1)
        for bad in ({}, {"ids": "t1"}, {"ids": []}, {"ids": ["t9"]}, {"ids": [1]}):
            receipt = apply_effect(state, {"type": "agenda_trace_seen", **bad})
            assert receipt["ok"] is False and receipt["message"], bad
        assert state.agendas["traces"][0]["seen"] is False
        ok = apply_effect(state, {"type": "agenda_trace_seen", "ids": ["t1"]})
        assert ok["ok"] and ok["hidden"] and ok["text"] == ""
    assert apply_effect(GameState(), {"type": "agenda_trace_seen", "ids": ["t1"]})["ok"] is False


def test_agenda_trace_seen_is_not_authorable(tmp_path: Path) -> None:
    move = {**CHALK, "effects": [{"type": "agenda_trace_seen", "ids": ["t1"]}]}
    _fails(tmp_path, _spec(move), "agenda_trace_seen")


def test_a_public_trace_is_journalled_unlocated_and_is_never_a_sign(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CRY)):
        state = _world()
        _run(state, 1)
        state.location_id = MARKET
        assert "- the crier calls the hour" in prompts.moved_block(state)
        state.location_id = SQUARE
        assert prompts.agenda_block(state) == ""
        assert "- the crier calls the hour" in prompts.moved_block(state)


def test_the_wiring_marks_at_prompt_build_and_clears_after_the_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The flagship turn calls both halves, in order; each is a no-op there."""
    from engine.persistence import reset_save_store
    from engine.persistence.saves import SaveStore
    from engine.scenes.default_state import SessionStore, run_turn

    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    calls: list[str] = []
    real_mark, real_clear = agendas.mark_shown, agendas.clear_shown
    monkeypatch.setattr(agendas, "mark_shown",
                        lambda st: (calls.append("mark"), real_mark(st))[1])
    monkeypatch.setattr(agendas, "clear_shown",
                        lambda st: (calls.append("clear"), real_clear(st))[1])

    def llm(_messages: Any) -> str:
        return json.dumps({"narration": "The square keeps its own counsel tonight.",
                           "choices": [{"id": "a", "text": "Wait"},
                                       {"id": "b", "text": "Go"}]})

    try:
        session = SessionStore().create(seed=42, llm_fn=llm)
        run_turn(session, "The player chooses: Wait")
    finally:
        reset_save_store()
    assert calls and calls[0] == "mark" and calls[-1] == "clear", calls


# ---------------------------------------------------------------------------
# Progress: label and band, never the goal
# ---------------------------------------------------------------------------


def test_the_clocks_block_shows_label_and_band_and_never_the_goal(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CHALK)):
        state = _world()
        apply_effect(state, {"type": "value", "name": "magpie_spree", "delta": 3})
        block = prompts._clocks_block(state)
        assert "How close the Magpie is to the heart of the city" in block
        band = block.split("heart of the city: ")[1].splitlines()[0]
        assert band and not any(ch.isdigit() for ch in band)
        world = prompts.world_state_block(state, {})
        assert GOAL not in world and "the_magpie" not in world and "magpie_spree" not in world
        # GM-only: inside the spoiler region.
        gm = world.split(SPOILER_OPEN, 1)[1].split(SPOILER_CLOSE, 1)[0]
        assert "How close the Magpie is" in gm


# ---------------------------------------------------------------------------
# The link between the role and its NPC
# ---------------------------------------------------------------------------


def test_a_sign_naming_the_chosen_npc_reaches_the_narrator_masked(tmp_path: Path) -> None:
    with story(tmp_path, _spec(TELLS)):
        state = _world()
        chosen = _chosen(state)
        _sighting(state, chosen)
        _run(state, 1)
        [trace] = state.agendas["traces"]
        assert NAMES[chosen] in trace["text"]  # state keeps the truth
        block = prompts.agenda_block(state)
        assert block == f"{HEADER}\n- The Magpie swears the thief wore a porter's smock"
        world = prompts.world_state_block(state, {})
        assert f"{NAMES[chosen]} swears" not in world
        assert "WHO THE MAGPIE IS" not in world


def test_a_public_trace_naming_the_chosen_npc_is_journalled_masked(tmp_path: Path) -> None:
    with story(tmp_path, _spec(SHOUTS)):
        state = _world()
        chosen = _chosen(state)
        _sighting(state, chosen)
        _run(state, 1)
        block = prompts.moved_block(state)
        assert "- The Magpie swears the thief wore a porter's smock" in block
        assert NAMES[chosen] not in block


@pytest.mark.parametrize("which", [0, 1])
def test_the_other_candidates_are_never_masked(tmp_path: Path, which: int) -> None:
    with story(tmp_path, _spec(TELLS)):
        state = _world()
        other = _others(state)[which]
        _sighting(state, other)
        _run(state, 1)
        assert prompts.agenda_block(state) == (
            f"{HEADER}\n- {NAMES[other]} swears the thief wore a porter's smock")


def test_aliases_mask_only_the_chosen_npcs_own(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CHALK)):
        state = _world()
        chosen = _chosen(state)
        text = " / ".join(f"{NAMES[c]} ({MASK['aliases'][c][0]})" for c in CANDIDATES)
        masked = agendas.mask_text(state, text)
        for c in CANDIDATES:
            if c == chosen:
                assert NAMES[c] not in masked and MASK["aliases"][c][0] not in masked
            else:
                assert f"{NAMES[c]} ({MASK['aliases'][c][0]})" in masked
        assert "Magpie (the Magpie)" in masked


def test_masking_is_word_bounded_and_case_aware(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CHALK)):
        state = _world()
        name = NAMES[_chosen(state)]
        first = name.split()[-1]
        # A longer word containing the name, and the name in lower case, pass.
        assert agendas.mask_text(state, f"{first}ful {name.lower()}") == \
            f"{first}ful {name.lower()}"
        assert agendas.mask_text(state, f"{name}'s window") == "The Magpie's window"


def test_an_alias_at_the_start_of_a_sentence_is_masked(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CHALK)):
        state = _world()
        alias = MASK["aliases"][_chosen(state)][0]
        cap = alias[0].upper() + alias[1:]
        assert agendas.mask_text(state, f"{cap} was seen at the well.") == \
            "The Magpie was seen at the well."
        assert agendas.mask_text(state, f"Dusk fell. {cap} was seen.") == \
            "Dusk fell. The Magpie was seen."


def test_an_article_before_the_name_is_swallowed_in_either_case(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CHALK)):
        state = _world()
        name = NAMES[_chosen(state)]
        assert agendas.mask_text(state, f"The {name} was here.") == "The Magpie was here."
        assert agendas.mask_text(state, f"they saw the {name} go") == "they saw the Magpie go"
        assert agendas.mask_text(state, f"a note from {name}!") == "a note from the Magpie!"


def test_the_masked_phrase_is_capitalised_only_at_a_sentence_start(tmp_path: Path) -> None:
    with story(tmp_path, _spec(CHALK)):
        state = _world()
        name = NAMES[_chosen(state)]
        assert agendas.mask_text(state, f"{name} swears it. Ask {name}? {name} left.") == \
            "The Magpie swears it. Ask the Magpie? The Magpie left."


def test_the_bird_in_lower_case_prose_is_untouched(tmp_path: Path) -> None:
    doc = _spec(CHALK)
    doc["roles"]["magpie"]["from"] = ["npc_wren"]  # the seed can only choose Wren
    doc["roles"]["magpie"]["mask"]["aliases"] = {"npc_wren": ["the lamplighter"]}
    with story(tmp_path, doc):
        state = _world()
        assert _chosen(state) == "npc_wren"
        text = "a wren on the sill; the wren flew. Wren did not."
        assert agendas.mask_text(state, text) == \
            "a wren on the sill; the wren flew. The Magpie did not."
        # An alias that carries its own article needs it: a bare noun is not them.
        assert agendas.mask_text(state, "a lamplighter passed") == "a lamplighter passed"


def test_the_cast_block_and_storyteller_prompt_are_untouched(tmp_path: Path) -> None:
    with story(tmp_path, _spec(TELLS)):
        state = _world()
        masked = prompts._npcs_present_block(state)
        persona = prompts.storyteller_persona()
        state.flags["magpie_unmasked"] = True
        assert prompts._npcs_present_block(state) == masked
        assert prompts.storyteller_persona() == persona
        assert "the Magpie" not in masked


def test_once_earned_the_gm_line_says_who_and_signs_name_them(tmp_path: Path) -> None:
    with story(tmp_path, _spec(TELLS)):
        state = _world()
        chosen = _chosen(state)
        _sighting(state, chosen)
        _run(state, 1)
        before = prompts.world_state_block(state, {})
        assert "WHO THE MAGPIE IS" not in before
        assert f"{NAMES[chosen]} swears" not in before

        state.flags["magpie_unmasked"] = True
        after = prompts.world_state_block(state, {})
        assert f"- {NAMES[chosen]} swears the thief wore a porter's smock" in after
        gm = after.split(SPOILER_OPEN, 1)[1].split(SPOILER_CLOSE, 1)[0]
        role_word = {"npc_wren": "lamplighter", "npc_silas": "upstart",
                     "npc_imelda": "noble"}[chosen]
        assert (f"WHO THE MAGPIE IS (the player has earned this; name them freely): "
                f"{NAMES[chosen]}, the {role_word}.") in gm
        assert after.count("WHO THE MAGPIE IS") == 1
        # Unmasking is read every time, never cached: close it again and it hides.
        state.flags["magpie_unmasked"] = False
        assert prompts.world_state_block(state, {}) == before


def test_a_role_without_a_mask_is_neither_masked_nor_revealed(tmp_path: Path) -> None:
    with story(tmp_path, _spec(TELLS, mask=None)):
        state = _world()
        chosen = _chosen(state)
        _sighting(state, chosen)
        _run(state, 1)
        world = prompts.world_state_block(state, {})
        assert f"- {NAMES[chosen]} swears" in world and "WHO THE" not in world


# ---------------------------------------------------------------------------
# Loader rulings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mask", [
    {"instead": "the Magpie"},
    {"instead": "the Magpie", "unmask_when": None},
    {"instead": "the Magpie", "unmask_when": {}},
])
def test_a_mask_that_can_never_lift_fails(tmp_path: Path, mask: dict) -> None:
    _fails(tmp_path, _spec(CHALK, mask=mask), "unmask_when")


@pytest.mark.parametrize("aliases, needle", [
    (["Wren"], "aliases"),
    ({"npc_ardane": ["the captain"]}, "npc_ardane"),
    ({"npc_wren": "the lamplighter"}, "aliases"),
    ({"npc_wren": ["", "x"]}, "aliases"),
    ({"npc_wren": [3]}, "aliases"),
])
def test_malformed_aliases_fail(tmp_path: Path, aliases: Any, needle: str) -> None:
    _fails(tmp_path, _spec(CHALK, mask={**MASK, "aliases": aliases}), needle)


def test_aliases_are_optional(tmp_path: Path) -> None:
    mask = {k: v for k, v in MASK.items() if k != "aliases"}
    with story(tmp_path, _spec(CHALK, mask=mask)):
        assert agendas.spec()["roles"]["magpie"]["mask"]["aliases"] == {}


# ---------------------------------------------------------------------------
# A story without agendas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", NO_AGENDAS)
def test_a_story_without_agendas_builds_the_same_prompt(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with no_agendas_story(kind, tmp_path):
        state = GameState(rng_seed=42, location_id=SQUARE)
        state.procgen = generate_world(42)
        set_clock(state, day=1, hour=20)
        moved.note(state, "rumor", "the mill wheel stopped at noon")
        before = (prompts.world_state_block(state, {}), prompts.moved_block(state))
        saved = state.to_save_dict()

        def boom(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("an agenda visibility hook ran without agendas")

        for name in ("spec", "role", "masked_terms", "signs_here", "revealed"):
            monkeypatch.setattr(agendas, name, boom)
        assert prompts.agenda_block(state) == ""
        agendas.mark_shown(state)
        after = (prompts.world_state_block(state, {}), prompts.moved_block(state))
        agendas.clear_shown(state)
        assert after == before
        assert state.to_save_dict() == saved
        assert not hasattr(state, agendas.SHOWN_ATTR)

"""
Challenge tests.

The load-bearing property is not "a gauntlet resolves". It is that a model
cannot use a challenge to hand itself anything the designer did not authorise:
the spec layer bounds every number before the runner ever sees it.
"""

from __future__ import annotations

import random

import pytest

from engine.challenges import runner, set_pieces
from engine.challenges import spec as spec_module
from engine.game.state import GameState
from engine.world import world_effects


@pytest.fixture(autouse=True)
def _clean_caches():
    set_pieces.reset_set_piece_cache()
    world_effects.reset_doom_effects_cache()
    yield
    set_pieces.reset_set_piece_cache()
    world_effects.reset_doom_effects_cache()


@pytest.fixture
def state() -> GameState:
    return GameState(rng_seed=99)


class _HighRoller(random.Random):
    """
    Always rolls 19 on a d20 — clears every band up to severe.

    A seeded ``random.Random`` would make these tests depend on which face a
    particular CPython seed happens to produce, which is luck dressed up as
    determinism. 19 rather than 20 so a natural crit does not drag the boon
    table into a test that is not about boons.
    """

    def randint(self, a: int, b: int) -> int:  # noqa: D102
        return max(a, b - 1)


class _LowRoller(random.Random):
    """Always rolls 2 — fails every band, without the fumble path."""

    def randint(self, a: int, b: int) -> int:  # noqa: D102
        return min(b, a + 1)


def _gauntlet(**overrides) -> dict:
    base = {
        "id": "test_gauntlet",
        "kind": "skill_gauntlet",
        "title": "A Test",
        "steps": [{"skill": "nerve", "difficulty": "trivial", "text": "Step one."}],
        "reward": {"text": "Done.", "effects": [{"type": "gold", "delta": 5}]},
        "fail": {"text": "Nope.", "effects": []},
    }
    base.update(overrides)
    return base


# ===========================================================================
# Bounds — the reason this system is safe to let a model drive
# ===========================================================================


def test_a_hallucinated_reward_is_clamped_not_honoured(state):
    """The headline property: no 900-gold challenge."""
    result = spec_module.validate(
        _gauntlet(reward={"effects": [{"type": "gold", "delta": 900}]})
    )
    assert result.ok
    granted = result.spec["reward"]["effects"][0]["delta"]
    assert granted == spec_module.EFFECT_CEILINGS["gold"] == 25
    assert result.adjustments


def test_a_clamped_reward_actually_pays_out_the_clamped_amount(state):
    """End to end: the ceiling has to survive into the player's purse."""
    before = state.stats.gold
    runner.start(
        state, _gauntlet(reward={"effects": [{"type": "gold", "delta": 900}]})
    )
    runner.resolve(state, rng=_HighRoller())
    assert state.stats.gold - before <= spec_module.EFFECT_CEILINGS["gold"]


def test_effect_count_is_capped(state):
    result = spec_module.validate(
        _gauntlet(
            reward={"effects": [{"type": "gold", "delta": 1}] * 20}
        )
    )
    assert len(result.spec["reward"]["effects"]) == spec_module.MAX_EFFECTS


def test_disallowed_effect_types_are_dropped(state):
    """A challenge must not be able to write itself into memory as fact."""
    result = spec_module.validate(
        _gauntlet(
            reward={
                "effects": [
                    {"type": "ledger_fact", "text": "You are the chosen one."},
                    {"type": "gold", "delta": 1},
                ]
            }
        )
    )
    kinds = [e["type"] for e in result.spec["reward"]["effects"]]
    assert kinds == ["gold"]


def test_item_quantity_is_capped(state):
    result = spec_module.validate(
        _gauntlet(reward={"effects": [{"type": "item", "item_id": "gem", "qty": 99}]})
    )
    assert result.spec["reward"]["effects"][0]["qty"] == spec_module.MAX_ITEM_QTY


def test_difficulty_is_a_band_so_there_is_no_dc_to_inflate(state):
    """
    A raw DC is not part of the schema at all.

    Upstream took an integer ``dc`` straight from the model. Bands route
    through data/rules/skills.yaml, so difficulty stays reviewable.
    """
    result = spec_module.validate(
        _gauntlet(steps=[{"skill": "nerve", "dc": 999, "difficulty": "hard"}])
    )
    step = result.spec["steps"][0]
    assert "dc" not in step
    assert step["difficulty"] == "hard"


def test_an_unknown_difficulty_falls_back_to_standard(state):
    result = spec_module.validate(
        _gauntlet(steps=[{"skill": "nerve", "difficulty": "impossible"}])
    )
    assert result.spec["steps"][0]["difficulty"] == "standard"


def test_a_non_canon_skill_is_retargeted(state):
    result = spec_module.validate(
        _gauntlet(steps=[{"skill": "swordfighting", "difficulty": "easy"}])
    )
    assert result.spec["steps"][0]["skill"] in spec_module.SKILLS


def test_step_count_is_capped(state):
    result = spec_module.validate(
        _gauntlet(steps=[{"skill": "nerve", "difficulty": "easy"}] * 50)
    )
    assert len(result.spec["steps"]) == spec_module.MAX_STEPS


def test_text_is_truncated_so_a_spec_cannot_bloat_the_save(state):
    result = spec_module.validate(
        _gauntlet(steps=[{"skill": "nerve", "difficulty": "easy", "text": "x" * 5000}])
    )
    assert len(result.spec["steps"][0]["text"]) <= spec_module.MAX_TEXT


def test_structurally_unusable_specs_are_refused():
    for bad in (
        {"kind": "skill_gauntlet"},
        {"kind": "nonsense"},
        {"kind": "puzzle"},
        {"kind": "dice_table", "outcomes": []},
        {"kind": "decision_tree", "nodes": {}, "start": "start"},
        "not a mapping",
    ):
        assert not spec_module.validate(bad).ok, bad


# ===========================================================================
# Resolution
# ===========================================================================


def test_a_gauntlet_runs_step_by_step_and_pays_out(state):
    spec = _gauntlet(
        steps=[
            {"skill": "nerve", "difficulty": "trivial", "text": "One."},
            {"skill": "craft", "difficulty": "trivial", "text": "Two."},
        ]
    )
    first = runner.start(state, spec)
    assert first.status == runner.STATUS_ACTIVE
    assert first.total_steps == 2
    assert state.challenge

    second = runner.resolve(state, rng=_HighRoller())
    assert second.status == runner.STATUS_ACTIVE
    assert second.step == 1

    final = runner.resolve(state, rng=_HighRoller())
    assert final.ended and final.success
    assert state.challenge == {}, "a finished challenge must clear off the state"


def test_a_failed_step_ends_the_gauntlet(state):
    spec = _gauntlet(
        steps=[{"skill": "nerve", "difficulty": "legendary", "text": "Hopeless."}] * 2
    )
    runner.start(state, spec)
    result = runner.resolve(state, rng=_LowRoller())
    assert result.ended and not result.success
    assert state.challenge == {}


def test_a_gauntlet_check_is_a_real_engine_check(state):
    """
    Routed through checks.resolve, not a private d20 formula.

    That is what makes wounds, hunger and archetype modifiers apply inside a
    challenge the same as everywhere else.
    """
    runner.start(state, _gauntlet())
    result = runner.resolve(state, rng=_HighRoller())
    assert result.check is not None
    assert "modifiers" in result.check
    assert result.check["skill"] == "nerve"


def test_a_puzzle_accepts_a_sloppy_answer(state):
    spec = {
        "kind": "puzzle",
        "id": "p",
        "title": "P",
        "prompt": "What?",
        "answer": "Time",
        "attempts": 2,
        "reward": {"effects": [{"type": "flag", "flag": "solved"}]},
    }
    runner.start(state, spec)
    result = runner.resolve(state, answer="  TIME! ")
    assert result.success
    assert state.flags["solved"] is True


def test_a_puzzle_runs_out_of_attempts(state):
    spec = {
        "kind": "puzzle",
        "id": "p",
        "answer": "time",
        "attempts": 2,
        "fail": {"effects": []},
    }
    runner.start(state, spec)
    assert runner.resolve(state, answer="wrong").status == runner.STATUS_ACTIVE
    final = runner.resolve(state, answer="wrong")
    assert final.ended and not final.success


def test_a_decision_tree_walks_to_a_terminal_node(state):
    spec = {
        "kind": "decision_tree",
        "id": "t",
        "start": "start",
        "nodes": {
            "start": {
                "text": "A fork.",
                "options": [
                    {"id": "left", "text": "Left", "goto": "win"},
                    {"id": "right", "text": "Right", "goto": "lose"},
                ],
            },
            "win": {"terminal": True, "outcome": "success", "text": "Out.",
                    "reward": {"effects": [{"type": "gold", "delta": 3}]}},
            "lose": {"terminal": True, "outcome": "failure", "text": "Lost."},
        },
    }
    gold = state.stats.gold
    runner.start(state, spec)
    result = runner.resolve(state, choice="left")
    assert result.success
    assert state.stats.gold == gold + 3


def test_an_unknown_choice_re_presents_rather_than_punishes(state):
    spec = {
        "kind": "decision_tree",
        "id": "t",
        "start": "start",
        "nodes": {
            "start": {"text": "A fork.", "options": [{"id": "left", "goto": "win"}]},
            "win": {"terminal": True, "outcome": "success"},
        },
    }
    runner.start(state, spec)
    result = runner.resolve(state, choice="sideways")
    assert result.status == runner.STATUS_ACTIVE
    assert state.challenge


def test_a_dead_end_node_is_repaired_into_a_terminal(state):
    """A node you can enter and never leave is the location-graph bug again."""
    spec = {
        "kind": "decision_tree",
        "id": "t",
        "start": "start",
        "nodes": {
            "start": {"options": [{"id": "a", "goto": "trap"}]},
            "trap": {"text": "Nowhere.", "options": [{"id": "x", "goto": "missing"}]},
        },
    }
    result = spec_module.validate(spec)
    assert result.ok
    assert result.spec["nodes"]["trap"]["terminal"] is True


def test_a_dice_table_always_lands_on_an_outcome(state):
    spec = {
        "kind": "dice_table",
        "id": "d",
        "die": 6,
        "outcomes": [
            {"min": 1, "max": 3, "text": "Low.", "effects": []},
            {"min": 4, "max": 6, "text": "High.", "effects": []},
        ],
    }
    for seed in range(12):
        fresh = GameState(rng_seed=seed)
        runner.start(fresh, spec)
        result = runner.resolve(fresh, rng=random.Random(seed))
        assert result.ended
        assert result.text in ("Low.", "High.")


# ===========================================================================
# Lifecycle and persistence
# ===========================================================================


def test_a_second_challenge_cannot_stomp_a_running_one(state):
    runner.start(state, _gauntlet())
    blocked = runner.start(state, _gauntlet(id="other"))
    assert blocked.status == runner.STATUS_ERROR
    assert state.challenge["id"] == "test_gauntlet"

    replaced = runner.start(state, _gauntlet(id="other"), replace=True)
    assert replaced.status == runner.STATUS_ACTIVE


def test_resolving_with_nothing_running_is_an_error_not_a_crash(state):
    assert runner.resolve(state).status == runner.STATUS_ERROR


def test_a_challenge_survives_a_save_reload(state):
    spec = _gauntlet(
        steps=[
            {"skill": "nerve", "difficulty": "trivial", "text": "One."},
            {"skill": "craft", "difficulty": "trivial", "text": "Two."},
        ]
    )
    runner.start(state, spec)
    runner.resolve(state, rng=_HighRoller())

    restored = GameState.from_dict(state.to_save_dict())
    assert restored.challenge["id"] == "test_gauntlet"
    assert restored.challenge["step"] == 1

    final = runner.resolve(restored, rng=_HighRoller())
    assert final.ended


def test_the_active_challenge_reaches_the_client(state):
    runner.start(state, _gauntlet())
    assert state.to_client_dict()["challenge"]["id"] == "test_gauntlet"


def test_abandoning_costs_nothing(state):
    gold = state.stats.gold
    runner.start(state, _gauntlet())
    result = runner.abandon(state)
    assert result.ended and not result.success
    assert state.stats.gold == gold
    assert state.challenge == {}


def test_the_same_seed_replays_a_gauntlet_identically():
    def play() -> list[int]:
        game = GameState(rng_seed=4242)
        runner.start(
            game,
            _gauntlet(
                steps=[{"skill": "nerve", "difficulty": "standard"}] * 3,
            ),
        )
        totals = []
        while game.challenge:
            result = runner.resolve(game)
            totals.append(result.check["total"])
        return totals

    assert play() == play()


# ===========================================================================
# Set-pieces — the doom-beat loop
# ===========================================================================


def test_the_shipped_set_pieces_all_validate():
    catalogue = set_pieces.load_set_pieces()
    assert catalogue
    for piece_id, piece in catalogue.items():
        result = spec_module.validate(piece.get("challenge"))
        assert result.ok, f"{piece_id}: {result.error}"


def test_a_set_piece_is_gated_shut_until_its_doom_beat_fires(state):
    state.location_id = "edgewood_square"
    assert "brass_scarecrow" not in [p["id"] for p in set_pieces.available(state)]

    state.evil_progress = 0.35
    world_effects.apply_pending_beats(state)

    assert "brass_scarecrow" in [p["id"] for p in set_pieces.available(state)]


def test_a_set_piece_is_gated_by_location(state):
    state.evil_progress = 0.35
    world_effects.apply_pending_beats(state)
    state.location_id = "millhaven_gate"
    assert "brass_scarecrow" not in [p["id"] for p in set_pieces.available(state)]


def test_starting_a_gated_set_piece_is_refused(state):
    assert set_pieces.start(state, "brass_scarecrow").status == runner.STATUS_ERROR
    assert set_pieces.start(state, "no_such_piece").status == runner.STATUS_ERROR


def test_the_full_loop_beat_to_flag_to_set_piece_to_terminal_flag(state):
    """doom beat -> flag -> set-piece -> terminal flag, all on one save."""
    state.location_id = "edgewood_square"
    state.evil_progress = 0.35
    world_effects.apply_pending_beats(state)
    assert state.flags["scarecrow_awake"] is True

    started = set_pieces.start(state, "brass_scarecrow")
    assert started.status == runner.STATUS_ACTIVE
    assert state.challenge[set_pieces.SET_PIECE_KEY] == "brass_scarecrow"

    # Walk it to completion. Trivial-forcing the rolls keeps the test about the
    # loop rather than about the dice.
    guard = 0
    result = None
    while state.challenge and guard < 20:
        guard += 1
        result = set_pieces.resolve(state, rng=_HighRoller())

    assert result is not None and result.ended and result.success
    assert state.flags["set_piece_brass_scarecrow_done"] is True
    assert "brass_scarecrow" not in [p["id"] for p in set_pieces.available(state)]


def test_the_set_piece_id_survives_a_reload_mid_run(state):
    state.location_id = "edgewood_square"
    state.evil_progress = 0.35
    world_effects.apply_pending_beats(state)
    set_pieces.start(state, "brass_scarecrow")

    restored = GameState.from_dict(state.to_save_dict())
    assert restored.challenge[set_pieces.SET_PIECE_KEY] == "brass_scarecrow"

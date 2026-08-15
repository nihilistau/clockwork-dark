"""
Skill check tests.

Covers the contract the narration prompt and the UI both depend on: the
modifier breakdown is complete (its deltas sum to what was actually added to
the die), every degree boundary lands where the table says, each situational
modifier fires on its own condition, and advantage really does skew high.
"""

from __future__ import annotations

import random

import pytest

from engine.game import checks
from engine.game.state import EvilPhase, GameState, TimedEffect, Wound


class FixedRNG:
    """RNG stub returning a scripted sequence of die faces."""

    def __init__(self, *faces: int) -> None:
        self._faces = list(faces)
        self._i = 0

    def randint(self, _low: int, _high: int) -> int:
        face = self._faces[self._i % len(self._faces)]
        self._i += 1
        return face


def neutral_state(**kwargs) -> GameState:
    """
    State with every check input at zero.

    `sympathy` is the probe skill throughout: focus defaults to 10 (mod 0) and
    no archetype grants it an affinity, so any modifier that shows up in the
    breakdown was put there by the thing under test.
    """
    state = GameState(rng_seed=1234, **kwargs)
    state.stats.stamina = 100
    state.stats.hp = state.stats.max_hp
    state.hunger = 0.0
    return state


# -- taxonomy and tables -------------------------------------------------


def test_all_seven_skills_present():
    skills = checks.load_skill_rules()["skills"]
    assert set(skills) == {
        "persuasion",
        "stealth",
        "sympathy",
        "lore",
        "craft",
        "survival",
        "nerve",
    }


@pytest.mark.parametrize(
    "skill,stat",
    [
        ("persuasion", "presence"),
        ("stealth", "agility"),
        ("sympathy", "focus"),
        ("lore", "wits"),
        ("craft", "craft"),
        ("survival", "wits"),
        ("nerve", "grit"),
    ],
)
def test_skill_stat_mapping(skill, stat):
    result = checks.resolve(neutral_state(), skill, "standard")
    assert result.stat == stat


@pytest.mark.parametrize(
    "band,dc",
    [
        ("trivial", 8),
        ("easy", 10),
        ("standard", 13),
        ("hard", 16),
        ("severe", 19),
        ("legendary", 22),
    ],
)
def test_difficulty_bands(band, dc):
    assert checks.difficulty_dc(band)[1] == dc


def test_unknown_difficulty_falls_back_to_standard():
    band, dc = checks.difficulty_dc("impossible-ish")
    assert (band, dc) == ("standard", 13)


def test_unknown_skill_resolves_rather_than_refusing():
    # Refusing would hand narration of an unrolled outcome back to the model.
    result = checks.resolve(neutral_state(), "haggling", "standard")
    assert result.stat == "wits"
    assert result.degree in ("crit_success", "success", "partial", "failure")


@pytest.mark.parametrize(
    "value,expected", [(3, -4), (8, -1), (10, 0), (11, 0), (12, 1), (14, 2), (18, 4)]
)
def test_stat_mod(value, expected):
    assert checks.stat_mod(value) == expected


# -- modifier breakdown --------------------------------------------------


def test_modifier_breakdown_sums_to_applied_modifier():
    state = neutral_state()
    state.stats.presence = 16
    state.stats.stamina = 10          # exhausted -3
    state.stats.hp = 4                # injured  -2 (4/20 = 0.2)
    state.hunger = 90.0               # starving -2
    state.wounds.append(
        Wound(id="w1", text="Turned ankle", check_penalty=-1, skills=["persuasion"])
    )
    state.active_effects.append(
        TimedEffect(
            id="e1",
            kind="check_penalty",
            text="badly shaken",
            delta=-2,
            expires_day=99,
        )
    )

    result = checks.resolve(state, "persuasion", "standard", extra_mod=1)

    assert sum(d for _, d in result.modifiers) == result.dice.modifier
    assert result.total == result.dice.rolls[0] + result.dice.modifier
    labels = [label for label, _ in result.modifiers]
    for expected in ("presence", "exhausted", "injured", "starving", "circumstance"):
        assert expected in labels
    assert result.to_dict()["modifier_total"] == result.dice.modifier


def test_extra_mod_is_itemised_never_hidden():
    state = neutral_state()
    result = checks.resolve(state, "sympathy", "standard", extra_mod=3)
    assert ("circumstance", 3) in result.modifiers


# -- situational modifiers, one at a time --------------------------------


def _delta_for(state: GameState, skill: str, label: str) -> int:
    return sum(d for lbl, d in checks.gather_modifiers(state, skill) if lbl == label)


def test_exhausted_modifier():
    state = neutral_state()
    assert _delta_for(state, "sympathy", "exhausted") == 0
    state.stats.stamina = 20
    assert _delta_for(state, "sympathy", "exhausted") == -3


def test_injured_modifier():
    state = neutral_state()
    assert _delta_for(state, "sympathy", "injured") == 0
    state.stats.hp = 8  # exactly 40% of 20
    assert _delta_for(state, "sympathy", "injured") == -2


def test_starving_modifier():
    state = neutral_state()
    state.hunger = 84.0
    assert _delta_for(state, "sympathy", "starving") == 0
    state.hunger = 85.0
    assert _delta_for(state, "sympathy", "starving") == -2


def test_night_helps_stealth_only():
    from engine.game.clock import set_clock

    state = neutral_state()
    set_clock(state, day=1, hour=12)
    assert _delta_for(state, "stealth", "darkness") == 0

    set_clock(state, day=1, hour=23)
    assert state.time_of_day == "night"
    assert _delta_for(state, "stealth", "darkness") == 2
    assert _delta_for(state, "sympathy", "darkness") == 0


def test_evil_phase_presses_on_nerve():
    state = neutral_state()
    assert _delta_for(state, "nerve", "the wrongness") == 0

    state.evil_phase = EvilPhase.SPREADING
    assert _delta_for(state, "nerve", "the wrongness") == -1
    assert _delta_for(state, "stealth", "the wrongness") == 0

    state.evil_phase = EvilPhase.CONSUMING
    assert _delta_for(state, "nerve", "the wrongness") == -3


def test_wound_penalty_applies_only_to_listed_skills():
    state = neutral_state()
    state.wounds.append(
        Wound(id="w1", text="Torn hands", check_penalty=-2, skills=["craft"])
    )
    assert _delta_for(state, "craft", "torn hands") == -2
    assert _delta_for(state, "sympathy", "torn hands") == 0


def test_wound_without_skill_filter_applies_everywhere():
    state = neutral_state()
    state.wounds.append(Wound(id="w1", text="Cracked rib", check_penalty=-1))
    assert _delta_for(state, "sympathy", "cracked rib") == -1
    assert _delta_for(state, "nerve", "cracked rib") == -1


def test_timed_check_penalty_contributes():
    state = neutral_state()
    state.active_effects.append(
        TimedEffect(
            id="e1",
            kind="check_penalty",
            text="the taste of brass",
            delta=-1,
            skills=["nerve"],
            expires_day=99,
        )
    )
    assert _delta_for(state, "nerve", "the taste of brass") == -1
    assert _delta_for(state, "craft", "the taste of brass") == 0


def test_non_check_timed_effects_are_ignored():
    state = neutral_state()
    state.active_effects.append(
        TimedEffect(id="e1", kind="buff_speed", text="quick", delta=5, expires_day=99)
    )
    assert sum(d for _, d in checks.gather_modifiers(state, "sympathy")) == 0


def test_archetype_affinity_is_small_and_itemised():
    state = neutral_state(archetype="hearthkeeper")
    assert _delta_for(state, "craft", "hearthkeeper") == 2
    assert _delta_for(state, "stealth", "hearthkeeper") == 0


# -- degrees -------------------------------------------------------------


@pytest.mark.parametrize(
    "face,degree",
    [
        # The crit boundary moved from margin +10 to +6. At +10 over a
        # `standard` DC of 13 the band needed a total of 23, and the best
        # shipped build tops out at 24 on a natural 20 -- so it was a 5% band
        # for one archetype and impossible for the rest. See
        # test_every_declared_degree_is_reachable_by_some_shipped_build.
        (14, "crit_success"),  # margin +6, exactly the boundary
        (13, "success"),       # margin +5
        (8, "success"),        # margin  0, exactly the boundary
        (7, "partial"),        # margin -1
        (4, "partial"),        # margin -4, exactly the boundary
        (3, "failure"),        # margin -5
    ],
)
def test_degree_boundaries(face, degree):
    # DC 8 (trivial) with a zero modifier makes margin == face - 8.
    result = checks.resolve(neutral_state(), "sympathy", "trivial", rng=FixedRNG(face))
    assert result.margin == face - 8
    assert result.degree == degree


def test_success_property_excludes_partial():
    partial = checks.resolve(neutral_state(), "sympathy", "trivial", rng=FixedRNG(7))
    full = checks.resolve(neutral_state(), "sympathy", "trivial", rng=FixedRNG(8))
    assert partial.success is False
    assert full.success is True


# -- advantage -----------------------------------------------------------


def test_advantage_skews_high_over_10k_rolls():
    n = 10000
    gen = random.Random(20260807)

    def mean(advantage: int) -> float:
        total = 0
        for _ in range(n):
            result = checks.resolve(
                neutral_state(), "sympathy", "standard", advantage=advantage, rng=gen
            )
            total += result.natural
        return total / n

    high = mean(1)
    flat = mean(0)
    low = mean(-1)

    # Expectations for keep-high/flat/keep-low of 1d20: 13.825 / 10.5 / 7.175.
    assert high == pytest.approx(13.825, abs=0.25)
    assert flat == pytest.approx(10.5, abs=0.25)
    assert low == pytest.approx(7.175, abs=0.25)
    assert low < flat < high


def test_advantage_keeps_the_better_die():
    result = checks.resolve(
        neutral_state(), "sympathy", "standard", advantage=1, rng=FixedRNG(3, 17)
    )
    assert sorted(result.all_rolls) == [3, 17]
    assert result.natural == 17


def test_disadvantage_keeps_the_worse_die():
    result = checks.resolve(
        neutral_state(), "sympathy", "standard", advantage=-1, rng=FixedRNG(3, 17)
    )
    assert result.natural == 3


def test_no_advantage_rolls_once():
    result = checks.resolve(neutral_state(), "sympathy", "standard", rng=FixedRNG(11, 2))
    assert result.all_rolls == [11]


# -- boons and complications --------------------------------------------


def test_natural_20_draws_a_boon_and_applies_its_effects():
    state = neutral_state()
    state.stats.stamina = 50
    before = state.to_save_dict()

    result = checks.resolve(state, "sympathy", "standard", rng=FixedRNG(20))

    assert result.dice.critical is True
    assert result.boon is not None and result.boon["id"]
    assert "Boon:" in result.summary
    # A boon must actually do something to the world, not just say so.
    assert state.to_save_dict() != before or result.effects_applied


def test_natural_1_draws_a_complication_and_applies_its_effects():
    state = neutral_state()
    state.stats.stamina = 60

    result = checks.resolve(state, "sympathy", "standard", rng=FixedRNG(1))

    assert result.dice.fumble is True
    assert result.complication is not None and result.complication["id"]
    assert "Complication:" in result.summary
    assert result.effects_applied


def test_table_filters_are_respected():
    boons = checks._load_table("boons.yaml", "boons")
    comps = checks._load_table("complications.yaml", "complications")
    assert len(boons) >= 16
    assert len(comps) >= 16
    # The original ids are load-bearing: saves and receipts cite them.
    assert {"clean_success", "lucky_find"} <= {b["id"] for b in boons}
    assert {"slip", "break_tool", "alert_npc"} <= {c["id"] for c in comps}
    for row in boons + comps:
        assert row.get("text")
        assert isinstance(row.get("effects", []), list)


def test_boon_draw_respects_applies_to():
    # forager_luck is survival-only; a sympathy crit must never draw it.
    for seed in range(30):
        state = neutral_state()
        state.rng_seed = seed
        result = checks.resolve(state, "sympathy", "standard", rng=FixedRNG(20))
        assert result.boon["id"] != "forager_luck"


# -- receipts ------------------------------------------------------------


def test_summary_shape_matches_the_narration_contract():
    state = neutral_state()
    state.stats.agility = 14   # +2
    state.stats.stamina = 10   # exhausted -3
    result = checks.resolve(state, "stealth", "standard", rng=FixedRNG(6))

    # "stealth (standard): d20 6, +2 agility, +1 wayfarer, -3 exhausted = 6 vs DC 13. FAILURE by 7."
    summary = result.summary
    assert summary.startswith("stealth (standard): d20 6")
    assert "+2 agility" in summary
    assert "-3 exhausted" in summary
    assert f"= {result.total} vs DC 13." in summary
    assert summary.endswith(f"FAILURE by {abs(result.margin)}.")


def test_to_dict_carries_summary_for_the_prompt():
    payload = checks.resolve(neutral_state(), "lore", "hard").to_dict()
    assert isinstance(payload["summary"], str) and payload["summary"]
    assert payload["dc"] == 16
    assert payload["difficulty"] == "hard"
    assert isinstance(payload["modifiers"], list)


def test_default_rng_is_the_deterministic_dice_stream():
    a = GameState(rng_seed=99)
    b = GameState(rng_seed=99)
    assert checks.resolve(a, "lore").natural == checks.resolve(b, "lore").natural
    # And consecutive draws differ rather than repeating a frozen value.
    faces = {checks.resolve(a, "lore").natural for _ in range(12)}
    assert len(faces) > 1


def test_every_declared_degree_is_reachable_by_some_shipped_build():
    """
    A band nobody can roll into is dead content, and one had been for the whole
    life of the game.

    `crit_success` required margin 10 over a `standard` DC of 13, i.e. a total
    of 23. The best build in the flagship is a hearthkeeper at the forge: craft
    14 (+2) plus `skill_bonus.craft: 2` is +4, so a natural 20 makes 24 -- a 5%
    band for one archetype at one skill, and mathematically IMPOSSIBLE for a
    wayfarer, whose craft 8 tops out at 19. Content behind it never fired:
    `forge_bellows`'s charcoal payout, its 1.6x wage, three reputation rows,
    and `craft_item`'s crit batch bonus.

    THE NUMBER IS NOT THE GUARD -- this is. Tuning `min_margin` back up until
    the band goes dead again fails here rather than in a player's run.
    """
    import yaml

    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        rules = yaml.safe_load(
            open("games/clockwork-dark/data/rules/skills.yaml", encoding="utf-8")
        )
        archetypes = yaml.safe_load(
            open("games/clockwork-dark/data/rules/archetypes.yaml", encoding="utf-8")
        )

        dc = int(rules["difficulty"][rules.get("default_difficulty", "standard")])
        degrees = rules["degrees"]

        # The best total any shipped build can roll on a natural 20, before
        # situational modifiers -- every one of which in this table is a
        # PENALTY except two, so this is a genuine ceiling.
        best = -99
        for arch in (archetypes.get("archetypes") or archetypes).values():
            if not isinstance(arch, dict):
                continue
            stats = arch.get("stats") or {}
            bonuses = arch.get("skill_bonus") or {}
            for skill, value in stats.items():
                stat_mod = (int(value) - 10) // 2
                best = max(best, 20 + stat_mod + int(bonuses.get(skill, 0)))

        top_margin = best - dc
        unreachable = [
            str(d.get("id"))
            for d in degrees
            if int(d.get("min_margin", 0)) > top_margin
        ]
        assert not unreachable, (
            f"these degrees cannot be rolled by any shipped archetype at "
            f"difficulty '{rules.get('default_difficulty')}' (DC {dc}, best "
            f"possible total {best}, so best margin {top_margin}): "
            f"{unreachable}. Any content gated on them is dead."
        )
    finally:
        registry.deactivate()

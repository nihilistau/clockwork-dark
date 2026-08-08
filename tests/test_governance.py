"""
Governance pipeline tests.

The point of these is not that the rules are correct -- ``SceneRulesEngine``
was already tested. It is that the rules now RUN, that the two legacy chains
delegate to one implementation without changing behaviour, and that an unearned
stat claim becomes a number someone can look at.
"""

from __future__ import annotations

import pytest

from engine.agents.governance import (
    PHASE_DIRECTIVE,
    PHASE_POST,
    DoomSignsInterceptor,
    EvilPhaseTone,
    GovernancePipeline,
    RulesGovernor,
    StorytellerMind,
    TurnContext,
    get_governance,
    reset_governance,
)
from engine.game.state import EvilPhase, GameState
from engine.telemetry import get_oracle, reset_oracle


@pytest.fixture(autouse=True)
def _clean_singletons():
    reset_governance()
    reset_oracle()
    yield
    reset_governance()
    reset_oracle()


def _ctx(**kwargs) -> TurnContext:
    state = kwargs.pop("state", None) or GameState()
    return TurnContext(state=state, **kwargs)


# -- pipeline construction --------------------------------------------------


def test_pipeline_builds_every_phase_from_config():
    pipeline = get_governance()
    assert pipeline.chains[PHASE_POST], "POST chain must not be empty"
    assert any(
        isinstance(hook, RulesGovernor) for hook in pipeline.chains[PHASE_POST]
    ), "RulesGovernor must be wired -- it was dead code before"


def test_chains_run_in_priority_order():
    class First:
        priority = 1
        name = "First"

        def run_pre(self, state, prompt, **_):
            return prompt + "A"

    class Second:
        priority = 99
        name = "Second"

        def run_pre(self, state, prompt, **_):
            return prompt + "B"

    pipeline = GovernancePipeline({"pre": [Second(), First()]})
    assert pipeline.run_pre(GameState(), "") == "AB"


def test_a_raising_interceptor_does_not_break_the_turn():
    class Exploding:
        priority = 10
        name = "Exploding"

        def run_pre(self, state, prompt, **_):
            raise RuntimeError("boom")

    class Fine:
        priority = 20
        name = "Fine"

        def run_pre(self, state, prompt, **_):
            return prompt + "ok"

    pipeline = GovernancePipeline({"pre": [Exploding(), Fine()]})
    assert pipeline.run_pre(GameState(), "") == "ok"


# -- the two legacy chains now delegate -------------------------------------


def test_legacy_pre_chain_delegates_to_governance():
    """``run_pre_interceptors`` must be the same code path as the pipeline."""
    from engine.lore.interceptors import AwarenessGateInterceptor, run_pre_interceptors

    state = GameState()
    prompt = "keep me"
    chain = [AwarenessGateInterceptor()]

    legacy = run_pre_interceptors(state, prompt, interceptors=chain)
    direct = get_governance().run_pre(state, prompt, interceptors=chain)
    assert legacy == direct == prompt


def test_legacy_media_chain_delegates_to_governance():
    from engine.media.interceptors import run_media_interceptors

    state = GameState()
    data = run_media_interceptors(state, narration="A quiet street.")
    # Shape is MediaPipelineResult.to_dict(); the contract is that it is still
    # a dict and still produced, not what the media pipeline chose to do.
    assert isinstance(data, dict)


# -- directive phase --------------------------------------------------------


def test_directives_build_one_block_and_do_not_touch_the_prompt():
    """
    The directive chain must NEVER append to an assembled prompt.

    Appending per system block after the budget was fitted is issue R-01.
    """
    state = GameState()
    directives = get_governance().build_directives(state)
    assert directives
    assert "Tone:" in directives
    # Built from an empty seed, so it cannot contain a caller's prompt.
    assert "SYSTEM" not in directives


def test_evil_phase_tone_shifts_with_the_phase():
    dormant = GameState(evil_progress=0.0)
    consuming = GameState(evil_progress=0.9)
    assert consuming.evil_phase is EvilPhase.CONSUMING

    tone = EvilPhaseTone()
    assert tone.run_pre(dormant, "") != tone.run_pre(consuming, "")


def test_storyteller_mind_is_silent_when_the_knobs_are_neutral():
    state = GameState()
    state.storyteller_mind.cruelty_bias = 0.35
    state.storyteller_mind.reward_generosity = 0.5
    state.storyteller_mind.patience = 80.0
    assert StorytellerMind().run_pre(state, "base") == "base"


def test_doom_signs_narrate_only_doom_marks():
    state = GameState()
    state.world_events.append(
        {"event_id": "caravan", "text": "A caravan arrives.", "expires_day": 9}
    )
    state.world_events.append(
        {"event_id": "tower", "text": "A tower rises.", "source": "doom"}
    )
    out = DoomSignsInterceptor().run_pre(state, "")
    assert "A tower rises." in out
    assert "A caravan arrives." not in out


def test_doom_signs_are_silent_with_no_marks():
    assert DoomSignsInterceptor().run_pre(GameState(), "base") == "base"


# -- R001 / R004 / R005 -----------------------------------------------------


def test_r005_clamps_and_records_out_of_range_awareness():
    state = GameState()
    state.awareness = 140.0
    ctx = _ctx(state=state)

    RulesGovernor().run_post(ctx)

    assert state.awareness == 100.0, "must clamp, not merely complain"
    assert any(v["rule_id"] == "R005" for v in ctx.violations)


def test_r004_flags_evil_progress_going_backwards():
    state = GameState(evil_progress=0.2)
    ctx = _ctx(state=state, metadata={"evil_before": 0.5})

    RulesGovernor().run_post(ctx)

    assert any(v["rule_id"] == "R004" for v in ctx.violations)


def test_r004_is_quiet_when_evil_advances():
    state = GameState(evil_progress=0.5)
    ctx = _ctx(state=state, metadata={"evil_before": 0.2})
    RulesGovernor().run_post(ctx)
    assert not [v for v in ctx.violations if v["rule_id"] == "R004"]


def test_r001_flags_a_location_that_does_not_exist():
    state = GameState(location_id="nowhere_at_all")
    ctx = _ctx(state=state)

    RulesGovernor().run_post(ctx)

    assert any(v["rule_id"] == "R001" for v in ctx.violations)


def test_r001_accepts_generated_non_canon_locations():
    """
    A procgen location is legal.

    The upstream implementation validated against the five CANON ids, which
    would have flagged every turn spent foraging in `deeper_forest` as a
    violation. Guard against porting that back in.
    """
    from engine.game.locations import LOCATION_IDS

    non_canon = sorted(
        LOCATION_IDS - {
            "forest_clearing",
            "edgewood_square",
            "edgewood_bakery",
            "tinker_caravan",
            "millhaven_gate",
        }
    )
    if not non_canon:
        pytest.skip("map has no non-canon locations")

    ctx = _ctx(state=GameState(location_id=non_canon[0]))
    RulesGovernor().run_post(ctx)
    assert not [v for v in ctx.violations if v["rule_id"] == "R001"]


def test_r001_reads_the_location_set_through_the_rules_engine():
    """
    The rebind hazard.

    ``LOCATION_IDS`` is a frozenset that a game swap REBINDS; caches.py
    refreshes the copy inside scene_rules_engine. The governor must see that
    refresh, which it only does by going through the rules engine rather than
    holding its own ``from ... import``.
    """
    import engine.mcp.scene_rules_engine as sre

    original = sre.LOCATION_IDS
    try:
        sre.LOCATION_IDS = frozenset({"a_wholly_different_map"})
        ctx = _ctx(state=GameState(location_id="a_wholly_different_map"))
        RulesGovernor().run_post(ctx)
        assert not [v for v in ctx.violations if v["rule_id"] == "R001"], (
            "governor kept a stale copy of LOCATION_IDS"
        )
    finally:
        sre.LOCATION_IDS = original


# -- R003: the telemetry that motivated the whole thing ---------------------


def test_r003_records_an_unearned_stat_claim_instead_of_dropping_it():
    ctx = _ctx(parsed={"stat_changes": {"gold": 50}})

    RulesGovernor().run_post(ctx)

    violations = [v for v in ctx.violations if v["rule_id"] == "R003"]
    assert violations
    assert violations[0]["severity"] == "warning", (
        "the engine already ignored the claim; the turn is not broken"
    )

    metrics = get_oracle().metrics()
    assert metrics["unearned_claims"]["gold"]["count"] == 1
    assert metrics["unearned_claims"]["gold"]["max_delta"] == 50


def test_r003_accepts_a_claim_backed_by_a_tool_receipt():
    ctx = _ctx(
        parsed={"stat_changes": {"gold": 5}},
        tool_receipts=[{"type": "stat", "stat": "gold"}],
    )
    RulesGovernor().run_post(ctx)
    assert not [v for v in ctx.violations if v["rule_id"] == "R003"]
    assert get_oracle().metrics()["unearned_claims_total"] == 0


def test_r003_ignores_a_zero_delta():
    ctx = _ctx(parsed={"stat_changes": {"gold": 0}})
    RulesGovernor().run_post(ctx)
    assert not ctx.violations


def test_repeated_claims_accumulate_so_a_prompt_bug_is_visible():
    governor = RulesGovernor()
    for amount in (10, 50, 20):
        governor.run_post(_ctx(parsed={"stat_changes": {"gold": amount}}))

    claim = get_oracle().metrics()["unearned_claims"]["gold"]
    assert claim["count"] == 3
    assert claim["total_delta"] == 80
    assert claim["max_delta"] == 50


# -- telemetry --------------------------------------------------------------


def test_oracle_rolls_turns_into_metrics():
    oracle = get_oracle()
    oracle.record_turn(
        {
            "governance": [{"rule_id": "R003", "message": "x"}],
            "assistant": {"spoke": True, "intent": "hint", "reliable": False},
            "tool_receipts": [{"skill": "move_to"}],
        },
        latency_ms=120.0,
        evil_progress=0.4,
    )
    oracle.record_turn({}, latency_ms=80.0, evil_progress=0.42)

    metrics = oracle.metrics()
    assert metrics["turns"] == 2
    assert metrics["violation_rate"] == 0.5
    assert metrics["violations_by_rule"] == {"R003": 1}
    assert metrics["assistant_intervention_rate"] == 0.5
    assert metrics["assistant_misled_count"] == 1
    assert metrics["avg_latency_ms"] == 100.0
    assert metrics["last_evil_progress"] == 0.42
    assert len(oracle.recent()) == 2


def test_oracle_metrics_are_safe_on_a_fresh_collector():
    metrics = get_oracle().metrics()
    assert metrics["turns"] == 0
    assert metrics["violation_rate"] == 0.0
    assert metrics["unearned_claims"] == {}

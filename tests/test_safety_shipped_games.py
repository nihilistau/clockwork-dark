"""
The compatibility bar for the safety layer — mechanism, not shipped values.

This file used to pin every shipped story to an INERT policy, which made the
test a hostage of content decisions: the moment The Wicked Garden declared the
`explicit` rating its content is written for, a test named "shipped stories are
unchanged" failed on a change that was the point. What the engine actually
guarantees is not "every story is suggestive" — it is:

  1. The policy in force MATCHES THE DECLARATION. A story that declares nothing
     resolves inert; a story that declares a ceiling and default gets exactly
     that ceiling and default. The expectation is computed from the manifest
     block itself, never hardcoded, so shipping a new rating cannot break this
     file.
  2. No shipped story configures a LIMIT. `hard_nos` belongs to the PLAYER, set
     in the boundary sheet at the start of a run; a manifest pre-filling it
     would be a story deciding what its player finds unbearable.
  3. The player dial is clamped both ways: raising past the story ceiling is
     refused, lowering below the story default is honoured.
  4. An INERT policy stays free: no prompt text, no RNG draw, every surface
     allows. (Asserted only for stories whose declaration implies inert —
     for the others the safety layer being active is the declared behaviour.)

Version: v0.3.0 [2026-08-13]
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from engine.game.state import GameState
from engine.games import registry
from engine.safety import reset_policies
from engine.safety.gate import SafetyGate
from engine.safety.governor import SafetyCeiling, SafetyDirective
from engine.safety.policy import resolve
from engine.safety.tiers import LOWEST, IntensityTier, clamp

SHIPPED = ("clockwork-dark", "wicked-garden")


@pytest.fixture(autouse=True)
def _clean_policies() -> Iterator[None]:
    reset_policies()
    yield
    reset_policies()


@pytest.fixture(params=SHIPPED)
def shipped(request: Any) -> Iterator[Any]:
    """
    Activate each shipped game in turn, then put it back.

    Teardown is not optional -- activation mutates process-global config and a
    dozen module caches. Same reasoning as ``tests/test_games.py::garden``.
    """
    manifest = registry.activate(request.param)
    try:
        reset_policies()
        yield manifest
    finally:
        registry.deactivate()
        reset_policies()


def _declared(manifest: Any) -> tuple[IntensityTier, IntensityTier]:
    """
    The (ceiling, default) the manifest's own block implies.

    Computed from the declaration with the same fallbacks resolve() documents,
    so the expectation moves WITH the manifest rather than being restated here.
    """
    block = manifest.extras.get("safety") or {}
    intensity = block.get("intensity") if isinstance(block.get("intensity"), dict) else {}
    ceiling = IntensityTier.parse(
        intensity.get("ceiling", intensity.get("max")), default=LOWEST
    )
    default = IntensityTier.parse(intensity.get("default"), default=LOWEST)
    # resolve() clamps at construction; mirror it so the expectation is legal.
    return ceiling, default if default <= ceiling else ceiling


class TestPolicyMatchesDeclaration:
    def test_no_shipped_story_declares_a_limit(self, shipped: Any) -> None:
        """Rating is authorship; limits are the player's. Never a manifest's."""
        block = shipped.extras.get("safety") or {}
        assert not block.get("hard_nos")
        assert not block.get("markers")
        assert not block.get("boundaries")

    def test_the_resolved_policy_is_the_declared_one(self, shipped: Any) -> None:
        ceiling, default = _declared(shipped)
        policy = resolve()
        assert policy.ceiling is ceiling, policy
        assert policy.intensity is default, policy
        assert policy.sheet.empty
        assert policy.markers.empty

    def test_a_story_declaring_nothing_is_inert(self, shipped: Any) -> None:
        """The flagship path: no `safety:` block must mean a free turn."""
        if shipped.extras.get("safety"):
            pytest.skip(f"{shipped.slug} declares a safety block")
        assert resolve().inert


class TestThePlayerDial:
    def test_raising_past_the_ceiling_is_clamped(self, shipped: Any) -> None:
        ceiling, _ = _declared(shipped)
        policy = resolve(player={"intensity": "extreme"})
        assert policy.intensity is clamp(IntensityTier.EXTREME, ceiling)

    def test_lowering_is_always_honoured(self, shipped: Any) -> None:
        policy = resolve(player={"intensity": "suggestive"})
        assert policy.intensity is IntensityTier.SUGGESTIVE

    def test_the_config_dial_follows_the_same_clamp(self, shipped: Any, monkeypatch: Any) -> None:
        """The Settings screen writes safety.intensity.player; same rules."""
        from engine.config import get_config

        ceiling, _ = _declared(shipped)
        monkeypatch.setitem(
            get_config()._data.setdefault("safety", {}).setdefault("intensity", {}),  # noqa: SLF001
            "player",
            "extreme",
        )
        policy = resolve()
        assert policy.intensity <= ceiling

    def test_the_story_sentinel_follows_the_story(self, shipped: Any, monkeypatch: Any) -> None:
        from engine.config import get_config

        _, default = _declared(shipped)
        monkeypatch.setitem(
            get_config()._data.setdefault("safety", {}).setdefault("intensity", {}),  # noqa: SLF001
            "player",
            "story",
        )
        assert resolve().intensity is default


class TestAnInertPolicyStaysFree:
    """
    The zero-cost guarantees, asserted only where the declaration implies
    inert. A story that declares a rating has ASKED for the layer to run;
    charging it is the documented behaviour, not a regression.
    """

    @pytest.fixture(autouse=True)
    def _only_inert_stories(self, shipped: Any) -> None:
        ceiling, default = _declared(shipped)
        if ceiling is not LOWEST or default is not LOWEST:
            pytest.skip(f"{shipped.slug} declares a non-inert rating")

    def test_the_gm_prompt_gains_nothing(self, shipped: Any) -> None:
        state = GameState()
        assert SafetyGate.for_state(state).directive_text() == ""
        assert SafetyDirective().run_pre(state, "PROMPT") == "PROMPT"

    def test_no_rng_stream_is_drawn(self, shipped: Any) -> None:
        # A recorded seed must replay identically with the layer present.
        state = GameState(rng_seed=4242)
        gate = SafetyGate.for_state(state)
        gate.review_input("anything at all, however pointed")
        gate.review_narration("anything at all, however pointed")
        assert state.rng_counters == {}

    def test_every_surface_allows(self, shipped: Any) -> None:
        gate = SafetyGate.for_state(GameState())
        for verdict in (
            gate.review_input("burn the bakery down"),
            gate.review_beat("burn the bakery down", declared="extreme"),
            gate.review_narration("burn the bakery down"),
        ):
            assert verdict.allowed
            assert verdict.outcomes_apply

    def test_display_strings_are_returned_verbatim(self, shipped: Any) -> None:
        gate = SafetyGate.for_state(GameState())
        for name in ("Collar of Soft Thorns", "brass key", "tinker's caravan"):
            assert gate.rename(name) == name


class TestTheCommitHook:
    def test_the_commit_hook_records_the_tier_in_force(self, shipped: Any) -> None:
        """
        SafetyCeiling always writes the tier in force for the turn journal and
        never edits effects on content it has no reason to touch.
        """
        _, default = _declared(shipped)

        class _Plan:
            def __init__(self) -> None:
                self.beat = "the caravan arrives"
                self.effects = [{"type": "stat", "stat": "gold", "delta": 5}]
                self.choices: list = []
                self.extras: dict = {}

        class _Ctx:
            def __init__(self, plan: Any) -> None:
                self.state = GameState()
                self.plans = {"storyteller": plan}
                self.narration = "The caravan arrives."
                self.negotiated = None
                self.metadata: dict = {}
                self.intensity = ""
                self.safety_block = ""
                self.veto = ""

        plan = _Plan()
        ctx = _Ctx(plan)
        SafetyCeiling().run_post(ctx)

        assert plan.effects == [{"type": "stat", "stat": "gold", "delta": 5}]
        assert ctx.veto == ""
        # The one thing it DOES write: the tier in force, for the turn journal.
        assert ctx.intensity == default.value

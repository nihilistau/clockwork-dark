"""
The compatibility bar for the safety layer.

``games/clockwork-dark/game.yaml`` says the safety layer must leave the shipped
stories exactly as they were, in the same way the manifest layer's bar was that
activating the flagship is a no-op merge. This file is that claim, tested.

The claim has three parts and each is a separate failure if it breaks:

  1. No shipped story configures a LIMIT -- the flagship declares no ``safety:``
     block at all, and The Wicked Garden declares one that names an intensity
     ceiling and nothing else -- so both resolve to an INERT policy.
  2. An inert policy contributes no prompt text -- R-01 means the budget is
     already over, and a layer nobody configured must not spend a token of it.
  3. An inert policy draws no RNG, so a recorded seed replays identically with
     the layer present.

Part 1 is the one that changed shape. It used to read "neither shipped story
declares a ``safety:`` block", which was true when the second story was a
near-copy of the flagship. The Garden does declare one, and it still resolves
inert -- which is the more useful claim, because it is the DECLARATION that has
to be inspected rather than its absence.

Version: v0.2.0 [2026-08-09]
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
from engine.safety.tiers import IntensityTier

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


class TestShippedStoriesAreUnchanged:
    def test_neither_declares_a_limit(self, shipped: Any) -> None:
        """
        What makes a policy inert is what is ABSENT from the block, not the
        block. The flagship declares nothing; the Garden declares a ceiling and
        a fade preference, which are authorship, not restriction.

        ``hard_nos`` stays empty in a manifest on purpose: limits belong to the
        PLAYER, set in the boundary sheet at the start of a run. A story
        pre-filling them would be a story deciding what its player finds
        unbearable -- and would make everything below this line false.
        """
        block = shipped.extras.get("safety") or {}
        assert not block.get("hard_nos")
        assert not block.get("markers")
        ceiling = str((block.get("intensity") or {}).get("ceiling") or "suggestive")
        assert ceiling == "suggestive"

    def test_the_resolved_policy_is_inert(self, shipped: Any) -> None:
        policy = resolve()
        assert policy.inert, policy
        assert policy.ceiling is IntensityTier.SUGGESTIVE
        assert policy.intensity is IntensityTier.SUGGESTIVE
        assert policy.sheet.empty
        assert policy.markers.empty

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

    def test_the_commit_hook_changes_nothing(self, shipped: Any) -> None:
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
        assert ctx.metadata == {}
        assert ctx.safety_block == ""
        assert ctx.veto == ""
        # The one thing it DOES write: the tier in force, for the turn journal.
        assert ctx.intensity == "suggestive"

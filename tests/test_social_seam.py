"""
The `paths.social` seam (v0.22.0 spec §2.1-2.4).

A story that declares no `paths.social` pays nothing: a turn of it adds no
engine.social submodule to sys.modules (and a fresh interpreter imports none),
its payload carries no `phone` key, and that payload is byte-identical to the
one v0.21.1 built (recorded before T1 changed any engine file).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.social_fixtures import receipts_active  # noqa: F401  (test_every_social_kind_has_a_handler)

SIX = ["clockwork-dark", "wicked-garden", "neon-city", "the-long-con", "dev-story", "hue-and-cry"]

ROOT = Path(__file__).resolve().parents[1]
PAYLOADS = Path(__file__).parent / "fixtures" / "social_seam_payloads_v0211.json"

#: The one submodule every story imports: data-only names, read by effects.py (Plan decision 2).
ALWAYS = {"engine.social.kinds"}


def _social_names(names) -> set[str]:
    return {n for n in names if n.startswith("engine.social.") and n not in ALWAYS}


def _payload(slug: str, volatile: tuple[str, ...] = ("session_id",)) -> str:
    """One story's payload after a 3-hour advance at seed 99, minus its volatile keys, as sorted JSON."""
    from engine.game import clock, procgen
    from engine.games import registry

    registry.activate(slug)
    try:
        state = procgen.new_game_state(player_name="Ash", seed=99)
        clock.advance_time(state, 3.0)
        body = state.to_client_dict()
    finally:
        registry.deactivate()
    for key in volatile:
        body.pop(key, None)
    return json.dumps(body, sort_keys=True)


@pytest.mark.parametrize("slug", SIX)
def test_a_story_without_paths_social_carries_no_phone_and_imports_nothing(slug: str) -> None:
    """A SNAPSHOT of sys.modules, never a pop: popping builds second registries (pre-flight F8)."""
    from engine import social
    from engine.game import clock, procgen
    from engine.games import registry

    before = set(sys.modules)
    registry.activate(slug)
    try:
        assert social.declared() is False
        state = procgen.new_game_state(player_name="Ash", seed=1234)
        clock.advance_time(state, 3.0)
        payload = state.to_client_dict()
        assert "phone" not in payload
        assert state.social == {}
    finally:
        registry.deactivate()
    added = sorted(_social_names(set(sys.modules) - before))
    assert added == [], added


@pytest.mark.parametrize("slug", SIX)
def test_the_payload_is_byte_identical_to_v0211(slug: str) -> None:
    recorded = json.loads(PAYLOADS.read_text(encoding="utf-8"))
    assert _payload(slug, tuple(recorded["volatile"])) == recorded["payloads"][slug]


_CHILD = """
import json, sys
from engine.game import clock, procgen
from engine.games import registry
for slug in sys.argv[1:]:
    registry.activate(slug)
    try:
        state = procgen.new_game_state(player_name="Ash", seed=1234)
        clock.advance_time(state, 3.0)
        assert "phone" not in state.to_client_dict(), slug
    finally:
        registry.deactivate()
print(json.dumps(sorted(n for n in sys.modules if n.startswith("engine.social.") and n != "engine.social.kinds")))
"""


@pytest.mark.process
def test_a_fresh_interpreter_imports_no_social_submodule_for_any_shipped_story() -> None:
    """The honest "never imported" (F8): one child interpreter plays a turn of all six non-phone stories."""
    import subprocess

    done = subprocess.run([sys.executable, "-c", _CHILD, *SIX], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr[-2000:]
    assert json.loads(done.stdout.strip().splitlines()[-1]) == []


def test_every_social_kind_is_engine_only() -> None:
    from engine.game.effects import ENGINE_ONLY_EFFECTS
    from engine.social.kinds import SOCIAL_EFFECT_KINDS

    assert SOCIAL_EFFECT_KINDS <= ENGINE_ONLY_EFFECTS
    assert {"custody_served", "law_deed_committed"} <= ENGINE_ONLY_EFFECTS
    assert all(kind.startswith("social_") for kind in SOCIAL_EFFECT_KINDS)


def test_the_social_streams_are_distinct_and_new() -> None:
    from engine.game import rng

    names = [rng.SOCIAL_POPULATION, rng.SOCIAL_MATCH, rng.SOCIAL_PACE, rng.SOCIAL_BEHAVIOUR,
             rng.SOCIAL_MEDIA, rng.SOCIAL_MEET, rng.SOCIAL_GAME]
    assert len(set(names)) == 7
    others = {v for k, v in vars(rng).items() if k.isupper() and isinstance(v, str) and not k.startswith("SOCIAL_")}
    assert not set(names) & others


def test_state_social_round_trips_and_an_old_save_loads_empty() -> None:
    from engine.game.state import GameState

    state = GameState()
    state.social = {"player": {"name": "Sam"}, "seq": 3}
    again = GameState.from_dict(state.to_save_dict())
    assert again.social == state.social
    old = state.to_save_dict()
    old.pop("social")
    assert GameState.from_dict(old).social == {}


def test_an_empty_social_slice_is_left_out_of_the_save_and_loads_back_empty() -> None:
    """A story with no phone writes no `social` key, and a save without one loads as {}."""
    from engine.game.state import GameState

    saved = GameState().to_save_dict()
    assert "social" not in saved
    assert GameState.from_dict(saved).social == {}


def test_an_endless_manifest_may_not_declare_endings(tmp_path) -> None:
    from engine.games.manifest import from_dict
    from engine.games.validation import StoryValidator

    manifest = from_dict(
        {"id": "endless-probe", "title": "P", "version": "0.1.0", "engine_requires": ">=0.2.0",  # Plan decision 23
         "endless": True, "paths": {"endings": "x.yaml"}},
        slug="endless-probe",
        root=tmp_path,
    )
    issues = StoryValidator(manifest).run()
    assert any(i.ref_id == "endless" and i.severity == "error" for i in issues), issues


def test_every_social_kind_has_a_handler(receipts_active) -> None:
    """Plan decision 11: every kind T1 named has its handler registered by the module that owns it (T26)."""
    from engine.game.effects import registered_kinds
    from engine.social.kinds import SOCIAL_EFFECT_KINDS

    assert SOCIAL_EFFECT_KINDS <= set(registered_kinds())

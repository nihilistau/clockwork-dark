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
from typing import Any

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
             rng.SOCIAL_MEDIA, rng.SOCIAL_GAME, rng.SOCIAL_VENUE]
    assert len(set(names)) == 7
    assert not hasattr(rng, "SOCIAL_MEET")
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


#: v0.23.0's new data files (spec §22): each a skeleton until its task fills it.
NEW_FILES = ("conversation", "promises", "growth", "topics", "layers", "plans", "scenes", "life_events", "homes")


def test_the_new_data_files_are_declared_and_load(receipts_active) -> None:
    """Every fixed file loads as a mapping, and each v0.23.0 file's opening comment names its spec section."""
    import re

    from engine import social

    assert set(NEW_FILES) <= set(social.FILES)
    for name in social.FILES:
        assert isinstance(social.data(name), dict), name
    directory = social.social_dir()
    assert directory is not None
    for name in NEW_FILES:
        lines = (directory / f"{name}.yaml").read_text(encoding="utf-8").splitlines()
        header = []
        for line in lines:
            if not line.startswith("#"):
                break
            header.append(line)
        assert re.search(r"§\d+", "\n".join(header)), f"{name}.yaml's header names no spec section"


@pytest.mark.parametrize("slug", SIX)
def test_no_story_but_read_receipts_builds_a_turnstile(slug: str) -> None:
    """
    §19.5 pin 9 (m10), in process: a session of a story without `paths.social` carries no turnstile.
    Whether `engine.social.turnstile` is IMPORTED cannot be judged here (any earlier test that loaded
    the voicer imported it for good), so that half is the fresh interpreter's, below. `run_guarded`'s
    own half (it takes no turnstile for these stories) is `test_another_storys_choice_runs_its_turn_untouched`.
    """
    from engine.games import registry
    from engine.session.store import SessionStore

    registry.activate(slug)
    try:
        session = SessionStore().create(seed=1)
        assert session.narration_turnstile is None
    finally:
        registry.deactivate()


_TURNSTILE_CHILD = """
import json, sys
from engine.game import procgen
from engine.games import registry
from engine.session.store import SessionStore


class _KeepsNothing:
    keeps_nothing = True

    def save(self, state, **_):
        return ""

    def append_transcript(self, *_a, **_k):
        return None


NARRATION = ("The moment holds. Nothing in the room moves that you did not move yourself, and the air "
             "carries the small sounds of a place going on without you: a door somewhere, a voice "
             "further off, the light changing by a degree. You take it in and decide what comes next.")


def stub(messages, **_):
    return json.dumps({"narration": NARRATION, "choices": [{"id": "a", "text": "Go on"},
                                                           {"id": "b", "text": "Look around"}]})


from engine.scenes.default_scene import run_guarded   # v0.23.0 T11: a turn through run_guarded too

built = {}
turned = {}
for slug in sys.argv[1:]:
    registry.activate(slug)
    try:
        keeps = _KeepsNothing()
        state = procgen.new_game_state(player_name="Ash", seed=1234)
        session = SessionStore(save_store=lambda: keeps)._build(state, llm_fn=stub, saves=keeps)
        built[slug] = session.narration_turnstile is None
        payload, error, busy = run_guarded(session, "Look around", None)
        turned[slug] = payload is not None and not error
    finally:
        registry.deactivate()
print(json.dumps({"none": built, "turned": turned, "imported": "engine.social.turnstile" in sys.modules}))
"""


@pytest.mark.process
def test_a_fresh_interpreter_builds_no_turnstile_and_never_imports_it() -> None:
    """§19.5 pin 9 (m10), honestly: one child interpreter builds a session of each of the six stories
    without `paths.social` through `SessionStore._build` and plays a turn of each through `run_guarded`
    (v0.23.0 T11); none has a turnstile and the module is never imported."""
    import subprocess

    done = subprocess.run([sys.executable, "-c", _TURNSTILE_CHILD, *SIX], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result == {"none": {slug: True for slug in SIX}, "turned": {slug: True for slug in SIX},
                      "imported": False}, result


# -- places (v0.23.0 T10; §19.5 pins 1, 2 and 7) -----------------------------------------------------


@pytest.mark.parametrize("slug", SIX)
def test_an_edge_without_minutes_is_unchanged(slug: str) -> None:
    """Pin 1: every edge of another story comes out of `_clean_edge` as it always did, with no
    `minutes` key, and one move's receipt carries none."""
    import yaml

    from engine.game import locations, procgen
    from engine.game.engine import GameEngine
    from engine.games import registry

    registry.activate(slug)
    try:
        raw = yaml.safe_load(locations._locations_path().read_text(encoding="utf-8"))["locations"]
        known = set(raw)
        checked = 0
        for src, row in raw.items():
            for dst, edge_raw in ((row or {}).get("connections") or {}).items():
                got = locations._clean_edge(str(src), str(dst), edge_raw, known)
                assert got is not None and "minutes" not in got, (src, dst)
                assert set(got) == {"hours", "danger_dc", "awareness_delta", "one_way", *dict(edge_raw)}, (src, dst)
                assert got["hours"] == max(0, min(48, int(dict(edge_raw).get("hours", 1)))), (src, dst)
                checked += 1
        assert checked
        state = procgen.new_game_state(seed=1)
        engine = GameEngine(state)
        moved = False
        for dst in locations.neighbours(state.location_id):
            result = engine.move_to(dst)
            if result.success:
                assert "minutes" not in result.to_dict()
                moved = True
                break
        assert moved
    finally:
        registry.deactivate()


def test_a_minutes_edge_defaults_hours_to_zero() -> None:
    """Pin 2: a synthetic edge `{"minutes": 5}` has `hours` 0, not `_EDGE_DEFAULTS`' 1."""
    from engine.game import locations

    edge = locations._clean_edge("a", "b", {"minutes": 5}, {"a", "b"})
    assert edge["hours"] == 0 and edge["minutes"] == 5


# -- the narrated turn opened (v0.23.0 T11; §19.5 pins 3, 4, 5, 6 and 9) ---------------------------------

#: Each other story's directive chain, as it was before READ RECEIPTS' world turn (seam pin 4).
CHAINS = {
    "clockwork-dark": ["EvilPhaseTone", "DoomSignsInterceptor", "StorytellerMind"],
    "wicked-garden": ["StorytellerMind"], "neon-city": ["StorytellerMind"], "the-long-con": ["StorytellerMind"],
    "dev-story": ["StorytellerMind"], "hue-and-cry": ["StorytellerMind"],
}

#: Long enough for the turn schema's narration minimum, and story-neutral.
_NARRATION = ("The moment holds. Nothing in the room moves that you did not move yourself, and the air "
              "carries the small sounds of a place going on without you: a door somewhere, a voice "
              "further off, the light changing by a degree. You take it in and decide what comes next.")


def _story_stub():
    """An `llm_fn` for any story's storyteller (its persona's first line identifies the call): a turn with
    no intent, valid under every grammar; any other agent gets a short shapeless line."""
    from engine.agents.prompts import storyteller_persona

    calls: list[int] = []

    def fake(messages, **_):
        persona = storyteller_persona().strip().splitlines()[0]
        if not any(persona in str(m.get("content", "")) for m in messages):
            return "Nothing is said, at length."
        calls.append(1)
        return json.dumps({"narration": _NARRATION, "choices": [{"id": "a", "text": "Go on"},
                                                                {"id": "b", "text": "Stand a while and look"}]})

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


@pytest.mark.parametrize("slug", SIX)
def test_the_world_verbs_change_no_other_storys_catalogue_or_grammar(slug: str) -> None:
    """Pin 3: at each other story's opening, `legal_intents`, `scene_owns_turn` and the turn schema's bytes are
    the same with and without `engine.social.world` imported; the world gate is closed there."""
    import importlib

    from engine.game import intents, procgen
    from engine.games import registry
    from engine.llm.schemas import storyteller_turn_schema

    registry.activate(slug)
    try:
        state = procgen.new_game_state(player_name="Ash", seed=1234)

        def read() -> tuple[str, bool, str]:
            verbs = intents.legal_intents(state)
            return (repr(verbs), intents.scene_owns_turn(state),
                    json.dumps(storyteller_turn_schema(intents=verbs), sort_keys=True))

        before = read()
        importlib.import_module("engine.social.world")
        assert read() == before
        assert intents._social_world(state) is False
        assert not {v.action for v in intents.legal_intents(state)} & intents.SOCIAL_WORLD_ACTIONS
    finally:
        registry.deactivate()


def test_the_default_directive_list_is_untouched() -> None:
    """Pin 4: config/default.yaml's directives are the three they were; every other story's chain is what it
    was; READ RECEIPTS' is exactly [StorytellerMind, SocialWorld] (no doom ledger's tone reaches it)."""
    from engine import yamlio
    from engine.agents.governance import PHASE_DIRECTIVE, GovernancePipeline
    from engine.games import registry

    default = yamlio.safe_load((ROOT / "config" / "default.yaml").read_text(encoding="utf-8"))
    assert default["governance"]["directives"] == ["EvilPhaseTone", "DoomSignsInterceptor", "StorytellerMind"]
    for slug, chain in {**CHAINS, "read-receipts": ["StorytellerMind", "SocialWorld"]}.items():
        registry.activate(slug)
        try:
            names = [type(i).__name__ for i in GovernancePipeline.from_config().chains[PHASE_DIRECTIVE]]
        finally:
            registry.deactivate()
        assert names == chain, slug


@pytest.mark.parametrize("slug", SIX)
def test_another_storys_choice_runs_its_turn_untouched(slug: str, monkeypatch) -> None:
    """Pins 5, 6 and 9: `/api/game/choice` runs a turn for each other story (its stub built into the app
    before the run starts, F2; an opening option's `choice_id`, F3) and answers 200 with narration. The
    phone_up refusal never appears, the world turn's path is never taken, the session has no turnstile, and
    the turn imports no `engine.social` submodule (a `sys.modules` snapshot, v0.22 PD2)."""
    from engine.games import registry
    from engine.scenes import default_scene

    def no_world_turn(*_a, **_k):
        raise AssertionError("a world turn's path was taken")

    monkeypatch.setattr(default_scene, "_run_world_turn", no_world_turn)
    registry.activate(slug)
    try:
        stub = _story_stub()
        scene, app = default_scene.create_app(testing=True, llm_fn=stub)
        http = app.test_client()
        opened = http.post("/api/game/new", json={"seed": 7})
        assert opened.status_code == 200, opened.get_data(as_text=True)
        body = opened.get_json()
        session = scene.store.require(body["session_id"])
        assert session.narration_turnstile is None
        choice = body["opening"]["choices"][0]
        before = set(sys.modules)
        turn = http.post("/api/game/choice", json={"session_id": body["session_id"], "choice_id": choice["id"]})
        added = sorted(_social_names(set(sys.modules) - before))
    finally:
        registry.deactivate()
    assert turn.status_code == 200, turn.get_data(as_text=True)
    assert turn.get_json()["narration"] and stub.calls
    assert "Put the phone down first." not in turn.get_data(as_text=True)
    assert added == [], added


@pytest.mark.parametrize("slug", SIX)
def test_run_turns_scene_hook_is_read_receipts_alone(slug: str, monkeypatch) -> None:
    """Pin 10 (v0.23.0 T13, pre-flight F30): `run_turn`'s post-turn `scene.archive_turn` hook is gated on
    `social.declared()`. A narrated turn of each other story leaves `sys.modules` with no `engine.social.scene`
    it did not already hold (the pin-9 snapshot) and, with the module held and its hook armed to fail, never
    calls it."""
    from engine.games import registry
    from engine.scenes import default_scene

    def turn_of(story: str) -> tuple[Any, set[str]]:
        registry.activate(story)
        try:
            stub = _story_stub()
            scene, app = default_scene.create_app(testing=True, llm_fn=stub)
            http = app.test_client()
            body = http.post("/api/game/new", json={"seed": 7}).get_json()
            before = set(sys.modules)
            done = http.post("/api/game/choice", json={"session_id": body["session_id"],
                                                       "choice_id": body["opening"]["choices"][0]["id"]})
            return done, set(sys.modules) - before
        finally:
            registry.deactivate()

    held = "engine.social.scene" in sys.modules
    turn, added = turn_of(slug)
    assert turn.status_code == 200, turn.get_data(as_text=True)
    assert held or "engine.social.scene" not in added, sorted(added)
    import engine.social.scene as social_scene

    def armed(*_a, **_k):
        raise AssertionError("run_turn's scene hook ran for a story without paths.social")

    monkeypatch.setattr(social_scene, "archive_turn", armed)
    again, _added = turn_of(slug)
    assert again.status_code == 200, again.get_data(as_text=True)


def test_the_phone_up_refusal_is_read_receipts_alone(receipts_active) -> None:
    """Pin 6, the other half: the refusal is answered only where `paths.social` is declared."""
    from engine.scenes.default_scene import _phone_was_up
    from engine.social.world import PHONE_UP_REFUSAL

    assert _phone_was_up(PHONE_UP_REFUSAL) is True


@pytest.mark.parametrize("slug", SIX)
def test_the_phone_up_refusal_is_never_another_storys(slug: str) -> None:
    from engine.games import registry
    from engine.scenes.default_scene import _phone_was_up

    registry.activate(slug)
    try:
        assert _phone_was_up("Put the phone down first.") is False
    finally:
        registry.deactivate()


@pytest.mark.parametrize("slug", SIX)
def test_the_director_is_unchanged_for_every_other_story(slug: str) -> None:
    """§19.5 pin 8: ensure_scene deals exactly as before, and engine.social's submodules are never imported."""
    import sys

    from engine.content import director
    from engine.games import registry
    from engine.game import procgen

    registry.activate(slug)
    try:
        before = set(sys.modules)
        state = procgen.new_game_state(seed=5)
        first = director.ensure_scene(state)
        added = {n for n in set(sys.modules) - before if n.startswith("engine.social.")}
        assert not added
        state2 = procgen.new_game_state(seed=5)
        assert director.ensure_scene(state2) == first
    finally:
        registry.deactivate()


@pytest.mark.parametrize("slug", SIX)
def test_a_typed_turn_carries_no_intent_for_every_other_story(slug: str, monkeypatch) -> None:
    """A4 pin 10 (v0.23.0 T23E): typed text is `{}` at the route; `engine.social.typed` is never imported;
    run_guarded's `typed_text` is unread outside the phone story's branch. In process: `resolve_player_intent`
    answers `{}` for a typed line; then a typed turn through `/api/game/choice` reaches `run_turn` with no intent,
    never takes the world turn's path, and adds no `engine.social` submodule to `sys.modules`."""
    from types import SimpleNamespace

    from engine.games import registry
    from engine.scenes import default_scene, default_state

    def no_world_turn(*_a, **_k):
        raise AssertionError("a world turn's path was taken")

    seen: list[Any] = []
    real_run_turn = default_scene.run_turn

    def recording(session, action, **kwargs):
        seen.append((action, kwargs.get("intent")))
        return real_run_turn(session, action, **kwargs)

    monkeypatch.setattr(default_scene, "_run_world_turn", no_world_turn)
    monkeypatch.setattr(default_scene, "run_turn", recording)
    registry.activate(slug)
    try:
        before = set(sys.modules)
        session = SimpleNamespace(last_turn={"choices": [{"id": "1", "text": "x", "intent": {"action": "travel"}}]})
        assert default_state.resolve_player_intent(session, "custom", "make breakfast") == {}
        stub = _story_stub()
        scene, app = default_scene.create_app(testing=True, llm_fn=stub)
        http = app.test_client()
        body = http.post("/api/game/new", json={"seed": 7}).get_json()
        turn = http.post("/api/game/choice", json={"session_id": body["session_id"], "choice_id": "custom",
                                                   "custom_text": "make breakfast"})
        added = sorted(_social_names(set(sys.modules) - before))
    finally:
        registry.deactivate()
    assert turn.status_code == 200, turn.get_data(as_text=True)
    assert seen == [("make breakfast", {})], seen
    assert not any(r.get("typed") or r.get("typed_line") for r in turn.get_json().get("tool_receipts") or [])
    assert added == [], added

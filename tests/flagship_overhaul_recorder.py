"""
What v0.24.0 looked like, for v0.25.0's byte-identity and save tests
(spec §11.3, §12.4, §12.5; plan T0).

Recorded ONCE, by plan T0, from a git worktree at 3c6882f (the v0.24.0
commit): ``tests/test_flagship_overhaul_isolation.py`` writes ``FIXTURE``
when ``CLOCKWORK_FLAGSHIP_RECORD=1``. Every reader here is a pure function
of a fresh state, so the SAME code reads the v0.25.0 tree and a comparison
is exact. Digests, not payloads: a sha256 of canonical JSON.

Version: v0.1.0 [2026-10-27]
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "flagship_overhaul" / "v0240.json"
FLAGSHIP = "clockwork-dark"
OTHER_SIX = ("hue-and-cry", "neon-city", "wicked-garden", "the-long-con", "dev-story", "read-receipts")
SEVEN = (FLAGSHIP, *OTHER_SIX)
#: The flagship's LM Studio golden builds its states at these seeds (tests/llm_golden.py).
FLAGSHIP_GOLDEN_SEEDS = (5, 7)
OPENING_SEED = 1234
RUN_SEED = 7
RUN_TURNS = 20
#: The stories whose 20-turn stub run is recorded. READ RECEIPTS keeps its own
#: turn-cost and digest pins (spec §11.3).
RUN_STORIES = (FLAGSHIP, "hue-and-cry", "neon-city", "wicked-garden", "the-long-con", "dev-story")
#: The two stories that declare the three legacy wall-clock slots (spec §6.1).
LEGACY_SLOT_STORIES = ("wicked-garden", "dev-story")
LEGACY_STREAMS = ("schedule.caravan", "schedule.tinker", "schedule.militia")
LEGACY_SLOT_IDS = ("caravan_arrival", "tinker_camp", "militia_press")
LEGACY_TICKS = 120
#: The trees a recording reads: a change in either makes the recording not v0.24.0's.
RECORDED_TREES = ("engine", "games")
_REPO = Path(__file__).resolve().parents[1]


def dirty_recorded_paths(porcelain: str) -> list[str]:
    """The paths under ``RECORDED_TREES`` a ``git status --porcelain`` listing names."""
    out: list[str] = []
    for line in porcelain.splitlines():
        path = line[3:].strip().strip('"').replace("\\", "/")
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.split("/", 1)[0] in RECORDED_TREES:
            out.append(path)
    return out


def refuse_a_dirty_tree(status: Any = None) -> None:
    """
    ``CLOCKWORK_FLAGSHIP_RECORD=1`` re-records from whatever tree it runs in, and every
    byte-identity test then passes against that tree (T14 review, d6). So it refuses a tree whose
    ``engine/`` or ``games/`` carries uncommitted changes: the recording is meaningful only from a
    clean v0.24.0 worktree (3c6882f, plan T0). ``status`` returns the porcelain text (a test's fake).
    """
    if status is None:
        import subprocess

        def status() -> str:
            return subprocess.run(
                ["git", "status", "--porcelain", "--", *RECORDED_TREES],
                cwd=_REPO, capture_output=True, text=True, check=True,
            ).stdout

    dirty = dirty_recorded_paths(status())
    if dirty:
        pytest.fail(
            "CLOCKWORK_FLAGSHIP_RECORD=1 refuses to record from a dirty tree: "
            f"{', '.join(dirty[:8])}{' ...' if len(dirty) > 8 else ''} carry uncommitted changes. "
            "Record from a clean git worktree at 3c6882f (v0.24.0, plan T0).",
            pytrace=False,
        )
#: Save keys that differ between two runs of one seed (wall clock, minted ids).
#: Step 4 records twice and adds any key that differed, with a comment saying why.
#: Plan T0's two recordings differed in exactly these two (the saves' fixtures
#: drop them too, tests/test_clockwork_dark_saves.py); nothing else moved.
VOLATILE = frozenset({"session_id", "last_sim_tick_at"})

#: Long enough for the turn schema's narration minimum, and story-neutral
#: (the same words tests/test_social_seam.py stubs every story with).
NARRATION = (
    "The moment holds. Nothing in the room moves that you did not move yourself, and the air "
    "carries the small sounds of a place going on without you: a door somewhere, a voice "
    "further off, the light changing by a degree. You take it in and decide what comes next."
)


def sha(value: Any) -> str:
    """sha256 of canonical JSON (sorted keys; anything else by ``str``)."""
    blob = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@contextmanager
def active(slug: str) -> Iterator[None]:
    """
    Activate a story for the duration; READ RECEIPTS quietened as its own tests do.

    The lore index is held EMPTY throughout (``_no_lore``), for every story and
    every reader here: T0 recorded in a fresh worktree, which has no gitignored
    ``lore.db``, and a checkout that has one adds a LORE CONTEXT block to every
    storyteller prompt, so a digest would follow the checkout, not the code.
    """
    from engine.games import registry

    with _no_lore():
        registry.activate(slug)
        try:
            if slug == "read-receipts":
                from engine import social
                from tests.social_fixtures import _quieted, _stop_dirty_saver

                with _quieted():
                    social.boot()
                    try:
                        yield
                    finally:
                        _stop_dirty_saver()
            else:
                yield
        finally:
            registry.deactivate()


@contextmanager
def _no_lore() -> Iterator[None]:
    """
    Every lore reader sees an empty in-memory index. Patched at the source
    (``engine.lore.manager._default_db_path``), so the storyteller's
    ``_lore_block`` and ``engine/lore/interceptors.py``'s interceptors, which
    both build through ``get_lore_manager()``, are covered alike; the singleton
    is dropped on the way in and out, so neither a file-backed manager built
    before nor the empty one built here outlives the hold.
    """
    from engine.lore import manager

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(manager, "_default_db_path", lambda: manager.MEMORY_DB)
        manager._manager = None
        try:
            yield
        finally:
            manager._manager = None


def catalogue(state: Any) -> dict[str, str]:
    """``legal_intents`` and the rendered turn schema, digested."""
    from engine.game import intents
    from engine.llm.schemas import storyteller_turn_schema

    verbs = intents.legal_intents(state)
    return {"intents": sha(repr(verbs)), "schema": sha(storyteller_turn_schema(intents=verbs))}


def openings(slug: str, seeds: tuple[int, ...]) -> dict[str, dict[str, str]]:
    """The catalogue at a new game's opening, per seed."""
    from engine.game import procgen

    with active(slug):
        return {
            str(seed): catalogue(procgen.new_game_state(player_name="Ash", seed=seed))
            for seed in seeds
        }


def bound_beats(slug: str) -> dict[str, str]:
    """Every shipped card's bound beats (``deck.bound_beats`` via ``load_deck``), digested."""
    from engine.content import deck as deck_module

    out: dict[str, str] = {}
    with active(slug):
        for deck_id in deck_module.deck_ids():
            deck = deck_module.load_deck(deck_id)
            for card in (deck.cards if deck is not None else []):
                out[f"{deck_id}/{card.id}"] = sha(card.beats)
    return out


def _stub() -> Any:
    """An ``llm_fn`` for any story's storyteller; records each storyteller request's digest."""
    from engine.agents.prompts import storyteller_persona

    prompts: list[str] = []

    def fake(messages: list[dict[str, Any]], **_: Any) -> str:
        persona = storyteller_persona().strip().splitlines()[0]
        if not any(persona in str(m.get("content", "")) for m in messages):
            return "Nothing is said, at length."
        prompts.append(sha(messages))
        return json.dumps({"narration": NARRATION, "choices": [
            {"id": "a", "text": "Go on"}, {"id": "b", "text": "Stand a while and look"}]})

    fake.prompts = prompts  # type: ignore[attr-defined]
    return fake


def stub_run(slug: str) -> dict[str, Any]:
    """
    Twenty narrated turns through ``/api/game/choice`` with a stub narrator,
    the background tick held at zero (it is wall-clock, R-03): each turn's
    catalogue, each storyteller prompt's digest, and the final save's digest.
    """
    from engine.scenes import default_scene, default_state

    fake = _stub()
    catalogues: list[dict[str, str]] = []
    with pytest.MonkeyPatch.context() as patch, active(slug):
        patch.setattr(default_state, "_background_tick", lambda state: 0.0)
        scene, app = default_scene.create_app(testing=True, llm_fn=fake)
        http = app.test_client()
        body = http.post("/api/game/new", json={"seed": RUN_SEED}).get_json()
        session_id = body["session_id"]
        session = scene.store.require(session_id)
        choice = body["opening"]["choices"][0]["id"]
        for _ in range(RUN_TURNS):
            catalogues.append(catalogue(session.engine.state))
            turn = http.post("/api/game/choice",
                             json={"session_id": session_id, "choice_id": choice}).get_json()
            choice = ((turn or {}).get("choices") or [{"id": "a"}])[0]["id"]
        save = {k: v for k, v in session.engine.state.to_save_dict().items() if k not in VOLATILE}
    return {"catalogues": catalogues, "prompts": list(fake.prompts), "save": sha(save)}


def legacy_rolls(slug: str) -> dict[str, Any]:
    """The three legacy slots, unforced over 120 two-hour ticks and forced once."""
    from engine.game.procgen import new_game_state
    from engine.world.world_sim import WorldSim

    with active(slug):
        state = new_game_state(seed=3)
        emitted: list[list[Any]] = []
        for _ in range(LEGACY_TICKS):
            emitted += [[e.event_id, e.day, e.expires_day] for e in WorldSim.on_tick(state, hours=2.0)]
        counters = {s: int(state.rng_counters.get(s, 0)) for s in LEGACY_STREAMS}
        forced_state = new_game_state(seed=3)
        forced = [[e.event_id, e.day, e.expires_day]
                  for e in WorldSim.on_tick(forced_state, hours=2.0, force=list(LEGACY_SLOT_IDS))]
    return {"emitted": emitted, "counters": counters, "forced": forced}


def hue_endings() -> str:
    """HUE & CRY's endings payload block at a new game (spec §11.3, its {when, ending} terminal)."""
    from engine.game import endings
    from engine.game.procgen import new_game_state

    with active("hue-and-cry"):
        return sha(endings.to_client(new_game_state(seed=11, location_id="tallow_docks")))


def record_all() -> dict[str, Any]:
    """Everything above, for every story it applies to."""
    return {
        "openings": {slug: openings(slug, (OPENING_SEED,)) for slug in SEVEN},
        "flagship_golden": openings(FLAGSHIP, FLAGSHIP_GOLDEN_SEEDS),
        "beats": {slug: bound_beats(slug) for slug in OTHER_SIX},
        "runs": {slug: stub_run(slug) for slug in RUN_STORIES},
        "legacy": {slug: legacy_rolls(slug) for slug in LEGACY_SLOT_STORIES},
        "hue_endings": hue_endings(),
    }

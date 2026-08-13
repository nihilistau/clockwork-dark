"""
The deck-story walker and the ``--game`` dispatch in scripts/simulate.py.

Two stories are walked, on purpose:

    the deck TEMPLATE   scaffolded fresh by scripts/new_story.py into a temp
                        games root (the ``story_root`` seam from
                        tests/test_new_story.py), because the template is the
                        first thing a new author simulates and it must come
                        out of the box with every ending reachable.
    wicked-garden       the shipped deck story -- 124 authored cards, 23
                        endings, four clocks -- because the walker's whole
                        reason to exist is coverage claims about real content.

THE LOADER-ROOT SEAM. The structural loaders (decks, clocks, threads, endings,
epilogues) resolve their config paths against the REPO root via a module-level
``_ROOT`` -- which is exactly right in production and wrong for a story
scaffolded into a temp directory. Each of those five constants is monkeypatched
to the temp root here, which is the narrowest possible redirection: the loaders
themselves, the predicate grammar and the effect dispatcher all run unpatched.

Budgets are deliberately small (a handful of runs, a short day budget): this
file proves the walker works and is deterministic, not that the Garden is
balanced. The 200-run coverage numbers belong to the CLI.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

from engine.games import registry

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def _load_script(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registered BEFORE exec: @dataclass resolves string annotations through
    # sys.modules[cls.__module__], which must exist while the module body runs.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


simulate_decks = _load_script("simulate_decks")
new_story = _load_script("new_story")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def garden():
    """The shipped deck story, active, and put back afterwards."""
    registry.activate("wicked-garden")
    try:
        yield
    finally:
        registry.deactivate()


@pytest.fixture
def template_story(tmp_path, monkeypatch):
    """
    A freshly scaffolded deck-template story, discoverable AND loadable.

    The registry seam is tests/test_new_story.py's; the loader-root seam is
    this file's own (see the module docstring).
    """
    (tmp_path / "games").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("engine.games.manifest.project_root", lambda: tmp_path)
    monkeypatch.setattr("engine.games.registry.project_root", lambda: tmp_path)
    for module in (
        "engine.content.deck",
        "engine.game.clocks",
        "engine.game.threads",
        "engine.game.endings",
        "engine.game.epilogue",
    ):
        monkeypatch.setattr(f"{module}._ROOT", tmp_path)

    new_story.scaffold("probe-deck", template="deck", games_root=tmp_path / "games")
    registry.activate("probe-deck")
    try:
        yield
    finally:
        registry.deactivate()


REPORT_KEYS = {
    "config",
    "days",
    "steps",
    "passes",
    "endings",
    "epilogues",
    "clocks",
    "threads",
    "cards",
    "orphans",
    "forced_scenes",
    "meters",
    "errors",
    "error_count",
    "acceptance",
}


# ---------------------------------------------------------------------------
# the template: the authoring loop's day-one story
# ---------------------------------------------------------------------------


def test_the_template_walk_produces_the_full_report_shape(template_story):
    report = simulate_decks.simulate_deck_story(runs=4, seed=7, max_days=10)
    assert set(report) == REPORT_KEYS
    assert report["config"]["game"] == "probe-deck"
    assert report["config"]["decks"] == ["day_one"]
    assert report["config"]["fail_forward"] == "the_long_stay"
    # Every run locks something and gets its cards: the template's promise.
    assert sum(report["endings"]["locked"].values()) == 4
    assert report["epilogues"]["rendered_runs"] == 4
    assert report["error_count"] == 0, report["errors"]


def test_every_template_ending_is_reachable_within_the_default_budget(template_story):
    """
    The acceptance metric the template must pass on day one: a scaffold whose
    gated ending cannot be reached teaches every new author that a dead card
    is normal, which is the one lesson a template must never teach.
    """
    report = simulate_decks.simulate_deck_story(runs=12, seed=3, max_days=20)
    assert report["endings"]["unreachable"] == [], (
        f"template endings never reachable: {report['endings']['unreachable']}"
    )
    # And the walk actually travelled: the gated ending needs favor the deck
    # only pays out over repeated chapters, so passes must be > 1 somewhere.
    assert report["passes"]["max"] > 1


def test_the_template_clock_can_go_unfired_without_crashing(template_story):
    """
    A one-run walk in which the suspicion clock may never cross a threshold
    -- the 'clocks that never fire' case the report must survive, reporting
    a rate rather than raising.
    """
    report = simulate_decks.simulate_deck_story(runs=1, seed=11, max_days=4)
    assert "suspicion" in report["clocks"]
    for row in report["clocks"]["suspicion"]["beats"].values():
        assert 0.0 <= row["fire_rate"] <= 1.0
    assert report["error_count"] == 0, report["errors"]


# ---------------------------------------------------------------------------
# the shipped deck story
# ---------------------------------------------------------------------------


def test_the_garden_walks_clean_and_reports_its_declared_universe(garden):
    report = simulate_decks.simulate_deck_story(runs=5, seed=42)
    assert report["error_count"] == 0, report["errors"]
    # The declared universe, read back through the real loaders.
    assert report["config"]["declared_endings"] == 23
    assert len(report["config"]["decks"]) == 11
    # One pass of ten chapters plus the chamber deck: the finale locks.
    assert report["days"]["max"] <= 13
    assert sum(report["endings"]["locked"].values()) == 5
    assert report["epilogues"]["rendered_runs"] == 5
    assert report["epilogues"]["endings_without_row"] == []
    # Agent-wound clocks are the walker's declared blind spot: they must be
    # REPORTED (with whatever rate the walk earned), never omitted or crashed.
    assert {"ashen_pressure", "briar_hunger", "mortal_collapse", "sophia_break"} <= set(
        report["clocks"]
    )
    # The finale deck sorts before the labyrinth chambers, and the lock ends
    # the run -- the walker must still deal the chamber deck rather than
    # reporting nine phantom orphans.
    assert report["cards"]["thorn_labyrinth"]["dealt"], (
        "the labyrinth deck was never walked"
    )


def test_the_same_seed_replays_to_the_same_json(garden):
    """Determinism is the whole warrant for acting on the walker's numbers."""
    first = simulate_decks.simulate_deck_story(runs=3, seed=42)
    second = simulate_decks.simulate_deck_story(runs=3, seed=42)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_a_different_seed_is_a_different_run(garden):
    first = simulate_decks.simulate_deck_story(runs=2, seed=42)
    second = simulate_decks.simulate_deck_story(runs=2, seed=1042)
    assert json.dumps(first, sort_keys=True) != json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# the dispatcher
# ---------------------------------------------------------------------------


def test_simulate_py_dispatches_deck_stories_to_the_walker(capsys):
    simulate = _load_script("simulate")
    try:
        code = simulate.main(
            ["--game", "wicked-garden", "--runs", "2", "--seed", "5", "--json"]
        )
    finally:
        registry.deactivate()
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["config"]["game"] == "wicked-garden"
    assert report["config"]["runs"] == 2


def test_simulate_py_refuses_a_graph_story_it_cannot_play(capsys):
    """
    dev-story declares quests, so it is graph-shaped -- and the policies walk
    Edgewood ids it does not have. The refusal must say whose fault that is.
    """
    simulate = _load_script("simulate")
    try:
        with pytest.raises(SystemExit) as excinfo:
            simulate.main(["--game", "dev-story", "--turns", "1"])
    finally:
        registry.deactivate()
    assert excinfo.value.code == 2
    assert "flagship-owned" in capsys.readouterr().err


def test_shape_detection_reads_the_manifests_not_the_slugs():
    simulate = _load_script("simulate")
    assert simulate.story_shape(registry.get("clockwork-dark")) == "graph"
    assert simulate.story_shape(registry.get("wicked-garden")) == "deck"
    assert simulate.story_shape(registry.get("dev-story")) == "graph"

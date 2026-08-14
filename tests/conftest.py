"""Pytest fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.game.engine import GameEngine, set_active_engine
from engine.game.state import GameState


@pytest.fixture
def game_state() -> GameState:
    """Fresh game state."""
    return GameState()


@pytest.fixture
def story_declaring_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """
    Activate a story on disk that declares no optional content paths at all.

    THE ABSENCE HAS TO BE BUILT, NOT BORROWED. Several tests assert that an
    undeclared ``paths.*`` key makes its system inert, and they used to read
    that claim off The Clockwork Dark because the flagship happened to declare
    no clocks, threads, endings, decks or epilogues. "The flagship declares
    none" and "an undeclared path is inert" are different statements -- only
    the second is about the engine -- and the difference stopped being
    academic the day the flagship shipped a finale: three tests failed that
    were never testing the flagship's content in the first place.

    An empty config overlay is NOT enough to build this. ``paths.*`` falls
    back to the ACTIVE MANIFEST when the config layers hold nothing
    (``engine/config.py::_story_path``), which is the whole point of the
    engine/story seam -- so the only way to have a story that declares nothing
    is to activate one.

    Yields the temp slug. ``games_root`` is redirected at the temp directory,
    so discovery finds this story and nothing else, and a leaked activation
    cannot reach the real ``games/``.
    """
    from engine.games import registry

    slug = "declares-nothing"
    directory = tmp_path / "games" / slug
    directory.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "id": slug,
        "title": "A Story That Declares Nothing",
        # Not one optional content path. `saves` is an engine OUTPUT rather
        # than story content and every story shares it, so it is the only key
        # here -- and it is checked on its parent, not for existence.
        "paths": {"saves": "data/saves"},
        "entry": {"location_id": "nowhere", "archetypes": []},
    }
    directory.joinpath("game.yaml").write_text(
        yaml.safe_dump(manifest), encoding="utf-8"
    )
    monkeypatch.setattr(registry, "games_root", lambda: tmp_path / "games")
    registry.activate(slug)
    try:
        yield slug
    finally:
        # Back to "no story activated", which is the state a fresh process
        # starts in: `resolve_slug()` then answers from config as it always did.
        registry.deactivate()


@pytest.fixture
def engine(game_state: GameState) -> GameEngine:
    """Game engine with active context bound."""
    eng = GameEngine(game_state)
    set_active_engine(eng)
    return eng
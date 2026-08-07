"""Lore RAG ingest and retrieval tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.lore.interceptors import LoreInjectInterceptor
from engine.lore.manager import LoreManager, chunk_markdown, reset_lore_manager
from engine.game.state import GameState

_LORE_SAMPLE = """
# Test Lore

## Edgewood Bakery
Maris Hearth runs the Hearth Bakery with flour on her sleeves and a hum in her throat.

## Forest Clearing
The birch clearing at the forest edge holds mist and distant hearth smoke from Edgewood village.
"""


@pytest.fixture
def lore_db(tmp_path: Path) -> LoreManager:
    db = tmp_path / "test_lore.db"
    return reset_lore_manager(db_path=db)


def test_chunk_markdown_splits_sections():
    chunks = chunk_markdown(_LORE_SAMPLE, "sample.md")
    assert len(chunks) >= 2
    titles = [c[0] for c in chunks]
    assert any("Bakery" in t for t in titles)


def test_ingest_and_count(lore_db: LoreManager):
    added = lore_db.ingest_text(_LORE_SAMPLE, source="sample.md")
    assert added >= 2
    assert lore_db.count() == added


def test_search_returns_relevant_chunk(lore_db: LoreManager):
    lore_db.ingest_text(_LORE_SAMPLE, source="sample.md")
    hits = lore_db.search("Maris bakery edgewood", limit=2)
    assert hits
    assert any("Maris" in h.text for h in hits)


def test_ingest_directory(lore_db: LoreManager):
    root = Path(__file__).resolve().parents[1]
    lore_dir = root / "data" / "lore"
    count = lore_db.ingest_directory(lore_dir)
    assert count >= 3
    hits = lore_db.search("forest clearing birch", limit=2)
    assert hits


def test_lore_inject_noop_when_empty():
    interceptor = LoreInjectInterceptor(manager=LoreManager(db_path=Path("/tmp/empty_lore_x.db")))
    interceptor.manager.clear()
    state = GameState()
    prompt = "Base system prompt."
    assert interceptor.run_pre(state, prompt) == prompt


def test_lore_inject_adds_chunks(lore_db: LoreManager):
    lore_db.ingest_text(_LORE_SAMPLE, source="sample.md")
    interceptor = LoreInjectInterceptor(manager=lore_db)
    state = GameState(location_id="edgewood_bakery")
    result = interceptor.run_pre(
        state,
        "SYSTEM",
        player_action="visit the bakery",
    )
    assert "LORE CONTEXT" in result
    assert "Maris" in result
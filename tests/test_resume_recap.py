"""
The resume recap -- "PREVIOUSLY" -- as a returning player reads it.

THE BUG. Every resumed game opened on a recap like::

    PREVIOUSLY On day 1 at tallow_docks, Somewhere up the quay a bell counts
    the hour, ... On day 1 at tallow_docks, Somewhere up the quay a bell
    counts the hour, ... [once per evicted turn] ... You left off on day 1, at
    The Lantern House.

The recap shows the ledger's running summary, and with no summarizer model
(the deterministic fallback, ``engine/memory/summarizer.py``) that summary was
built as one "On day N at <location_id>, <first sentence>." per evicted turn:
the RAW location id reached the prose, and a turn whose narration opened on
the same ambient line as the last (every fallback turn does) added the same
entry again. Nothing capped the entries but a 250-word slice.

These play real turns, for every shipped story, through the app with a
scripted model that answers every turn with the story's own fallback
narration (as ``scripts/screenshot_runs.py`` does), save, resume through
``/api/saves/<id>/load``, and read the frame the resumed run lands in.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.memory.ledger import StoryLedger, TurnRecord
from engine.memory.summarizer import _fallback_summary

STORIES = ("clockwork-dark", "wicked-garden", "neon-city", "the-long-con", "hue-and-cry", "dev-story")
#: Enough turns to evict several from the six-turn buffer.
TURNS = 12
#: The scripted model's second line, between the story's fallback narrations.
OTHER_LINE = "The hour turns over, and you turn with it."


def _first_sentence(text: str) -> str:
    return text.strip().split(".")[0].strip()


@pytest.fixture
def saves_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    from engine.persistence import saves

    base = tmp_path / "saves"
    base.mkdir()
    monkeypatch.setattr(saves, "saves_base", lambda: base)
    saves.reset_save_store()
    yield base
    saves.reset_save_store()


def _resumed_recap(story: str) -> tuple[str, str, dict[str, Any]]:
    """Play TURNS turns of ``story``, save, resume; return (recap, ambient, graph)."""
    from engine.game.locations import LOCATIONS
    from engine.games import registry
    from engine.scenes.default_scene import create_app, reset_store

    manifest = registry.activate(story)
    ambient = manifest.fallback_narration or "The world waits. Nothing moves."

    turns = iter(range(10_000))

    def model(*_args: Any, **_kwargs: Any) -> str:
        # Two lines in turn: the recap leaves out an entry that repeats the
        # narration shown under it (`tidy_summary(shown=)`), so a run that
        # said ONE thing every turn would rightly have nothing to recap.
        line = ambient if next(turns) % 2 else OTHER_LINE
        return json.dumps({"narration": line, "choices": [{"id": "a", "text": "Look about you"}]})

    reset_store()
    try:
        scene, app = create_app(testing=True, llm_fn=model)
        client = app.test_client()
        started = client.post("/api/game/new", json={"seed": 1021, "player_name": "Wren"}).get_json()
        session_id = started["session_id"]
        last = started.get("opening") or {}
        for _ in range(TURNS):
            choices = last.get("choices") or [{"id": "a"}]
            answer = client.post(
                "/api/game/choice", json={"session_id": session_id, "choice_id": choices[-1]["id"]}
            )
            assert answer.status_code == 200, answer.get_data(as_text=True)
            last = answer.get_json()
        saved = client.post("/api/saves", json={"session_id": session_id, "save_id": started["save_id"]})
        assert saved.status_code == 200, saved.get_data(as_text=True)
        loaded = client.post(f"/api/saves/{started['save_id']}/load")
        assert loaded.status_code == 200, loaded.get_data(as_text=True)
        resumed = scene.store._sessions[loaded.get_json()["session_id"]]
        narration = str(resumed.last_turn.get("narration") or "")
        assert narration.startswith("PREVIOUSLY"), f"{story}: no recap after {TURNS} turns:\n{narration}"
        recap = narration.split("\n\n", 1)[0]
        return recap, ambient, dict(LOCATIONS)
    finally:
        reset_store()


@pytest.mark.parametrize("story", STORIES)
def test_the_recap_names_places_not_ids(story: str, saves_in_tmp: Path) -> None:
    recap, _ambient, graph = _resumed_recap(story)
    leaked = [
        loc_id
        for loc_id, row in graph.items()
        if "_" in loc_id and str(row.get("name") or "") != loc_id and re.search(rf"\b{re.escape(loc_id)}\b", recap)
    ]
    assert not leaked, f"{story}: raw location ids in the recap {leaked}:\n{recap}"


@pytest.mark.parametrize("story", STORIES)
def test_the_recap_says_each_thing_once(story: str, saves_in_tmp: Path) -> None:
    recap, ambient, _graph = _resumed_recap(story)
    sentence = _first_sentence(ambient)
    assert recap.count(sentence) <= 1, f"{story}: the same line {recap.count(sentence)} times:\n{recap}"


@pytest.mark.parametrize("story", STORIES)
def test_the_recap_heading_is_punctuated(story: str, saves_in_tmp: Path) -> None:
    """
    The client renders narration in one paragraph and collapses newlines, so
    "PREVIOUSLY\\nOn day 1..." read "PREVIOUSLY On day 1...". The heading
    carries its own punctuation, and each entry starts a sentence.
    """
    recap, _ambient, _graph = _resumed_recap(story)
    collapsed = " ".join(recap.split())
    assert collapsed.startswith("PREVIOUSLY: "), collapsed
    # An entry reads "On day N, at <Place>: <Sentence>." -- never a capital
    # straight after a comma, which is how the old entry joined its parts.
    assert not re.search(r"On day \d+ at [^,:]+, [A-Z]", collapsed), collapsed


# ---------------------------------------------------------------------------
# the fallback summary itself
# ---------------------------------------------------------------------------


def _record(turn: int, narration: str, location_id: str = "edgewood_square", day: int = 1) -> TurnRecord:
    return TurnRecord(turn=turn, day=day, location_id=location_id, player_action="wait", narration=narration)


def test_identical_turns_leave_one_entry() -> None:
    from engine.games import registry

    registry.activate("clockwork-dark")
    summary = ""
    for turn in range(1, 9):
        summary = _fallback_summary(summary, [_record(turn, "A bell counts the hour. Nothing else.")])
    assert summary.count("A bell counts the hour") == 1, summary
    assert "edgewood_square" not in summary
    assert "Edgewood Square" in summary


def test_entries_are_capped_to_the_most_recent() -> None:
    from engine.games import registry
    from engine.memory import summarizer

    cap = getattr(summarizer, "MAX_RECAP_ENTRIES", 6)

    registry.activate("clockwork-dark")
    summary = ""
    for turn in range(1, 20):
        summary = _fallback_summary(summary, [_record(turn, f"Event number {turn} happens. More.")])
    assert summary.count("On day") == cap, summary
    assert "Event number 19 happens" in summary
    assert "Event number 1 happens" not in summary


def test_a_legacy_summary_is_cleaned_on_its_next_fold() -> None:
    """A save written before the fix carries the old noise; the next eviction repairs it."""
    from engine.games import registry

    registry.activate("clockwork-dark")
    legacy = " ".join(["On day 1 at edgewood_square, A bell counts the hour."] * 5)
    summary = _fallback_summary(legacy, [_record(9, "The baker waves. Bread.", location_id="edgewood_bakery", day=2)])
    assert summary.count("A bell counts the hour") == 1, summary
    assert "edgewood_" not in summary, summary
    assert "The baker waves" in summary


def test_model_prose_before_the_entries_is_kept() -> None:
    from engine.games import registry

    registry.activate("clockwork-dark")
    prose = "The traveller reached Edgewood and owes Maris a favour."
    summary = _fallback_summary(prose, [_record(7, "Rain. More rain.")])
    assert summary.startswith(prose)
    assert "Rain." in summary


# ---------------------------------------------------------------------------
# fix round 1: model prose is never read as an entry
# ---------------------------------------------------------------------------

#: Model-written summaries that merely SAY "on day N at <time>, ...": none
#: names a place of the story, so none is an entry.
MODEL_PROSE = (
    "On day 2 at dawn, the knight rode out. Later On day 3 at noon, he fell.",
    "On day 3, at the old mill, he said: go. Then nothing.",
    "On day 5 at Rome, the traveller paid Maris back.",
)


@pytest.mark.parametrize("prose", MODEL_PROSE)
def test_tidy_leaves_model_prose_byte_unchanged(prose: str) -> None:
    from engine.games import registry
    from engine.memory.summarizer import tidy_summary

    registry.activate("clockwork-dark")
    assert tidy_summary(prose) == prose


@pytest.mark.parametrize("prose", MODEL_PROSE)
def test_a_later_fold_leaves_model_prose_byte_unchanged(prose: str) -> None:
    from engine.games import registry

    registry.activate("clockwork-dark")
    once = _fallback_summary(prose, [_record(7, "Rain on the square. More.")])
    assert once.startswith(prose + " On day 1, at "), once
    twice = _fallback_summary(once, [_record(8, "The baker waves. Bread.", location_id="edgewood_bakery")])
    assert twice.startswith(prose + " On day 1, at "), twice
    assert "Rain on the square" in twice and "The baker waves" in twice, twice


def test_a_place_name_holding_a_colon_survives_a_fold(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.game import locations
    from engine.games import registry

    registry.activate("clockwork-dark")
    monkeypatch.setitem(locations.LOCATIONS, "north_gate", {"name": "The Gate: North"})
    once = _fallback_summary("", [_record(1, "Wind. More.", location_id="north_gate")])
    twice = _fallback_summary(once, [_record(2, "Wind. More.", location_id="north_gate", day=2)])
    assert twice == "On day 2, at The Gate: North: Wind.", twice


def test_the_word_cap_drops_whole_entries() -> None:
    from engine.games import registry
    from engine.memory import summarizer

    registry.activate("clockwork-dark")
    long = " ".join(["word"] * 40)
    summary = ""
    for turn in range(1, 9):
        summary = _fallback_summary(summary, [_record(turn, f"Event {turn} {long}. More.")])
    assert len(summary.split()) <= summarizer.MAX_SUMMARY_WORDS
    assert summary.startswith("On day 1, at Edgewood Square: Event "), summary[:80]
    assert "Event 8 " in summary


def test_tidy_displays_an_old_format_save() -> None:
    """A save from before the fix, recapped through _recap at once, before any new fold."""
    from engine.game.state import GameState
    from engine.games import registry
    from engine.memory.summarizer import tidy_summary
    from engine.scenes.default_state import _recap

    registry.activate("clockwork-dark")
    legacy = " ".join(["On day 1 at edgewood_square, A bell counts the hour."] * 4)
    assert tidy_summary(legacy) == "On day 1, at Edgewood Square: A bell counts the hour."
    state = GameState(session_id="old")
    state.location_id = "edgewood_bakery"
    ledger = StoryLedger()
    ledger.summary = legacy
    recap = _recap(state, ledger)
    assert recap.count("A bell counts the hour") == 1, recap
    assert "edgewood_square" not in recap, recap


# ---------------------------------------------------------------------------
# v0.21.0 final fix wave: the recap does not repeat the narration under it,
# and a title's full stop does not end a summary's sentence
# ---------------------------------------------------------------------------


def test_the_recap_leaves_out_the_line_shown_beneath_it() -> None:
    """
    K4: a resumed Wicked Garden run read "On day 1, at The Gate of Briars:
    <line>." and then <line> again as the re-shown narration. An entry the
    narration under it already holds is left out of the recap.
    """
    from engine.game.state import GameState
    from engine.games import registry
    from engine.scenes.default_state import resume_opening

    registry.activate("clockwork-dark")
    line = "A bell counts the hour on the square"
    ledger = StoryLedger()
    ledger.summary = (
        f"On day 1, at Edgewood Square: The baker waves. On day 1, at Edgewood Square: {line}."
    )
    ledger.turn_buffer = [_record(9, f"{line}. Nothing else moves.")]
    state = GameState(session_id="recap")
    state.location_id = "edgewood_square"
    narration = resume_opening(state, ledger)["narration"]
    assert narration.count(line) == 1, narration
    assert narration.startswith("PREVIOUSLY:"), narration
    assert "The baker waves" in narration, narration


def test_a_recap_with_only_the_shown_line_is_left_out() -> None:
    from engine.game.state import GameState
    from engine.games import registry
    from engine.scenes.default_state import _recap

    registry.activate("clockwork-dark")
    ledger = StoryLedger()
    ledger.summary = "On day 1, at Edgewood Square: Rain on the square."
    state = GameState(session_id="recap")
    assert _recap(state, ledger, shown="Rain on the square. More rain.") == ""
    assert "Rain on the square" in _recap(state, ledger, shown="Something else.")


@pytest.mark.parametrize(
    ("narration", "first"),
    [
        ("Dr. Vance waits by the door. He says nothing.", "Dr. Vance waits by the door"),
        ("Mrs. Gannet counts the coin. Then again.", "Mrs. Gannet counts the coin"),
        ("It costs 1.5 crowns. Pay it.", "It costs 1.5 crowns"),
        ("Rain. More rain.", "Rain"),
        ("Who goes there? Nobody.", "Who goes there"),
    ],
)
def test_the_summary_sentence_survives_an_abbreviation(narration: str, first: str) -> None:
    """``split(".")[0]`` cut "Dr. Vance waits..." to "Dr"."""
    from engine.games import registry

    registry.activate("clockwork-dark")
    summary = _fallback_summary("", [_record(1, narration)])
    assert summary == f"On day 1, at Edgewood Square: {first}.", summary

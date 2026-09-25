"""
The Law, part six: the narrator and the player see it.

THE SHAPE. Everything Tasks 1-5 built stays inside the engine until this task:
a wanted band nobody speaks, a witness nobody names, a cell nobody is told
about. ``prompts.law_block`` renders the first three in words -- who saw the
last deed and how clearly, the wanted band for the guise worn here, the
law-role people present, custody if held -- never a score, a precision or an
id. ``evaluator.contradicts`` gains a third opposite: a clean getaway claimed
over a receipt whose result says ``noticed: true``. ``to_client_dict`` gains a
``law`` key for the player's own sheet, omitted whole for a story with no Law.

WHAT THESE TESTS HOLD. The block is "" undeclared; it names the last deed's
hop-1 witnesses by display name and clarity word, only when that deed was
committed THIS turn (every deed updates the stamp, seen or not) and never an older
one; it speaks the wanted band in words and only once it clears the floor
band; it lists the watch standing here by name; it speaks custody as money
and days in words; nothing it prints is a digit except the story's own
currency. The evaluator flags "you slip away
unnoticed" over ``noticed: true`` and does not flag honest caught prose. The
payload carries ``law`` keyed by jurisdiction LABEL, and is entirely absent
for a story that declares none -- the flagship's own shape.

Version: v0.1.0 [2026-09-24]
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.agents import prompts
from engine.agents.evaluator import contradicts
from engine.config import set_overlay
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.state import GameState
from engine.world import law

from test_law import SPEC as LAW_SPEC

SQUARE = "edgewood_square"
ALL_DAY = [{"hours": list(range(24)), "location": SQUARE, "activity": "idling"}]


def _person(npc_id: str, role: str, routine: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": npc_id, "name": npc_id.replace("_", " ").title(), "role": role, "routine": routine}


@pytest.fixture()
def lawful(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "law.yaml"
    import yaml

    path.write_text(yaml.safe_dump(LAW_SPEC), encoding="utf-8")
    set_overlay({"paths": {"law": str(path)}})
    try:
        yield path
    finally:
        set_overlay(None)


def _world(*, seed: int = 42, people: list[dict[str, Any]] | None = None) -> GameState:
    state = GameState(rng_seed=seed, location_id=SQUARE)
    state.procgen = generate_world(seed)
    state.procgen.npcs = people or []
    return state


def _witness(state: GameState, *, deed: str = "fencing", npc: str = "gen_a_mark",
             deed_id: str = "", hop: int = 1, precision: float = 1.0) -> dict[str, Any]:
    return apply_effect(state, {
        "type": "witness", "deed": deed, "guise": "self", "npc": npc,
        "where": SQUARE, "deed_id": deed_id, "hop": hop, "precision": precision,
    })


def _report(state: GameState, *, deed: str = "fencing", precision: float = 1.0,
            deed_id: str = "") -> dict[str, Any]:
    return apply_effect(state, {
        "type": "report", "deed": deed, "guise": "self", "jurisdiction": "village",
        "precision": precision, "deed_id": deed_id,
    })


def _this_turns_deed(state: GameState, row: dict[str, Any]) -> None:
    """Stamp ``row``'s deed as committed this turn -- what ``commit_deed``
    writes for every deed, seen or not."""
    apply_effect(state, {"type": "law_last_deed", "deed_id": row["deed_id"], "where": SQUARE})


_DIGIT = re.compile(r"\d")


# ---------------------------------------------------------------------------
# law_block
# ---------------------------------------------------------------------------


def test_undeclared_story_gets_an_empty_block() -> None:
    """No `paths.law` at all -- the flagship's own shape."""
    state = _world()
    assert prompts.law_block(state) == ""


def test_a_quiet_lawful_story_with_nothing_to_say_gets_an_empty_block(lawful: Path) -> None:
    """Declared, but no deed, no band above the floor, no watch, no custody."""
    state = _world()
    assert prompts.law_block(state) == ""


def test_the_last_deeds_witnesses_are_named_and_clear(lawful: Path) -> None:
    state = _world(people=[_person("gen_a_mark", "vendor", ALL_DAY)])
    _this_turns_deed(state, _witness(state, npc="gen_a_mark"))
    block = prompts.law_block(state)
    assert "Gen A Mark" in block
    assert "clearly" in block
    assert "gen_a_mark" not in block  # display name only, never the id


def test_a_half_seen_witness_reads_as_a_glimpse(lawful: Path) -> None:
    """Hop 1 is always precision 1.0 in production; a lower precision -- the
    shape a told copy or a hand-edited save could carry -- still reads as
    words, never as the number."""
    state = _world(people=[_person("gen_a_mark", "vendor", ALL_DAY)])
    _this_turns_deed(state, _witness(state, npc="gen_a_mark", precision=0.6))
    block = prompts.law_block(state)
    assert "only a glimpse" in block
    assert "0.6" not in block


def test_a_hop_two_copy_is_never_read_as_the_last_deeds_witness(lawful: Path) -> None:
    """Propagation is someone ELSE'S account reaching a third party -- not the
    player being seen -- so a told copy never joins the "you were seen" line,
    even though the deed's own hop-1 witness still does."""
    state = _world(people=[_person("gen_a_mark", "vendor", ALL_DAY)])
    row = _witness(state, npc="gen_a_mark")
    _this_turns_deed(state, row)
    _witness(state, npc="gen_b_teller", deed_id=row["deed_id"], hop=2, precision=0.6)
    block = prompts.law_block(state)
    assert "Gen A Mark" in block
    assert "Gen B Teller" not in block


def test_a_deed_from_an_earlier_turn_says_nothing(lawful: Path) -> None:
    state = _world(people=[_person("gen_a_mark", "vendor", ALL_DAY)])
    _this_turns_deed(state, _witness(state, npc="gen_a_mark"))
    assert "You were seen" in prompts.law_block(state)
    state.turn_number += 1  # the storyteller's counter, after the turn commits
    block = prompts.law_block(state)
    assert "You were seen" not in block


def test_only_the_newest_deed_is_read_as_the_last_one(lawful: Path) -> None:
    state = _world(people=[_person("gen_a_mark", "vendor", ALL_DAY),
                           _person("gen_b_mark", "vendor", ALL_DAY)])
    _witness(state, npc="gen_a_mark")  # d1, older
    _this_turns_deed(state, _witness(state, npc="gen_b_mark"))  # d2, this turn's
    block = prompts.law_block(state)
    assert "Gen B Mark" in block
    assert "Gen A Mark" not in block


def test_the_wanted_band_is_spoken_in_words_never_the_score(lawful: Path) -> None:
    state = _world()
    _report(state, deed="fencing", precision=1.0)  # severity 2 -- clears "noticed" at 2
    block = prompts.law_block(state)
    assert "looking for your own face: noticed" in block
    assert not _DIGIT.search(block)


def test_the_floor_band_is_not_worth_a_line(lawful: Path) -> None:
    """Nobody looking for you is not news the narrator needs every turn."""
    state = _world()
    assert law.wanted_band(state, "self", "village") == "unknown"
    assert "looking for" not in prompts.law_block(state)


def test_law_role_people_present_are_named(lawful: Path) -> None:
    state = _world(people=[_person("gen_a_watch", "watch", ALL_DAY)])
    block = prompts.law_block(state)
    assert "Gen A Watch" in block
    assert "gen_a_watch" not in block


def test_custody_is_money_and_days_in_words(lawful: Path) -> None:
    state = _world()
    state.law["custody"] = {"fine": 12, "days": 2, "since_day": 1, "jurisdiction": "village",
                             "guise": "self", "charged": []}
    block = prompts.law_block(state)
    assert "12g" in block
    assert "two days" in block
    assert "since_day" not in block and "jurisdiction" not in block


def test_wired_into_world_state_block(lawful: Path) -> None:
    """The narrator actually sees it -- not just a function nobody calls."""
    state = _world()
    _report(state, deed="fencing")
    text = prompts.world_state_block(state, {})
    assert "THE LAW" in text
    assert "looking for" in text


def test_flagship_prompt_is_byte_identical_with_no_law() -> None:
    """A story that declares no `paths.law` sees no `THE LAW` block at all."""
    state = _world()
    assert "THE LAW" not in prompts.world_state_block(state, {})


# ---------------------------------------------------------------------------
# evaluator.contradicts
# ---------------------------------------------------------------------------

NOTICED_LIFT = [{"skill": "lift_purse", "success": True, "result": {"noticed": True}}]


@pytest.mark.parametrize(
    "prose",
    [
        "You slip away unnoticed, the purse never missed.",
        "No one notices you slip into the crowd.",
        "You vanish, unseen.",
        "Nobody notices, and you are gone before the bell rings.",
        "And you get away clean, the ring already in your pocket.",
    ],
)
def test_a_clean_getaway_over_noticed_true_is_caught(prose: str) -> None:
    assert contradicts(prose, NOTICED_LIFT)


@pytest.mark.parametrize(
    "prose",
    [
        "The mark's hand closes on your wrist and he shouts for the watch.",
        "She catches you at it and calls out, furious.",
        "You are caught red-handed, the purse still in your fingers.",
        # The three the review found: a bare "unseen"/"unnoticed" used about
        # someone or something OTHER than the player being caught, which the
        # first cut of this regex flagged anyway.
        "The guard stands unseen in the shadows, waiting for his moment.",
        "An owl passes unnoticed overhead as you argue with the merchant.",
        "You are caught red-handed, unnoticed no longer, and the mark shouts.",
        # Two more of the same shape: a third party's stealth, and the
        # player's own arrest scene using the same vocabulary honestly.
        "The cutpurse across the square goes unnoticed as the watch passes.",
        "Your escape plan lay unseen in your coat, useless now the mark has you.",
    ],
)
def test_honest_caught_prose_is_not_flagged(prose: str) -> None:
    """The counter-control. A gate that fires on honest prose gets deleted."""
    assert contradicts(prose, NOTICED_LIFT) == ""


def test_a_clean_getaway_over_an_unnoticed_lift_is_not_a_contradiction() -> None:
    clean = [{"skill": "lift_purse", "success": True, "result": {"noticed": False}}]
    assert contradicts("You slip away unnoticed, coin in hand.", clean) == ""


# ---------------------------------------------------------------------------
# to_client_dict
# ---------------------------------------------------------------------------


def test_payload_omits_law_when_undeclared() -> None:
    state = _world()
    assert "law" not in state.to_client_dict()


def test_payload_ships_law_keyed_by_jurisdiction_label(lawful: Path) -> None:
    state = _world()
    _report(state, deed="fencing")
    payload = state.to_client_dict()["law"]
    assert payload["guise_label"] == "your own face"
    assert payload["wanted"] == {"Village": "noticed", "Town": "unknown"}
    assert payload["custody"] is None


def test_payload_custody_is_fine_fine_text_and_days(lawful: Path) -> None:
    """Both: `fine` meets the plan's own `{fine, days}` contract, and
    `fine_text` saves a client from knowing what a story calls its money."""
    state = _world()
    state.law["custody"] = {"fine": 12, "days": 2}
    custody = state.to_client_dict()["law"]["custody"]
    assert custody == {"fine": 12, "fine_text": "12g", "days": 2}


# ---------------------------------------------------------------------------
# v0.10.0 final fix (I2): "you were seen" means THIS turn's deed
# ---------------------------------------------------------------------------


def test_an_unseen_deed_after_a_seen_one_names_nobody(lawful: Path) -> None:
    """The reviewer's seen.py: a lift in a crowd, then one where nobody is.
    Before the fix the block read the newest WITNESSED deed of the day and
    named the first crowd -- people nowhere near the second lift -- all day."""
    state = _world(people=[_person("gen_a_mark", "vendor", ALL_DAY)])
    law.commit_deed(state, "pickpocket", certain=["gen_a_mark"])
    assert "Gen A Mark" in prompts.law_block(state)
    state.turn_number += 1
    law.commit_deed(state, "pickpocket", location="millhaven_gate")  # nobody there
    block = prompts.law_block(state)
    assert "You were seen" not in block
    assert "Gen A Mark" not in block


def test_a_seen_deed_this_turn_names_its_witnesses(lawful: Path) -> None:
    state = _world(people=[_person("gen_a_mark", "vendor", ALL_DAY)])
    state.turn_number = 7
    law.commit_deed(state, "pickpocket", certain=["gen_a_mark"])
    assert state.law["last_deed"]["turn"] == 7
    assert "You were seen: Gen A Mark saw you clearly." in prompts.law_block(state)


def test_a_turn_that_commits_nothing_names_nobody(lawful: Path) -> None:
    state = _world(people=[_person("gen_a_mark", "vendor", ALL_DAY)])
    law.commit_deed(state, "pickpocket", certain=["gen_a_mark"])
    state.turn_number += 1  # same day, same square, a quiet turn
    assert "You were seen" not in prompts.law_block(state)


def test_a_seen_lift_is_never_summarised_as_unnoticed() -> None:
    """The mark not feeling it is not nobody seeing it."""
    seen = prompts._sum_lift({"mark": "Prue", "gold": 3, "noticed": False,
                              "seen_by": ["gen_prue"]})
    assert "unnoticed" not in seen
    assert "seen" in seen
    empty = prompts._sum_lift({"mark": "Prue", "noticed": False, "seen_by": ["gen_prue"]})
    assert "unnoticed" not in empty
    clean = prompts._sum_lift({"mark": "Prue", "gold": 3, "noticed": False, "seen_by": []})
    assert "unnoticed" in clean


# ---------------------------------------------------------------------------
# v0.13.0 T5: how clearly the watch knows your face (the poster's sketch)
# ---------------------------------------------------------------------------


def _file(state: GameState, *, guise: str = "self", precision: float, deed_id: str,
          jurisdiction: str = "village", deed: str = "pickpocket") -> dict[str, Any]:
    return apply_effect(state, {
        "type": "report", "deed": deed, "guise": guise, "jurisdiction": jurisdiction,
        "precision": precision, "deed_id": deed_id,
    })


def test_the_default_clarity_words_rise_with_precision(lawful: Path) -> None:
    """No `clarity_words` in the file: the engine's four, ascending, and the
    shipped hops (0.3 / 0.6 / 1.0) land one on each above the floor."""
    state = _world()
    assert law.load_spec()["clarity_words"] == list(law.DEFAULT_CLARITY_WORDS)
    seen = [law.clarity_word(state, "self", "village")]
    for n, p in enumerate((0.3, 0.6, 1.0)):
        _file(state, precision=p, deed_id=f"d{n}")
        seen.append(law.clarity_word(state, "self", "village"))
    assert seen == ["nothing", "a rumour", "a description", "a likeness"]


def test_the_best_live_report_decides_not_the_newest(lawful: Path) -> None:
    state = _world()
    _file(state, precision=1.0, deed_id="d1")
    _file(state, precision=0.3, deed_id="d2")
    assert law.clarity_word(state, "self", "village") == "a likeness"


def test_linked_guises_share_one_sketch(lawful: Path) -> None:
    """The watch takes the Magpie for you: her likeness is yours. The porter
    nobody has tied to you is not."""
    state = _world()
    _file(state, guise="magpie", precision=1.0, deed_id="d1")
    _file(state, guise="porter", precision=0.6, deed_id="d2")
    assert law.clarity_word(state, "self", "village") == "a likeness"
    assert law.clarity_word(state, "magpie", "village") == "a likeness"
    assert law.clarity_word(state, "porter", "village") == "a description"


def test_another_jurisdictions_file_is_not_this_watchs(lawful: Path) -> None:
    state = _world()
    _file(state, precision=1.0, deed_id="d1", jurisdiction="town")
    assert law.clarity_word(state, "self", "village") == "nothing"
    assert law.clarity_word(state, "self", "town") == "a likeness"


def test_discharged_and_quashed_reports_draw_nothing(lawful: Path) -> None:
    """Read through `law.discharged` / `law.quashed`, not only through the
    rows the effects drop: a row a hand-edited save left behind for a deed
    the player has paid for, or a watch-house was bribed to lose, is no
    likeness."""
    state = _world()
    _file(state, precision=1.0, deed_id="paid")
    _file(state, precision=0.6, deed_id="lost")
    state.law["discharged_deeds"] = ["paid"]
    state.law["quashed"] = {"village": ["lost"]}
    assert law.clarity_word(state, "self", "village") == "nothing"
    # And through the effects themselves, end to end.
    fresh = _world()
    _file(fresh, precision=1.0, deed_id="x1")
    apply_effect(fresh, {"type": "quash_reports", "jurisdiction": "village", "guise": "self"})
    assert law.clarity_word(fresh, "self", "village") == "nothing"
    _file(fresh, precision=0.6, deed_id="x2")
    apply_effect(fresh, {"type": "law_discharge", "deed_ids": ["x2"]})
    assert law.clarity_word(fresh, "self", "village") == "nothing"


def test_authored_clarity_words_replace_the_defaults(tmp_path: Path) -> None:
    import yaml

    path = tmp_path / "law.yaml"
    path.write_text(yaml.safe_dump({**LAW_SPEC, "clarity_words": ["a stranger", "a face"]}),
                    encoding="utf-8")
    set_overlay({"paths": {"law": str(path)}})
    try:
        state = _world()
        assert law.clarity_word(state, "self", "village") == "a stranger"
        _file(state, precision=0.3, deed_id="d1")
        assert law.clarity_word(state, "self", "village") == "a face"
    finally:
        set_overlay(None)


@pytest.mark.parametrize("bad", [
    ["only one"], "a likeness", [1, 2], ["a rumour", "  "], {},
    # Never a number: a digit inside a word reaches the poster and the prose.
    ["nothing", "2 witnesses"], ["nothing", "a likeness v2"],
    # Two thresholds sharing a word are one word the player cannot tell apart.
    ["nothing", "a rumour", "a rumour"], ["nothing", "A Rumour", "a rumour "],
])
def test_clarity_words_are_validated(tmp_path: Path, bad: Any) -> None:
    import yaml

    path = tmp_path / "law.yaml"
    path.write_text(yaml.safe_dump({**LAW_SPEC, "clarity_words": bad}), encoding="utf-8")
    set_overlay({"paths": {"law": str(path)}})
    try:
        with pytest.raises(ValueError, match="clarity_words") as caught:
            law.load_spec()
        assert str(path) in str(caught.value), caught.value
    finally:
        set_overlay(None)


def test_undeclared_story_has_no_clarity_word() -> None:
    assert law.clarity_word(_world(), "self", "village") == ""


def test_payload_ships_the_clarity_word_for_the_face_worn_here(lawful: Path) -> None:
    state = _world()
    assert state.to_client_dict()["law"]["clarity"] == "nothing"
    _file(state, guise="magpie", precision=0.6, deed_id="d1")
    payload = state.to_client_dict()["law"]
    assert payload["clarity"] == "a description"
    assert not _DIGIT.search(payload["clarity"])


def test_the_narrator_hears_the_same_word_as_the_poster(lawful: Path) -> None:
    """One source of wording: the wanted line carries the payload's word."""
    state = _world()
    _report(state, deed="fencing", precision=0.6, deed_id="d1")
    _report(state, deed="assault_watch", precision=0.3, deed_id="d2")
    block = prompts.law_block(state)
    word = state.to_client_dict()["law"]["clarity"]
    assert word == "a description"
    assert f"it has {word} of you" in block
    assert not _DIGIT.search(block)


def test_the_payload_law_key_is_absent_undeclared_with_clarity_too() -> None:
    """The flagship: no `law` key at all, so no `clarity` either."""
    assert "law" not in _world().to_client_dict()

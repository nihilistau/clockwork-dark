"""Each agreement check fails its bad fixtures and passes its good ones (spec §11.5, A2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import yamlio
from tests.social_fixtures import matched, receipts_active, receipts_state  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures" / "social_agreement"
CHECKS = ["media_claimed", "media_denied", "stage_claimed", "profile_contradicted",
          "another_person", "number", "decline_wording", "meeting_claimed"]


def _cases(name: str, which: str) -> list[dict]:
    return yamlio.safe_load((FIXTURES / f"{name}.yaml").read_text(encoding="utf-8"))[which]


@pytest.mark.parametrize("name", CHECKS)
def test_every_bad_fixture_fails_its_check(receipts_active, name) -> None:
    from engine.social import agreement

    cases = _cases(name, "bad")
    assert len(cases) >= 6
    for case in cases:
        failures = agreement.check(case["reply"], agreement.decision_of(case), agreement.view_of(case))
        assert any(f.check == name for f in failures), case


@pytest.mark.parametrize("name", CHECKS)
def test_every_good_fixture_passes_every_check(receipts_active, name) -> None:
    from engine.social import agreement

    cases = _cases(name, "good")
    assert len(cases) >= 6
    for case in cases:
        assert agreement.check(case["reply"], agreement.decision_of(case), agreement.view_of(case)) == [], case


def test_every_check_is_registered_and_fixtured(receipts_active) -> None:
    from engine.social import agreement

    assert list(agreement.CHECKS) == CHECKS
    assert agreement.STATE_CHECKS == frozenset({"stage_claimed", "another_person", "meeting_claimed"})
    assert {p.stem for p in FIXTURES.glob("*.yaml")} == set(CHECKS)


def test_a_failing_shared_fact_is_reported_where_it_is(receipts_active) -> None:
    from engine.social import agreement

    case = _cases("another_person", "bad")[-1]          # the last bad case puts the name in `shared`
    failures = agreement.check(case["reply"], agreement.decision_of(case), agreement.view_of(case))
    assert any(f.where == "shared" for f in failures)
    assert failures == [agreement.Failure("another_person", "shared", 0, "Callum")]


def test_a_failure_names_its_item(receipts_active) -> None:
    from engine.social import agreement

    case = _cases("media_claimed", "bad")[5]             # the claim is in the second bubble
    found = agreement.check(case["reply"], agreement.decision_of(case), agreement.view_of(case))
    assert found == [agreement.Failure("media_claimed", "bubbles", 1, "sent you a voice note")]
    case = _cases("number", "bad")[0]                    # four bubbles, three allowed
    found = agreement.check(case["reply"], agreement.decision_of(case), agreement.view_of(case))
    assert [(f.check, f.index) for f in found] == [("number", 3)]
    case = _cases("profile_contradicted", "bad")[5]      # Sam is 29, not 35
    found = agreement.check(case["reply"], agreement.decision_of(case), agreement.view_of(case))
    assert found == [agreement.Failure("profile_contradicted", "learned", 0, "player age 35")]


def test_checks_are_pure(receipts_active) -> None:
    import ast
    import inspect

    from engine.social import agreement

    tree = ast.parse(inspect.getsource(agreement))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & {"apply_effect", "world_rng", "person_rng", "stable_rng", "random"}
    assert "random" not in imported and "engine.game.rng" not in imported
    for name, fn in agreement.CHECKS.items():
        assert list(inspect.signature(fn).parameters) == ["reply", "decision", "view"], name   # never `state`
    assert list(inspect.signature(agreement.check).parameters) == ["reply", "decision", "view"]


def test_a_check_leaves_the_reply_as_it_was(receipts_active) -> None:
    import copy

    from engine.social import agreement

    for name in CHECKS:
        for case in _cases(name, "bad") + _cases(name, "good"):
            before = copy.deepcopy(case["reply"])
            agreement.check(case["reply"], agreement.decision_of(case), agreement.view_of(case))
            assert case["reply"] == before


def test_view_from_state_matches_the_live_person(receipts_state, matched) -> None:
    from engine.social import agreement, messaging, population

    first_tid = matched("matchstick")
    first = first_tid.split(":", 1)[1]
    second = matched("front_porch").split(":", 1)[1]
    view = agreement.view_from_state(receipts_state, first)
    live = receipts_state.social["people"][first]
    second_name = population.profile(receipts_state, second).name
    assert view.stage == live["stage"] == "matched"
    assert view.person == population.profile(receipts_state, first)
    assert view.player == receipts_state.social["player"]
    assert view.contacts == (second_name,)
    assert agreement.view_from_state(receipts_state, second).contacts == (view.person.name,)
    assert view.agreed_meets == () and view.told == () and view.stage_before == ""
    # the player names the other person in this thread: now this person may know the name
    assert messaging.send(receipts_state, first_tid, "text", f"{second_name} says hi")["ok"]
    assert agreement.view_from_state(receipts_state, first).told == (second_name,)
    assert agreement.view_from_state(receipts_state, second).told == ()


def test_view_from_state_carries_the_stage_they_left(receipts_state, matched) -> None:
    from engine.social import agreement
    from tests.social_fixtures import _force_stage

    pid = matched("matchstick").split(":", 1)[1]
    _force_stage(receipts_state, pid, "talking")
    _force_stage(receipts_state, pid, "winding_down")
    view = agreement.view_from_state(receipts_state, pid)
    assert (view.stage, view.stage_before) == ("winding_down", "talking")
    _force_stage(receipts_state, pid, "faded")                     # left from cooling off: what it cooled from
    assert agreement.view_from_state(receipts_state, pid).stage_before == "talking"


#: Every population.yaml name, as reviewed for ordinary words and places in v0.22.0 T11
#: (relationships.yaml `ordinary_names` holds those that are). A new name fails here until
#: it is decided: add it to this list, and to ordinary_names if it is also a word or a place.
REVIEWED_NAMES = """
    Aaron Abby Abe Ada Adam Aidan Aisha Alana Alex Alfie Ali Alice Amara Amber Amelia Amir Amy Ana
    Andre Andy Anna Annie April Archie Aria Arlo Arthur Ash Asher Ava Bea Beau Bella Ben Beth
    Bianca Billy Blake Bobby Bonnie Bree Brooke Caitlin Cal Caleb Callie Callum Carla Carlos Carmen
    Cass Charlie Chloe Chris Cian Ciara Clara Claudia Cleo Cole Conor Daisy Dan Dani Danny Dara
    Darcy Declan Delia Demi Dev Dexter Dom Dylan Eddie Eden Eleanor Elena Eli Eliza Ella Ellie
    Elliot Ellis Elsie Emil Emily Emma Eric Erin Esme Ethan Eva Evan Evie Ezra Faye Felix Fergus
    Fern Finn Fiona Flo Fraser Freddie Freya Gabe Gabi Gemma George Georgia Gil Grace Gus Hal Hamza
    Hana Hannah Hari Harper Harry Harvey Hattie Hazel Heidi Holly Hugo Ian Idris Imogen India Ines
    Iris Isaac Isla Ivan Ivy Jack Jacob Jade Jake James Jamie Jasmine Jay Jed Jess Jo Joe Jonah
    Jonny Jordan Josh Josie Jude Julia June Kai Kara Kate Katie Kaz Keira Kieran Kim Kira Kit Kofi
    Lacey Laila Lana Laura Layla Leah Lena Leo Leon Lewis Lexi Liam Libby Lila Lily Lina Liv Lola
    Lottie Louis Luca Lucy Luke Luna Lydia Mabel Maddie Maeve Maisie Malik Marcus Maria Mark Martha
    Mason Matt Max Maya Meg Mia Mila Miles Millie Milo Mina Mo Molly Nadia Naomi Nate Ned Nell Nia
    Niall Nick Nina Noah Nora Olive Olivia Ollie Omar Orla Oscar Otis Owen Paige Pat Paul Pearl
    Pete Phoebe Pip Poppy Priya Quinn Rae Raf Rami Ravi Ray Reece Rhea Rhys Rita Rob Robyn Ronan
    Rory Rosa Rose Ross Rowan Ruben Ruby Rufus Ruth Ryan Sadie Sam Sami Sara Sasha Sean Seb Selma
    Sian Sid Sienna Simon Skye Sofia Sol Sophie Stan Stella Steve Tara Teddy Tess Thea Theo Tilly
    Toby Tom Tommy Tristan Ty Uma Vera Vic Vince Violet Wes Wilf Will Willa Xander Yara Yasmin
    Yusuf Zac Zain Zara Zeke Zoe
""".split()


def test_every_population_name_was_reviewed_for_ordinary_words(receipts_active) -> None:
    from engine import social

    names = {n for rows in social.data("population")["names"].values() for n in rows}
    assert sorted(names) == sorted(REVIEWED_NAMES), sorted(names ^ set(REVIEWED_NAMES))
    ordinary = set(social.data("relationships")["ordinary_names"])
    assert ordinary <= {n.lower() for n in names}, sorted(ordinary - {n.lower() for n in names})
    assert len(ordinary) == 70


def test_the_phrase_lists_are_checked(receipts_active) -> None:
    from engine import social
    from engine.social import agreement

    assert agreement.check_phrases(social.data("relationships")) == []
    for name in agreement.PHRASE_LISTS:
        assert social.data("relationships").get(name), name        # the story ships every list
    assert agreement.check_phrases({"media_claims": "sent you a pic"}) == [
        ("media_claims", "must be a list of phrases, each with a word in it")]
    assert agreement.check_phrases({"agree_phrases": ["ok sending", " !! "]})[0][0] == "agree_phrases"


def test_the_validator_reports_a_bad_phrase_list(tmp_path: Path) -> None:
    import shutil

    from engine.games import registry
    from engine.games.validation import StoryValidator

    social_dir = Path(__file__).resolve().parents[1] / "games" / "read-receipts" / "data" / "social"
    shutil.copy(social_dir / "behaviours.yaml", tmp_path / "behaviours.yaml")
    text = (social_dir / "relationships.yaml").read_text(encoding="utf-8")
    start = text.index("media_claims: [")
    end = text.index("]\n", start) + 2
    (tmp_path / "relationships.yaml").write_text(text[:start] + "media_claims: 12\n" + text[end:], encoding="utf-8")
    validator = StoryValidator(registry.get("read-receipts"))
    validator._check_relationships(tmp_path)
    named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
    assert named == {("social/relationships.yaml", "media_claims")}, validator.issues
    clean = StoryValidator(registry.get("read-receipts"))
    clean._check_relationships(social_dir)
    assert [i for i in clean.issues if i.severity == "error"] == []

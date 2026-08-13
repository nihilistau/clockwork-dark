"""
Story content integrity — every discovered game, through the one validator.

WHAT THIS REPLACES. ``tests/test_content_integrity.py`` ran the referential
pass for the flagship alone, against a validator whose paths and vocabularies
were the flagship's. The shared validator (``engine/games/validation.py``)
resolves everything through the story manifest, so this file runs the full
pass over EVERY ``games/<slug>/game.yaml`` on disk -- a story added tomorrow
(dev-story included) is validated the moment it exists, with no test edit.
The flagship-specific volume assertions stay in the old file.

Nothing here activates a game. The validator reads YAML straight off the
manifest's paths, which is what lets one process validate every story without
repointing config or clearing a content cache.

The negative controls matter as much as the green runs: a referential pass
that cannot go red is a rubber stamp. Each control builds a tiny broken story
in tmp_path and asserts the validator says exactly what broke.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.games import registry
from engine.games import validation
from engine.games.manifest import GameManifest, from_dict

#: Discovered once at collection. A worktree without a story (dev-story before
#: its stream lands) simply parametrises fewer cases; an empty games/ dir
#: skips the per-game test rather than passing vacuously.
SLUGS = sorted(registry.discover())


def _manifest(slug: str) -> GameManifest:
    manifest = registry.get(slug)
    assert manifest is not None, f"games/{slug}/game.yaml vanished mid-run"
    return manifest


# ---------------------------------------------------------------------------
# every game, the whole tree
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not SLUGS, reason="no games discovered under games/")
@pytest.mark.parametrize("slug", SLUGS)
def test_story_content_has_no_broken_references(slug: str) -> None:
    """The one assertion this file exists for, per story."""
    issues = validation.validate_story(_manifest(slug))
    errors = validation.errors_only(issues)
    assert not errors, "\n".join(str(e) for e in errors)


@pytest.mark.skipif(not SLUGS, reason="no games discovered under games/")
@pytest.mark.parametrize("slug", SLUGS)
def test_story_content_is_strict_clean(slug: str) -> None:
    """
    Shipped stories carry no advisories either.

    Advisories exist so a work-in-progress story can run the tool without
    drowning; a SHIPPED story with a standing advisory is a shipped question
    nobody answered. This is `validate_content.py --game <slug> --strict`.
    """
    issues = validation.validate_story(_manifest(slug))
    assert not issues, "\n".join(str(i) for i in issues)


@pytest.mark.skipif(not SLUGS, reason="no games discovered under games/")
@pytest.mark.parametrize("slug", SLUGS)
def test_validator_reports_only_known_severities(slug: str) -> None:
    """Advisories must not be able to fail a build by accident."""
    issues = validation.validate_story(_manifest(slug))
    assert all(i.severity in {"error", "warning"} for i in issues)


def test_validating_an_unknown_slug_reports_rather_than_raises() -> None:
    """A caller iterating games must be able to report a missing one."""
    issues = validation.validate_story("no-such-story")
    assert validation.errors_only(issues)


# ---------------------------------------------------------------------------
# vocabularies resolve per story
# ---------------------------------------------------------------------------


def test_story_skills_fall_back_to_the_engine_seven(tmp_path: Path) -> None:
    """A graph story with no skills.yaml speaks the canon taxonomy."""
    manifest = from_dict({"title": "T"}, slug="t", root=tmp_path)
    assert validation.story_skills(manifest) == validation.ENGINE_SKILLS
    assert validation.story_bands(manifest) == validation.ENGINE_BANDS


def test_story_skills_come_from_the_storys_own_rules(tmp_path: Path) -> None:
    """A declared taxonomy REPLACES the engine's, it does not extend it."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "skills.yaml").write_text(
        "skills:\n  weaving: {stat: focus}\n  malice: {stat: presence}\n"
        "difficulty:\n  soft: 5\n  cruel: 20\n",
        encoding="utf-8",
    )
    manifest = from_dict(
        {"title": "T", "paths": {"rules": str(rules)}}, slug="t", root=tmp_path
    )
    assert validation.story_skills(manifest) == frozenset({"weaving", "malice"})
    assert validation.story_bands(manifest) == frozenset({"soft", "cruel"})


def test_item_tags_are_the_storys_own_plus_the_engine_set() -> None:
    """The Garden tags by provenance; the engine set is a floor, not a law."""
    tags = validation.story_item_tags({"x": {"tags": ["gift", "sophia"]}})
    assert {"gift", "sophia"} <= tags
    assert validation.ENGINE_ITEM_TAGS <= tags


def test_doom_vocabulary_is_gated_on_the_doom_path() -> None:
    """Phase ids are only a vocabulary for a story that runs the doom clock."""
    flagship = _manifest("clockwork-dark") if "clockwork-dark" in SLUGS else None
    if flagship is not None:
        assert validation.doom_enabled(flagship)
    no_doom = from_dict({"title": "T"}, slug="t")
    assert not validation.doom_enabled(no_doom)


# ---------------------------------------------------------------------------
# negative controls — the checks can go red
# ---------------------------------------------------------------------------


def _story(tmp_path: Path, paths: dict[str, str], extra: dict | None = None) -> GameManifest:
    """A synthetic manifest rooted in tmp_path, paths given repo-absolute."""
    data: dict = {"title": "Broken", "entry": {"location_id": "a", "archetypes": []}}
    data.update(extra or {})
    data["paths"] = paths
    return from_dict(data, slug="broken", root=tmp_path)


def test_validator_detects_a_vendor_stocking_a_ghost_item() -> None:
    """The economy check must notice an item that no longer exists."""
    issues = validation.check_economy_data(
        "economy.yaml",
        {"maris": {"sells": {"wild_mushrooms": {"price": 2}}}},
        items={},
        npc_ids={"maris"},
    )
    assert any("not in the story's items files" in i.message for i in issues)


def test_validator_detects_a_dead_recipe_input() -> None:
    """The recipe check must notice an input that no longer exists."""
    issues = validation.check_recipe_row(
        "recipes.yaml",
        {
            "id": "r",
            "skill": "craft",
            "band": "standard",
            "hours": 1,
            "inputs": [{"id": "gone"}],
            "output": {"id": "also_gone"},
        },
        items={},
        locations=set(),
        skills=validation.ENGINE_SKILLS,
        bands=validation.ENGINE_BANDS,
    )
    messages = "\n".join(i.message for i in issues)
    assert "input item" in messages
    assert "output item" in messages


def test_validator_detects_an_edge_to_nowhere_and_an_orphan(tmp_path: Path) -> None:
    locations = tmp_path / "locations.yaml"
    locations.write_text(
        "locations:\n"
        "  a: {name: A, ring: 0, connections: {ghost: {hours: 1}}}\n"
        "  island: {name: I, ring: 0, connections: {}}\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {"locations": str(locations)}))
    messages = "\n".join(str(i) for i in validation.errors_only(issues))
    assert "a>ghost" in messages and "edge target does not exist" in messages
    assert "island" in messages and "unreachable from a" in messages


def test_a_sentinel_location_is_allowed_to_be_unreachable(tmp_path: Path) -> None:
    """The Garden's `unknown` pattern: placed by effects, never by travel."""
    locations = tmp_path / "locations.yaml"
    locations.write_text(
        "locations:\n"
        "  a: {name: A, ring: 0, connections: {}}\n"
        "  limbo: {name: L, ring: 0, tags: [sentinel], connections: {}}\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {"locations": str(locations)}))
    assert not any("unreachable" in i.message for i in issues)


def test_validator_detects_a_missing_canon_location(tmp_path: Path) -> None:
    """A graph may pin its canon inside the file; a pinned id must exist."""
    locations = tmp_path / "locations.yaml"
    locations.write_text(
        "canon: [a, renamed_place]\n"
        "locations:\n"
        "  a: {name: A, ring: 0, connections: {}}\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {"locations": str(locations)}))
    assert any(
        i.ref_id == "renamed_place" and "canon location id is missing" in i.message
        for i in issues
    )


def test_validator_detects_an_undeclared_value_in_a_deck(tmp_path: Path) -> None:
    """A meter the schema does not declare is a write the store refuses."""
    (tmp_path / "state.yaml").write_text(
        "version: 1\nmeters:\n  favor: {min: 0, max: 100}\n", encoding="utf-8"
    )
    decks = tmp_path / "scenes"
    decks.mkdir()
    (decks / "day.yaml").write_text(
        "id: day\ncards:\n"
        "  - id: c1\n"
        "    beats:\n"
        "      - id: b1\n"
        "        gate:\n"
        "          on_pass:\n"
        "            effects:\n"
        "              - {type: value, name: favro, delta: 1}\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {"decks": str(decks)}))
    assert any(
        i.ref_id == "favro" and "not declared in state.yaml" in i.message for i in issues
    )


def test_validator_detects_an_undeclared_clock(tmp_path: Path) -> None:
    """Every clock the clock table drives must be declared as one."""
    (tmp_path / "state.yaml").write_text(
        "version: 1\nclocks:\n  hunger: {min: 0, max: 5}\n", encoding="utf-8"
    )
    clocks = tmp_path / "clocks.yaml"
    clocks.write_text(
        "clocks:\n  hunger: {beats: []}\n  thirst: {beats: []}\n", encoding="utf-8"
    )
    issues = validation.validate_story(_story(tmp_path, {"clocks": str(clocks)}))
    assert any(
        i.ref_id == "thirst" and "not declared in state.yaml" in i.message for i in issues
    )


def test_validator_detects_a_gate_on_a_flag_nobody_sets(tmp_path: Path) -> None:
    """The read side of the two-direction check."""
    decks = tmp_path / "scenes"
    decks.mkdir()
    (decks / "day.yaml").write_text(
        "id: day\ncards:\n"
        "  - id: c1\n"
        "    when: {flag: never_written}\n"
        "    beats: []\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {"decks": str(decks)}))
    assert any(
        i.ref_id == "never_written" and "can never open" in i.message for i in issues
    )


def test_the_canon_dictionary_resolves_a_flag_in_both_directions(tmp_path: Path) -> None:
    """
    The Garden pattern, generalised: a canon dictionary turns write-only flags
    from advisories into declared vocabulary, and non-canon writes into errors.
    """
    canon_dir = tmp_path / "data" / "canon"
    canon_dir.mkdir(parents=True)
    (canon_dir / "state-dictionary.json").write_text(
        '{"flags": {"booleans": {"acts": ["door_opened"]},'
        ' "enums": {"path": ["none", "roses"]}}}',
        encoding="utf-8",
    )
    decks = tmp_path / "scenes"
    decks.mkdir()
    (decks / "day.yaml").write_text(
        "id: day\ncards:\n"
        "  - id: c1\n"
        "    when: {flag: path_roses}\n"  # canon via enum expansion
        "    beats:\n"
        "      - id: b1\n"
        "        gate:\n"
        "          on_pass:\n"
        "            effects:\n"
        "              - {type: flag, flag: door_opened}\n"  # canon boolean
        "              - {type: flag, flag: door_openned}\n"  # the typo
        "",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {"decks": str(decks)}))
    errors = validation.errors_only(issues)
    assert any(i.ref_id == "door_openned" for i in errors)
    assert not any(i.ref_id in {"door_opened", "path_roses"} for i in errors)


def test_validator_detects_an_ending_without_an_epilogue(tmp_path: Path) -> None:
    endings = tmp_path / "endings.yaml"
    endings.write_text(
        "fail_forward: E1a\n"
        "classes:\n  E1:\n    variants:\n      E1a: {label: Out}\n      E1b: {label: In}\n",
        encoding="utf-8",
    )
    epilogues = tmp_path / "epilogues"
    epilogues.mkdir()
    (epilogues / "epilogue_index.yaml").write_text(
        "endings:\n  - {id: E1a, title: Out}\n", encoding="utf-8"
    )
    (epilogues / "epilogue_cards.yaml").write_text(
        "cards:\n  E1a: {card_m: 'You went home.', card_g: 'The gate closed.'}\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(
        _story(tmp_path, {"endings": str(endings), "epilogues": str(epilogues)})
    )
    messages = "\n".join(str(i) for i in validation.errors_only(issues))
    assert "E1b" in messages and "no epilogue" in messages


def test_validator_detects_a_fail_forward_that_resolves_to_nothing(tmp_path: Path) -> None:
    endings = tmp_path / "endings.yaml"
    endings.write_text(
        "fail_forward: E9z\nclasses:\n  E1:\n    variants:\n      E1a: {label: Out}\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {"endings": str(endings)}))
    assert any(
        i.ref_id == "E9z" and "undeclared ending" in i.message
        for i in validation.errors_only(issues)
    )


def test_validator_detects_a_missing_agent_prompt_file(tmp_path: Path) -> None:
    """
    The silent-never-plans trap is a hard error.

    An agent whose persona file is missing does not fail -- it sits out every
    negotiation and the other agent leads by default. That shipped once.
    """
    (tmp_path / "state.yaml").write_text(
        "version: 1\nmeters:\n  favor: {min: 0, max: 100}\n", encoding="utf-8"
    )
    (tmp_path / "agents.yaml").write_text(
        "agents:\n"
        "  gm:\n"
        "    role: world\n"
        "    prompt: prompts/gm.md\n"
        "    voices: [narration]\n"
        "    writes: [favor]\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {}))
    assert any(
        i.ref_id == "gm" and "prompt file does not exist" in i.message
        for i in validation.errors_only(issues)
    )


def test_validator_detects_an_agent_writing_an_undeclared_value(tmp_path: Path) -> None:
    (tmp_path / "state.yaml").write_text(
        "version: 1\nmeters:\n  favor: {min: 0, max: 100}\n", encoding="utf-8"
    )
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "gm.md").write_text("You are the world.", encoding="utf-8")
    (tmp_path / "agents.yaml").write_text(
        "agents:\n"
        "  gm:\n"
        "    role: world\n"
        "    prompt: prompts/gm.md\n"
        "    voices: [narration]\n"
        "    writes: [favor, favro]\n"
        "    reads: [gm_secrets, crystal_ball]\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {}))
    messages = "\n".join(str(i) for i in validation.errors_only(issues))
    assert "favro" in messages and "does not declare" in messages
    assert "crystal_ball" in messages and "unknown knowledge scope" in messages


def test_validator_detects_a_spoiler_row_the_gate_would_skip(tmp_path: Path) -> None:
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "spoilers.yaml").write_text(
        "spoilers:\n  - {term: 'The Big Reveal'}\n", encoding="utf-8"
    )
    issues = validation.validate_story(_story(tmp_path, {"rules": str(rules)}))
    assert any(
        "needs both term: and instead:" in i.message
        for i in validation.errors_only(issues)
    )


def test_validator_detects_duplicate_card_ids(tmp_path: Path) -> None:
    decks = tmp_path / "scenes"
    decks.mkdir()
    (decks / "day.yaml").write_text(
        "id: day\ncards:\n  - {id: c1, beats: []}\n  - {id: c1, beats: []}\n",
        encoding="utf-8",
    )
    issues = validation.validate_story(_story(tmp_path, {"decks": str(decks)}))
    assert any(
        i.ref_id == "c1" and "duplicate card id" in i.message
        for i in validation.errors_only(issues)
    )

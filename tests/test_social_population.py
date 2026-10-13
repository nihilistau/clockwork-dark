"""A person is a pure function of (seed, index) (spec §4, §19.1)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from tests.social_fixtures import receipts_active, receipts_state  # noqa: F401 -- created in this task

ROOT = Path(__file__).resolve().parents[1]

ARCHETYPES = {"romantic", "slow_burner", "banterer", "dry_texter", "needy", "ghoster",
              "breadcrumber", "drifter", "turner", "steady", "busy", "night_owl"}


def test_a_person_is_the_same_whatever_order_anyone_was_met_in(receipts_active) -> None:
    from engine.social import population

    a = [population.person(7, i) for i in (5, 400, 12)]
    population.reset_profiles()
    b = [population.person(7, i) for i in (12, 5, 400)]
    assert {p.pid: p for p in a} == {p.pid: p for p in b}


def test_no_draw_uses_a_salted_hash_or_bare_random(receipts_active) -> None:
    """Cross-process stability (spec §4.1): every draw is stable_rng (blake2b), never hash() or random.*."""
    import ast
    import inspect

    from engine.social import population

    tree = ast.parse(inspect.getsource(population))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "hash" not in called
    imported = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert "random" not in imported


@pytest.mark.parametrize("sex, mode, expected", [
    ("female", "opposite", {"male"}), ("male", "opposite", {"female"}),
    ("female", "same", {"female"}), ("male", "any", {"male", "female"}),
])
def test_the_filter(receipts_active, monkeypatch, sex, mode, expected) -> None:
    from engine.social import population

    monkeypatch.setitem(population._filter_spec(), "sex", mode)
    player = {"sex": sex, "discovery": {"age_min": 25, "age_max": 38}}
    seen = {population.person(3, i, player).sex for i in range(200)}
    assert seen == expected


def test_the_filter_mode_is_in_the_cache_key(receipts_active, monkeypatch) -> None:
    """F7: the same (seed, index, player) under another filter is another person, with no reset."""
    from engine.social import population

    player = {"sex": "female", "discovery": {"age_min": 25, "age_max": 38}}
    assert population.person(3, 17, player).sex == "male"
    monkeypatch.setitem(population._filter_spec(), "sex", "same")
    assert population.person(3, 17, player).sex == "female"


def test_changing_the_filter_reshuffles_nothing_else(receipts_active, monkeypatch) -> None:
    from engine.social import population

    player = {"sex": "female", "discovery": {"age_min": 25, "age_max": 38}}
    before = population.person(3, 17, player)
    monkeypatch.setitem(population._filter_spec(), "sex", "same")
    population.reset_profiles()
    after = population.person(3, 17, player)
    assert before.hobbies == after.hobbies and before.archetype == after.archetype
    assert before.personality == after.personality and before.neighbourhood == after.neighbourhood


def test_changing_the_filter_moves_only_sex_and_name(receipts_active, monkeypatch) -> None:
    """...and, since T21, the voice: one of that sex (drawn after it, on its own key)."""
    import dataclasses

    from engine.social import population

    player = {"sex": "female", "discovery": {"age_min": 25, "age_max": 38}}
    before = [population.person(3, i, player) for i in range(40)]
    monkeypatch.setitem(population._filter_spec(), "sex", "same")
    after = [population.person(3, i, player) for i in range(40)]
    for a, b in zip(before, after):
        assert dataclasses.replace(a, sex=b.sex, name=b.name, voice_id=b.voice_id) == b


def test_pools_are_disjoint_but_for_the_overlap_band(receipts_active) -> None:
    from engine.social import population

    match, porch = population.pool("matchstick"), population.pool("front_porch")
    shared = set(match) & set(porch)
    assert len(shared) == 0
    band = population.overlap("matchstick")
    assert len(band) == 60
    assert all(set(population.apps_of(population.pid_for(i))) == {"matchstick", "front_porch"} for i in band)


def test_the_pools_are_the_specs_sizes_and_the_band_is_one_for_both_apps(receipts_active) -> None:
    from engine.social import population

    # The spec's example pools were 900 and 400 (§4.1); T26 grew Matchstick's to 1800 (rule 10, apps.yaml's
    # measured table: at 900 an attentive player had swiped the whole deck by day 30).
    assert population.pool("matchstick") == range(0, 1800)
    assert population.pool("front_porch") == range(1800, 2200)
    assert population.overlap("front_porch") == population.overlap("matchstick") == range(2200, 2260)
    assert population.apps_of("p0004") == ("matchstick",)
    assert population.apps_of("p1950") == ("front_porch",)
    assert population.apps_of("p5000") == ()


def test_ages_respect_discovery_widened_by_the_spill(receipts_active) -> None:
    from engine.social import population

    player = {"sex": "female", "discovery": {"age_min": 25, "age_max": 38}}
    ages = [population.person(9, i, player).age for i in range(300)]
    assert min(ages) >= 18
    assert min(ages) >= int(25 * 0.8) and max(ages) <= round(38 * 1.2)


def test_profiles_cost_no_model_call(receipts_active, monkeypatch) -> None:
    from engine.llm import backend
    from engine.social import population

    monkeypatch.setattr(backend, "get_backend", lambda: pytest.fail("a profile called the model"))
    for i in range(50):
        population.person(1, i)


def test_every_person_is_well_formed(receipts_active) -> None:
    from engine import social
    from engine.social import population

    data = social.data("population")
    flags = set(data["flags"])
    sliders = list(data["personality"])
    photo_ids = {row["id"] for row in data["photo_set"]}
    lo, hi = social.data("apps").get("matching", {}).get("chemistry", (-0.15, 0.15))
    indices = list(range(0, 40)) + list(range(900, 940)) + list(range(1300, 1320))
    for i in indices:
        p = population.person(11, i)
        assert p.pid == population.pid_for(i) and population.index_of(p.pid) == i
        assert 2 <= len(p.hobbies) <= 6 and len(set(p.hobbies)) == len(p.hobbies)
        assert len(p.traits) == 3 and len(set(p.traits)) == 3
        assert 2 <= len(p.photos) <= 5 and set(p.photos) <= photo_ids
        assert [k for k, _ in p.personality] == sliders and all(1 <= v <= 5 for _, v in p.personality)
        assert set(p.flags) <= flags
        assert p.intent in {"friendship", "short_term", "long_term", "unsure"}
        assert p.archetype in ARCHETYPES
        assert lo <= p.chemistry <= hi
        assert set(p.bio) == set(population.apps_of(p.pid)) and all(p.bio.values())
        assert all("{" not in text for text in p.bio.values())
        assert (len(p.prompts) == 3) == ("front_porch" in population.apps_of(p.pid))
        attrs = dict(p.attributes)
        assert (attrs["kids"] == "have") == p.has_flag("has_kids")
        prefs = dict(p.preferences)
        assert 18 <= prefs["age_min"] <= prefs["age_max"]
        assert 0.0 <= prefs["selectivity"] <= 1.0
        assert p.appearance and p.voice_id in population.voices_of(p.sex)


def test_profile_reads_the_states_seed_and_player(receipts_state) -> None:
    from engine.social import population

    player = receipts_state.social.get("player") or {}
    assert population.profile(receipts_state, "p0012") == population.person(4242, 12, player)


def test_tables_are_the_creation_sources(receipts_active) -> None:
    from engine.social import population

    for name in ("hobbies", "hair", "style", "jobs", "photo_set"):
        rows = population.table(name)
        assert rows and all({"id", "label"} <= set(row) for row in rows), name
    assert population.table("no_such_table") == []


def test_the_shipped_tables_meet_their_counts(receipts_active) -> None:
    from engine import social

    data = social.data("population")
    assert len(data["names"]["female"]) >= 150 and len(data["names"]["male"]) >= 150
    assert len(data["neighbourhoods"]) == 11
    assert len(data["jobs"]) >= 40 and len(data["hobbies"]) >= 40
    assert len(data["traits"]) >= 30 and len(data["photo_set"]) >= 30
    assert len(data["texting_styles"]) >= 8


def test_the_dating_apps_declare_kind_label_and_capabilities(receipts_active) -> None:
    """Pre-flight F6: T6's edit_profile needs kind: dating before T7 fills the rest."""
    from engine import social

    apps = social.data("apps")["apps"]
    assert apps["matchstick"]["kind"] == apps["front_porch"]["kind"] == "dating"
    assert apps["matchstick"]["label"] == "Matchstick" and apps["front_porch"]["label"] == "Front Porch"
    assert apps["matchstick"]["capabilities"] == ["text"]
    assert apps["front_porch"]["capabilities"] == ["text", "voice"]


def test_a_cache_reset_drops_every_profile(receipts_active) -> None:
    """F7: the cache-reset walk (RELOADERS) never leaves a stale person behind a data reload."""
    from engine.games import caches
    from engine.social import population

    assert ("engine.social.population", "reset_profiles") in caches.RELOADERS
    population.person(2, 3)
    assert population._PROFILES
    caches.reset_all_caches()
    assert not population._PROFILES


def test_the_cache_is_bounded(receipts_active, monkeypatch) -> None:
    from engine.social import population

    monkeypatch.setattr(population, "PROFILE_CACHE_MAX", 5)
    for i in range(12):
        population.person(4, i)
    assert len(population._PROFILES) == 5
    assert [key[1] for key in population._PROFILES] == list(range(7, 12))


def test_the_shipped_population_validates_clean() -> None:
    from engine.games.validation import errors_only, validate_story

    errors = [i for i in errors_only(validate_story("read-receipts")) if i.source.startswith("social/")]
    assert errors == []


def _broken(data: dict, how: str) -> str:
    """Break ``data`` one way; return the key the validator must name."""
    if how == "filter":
        data["filter"]["sex"] = "both"
        return "filter.sex"
    if how == "neighbourhoods":
        data["neighbourhoods"].pop()
        return "neighbourhoods"
    if how == "asymmetric":
        first, second = data["neighbourhoods"][0]["id"], data["neighbourhoods"][1]["id"]
        data["distance"][first][second] = 4 if data["distance"][second][first] != 4 else 3
        return "distance"
    if how == "names":
        data["names"]["male"] = []
        return "names.male"
    if how == "weight":
        data["traits"][0]["weight"] = 0
        return "traits"
    if how == "bios":
        data["bios"]["no_such_style"] = ["hello"]
        return "bios.no_such_style"
    if how == "age_bounds":
        del data["age_bounds"]
        return "age_bounds"
    if how == "age_bounds_order":
        data["age_bounds"] = {"min": 40, "max": 30}
        return "age_bounds"
    if how == "prompt_row":
        data["prompts"]["front_porch"].append("just a string")
        return "prompts.front_porch"
    if how == "article":
        data["jobs"][0]["article"] = "the"
        return "jobs"
    if how == "placeholder":
        style = data["texting_styles"][0]["id"]
        data["bios"][style] = ["{no_such_field} forever"]
        return f"bios.{style}"
    raise AssertionError(how)


@pytest.mark.parametrize("how", ["filter", "neighbourhoods", "asymmetric", "names", "weight", "bios", "placeholder",
                                 "age_bounds", "age_bounds_order", "prompt_row", "article"])
def test_a_broken_population_is_an_error_naming_its_key(tmp_path, how) -> None:
    import yaml

    from engine import yamlio
    from engine.games import registry
    from engine.games.validation import StoryValidator

    manifest = registry.get("read-receipts")
    source = ROOT / "games" / "read-receipts" / "data" / "social" / "population.yaml"
    data = copy.deepcopy(yamlio.safe_load(source.read_text(encoding="utf-8")))
    key = _broken(data, how)
    (tmp_path / "population.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    validator = StoryValidator(manifest)
    validator._check_population(tmp_path)
    named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
    assert ("social/population.yaml", key) in named, validator.issues


def test_a_person_outside_every_pool_is_refused(receipts_active) -> None:
    from engine.social import population

    with pytest.raises(ValueError, match="p5000"):
        population.person(1, 5000)


def test_the_age_floor_is_data_with_no_engine_fallback(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import population

    monkeypatch.delitem(social.data("population"), "age_bounds")
    with pytest.raises(ValueError, match=r"population\.yaml: age_bounds\.min"):
        population.person(1, 3)


def test_reading_the_filter_never_writes_the_shared_data(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import population

    data = social.data("population")
    monkeypatch.delitem(data, "filter")
    population.person(1, 3, {"sex": "female"})
    assert "filter" not in data


def test_age_from_discovery_is_in_the_cache_key(receipts_active, monkeypatch) -> None:
    from engine.social import population

    player = {"sex": "female", "discovery": {"age_min": 25, "age_max": 26}}
    narrow = {population.person(9, i, player).age for i in range(60)}
    monkeypatch.setitem(population._filter_spec(), "age_from_discovery", False)
    wide = {population.person(9, i, player).age for i in range(60)}   # no reset: the key must differ
    assert max(narrow) <= round(26 * 1.2) < max(wide)


def test_a_job_may_name_its_article(receipts_active) -> None:
    from engine import social
    from engine.social import population

    data = social.data("population")
    words = population.template_words(data, ("reading", "hiking"), "hr_manager", "old_town")
    assert words["a_job"] == "an HR manager" and words["A_job"] == "An HR manager"
    assert population.template_words(data, ("reading", "hiking"), "accountant", "old_town")["a_job"] == "an accountant"
    assert population.template_words(data, ("reading", "hiking"), "nurse", "old_town")["a_job"] == "a nurse"


# -- the voice (T21, spec §13.6) ---------------------------------------------------------------------


def test_each_person_has_a_voice_of_their_sex(receipts_active, monkeypatch) -> None:
    from engine.config import get_config
    from engine.social import population

    monkeypatch.setitem(population._filter_spec(), "sex", "any")
    voices = {v["id"]: v["sex"] for v in get_config().get("tts.voices")}
    people = [population.person(11, i, {"sex": "female", "discovery": {"age_min": 22, "age_max": 50}})
              for i in range(200)]
    assert {p.sex for p in people} == {"female", "male"}
    assert all(voices.get(p.voice_id) == p.sex for p in people)
    assert {p.voice_id for p in people} == set(voices)               # every voice is drawn by someone


def test_adding_the_voice_draw_moved_no_earlier_field(receipts_active) -> None:
    """The twenty people of tests/fixtures/social_people_v022_t21.json (written before the draw) are
    equal field for field but `voice_id`: the draw is last, on its own key."""
    import dataclasses
    import json

    from engine.social import population

    expected = json.loads((ROOT / "tests" / "fixtures" / "social_people_v022_t21.json").read_text(encoding="utf-8"))
    player = {"sex": "female", "discovery": {"age_min": 25, "age_max": 38}}
    got = []
    for i in range(20):
        row = dataclasses.asdict(population.person(4242, i * 37, player))
        assert row.pop("voice_id")                                    # drawn now
        got.append(json.loads(json.dumps(row)))                       # tuples as lists, as the fixture holds them
    assert got == expected

"""Player creation (v0.22.0 T4, spec §3): the form is data; the engine validates and stores it."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from tests.social_fixtures import receipts_active  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_defaults_fill_an_omitted_creation(receipts_active) -> None:
    from engine.game import procgen

    state = procgen.new_game_state(player_name="Sam", seed=1)
    player = state.social["player"]
    assert player["sex"] == "female" and player["age"] == 29 and player["looking_for"] == "unsure"
    assert player["discovery"] == {"age_min": 25, "age_max": 38, "distance": "city"}
    assert 1 <= len(player["photos"]) <= 6 and 2 <= len(player["hobbies"]) <= 6


@pytest.mark.parametrize("payload, field", [
    ({"age": 17}, "age"),
    ({"sex": "other"}, "sex"),
    ({"hobbies": ["climbing"]}, "hobbies"),            # under min 2
    ({"wings": True}, "wings"),                         # unknown key refused
    ({"attributes": {"hair": "not_a_hair"}}, "attributes.hair"),
    ({"personality": {"outgoing": 9}}, "personality.outgoing"),
])
def test_a_bad_value_is_refused_naming_its_field(receipts_active, payload, field) -> None:
    from engine.game.state import GameState
    from engine.social import creation

    with pytest.raises(creation.CreationError) as err:
        creation.apply(GameState(), payload)
    assert err.value.field == field


def test_the_form_expands_tables(receipts_active) -> None:
    from engine.social import creation

    form = creation.resolved_form()
    hobbies = form["fields"]["hobbies"]
    assert hobbies["kind"] == "multi" and all({"id", "label"} <= set(row) for row in hobbies["of"])


def test_new_game_takes_creation_over_http(receipts_active, tmp_path, monkeypatch) -> None:
    from engine.scenes.default_scene import create_app

    scene, app = create_app(testing=True)  # reads the active story; local mode
    client = app.test_client()
    assert client.get("/api/social/creation").status_code == 200
    body = {"player_name": "Sam", "seed": 5, "creation": {"sex": "male", "age": 40}}
    resp = client.post("/api/game/new", json=body)
    assert resp.status_code == 200, resp.get_json()
    # The posted creation reaches the live run AND its first save.
    made = resp.get_json()
    live = scene.store.require(made["session_id"]).engine.state.social["player"]
    assert (live["sex"], live["age"]) == ("male", 40)
    saved, _ = scene.store._store_for("").load(made["save_id"])
    assert (saved.social["player"]["sex"], saved.social["player"]["age"]) == ("male", 40)
    bad = client.post("/api/game/new", json={"creation": {"age": 12}})
    assert bad.status_code == 400 and "age" in bad.get_json()["error"]


def test_a_refused_creation_writes_no_save(receipts_active) -> None:
    from engine.scenes.default_scene import create_app

    scene, app = create_app(testing=True)
    saves = scene.store._store_for("")
    before = [row.save_id for row in saves.list_saves()]
    resp = app.test_client().post("/api/game/new", json={"seed": 3, "creation": {"hobbies": ["nope", "never"]}})
    assert resp.status_code == 400 and resp.get_json()["error"].startswith("hobbies:")
    assert [row.save_id for row in saves.list_saves()] == before


def test_a_min_zero_multi_defaults_to_nothing(receipts_active, monkeypatch) -> None:
    from engine.game.state import GameState
    from engine.social import creation

    form = copy.deepcopy(creation.form_fields())
    form["photos"]["min"] = 0
    monkeypatch.setattr(creation, "form_fields", lambda: form)
    assert creation.apply(GameState(), {})["photos"] == []


def test_creation_in_a_story_without_a_form_is_a_400() -> None:
    from engine.games import registry
    from engine.scenes.default_scene import create_app

    registry.activate("clockwork-dark")
    try:
        _, app = create_app(testing=True)
        client = app.test_client()
        resp = client.post("/api/game/new", json={"creation": {"age": 30}})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "this story has no creation form"
        assert client.get("/api/social/creation").status_code == 404
    finally:
        registry.deactivate()


# -- further cases ---------------------------------------------------------------


def test_a_full_payload_is_stored_as_given(receipts_active) -> None:
    from engine.game import procgen
    from engine.social.population import table

    hobbies = [row["id"] for row in table("hobbies")][:3]
    photos = [row["id"] for row in table("photo_set")][:2]
    payload = {
        "name": "  Jo  ", "sex": "male", "age": 41, "looking_for": "long_term",
        "hobbies": hobbies, "photos": photos,
        "attributes": {"height": "tall", "smokes": "no", "kids": "have"},
        "personality": {"outgoing": 5, "homebody": 1},
        "discovery": {"age_min": 30, "age_max": 45, "distance": "anywhere"},
    }
    state = procgen.new_game_state(player_name="Jo", seed=7, creation=payload)
    player = state.social["player"]
    assert player["name"] == "Jo"                       # stripped
    assert (player["sex"], player["age"], player["looking_for"]) == ("male", 41, "long_term")
    assert player["hobbies"] == hobbies and player["photos"] == photos
    assert player["attributes"]["height"] == "tall" and player["attributes"]["smokes"] == "no"
    assert player["personality"] == {"outgoing": 5, "playful": 3, "romantic": 3, "adventurous": 3, "homebody": 1}
    assert player["discovery"] == {"age_min": 30, "age_max": 45, "distance": "anywhere"}
    # The slice is born whole around the profile (empty_slice + player).
    from engine.social.kinds import empty_slice

    assert set(state.social) == set(empty_slice())


def test_seeded_defaults_replay_and_fill_every_attribute(receipts_active) -> None:
    from engine.game.state import GameState
    from engine.social import creation

    def made(seed: int) -> dict:
        state = GameState()
        state.rng_seed = seed
        return creation.apply(state, {})

    first, again = made(11), made(11)
    assert first == again
    assert len(first["hobbies"]) == 2 and len(first["photos"]) == 1     # the first `min` of a seeded pick
    form = creation.form_fields()
    assert set(first["attributes"]) == set(form["attributes"])
    for name, spec in form["attributes"].items():
        assert first["attributes"][name] in {row["id"] for row in creation.options(spec)}
    # Another seed draws another default player (somewhere among its picks).
    others = [made(seed) for seed in range(12, 20)]
    assert any(o["hobbies"] != first["hobbies"] or o["attributes"] != first["attributes"] for o in others)


@pytest.mark.parametrize("payload, field", [
    ({"age": True}, "age"),                                        # a bool is not a number
    ({"age": "30"}, "age"),
    ({"age": 76}, "age"),
    ({"name": "x" * 25}, "name"),
    ({"name": 5}, "name"),
    ({"hobbies": ["no_such_hobby", "also_not"]}, "hobbies"),
    ({"photos": []}, "photos"),
    ({"attributes": {"wings": "yes"}}, "attributes.wings"),
    ({"attributes": "tall"}, "attributes"),
    ({"personality": {"grumpy": 2}}, "personality.grumpy"),
    ({"personality": {"outgoing": 0}}, "personality.outgoing"),
    ({"discovery": {"age_min": 17}}, "discovery.age_min"),
    ({"discovery": {"age_min": 40, "age_max": 30}}, "discovery"),
    ({"discovery": {"distance": "moon"}}, "discovery.distance"),
])
def test_more_bad_values_are_refused_naming_their_field(receipts_active, payload, field) -> None:
    from engine.game.state import GameState
    from engine.social import creation

    state = GameState()
    with pytest.raises(creation.CreationError) as err:
        creation.apply(state, payload)
    assert err.value.field == field
    assert state.social == {}                                    # nothing written on a refusal


def test_a_hobby_named_twice_is_refused(receipts_active) -> None:
    from engine.game.state import GameState
    from engine.social import creation
    from engine.social.population import table

    one = table("hobbies")[0]["id"]
    with pytest.raises(creation.CreationError) as err:
        creation.apply(GameState(), {"hobbies": [one, one]})
    assert err.value.field == "hobbies"


def test_a_payload_that_is_not_an_object_is_refused(receipts_active) -> None:
    from engine.game.state import GameState
    from engine.social import creation

    with pytest.raises(creation.CreationError) as err:
        creation.apply(GameState(), ["age", 30])
    assert err.value.field == "creation"


def test_social_profile_is_engine_only_and_writes_once(receipts_active) -> None:
    from engine.game.effects import ENGINE_ONLY_EFFECTS, apply_effect
    from engine.game.state import GameState
    from engine.social import creation

    assert "social_profile" in ENGINE_ONLY_EFFECTS
    state = GameState()
    creation.apply(state, {"age": 33})
    second = apply_effect(state, {"type": "social_profile", "profile": {"age": 50}})
    assert second["ok"] is False and state.social["player"]["age"] == 33
    with pytest.raises(creation.CreationError):
        creation.apply(state, {})


def test_new_game_state_refuses_creation_in_a_story_without_a_form() -> None:
    from engine.game import procgen
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        with pytest.raises(ValueError, match="this story has no creation form"):
            procgen.new_game_state(player_name="Sam", seed=1, creation={"age": 30})
        state = procgen.new_game_state(player_name="Sam", seed=1)
        assert state.social == {}
    finally:
        registry.deactivate()


def test_the_form_serves_inline_choices_as_rows_and_keeps_the_age_floor_as_data(receipts_active) -> None:
    from engine.scenes.default_scene import create_app

    _, app = create_app(testing=True)
    form = app.test_client().get("/api/social/creation").get_json()["fields"]
    assert form["age"]["min"] == 18 and form["discovery"]["age_min"]["min"] == 18
    assert {row["id"] for row in form["attributes"]["smokes"]["of"]} == {"no", "sometimes", "yes"}
    assert form["attributes"]["hair"]["of"] and all(row["label"] for row in form["attributes"]["hair"]["of"])
    assert form["personality"]["of"][0] == "outgoing"


def test_an_http_creation_that_is_not_an_object_is_a_400(receipts_active) -> None:
    from engine.scenes.default_scene import create_app

    _, app = create_app(testing=True)
    resp = app.test_client().post("/api/game/new", json={"creation": "hello"})
    assert resp.status_code == 400 and resp.get_json()["error"].startswith("creation:")


def test_the_shipped_creation_form_validates_clean() -> None:
    from engine.games.validation import errors_only, validate_story

    errors = [i for i in errors_only(validate_story("read-receipts")) if i.source == "social/creation.yaml"]
    assert errors == []


def _broken(data: dict, how: str) -> str:
    fields = data["fields"]
    if how == "of_table":
        fields["attributes"]["hair"]["of_table"] = "no_such_table"
        return "fields.attributes.hair"
    if how == "kind":
        fields["age"]["kind"] = "number"
        return "fields.age"
    if how == "default":
        fields["sex"]["default"] = "neither"
        return "fields.sex"
    if how == "int_default":
        fields["age"]["default"] = 12
        return "fields.age"
    if how == "boolean_of":
        fields["attributes"]["smokes"]["of"] = [False, "sometimes", True]
        return "fields.attributes.smokes"
    if how == "drawn_not_offered":
        fields["attributes"]["build"]["of"] = ["slim", "average"]
        return "fields.attributes.build"
    if how == "text_max":
        del fields["name"]["max"]
        return "fields.name"
    if how == "min_above_max":
        fields["hobbies"]["min"], fields["hobbies"]["max"] = 5, 3
        return "fields.hobbies"
    if how == "max_over_choices":
        fields["photos"]["max"] = 10_000
        return "fields.photos"
    if how == "start_hour":
        data["start_hour"] = 24                      # T16: a whole hour 0-23
        return "start_hour"
    if how == "discovery_defaults":
        fields["discovery"]["age_min"]["default"] = 50
        fields["discovery"]["age_max"]["default"] = 30
        return "fields.discovery"
    raise AssertionError(how)


@pytest.mark.parametrize("how", ["of_table", "kind", "default", "int_default", "boolean_of", "drawn_not_offered",
                                 "text_max", "min_above_max", "max_over_choices", "discovery_defaults",
                                 "start_hour"])
def test_a_broken_creation_form_is_an_error_naming_its_field(tmp_path, how) -> None:
    import shutil

    import yaml

    from engine import yamlio
    from engine.games import registry
    from engine.games.validation import StoryValidator

    social_dir = ROOT / "games" / "read-receipts" / "data" / "social"
    shutil.copy(social_dir / "population.yaml", tmp_path / "population.yaml")
    data = copy.deepcopy(yamlio.safe_load((social_dir / "creation.yaml").read_text(encoding="utf-8")))
    key = _broken(data, how)
    (tmp_path / "creation.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    validator = StoryValidator(registry.get("read-receipts"))
    validator._check_creation(tmp_path)
    named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
    assert ("social/creation.yaml", key) in named, validator.issues


def test_one_identity_the_creation_name_is_the_players_name(receipts_active) -> None:
    """v0.22.0 T4 ruling, wired in T27: a new game's player_name (not the engine default) seeds
    creation.name's default, and the run's player_name is the creation's name."""
    from engine.game import procgen

    seeded = procgen.new_game_state(player_name="Ash", seed=1)
    assert seeded.social["player"]["name"] == "Ash" and seeded.player_name == "Ash"
    # The creation's own name wins over player_name.
    named = procgen.new_game_state(player_name="Ash", seed=1, creation={"name": "Kai"})
    assert named.social["player"]["name"] == "Kai" and named.player_name == "Kai"
    # The engine's default names nobody: the form's default stands, for both.
    plain = procgen.new_game_state(seed=1)
    assert plain.social["player"]["name"] == "Sam" and plain.player_name == "Sam"
    # A player_name the form would refuse (over its max) is not seeded: no new refusal.
    long = procgen.new_game_state(player_name="x" * 40, seed=1)
    assert long.social["player"]["name"] == "Sam" and long.player_name == "Sam"


def test_one_identity_over_http(receipts_active) -> None:
    from engine.scenes.default_scene import create_app

    scene, app = create_app(testing=True)
    client = app.test_client()
    made = client.post("/api/game/new", json={"player_name": "Ash", "seed": 2}).get_json()
    state = scene.store.require(made["session_id"]).engine.state
    assert (state.player_name, state.social["player"]["name"]) == ("Ash", "Ash")
    made = client.post("/api/game/new", json={"player_name": "Robin", "seed": 2, "creation": {"name": "Robin"}}).get_json()
    state = scene.store.require(made["session_id"]).engine.state
    assert (state.player_name, state.social["player"]["name"]) == ("Robin", "Robin")
    assert made["state"]["phone"]["player"]["name"] == "Robin"

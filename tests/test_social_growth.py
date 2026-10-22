"""Growth: depth, openness, pace and the closed disclosure vocabulary (v0.23.0 spec §6, §19.6; T2).

The rule-12 guard is STRUCTURAL (§19.6): rungs are built from a closed vocabulary in code and the
loader refuses anything else. No test here holds a word list.
"""

from __future__ import annotations

import copy

import pytest

from tests.social_fixtures import _set_person, matched, receipts_active, receipts_state  # noqa: F401


@pytest.fixture
def paced(monkeypatch):
    """Lesson 1 / pre-flight F16: the openness loops never ride the drawn pace. `_jitter` is forced to 1.0
    (before `matched` materialises the attribute), and `pin(state, pid)` stores pace 1.0 outright, so
    neither the archetype nor the traits can move a loop's count."""
    from engine.game.effects import apply_effect
    from engine.social import attrs, growth

    monkeypatch.setattr(growth, "_jitter", lambda rng: 1.0)

    def pin(state, pid: str, pace: float = 1.0) -> None:
        apply_effect(state, {"type": "social_person", "pid": pid,
                             "set": {"attrs": {**attrs.of(state, pid), "pace": pace}}})
    return pin


def _with_data(**over):
    """A copy of the loaded growth/topics/layers with `over` applied, for the load-error tests."""
    from engine import social

    data = {name: copy.deepcopy(social.data(name)) for name in ("growth", "topics", "layers")}
    for name, change in over.items():
        change(data[name])
    return data


def test_rungs_are_built_from_the_closed_vocabulary(receipts_active) -> None:
    from engine.social import growth

    loaded = _with_data()
    growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"])     # the shipped data passes
    for i, row in enumerate(loaded["growth"]["depths"]):
        assert row["id"] == growth.RUNG_IDS[i]
        assert set(row["kinds"]) <= growth.RUNGS[i][1]
        assert set(row) <= growth.DEPTH_ROW_KEYS
    for row in loaded["topics"]["topics"] + loaded["layers"]["layers"]:
        assert row["kind"] in growth.KINDS

    bad_key = _with_data(growth=lambda g: g["depths"][2].update({"willing": ["x"]}))
    with pytest.raises(ValueError, match=r"growth\.yaml: depths\[2\]: unknown key"):
        growth.check_data(bad_key["growth"], bad_key["topics"], bad_key["layers"])
    bad_kind = _with_data(topics=lambda t: t["topics"].append({"id": "t_x", "kind": "zz_q7", "label": "x"}))
    with pytest.raises(ValueError, match=r"topics\.yaml: .*kind: 'zz_q7' is not in the disclosure vocabulary"):
        growth.check_data(bad_kind["growth"], bad_kind["topics"], bad_kind["layers"])
    wrong_rung = _with_data(growth=lambda g: g["depths"][1]["kinds"].append("money"))
    with pytest.raises(ValueError, match=r"depths\[1\]\.kinds"):
        growth.check_data(wrong_rung["growth"], wrong_rung["topics"], wrong_rung["layers"])


def test_commitments_are_the_closed_enum(receipts_active) -> None:
    from engine.social import growth

    loaded = _with_data(growth=lambda g: g.__setitem__("willing", {"move_in": {"depth": 2}}))
    with pytest.raises(ValueError, match=r"willing\.move_in\.depth: only number and meet may read depth"):
        growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"])
    loaded = _with_data(growth=lambda g: g.__setitem__("willing", {"q7_unknown": {}}))
    with pytest.raises(ValueError, match="not a commitment"):
        growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"])


def test_openness_fills_and_a_rung_steps_with_a_reveal(paced, receipts_state, matched) -> None:
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    paced(receipts_state, pid)
    _set_person(receipts_state, pid, warmth=30, trust=20, episodes_done=1)
    for _ in range(60):
        growth.gain(receipts_state, pid, "exchange", mode="deep")
        if growth.depth(receipts_state, pid) == 1:
            break
    rec = growth.record(receipts_state, pid)
    assert rec["depth"] == 1 and rec["openness"] == 0.0 and rec["peak_depth"] == 1
    assert rec["reveal_due"] == "" or rec["reveal_due"].startswith("l_")


def test_a_floor_holds_a_rung_back(paced, receipts_state, matched) -> None:
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    paced(receipts_state, pid)
    _set_person(receipts_state, pid, warmth=10, trust=5, episodes_done=5)        # under everyday's floors
    for _ in range(60):
        growth.gain(receipts_state, pid, "exchange", mode="deep")
    assert growth.depth(receipts_state, pid) == 0
    assert growth.record(receipts_state, pid)["openness"] == 100.0


def test_a_cap_holds_a_breadcrumber_at_everyday(paced, receipts_state, matched, monkeypatch) -> None:
    from engine.social import behaviour, growth

    pid = matched("matchstick").split(":")[1]
    paced(receipts_state, pid)
    real = behaviour.archetype
    monkeypatch.setattr(behaviour, "archetype", lambda name: __import__("dataclasses").replace(
        real(name), growth={**real(name).growth, "cap": 1, "cap_in_person": 1}))
    _set_person(receipts_state, pid, warmth=99, trust=99, episodes_done=99, scenes_done=99)
    for _ in range(400):
        growth.gain(receipts_state, pid, "exchange", mode="deep")
    assert growth.depth(receipts_state, pid) == 1


def test_depth_never_goes_down_and_guarded_halves(paced, receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    paced(receipts_state, pid)
    plain = growth.gain(receipts_state, pid, "good_end")
    apply_effect(receipts_state, {"type": "social_growth", "op": "guard", "pid": pid})
    halved = growth.gain(receipts_state, pid, "good_end")
    assert halved == pytest.approx(plain / 2)
    # Step to depth 1 FIRST, so "never goes down" is not asserted vacuously at depth 0 (pre-flight T2 note).
    _set_person(receipts_state, pid, warmth=99, trust=99, episodes_done=9)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    assert growth.depth(receipts_state, pid) == 1
    for _ in range(20):
        growth.loss(receipts_state, pid, "fight")
    assert growth.depth(receipts_state, pid) == 1 and growth.record(receipts_state, pid)["openness"] == 0.0


def test_who_now_drops_the_bio_at_everyday(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import growth, population

    pid = matched("matchstick").split(":")[1]
    bio = next(iter(population.profile(receipts_state, pid).bio.values()))
    assert bio in growth.who_now(receipts_state, pid)
    _set_person(receipts_state, pid, warmth=99, trust=99, episodes_done=9)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    assert growth.depth(receipts_state, pid) == 1
    assert bio not in growth.who_now(receipts_state, pid)
    assert "What you still keep to yourself" in growth.who_now(receipts_state, pid)


def test_who_now_names_their_home(receipts_state, matched) -> None:
    from engine.social import growth, places

    pid = matched("matchstick").split(":")[1]
    assert places.home_label(receipts_state, pid) in growth.who_now(receipts_state, pid)


def test_growth_replays(receipts_active) -> None:
    """Each run in a FRESH state from the seed alone (the profile cache emptied between them), and
    the pace is per person: two people of the same seed do not share one (review M5)."""
    from engine.game import procgen
    from engine.social import attrs, growth, population

    def run() -> list[tuple]:
        population.reset_profiles()
        state = procgen.new_game_state(seed=77)
        return [(pid, attrs.of(state, pid)["pace"], tuple(attrs.of(state, pid)["topics"]))
                for pid in ("p0001", "p0002", "p0003")]

    first = run()
    assert first == run()
    paces = [pace for _, pace, _ in first]
    assert len(set(paces)) > 1, paces
    assert all(len(topics) == len(growth.KINDS) for _, _, topics in first)


def test_a_bad_rung_in_a_story_copy_fails_the_load(receipts_active, tmp_path, monkeypatch) -> None:
    """§19.6 "loads a story copy" (pre-flight F39): the guard is wired into `load_all`, not only callable.
    The v0.22 pattern of tests/test_social_relationships.py (copytree, `social_dir` patched, cache nulled).
    And `validate_content.py`'s check (`validation._check_growth`) reports the same fault."""
    import shutil
    from pathlib import Path

    import yaml

    from engine import social
    from engine.games import validation

    src = Path(__file__).resolve().parents[1] / "games" / "read-receipts" / "data" / "social"
    shutil.copytree(src, tmp_path / "social")
    path = tmp_path / "social" / "growth.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["depths"][1]["kinds"].append("money")                 # a family_and_future kind on everyday
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(social, "social_dir", lambda: tmp_path / "social")
    monkeypatch.setattr(social, "_DATA_CACHE", None)
    with pytest.raises(ValueError, match=r"growth\.yaml: depths\[1\]\.kinds"):
        social.load_all()
    assert social._DATA_CACHE is None
    real = validation._declared_dir
    monkeypatch.setattr(validation, "_declared_dir",
                        lambda manifest, key: tmp_path / "social" if key == "social" else real(manifest, key))
    issues = [i for i in validation.errors_only(validation.validate_story("read-receipts"))
              if i.source == "social/growth.yaml"]
    assert [i.ref_id for i in issues] == ["depths[1].kinds"]


def test_the_shipped_story_validates_clean_for_growth() -> None:
    from engine.games.validation import errors_only, validate_story

    assert [i for i in errors_only(validate_story("read-receipts"))
            if i.source in ("social/growth.yaml", "social/topics.yaml", "social/layers.yaml",
                            "social/behaviours.yaml")] == []


def test_a_trait_mult_key_must_be_a_population_trait(receipts_active) -> None:
    """Pre-flight F23: a multiplier on a trait nobody can have is refused at load."""
    from engine.social import growth

    loaded = _with_data(growth=lambda g: g.__setitem__("trait_mult", {"zz_q7_trait": 0.5}))
    with pytest.raises(ValueError, match=r"growth\.yaml: trait_mult: \['zz_q7_trait'\] are not population traits"):
        growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"], traits=frozenset({"warm", "shy"}))


def test_scene_moves_carry_no_floor_or_refusal(receipts_active) -> None:
    from engine import social

    moves = social.data("scenes")["moves"]
    for name, row in moves.items():
        assert set(row) <= {"label", "minutes", "fit", "bands"}, name
        for band in row["bands"].values():
            assert "error" not in band and "refuse" not in band and "refused" not in band, name


# -- beyond the brief's list -----------------------------------------------------------------------


def test_every_kind_has_topics_anyone_can_draw_and_every_deeper_kind_three_layers(receipts_active) -> None:
    """Nobody draws an empty kind (a row with no `when` in every kind), and every rung 1-4 kind can reveal."""
    from engine import social
    from engine.social import growth

    topics = social.data("topics")["topics"]
    layers = social.data("layers")["layers"]
    for kind in growth.KINDS:
        assert len([t for t in topics if t["kind"] == kind]) >= 2, kind
        assert any(t["kind"] == kind and not t.get("when") for t in topics), kind
    for _, kinds in growth.RUNGS[1:]:
        for kind in kinds:
            assert len([r for r in layers if r["kind"] == kind]) >= 3, kind


def test_every_when_names_a_population_id(receipts_active) -> None:
    """A misspelt id in a `when` would hold for nobody, silently: each names a real job, shape, flag or hobby."""
    from engine import social

    pop = social.data("population")
    real = {"job": {j["id"] for j in pop["jobs"]}, "job_shape": set(pop["schedules"]),
            "flag": set(pop["flags"]), "hobby": {h["id"] for h in pop["hobbies"]}}
    for row in social.data("topics")["topics"] + social.data("layers")["layers"]:
        for key, value in (row.get("when") or {}).items():
            assert key in real, (row["id"], key)          # `life` waits for T17's table
            ids = value if isinstance(value, list) else [value]
            assert set(ids) <= real[key], (row["id"], key, ids)


def test_profile_when_reads_each_key(receipts_state) -> None:
    import dataclasses

    from engine.social import growth, population

    person = dataclasses.replace(population.profile(receipts_state, "p0001"), job="nurse", job_shape="shifts",
                                 flags=("has_pet",), hobbies=("climbing", "reading"))
    assert growth.profile_when(person, {}, None) and growth.profile_when(person, {}, {})
    assert growth.profile_when(person, {}, {"job": ["nurse", "baker"], "job_shape": "shifts"})
    assert not growth.profile_when(person, {}, {"job": ["nurse"], "job_shape": ["nights"]})   # every key holds
    assert growth.profile_when(person, {}, {"flag": "has_pet", "hobby": ["sailing", "reading"]})
    assert not growth.profile_when(person, {}, {"flag": ["has_kids"]})
    assert not growth.profile_when(person, {}, {"life": ["new_job"]})
    assert growth.profile_when(person, {"life": [{"id": "new_job"}]}, {"life": ["new_job"]})


def test_a_when_value_must_be_ids(receipts_active) -> None:
    from engine.social import growth

    loaded = _with_data(layers=lambda d: d["layers"][0].__setitem__("when", {"job": [3]}))
    with pytest.raises(ValueError, match=r"layers\.yaml: layers\[0\]\.when\.job"):
        growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"])
    loaded = _with_data(layers=lambda d: d["layers"][0].__setitem__("when", {"weekday": "mon"}))
    with pytest.raises(ValueError, match=r"layers\.yaml: layers\[0\]\.when: unknown key"):
        growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"])


def test_a_count_is_never_days_and_a_floor_only_regard(receipts_active) -> None:
    """§6.4: no floor or count reads in-game days."""
    from engine.social import growth

    loaded = _with_data(growth=lambda g: g["depths"][2]["counts"].__setitem__("days", 3))
    with pytest.raises(ValueError, match=r"depths\[2\]\.counts: unknown key"):
        growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"])
    loaded = _with_data(growth=lambda g: g["depths"][3]["floors"].__setitem__("stage", "dating"))
    with pytest.raises(ValueError, match=r"depths\[3\]\.floors: unknown key"):
        growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"])
    loaded = _with_data(growth=lambda g: g.__setitem__("kinds", [*g["kinds"], "zz_q7"]))
    with pytest.raises(ValueError, match=r"growth\.yaml: kinds: must be exactly"):
        growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"])


def test_record_and_who_now_write_nothing(receipts_state, matched) -> None:
    """I14: a read path computes a fresh record and the attributes, and writes nothing."""
    import json

    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    before = json.dumps(receipts_state.to_save_dict(), sort_keys=True, default=str)
    assert growth.record(receipts_state, pid)["depth"] == 0
    growth.who_now(receipts_state, pid, in_episode_mode="deep")
    growth.topics_of(receipts_state, pid)
    assert json.dumps(receipts_state.to_save_dict(), sort_keys=True, default=str) == before
    assert "growth" not in receipts_state.social["people"][pid]


def test_the_attributes_are_materialised_at_the_match(receipts_state, matched) -> None:
    """T1's `materialise` now writes pace and topics (Plan decision 7), one per kind."""
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    stored = receipts_state.social["people"][pid]["attrs"]
    assert stored["pace"] > 0
    drawn = growth.topics_of(receipts_state, pid)
    assert sorted(t["id"] for t in drawn) == sorted(stored["topics"])
    assert len(drawn) == len(growth.KINDS) and {t["kind"] for t in drawn} == growth.KINDS


def test_pace_multiplies_archetype_traits_and_jitter(receipts_state, monkeypatch) -> None:
    import dataclasses

    from engine.social import attrs, behaviour, growth, population

    real = population.profile
    monkeypatch.setattr(population, "profile", lambda state, pid: dataclasses.replace(
        real(state, pid), archetype="romantic", traits=("warm", "shy", "curious")))
    monkeypatch.setattr(growth, "_jitter", lambda rng: 1.0)
    pace = growth._pace(receipts_state, "p0001", attrs.key(receipts_state.rng_seed, "x", "p0001", "pace"))
    assert behaviour.archetype("romantic").growth["pace"] == 1.4
    assert pace == pytest.approx(round(1.4 * 1.3 * 0.7, 4))


def test_the_guarded_count_runs_down_by_episode(paced, receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    paced(receipts_state, pid)
    plain = growth.gain(receipts_state, pid, "good_end")
    apply_effect(receipts_state, {"type": "social_growth", "op": "guard", "pid": pid})
    assert growth.record(receipts_state, pid)["guarded_left"] == 6
    for _ in range(6):
        apply_effect(receipts_state, {"type": "social_growth", "op": "tick", "pid": pid})
    assert growth.record(receipts_state, pid)["guarded_left"] == 0
    assert growth.gain(receipts_state, pid, "good_end") == pytest.approx(plain)


def test_a_ghosters_losses_are_doubled(receipts_state, matched, monkeypatch) -> None:
    import dataclasses

    from engine.social import growth, population

    pid = matched("matchstick").split(":")[1]
    real = population.profile
    for name, expected in (("steady", 10.0), ("ghoster", 20.0)):
        monkeypatch.setattr(population, "profile", lambda state, p, name=name: dataclasses.replace(
            real(state, p), archetype=name))
        assert growth.loss(receipts_state, pid, "fight") == expected


def test_step_tries_the_rung_once_a_floor_moves(paced, receipts_state, matched) -> None:
    """A full meter held by a floor steps when the floor is met and `step` is applied: no fresh gain needed."""
    from engine.game.effects import apply_effect
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    paced(receipts_state, pid)
    _set_person(receipts_state, pid, warmth=0, trust=0, episodes_done=1)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 150})
    assert growth.depth(receipts_state, pid) == 0
    _set_person(receipts_state, pid, warmth=30, trust=20)
    result = apply_effect(receipts_state, {"type": "social_growth", "op": "step", "pid": pid})
    assert result["stepped"] and growth.depth(receipts_state, pid) == 1
    history = receipts_state.social["people"][pid]["memory"]["history"]
    assert history[-1]["kind"] == "growth" and history[-1]["text"] == growth._STEP_LINES["everyday"]


def test_the_reveal_is_a_counterless_pick_of_the_rung_and_is_spent(paced, receipts_state, matched) -> None:
    from engine import social
    from engine.game.effects import apply_effect
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    paced(receipts_state, pid)
    _set_person(receipts_state, pid, warmth=99, trust=99, episodes_done=9, scenes_done=9)
    first = growth._next_layer(receipts_state, pid, 1, [])
    assert first == growth._next_layer(receipts_state, pid, 1, [])          # the same whenever asked
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    due = growth.record(receipts_state, pid)["reveal_due"]
    assert due == first
    kind = next(r["kind"] for r in social.data("layers")["layers"] if r["id"] == due)
    assert kind in growth.RUNGS[1][1]
    apply_effect(receipts_state, {"type": "social_growth", "op": "reveal", "pid": pid, "layer": due})
    rec = growth.record(receipts_state, pid)
    assert rec["revealed"] == [due] and rec["reveal_due"] == ""


def test_an_unknown_op_is_refused(receipts_state) -> None:
    from engine.game.effects import apply_effect

    assert apply_effect(receipts_state, {"type": "social_growth", "op": "zz_q7", "pid": "p0001"})["ok"] is False


def test_a_short_texter_reads_medium_once_opened_in_a_long_chat(receipts_state, matched, monkeypatch) -> None:
    import dataclasses

    from engine.game.effects import apply_effect
    from engine.social import growth, population

    pid = matched("matchstick").split(":")[1]
    real = population.profile
    monkeypatch.setattr(population, "profile", lambda state, p: dataclasses.replace(
        real(state, p), texting_style="lowercase_fast", archetype="steady"))
    assert "short messages" in growth.who_now(receipts_state, pid, in_episode_mode="deep")
    _set_person(receipts_state, pid, warmth=99, trust=99, episodes_done=9, scenes_done=9)
    for _ in range(2):
        apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    assert growth.depth(receipts_state, pid) == 2
    assert "medium-length messages" in growth.who_now(receipts_state, pid, in_episode_mode="deep")
    assert "medium-length messages" in growth.who_now(receipts_state, pid, in_episode_mode="chatting")
    assert "short messages" in growth.who_now(receipts_state, pid, in_episode_mode="quick")


def test_an_archetype_growth_block_is_checked(receipts_active) -> None:
    from engine import social
    from engine.social import behaviour

    rows = social.data("behaviours")["archetypes"]
    arcs = social.data("behaviours")["arcs"]
    for name, row in rows.items():
        assert set(behaviour.build_archetype(name, row, arcs).growth) == set(behaviour.GROWTH_KEYS)
    assert behaviour.archetype("breadcrumber").growth["cap"] == 1
    assert behaviour.archetype("dry_texter").growth["cap_in_person"] == 3
    assert behaviour.archetype("ghoster").growth["decay_mult"] == 2
    for change, match in (({"pace": 0}, r"growth\.pace: must be above 0"),
                          ({"cap": 5}, r"growth\.cap: must be 0 to 4"),
                          ({"zz_q7": 1}, r"growth: has unknown keys zz_q7")):
        row = copy.deepcopy(rows["steady"])
        row["growth"].update(change)
        with pytest.raises(ValueError, match=match):
            behaviour.build_archetype("steady", row, arcs)
    row = copy.deepcopy(rows["steady"])
    del row["growth"]
    with pytest.raises(ValueError, match=r"archetypes\.steady: is missing growth"):
        behaviour.build_archetype("steady", row, arcs)


# -- review fix round 1 (T2 review M1-M3) -----------------------------------------------------------


@pytest.mark.parametrize("call", [("gain", "good_ending"), ("gain", "zz_q7"), ("loss", "fights"),
                                  ("loss", "exchange")])
def test_an_unknown_event_is_an_error(receipts_state, matched, call) -> None:
    """M1: a misspelt caller fails loudly rather than moving nothing (checked before the stub set)."""
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    fn, event = call
    with pytest.raises(ValueError, match=rf"growth\.{fn}: '{event}' is not one of"):
        getattr(growth, fn)(receipts_state, pid, event)


@pytest.mark.parametrize("change, match", [
    (lambda g: g["depths"][1]["floors"].__setitem__("warmth", "high"), r"depths\[1\]\.floors\.warmth: must be a number"),
    (lambda g: g["depths"][1]["floors"].__setitem__("trust", -1), r"depths\[1\]\.floors\.trust: must be at least 0"),
    (lambda g: g["gain"].__setitem__("exchange", "6"), r"gain\.exchange: must be a number"),
    (lambda g: g["gain"]["moment"].__setitem__("lands", None), r"gain\.moment\.lands: must be a number"),
    (lambda g: g["gain"]["mode_mult"].__setitem__("deep", True), r"gain\.mode_mult\.deep: must be a number"),
    (lambda g: g["gain"]["mode_mult"].__setitem__("zz_q7", 1.0), r"gain\.mode_mult: unknown key"),
    (lambda g: g["gain"].__setitem__("zz_q7", 1), r"gain: unknown key"),
    (lambda g: g["loss"].__setitem__("fight", -10), r"loss\.fight: must be at least 0"),
    (lambda g: g["loss"].__setitem__("zz_q7", 1), r"loss: unknown key"),
    (lambda g: g["trait_mult"].__setitem__("shy", 0), r"trait_mult\.shy: must be above 0"),
    (lambda g: g.__setitem__("topics_per_kind", 1.5), r"topics_per_kind: must be a whole number"),
    (lambda g: g.__setitem__("topics_per_kind", -1), r"topics_per_kind: must be at least 0"),
    (lambda g: g.__setitem__("guarded_episodes", "six"), r"guarded_episodes: must be a whole number"),
    (lambda g: g["pace"].__setitem__("jitter", -0.2), r"pace\.jitter: must be at least 0"),
    (lambda g: g["pace"].__setitem__("spread", 0.2), r"pace: unknown key"),
    (lambda g: g.__setitem__("gain", [6]), r"gain: must be a mapping"),
])
def test_a_bad_value_is_a_load_error(receipts_active, change, match) -> None:
    """M2: every number is checked at load, so none raises mid-turn (`topics_per_kind` is read inside
    the match's `materialise`)."""
    from engine.social import growth

    loaded = _with_data(growth=change)
    with pytest.raises(ValueError, match=r"growth\.yaml: " + match):
        growth.check_data(loaded["growth"], loaded["topics"], loaded["layers"])


def test_the_handler_refuses_a_stranger_and_a_malformed_effect(receipts_state, matched) -> None:
    """M3: an unknown pid, a gain with no amount and a reveal with no layer are refused with a reason,
    and no people row is ever made by the handler."""
    from engine.game.effects import apply_effect
    from engine.social import growth

    people = receipts_state.social["people"]
    assert "p0999" not in people
    for op in ("gain", "step", "guard", "tick", "reveal"):
        out = apply_effect(receipts_state, {"type": "social_growth", "op": op, "pid": "p0999",
                                            "amount": 5, "layer": "l_x"})
        assert out["ok"] is False and out["text"], op
    assert "p0999" not in people
    pid = matched("matchstick").split(":")[1]
    for effect in ({"op": "gain"}, {"op": "gain", "amount": "5"}, {"op": "gain", "amount": True},
                   {"op": "reveal"}, {"op": "reveal", "layer": ""}):
        out = apply_effect(receipts_state, {"type": "social_growth", "pid": pid, **effect})
        assert out["ok"] is False and out["text"], effect
    assert "growth" not in people[pid]
    assert growth.record(receipts_state, pid)["openness"] == 0.0

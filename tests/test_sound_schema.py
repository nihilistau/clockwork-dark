"""The sound data (v0.24.0 spec §4, §5.1): the engine file, every story's, and every §4.4 fault."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from engine.games import sounds

OGG = b"OggS" + b"\x00" * 60


def _engine() -> dict[str, Any]:
    return copy.deepcopy(sounds.load_engine()["data"])


def _check_engine(data: dict[str, Any], root: Path) -> None:
    # The data under test is the engine's own, whose file rows name real files: check them in the engine's tree.
    sounds.check(data, where="sounds.yaml", root=sounds.engine_root(), story=False)


def _story(**rows: Any) -> dict[str, Any]:
    return {"version": 1, **rows}


def _check_story(data: dict[str, Any], root: Path) -> None:
    engine = sounds.load_engine()
    sounds.check(data, where="story/sounds.yaml", root=root, story=True,
                 engine_sounds=engine["data"]["sounds"], engine_root=engine["root"])


def test_the_engine_file_loads_and_binds_every_engine_event() -> None:
    loaded = sounds.load_engine()
    assert set(loaded["data"]["bind"]) == set(sounds.ENGINE_EVENTS)
    assert loaded["data"]["bind"]["plate.reveal"] is None


def test_every_declaring_story_loads() -> None:
    from engine.games import registry

    for slug, manifest in sorted(registry.discover().items()):
        if manifest.paths.get("sounds"):
            assert sounds.load_story(manifest)["data"]["version"] == 1, slug


def test_the_engine_events_are_the_specs() -> None:
    assert sounds.ENGINE_EVENTS == (
        "ui.press", "ui.toggle", "ui.open", "ui.close", "choice.pick", "choice.send", "turn.arrive",
        "roll.cast", "roll.crit_success", "roll.success", "roll.partial", "roll.failure", "roll.crit_failure",
        "alert.error", "link.lost", "link.back", "game.begin", "game.save", "game.ending", "cutscene.start",
        "encounter.start", "panel.wanted", "panel.job", "panel.casing", "plate.reveal",
    )


@pytest.mark.parametrize("edit, key", [
    (lambda d: d.update(colour=1), "colour"),
    (lambda d: d["sounds"]["ui.click"].update(volume=1), "sounds.ui.click.volume"),
    (lambda d: d["sounds"]["ui.click"]["synth"]["layers"][0].update(shape="sine"), "sounds.ui.click.synth.layers.0.shape"),
    (lambda d: d["sounds"]["ui.click"]["synth"]["layers"][0].update(freq=5), "sounds.ui.click.synth.layers.0.freq"),
    (lambda d: d["sounds"]["ui.click"]["synth"]["layers"][0].update(gain=2), "sounds.ui.click.synth.layers.0.gain"),
    (lambda d: d["sounds"]["ui.click"]["synth"]["layers"][0].update(wave="pulse"), "sounds.ui.click.synth.layers.0.wave"),
    (lambda d: d["sounds"]["ui.click"]["synth"]["layers"][0]["filter"].update(kind="x"), "sounds.ui.click.synth.layers.0.filter.kind"),
    (lambda d: d["sounds"]["ui.click"]["synth"]["layers"][0].update(decay_ms=5000), "sounds.ui.click.synth.layers.0.decay_ms"),
    (lambda d: d["sounds"]["ui.click"]["synth"].update(repeat={"times": 2, "gap_ms": 0})
     or d["sounds"]["ui.click"]["synth"]["layers"][0].update(decay_ms=3000), "sounds.ui.click.synth"),
    (lambda d: d["sounds"]["ui.click"].update(category="loud"), "sounds.ui.click.category"),
    (lambda d: d["sounds"]["ui.click"].pop("label"), "sounds.ui.click.label"),
    (lambda d: d["sounds"]["ui.click"].pop("synth"), "sounds.ui.click"),
    (lambda d: d["sounds"]["ui.click"].update(file="files/x.ogg"), "sounds.ui.click"),
    (lambda d: d["sounds"].update({"Bad Id": d["sounds"]["ui.click"]}), "sounds.Bad Id"),
    (lambda d: d["bind"].update({"ui.press": "no.such"}), "bind.ui.press"),
    (lambda d: d["bind"].pop("turn.arrive"), "bind.turn.arrive"),
    (lambda d: d["bind"].update({"made.up": "ui.click"}), "bind.made.up"),
])
def test_an_engine_fault_names_its_key(tmp_path, edit, key) -> None:
    data = _engine()
    edit(data)
    with pytest.raises(sounds.SoundError, match=f": {key.replace('.', '[.]')}:"):
        _check_engine(data, tmp_path)


def test_a_sequence_names_notes_or_hertz(tmp_path) -> None:
    data = _engine()
    data["sounds"]["roll.success"]["synth"]["sequence"]["notes"][0][1] = "H9"
    with pytest.raises(sounds.SoundError, match="sequence.notes.0"):
        _check_engine(data, tmp_path)


def _file_row(path: str, **extra: Any) -> dict[str, Any]:
    return {"category": "world", "label": "A door", "file": path,
            "fallback": {"layers": [{"wave": "noise", "attack_ms": 2, "decay_ms": 60, "gain": 0.2}]}, **extra}


def test_a_file_sound_needs_a_fallback(tmp_path) -> None:
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "door.ogg").write_bytes(OGG)
    row = _file_row("files/door.ogg")
    row.pop("fallback")
    data = _story(events={"story.door": {"label": "A door"}}, sounds={"story.door": row}, bind={"story.door": "story.door"})
    with pytest.raises(sounds.SoundError, match="sounds.story.door.fallback"):
        _check_story(data, tmp_path)


def test_a_wrong_case_file_name_is_refused(tmp_path) -> None:
    """Rule 11: `Path.exists()` is case-blind on Windows, so this passes there by listing, and fails on Linux."""
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "metallatch.ogg").write_bytes(OGG)
    assert sounds.exists_exact(tmp_path, "files/metallatch.ogg")
    assert not sounds.exists_exact(tmp_path, "files/MetalLatch.ogg")
    assert not sounds.exists_exact(tmp_path, "Files/metallatch.ogg")
    data = _story(events={"story.latch": {"label": "A latch"}},
                  sounds={"story.latch": _file_row("files/metallatch.ogg")}, bind={"story.latch": "story.latch"})
    _check_story(data, tmp_path)
    data["sounds"]["story.latch"]["file"] = "files/MetalLatch.ogg"
    with pytest.raises(sounds.SoundError, match="sounds.story.latch.file"):
        _check_story(data, tmp_path)


@pytest.mark.parametrize("path", ["files/../x.ogg", "/abs.ogg", "files\\x.ogg", "files/x.wav", "files/con.ogg"])
def test_a_file_path_must_be_plain_portable_ogg(tmp_path, path) -> None:
    data = _story(events={"story.x": {"label": "x"}}, sounds={"story.x": _file_row(path)}, bind={"story.x": "story.x"})
    with pytest.raises(sounds.SoundError, match="sounds.story.x.file"):
        _check_story(data, tmp_path)


def test_a_story_reuses_an_engine_file_by_prefix(tmp_path) -> None:
    engine = sounds.load_engine()
    files = sorted((engine["root"] / "files").rglob("*.ogg"))
    assert files, "the engine ships its Kenney files since v0.24.0 T7"
    rel = files[0].relative_to(engine["root"]).as_posix()
    data = _story(events={"story.x": {"label": "x"}}, sounds={"story.x": _file_row(f"engine:{rel}")},
                  bind={"story.x": "story.x"})
    _check_story(data, tmp_path)


@pytest.mark.parametrize("data, key", [
    (_story(events={"phone.ring": {"label": "r"}}, bind={}), "bind.phone.ring"),
    (_story(bind={"phone.ring": "ui.click"}), "bind.phone.ring"),
    (_story(events={"roll.extra": {"label": "r"}}, bind={"roll.extra": "ui.click"}), "events.roll.extra"),
    (_story(events={"phone.ring": {"label": "r"}},
            sounds={"ring.a": {"category": "phone", "label": "a", "synth": {"layers": [{"wave": "sine", "freq": 880, "decay_ms": 50}]}}},
            bind={"phone.ring": {"default": "ring.a", "choices": ["ring.a", "ui.click"]}}), "bind.phone.ring.choices"),
])
def test_a_story_fault_names_its_key(tmp_path, data, key) -> None:
    with pytest.raises(sounds.SoundError, match=f": {key.replace('.', '[.]')}"):
        _check_story(data, tmp_path)


def test_a_story_overrides_and_rebinds() -> None:
    story = {"version": 1, "events": {"story.bell": {"label": "A bell"}},
             "sounds": {"ui.click": {"category": "ui", "label": "Tick", "synth": {"layers": [{"wave": "sine", "freq": 900, "decay_ms": 20}]}},
                        "story.bell": {"category": "world", "label": "Bell", "synth": {"layers": [{"wave": "sine", "freq": 660, "decay_ms": 400}]}}},
             "bind": {"turn.arrive": "story.bell", "story.bell": "story.bell"}}
    out = sounds.merge(sounds.load_engine(), {"data": story, "root": Path("."), "scope": "probe", "file": "probe/sounds.yaml"})
    assert out["sounds"]["ui.click"]["label"] == "Tick" and out["sounds"]["ui.click"]["overrides"] is True
    assert out["bind"]["turn.arrive"] == "story.bell" and out["bind"]["story.bell"] == "story.bell"
    assert "story.bell" in out["events"] and out["events"][: len(sounds.ENGINE_EVENTS)] == list(sounds.ENGINE_EVENTS)
    assert out["sounds"]["story.bell"]["key"] == "probe/sounds.yaml › sounds › story.bell"


def test_merged_for_a_story_with_no_sounds_is_the_engines() -> None:
    from engine.games import registry

    assert sounds.merged(registry.get("dev-story")) == sounds.merged(None)


def test_the_cache_is_cleared_with_the_story_caches() -> None:
    from engine.games import caches

    assert ("engine.games.sounds", "_load_file") in caches.LRU_CACHES
    assert ("engine.games.sounds", "warm") in caches.WARMERS


# -- fix round 1 (T3 review) -------------------------------------------------------------------------------------

@pytest.mark.parametrize("edit, key", [
    (lambda d: d.update(sounds=["ui.click"]), "sounds"),
    (lambda d: d.update(bind=["ui.press"]), "bind"),
    (lambda d: d["bind"].update({"ui.press": {"default": ["x"], "choices": ["ui.click"]}}), "bind.ui.press"),
    (lambda d: d["bind"].update({"ui.press": {"default": "ui.click", "choices": [["x"]]}}), "bind.ui.press"),
    (lambda d: d["bind"].update({"ui.press": ["ui.click"]}), "bind.ui.press"),
    (lambda d: d["bind"].update({"ui.press": {"default": {"a": 1}, "choices": []}}), "bind.ui.press"),
])
def test_a_malformed_shape_is_a_sound_error_not_a_type_error(tmp_path, edit, key) -> None:
    data = _engine()
    edit(data)
    with pytest.raises(sounds.SoundError) as caught:
        _check_engine(data, tmp_path)
    assert caught.value.key == key and caught.value.file == "sounds.yaml"


def test_a_story_events_that_is_a_list_is_a_sound_error(tmp_path) -> None:
    with pytest.raises(sounds.SoundError) as caught:
        _check_story(_story(events=[["a"]], bind={}), tmp_path)
    assert caught.value.key == "events"


def test_a_sound_error_keeps_its_parts() -> None:
    err = sounds.SoundError("a.yaml", "bind.x", "is wrong")
    assert (err.file, err.key, err.message) == ("a.yaml", "bind.x", "is wrong")
    assert str(err) == "a.yaml: bind.x: is wrong"


def _manifest(tmp_path: Path, text: str):
    from types import SimpleNamespace

    story = tmp_path / "story_sounds"
    story.mkdir()
    (story / "sounds.yaml").write_text(text, encoding="utf-8")
    return SimpleNamespace(paths={"sounds": "story_sounds"}, slug="probe", resolve=lambda rel: tmp_path / rel)


@pytest.mark.parametrize("text, key", [
    ("version: [unclosed\n", "yaml"),
    ("version: 1\nevents:\n  phone.ring: {label: r}\nbind: {}\n", "bind.phone.ring"),
    ("version: 1\nbind:\n  ui.press: no.such\n", "bind.ui.press"),
])
def test_the_story_validator_reports_a_bad_sounds_file(tmp_path, text, key) -> None:
    from engine.games.validation import StoryValidator

    validator = StoryValidator(_manifest(tmp_path, text))
    validator.check_sounds()
    assert [(i.source, i.ref_id) for i in validator.issues] == [("story_sounds/sounds.yaml", key)]
    assert validator.issues[0].severity == "error"


def test_a_sounds_file_not_in_utf8_is_reported(tmp_path) -> None:
    """Re-review R1: a file that is not UTF-8 is a fault named on the file, not a traceback."""
    from engine.games.validation import StoryValidator

    manifest = _manifest(tmp_path, "version: 1\n")
    (tmp_path / "story_sounds" / "sounds.yaml").write_bytes(b"version: 1\nlabel: \xff\xfe\n")
    validator = StoryValidator(manifest)
    validator.check_sounds()
    assert [(i.source, i.ref_id) for i in validator.issues] == [("story_sounds/sounds.yaml", "yaml")]


def test_the_story_validator_passes_a_good_sounds_file(tmp_path) -> None:
    from engine.games.validation import StoryValidator

    validator = StoryValidator(_manifest(tmp_path, "version: 1\n"))
    validator.check_sounds()
    assert validator.issues == []


def test_a_malformed_yaml_is_a_sound_error(tmp_path, monkeypatch) -> None:
    (tmp_path / "sounds.yaml").write_text("sounds: [oops\n", encoding="utf-8")
    monkeypatch.setattr(sounds, "engine_root", lambda: tmp_path)
    with pytest.raises(sounds.SoundError):
        sounds.load_engine()


def test_a_file_is_checked_once_per_edit(monkeypatch) -> None:
    from engine.games import registry

    real = sounds.check
    calls: list[str] = []
    monkeypatch.setattr(sounds, "check", lambda *a, **k: (calls.append(k["where"]), real(*a, **k))[1])
    sounds._load_file.cache_clear()
    manifest = registry.get("dev-story")
    for _ in range(3):
        sounds.merged(manifest)
    assert calls.count(f"{sounds._engine_rel()}/sounds.yaml") == 1


def test_a_returned_dict_is_the_callers_own() -> None:
    first = sounds.merged(None)
    first["sounds"]["ui.click"]["label"] = "changed"
    first["sounds"]["ui.click"]["synth"]["layers"][0]["freq"] = 1
    first["bind"]["ui.press"] = "changed"
    first["limits"]["voices"] = -1
    loaded = sounds.load_engine()
    loaded["data"]["sounds"]["ui.click"]["synth"]["layers"][0]["freq"] = 2
    again = sounds.merged(None)
    assert again["sounds"]["ui.click"]["label"] != "changed"
    assert again["sounds"]["ui.click"]["synth"]["layers"][0]["freq"] not in (1, 2)
    assert again["bind"]["ui.press"] != "changed" and again["limits"]["voices"] != -1
    assert sounds.load_engine()["data"]["sounds"]["ui.click"]["synth"]["layers"][0]["freq"] != 2

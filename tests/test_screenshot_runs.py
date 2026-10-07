"""
``scripts/screenshot_runs.py``: the README's runs, built deterministically
(v0.21.0, spec §11). No model (each story's own fallback narration answers),
no browser, no owner storage.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("screenshot_runs", REPO / "scripts" / "screenshot_runs.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, root: Path) -> None:
    """The data dir is `root`, the config dir a temp one; both restored after."""
    import engine.config as config

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(root))
    monkeypatch.delenv("CLOCKWORK_CONFIG", raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(config, "_instance", None)


def _no_build(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("a refused run must never reach the build")


def test_it_refuses_without_a_fresh_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    runs = _script()
    import engine.config as config

    # A regression falls into pin_config and a build: both are contained.
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(config, "_instance", None)
    monkeypatch.delenv("CLOCKWORK_CONFIG", raising=False)
    monkeypatch.setattr(runs, "build_runs", _no_build)
    root = tmp_path / "shots"
    monkeypatch.delenv("CLOCKWORK_DATA_DIR", raising=False)
    assert runs.main(["--root", str(root)]) == 2
    assert "CLOCKWORK_DATA_DIR" in capsys.readouterr().err

    root.mkdir()
    (root / "saves").mkdir()
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(root))
    assert runs.main(["--root", str(root)]) == 2
    assert "not empty" in capsys.readouterr().err

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "elsewhere"))
    assert runs.main(["--root", str(tmp_path / "fresh")]) == 2


def test_a_data_dir_typed_in_another_case_is_the_same_root(tmp_path: Path) -> None:
    runs = _script()
    root = tmp_path / "Shots"
    assert runs._same_path(str(root), root)
    assert runs._same_path(str(root) + "/", root)
    assert not runs._same_path(str(tmp_path / "other"), root)
    # A root not made yet keeps the case it was typed in: on Windows one
    # directory either way (rule 11), elsewhere two.
    assert runs._same_path(str(root).upper(), root) is (os.name == "nt")


def test_the_pin_is_the_only_layer_and_holds_every_service_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _script()
    import engine.config as config

    root = tmp_path / "shots"
    _isolate(monkeypatch, tmp_path, root)
    assert runs.pin_config(root) == root / "config"
    cfg = config.get_config()
    assert cfg.get("llm.base_url") == config.TEST_SANDBOX_BASE_URL
    assert cfg.get("llm.api_key") == ""
    assert cfg.get("llm.mcp.enabled") is False
    assert cfg.get("comfyui.enabled") is False
    assert cfg.get("tts.enabled") is False and cfg.get("tts.assistant_enabled") is False
    for block in ("comfyui", "tts", "stt"):
        assert cfg.get(f"{block}.base_url") == config.TEST_SANDBOX_SERVICE_URL, block
    assert cfg.get("media.live_generation") is False
    services = cfg.get("stack.services") or {}
    assert services and all(spec.get("manage") is False for spec in services.values()), services
    assert cfg.get("world.tick_interval_seconds") == runs.TICK_NEVER_SECONDS
    config._instance = None


def test_a_set_clockwork_config_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Its files merge ABOVE local.yaml, so they would override the pin."""
    runs = _script()

    root = tmp_path / "shots"
    _isolate(monkeypatch, tmp_path, root)
    layer = tmp_path / "theirs.yaml"
    layer.write_text("llm:\n  base_url: http://example.invalid/v1\n", encoding="utf-8")
    monkeypatch.setenv("CLOCKWORK_CONFIG", str(layer))
    with pytest.raises(runs.ScriptStop, match="CLOCKWORK_CONFIG"):
        runs.pin_config(root)
    monkeypatch.setattr(runs, "build_runs", _no_build)
    assert runs.main(["--root", str(tmp_path / "fresh")]) == 2  # data dir differs: refused before
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "fresh"))
    assert runs.main(["--root", str(tmp_path / "fresh")]) == 2
    assert "CLOCKWORK_CONFIG" in capsys.readouterr().err


def test_offered_is_the_choice_carrying_the_move_whatever_its_id() -> None:
    """Ruling C8: never a fall-back to "a"."""
    runs = _script()
    turn = {
        "choices": [
            {"id": "a", "text": "Check lore", "intent": {"action": "check", "target": "lore"}},
            {"id": "b", "text": "Look", "intent": None},
            {"id": "c", "text": "Go", "intent": {"action": "travel", "target": "ghost_alley"}},
        ]
    }
    assert runs._offered(turn, ("intent", "travel", "", "required")) == "c"
    assert runs._offered(turn, ("intent", "travel", "ghost_alley", "required")) == "c"
    assert runs._offered(turn, ("intent", "travel", "elsewhere", "required")) is None
    assert runs._offered(turn, ("intent", "burgle", "", "required")) is None
    assert runs._offered({"choices": [{"id": "a", "text": "Look"}]}, ("intent", "travel", "", "required")) is None


def _ends(story: str, save_id: str) -> Any:
    """The state a built save holds, loaded as the capture's server loads it."""
    from engine.games import registry
    from engine.scenes.default_scene import get_store, reset_store

    registry.activate(story)
    try:
        reset_store()
        session = get_store().resume(save_id, llm_fn=lambda *_a, **_k: "{}")
        return session.engine.state
    finally:
        registry.deactivate()
        reset_store()


def test_every_scripted_move_is_in_its_turns_enum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each run is played to its end and reaches what its capture shows."""
    runs = _script()
    import engine.config as config
    from engine.content import director
    from engine.game.intents import legal_intents
    from engine.games import registry
    from engine.world import jobs, law

    root = tmp_path / "shots"
    _isolate(monkeypatch, tmp_path, root)
    built = runs.build_runs(root)
    assert sorted(built) == sorted(runs.STORIES)
    for story, tags in runs.RUNS.items():
        assert sorted(built[story]) == sorted(tags), story
    written = json.loads((root / runs.RUNS_FILE).read_text(encoding="utf-8"))
    assert written == built

    def end(story: str, tag: str) -> Any:
        return _ends(story, built[story][tag]["save_id"])

    # One save row per run, each its own name.
    for story, tags in built.items():
        assert len({row["player"] for row in tags.values()}) == len(tags), story

    # Each run plays its story's NAMED archetype, not the manifest's default
    # (T5 re-review: nothing checked the saved state carried it).
    for story, tags in built.items():
        for tag in tags:
            assert end(story, tag).archetype == runs.ARCHETYPES[story], (story, tag)

    # Every travel run left where it started.
    for story in ("clockwork-dark", "neon-city", "the-long-con", "dev-story"):
        entry = registry.activate(story).entry_location
        registry.deactivate()
        assert end(story, "play").location_id != entry, story

    # The layout's encounter run stands in an open encounter, reached by
    # engine-offered travel only.
    from engine.game import encounter

    assert encounter.active(end("clockwork-dark", "encounter")), "the encounter run reached no encounter"
    # HUE & CRY's stands in the Law's watch stop, reached by a caught job
    # (v0.21.0 T10): the stop the approach buttons are pressed in.
    stop = end("hue-and-cry", "encounter")
    assert encounter.active(stop) and stop.encounter["id"] == "watch_stop", stop.encounter

    panels = end("hue-and-cry", "panels")
    assert panels.location_id == "silk_row"
    assert jobs.active(panels), "the panels run has no job under way"
    assert not law.in_custody(panels)
    play = end("hue-and-cry", "play")
    assert not law.in_custody(play)

    # The poster's painted states: a non-zero band at the Lantern House, and
    # custody before the fine is paid -- by engine-offered intents only.
    wanted = end("hue-and-cry", "wanted")
    assert wanted.location_id == "lantern_house"
    registry.activate("hue-and-cry")
    try:
        guise = law.current_guise(wanted)
        bands = {law.wanted_band(wanted, guise, name) for name in law.load_spec()["jurisdictions"]}
    finally:
        registry.deactivate()
    assert "wanted" in bands, bands
    held = end("hue-and-cry", "held")
    assert law.in_custody(held)

    deck = end("wicked-garden", "deck")
    assert director.active(deck), "the deck run shows no card"
    garden = end("wicked-garden", "play")
    assert not director.active(garden), "the prologue is still being dealt"
    assert "card" not in {verb.action for verb in legal_intents(garden)}
    assert garden.location_id != "mortal_threshold"
    config._instance = None


def test_a_missing_intent_stops_the_script_and_names_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _script()
    import engine.config as config

    root = tmp_path / "shots"
    _isolate(monkeypatch, tmp_path, root)
    monkeypatch.setitem(runs.RUNS, "dev-story", {"play": (("intent", "no_such_verb", ""),)})
    with pytest.raises(runs.ScriptStop, match="no_such_verb"):
        runs.build_runs(root, stories=["dev-story"])
    config._instance = None


def test_a_move_missing_mid_run_stops_at_the_scripted_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Director's own check: the move after a played one is not in that turn's enum."""
    runs = _script()
    import engine.config as config

    root = tmp_path / "shots"
    _isolate(monkeypatch, tmp_path, root)
    seen: list[str] = []
    real = runs.Director.__call__

    def spy(self: Any, *a: Any, **k: Any) -> str:
        reply = real(self, *a, **k)
        if self.missing:
            seen.append(self.missing)
        return reply

    monkeypatch.setattr(runs.Director, "__call__", spy)
    monkeypatch.setitem(runs.RUNS, "dev-story", {"play": (("intent", "travel", ""), ("intent", "no_such_verb", ""))})
    with pytest.raises(runs.ScriptStop, match="no_such_verb"):
        runs.build_runs(root, stories=["dev-story"])
    assert seen and seen[0] == "no_such_verb"
    config._instance = None


def test_a_target_the_turn_does_not_offer_stops_the_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _script()
    import engine.config as config

    root = tmp_path / "shots"
    _isolate(monkeypatch, tmp_path, root)
    monkeypatch.setitem(runs.RUNS, "dev-story", {"play": (("intent", "travel", "no_such_place"),)})
    with pytest.raises(runs.ScriptStop, match="no_such_place"):
        runs.build_runs(root, stories=["dev-story"])
    monkeypatch.setitem(
        runs.RUNS, "dev-story", {"play": (("intent", "travel", ""), ("intent", "travel", "no_such_place"))}
    )
    with pytest.raises(runs.ScriptStop, match="no_such_place"):
        runs.build_runs(tmp_path / "again", stories=["dev-story"])
    config._instance = None


def test_an_offer_step_offers_every_target_and_presses_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    ("offer", action) (v0.21.0 T10): the last reply carries the move on every
    legal target, nothing presses it, and a move the engine does not offer
    stops the script.
    """
    runs = _script()
    import engine.config as config
    from engine.game.intents import legal_intents

    root = tmp_path / "shots"
    _isolate(monkeypatch, tmp_path, root)
    replies: list[tuple[list[str], list[dict[str, Any]]]] = []
    real = runs.Director.__call__

    def spy(self: Any, *a: Any, **k: Any) -> str:
        reply = real(self, *a, **k)
        legal = [t for v in legal_intents(self.state()) if v.action == "travel" for t in v.targets]
        replies.append((legal, json.loads(reply)["choices"]))
        return reply

    monkeypatch.setattr(runs.Director, "__call__", spy)
    monkeypatch.setitem(runs.RUNS, "dev-story", {"play": (("intent", "travel", ""), ("offer", "travel"))})
    built = runs.build_runs(root, stories=["dev-story"])
    # One turn was played (the travel); the offer step pressed nothing.
    assert _ends("dev-story", built["dev-story"]["play"]["save_id"]).turn_number == 1
    legal, choices = replies[-1]
    offered = [c["intent"]["target"] for c in choices if (c.get("intent") or {}).get("action") == "travel"]
    # The scripted reply offers every legal target (the turn's cap applies later).
    assert offered == list(legal) and offered, (offered, legal)

    monkeypatch.setitem(runs.RUNS, "dev-story", {"play": (("intent", "travel", ""), ("offer", "no_such_verb"))})
    with pytest.raises(runs.ScriptStop, match="no_such_verb"):
        runs.build_runs(tmp_path / "again", stories=["dev-story"])
    config._instance = None


def test_an_offer_step_stops_when_a_target_is_lost_on_the_way(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every legal target must reach the turn's choices (the merge once displaced one)."""
    runs = _script()
    import engine.config as config
    import engine.scenes.default_state as default_state

    root = tmp_path / "shots"
    _isolate(monkeypatch, tmp_path, root)
    real = default_state.merge_choices

    def lossy(result: Any, narrated: Any, **k: Any) -> Any:
        merged = real(result, narrated, **k)
        intents = [i for i, c in enumerate(merged) if c.get("intent")]
        return [c for i, c in enumerate(merged) if not intents or i != intents[-1]]

    monkeypatch.setattr(default_state, "merge_choices", lossy)
    monkeypatch.setitem(runs.RUNS, "dev-story", {"play": (("intent", "travel", ""), ("offer", "travel"))})
    with pytest.raises(runs.ScriptStop, match="not every legal target"):
        runs.build_runs(root, stories=["dev-story"])
    config._instance = None


def test_an_offer_step_must_be_last() -> None:
    runs = _script()
    with pytest.raises(runs.ScriptStop, match="must be a run's last"):
        runs.expand((("offer", "travel"), ("intent", "travel", "")))
    assert runs.expand((("intent", "travel", ""), ("offer", "travel")))[-1] == ("intent", "travel", "", "offer")


def test_serve_refuses_a_port_that_already_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A second server on a served port would let a stale one answer the gate (T8 review 4)."""
    import socket

    runs = _script()
    root = tmp_path / "shots"
    root.mkdir()
    (root / runs.RUNS_FILE).write_text("{}", encoding="utf-8")
    _isolate(monkeypatch, tmp_path, root)
    monkeypatch.setattr(runs, "pin_config", lambda _root: None)

    def never_started(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a refused serve must not start an app")

    monkeypatch.setattr("engine.scenes.default_scene.create_app", never_started)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen(8)
        port = held.getsockname()[1]
        assert runs.port_answers(port)
        assert runs.main(["--root", str(root), "--serve", "dev-story", "--port", str(port)]) == 2
        assert "already served" in capsys.readouterr().err
    assert not runs.port_answers(port)
    assert not list(root.glob("serve-*.json"))


def test_a_server_notes_its_own_identity(tmp_path: Path) -> None:
    from engine.hosting import process_identity

    runs = _script()
    path = runs._record_identity(tmp_path, 8791)
    noted = json.loads(path.read_text(encoding="utf-8"))
    me = process_identity.me()
    assert noted == {"pid": me.pid, "created": me.created}
    assert process_identity.alive(process_identity.Identity(noted["pid"], noted["created"]))


def test_a_server_notes_its_own_identity_and_removes_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The serve loop's `finally` removes the file, and a stale one is replaced, a live one refused."""
    from engine.hosting import process_identity

    runs = _script()
    root = tmp_path / "shots"
    root.mkdir()
    (root / runs.RUNS_FILE).write_text("{}", encoding="utf-8")
    _isolate(monkeypatch, tmp_path, root)
    monkeypatch.setattr(runs, "pin_config", lambda _root: None)

    class Scene:
        def run(self, **_k: Any) -> None:
            assert (root / "serve-8792.json").is_file(), "the file is written before the server runs"

    monkeypatch.setattr("engine.scenes.default_scene.create_app", lambda **_k: (Scene(), None))
    assert runs.main(["--root", str(root), "--serve", "dev-story", "--port", "8792"]) == 0
    assert not (root / "serve-8792.json").exists(), "the file outlived the server"

    # A file left by a dead server (no such creation time) is replaced...
    (root / "serve-8793.json").write_text(json.dumps({"pid": 999999, "created": 1.0}), encoding="utf-8")
    runs._record_identity(root, 8793)
    assert json.loads((root / "serve-8793.json").read_text(encoding="utf-8"))["pid"] == os.getpid()
    # ...and one naming a live process (this one) is refused.
    me = process_identity.me()
    (root / "serve-8794.json").write_text(json.dumps({"pid": me.pid, "created": me.created}), encoding="utf-8")
    with pytest.raises(runs.ScriptStop, match="live server"):
        runs._record_identity(root, 8794)


def test_exit_with_parent_follows_a_verified_parent_and_warns_on_one_it_cannot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import subprocess
    import sys
    import threading

    from engine.hosting import process_identity

    runs = _script()
    record = tmp_path / "serve-1.json"
    record.write_text("{}", encoding="utf-8")
    left = threading.Event()

    # A parent that is its own process: noted while it runs, then ended by
    # this test through its own handle once the identity is taken. It used
    # to live 1.5 s on its own, and on a loaded runner it could exit before
    # `identify` read it (final review finding 30).
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        parent = process_identity.identify(child.pid)
        assert parent.created is not None
        thread = runs._exit_with_parent(record, parent=parent, poll=0.1, leave=lambda _code: left.set())
        assert thread is not None
        child.terminate()
        assert left.wait(15), "the watcher never saw its parent go"
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=30)
    assert not record.exists(), "the identity file outlived the parent"

    # A pid reused by a stranger: same pid as a live process, but another creation time.
    record.write_text("{}", encoding="utf-8")
    left.clear()
    stranger = process_identity.Identity(os.getpid(), process_identity.me().created + 1000.0)
    runs._exit_with_parent(record, parent=stranger, poll=0.1, leave=lambda _code: left.set())
    assert left.wait(15), "a parent that started after this process was followed"

    # A parent whose creation time cannot be read is a warning, not a silent no-op.
    assert runs._exit_with_parent(record, parent=process_identity.Identity(1, None), leave=lambda _c: None) is None
    assert "cannot verify its parent" in capsys.readouterr().err

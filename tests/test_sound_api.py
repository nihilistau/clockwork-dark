"""The sound routes (v0.24.0 spec §10)."""

from __future__ import annotations

from typing import Any, Iterator

import pytest


@pytest.fixture
def client() -> Iterator[Any]:
    from engine.scenes.default_scene import create_app, reset_store

    reset_store()
    _, app = create_app(testing=True, llm_fn=lambda _m: "{}")
    yield app.test_client()


def test_the_running_storys_catalogue(client) -> None:
    body = client.get("/api/sounds").get_json()
    assert body["enabled"] is True
    assert body["bind"]["turn.arrive"] in body["sounds"]
    assert body["events"][:3] == ["ui.press", "ui.toggle", "ui.open"]
    assert body["limits"]["voices"] == 8


def test_sound_off_answers_enabled_false(client, monkeypatch) -> None:
    from engine.config import get_config

    real = get_config().get
    monkeypatch.setattr(type(get_config()), "get", lambda self, k, d=None: False if k == "sound.enabled" else real(k, d))
    assert client.get("/api/sounds").get_json() == {"enabled": False}


def test_the_catalog_lists_the_engine_and_every_story(client) -> None:
    from engine.games import registry

    body = client.get("/api/sounds/catalog").get_json()
    assert body["engine"]["sounds"]
    slugs = [row["slug"] for row in body["stories"]]
    assert slugs == sorted(registry.discover())
    dev = next(row for row in body["stories"] if row["slug"] == "dev-story")
    assert dev["declares"] is False and dev["overrides"] == []


def test_a_file_is_served_as_private_ogg(client, tmp_path, monkeypatch) -> None:
    from engine.games import sounds

    root = tmp_path / "sounds"
    (root / "files").mkdir(parents=True)
    (root / "files" / "a.ogg").write_bytes(b"OggS" + b"\x00" * 60)
    monkeypatch.setattr(sounds, "engine_root", lambda: root)
    response = client.get("/sound/_engine/files/a.ogg")
    assert response.status_code == 200
    assert response.mimetype == "audio/ogg"
    assert response.headers["Cache-Control"].startswith("private, max-age=")


@pytest.mark.parametrize("url", [
    "/sound/_engine/../config/default.yaml", "/sound/_engine/files/../../x.ogg", "/sound/no-such-story/a.ogg",
    "/sound/dev-story/a.ogg", "/sound/_engine/files/A.ogg",
    "/sound/_engine/%2e%2e/%2e%2e/a.ogg", "/sound/_engine/files%5C..%5Ca.ogg", "/sound/_engine/files%5Ca.ogg",
    "/sound/_engine/files/a.txt",
])
def test_anything_else_is_404(client, tmp_path, monkeypatch, url) -> None:
    from engine.games import sounds

    root = tmp_path / "sounds"
    (root / "files").mkdir(parents=True)
    (root / "files" / "a.ogg").write_bytes(b"OggS" + b"\x00" * 60)
    (root / "files" / "a.txt").write_text("x")
    (tmp_path / "a.ogg").write_bytes(b"OggS")          # a real file just above the root: traversal must not reach it
    monkeypatch.setattr(sounds, "engine_root", lambda: root)
    assert client.get(url).status_code == 404


def test_an_absolute_path_is_404(client, tmp_path, monkeypatch) -> None:
    from engine.games import sounds

    outside = tmp_path / "outside.ogg"
    outside.write_bytes(b"OggS")
    root = tmp_path / "sounds"
    root.mkdir()
    monkeypatch.setattr(sounds, "engine_root", lambda: root)
    absolute = str(outside).replace("\\", "/").lstrip("/")
    assert client.get(f"/sound/_engine/{absolute}").status_code == 404
    assert client.get(f"/sound/_engine//{absolute}", follow_redirects=True).status_code == 404


def test_a_link_out_of_the_root_is_404(client, tmp_path, monkeypatch) -> None:
    from engine.games import sounds

    outside = tmp_path / "outside.ogg"
    outside.write_bytes(b"OggS")
    root = tmp_path / "sounds"
    root.mkdir()
    try:
        (root / "link.ogg").symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks cannot be created here: {exc}")
    monkeypatch.setattr(sounds, "engine_root", lambda: root)
    assert client.get("/sound/_engine/link.ogg").status_code == 404


def test_no_active_story_uses_the_entry_manifest(client, monkeypatch) -> None:
    from engine.games import registry, sounds

    seen: list[Any] = []
    real = sounds.merged
    monkeypatch.setattr(registry, "peek", lambda: None)
    monkeypatch.setattr(registry, "active", lambda *a, **k: (_ for _ in ()).throw(AssertionError("activated")))
    marker = object()
    monkeypatch.setattr(registry, "entry_manifest", lambda: marker)
    monkeypatch.setattr(sounds, "merged", lambda m: (seen.append(m), real(None))[1])
    assert client.get("/api/sounds").status_code == 200
    assert seen == [marker]


def test_one_broken_story_does_not_sink_the_catalog(client, monkeypatch) -> None:
    from engine.games import sounds

    real = sounds.load_story
    calls: list[int] = []
    real_engine = sounds.load_engine
    monkeypatch.setattr(sounds, "load_engine", lambda: (calls.append(1), real_engine())[1])

    def load_story(manifest):
        if manifest.slug == "dev-story":
            raise sounds.SoundError("sounds.yaml", "sounds.x", "broken")
        return real(manifest)

    monkeypatch.setattr(sounds, "load_story", load_story)
    response = client.get("/api/sounds/catalog")
    assert response.status_code == 200
    rows = {row["slug"]: row for row in response.get_json()["stories"]}
    assert "broken" in rows["dev-story"]["error"]
    assert len(rows) > 1 and all("error" not in r for s, r in rows.items() if s != "dev-story")
    assert len(calls) == 1


def test_a_file_row_carries_its_provenance(client) -> None:
    body = client.get("/api/sounds/catalog").get_json()
    files = [row for row in body["engine"]["sounds"].values() if "file" in row]
    assert files
    for row in files:
        assert set(row["provenance"]) == {"author", "pack", "licence"}
        assert row["provenance"]["licence"]
        assert row["provenance"]["pack"]


def _catalogue(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"sounds": {f"s{i}": dict(row) for i, row in enumerate(rows)}}


def test_a_missing_provenance_file_gives_none_and_crashes_nothing(tmp_path, monkeypatch) -> None:
    from engine.api import sounds as api
    from engine.games import sounds

    monkeypatch.setattr(sounds, "engine_root", lambda: tmp_path)       # an empty root: no PROVENANCE.yaml
    out = api._with_urls(_catalogue({"file": "engine:files/a.ogg", "scope": "_engine"}))
    row = out["sounds"]["s0"]
    assert row["provenance"] is None
    assert row["url"] == "/sound/_engine/files/a.ogg"


def test_a_story_file_row_reads_its_own_stories_table(tmp_path, monkeypatch) -> None:
    from engine.api import sounds as api
    from engine.games import sounds

    engine, story = tmp_path / "engine", tmp_path / "story"
    engine.mkdir(); story.mkdir()
    (engine / "PROVENANCE.yaml").write_text(
        "files:\n- {path: files/door.ogg, author: Engine Author, pack: Engine Pack, licence: CC0-1.0}\n", encoding="utf-8")
    (story / "PROVENANCE.yaml").write_text(
        "files:\n- {path: files/door.ogg, author: Story Author, pack: Story Pack, licence: CC-BY-4.0}\n", encoding="utf-8")
    monkeypatch.setattr(sounds, "engine_root", lambda: engine)
    out = api._with_urls(_catalogue({"file": "files/door.ogg", "scope": "probe"},
                                    {"file": "engine:files/door.ogg", "scope": "probe"}), story)
    assert out["sounds"]["s0"]["provenance"]["pack"] == "Story Pack"
    assert out["sounds"]["s0"]["url"] == "/sound/probe/files/door.ogg"
    assert out["sounds"]["s1"]["provenance"]["pack"] == "Engine Pack"


def test_a_story_file_row_with_no_sounds_root_never_reads_the_engines_table(tmp_path, monkeypatch) -> None:
    from engine.api import sounds as api
    from engine.games import sounds

    (tmp_path / "PROVENANCE.yaml").write_text(
        "files:\n- {path: files/door.ogg, author: A, pack: P, licence: CC0-1.0}\n", encoding="utf-8")
    monkeypatch.setattr(sounds, "engine_root", lambda: tmp_path)
    out = api._with_urls(_catalogue({"file": "files/door.ogg", "scope": "probe"}), None)
    assert out["sounds"]["s0"]["provenance"] is None


def _declared_empty(tmp_path):
    from types import SimpleNamespace

    (tmp_path / "story_sounds").mkdir()
    return SimpleNamespace(paths={"sounds": "story_sounds"}, slug="probe", title="Probe",
                           resolve=lambda rel: tmp_path / rel)


def test_a_story_with_no_sounds_file_serves_the_engine_set(client, tmp_path, monkeypatch, caplog) -> None:
    """(T14 d8) A story declaring `paths.sounds` with no sounds.yaml: `/api/sounds` 500ed. It now logs a warning
    and serves the engine's set alone, and the catalogue shows the story's error row."""
    import logging

    from engine.games import registry, sounds

    manifest = _declared_empty(tmp_path)
    monkeypatch.setattr(registry, "entry_manifest", lambda: manifest)
    with caplog.at_level(logging.WARNING, logger="engine.api.sounds"):
        response = client.get("/api/sounds")
    assert response.status_code == 200
    body = response.get_json()
    assert body["enabled"] is True
    assert set(body["sounds"]) == set(sounds.merged(None)["sounds"])
    assert any("probe" in r.getMessage() and "engine's set alone" in r.getMessage() for r in caplog.records)
    real = registry.discover
    monkeypatch.setattr(registry, "discover", lambda: {**real(), "probe": manifest})
    response = client.get("/api/sounds/catalog")
    assert response.status_code == 200
    rows = {row["slug"]: row for row in response.get_json()["stories"]}
    assert "sounds.yaml is missing" in rows["probe"]["error"]

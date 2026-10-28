"""The `gallery` art kind (v0.25.0 E7, spec §6.7): an epilogue's gallery_key resolves to a plate."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.config import set_overlay


@pytest.fixture
def pack(tmp_path: Path):
    from engine.media.providers import shipped

    root = tmp_path / "art"
    (root / "gallery").mkdir(parents=True)
    (root / "gallery" / "banked-oven.jpg").write_bytes(b"\xff\xd8\xff")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.safe_dump({"root": "/static/art", "gallery": {"banked_oven": "gallery/banked-oven.jpg"}}),
                        encoding="utf-8")
    subjects = tmp_path / "subjects.yaml"
    subjects.write_text(yaml.safe_dump({"gallery": {"banked_oven": {"subject": "A banked oven at night"}}}),
                        encoding="utf-8")
    set_overlay({"paths": {"art_root": str(root), "art_manifest": str(manifest), "art_subjects": str(subjects)}})
    shipped.reset_manifest_cache()
    try:
        yield
    finally:
        set_overlay(None)
        shipped.reset_manifest_cache()


def test_a_gallery_row_resolves(pack) -> None:
    from engine.api.art import shipped_art_url

    assert shipped_art_url("banked_oven", "gallery").endswith("gallery/banked-oven.jpg")
    assert shipped_art_url("no_such_key", "gallery") == ""


def test_its_prompt_reads_the_subjects_gallery_block(pack) -> None:
    from engine.media import art

    art.reset_subjects_cache()
    assert art.render_prose("banked_oven", kind="gallery").startswith("A banked oven at night.")


def test_a_story_without_the_section_resolves_nothing_new(tmp_path: Path) -> None:
    from engine.api.art import shipped_art_url
    from engine.media.providers import shipped

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.safe_dump({"root": "/static/art"}), encoding="utf-8")
    set_overlay({"paths": {"art_root": str(tmp_path), "art_manifest": str(manifest)}})
    shipped.reset_manifest_cache()
    try:
        assert shipped_art_url("banked_oven", "gallery") == ""
    finally:
        set_overlay(None)
        shipped.reset_manifest_cache()

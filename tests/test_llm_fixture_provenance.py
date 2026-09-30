"""
Every model-server fixture says where it came from.

``tests/fixtures/llm/<provider>/`` holds a server's answers, and a test that
passes against one is only as good as the claim that the server really answers
that way. ``tests/fixtures/llm/PROVENANCE.yaml`` makes the claim explicit, file
by file: the provider, the server version, and whether the bytes were
``recorded`` from a live server or ``authored`` from its documentation (with
the page they were taken from). A fixture without a row fails here, so nothing
can be passed off as recorded by omission (spec §9.3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from engine.llm.providers import PROVIDERS

ROOT = Path(__file__).resolve().parent / "fixtures" / "llm"
PROVENANCE = ROOT / "PROVENANCE.yaml"


def _rows() -> dict[str, Any]:
    data = yaml.safe_load(PROVENANCE.read_text(encoding="utf-8")) or {}
    rows = data.get("files")
    assert isinstance(rows, dict), "PROVENANCE.yaml has no `files:` mapping"
    return rows


def _fixture_files() -> list[str]:
    """Every file under a directory named for a provider, as ``<provider>/<path>``."""
    found: list[str] = []
    for name in PROVIDERS:
        directory = ROOT / name
        if directory.is_dir():
            found += [
                path.relative_to(ROOT).as_posix()
                for path in sorted(directory.rglob("*"))
                if path.is_file()
            ]
    return found


def test_there_are_provider_fixtures_to_check() -> None:
    """Not vacuous: each non-LM Studio provider has discovery fixtures."""
    providers = {f.split("/", 1)[0] for f in _fixture_files()}
    assert {"vllm", "llamacpp", "ollama", "openai_compat"} <= providers


def test_every_fixture_file_has_a_provenance_row() -> None:
    rows = _rows()
    missing = [f for f in _fixture_files() if f not in rows]
    assert not missing, f"fixture files with no PROVENANCE.yaml row: {missing}"


def test_every_row_names_a_file_that_exists() -> None:
    gone = [f for f in _rows() if not (ROOT / f).is_file()]
    assert not gone, f"PROVENANCE.yaml rows whose file is gone: {gone}"


@pytest.mark.parametrize("fixture", sorted(_rows()))
def test_each_row_is_complete(fixture: str) -> None:
    row = _rows()[fixture]
    assert isinstance(row, dict), f"{fixture}: row is not a mapping"
    directory = fixture.split("/", 1)[0]
    assert row.get("provider") == directory, (
        f"{fixture}: provider {row.get('provider')!r} is not its directory's"
    )
    assert row["provider"] in PROVIDERS
    assert str(row.get("server_version") or "").strip(), f"{fixture}: no server_version"
    assert row.get("origin") in ("recorded", "authored"), (
        f"{fixture}: origin must be recorded or authored, not {row.get('origin')!r}"
    )
    if row["origin"] == "authored":
        source = str(row.get("source") or "")
        assert source.startswith(("https://", "http://")), (
            f"{fixture}: an authored fixture names the documentation it was "
            f"taken from; source is {source!r}"
        )


def test_vllm_is_never_labelled_recorded() -> None:
    """vLLM is not run in v0.19.0 (live in v0.20.0, owner decision)."""
    recorded = [
        f for f, row in _rows().items()
        if row.get("provider") == "vllm" and row.get("origin") != "authored"
    ]
    assert not recorded, f"vLLM fixtures not labelled authored: {recorded}"

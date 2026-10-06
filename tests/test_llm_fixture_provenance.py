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


def test_vllm_s_recorded_rows_name_the_server_that_ran_and_its_authored_ones_say_why() -> None:
    """
    vLLM was authored in v0.19.0 and run live in v0.20.0 T19 (vLLM 0.31.0):
    a recorded row names that version, the model and the date, as the
    provider cells do; a row still authored says, in its note, why no live
    vLLM could give it (a 200 error body on the list, an [IMAGE:] in the
    thinking).
    """
    vllm = {f: row for f, row in _rows().items() if row.get("provider") == "vllm"}
    recorded = {f: row for f, row in vllm.items() if row.get("origin") == "recorded"}
    assert "vllm/models.json" in recorded and len(recorded) >= 10
    for fixture, row in recorded.items():
        assert row.get("server_version") == PROVIDERS["vllm"].chat_transport.verified, fixture
        assert str(row.get("model") or "").strip() and str(row.get("recorded") or "").strip(), fixture
    for fixture, row in vllm.items():
        if row.get("origin") == "authored":
            assert str(row.get("note") or "").strip(), f"{fixture}: authored, and no note says why"


def _recorder() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "record_llm_fixtures.py"
    spec = importlib.util.spec_from_file_location("record_llm_fixtures_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_recorder_never_writes_the_operators_real_key(tmp_path: Path) -> None:
    """
    T20 (from T19's review): a fixture is committed, so the recorder scrubs
    the operator's real ``llm.api_key`` from anything a server echoes back,
    and every recorded 401 shows only the dummy key it sent on purpose.
    """
    recorder = _recorder()
    real = "sk-operator-real-key-0123456789"
    answer = {"status": 401, "json": {"error": {"message": f"bad key {real}"}},
              "request_headers": {"Authorization": f"Bearer {real}"}}
    target = tmp_path / "error_401.json"
    recorder._write(target, answer, (real,))
    written = target.read_text(encoding="utf-8")
    assert real not in written and written.count(recorder.REDACTED) == 2
    recorder._write(target, f"ndjson {real}\n", (real,))  # a stream's raw text too
    assert real not in target.read_text(encoding="utf-8")
    recorder._write(target, answer, ("",))  # no key configured: nothing to scrub
    assert real in target.read_text(encoding="utf-8")
    for provider in PROVIDERS:
        fixture = ROOT / provider / "error_401.json"
        if fixture.is_file():
            headers = yaml.safe_load(fixture.read_text(encoding="utf-8")).get("request_headers")
            # Ollama's 401 is authored (a proxy's) and records no request.
            assert headers in (None, {"Authorization": "Bearer not-the-key"}), fixture

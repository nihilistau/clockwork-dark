"""
``launcher.py`` and the model server (v0.19.0 T6, spec §8).

``_report`` against a healthy LM Studio is v0.18's text, byte for byte (T1's
``tests/fixtures/llm/golden_lmstudio/launcher_report.txt``). The model server
is the one FAIL-level service whatever its provider, so ``--check`` exits 1
when it is down -- and only then: every other service degrades a feature.

Nothing opens a socket: ``tests/llm_wire.py`` answers every request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import launcher
from tests.llm_golden import FIXTURES as GOLDEN, capture_baseline
from tests.llm_wire import wire

pytestmark = pytest.mark.real_discovery

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm"


def _ok(name: str) -> dict[str, Any]:
    return {"status": 200, "json": json.loads((FIXTURES / name).read_text(encoding="utf-8"))}


#: Per provider: a healthy server's answers.
UP: dict[str, list[dict[str, Any]]] = {
    "lmstudio": [{"status": 200, "json": {"models": [{"key": "a-model", "type": "llm"}]}}],
    "vllm": [{"status": 200, "text": ""}, _ok("vllm/models.json")],
    "llamacpp": [_ok("llamacpp/health.json")],
    "ollama": [_ok("ollama/version.json"), _ok("ollama/models_tags.json")],
    "openai_compat": [_ok("openai_compat/models.json")],
}


def test_the_lm_studio_report_is_the_v18_baseline(tmp_path: Path) -> None:
    recorded = (GOLDEN / "launcher_report.txt").read_text(encoding="utf-8")
    assert capture_baseline("launcher_report", tmp_path / "config") == recorded


@pytest.fixture
def only_the_model_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--check`` on the model server's service alone, with no game activated."""
    from engine import stack

    real = stack.load_specs
    monkeypatch.setattr(stack, "load_specs", lambda: [s for s in real() if s.model_server])
    monkeypatch.setattr(launcher, "_activate_game", lambda _slug: True)


@pytest.mark.parametrize("provider", sorted(UP))
def test_check_exits_1_when_the_model_server_is_down(
    llm_server: Any, only_the_model_server: None, provider: str, capsys: Any
) -> None:
    llm_server(provider)
    with wire([{"raise": "ConnectError", "message": "refused"}], exhaust=True):
        assert launcher.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "no narration" in out


@pytest.mark.parametrize("provider", sorted(UP))
def test_check_exits_0_when_the_model_server_is_up(
    llm_server: Any, only_the_model_server: None, provider: str
) -> None:
    llm_server(provider)
    with wire(list(UP[provider]), exhaust=True):
        assert launcher.main(["--check"]) == 0


def test_another_service_down_does_not_fail_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine import stack

    statuses = [
        stack.ServiceStatus("lmstudio", stack.STATUS_UP, "ok"),
        stack.ServiceStatus("voxtral_tts", stack.STATUS_DOWN, "ConnectError"),
    ]
    monkeypatch.setattr(stack.StackManager, "status", lambda self: statuses)
    monkeypatch.setattr(launcher, "_activate_game", lambda _slug: True)
    assert launcher.main(["--check"]) == 0


def test_the_model_server_is_named_as_the_model_server_off_lm_studio(capsys: Any) -> None:
    from engine import stack

    launcher._report([stack.ServiceStatus("llm", stack.STATUS_DOWN, "ConnectError")])
    out = capsys.readouterr().out
    assert "the model server is down" in out
    assert "LM Studio" not in out

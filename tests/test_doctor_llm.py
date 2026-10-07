"""
The doctor's model-server section, for every provider (v0.19.0 T6, spec §8).

LM Studio's section is v0.18's, byte for byte: ``LM Studio``, and the rows
recorded in ``tests/fixtures/llm/golden_lmstudio/doctor_llm.txt`` and
``doctor_services.txt`` (T1's baseline, never re-recorded). Every other
provider gets ``Model server (<provider>)`` and its own rows: liveness (the
row's health probe), the model bound, the chat probe, "reasoning off"
(trusted, untrusted or unavailable), the grammar rung, inline ``<think>``,
any set key the provider ignores, and the MCP row (spec §7).

Nothing opens a socket: ``tests/llm_wire.py`` answers every request.
"""

from __future__ import annotations

import difflib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from engine.llm.providers import PROVIDERS
from tests.llm_golden import FIXTURES as GOLDEN, capture_baseline
from tests.llm_wire import wire
from tests.test_llm_ollama import answer as ollama_answer
from tests.test_llm_ollama import discovery as ollama_discovery
from tests.test_llm_request_shaping import chat_answer, discovery, model_of

pytestmark = pytest.mark.real_discovery

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "llm"


def _ok(name: str) -> dict[str, Any]:
    return {"status": 200, "json": json.loads((FIXTURES / name).read_text(encoding="utf-8"))}


def _doctor() -> Any:
    spec = importlib.util.spec_from_file_location("doctor_under_test", REPO / "scripts" / "doctor.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


DOCTOR = _doctor()

#: Each provider's health answers, in order.
HEALTH: dict[str, list[dict[str, Any]]] = {
    "vllm": [{"status": 200, "text": ""}, _ok("vllm/models.json")],
    "llamacpp": [_ok("llamacpp/health.json")],
    "openai_compat": [_ok("openai_compat/models.json")],
    "ollama": [_ok("ollama/version.json"), _ok("ollama/models_tags.json")],
}

OLLAMA_MODEL = "qwen3:8b"


def _configure(llm_server: Any, provider: str, **llm: Any) -> str:
    """Name ``provider``, both profiles on its model, grammar set (no probe)."""
    model = OLLAMA_MODEL if provider == "ollama" else model_of(provider)
    llm.setdefault("structured_output", "json_schema")
    llm_server(provider, profiles={"big": {"model": model}, "small": {"model": model}}, **llm)
    return model


def _served(provider: str, content: str = "ready") -> list[dict[str, Any]]:
    """Health, then the chat probe: discovery and one completion."""
    if provider == "ollama":
        return HEALTH[provider] + ollama_discovery() + [ollama_answer(content)]
    return HEALTH[provider] + discovery(provider) + [chat_answer(content)]


def _rows(answers: list[dict[str, Any]]) -> tuple[Any, Any]:
    report = DOCTOR.Report()
    with wire(answers) as seam:
        DOCTOR.check_llm(report)
    return report, seam


def _by_name(report: Any) -> dict[str, tuple[str, str, str]]:
    return {name: (section, status, detail) for section, name, status, detail in report.rows}


# -- LM Studio: byte for byte ------------------------------------------------------


@pytest.mark.parametrize("name", ["doctor_llm", "doctor_services"])
def test_lm_studio_is_the_v18_baseline(name: str, tmp_path: Path) -> None:
    recorded = (GOLDEN / f"{name}.txt").read_text(encoding="utf-8")
    now = capture_baseline(name, tmp_path / "config")
    assert now == recorded, "\n".join(
        difflib.unified_diff(recorded.splitlines(), now.splitlines(), "v0.18", "now", lineterm="")
    )


# -- every other provider ----------------------------------------------------------


@pytest.mark.parametrize("provider", ["vllm", "llamacpp", "openai_compat", "ollama"])
def test_each_provider_has_its_own_section_and_rows(llm_server: Any, provider: str) -> None:
    model = _configure(llm_server, provider)
    report, _ = _rows(_served(provider))
    sections = {row[0] for row in report.rows}
    assert sections == {f"Model server ({provider})"}
    names = [row[1] for row in report.rows]
    assert names == [
        "liveness", f"model ({model})", "chat probe", "reasoning off", "grammar rung",
        "inline <think>",
    ]
    rows = _by_name(report)
    assert rows["liveness"][1] == DOCTOR.OK
    assert rows["chat probe"][1] == DOCTOR.OK, rows["chat probe"]
    assert rows["grammar rung"][2].startswith("1: json_schema")
    assert rows["inline <think>"] [1:] == (DOCTOR.OK, "none seen in the probes")
    assert not report.failed


def test_a_server_that_is_down_fails_liveness_and_asks_nothing_more(llm_server: Any) -> None:
    _configure(llm_server, "llamacpp")
    report, seam = _rows([{"status": 503, "json": json.loads(
        (FIXTURES / "llamacpp/health_loading.json").read_text(encoding="utf-8"))}])
    assert [row[1:3] for row in report.rows] == [("liveness", DOCTOR.FAIL)]
    assert report.rows[0][3].startswith("loading")
    assert len(seam.requests) == 1


def test_an_undeclared_model_gets_an_untrusted_patch(llm_server: Any) -> None:
    _configure(llm_server, "vllm")
    report, _ = _rows(_served("vllm"))
    section, status, detail = _by_name(report)["reasoning off"]
    assert status == DOCTOR.WARN
    assert detail.startswith('{"chat_template_kwargs": {"enable_thinking": false}} (untrusted)')


def test_a_declared_model_gets_a_trusted_patch(llm_server: Any) -> None:
    model = model_of("vllm")
    _configure(llm_server, "vllm", declared_models={model: {"reasoning": ["on", "off"]}})
    report, _ = _rows(_served("vllm"))
    _, status, detail = _by_name(report)["reasoning off"]
    assert status == DOCTOR.OK
    assert "(trusted)" in detail


def test_a_generic_server_without_a_body_has_no_patch(llm_server: Any) -> None:
    _configure(llm_server, "openai_compat")
    report, _ = _rows(_served("openai_compat"))
    _, status, detail = _by_name(report)["reasoning off"]
    assert status == DOCTOR.WARN
    assert detail.startswith("unavailable")
    assert "llm.reasoning_off_body" in detail


def test_the_probed_rung_is_shown(llm_server: Any) -> None:
    """``auto``: the constraint probe runs, is refused, and the rung says so."""
    _configure(llm_server, "vllm", structured_output="auto")
    refused = {"status": 400, "json": {"object": "error", "message": "no grammar"}}
    report, _ = _rows(_served("vllm") + [refused, refused])
    _, status, detail = _by_name(report)["grammar rung"]
    assert status == DOCTOR.WARN
    assert detail.startswith("3: none (llm.structured_output: auto, probed)")


@pytest.mark.parametrize(
    ("provider", "flag"),
    [("vllm", "--reasoning-parser"), ("llamacpp", "--reasoning-format")],
)
def test_inline_think_is_a_warning_naming_the_server_flag(
    llm_server: Any, provider: str, flag: str
) -> None:
    """Spec §4.5: the probe's answer arrived with its thinking in content."""
    _configure(llm_server, provider)
    report, _ = _rows(_served(provider, "<think>the user wants one word</think>ready"))
    rows = _by_name(report)
    assert rows["chat probe"][1] == DOCTOR.OK
    assert "'ready'" in rows["chat probe"][2]
    _, status, detail = rows["inline <think>"]
    assert status == DOCTOR.WARN
    assert flag in detail
    # Advice, not the matrix's condition (T6 review, finding 3).
    assert f"to stop it, {PROVIDERS[provider].inline_think_fix}" in detail
    assert "unless" not in detail


# -- the config rows: ignored keys, MCP ------------------------------------------------


def test_the_mcp_row_fails_off_lm_studio(llm_server: Any) -> None:
    _configure(llm_server, "vllm", mcp={"enabled": True})
    report, _ = _rows([{"raise": "ConnectError", "message": "down"}])
    _, status, detail = _by_name(report)["mcp"]
    assert status == DOCTOR.FAIL
    assert detail == "`llm.mcp.enabled` is set but vllm has no MCP integrations; Phase A is off"


def test_a_key_the_provider_ignores_is_a_warning(llm_server: Any) -> None:
    _configure(llm_server, "vllm", prefer_native=False, keep_alive_seconds=60)
    report, _ = _rows([{"raise": "ConnectError", "message": "down"}])
    ignored = [row for row in report.rows if row[1] == "ignored key"]
    assert [row[2] for row in ignored] == [DOCTOR.WARN, DOCTOR.WARN]
    assert "llm.prefer_native is set, but vLLM ignores it" in ignored[0][3]
    assert "llm.keep_alive_seconds is set, but vLLM ignores it" in ignored[1][3]


def test_reasoning_off_trusted_is_ignored_on_lm_studio_and_says_so(llm_server: Any) -> None:
    """T5 re-review N1: it was silently ignored there."""
    llm_server("lmstudio", declared_models={"some/model": {"reasoning_off_trusted": False}})
    report, _ = _rows([{"raise": "ConnectError", "message": "down"}])
    (row,) = [r for r in report.rows if r[1] == "ignored key"]
    assert row[0] == "LM Studio" and row[2] == DOCTOR.WARN
    assert row[3].startswith(
        "llm.declared_models.some/model.reasoning_off_trusted is set, but LM Studio ignores it"
    )


def _chain(tmp_path: Path) -> str:
    """The shipped key chain, its two files moved under ``tmp_path``."""
    general = (tmp_path / "llm_api_key.txt").as_posix()
    lm = (tmp_path / "lmstudio.txt").as_posix()
    return (
        f"${{file:{general}|lmstudio?file:{lm}|env:CLOCKWORK_LLM_API_KEY"
        "|lmstudio?env:LMSTUDIO_API_KEY}"
    )


def test_n4_a_skipped_key_file_that_holds_a_key_is_a_warning(
    llm_server: Any, tmp_path: Path
) -> None:
    """
    v0.20.0 T2 (spec §2.3, N4): LM Studio's key file is skipped off LM Studio,
    by design; the doctor now says it was, naming the source and never the
    value or its length.
    """
    secret = "lm-studio-secret-key"
    (tmp_path / "lmstudio.txt").write_text(secret + "\n", encoding="utf-8")
    llm_server("vllm", api_key=_chain(tmp_path))
    report, _ = _rows([{"raise": "ConnectError", "message": "down"}])
    rows = [row for row in report.rows if row[1] == "skipped key"]
    lm = (tmp_path / "lmstudio.txt").as_posix()
    general = (tmp_path / "llm_api_key.txt").as_posix()
    assert rows == [(
        "Model server (vllm)", "skipped key", DOCTOR.WARN,
        f"`{lm}` holds a key, but `llm.provider` is `vllm`: it is LM Studio's and "
        f"is not sent. Put this server's key in `{general}` or `CLOCKWORK_LLM_API_KEY`.",
    )]
    rendered = report.render()
    assert secret not in rendered
    # The length as a whole number, once the temp path (which carries a
    # run_tests.py basetemp's date) is out of the way.
    scrubbed = rendered.replace(str(tmp_path), "<tmp>").replace(tmp_path.as_posix(), "<tmp>")
    assert not re.search(rf"(?<!\d){len(secret)}(?!\d)", scrubbed), scrubbed


def test_n4_a_skipped_variable_that_is_set_is_a_warning(
    llm_server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm_server("vllm", api_key=_chain(tmp_path))
    monkeypatch.setenv("LMSTUDIO_API_KEY", "env-secret")
    report, _ = _rows([{"raise": "ConnectError", "message": "down"}])
    (row,) = [row for row in report.rows if row[1] == "skipped key"]
    assert row[2] == DOCTOR.WARN
    assert row[3].startswith(
        "`LMSTUDIO_API_KEY` is set, but `llm.provider` is `vllm`: it is LM Studio's"
    )
    assert "env-secret" not in report.render()


def test_n4_nothing_is_skipped_on_lm_studio_or_when_the_source_is_empty(
    llm_server: Any, tmp_path: Path
) -> None:
    (tmp_path / "lmstudio.txt").write_text("a-key\n", encoding="utf-8")
    llm_server("lmstudio", api_key=_chain(tmp_path))
    report, _ = _rows([{"raise": "ConnectError", "message": "down"}])
    assert not [row for row in report.rows if row[1] == "skipped key"]

    (tmp_path / "lmstudio.txt").write_text("\n", encoding="utf-8")
    llm_server("vllm", api_key=_chain(tmp_path))
    report, _ = _rows([{"raise": "ConnectError", "message": "down"}])
    assert not [row for row in report.rows if row[1] == "skipped key"]


def test_a_shipped_value_is_not_reported_as_set(llm_server: Any) -> None:
    """The defaults are no one's choice: only a changed key is 'set'."""
    _configure(llm_server, "ollama")
    report, _ = _rows([{"raise": "ConnectError", "message": "down"}])
    assert [row[1] for row in report.rows] == ["liveness"]


# -- the Config section ------------------------------------------------------------


def test_the_key_row_is_named_after_the_service_and_shows_only_a_length(llm_server: Any) -> None:
    _configure(llm_server, "vllm")
    report = DOCTOR.Report()
    DOCTOR.check_config(report)
    (row,) = [r for r in report.rows if r[1].endswith(" key")]
    assert row[1:] == ("llm key", DOCTOR.OK, f"resolved ({len('shaping-test-key')} chars)")
    assert "shaping-test-key" not in report.render()


@pytest.mark.parametrize(
    ("provider", "label", "text"),
    [
        # v0.18's line, byte for byte.
        ("lmstudio", "lmstudio key",
         "not set - fine only if LM Studio's 'Require API key' is off"),
        ("vllm", "llm key",
         "not set - fine only if vLLM was started without one (docs/MODEL_SERVERS.md)"),
    ],
)
def test_a_missing_key_is_said_in_the_rows_own_words(
    llm_server: Any, provider: str, label: str, text: str
) -> None:
    """T6 review, finding 2: the sentence is the row's `key_missing`, not a branch."""
    llm_server(provider, api_key="")
    report = DOCTOR.Report()
    DOCTOR.check_config(report)
    (row,) = [r for r in report.rows if r[1].endswith(" key")]
    assert row[1:] == (label, DOCTOR.WARN, text)
    assert PROVIDERS[provider].key_missing == text


def test_the_services_row_is_fail_level_for_every_provider(
    llm_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine import stack

    _configure(llm_server, "vllm")
    down = [stack.ServiceStatus("llm", stack.STATUS_DOWN, "ConnectError")]
    monkeypatch.setattr(stack.StackManager, "status", lambda self: down)
    report = DOCTOR.Report()
    DOCTOR.check_services(report)
    assert report.rows == [(
        "Services", "llm", DOCTOR.FAIL,
        "ConnectError -> no narration - the model server is down, so the "
        "Storyteller falls back to a canned line",
    )]

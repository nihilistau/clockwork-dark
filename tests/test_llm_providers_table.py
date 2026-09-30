"""
The provider table: its rows, its fields, and the document that carries it.

``engine/llm/providers.py::PROVIDERS`` is the capability matrix as code
(spec §1.2): one row per model server, one ``Cell`` per fact, each cell saying
whether it was measured live (``verified``) or taken from documentation.
``docs/MODEL_SERVERS.md`` is written by hand and carries the same matrix; the
last tests here parse its Markdown table and hold it to ``PROVIDERS`` cell by
cell, naming the cell that drifted.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from engine.llm.providers import FIELDS, PROVIDERS, Cell, Provider, get_provider

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "MODEL_SERVERS.md"

#: Spec §1.2's rows and fields, in its order.
SPEC_ROWS = ["lmstudio", "vllm", "llamacpp", "ollama", "openai_compat"]
SPEC_FIELDS = [
    "chat_transport",
    "structured_output",
    "probe",
    "reasoning_off",
    "grammar_and_reasoning_off_together",
    "inline_think",
    "discovery",
    "keep_alive",
    "context_control",
    "auth",
    "inline_tools",
    "mcp_integrations",
    "health",
    "default_base_url",
]


# -- the rows and the fields ---------------------------------------------------------


def test_the_table_holds_exactly_the_spec_rows() -> None:
    assert list(PROVIDERS) == SPEC_ROWS
    for name, row in PROVIDERS.items():
        assert isinstance(row, Provider) and row.name == name and row.title


def test_every_row_has_exactly_the_spec_fields_and_each_is_a_cell() -> None:
    assert list(FIELDS) == SPEC_FIELDS
    identity = {
        "name", "title", "key_hint", "key_missing", "doctor_section", "inline_think_fix"
    }
    declared = [f for f in Provider.__dataclass_fields__ if f not in identity]
    assert declared == SPEC_FIELDS
    for row in PROVIDERS.values():
        cells = row.cells()
        assert list(cells) == SPEC_FIELDS
        for field, cell in cells.items():
            assert isinstance(cell, Cell), f"{row.name}.{field}"
            assert isinstance(cell.verified, str), f"{row.name}.{field}"


def test_the_machine_values_are_the_spec_vocabulary() -> None:
    col = {name: row.cells() for name, row in PROVIDERS.items()}
    assert {n: c["chat_transport"].value for n, c in col.items()} == {
        "lmstudio": "lmstudio_routed",
        "vllm": "compat",
        "llamacpp": "compat",
        "ollama": "ollama_native",
        "openai_compat": "compat",
    }
    assert {n: c["probe"].value for n, c in col.items()} == {
        "lmstudio": "lmstudio_v18",
        "vllm": "constraint_won",
        "llamacpp": "constraint_won",
        "ollama": "constraint_won",
        "openai_compat": "constraint_won",
    }
    assert {n: c["inline_think"].value for n, c in col.items()} == {
        "lmstudio": "pass",
        "vllm": "strip",
        "llamacpp": "strip",
        "ollama": "strip",
        "openai_compat": "strip",
    }
    assert {n: c["discovery"].value for n, c in col.items()} == {
        "lmstudio": "lmstudio_v1",
        "vllm": "openai_models",
        "llamacpp": "llamacpp_props",
        "ollama": "ollama_show",
        "openai_compat": "openai_models",
    }
    assert {n: c["mcp_integrations"].value for n, c in col.items()} == {
        "lmstudio": True,
        "vllm": False,
        "llamacpp": False,
        "ollama": False,
        "openai_compat": False,
    }
    assert {n: c["default_base_url"].value for n, c in col.items()} == {
        "lmstudio": "http://localhost:1234/v1",
        "vllm": "http://localhost:8000/v1",
        "llamacpp": "http://localhost:8080/v1",
        "ollama": "http://localhost:11434",
        "openai_compat": None,
    }
    assert {n: c["keep_alive"].value for n, c in col.items()} == {
        "lmstudio": "ttl",
        "vllm": None,
        "llamacpp": None,
        "ollama": "keep_alive",
        "openai_compat": None,
    }
    # Machine tokens a request shaper can dispatch on, never prose (review #3).
    assert {n: c["structured_output"].value for n, c in col.items()} == {
        "lmstudio": ("json_schema", "json_schema_permissive"),
        "vllm": ("json_schema", "json_object"),
        "llamacpp": ("json_schema", "json_object"),
        "ollama": ("ollama_format_schema", "ollama_format_json"),
        "openai_compat": ("json_schema", "json_object"),
    }
    # One type, three states: a truthy "if_declared" would read as yes (review #4).
    assert {n: c["grammar_and_reasoning_off_together"].value for n, c in col.items()} == {
        "lmstudio": "no",
        "vllm": "yes",
        "llamacpp": "yes",
        "ollama": "yes",
        "openai_compat": "if_declared",
    }
    assert col["vllm"]["reasoning_off"].value == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert col["ollama"]["reasoning_off"].value == {"think": False}
    assert col["openai_compat"]["reasoning_off"].value is None


GOLDEN = REPO / "tests" / "fixtures" / "llm" / "golden_lmstudio" / "shipped"


def _golden_requests(scenario: str) -> list[dict[str, Any]]:
    return json.loads((GOLDEN / f"{scenario}.requests.json").read_text(encoding="utf-8"))


def test_the_lmstudio_row_is_v018() -> None:
    """
    Every fact v0.18 acted on, read off the golden's recorded wire rather than
    typed into this test (review #12) -- so the row cannot drift from what
    client.py and lmstudio_native.py actually send and stay green. And every cell of it
    is verified, because the golden pins the behaviour it describes.
    """
    from urllib.parse import urlparse

    from engine.config import get_config
    from engine.llm.routes import COMPAT_CHAT_PATH

    row = PROVIDERS["lmstudio"]
    assert get_config().get("llm.provider") == "lmstudio"
    assert get_provider() is row

    compat = [
        r for r in _golden_requests("03_turn_non_streamed")
        if r["url"].endswith(COMPAT_CHAT_PATH)
    ]
    native = [
        r for r in _golden_requests("11_native_utility_chat")
        if urlparse(r["url"]).path == "/api/v1/chat"
    ]
    assert compat and native

    # default_base_url: the base the compat turn was sent to.
    assert row.default_base_url.value == compat[0]["url"][: -len(COMPAT_CHAT_PATH)]
    # keep_alive: v0.18 sends its key on compat, and never on native.
    key = row.keep_alive.value
    assert all(key in r["json"] for r in compat[1:])  # the turn, not the probe
    assert not any(key in (r.get("json") or {}) for r in native)
    # reasoning_off: exactly the native body's reasoning knob.
    ((field, value),) = row.reasoning_off.value.items()
    assert any((r.get("json") or {}).get(field) == value for r in native)
    # discovery and health: the paths the refresh and the stack probe asked.
    (refresh,) = _golden_requests("18_registry_refresh")
    assert row.discovery.value == "lmstudio_v1"
    assert (urlparse(refresh["url"]).path,) == row.health.value
    (health, *_) = _golden_requests("23_stack_probe")
    assert (urlparse(health["url"]).path,) == row.health.value
    # mcp_integrations: Phase A's native request carries them.
    phase_a = [
        r for r in _golden_requests("21_phase_a_mcp")
        if "integrations" in (r.get("json") or {})
    ]
    assert bool(phase_a) is row.mcp_integrations.value
    # json_schema on compat, as the probe sent it.
    assert compat[0]["json"]["response_format"]["type"] == row.structured_output.value[0]

    assert row.inline_think.value == "pass"
    assert row.empty_model_list() == {"models": []}
    unverified = [f for f, c in row.cells().items() if not c.verified]
    assert not unverified, f"LM Studio cells not verified: {unverified}"


def test_the_lmstudio_key_hint_is_v018s_text() -> None:
    """The 401 wording is row data now (review #8); LM Studio's is v0.18's, byte for byte."""
    assert PROVIDERS["lmstudio"].key_hint == (
        "Set llm.api_key in config/local.yaml, or turn off "
        "'Require API key' in LM Studio's server settings"
    )
    for name, row in PROVIDERS.items():
        assert row.key_hint, name
        if name != "lmstudio":
            assert "LM Studio" not in row.key_hint, name


def test_only_what_was_run_live_is_verified() -> None:
    """
    Spec §1.2: documentation facts are unverified until a live run. LM Studio
    is the golden's; llama-server and Ollama were run live in v0.19.0 T8,
    every cell but what nothing measured (``mcp_integrations``, and Ollama's
    proxy pass-through ``auth``); vLLM waits for v0.20.0, and a generic server
    has no one server to verify against.
    """
    for name in ("vllm", "openai_compat"):
        verified = [f for f, c in PROVIDERS[name].cells().items() if c.verified]
        assert not verified, f"{name} cells claim verification: {verified}"
    llamacpp = PROVIDERS["llamacpp"].cells()
    assert {f for f, c in llamacpp.items() if not c.verified} == {"mcp_integrations"}
    assert {c.verified for c in llamacpp.values()} == {"", "llama.cpp server b7966"}
    ollama = PROVIDERS["ollama"].cells()
    assert {f for f, c in ollama.items() if not c.verified} == {"mcp_integrations", "auth"}
    assert {c.verified for c in ollama.values()} == {"", "Ollama 0.34.4"}


def test_an_unknown_provider_name_raises_naming_the_legal_ones() -> None:
    with pytest.raises(KeyError, match="openai_compat"):
        get_provider("lm-studio")


# -- the document agrees, cell by cell ----------------------------------------------


def _render(cell: Cell) -> str:
    """How ``docs/MODEL_SERVERS.md`` writes a cell (backticks aside)."""
    value = cell.value
    if value is None:
        text = "none"
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, dict):
        text = json.dumps(value)
    elif isinstance(value, (tuple, list)):
        text = ", ".join(str(v) for v in value)
    else:
        text = str(value)
    if cell.note:
        text += f"; {cell.note}"
    return text + (" ✓" if cell.verified else " †")


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", "").replace("\\|", "|")).strip()


def _doc_table() -> tuple[list[str], dict[str, list[str]]]:
    """The matrix: its provider header, and each field's row of cells."""
    lines = DOC.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"^\|\s*Field\s*\|", line)), None
    )
    assert start is not None, "docs/MODEL_SERVERS.md has no `| Field | ...` matrix"

    def cells(line: str) -> list[str]:
        parts = re.split(r"(?<!\\)\|", line.strip())
        return [p.strip() for p in parts[1:-1]]

    header = [_normal(c) for c in cells(lines[start])[1:]]
    rows: dict[str, list[str]] = {}
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        row = cells(line)
        rows[_normal(row[0])] = row[1:]
    return header, rows


def test_the_document_matrix_has_the_tables_rows_and_columns() -> None:
    header, rows = _doc_table()
    assert header == list(PROVIDERS), f"columns: {header}"
    assert list(rows) == list(FIELDS), f"rows: {list(rows)}"


@pytest.mark.parametrize("field", FIELDS)
def test_the_document_matrix_matches_providers_cell_by_cell(field: str) -> None:
    header, rows = _doc_table()
    drifted: list[str] = []
    for provider, written in zip(header, rows.get(field, [])):
        expected = _render(PROVIDERS[provider].cells()[field])
        if _normal(written) != _normal(expected):
            drifted.append(
                f"{field} x {provider}: the document says {_normal(written)!r}, "
                f"PROVIDERS says {_normal(expected)!r}"
            )
    assert len(rows.get(field, [])) == len(PROVIDERS), f"{field}: wrong number of cells"
    assert not drifted, "\n".join(drifted)


def test_the_document_names_what_each_verification_was_against() -> None:
    text = DOC.read_text(encoding="utf-8")
    versions = {c.verified for row in PROVIDERS.values() for c in row.cells().values()}
    for version in versions - {""}:
        assert version in text, f"the document never says what {version!r} is"
    assert "†" in text and "unverified" in text.lower()


def test_the_readme_links_the_document() -> None:
    assert "docs/MODEL_SERVERS.md" in (REPO / "README.md").read_text(encoding="utf-8")

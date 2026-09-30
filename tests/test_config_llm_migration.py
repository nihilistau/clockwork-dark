"""
The ``llm:`` block, and the per-layer alias that keeps a ``lmstudio:`` one working.

v0.19.0 renamed ``config/default.yaml``'s ``lmstudio:`` block to ``llm:``
(spec §2). An owner's ``config/local.yaml`` still says ``lmstudio:``, and it
must keep beating the shipped default key for key -- which a read-time
"try ``llm.``, else ``lmstudio.``" gets backwards, because the default's
``llm.`` key always exists. So ``engine/config.py`` renames each LAYER before
it merges, and every test here goes through the real layer loader: the config
directory is pointed at ``tmp_path`` and the singleton is dropped, the real
``default.yaml`` stays the bottom layer.

Nothing here writes ``config/local.yaml``: the file each test writes is under
``tmp_path``.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config
from engine.llm.providers import PROVIDERS

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The real default layer, and ``tmp_path`` standing in for ``config/``."""
    monkeypatch.delenv("CLOCKWORK_ENV", raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield tmp_path


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    return path


def _fresh() -> config.ConfigManager:
    config._instance = None
    return config.get_config()


# -- the per-layer alias -------------------------------------------------------


def test_a_legacy_local_block_beats_the_shipped_llm_default(layers: Path) -> None:
    """
    (a) The precedence the rename must keep. The shipped default now says
    ``llm.base_url``; an owner's ``local.yaml`` still says
    ``lmstudio.base_url``, and the owner's value wins, as it did in v0.18.

    Canary: a read-time fallback (``llm.`` first, ``lmstudio.`` second) answers
    the default's localhost here, and fails this test.
    """
    _write(layers / "local.yaml", {"lmstudio": {"base_url": "http://10.9.8.7:4321/v1"}})
    cfg = _fresh()
    assert cfg.get("llm.base_url") == "http://10.9.8.7:4321/v1"
    assert cfg.get("lmstudio.base_url") == "http://10.9.8.7:4321/v1"


def test_both_blocks_in_one_layer_merge_with_llm_winning(layers: Path) -> None:
    """(b) ``llm:`` wins a key both set; a key only the legacy block sets survives."""
    _write(
        layers / "local.yaml",
        {
            "llm": {"base_url": "http://new.example:1/v1"},
            "lmstudio": {"base_url": "http://old.example:2/v1", "timeout_seconds": 42},
        },
    )
    cfg = _fresh()
    assert cfg.get("llm.base_url") == "http://new.example:1/v1"
    assert cfg.get("llm.timeout_seconds") == 42


def test_ttl_seconds_becomes_keep_alive_seconds_inside_the_legacy_block(layers: Path) -> None:
    _write(layers / "local.yaml", {"lmstudio": {"ttl_seconds": 600}})
    cfg = _fresh()
    assert cfg.get("llm.keep_alive_seconds") == 600
    assert "ttl_seconds" not in cfg.section("llm")


def test_the_legacy_stack_service_is_renamed_too(layers: Path) -> None:
    _write(layers / "local.yaml", {"stack": {"services": {"lmstudio": {"enabled": False}}}})
    cfg = _fresh()
    services = cfg.section("stack.services")
    assert "lmstudio" not in services
    assert services["llm"]["enabled"] is False
    # Merged, not replaced: the shipped keys of the service are still there.
    assert services["llm"]["manage"] is False
    assert services["voxtral_tts"]["enabled"] is True


def test_every_layer_is_aliased(layers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default, environment, local and the game overlay each get the rename."""
    _write(layers / "default.yaml", {"lmstudio": {"base_url": "d", "timeout_seconds": 1}})
    monkeypatch.setattr(config, "_DEFAULT_PATH", layers / "default.yaml")
    monkeypatch.setenv("CLOCKWORK_ENV", "staging")
    _write(layers / "staging.yaml", {"lmstudio": {"base_url": "e", "reserve_output": 2}})
    _write(layers / "local.yaml", {"lmstudio": {"base_url": "l", "context_tokens": 3}})
    monkeypatch.setattr(config, "_overlay", {"lmstudio": {"lanes": {"narration": 4}}})
    cfg = _fresh()
    assert cfg.section("llm") == {
        "base_url": "l",
        "timeout_seconds": 1,
        "reserve_output": 2,
        "context_tokens": 3,
        "lanes": {"narration": 4},
    }


def test_one_warning_per_aliased_layer_naming_the_file(
    layers: Path, caplog: pytest.LogCaptureFixture
) -> None:
    local = _write(layers / "local.yaml", {"lmstudio": {"base_url": "http://x:1/v1"}})
    with caplog.at_level(logging.WARNING, logger="engine.config"):
        _fresh()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert str(local) in warnings[0].getMessage()


def test_the_shipped_default_needs_no_alias(
    layers: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="engine.config"):
        cfg = _fresh()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert cfg.get("llm.provider") == "lmstudio"
    assert cfg.get("llm.keep_alive_seconds") == 900
    assert cfg.get("llm.declared_models") == {}
    assert cfg.get("llm.reasoning_off_body") == {}


def test_the_alias_does_not_touch_the_callers_dict() -> None:
    layer = {"lmstudio": {"ttl_seconds": 5}, "stack": {"services": {"lmstudio": {"x": 1}}}}
    migrated, renamed = config.migrate_legacy_llm(layer)
    assert layer == {"lmstudio": {"ttl_seconds": 5}, "stack": {"services": {"lmstudio": {"x": 1}}}}
    assert migrated == {"llm": {"keep_alive_seconds": 5}, "stack": {"services": {"llm": {"x": 1}}}}
    assert renamed


# -- the read alias ------------------------------------------------------------


def test_a_legacy_key_is_read_from_llm(layers: Path) -> None:
    """(c) An owner's script asking for ``lmstudio.*`` is answered from ``llm``."""
    _write(layers / "local.yaml", {"llm": {"profiles": {"big": {"temperature": 0.33}}}})
    cfg = _fresh()
    assert cfg.get("lmstudio.profiles.big.temperature") == 0.33
    assert cfg.section("lmstudio.profiles") == cfg.section("llm.profiles")
    assert cfg.section("lmstudio.profiles")["big"]["temperature"] == 0.33
    assert cfg.get("lmstudio.ttl_seconds") == cfg.get("llm.keep_alive_seconds") == 900
    assert cfg.get("lmstudio") == cfg.get("llm")
    assert (
        cfg.get("stack.services.lmstudio.health_url")
        == cfg.get("stack.services.llm.health_url")
    )


def test_as_dict_is_the_migrated_tree(layers: Path) -> None:
    """(d)"""
    _write(layers / "local.yaml", {"lmstudio": {"base_url": "http://x:1/v1"}})
    tree = _fresh().as_dict()
    assert "llm" in tree
    assert "lmstudio" not in tree
    assert "llm" in tree["stack"]["services"]
    assert "lmstudio" not in tree["stack"]["services"]


# -- nothing reads the old key any more ------------------------------------------


#: The one assignment allowed to spell the old key: the table that maps it.
ALIAS_TABLE = "_READ_ALIASES"


def _alias_table_constants(tree: ast.AST) -> set[int]:
    """The ids of the string constants inside ``_READ_ALIASES``' assignment."""
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == ALIAS_TABLE for t in targets):
            allowed |= {id(c) for c in ast.walk(node) if isinstance(c, ast.Constant)}
    return allowed


def _legacy_key_literals_in(source: str, name: str) -> list[str]:
    """Every string constant starting ``lmstudio.``, outside the alias table."""
    tree = ast.parse(source, filename=name)
    allowed = _alias_table_constants(tree)
    return [
        f"{name}:{node.lineno}: {node.value[:60]!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("lmstudio.")
        and id(node) not in allowed
    ]


def _legacy_key_literals(path: Path) -> list[str]:
    return _legacy_key_literals_in(
        path.read_text(encoding="utf-8"), str(path.relative_to(REPO))
    )


def test_no_engine_or_script_source_reads_a_lmstudio_key() -> None:
    """
    (e) Every reader moved to ``llm.``. The alias table in ``engine/config.py``
    is the one place the old name may be spelled, since it is what maps it.
    """
    sources = [
        *sorted((REPO / "engine").rglob("*.py")),
        *sorted((REPO / "scripts").rglob("*.py")),
        REPO / "launcher.py",
    ]
    hits: list[str] = []
    for path in sources:
        hits += _legacy_key_literals(path)
    assert not hits, "a lmstudio.* key literal is still read:\n" + "\n".join(hits)


def test_the_scan_spares_the_alias_table_and_nothing_else_in_config() -> None:
    """The exemption is the table's own assignment, not the whole of engine/config.py."""
    source = (REPO / "engine" / "config.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert _alias_table_constants(tree), f"{ALIAS_TABLE} is gone from engine/config.py"
    probe = source + '\n\ndef _probe():\n    return get_config().get("lmstudio.base_url")\n'
    hits = _legacy_key_literals_in(probe, "engine/config.py")
    assert len(hits) == 1 and "lmstudio.base_url" in hits[0], hits


# -- a story may declare neither block ---------------------------------------------


def test_a_story_may_not_set_either_block() -> None:
    from engine.games.manifest import SETTING_REFUSALS, refusal_reason

    prefixes = dict(SETTING_REFUSALS)
    assert prefixes["llm"] == prefixes["lmstudio"]
    assert "machine" in refusal_reason("llm.api_key")
    assert "machine" in refusal_reason("llm.mcp.port")
    assert "machine" in refusal_reason("lmstudio.base_url")


# -- llm.provider ------------------------------------------------------------------


def test_an_unknown_provider_is_refused_at_load(layers: Path) -> None:
    _write(layers / "local.yaml", {"llm": {"provider": "lm-studio"}})
    with pytest.raises(ValueError) as caught:
        _fresh()
    message = str(caught.value)
    assert "lm-studio" in message
    for name in PROVIDERS:
        assert name in message


def test_every_legal_provider_loads(layers: Path) -> None:
    # Every row of the provider table, not a list kept beside it.
    assert set(PROVIDERS) == {"lmstudio", "vllm", "llamacpp", "ollama", "openai_compat"}
    for name in PROVIDERS:
        _write(layers / "local.yaml", {"llm": {"provider": name}})
        assert _fresh().get("llm.provider") == name

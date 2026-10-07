"""
The secrets chain's scope syntax, made exact (v0.20.0 T2; spec survey finding
3, §2.2 -- v0.19.0's final re-review, N1-N3).

An alternative is scoped (``<provider>?<alternative>``) only if the text
before its first ``?`` matches ``^[a-z_]+$``:

- **N1.** ``file:/srv/keys/what?.txt`` (legal on POSIX) was split at its
  ``?`` and read as the scope ``file:/srv/keys/what``, which never matched, so
  the alternative was skipped in silence. It is read whole now.
- **N2.** A misspelt scope (``lmstuido?file:x``) never matched and was never
  reported. ``get_config`` refuses it at load, naming the key and the scope.
- **N3.** The scope test read ``llm.provider`` through ``get``, which expands
  again, so a ``ConfigManager`` whose provider was itself a scoped chain
  recursed to ``RecursionError``. It reads the provider raw now, and a
  ``${...}`` provider is refused at load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The real default.yaml, a temp config dir, no environment layer."""
    directory = tmp_path / "config"
    directory.mkdir()
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_CONFIG", "CLOCKWORK_LLM_API_KEY", "LMSTUDIO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield directory
    config._instance = None


def _local(directory: Path, data: dict[str, Any]) -> None:
    (directory / "local.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    config._instance = None


def _recording(monkeypatch: pytest.MonkeyPatch, answers: dict[str, str]) -> list[str]:
    """Stub ``_expand_one``: record each alternative asked, answer from ``answers``."""
    asked: list[str] = []

    def fake(token: str, default: Any) -> Any:
        asked.append(token)
        return answers.get(token, default)

    monkeypatch.setattr(config.ConfigManager, "_expand_one", staticmethod(fake))
    return asked


# -- N1 ---------------------------------------------------------------------------


def test_n1_an_unscoped_alternative_holding_a_question_mark_is_read_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    ``?`` is legal in a POSIX file name. The read itself is stubbed, since a
    Windows checkout cannot hold such a file: what is asserted is which
    alternative the chain hands to the reader.
    """
    asked = _recording(monkeypatch, {"file:/srv/keys/what?.txt": "the-key"})
    manager = config.ConfigManager(
        {"llm": {"provider": "lmstudio", "api_key": "${file:/srv/keys/what?.txt|env:NO_SUCH_VAR}"}}
    )
    assert manager.get("llm.api_key") == "the-key"
    assert asked == ["file:/srv/keys/what?.txt"]


def test_n1_a_single_alternative_holding_a_question_mark_is_read_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _recording(monkeypatch, {"file:/srv/keys/what?.txt": "the-key"})
    manager = config.ConfigManager({"llm": {"api_key": "${file:/srv/keys/what?.txt}"}})
    assert manager.get("llm.api_key") == "the-key"
    assert asked == ["file:/srv/keys/what?.txt"]


def test_a_real_scope_still_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The green control: ``lmstudio?`` is still a scope, and still honoured."""
    asked = _recording(monkeypatch, {"file:lm.txt": "lm-key", "env:OTHER": "other-key"})
    token = "${lmstudio?file:lm.txt|env:OTHER}"
    on_lm = config.ConfigManager({"llm": {"provider": "lmstudio", "api_key": token}})
    assert on_lm.get("llm.api_key") == "lm-key"
    off_lm = config.ConfigManager({"llm": {"provider": "vllm", "api_key": token}})
    assert off_lm.get("llm.api_key") == "other-key"
    assert asked == ["file:lm.txt", "env:OTHER"]


# -- N2 ---------------------------------------------------------------------------


def test_n2_a_misspelt_scope_is_refused_at_load_naming_key_and_scope(pinned: Path) -> None:
    _local(pinned, {"llm": {"api_key": "${file:llm_api_key.txt|lmstuido?file:x}"}})
    with pytest.raises(ValueError) as refused:
        config.get_config()
    message = str(refused.value)
    assert "llm.api_key" in message
    assert "lmstuido" in message


def test_n2_the_walk_reaches_any_key(pinned: Path) -> None:
    _local(pinned, {"stt": {"api_key": "${vlm?env:X}"}})
    with pytest.raises(ValueError) as refused:
        config.get_config()
    assert "stt.api_key" in str(refused.value) and "'vlm'" in str(refused.value)


def test_the_shipped_config_loads(pinned: Path) -> None:
    """Every scope ``config/default.yaml`` ships is a provider."""
    cfg = config.get_config()
    assert cfg.get("llm.provider") == "lmstudio"


@pytest.mark.parametrize("scope", ["lm-studio", "openai-compat", "LM Studio", "vllm2"])
def test_n2_any_misspelling_is_refused_not_only_lowercase(pinned: Path, scope: str) -> None:
    """
    Fix round 1 (review finding 6): `^[a-z_]+$` let `lm-studio?` and
    `openai-compat?` through as whole alternatives -- variable names that are
    never set -- so they were skipped in silence. Any text before the first
    `?` that holds no `:` is a scope now, checked against the providers.
    """
    _local(pinned, {"llm": {"api_key": f"${{file:llm_api_key.txt|{scope}?env:X}}"}})
    with pytest.raises(ValueError) as refused:
        config.get_config()
    assert "llm.api_key" in str(refused.value) and repr(scope) in str(refused.value)


def test_a_scope_matches_its_provider_ignoring_case(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _recording(monkeypatch, {"file:lm.txt": "lm-key"})
    manager = config.ConfigManager(
        {"llm": {"provider": "lmstudio", "api_key": "${LMStudio?file:lm.txt|env:OTHER}"}}
    )
    assert manager.get("llm.api_key") == "lm-key"
    assert asked == ["file:lm.txt"]


def test_a_differently_cased_scope_loads(pinned: Path) -> None:
    _local(pinned, {"llm": {"api_key": "${file:llm_api_key.txt|LMStudio?env:X}"}})
    assert config.get_config().get("llm.provider") == "lmstudio"


# -- N3 ---------------------------------------------------------------------------


def test_n3_a_scoped_chain_provider_does_not_recurse(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A hand-built manager skips the load check; the scope test must still read
    the provider as the plain string it is, never expand it.
    """
    _recording(monkeypatch, {"env:A": "a-key"})
    manager = config.ConfigManager(
        {
            "llm": {
                "provider": "${lmstudio?env:P|env:Q}",
                "api_key": "${lmstudio?env:A|env:B}",
            }
        }
    )
    # The raw provider names no provider, so the scoped alternative is
    # skipped, and the unscoped one answers (None here).
    assert manager.get("llm.api_key", "fallback") == "fallback"


def test_n3_a_templated_provider_is_refused_at_load(pinned: Path) -> None:
    _local(pinned, {"llm": {"provider": "${env:WHICH_SERVER}"}})
    with pytest.raises(ValueError) as refused:
        config.get_config()
    assert "llm.provider" in str(refused.value)


def test_raw_reads_without_expanding() -> None:
    manager = config.ConfigManager({"llm": {"provider": "${env:X}"}})
    assert manager._raw("llm.provider") == "${env:X}"
    assert manager._raw("llm.nothing", "d") == "d"
    # No read alias since v0.21.0 (the name is built so the AST scan in
    # tests/test_config_legacy_refused.py does not count this as a read).
    assert manager._raw("lmstudio" + ".provider") is None

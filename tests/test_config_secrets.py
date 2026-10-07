"""
``${a|b|...}``: the secrets fallback chain (spec §2.3, finding 1).

v0.18's ``config/default.yaml`` and README both promised that
``${file:lmstudio.txt}`` "falls back to the ``LMSTUDIO_API_KEY`` environment
variable". ``ConfigManager._expand`` never read the environment for a
``file:`` token: an absent file returned the caller's default, so a key set
only in the environment was silently ignored and every request 401'd. The
chain makes each fallback explicit, tried left to right, first non-empty
value wins.

``engine.config._ROOT`` is pointed at an empty ``tmp_path`` wherever a
relative secret file is in play, so a machine's own ``lmstudio.txt`` or
``llm_api_key.txt`` can never answer a test.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator, Optional

import pytest

import engine.config as config
from engine.config import ConfigManager

REPO = Path(__file__).resolve().parents[1]
SECRET = "sk-test-0123456789abcdef"
ENV_KEYS = ("CLOCKWORK_LLM_API_KEY", "LMSTUDIO_API_KEY", "CLOCKWORK_ENV")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """No secret file anywhere, no key in the environment, the shipped default."""
    for name in ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_ROOT", tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(config, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield tmp_path


def _value(token: str) -> ConfigManager:
    return ConfigManager({"k": "${" + token + "}"})


def test_the_shipped_key_falls_back_to_the_environment(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    FINDING 1. No key file on the machine and only ``LMSTUDIO_API_KEY`` set:
    v0.18 answered the default, and every request went out unauthenticated.
    Asked by its ``llm`` name: the v0.18 one is no longer read (v0.21.0).
    """
    monkeypatch.setenv("LMSTUDIO_API_KEY", SECRET)
    assert config.get_config().get("llm.api_key") == SECRET


def test_the_shipped_chain_prefers_the_new_names(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = config.get_config()
    monkeypatch.setenv("LMSTUDIO_API_KEY", "old-env")
    assert cfg.get("llm.api_key") == "old-env"
    monkeypatch.setenv("CLOCKWORK_LLM_API_KEY", "new-env")
    assert cfg.get("llm.api_key") == "new-env"
    (root / "lmstudio.txt").write_text("old-file\n", encoding="utf-8")
    assert cfg.get("llm.api_key") == "old-file"
    (root / "llm_api_key.txt").write_text("new-file\n", encoding="utf-8")
    assert cfg.get("llm.api_key") == "new-file"


def test_a_missing_file_falls_through_to_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CW_TEST_SECRET", SECRET)
    cfg = _value(f"file:{tmp_path / 'missing.txt'}|env:CW_TEST_SECRET")
    assert cfg.get("k", "default") == SECRET


def test_the_file_beats_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "key.txt"
    secret.write_text("from-the-file\nsecond line ignored\n", encoding="utf-8")
    monkeypatch.setenv("CW_TEST_SECRET", "from-the-env")
    assert _value(f"file:{secret}|env:CW_TEST_SECRET").get("k") == "from-the-file"
    assert _value(f"env:CW_TEST_SECRET|file:{secret}").get("k") == "from-the-env"


def test_a_byte_order_mark_is_not_part_of_the_key(tmp_path: Path) -> None:
    """Notepad saves "UTF-8 with BOM"; U+FEFF in a header makes httpx refuse it."""
    secret = tmp_path / "key.txt"
    secret.write_bytes(b"\xef\xbb\xbf" + SECRET.encode("ascii") + b"\r\n")
    assert _value(f"file:{secret}").get("k") == SECRET
    assert _value(f"file:{secret}|env:CW_TEST_UNSET").get("k") == SECRET


def test_an_empty_file_falls_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")
    monkeypatch.setenv("CW_TEST_SECRET", SECRET)
    assert _value(f"file:{empty}|env:CW_TEST_SECRET").get("k") == SECRET


def test_an_empty_variable_falls_through_and_a_bare_name_is_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CW_TEST_EMPTY", "")
    monkeypatch.setenv("CW_TEST_SECRET", SECRET)
    assert _value("env:CW_TEST_EMPTY|CW_TEST_SECRET").get("k") == SECRET


def test_nothing_answering_returns_the_callers_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CW_TEST_SECRET", raising=False)
    cfg = _value(f"file:{tmp_path / 'nope.txt'}|env:CW_TEST_SECRET")
    assert cfg.get("k", "fallback") == "fallback"
    assert cfg.get("k") is None


def test_a_token_without_a_bar_resolves_as_in_v0_18(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CW_TEST_SECRET", SECRET)
    monkeypatch.delenv("CW_TEST_UNSET", raising=False)
    assert _value("CW_TEST_SECRET").get("k") == SECRET
    assert _value("CW_TEST_UNSET").get("k", "d") == "d"
    # v0.18 returns the variable as set, empty included.
    monkeypatch.setenv("CW_TEST_EMPTY", "")
    assert _value("CW_TEST_EMPTY").get("k", "d") == ""

    secret = tmp_path / "key.txt"
    secret.write_text(" from-the-file \n", encoding="utf-8")
    assert _value(f"file:{secret}").get("k") == "from-the-file"
    # A file token alone answers the default when the file is absent; only a
    # chain goes on to the environment.
    assert _value(f"file:{tmp_path / 'absent.txt'}").get("k", "d") == "d"


def test_a_relative_file_is_read_against_the_repo_root(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "key.txt").write_text(SECRET, encoding="utf-8")
    assert _value("file:key.txt|env:CW_TEST_UNSET").get("k") == SECRET


def test_expansion_is_lazy(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A variable set AFTER the config is built is seen by the next ``get()``."""
    cfg = config.get_config()
    assert not cfg.get("llm.api_key")
    monkeypatch.setenv("CLOCKWORK_LLM_API_KEY", SECRET)
    assert cfg.get("llm.api_key") == SECRET


def _point_at(root: Path, provider: str, base_url: str) -> None:
    (root / "config" / "local.yaml").write_text(
        f"llm:\n  provider: {provider}\n  base_url: \"{base_url}\"\n", encoding="utf-8"
    )
    config._instance = None


def _authorization_sent(root: Path) -> Optional[str]:
    """What the configured compat client's health check sends as its key."""
    from engine.llm.client import LMSClient
    from tests.llm_wire import wire

    client = LMSClient()
    try:
        with wire([{"status": 200, "json": {"object": "list", "data": [{"id": "m"}]}}]) as seam:
            client.is_available()
    finally:
        client.close()
    assert seam.requests, "the health check sent nothing; the check proves nothing"
    return seam.requests[0]["headers"].get("authorization")


def test_lm_studios_key_is_never_sent_to_another_server(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    FINAL REVIEW, FINDING 4 (AGENTS.md rule 5). The shipped chain read
    ``lmstudio.txt`` and ``LMSTUDIO_API_KEY`` whatever ``llm.provider`` said,
    so an owner who kept LM Studio's key there and pointed the engine at a
    remote OpenAI-compatible host sent that host LM Studio's key. The two
    LM Studio-named sources now answer only while the provider is LM Studio.
    """
    (root / "lmstudio.txt").write_text("lm-studio-file-key\n", encoding="utf-8")
    monkeypatch.setenv("LMSTUDIO_API_KEY", "lm-studio-env-key")
    _point_at(root, "openai_compat", "https://models.example.net/v1")
    assert not config.get_config().get("llm.api_key")
    assert _authorization_sent(root) is None

    (root / "lmstudio.txt").unlink()
    assert not config.get_config().get("llm.api_key")
    assert _authorization_sent(root) is None


def test_the_provider_neutral_sources_still_reach_another_server(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "lmstudio.txt").write_text("lm-studio-file-key\n", encoding="utf-8")
    monkeypatch.setenv("LMSTUDIO_API_KEY", "lm-studio-env-key")
    _point_at(root, "openai_compat", "https://models.example.net/v1")
    monkeypatch.setenv("CLOCKWORK_LLM_API_KEY", "neutral-env-key")
    assert _authorization_sent(root) == "Bearer neutral-env-key"
    (root / "llm_api_key.txt").write_text("neutral-file-key\n", encoding="utf-8")
    assert _authorization_sent(root) == "Bearer neutral-file-key"


def test_lm_studio_still_reads_its_own_key_sources(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LMSTUDIO_API_KEY", "lm-studio-env-key")
    _point_at(root, "lmstudio", "http://localhost:1234/v1")
    assert config.get_config().get("llm.api_key") == "lm-studio-env-key"
    (root / "lmstudio.txt").write_text("lm-studio-file-key\n", encoding="utf-8")
    assert config.get_config().get("llm.api_key") == "lm-studio-file-key"


def test_a_scoped_alternative_is_tried_only_under_its_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CW_TEST_SECRET", SECRET)
    monkeypatch.delenv("CW_TEST_UNSET", raising=False)
    token = "${ollama?env:CW_TEST_SECRET|env:CW_TEST_UNSET}"
    here = ConfigManager({"k": token, "llm": {"provider": "ollama"}})
    there = ConfigManager({"k": token, "llm": {"provider": "vllm"}})
    assert here.get("k") == SECRET
    assert there.get("k", "d") == "d"


def test_the_value_is_never_logged(
    root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("CLOCKWORK_LLM_API_KEY", SECRET + "-env")
    with caplog.at_level(logging.DEBUG):
        cfg = config.get_config()
        assert cfg.get("llm.api_key") == SECRET + "-env"
        (root / "lmstudio.txt").write_text(SECRET, encoding="utf-8")
        assert cfg.get("llm.api_key") == SECRET
    assert caplog.records, "the config logged nothing at all; the check proves nothing"
    assert SECRET not in caplog.text

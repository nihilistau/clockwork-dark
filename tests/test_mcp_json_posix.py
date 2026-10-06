"""
``mcp_json_path`` under a POSIX-shaped home (spec §3.6).

LM Studio keeps ``mcp.json`` in ``~/.cache/lm-studio`` on current builds and in
``~/.lmstudio`` on older ones, on Linux as on Windows. The lookup has always
named both; these tests pin that it finds each under a faked home -- a
directory in ``tmp_path``, set as ``Path.home``, ``HOME`` and ``USERPROFILE``
-- and never touches the owner's.

The conftest guard (``_no_owner_lm_studio_files``) redirects the module's
``mcp_json_path`` for every test; the unredirected function is handed over on
``request.node.real_mcp_json_path``. It only answers a path: nothing here
writes, and the guarded writers stay up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest


@pytest.fixture
def posix_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home" / "player"
    home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    return home


@pytest.fixture
def lookup(request: Any, monkeypatch: pytest.MonkeyPatch) -> Callable[[], Any]:
    """The real lookup, with no ``llm.mcp.mcp_json`` declared."""
    from engine.config import get_config

    config = get_config()
    real_get = config.get

    def get(key: str, default: Any = None) -> Any:
        if key == "llm.mcp.mcp_json":
            return ""
        return real_get(key, default)

    monkeypatch.setattr(config, "get", get)
    return request.node.real_mcp_json_path


def _place(home: Path, *parts: str) -> Path:
    target = home.joinpath(*parts, "mcp.json")
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    return target


def test_finds_the_cache_directory(posix_home: Path, lookup: Callable[[], Any]) -> None:
    target = _place(posix_home, ".cache", "lm-studio")
    assert lookup() == target


def test_finds_the_older_dot_lmstudio(posix_home: Path, lookup: Callable[[], Any]) -> None:
    target = _place(posix_home, ".lmstudio")
    assert lookup() == target


def test_prefers_the_cache_directory_when_both_exist(
    posix_home: Path, lookup: Callable[[], Any]
) -> None:
    cache = _place(posix_home, ".cache", "lm-studio")
    _place(posix_home, ".lmstudio")
    assert lookup() == cache


def test_answers_none_with_neither(posix_home: Path, lookup: Callable[[], Any]) -> None:
    assert lookup() is None


def test_a_declared_path_expands_the_faked_home(
    posix_home: Path, request: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.config import get_config

    config = get_config()
    real_get = config.get
    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: "~/.lmstudio/mcp.json"
        if key == "llm.mcp.mcp_json"
        else real_get(key, default),
    )
    assert request.node.real_mcp_json_path() == posix_home / ".lmstudio" / "mcp.json"

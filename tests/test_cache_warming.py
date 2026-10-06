"""
Warming (v0.20.0 T6, spec §5.2): ``engine.games.caches.warm_all_caches()``
builds every per-story cache once, under its own lock (the outermost in
engine/locks.py), so a process that serves many sessions on threads has
nothing left for two first readers to build at once.

* It calls every loader ``WARMERS`` registers, in order, each under the warm
  lock and never under the config lock (each spied).
* Every ``warmed`` row of ``tests/fixtures/module_state.yaml`` names a
  ``WARMERS`` loader, and every loader builds some classified row.
* Every warmed cache has a reset in the registry (or says ``never``).
* After warming, every warmed cache is built, for the flagship and for HUE &
  CRY.

Version: v0.1.0 [2026-10-01]
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from engine.games import caches
from tests.module_state_scan import load_inventory


def _warmed_rows() -> dict[str, dict[str, Any]]:
    return {site: row for site, row in load_inventory().items() if row["verdict"] == "warmed"}


def _loaders(row: dict[str, Any]) -> list[str]:
    loader = row.get("loader") or []
    return [loader] if isinstance(loader, str) else list(loader)


def _split(site: str) -> tuple[Any, str, bool]:
    """(module, name, is_lru) for a site id."""
    is_lru = site.endswith("()")
    dotted = site[:-2] if is_lru else site
    module_name, _, name = dotted.rpartition(".")
    return importlib.import_module(module_name), name, is_lru


def test_warm_all_caches_calls_every_registered_loader_in_order_under_the_warm_lock(monkeypatch):
    from engine import config

    calls: list[str] = []
    held: list[bool] = []
    config_held: list[bool] = []

    for module_name, attr in caches.WARMERS:
        module = importlib.import_module(module_name)
        label = f"{module_name}.{attr}"

        def spy(*_a: Any, _label: str = label, **_k: Any) -> None:
            calls.append(_label)
            held.append(caches._warm_lock.locked())
            # The config lock is innermost (engine/locks.py): never held here.
            config_held.append(config._config_lock._is_owned())

        monkeypatch.setattr(module, attr, spy)

    returned = caches.warm_all_caches()
    expected = [f"{m}.{a}" for m, a in caches.WARMERS]
    assert calls == expected
    assert returned == expected
    assert all(held), "a loader ran outside the warm lock"
    assert not any(config_held), "a loader ran under the config lock, the innermost"


def test_every_warmer_builds_a_classified_row_and_every_warmed_row_has_one():
    named = {loader for row in load_inventory().values() for loader in _loaders(row)}
    registered = {f"{m}.{a}" for m, a in caches.WARMERS}
    assert sorted(registered - named) == [], "a WARMERS loader no module_state.yaml row names"
    assert sorted(named - registered) == [], "a row's loader missing from caches.WARMERS"
    assert len(registered) == len(caches.WARMERS), "a loader registered twice"


def test_every_warmed_cache_has_a_reset():
    nulled = {f"{m}.{a}" for m, a in caches.NULLED_ATTRIBUTES}
    lru = {f"{m}.{a}()" for m, a in caches.LRU_CACHES}
    reloaders = {f"{m}.{a}" for m, a in caches.RELOADERS}
    missing = []
    for site, row in _warmed_rows().items():
        reset = row.get("reset")
        if reset == "never":
            continue
        if reset is not None:
            if reset not in reloaders:
                missing.append(f"{site}: reset {reset} is not a RELOADERS entry")
        elif site not in nulled and site not in lru:
            missing.append(f"{site}: not in NULLED_ATTRIBUTES or LRU_CACHES")
    assert not missing, missing


def _built(site: str) -> bool:
    module, name, is_lru = _split(site)
    value = getattr(module, name)
    if is_lru:
        return value.cache_info().currsize > 0
    return value is not None


def _holds_content(site: str) -> bool:
    module, name, is_lru = _split(site)
    value = getattr(module, name)
    if is_lru:
        return value.cache_info().currsize > 0
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], dict):
        return bool(value[1])  # the recipe memo: (key, recipes)
    return isinstance(value, bool) or bool(value)


STORIES = ("clockwork-dark", "hue-and-cry")

#: Warmed caches that no shipped story gives content, so they are built empty
#: (or not at all) for both: nothing to hold is not a loader gone wrong.
NO_SHIPPED_CONTENT = {
    "engine.challenges.spec._read_bounds()": "no story declares paths.challenge_bounds",
}


def test_after_warming_every_warmed_cache_is_built_for_the_flagship_and_hue_and_cry():
    """
    Each story is activated (which resets every cache), then warmed, and every
    ``warmed`` row must be BUILT for both.

    Built is not enough on its own: a loader pointed at the wrong thing builds
    an empty answer. So each warmed cache must also hold content for at least
    one of the two (a system a story does not declare is built empty for it,
    correctly: the flagship has no law, HUE & CRY no doom clock).
    """
    from engine.games import registry

    rows = _warmed_rows()
    seen: dict[str, dict[str, tuple[bool, bool]]] = {}
    for slug in STORIES:
        registry.activate(slug)
        caches.warm_all_caches()
        seen[slug] = {site: (_built(site), _holds_content(site)) for site in rows}
        # A cache left unbuilt is right only when its story gives it nothing to
        # hold (the flagship ships no clocks.yaml, so `_read_table` is never
        # reached): asking its loaders again must still build nothing. One
        # that builds now is one warming missed.
        for site, (built, _content) in seen[slug].items():
            if built:
                continue
            for loader in _loaders(rows[site]):
                module_name, _, attr = loader.rpartition(".")
                getattr(importlib.import_module(module_name), attr)()
            assert not _built(site), (
                f"{slug}: {site} was built by a second call to its loader, "
                "so warm_all_caches() left it to the first reader"
            )
    empty = sorted(
        site for site in rows if not any(seen[slug][site][1] for slug in STORIES)
    )
    assert empty == sorted(NO_SHIPPED_CONTENT), (
        f"warmed caches empty for both stories (NO_SHIPPED_CONTENT lists the "
        f"ones that should be): {empty}"
    )

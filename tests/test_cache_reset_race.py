"""
A config reset can land between a loader's store and its return (v0.20.0 T6
fix round 2).

``engine/games/caches.py::reset_all_caches`` nulls every ``NULLED_ATTRIBUTES``
cache with a plain ``setattr`` -- no lock, on whatever thread asked for the
reset (a Settings save, a story activation). A loader written as::

    global _CACHE
    if _CACHE is not None:          # read 1
        return _CACHE               # read 2: None if a reset fell between
    _CACHE = build()
    return _CACHE                   # None if a reset fell between

hands its caller ``None`` (or, for a warn-once set, raises mid-turn) when the
reset falls between two of its reads. The fix is one shape everywhere: read
the global once into a local, build into a local, assign the global, return
the local. This file pins that shape by AST for every ``NULLED_ATTRIBUTES``
name, in every function of its module: a read is only ever a copy into a
local (a double-checked getter copies twice, once each side of its lock). A
canary restores one old-shaped site and the pin names it; and the race is
forced deterministically on the real loaders and two warn-once sets (fails on
b2b1b86).

Version: v0.1.0 [2026-10-01]
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from engine.games import caches

ROOT = Path(__file__).resolve().parent.parent


def _module_path(module_name: str) -> Path:
    base = ROOT.joinpath(*module_name.split("."))
    return base / "__init__.py" if base.is_dir() else base.with_suffix(".py")


def _functions(tree: ast.AST) -> Iterator[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _own_names(fn: ast.AST, name: str) -> list[ast.Name]:
    """Every use of ``name`` in ``fn`` itself (not in a nested def)."""
    found: list[ast.Name] = []

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            if isinstance(child, ast.Name) and child.id == name:
                found.append(child)
            walk(child)

    walk(fn)
    return found


def racy_reads(source: str, name: str) -> list[str]:
    """
    Functions that USE ``name`` other than by copying it into a local: every
    read must be the whole right-hand side of an assignment to plain names
    (``cached = _C``), so what the function then tests, returns or mutates is
    its own copy, which no reset can null. A double-checked getter may copy it
    twice (outside and inside its lock); a ``return _C``, ``_C is not None``,
    ``_C.add(x)`` or ``_C[0]`` is the race. ``"func:line"`` of the last
    offending read in each function.
    """
    out: list[str] = []
    for fn in _functions(ast.parse(source)):
        copies: set[int] = set()
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Name)
                and node.value.id == name
                and all(isinstance(t, ast.Name) for t in node.targets)
            ):
                copies.add(id(node.value))
        bad = [
            n
            for n in _own_names(fn, name)
            if isinstance(n.ctx, ast.Load) and id(n) not in copies
        ]
        if bad:
            last = max(bad, key=lambda n: (n.lineno, n.col_offset))
            out.append(f"{fn.name}:{last.lineno}")  # type: ignore[attr-defined]
    return out


def test_every_nulled_cache_is_read_once_per_call():
    offenders = []
    for module_name, name in caches.NULLED_ATTRIBUTES:
        source = _module_path(module_name).read_text(encoding="utf-8")
        for where in racy_reads(source, name):
            offenders.append(f"{module_name}.{name} in {where}")
    assert not offenders, (
        "these functions use a cache a config reset nulls without a lock other than "
        "through a local copy, so a reset between two touches hands back None (or "
        "raises): read it once into a local, build into a local, assign the global, "
        f"return the local: {offenders}"
    )


def test_the_pin_catches_the_old_shape():
    """The canary: v0.19.0's loader shape, restored in memory, is named."""
    old = (
        "def load():\n"
        "    global _C\n"
        "    if _C is not None:\n"
        "        return _C\n"
        "    _C = {}\n"
        "    return _C\n"
    )
    assert racy_reads(old, "_C") == ["load:6"]
    fixed = (
        "def load():\n"
        "    global _C\n"
        "    cached = _C\n"
        "    if cached is not None:\n"
        "        return cached\n"
        "    built = {}\n"
        "    _C = built\n"
        "    return built\n"
    )
    assert racy_reads(fixed, "_C") == []


def test_the_pin_catches_a_restored_real_site():
    """The canary on a real file: procgen's loader put back the old way."""
    source = _module_path("engine.game.procgen").read_text(encoding="utf-8")
    assert racy_reads(source, "_TEMPLATE_CACHE") == []
    restored = source + (
        "\n\ndef _canary_old_shape():\n"
        "    global _TEMPLATE_CACHE\n"
        "    if _TEMPLATE_CACHE is not None:\n"
        "        return _TEMPLATE_CACHE\n"
        "    _TEMPLATE_CACHE = {}\n"
        "    return _TEMPLATE_CACHE\n"
    )
    assert [w.split(":")[0] for w in racy_reads(restored, "_TEMPLATE_CACHE")] == ["_canary_old_shape"]


# ---------------------------------------------------------------------------
# the race, forced
# ---------------------------------------------------------------------------


def _run_with_reset_after_each_store(fn: Callable[[], Any], module: Any, name: str) -> Any:
    """
    Call ``fn`` under a line tracer that, as soon as ``module.name`` becomes
    non-None, sets it back to None before the next line of the module's code
    runs: a config reset landing between the loader's store and its return,
    deterministically. (``global X; X = v`` writes the module's dict directly,
    so a tracer, not a ``__setattr__`` hook, is what can see it.)
    """
    import sys

    code_module = module.__name__

    def tracer(frame: Any, event: str, arg: Any) -> Any:
        if frame.f_globals.get("__name__") != code_module:
            return None  # other modules' frames run untraced
        if module.__dict__.get(name) is not None:
            module.__dict__[name] = None  # the reset
        return tracer

    sys.settrace(tracer)
    try:
        return fn()
    finally:
        sys.settrace(None)


LOADERS = [
    ("engine.game.procgen", "_TEMPLATE_CACHE", "load_templates"),
    ("engine.game.evil_ticker", "_DOOM_DECLARED", "doom_enabled"),
    ("engine.world.schedules", "_SCHEDULE_CACHE", "load_schedules"),
    ("engine.world.schedules", "_RUMOR_CACHE", "load_rumors"),
    ("engine.world.npc_sim", "_SCHEDULE_CACHE", "load_npc_schedules"),
    ("engine.world.premises", "_SPEC_CACHE", "_load"),
    ("engine.world.thievery", "_SPEC_CACHE", "load_spec"),
    ("engine.world.law", "_SPEC_CACHE", "load_spec"),
    ("engine.world.jobs", "_SPEC_CACHE", "spec"),
    ("engine.world.agendas", "_SPEC_CACHE", "spec"),
    ("engine.world.clues", "_SPEC_CACHE", "spec"),
    ("engine.media.comfyui", "_TEMPLATE_CACHE", "load_comfyui_templates"),
    ("engine.game.quests", "_ARC_CACHE", "load_arcs"),
    ("engine.game.quests", "_QUEST_CACHE", "load_quests"),
    ("engine.game.reputation", "_FACTION_CACHE", "load_factions"),
    ("engine.mcp.scene_rules_engine", "_rules_instance", "get_rules_engine"),
    ("engine.skills.builtin.mechanics", "_RECIPE_CACHE", "_load_recipes"),
]


@pytest.mark.parametrize(
    "module_name,name,loader", LOADERS, ids=[f"{m.rsplit('.', 1)[-1]}.{n}" for m, n, _ in LOADERS]
)
@pytest.mark.parametrize("slug", ["clockwork-dark", "hue-and-cry"])
def test_a_reset_between_a_loaders_store_and_its_return_still_yields_a_value(
    module_name, name, loader, slug
):
    """Fails on b2b1b86: the loader re-read the global after storing it."""
    from engine.games import registry

    registry.activate(slug)
    module = importlib.import_module(module_name)
    setattr(module, name, None)
    result = _run_with_reset_after_each_store(getattr(module, loader), module, name)
    assert result is not None, f"{module_name}.{loader} returned None after a reset"


WARN_ONCE = [
    ("engine.world.law", "_WARNED_ENCOUNTERS"),
    ("engine.world.jobs", "_WARNED_ARREST"),
    ("engine.game.encounter", "_WARNED_DEATH"),
    ("engine.content.director", "_WARNED_FORCED"),
]


def test_every_nulled_cache_is_covered_here():
    """Every NULLED_ATTRIBUTES entry is a loader above, a warn-once set, or
    the save stores (fixed in round 1, tested in test_thread_safety). The rules
    engine is no longer one: it is dropped under its lock by a RELOADER."""
    rules = ("engine.mcp.scene_rules_engine", "_rules_instance")
    covered = (
        {(m, n) for m, n, _ in LOADERS} - {rules}
        | set(WARN_ONCE)
        | {("engine.persistence.saves", "_stores")}
    )
    assert set(caches.NULLED_ATTRIBUTES) == covered
    assert ("engine.mcp.scene_rules_engine", "reset_rules_engine") in caches.RELOADERS


def test_a_reset_mid_warning_does_not_raise_for_missing_death_rules(monkeypatch, tmp_path):
    """Fails on b2b1b86 (``None.add``): a warn-once set nulled between its
    creation and its use."""
    from engine.game import encounter

    monkeypatch.setattr(encounter, "_death_rules_path", lambda: tmp_path / "no-death.yaml")
    monkeypatch.setattr(encounter, "_WARNED_DEATH", None)
    assert _run_with_reset_after_each_store(encounter.load_death_rules, encounter, "_WARNED_DEATH") == {}


"""
Local mode is unchanged: the local-mode golden, replayed.

THE INVARIANT. v0.20.0 adds Linux and a hosted, multi-user mode; a local,
single-player owner's game must not move. ``tests/local_golden.py`` recorded,
from untouched v0.19.0 code (e7fdd26), everything local mode shows (spec §1):
the app's shape, ``GET /``, the flagship and HUE & CRY played at a fixed seed
over HTTP and Socket.IO, the saves those runs wrote and where saves go, the
catalogue, settings, art and media routes, and the launcher. This file
captures it all again and compares it with ``tests/fixtures/local_mode/``.

A FAILURE HERE IS A REGRESSION, or a spec decision to take back to the
controller -- never a reason to re-record. The differences allowed are the
``SANCTIONED`` list, each a transform applied to the recorded fixture before
comparing, and each asserted to CHANGE that fixture, so a sanction that stops
applying fails rather than lingering as a loophole. v0.20.0 T1 records it
empty; T2 and T3 add the spec's two (the bind, and ``paths.saves`` leaving
the manifests), and there are no others.

The capture opens no socket (Flask's and Socket.IO's test clients), writes
nothing outside the test's temp directory (asserted, by an audit hook), and
reaches no model server (``tests/conftest.py``'s guards stay up).

``test_local_mode_never_imports_hosting`` builds the app and plays a turn in a
fresh interpreter (``tests/probes/local_mode_child.py``) and asserts no
``engine.hosting`` module was imported: local mode must never load hosting.
"""

from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.local_golden import (
    FIXTURES,
    OVERWRITE_ENV,
    RECORD_ENV,
    REPO,
    capture,
    dump_json,
    write,
)

def json_sanction(transform: Callable[[Any], None]) -> Callable[[str], str]:
    """
    A sanction applied to a JSON fixture's STRUCTURE: load it, let
    ``transform`` edit it in place (asserting what it touched), and dump it
    back exactly as the recorder writes fixtures (``dump_json``).
    """

    def apply(text: str) -> str:
        value = json.loads(text)
        transform(value)
        return dump_json(value)

    return apply


def without_paths_saves(expected: int) -> Callable[[str], str]:
    """
    Sanction 2 (spec §1, §4.2; lands in T3): ``"saves"`` leaves the ``paths``
    of each game row (``/api/games``) or manifest (``/api/games/active``,
    ``/api/games/<slug>``), and nowhere else; exactly ``expected`` removed.
    """

    def transform(value: Any) -> None:
        body = value["json"]
        if "games" in body:
            rows = body["games"]
        elif "manifest" in body:
            rows = [body["manifest"]]
        else:
            rows = [body]
        removed = 0
        for row in rows:
            paths = row.get("paths")
            if isinstance(paths, dict) and "saves" in paths:
                del paths["saves"]
                removed += 1
        assert removed == expected, f"removed paths.saves {removed} times, not {expected}"

    return json_sanction(transform)


#: Sanction 2 (checked by ``test_the_saves_sanction_is_exact``), in
#: ``SANCTIONED`` since v0.20.0 T3 made it true.
SAVES_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    ("games.json", without_paths_saves(6)),
    ("games_active.json", without_paths_saves(1)),
    ("games_clockwork-dark.json", without_paths_saves(1)),
    ("games_hue-and-cry.json", without_paths_saves(1)),
]

def loopback_bind(value: Any) -> None:
    """
    Sanction 1 (spec §1, §3.6; owner decision 2026-09-30, lands in T2): the
    local default bind goes from ``0.0.0.0`` to ``127.0.0.1``, and that is
    ``app_shape.json``'s ``run_kwargs.host`` and nothing else.
    (``launcher_main.json`` records ``run_scene(host=None)``: unchanged.)
    """
    run_kwargs = value["run_kwargs"]
    assert run_kwargs["host"] == "0.0.0.0", run_kwargs
    run_kwargs["host"] = "127.0.0.1"


#: ``(fixture name, transform)``: the recording, as the sanctioned change
#: makes it. Sanction 1 since v0.20.0 T2, sanction 2 (``SAVES_SANCTION``)
#: since T3, and there are no others.
SANCTIONED: list[tuple[str, Callable[[str], str]]] = [
    ("app_shape.json", json_sanction(loopback_bind)),
    *SAVES_SANCTION,
]


# -- writes outside the temp directory ---------------------------------------

#: Paths this process wrote while a capture ran, outside its temp root.
#: Kept on ``sys`` for ``tests/conftest.py``'s reason: this module may be
#: imported twice, and an audit hook cannot be removed, so it is installed once.
_WATCH_KEY = "_clockwork_dark_local_golden_watch"
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_EVENTS = frozenset({"os.rename", "os.mkdir", "os.remove", "os.rmdir"})


def _sqlite_target(database: Any) -> Any:
    """
    The file a ``sqlite3.connect`` opens, or None for an in-memory database.
    SQLite raises its own audit event, not ``open``, and creates a missing
    database file, so a lore or index database written outside the temp
    directory would otherwise go unseen.
    """
    if isinstance(database, bytes):
        database = os.fsdecode(database)
    if not isinstance(database, (str, os.PathLike)):
        return None
    text = os.fspath(database)
    if text in ("", ":memory:"):
        return None
    if text.startswith("file:"):
        path, _, query = text[5:].partition("?")
        if "mode=memory" in query or path in ("", ":memory:"):
            return None
        return path
    return text


def _watch_state() -> dict[str, Any]:
    state = getattr(sys, _WATCH_KEY, None)
    if state is None:
        state = {"roots": None, "writes": []}
        setattr(sys, _WATCH_KEY, state)
        sys.addaudithook(_audit)
    return state


def _outside(path: Any, roots: list[str]) -> bool:
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, (str, os.PathLike)):
        return False
    full = os.path.normcase(os.path.abspath(os.fspath(path)))
    if f"{os.sep}__pycache__{os.sep}" in full or full.endswith(f"{os.sep}__pycache__"):
        return False  # the interpreter's own bytecode cache, not the engine's
    return not any(full == r or full.startswith(r + os.sep) for r in roots)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    try:
        state = getattr(sys, _WATCH_KEY)
        roots = state["roots"]
        if roots is None:
            return
        if event == "open":
            path, mode, flags = args
            if isinstance(mode, str):
                if not any(c in mode for c in "wax+"):
                    return
            elif not (int(flags or 0) & _WRITE_FLAGS):
                return
            if _outside(path, roots):
                state["writes"].append((event, os.fspath(path)))
        elif event == "sqlite3.connect":
            target = _sqlite_target(args[0] if args else None)
            if target is not None and _outside(target, roots):
                state["writes"].append((event, target))
        elif event in _WRITE_EVENTS:
            for path in args[:2] if event == "os.rename" else args[:1]:
                if _outside(path, roots):
                    state["writes"].append((event, os.fspath(path)))
    except Exception:  # noqa: BLE001 -- an audit hook must never raise
        return


def _diff(name: str, recorded: str, now: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            recorded.splitlines(),
            now.splitlines(),
            f"recorded {name} (v0.19.0)",
            f"now {name}",
            lineterm="",
            n=3,
        )
    )


def _recorded() -> dict[str, str]:
    return {
        path.relative_to(FIXTURES).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(FIXTURES.rglob("*"))
        if path.is_file()
    }


@pytest.mark.default_storage_root  # save_base.json pins the DEFAULT root's layout
def test_local_mode_is_unchanged(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Everything local mode shows, compared with the v0.19.0 recording after the
    ``SANCTIONED`` transforms; a mismatch prints a unified diff per fixture.
    """
    # (Until v0.20.0 T3 this asserted the repo's `data/` existed: a manifest's
    # `paths.saves` was an output path whose PARENT validation checked, so a
    # checkout with no `data/` activated no story. The manifests no longer
    # declare it.)
    state = _watch_state()
    temp_root = os.path.normcase(os.path.abspath(tmp_path_factory.getbasetemp()))
    state["roots"] = [temp_root]
    state["writes"] = []
    try:
        now = capture(tmp_path, monkeypatch)
    finally:
        state["roots"] = None
    assert not state["writes"], f"the capture wrote outside its temp directory: {state['writes'][:5]}"

    if os.environ.get(RECORD_ENV) == "1":
        written = write(now, overwrite=os.environ.get(OVERWRITE_ENV) == "1")
        print(f"recorded {len(written)} fixtures under {FIXTURES}")
        return

    recorded = _recorded()
    assert recorded, f"no recording under {FIXTURES}"
    expected = dict(recorded)
    for name, transform in SANCTIONED:
        assert name in expected, f"sanction names no fixture: {name}"
        changed = transform(expected[name])
        assert changed != expected[name], f"the sanction on {name} no longer changes it"
        expected[name] = changed

    assert sorted(now) == sorted(expected), (
        f"fixtures missing from the capture: {sorted(set(expected) - set(now))}; "
        f"captured but never recorded: {sorted(set(now) - set(expected))}"
    )
    diffs = [
        f"--- {name} differs:\n{_diff(name, expected[name], now[name])}"
        for name in sorted(expected)
        if now[name] != expected[name]
    ]
    assert not diffs, "local mode changed:\n" + "\n\n".join(diffs)


def test_the_saves_sanction_is_exact() -> None:
    """
    Sanction 2 applies to the recording as spec §1 says: it changes each of
    its four fixtures, removes exactly the counted ``paths.saves`` keys, and
    leaves no ``"saves": "data/saves"`` behind and nothing else moved.
    """
    recorded = _recorded()
    for name, transform in SAVES_SANCTION:
        before = recorded[name]
        after = transform(before)
        assert after != before, name
        assert '"saves": "data/saves"' not in after, name
        removed = [
            line for line in difflib.ndiff(before.splitlines(), after.splitlines())
            if line.startswith(("- ", "+ "))
        ]
        assert removed and all(
            line.startswith("- ") and line.strip().rstrip(",").endswith('"saves": "data/saves"')
            for line in removed
        ), (name, removed)


def test_the_bind_sanction_is_exact() -> None:
    """
    Sanction 1 changes one line of the recording: ``"host": "0.0.0.0"`` to
    ``"host": "127.0.0.1"`` in ``app_shape.json``; no other fixture holds the
    old bind, and the launcher's recorded ``run_scene`` call still passes
    ``host=None``.
    """
    recorded = _recorded()
    (name, transform), = [(n, t) for n, t in SANCTIONED if n == "app_shape.json"]
    before = recorded[name]
    after = transform(before)
    changed = [
        line for line in difflib.ndiff(before.splitlines(), after.splitlines())
        if line.startswith(("- ", "+ "))
    ]
    assert [line[:2] + line[2:].strip() for line in changed] == [
        '- "host": "0.0.0.0",',
        '+ "host": "127.0.0.1",',
    ], changed
    assert [n for n, text in recorded.items() if "0.0.0.0" in text] == ["app_shape.json"]
    launcher = json.loads(recorded["launcher_main.json"])
    assert launcher["run_scene_calls"] == [{"host": None, "port": None}]


def test_local_mode_never_imports_hosting(tmp_path: Path) -> None:
    """
    Build the app, play one HTTP turn and one ``join_session`` in a fresh
    interpreter, after ``launcher.main([])``: no ``engine.hosting`` module
    may be loaded. (On e7fdd26 the package does not exist; the canary that
    imports it unconditionally lands with it, in v0.20.0 T7.)
    """
    probe = REPO / "tests" / "probes" / "local_mode_child.py"
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLOCKWORK_")}
    env.pop("LMSTUDIO_API_KEY", None)
    done = subprocess.run(
        [sys.executable, str(probe), str(tmp_path)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, f"the child failed:\n{done.stdout}\n{done.stderr[-4000:]}"
    last = done.stdout.strip().splitlines()[-1]
    report = json.loads(last)
    assert report["turn_status"] == 200, report
    assert report["joined"] == "game_started", report
    assert report["hosting_modules"] == [], report

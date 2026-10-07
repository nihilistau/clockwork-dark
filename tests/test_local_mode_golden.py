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
empty; v0.20.0 added S1 (the bind) and S2 (``paths.saves`` leaving the
manifests), and v0.21.0 adds S3 (the poster's and job panel's scales), S4
(``/api/people``), S5 (HUE & CRY's ``ui`` block), S6 (``turn_running`` on
a rejoin), S7 and S8 (the codex's souls and vendors), S9 (a resume in an open
encounter) and S10 (the pace slider's range, marks and hint). There are no
others.

The capture opens no socket (Flask's and Socket.IO's test clients), writes
nothing outside the test's temp directory (asserted, by an audit hook), and
reaches no model server (``tests/conftest.py``'s guards stay up).

``test_local_mode_never_imports_hosting`` builds the app and plays a turn in a
fresh interpreter (``tests/probes/local_mode_child.py``) and asserts no
``engine.hosting`` module was imported: local mode must never load hosting.
"""

from __future__ import annotations

import copy
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

#: S3 (v0.21.0, spec §1.2): per HUE & CRY fixture, the exact number of `law`
#: blocks and of `job` blocks that gain `scales` -- counted on the recording
#: (e6716b1). The flagship's fixtures hold neither (asserted below).
SCALES_COUNTS: dict[str, tuple[int, int]] = {
    "hue-and-cry/http_turns.json": (2, 2),
    "hue-and-cry/join_live.json": (2, 2),
    "hue-and-cry/new_game.json": (2, 2),
    "hue-and-cry/save_load.json": (1, 1),
    "hue-and-cry/socket_resume.json": (2, 2),
    "hue-and-cry/socket_stream_turn.json": (3, 3),
    "hue-and-cry/socket_turns.json": (2, 2),
    "hue-and-cry/state.json": (1, 1),
}

_HUE_SCALES: list[dict[str, Any]] = []


def hue_scales() -> dict[str, Any]:
    """
    HUE & CRY's scales, read at test time through the loaders the payload
    uses (``law.load_spec``, ``jobs.spec``), under the story's activation.
    """
    if not _HUE_SCALES:
        from engine.games import registry
        from engine.world import jobs, law

        registry.activate("hue-and-cry")
        try:
            spec = law.load_spec()
            jobs_spec = jobs.spec()
            _HUE_SCALES.append(
                {
                    "law": {
                        "wanted": [str(b) for b in spec["wanted"]["bands"]],
                        "clarity": [str(w) for w in (spec.get("clarity_words") or law.DEFAULT_CLARITY_WORDS)],
                    },
                    "job": {
                        "prep": [str(b) for b in jobs_spec["prep"]["bands"]],
                        "alarm": [*(str(b) for b in jobs_spec["alarm"]["bands"]), jobs.RAISED],
                    },
                }
            )
        finally:
            registry.deactivate()
    return _HUE_SCALES[0]


def _is_law(node: Any) -> bool:
    return isinstance(node, dict) and "clarity" in node and "wanted" in node


def _is_job(node: Any) -> bool:
    return isinstance(node, dict) and "prep" in node


def _walk_blocks(value: Any, visit: Callable[[str, dict[str, Any]], None]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "law" and _is_law(child):
                visit("law", child)
            elif key == "job" and _is_job(child):
                visit("job", child)
            _walk_blocks(child, visit)
    elif isinstance(value, list):
        for child in value:
            _walk_blocks(child, visit)


def count_scaled_blocks(value: Any) -> tuple[int, int]:
    """``(law blocks, job blocks)`` anywhere in a fixture."""
    counts = {"law": 0, "job": 0}
    _walk_blocks(value, lambda kind, _block: counts.__setitem__(kind, counts[kind] + 1))
    return counts["law"], counts["job"]


def with_scales(expected: tuple[int, int]) -> Callable[[str], str]:
    """S3: every `law` and `job` block gains its `scales`; exactly `expected` of each."""

    def transform(value: Any) -> None:
        scales = hue_scales()
        touched = {"law": 0, "job": 0}

        def visit(kind: str, block: dict[str, Any]) -> None:
            block["scales"] = copy.deepcopy(scales[kind])
            touched[kind] += 1

        _walk_blocks(value, visit)
        got = (touched["law"], touched["job"])
        assert got == expected, f"S3 touched {got} blocks, not {expected}"

    return json_sanction(transform)


SCALES_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    (name, with_scales(counts)) for name, counts in SCALES_COUNTS.items()
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


#: S1 as a named constant, so its exactness test selects it by what it is
#: rather than by its fixture (S4 is a second app_shape.json sanction).
BIND_SANCTION: tuple[str, Callable[[str], str]] = ("app_shape.json", json_sanction(loopback_bind))


def with_people_route(value: Any) -> None:
    """
    S4 (spec §1.2): `url_map` gains exactly `/api/people`, shaped as the
    story blueprint's other session routes (`/api/clues` is the model), in
    the capture's own (sorted) order.
    """
    rows = value["url_map"]
    clues = next(row for row in rows if row[0] == "/api/clues")
    assert not any(row[0] == "/api/people" for row in rows)
    rows.append(["/api/people", list(clues[1]), clues[2].replace("api_clues", "api_people")])
    rows.sort()


PEOPLE_SANCTION: tuple[str, Callable[[str], str]] = ("app_shape.json", json_sanction(with_people_route))


def with_turn_running(value: Any) -> None:
    """S6 (spec §1.2): the one recorded `game_started` gains `turn_running: false`."""
    started = [event for event in value if event.get("name") == "game_started"]
    assert len(started) == 1, started
    payload = started[0]["args"][0]
    assert "turn_running" not in payload
    payload["turn_running"] = False


JOIN_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    ("clockwork-dark/join_live.json", json_sanction(with_turn_running)),
    ("hue-and-cry/join_live.json", json_sanction(with_turn_running)),
]


#: The flagship's three vendors, as ``codex_things``' ``from`` recorded them
#: (the id, title-cased) and as S7 says them to a player who has not met
#: them (``the <role>``, the role from the canon templates).
S7_VENDORS: dict[str, str] = {"Maris": "the baker", "Odran": "the caravan master", "Ilya": "the tinker"}

SOULS_ROUTES = ("/api/codex/souls", "/api/codex/souls?session_id")
THINGS_ROUTES = ("/api/codex/things", "/api/codex/things?session_id")


def unmet_identities_withheld(value: Any) -> None:
    """
    S7 (spec §1.2, added in T3 fix round 1; the review's finding 9): the
    codex stops identifying people the player has not met. With no session
    nobody is met (the canon cast was all "met": name, traits, portrait); an
    unmet soul's ``id`` is its opaque per-response key ``s<index>``; an unmet
    vendor in ``codex_things``' ``from`` is "the <role>". Roles are gated now
    too, but no recorded role is masked, so none moves.
    """
    for route in SOULS_ROUTES:
        souls = value[route]["json"]["souls"]
        for index, soul in enumerate(souls):
            if route == "/api/codex/souls" and soul["met"]:
                soul.update(met=False, name="Someone", traits=[], portrait="")
            assert soul["met"] is False, (route, soul)
            soul["id"] = f"s{index}"
    for route in THINGS_ROUTES:
        for thing in value[route]["json"]["things"]:
            if thing["from"]:
                thing["from"] = S7_VENDORS[thing["from"]]


CODEX_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    ("clockwork-dark/story_routes.json", json_sanction(unmet_identities_withheld)),
    ("hue-and-cry/story_routes.json", json_sanction(unmet_identities_withheld)),
]

#: S7's exact effect per fixture: (soul ids made opaque, no-session souls
#: made unmet, vendor ``from`` lines that stop naming).
CODEX_COUNTS: dict[str, tuple[int, int, int]] = {
    "clockwork-dark/story_routes.json": (13, 5, 104),
    "hue-and-cry/story_routes.json": (79, 0, 0),
}


#: Every vendor the two recordings name, as the map's points and the pack's
#: ``vendor`` recorded them (full name, or the title-cased id) and as S8 says
#: them to a player who has met none of them (``the <role>``).
S8_VENDORS: dict[str, str] = {
    "Maris Hearth": "the baker", "Maris": "the baker",
    "Odran Cartwright": "the caravan master", "Odran": "the caravan master",
    "Ilya of the Nine Pins": "the tinker", "Ilya": "the tinker",
    "Sera of the Gate": "the militia",
    "Brindle": "the cat",
    "Pell Hollis": "the fence", "Marrow": "the fence",
    "Dock Mag": "the porter boss",
}
ITEMS_ROUTES = ("/api/items", "/api/items?session_id")
PLACES_ROUTE = "/api/codex/places?session_id"
TRADE_ROUTE = "/api/trade?session_id"


def vendors_unnamed(value: Any) -> None:
    """
    S8 (spec §1.2, added in T3 fix round 2; re-review R2): S7's rule reaches
    the three sibling routes that named every vendor. The map's vendor
    points (``/api/codex/places?session_id``; with no session there are no
    points) and the pack's ``vendor`` (``/api/items``, both answers) say
    "the <role>"; the barter screen's stranger (``/api/trade?session_id``)
    gets an opaque ``npc_id`` ``v<index>``, ``name`` "the <role>" and
    ``known: false``. Nobody in either recording is met.
    """
    for place in value[PLACES_ROUTE]["json"]["places"]:
        for point in place.get("points") or []:
            if point["kind"] == "vendor":
                point["label"] = S8_VENDORS[point["label"]]
    for route in ITEMS_ROUTES:
        for item in value[route]["json"]["items"]:
            if item["vendor"]:
                item["vendor"] = S8_VENDORS[item["vendor"]]
    for index, vendor in enumerate(value[TRADE_ROUTE]["json"]["vendors"]):
        vendor.update(npc_id=f"v{index}", name=S8_VENDORS[vendor["name"]], known=False)


VENDORS_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    ("clockwork-dark/story_routes.json", json_sanction(vendors_unnamed)),
    ("hue-and-cry/story_routes.json", json_sanction(vendors_unnamed)),
]

#: S8's exact effect per fixture: (map vendor points, pack ``vendor``
#: lines, barter-screen vendors) renamed.
VENDORS_COUNTS: dict[str, tuple[int, int, int]] = {
    "clockwork-dark/story_routes.json": (5, 104, 1),
    "hue-and-cry/story_routes.json": (3, 36, 0),
}


#: S9's four approaches, as ``watch_stop`` offers them in the recorded state
#: (no ``bribe``: the recorded purse cannot pay it), in the order
#: ``encounter.available_approaches`` lists them.
S9_APPROACHES: list[dict[str, Any]] = [
    {"id": f"resume_encounter_{target}", "intent": {"action": "encounter", "target": target}, "text": text}
    for target, text in (
        ("run", "Bolt into the crowd before the whistle"),
        ("talk", "Explain, reasonably, that he has the wrong face"),
        ("surrender", "Hold out your wrists and go quietly"),
        ("fight", "Knock the lamp aside and hit him"),
    )
]
#: S9's exact effect: resumed frames whose two roads are replaced.
S9_COUNT = 1


def resume_offers_the_open_encounter(value: Any) -> None:
    """
    S9 (spec §1.2, added in the encounter-resume fix): the recorded resume
    lands during an open ``watch_stop``, and ``resume_opening`` offered it two
    roads the open scene refuses and no approach (bug 1). The two
    ``resume_go_*`` travel choices become the scene's four ``encounter``
    choices; ``resume_look`` and ``resume_wait`` stay. Raises unless exactly
    ``S9_COUNT`` frames are touched.
    """
    touched = 0
    for event in value:
        for arg in event.get("args") or []:
            opening = arg.get("opening") if isinstance(arg, dict) else None
            if not isinstance(opening, dict):
                continue
            choices = opening.get("choices") or []
            roads = [i for i, c in enumerate(choices) if str(c.get("id", "")).startswith("resume_go_")]
            if not roads:
                continue
            assert len(roads) == 2 and roads == [roads[0], roads[0] + 1], choices
            assert all(choices[i]["intent"]["action"] == "travel" for i in roads), choices
            choices[roads[0]:roads[1] + 1] = copy.deepcopy(S9_APPROACHES)
            assert [c["id"] for c in (choices[0], choices[-1])] == ["resume_look", "resume_wait"], choices
            touched += 1
    assert touched == S9_COUNT, f"S9 touched {touched} resumed frames, not {S9_COUNT}"


RESUME_SANCTION: tuple[str, Callable[[str], str]] = (
    "hue-and-cry/socket_resume.json",
    json_sanction(resume_offers_the_open_encounter),
)


#: S10's one row, as recorded (v0.19.0 code) and as the slider fix makes it.
S10_KEY = "world.evil_base_rate_per_day"
S10_BEFORE: dict[str, Any] = {
    "max": 0.02,
    "hint": (
        "The difficulty slider. 0.006 reaches CONSUMING near day 130; "
        "0.012 does it in half that; below 0.003 the world is still quiet "
        "at day 40 and the premise evaporates."
    ),
    "marks": {"0.003": "Slow", "0.006": "Measured", "0.012": "Hunted"},
}
S10_AFTER: dict[str, Any] = {
    "max": 0.05,
    "hint": (
        "The base rate of the doom clock, per in-game day. When the shipped "
        "0.028 was chosen (scripts/simulate.py, 200 turns, seed 42), the "
        "median run ended DORMANT at 0.006 and STIRRING at 0.020, and at 0.028 "
        "it only just reached SPREADING (the baker's run, just); at 0.032 a "
        "reckless player's world reached CONSUMING."
    ),
    "marks": {"0.006": "Dormant", "0.020": "Stirring", "0.028": "Spreading"},
}


def pace_slider_holds_its_default(value: Any) -> None:
    """
    S10 (spec §1.2, v0.21.0 T13 fix round 1): ``/api/settings``' pace row
    (``world.evil_base_rate_per_day``) had max 0.02, marks and a hint written
    for the old 0.006 default, while the value it reports is the shipped
    0.028. Its ``max``, ``hint`` and ``marks`` become ``S10_AFTER``; nothing
    else in the answer moves. Raises unless exactly one row matches the
    recorded ``S10_BEFORE``.
    """
    rows = [row for row in value["json"]["settings"] if row["key"] == S10_KEY]
    assert len(rows) == 1, rows
    row = rows[0]
    assert {k: row[k] for k in S10_BEFORE} == S10_BEFORE, row
    row.update(S10_AFTER)


SLIDER_SANCTION: tuple[str, Callable[[str], str]] = ("settings.json", json_sanction(pace_slider_holds_its_default))


#: S5 (v0.21.0, spec §9): HUE & CRY wears its own skin and declares its panels.
HUE_PANELS = ["wanted", "casing", "job", "people", "encounter", "negotiation", "rolls"]


def with_hue_ui(value: Any) -> None:
    """The HUE & CRY row's `ui` and `ui_plugin`, and nothing else."""
    body = value["json"]
    rows = body["games"] if "games" in body else [body]
    touched = 0
    for row in rows:
        if row.get("slug") != "hue-and-cry":
            continue
        assert row["ui"] == {"plugin": "_engine"} and row["ui_plugin"] == "_engine", row
        row["ui"] = {"plugin": "hue-and-cry", "panels": list(HUE_PANELS)}
        row["ui_plugin"] = "hue-and-cry"
        touched += 1
    assert touched == 1, f"S5 touched {touched} rows"


UI_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    ("games.json", json_sanction(with_hue_ui)),
    ("games_hue-and-cry.json", json_sanction(with_hue_ui)),
]


#: ``(fixture name, transform)``: the recording, as the sanctioned change
#: makes it. S1 since v0.20.0 T2, S2 since T3, S3-S10 since v0.21.0
#: (spec §1.2; S7 added in T3 fix round 1, S8 in fix round 2, S9 in the
#: encounter-resume fix, S10 in T13 fix round 1, S5 in T14); there are no
#: others.
SANCTIONED: list[tuple[str, Callable[[str], str]]] = [
    BIND_SANCTION,
    *SAVES_SANCTION,
    *SCALES_SANCTION,
    PEOPLE_SANCTION,
    *JOIN_SANCTION,
    *CODEX_SANCTION,
    *VENDORS_SANCTION,
    RESUME_SANCTION,
    SLIDER_SANCTION,
    *UI_SANCTION,
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
    name, transform = BIND_SANCTION
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


def test_the_v021_sanctions_are_exact() -> None:
    """
    Spec §1.2: each v0.21.0 sanction changes exactly what it names. S3 adds
    `scales` to the counted HUE & CRY blocks and touches no flagship fixture;
    S4 adds the one `/api/people` route row and nothing else; S6 adds
    `turn_running: false` to the one `game_started` of each fixture that holds
    one, and no other fixture holds one; S7 (T3 fix round 1) moves exactly
    the counted soul ids, no-session souls and vendor lines; S8 (fix round
    2) the counted map vendor points, pack vendor lines and barter vendors;
    S9 (the encounter-resume fix) replaces exactly the two roads of the one
    HUE & CRY resumed frame with the open scene's four approaches; S10 the
    one pace row; S5 (T14) exactly the HUE & CRY catalogue row's `ui` and
    `ui_plugin`, in the two fixtures that hold that row.
    """
    recorded = _recorded()
    for name, transform in SCALES_SANCTION:
        before = recorded[name]
        after = transform(before)
        assert after != before, name
        assert count_scaled_blocks(json.loads(before)) == SCALES_COUNTS[name], name
        assert after.count('"scales"') - before.count('"scales"') == sum(SCALES_COUNTS[name]), name
    # Every other fixture -- the flagship's, and the shared top-level ones --
    # holds no law or job block for S3 to touch.
    for name, text in recorded.items():
        if name.endswith(".json") and name not in SCALES_COUNTS:
            assert count_scaled_blocks(json.loads(text)) == (0, 0), name

    name, transform = PEOPLE_SANCTION
    before, after = json.loads(recorded[name]), json.loads(transform(recorded[name]))
    assert len(after["url_map"]) == len(before["url_map"]) + 1
    added = [row for row in after["url_map"] if row not in before["url_map"]]
    assert added == [["/api/people", ["GET", "HEAD", "OPTIONS"], "default_story.api_people"]]
    assert {k: v for k, v in after.items() if k != "url_map"} == {k: v for k, v in before.items() if k != "url_map"}

    for name, transform in JOIN_SANCTION:
        assert recorded[name].count('"game_started"') == 1, name
        assert transform(recorded[name]).count('"turn_running": false') == 1, name
    holders = [n for n, text in recorded.items() if '"game_started"' in text]
    assert sorted(holders) == sorted(n for n, _ in JOIN_SANCTION)

    # S7: exactly the counted souls and vendor lines, and nothing else.
    for name, transform in CODEX_SANCTION:
        before, after = json.loads(recorded[name]), json.loads(transform(recorded[name]))
        ids = made_unmet = froms = 0
        for route in SOULS_ROUTES:
            for old, new in zip(before[route]["json"]["souls"], after[route]["json"]["souls"], strict=True):
                ids += old["id"] != new["id"]
                made_unmet += old["met"] != new["met"]
                assert {k: v for k, v in new.items() if k not in ("id", "met", "name", "traits", "portrait")} == {
                    k: v for k, v in old.items() if k not in ("id", "met", "name", "traits", "portrait")
                }, (name, old)
        for route in THINGS_ROUTES:
            for old, new in zip(before[route]["json"]["things"], after[route]["json"]["things"], strict=True):
                froms += old["from"] != new["from"]
                assert {k: v for k, v in new.items() if k != "from"} == {k: v for k, v in old.items() if k != "from"}
        assert (ids, made_unmet, froms) == CODEX_COUNTS[name], name
        untouched = set(before) - set(SOULS_ROUTES) - set(THINGS_ROUTES)
        assert {k: after[k] for k in untouched} == {k: before[k] for k in untouched}, name
    # S8: exactly the counted vendor points, pack lines and barter vendors.
    for name, transform in VENDORS_SANCTION:
        before = json.loads(recorded[name])
        after = json.loads(transform(recorded[name]))
        points = sum(
            old != new
            for old_place, new_place in zip(before[PLACES_ROUTE]["json"]["places"], after[PLACES_ROUTE]["json"]["places"], strict=True)
            for old, new in zip(old_place.get("points") or [], new_place.get("points") or [], strict=True)
        )
        lines = sum(
            old["vendor"] != new["vendor"]
            for route in ITEMS_ROUTES
            for old, new in zip(before[route]["json"]["items"], after[route]["json"]["items"], strict=True)
        )
        traders = len(after[TRADE_ROUTE]["json"]["vendors"])
        assert (points, lines, traders) == VENDORS_COUNTS[name], name
        for route in ITEMS_ROUTES:
            for old, new in zip(before[route]["json"]["items"], after[route]["json"]["items"], strict=True):
                assert {k: v for k, v in new.items() if k != "vendor"} == {k: v for k, v in old.items() if k != "vendor"}
        for old, new in zip(before[TRADE_ROUTE]["json"]["vendors"], after[TRADE_ROUTE]["json"]["vendors"], strict=True):
            assert set(new) - set(old) == {"known"}
            assert {k: v for k, v in new.items() if k not in ("npc_id", "name", "known")} == {
                k: v for k, v in old.items() if k not in ("npc_id", "name")
            }
        for old_place, new_place in zip(before[PLACES_ROUTE]["json"]["places"], after[PLACES_ROUTE]["json"]["places"], strict=True):
            assert {k: v for k, v in new_place.items() if k != "points"} == {k: v for k, v in old_place.items() if k != "points"}
            assert [p["kind"] for p in new_place.get("points") or []] == [p["kind"] for p in old_place.get("points") or []]
        untouched = set(before) - {PLACES_ROUTE, TRADE_ROUTE, *ITEMS_ROUTES}
        assert {k: after[k] for k in untouched} == {k: before[k] for k in untouched}, name

    # Only those two fixtures record a codex ANSWER (app_shape.json names the
    # route, as a url_map row, and is S1/S4's).
    souls_holders = [n for n, text in recorded.items() if '"/api/codex/souls": {' in text]
    assert sorted(souls_holders) == sorted(CODEX_COUNTS)

    # S9: exactly two roads out, four approaches in, nothing else moved.
    name, transform = RESUME_SANCTION
    before, after = json.loads(recorded[name]), json.loads(transform(recorded[name]))
    old_choices = before[0]["args"][0]["opening"]["choices"]
    new_choices = after[0]["args"][0]["opening"]["choices"]
    removed = [c for c in old_choices if c not in new_choices]
    added = [c for c in new_choices if c not in old_choices]
    assert [c["id"] for c in removed] == ["resume_go_wickmarket", "resume_go_the_snuffs"], removed
    assert added == S9_APPROACHES, added
    assert len(new_choices) == len(old_choices) + 2
    after[0]["args"][0]["opening"]["choices"] = old_choices
    assert after == before, name
    # A transform that touches no frame raises rather than passing quietly.
    with pytest.raises(AssertionError, match="S9 touched 0"):
        resume_offers_the_open_encounter([{"args": [{"opening": {"choices": [{"id": "resume_look"}]}}]}])
    # The flagship's resume is not S9's: it lands with no scene open.
    flagship = recorded["clockwork-dark/socket_resume.json"]
    assert '"resume_go_' in flagship and "resume_encounter_" not in flagship

    # S10: the one pace row's max, hint and marks, and nothing else.
    name, transform = SLIDER_SANCTION
    before, after = json.loads(recorded[name]), json.loads(transform(recorded[name]))
    changed = [(old["key"], new) for old, new in zip(before["json"]["settings"], after["json"]["settings"], strict=True) if old != new]
    assert [key for key, _ in changed] == [S10_KEY], changed
    old_row = next(r for r in before["json"]["settings"] if r["key"] == S10_KEY)
    new_row = changed[0][1]
    assert {k: v for k, v in new_row.items() if k not in S10_AFTER} == {k: v for k, v in old_row.items() if k not in S10_AFTER}
    assert new_row["min"] <= new_row["value"] <= new_row["max"], new_row
    after["json"]["settings"] = before["json"]["settings"]
    assert after == before, name
    # A transform whose recorded row has moved on raises rather than passing.
    with pytest.raises(AssertionError):
        pace_slider_holds_its_default({"json": {"settings": [{"key": S10_KEY, **S10_AFTER}]}})

    # S5: the HUE & CRY row's `ui` and `ui_plugin`, and no other key or row.
    for name, transform in UI_SANCTION:
        before, after = json.loads(recorded[name]), json.loads(transform(recorded[name]))
        rows_before = before["json"]["games"] if "games" in before["json"] else [before["json"]]
        rows_after = after["json"]["games"] if "games" in after["json"] else [after["json"]]
        assert len(rows_before) == len(rows_after), name
        for old, new in zip(rows_before, rows_after, strict=True):
            changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
            assert changed == ({"ui", "ui_plugin"} if old.get("slug") == "hue-and-cry" else set()), (name, old.get("slug"), changed)
        assert {k: v for k, v in after.items() if k != "json"} == {k: v for k, v in before.items() if k != "json"}, name
    # The other catalogue fixtures hold no HUE & CRY row: S5, applied to
    # them, touches nothing and so raises (C17), rather than passing quietly.
    for untouched in ("games_active.json", "games_clockwork-dark.json"):
        with pytest.raises(AssertionError, match="S5 touched 0 rows"):
            json_sanction(with_hue_ui)(recorded[untouched])


def test_hue_scales_reads_the_shipped_bands() -> None:
    """
    ``hue_scales`` re-reads the scales through the payload's own loaders
    (spec-mandated), so it would follow a broken loader; these are the
    shipped words, written out once (T2 review 1-2, final review 38).
    """
    assert hue_scales() == {
        "law": {
            "wanted": ["unknown", "noticed", "sought", "wanted", "hunted"],
            "clarity": ["nothing", "a rumour", "a description", "a likeness"],
        },
        "job": {
            "prep": ["none", "a little", "some", "plenty"],
            "alarm": ["quiet", "uneasy", "stirring", "restless", "roused", "raised"],
        },
    }

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
encounter) and S10 (the pace slider's range, marks and hint), and v0.22.0
adds S11 (READ RECEIPTS's row in the catalogue), and v0.24.0 adds S13 (the
sound blueprint's three URL rules) and S12 (``paths.sounds`` in the catalogue rows
of the stories that declare sounds: five rows, ``EXPECTED_SOUNDS_ROWS``), and
v0.25.0 adds S14 (the overlay's route and socket handler), S15 (the
factions route), S16 (the codex's declared souls), S17 (Nessa met in the
flagship's recorded run), S18 (the flagship's banded roads and its two
secret places on the no-session map) and S19 (the flagship's doors named: its
gallery's gates, lock reasons and teases, and its `paths.decks`) and S20 (the
flagship's levy and bargain declared: an empty `threads` list in each of its
state blocks, and `paths.clocks` and `paths.threads` in its catalogue rows).
There are no others.

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

from engine.games.registry import catalog_key
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


def with_overlay_door(value: Any) -> None:
    """
    S14 (v0.25.0 T2, spec §6.4, §7.1): `url_map` gains exactly `/api/intents/overlay`,
    shaped as the story blueprint's other session routes, and the default namespace's
    socket handlers gain exactly `overlay_action`.
    """
    rows = value["url_map"]
    clues = next(row for row in rows if row[0] == "/api/clues")
    assert not any(row[0] == "/api/intents/overlay" for row in rows)
    rows.append(["/api/intents/overlay", list(clues[1]), clues[2].replace("api_clues", "api_overlay_intents")])
    rows.sort()
    handlers = value["socketio_handlers"]["/"]
    assert "overlay_action" not in handlers
    handlers.append("overlay_action")
    handlers.sort()


OVERLAY_SANCTION: tuple[str, Callable[[str], str]] = ("app_shape.json", json_sanction(with_overlay_door))


def with_factions_route(value: Any) -> None:
    """
    S15 (v0.25.0 T3, spec §6.4): `url_map` gains exactly `/api/factions`, shaped
    as the story blueprint's other session routes (`/api/clues` is the model).
    """
    rows = value["url_map"]
    clues = next(row for row in rows if row[0] == "/api/clues")
    assert not any(row[0] == "/api/factions" for row in rows)
    rows.append(["/api/factions", list(clues[1]), clues[2].replace("api_clues", "api_factions")])
    rows.sort()


FACTIONS_SANCTION: tuple[str, Callable[[str], str]] = ("app_shape.json", json_sanction(with_factions_route))


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


#: S11 (v0.22.0, spec §19.6): READ RECEIPTS joins the catalogue. One row is
#: added where the catalogue's order puts it, and nothing else moves.
READ_RECEIPTS_ROW: dict[str, Any] = {
    # Written by hand from games/read-receipts/game.yaml in T2 (engine_requires
    # ">=0.2.0", Plan decision 23: ">=0.22.0" would make the row unplayable),
    # every key the other rows carry with this story's values, plus the one
    # extra its manifest declares (`endless`). Reviewed against a live
    # registry.catalog() row once, by hand. Edited in place since: v0.23.0
    # T10 (`entry_location`), T11 (`version`, the directives, `paths.decks`), T23F (`paths.npc_schedules`), T26 (the three `paths.art_*`), v0.24.0 T9 (`paths.sounds`).
    "active": False,
    "archetypes": [],
    "blurb": (
        "A new city, a new phone, two dating apps. Everyone in them is somebody, "
        "and somebody is always typing."
    ),
    "endless": True,
    "engine_requires": ">=0.2.0",
    "entry_location": "apt_lounge",
    "id": "read-receipts",
    "paths": {
        "art_manifest": "games/read-receipts/data/art/manifest.yaml",
        "art_root": "games/read-receipts/data/art/plates",
        "art_subjects": "games/read-receipts/data/art/subjects.yaml",
        "decks": "games/read-receipts/data/scenes",
        "locations": "games/read-receipts/data/world/locations.yaml",
        "npc_schedules": "games/read-receipts/data/world/npc_schedules.yaml",
        "prompts": "games/read-receipts/prompts",
        "social": "games/read-receipts/data/social",
        "sounds": "games/read-receipts/data/sounds",
    },
    "playable": True,
    "problems": [],
    "scene": {
        "blueprint": "engine.scenes.default_api:story_blueprint",
        "module": "engine.scenes.default_scene",
        "name": "clockwork",
    },
    "settings": {
        "governance.directives": ["StorytellerMind", "SocialWorld"],
        "world.evil_base_rate_per_day": 0.0,
        "world.tick_hours": 0.0,
    },
    "slug": "read-receipts",
    "title": "Read Receipts",
    "ui": {"panels": [], "plugin": "read-receipts"},
    "ui_plugin": "read-receipts",
    "version": "0.2.0",
}


def with_read_receipts(value: Any) -> None:
    """The READ RECEIPTS row, added where ``catalog_key`` sorts it, and nothing else."""
    body = value["json"]
    rows = body["games"]
    assert all(row.get("slug") != "read-receipts" for row in rows), "S11 applied twice"
    rows.append(copy.deepcopy(READ_RECEIPTS_ROW))
    rows.sort(key=catalog_key)  # engine.games.registry.catalog_key: the route's own sort key
    assert len(rows) == 7, f"S11 left {len(rows)} rows"


RECEIPTS_SANCTION: tuple[str, Callable[[str], str]] = ("games.json", json_sanction(with_read_receipts))


#: S13 (v0.24.0 spec §10): the sound blueprint's three URL rules, and nothing else in the app's shape.
SOUND_RULES: list[list[Any]] = [
    ["/api/sounds", ["GET", "HEAD", "OPTIONS"], "sounds.api_sounds"],
    ["/api/sounds/catalog", ["GET", "HEAD", "OPTIONS"], "sounds.api_catalog"],
    ["/sound/<scope>/<path:name>", ["GET", "HEAD", "OPTIONS"], "sounds.sound_file"],
]


def with_sound_rules(value: Any) -> None:
    rules = value["url_map"]
    assert not any(r[0].startswith(("/api/sounds", "/sound/")) for r in rules), "S13 applied twice"
    rules.extend(copy.deepcopy(SOUND_RULES))
    rules.sort()  # the recorder's own order (capture: `sorted([rule, sorted(methods), endpoint] ...)`)


SOUND_RULES_SANCTION: tuple[str, Callable[[str], str]] = ("app_shape.json", json_sanction(with_sound_rules))

#: S12 (v0.24.0 spec §10): `paths.sounds` in each declaring story's catalogue rows, filled by the task that
#: makes the story declare it (T9 READ RECEIPTS, through READ_RECEIPTS_ROW, which carries its value since T9 and so
#: is NOT in this table -- listing it here would apply S12 twice; T10 the other five, below). dev-story declares
#: nothing and is the byte-identity proof.
EXPECTED_SOUNDS_ROWS: dict[str, str] = {
    "clockwork-dark": "games/clockwork-dark/data/sounds",
    "wicked-garden": "games/wicked-garden/data/sounds",
    "neon-city": "games/neon-city/data/sounds",
    "the-long-con": "games/the-long-con/data/sounds",
    "hue-and-cry": "games/hue-and-cry/data/sounds",
}


def with_sounds_paths(expected: int) -> Callable[[str], str]:
    """S12: `paths.sounds` gains its value in each declaring story's game row (`/api/games`) or manifest
    (`/api/games/active`, `/api/games/<slug>`), and nowhere else; exactly `expected` rows."""

    def transform(value: Any) -> None:
        body = value["json"]
        if "games" in body:
            rows = body["games"]
        elif "manifest" in body:
            rows = [body["manifest"]]
        else:
            rows = [body]
        touched = 0
        for row in rows:
            slug = row.get("slug")
            if slug in EXPECTED_SOUNDS_ROWS:
                assert "sounds" not in row["paths"], "S12 applied twice"
                row["paths"]["sounds"] = EXPECTED_SOUNDS_ROWS[slug]
                touched += 1
        assert touched == expected, f"S12 touched {touched}, not {expected}"

    return json_sanction(transform)


#: S12's fixtures and counts: READ RECEIPTS' row is S11's constant, edited in place by T9.
SOUNDS_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    ("games.json", with_sounds_paths(5)),
    ("games_active.json", with_sounds_paths(1)),
    ("games_clockwork-dark.json", with_sounds_paths(1)),
    ("games_hue-and-cry.json", with_sounds_paths(1)),
]


#: S16's rows per fixture, in the schedule file's order: ``(role, place)`` of each
#: person the story declares in ``npc_schedules.yaml`` and its procgen list lacks.
#: The flagship's four (v0.25.0 T4, §3.3); HUE & CRY's whole declared cast.
S16_DECLARED: dict[str, list[tuple[str, str]]] = {
    "clockwork-dark/story_routes.json": [
        ("smith", "Well Row"), ("child", "The Fallow Holding"),
        ("shrine keeper", "Well Row"), ("farmer", "The Fallow Holding"),
    ],
    "hue-and-cry/story_routes.json": [
        ("captain", "The Lantern House"), ("sergeant", "The Lantern House"),
        ("watch", "The Lantern House"), ("watch", "The Lantern House"),
        ("guild head", "The Snuffs"), ("upstart", "The Snuffs"), ("fence", "Wickmarket"),
        ("fence", "The Snuffs"), ("steward", "Margrave's Hill"), ("noble", "Silk Row"),
        ("chandler", "Chandlers' Rise"), ("priest", "Chandlers' Rise"),
        ("porter boss", "Tallow Docks"), ("lamplighter", "The Snuffs"),
    ],
}


def with_declared_souls(rows: list[tuple[str, str]]) -> Callable[[str], str]:
    """
    S16 (v0.25.0 T4, spec §8.7): both souls answers gain exactly the story's declared
    people the procgen list lacks, after the recorded souls and unmet (opaque ``s<index>``,
    "Someone", no traits or portrait), each its role and home. Nothing else moves.
    """

    def transform(value: Any) -> None:
        for route in SOULS_ROUTES:
            souls = value[route]["json"]["souls"]
            for role, place in rows:
                souls.append({
                    "canon": False, "disposition": 0, "first_met_day": 0, "id": f"s{len(souls)}",
                    "met": False, "name": "Someone", "place": place, "portrait": "", "role": role,
                    "traits": [],
                })

    return json_sanction(transform)


DECLARED_SOULS_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    (name, with_declared_souls(rows)) for name, rows in S16_DECLARED.items()
]

#: S17's fixture and the memory files in it that gain Nessa's relation.
S17_FIXTURE = "save_tree_clockwork-dark.json"
S17_MEMORIES = ("<save-1>/memory.json", "<save-1>/memory.json.bak")


def with_nessa_met(value: Any) -> None:
    """
    S17 (v0.25.0 T4, §3.3): the flagship's recorded run stands in Edgewood Square on day 1
    in Nessa Fallow's hours (09-16), so its memory (and the backup) meets her there, as it
    met the people already standing there. Exactly one relation per memory file.
    """
    for name in S17_MEMORIES:
        relations = value[name]["relations"]
        assert "npc_nessa" not in relations, "S17 applied twice"
        relations["npc_nessa"] = {
            "debts": [], "disposition": 0, "first_met_day": 1, "kind": "npc", "known_facts": [],
            "last_seen_day": 1, "last_seen_location": "edgewood_square", "met": True, "notes": [],
            "npc_id": "npc_nessa", "owed": [], "tags": [], "trust": 0,
        }


NESSA_SANCTION: tuple[str, Callable[[str], str]] = (S17_FIXTURE, json_sanction(with_nessa_met))


#: S18's fixture, its two map routes, and the 22 roads that carried `danger_dc: 0`
#: with a `# needs band` note in the recording and carry a band's number since
#: v0.25.0 T5 (§5.3), each with that number.
S18_FIXTURE = "clockwork-dark/story_routes.json"
S18_ROUTES = ("/api/codex/places", "/api/codex/places?session_id")
S18_BANDED: dict[str, int] = {
    "forest_clearing>deeper_forest": 6, "deeper_forest>forest_clearing": 6,
    "forest_clearing>herb_glen": 6, "herb_glen>forest_clearing": 6,
    "deeper_forest>herb_glen": 6, "herb_glen>deeper_forest": 6,
    "deeper_forest>charcoal_burn": 6, "charcoal_burn>deeper_forest": 6,
    "edgewood_square>charcoal_burn": 6, "edgewood_square>fallow_farm": 6,
    "deeper_forest>old_barrows": 10, "old_barrows>deeper_forest": 10,
    "old_barrows>tunnel_entrance": 10, "tunnel_entrance>old_barrows": 10,
    "millhaven_gate>toll_bridge": 10, "toll_bridge>burned_farmstead": 10,
    "burned_farmstead>toll_bridge": 10, "refugee_camp>burned_farmstead": 10,
    "burned_farmstead>refugee_camp": 10, "millhaven_gate>refugee_camp": 10,
    "toll_bridge>heartland_road": 14, "heartland_road>toll_bridge": 14,
}
#: The two secret places as the no-session map draws them (a codex with no
#: player knows every place), each after the place it follows in the graph, and
#: the road to each from its one neighbour (last in that neighbour's roads).
S18_PLACES: tuple[tuple[str, dict[str, Any], tuple[str, dict[str, Any]]], ...] = (
    ("tunnel_entrance", {
        "discovered": True, "here": False, "id": "the_works", "image": "",
        "name": "The Works Below the Stump", "points": [], "ring": 0,
        "roads": [{"danger_dc": 12, "hours": 1, "name": "Forest Clearing", "to": "forest_clearing"}],
    }, ("forest_clearing", {"danger_dc": 12, "hours": 1, "name": "The Works Below the Stump", "to": "the_works"})),
    ("heartland_road", {
        "discovered": True, "here": False, "id": "the_join", "image": "",
        "name": "The Join", "points": [], "ring": 3,
        "roads": [{"danger_dc": 14, "hours": 1, "name": "The Heartland Road", "to": "heartland_road"}],
    }, ("heartland_road", {"danger_dc": 14, "hours": 1, "name": "The Join", "to": "the_join"})),
)


def with_the_banded_map(value: Any) -> None:
    """
    S18 (v0.25.0 T5, §3.4, §5.3): the flagship's map answers carry its banded roads
    and, with no session only, its two secret places. In both map routes each of the
    22 roads recorded at ``danger_dc: 0`` carries its band's number (asserted 0
    before). With no session (no player, so every place known) the works and the
    Join appear, on the procedural tile (``image`` ""), each with its one road, and
    the road to each is added to its neighbour. With a session neither is known, so
    nothing of them appears. Nothing else moves.
    """
    for route in S18_ROUTES:
        places = value[route]["json"]["places"]
        assert not {"the_works", "the_join"} & {p["id"] for p in places}, "S18 applied twice"
        rebanded = 0
        for place in places:
            for road in place["roads"]:
                leg = f"{place['id']}>{road['to']}"
                if leg in S18_BANDED:
                    assert road["danger_dc"] == 0, leg
                    road["danger_dc"] = S18_BANDED[leg]
                    rebanded += 1
        assert rebanded == len(S18_BANDED), (route, rebanded)
    places = value[S18_ROUTES[0]]["json"]["places"]
    for after, place, (neighbour, road) in S18_PLACES:
        index = next(i for i, p in enumerate(places) if p["id"] == after)
        places.insert(index + 1, copy.deepcopy(place))
        next(p for p in places if p["id"] == neighbour)["roads"].append(dict(road))


MAP_SANCTION: tuple[str, Callable[[str], str]] = (S18_FIXTURE, json_sanction(with_the_banded_map))


#: S19's gallery rows (v0.25.0 T6, §4.2): per ending, the recorded ``gate`` and
#: ``lock_reason`` and what each reads since, and the ``tease`` each gains. A row
#: absent from ``S19_GATES`` keeps its gate and lock reason. Every recorded run
#: stands on day 1 with nothing earned, so each row's lock reason is the same in
#: every fixture.
S19_GATES: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "the_hearth_holds": (
        ("any: [{'quest_completed': 'bakery_apprentice'}, {'quest_completed': 'winter_stores'}, "
         "{'quest_completed': 'neighbours_ro and flag: nf_hearth_book_closed",
         "any: [{'quest_completed': 'bakery_apprentice'}, {'quest_completed': 'winter_stores'}, "
         "{'quest_completed': 'neighbours_ro and flag: nf_hearth_taking_stock"),
        ("Nobody in Edgewood would miss you yet, and that is the whole of what this ending is made of. "
         "You have not said you are staying. Not out loud, not to yourself.",
         "Nobody in Edgewood would miss you yet, and that is the whole of what this ending is made of. "
         "You have not walked your life here end to end and seen what it adds up to."),
    ),
    "the_long_witness": (
        ("min_awareness: 30 and any: [{'quest_completed': 'childs_drawing'}, {'quest_completed': 'not_right'}, "
         "{'quest_completed': 'rumour_made_true'},  and any: [{'flag': 'nf_hearth_book_closed'}, "
         "{'quest_completed': 'the_last_quiet_thing'}]",
         "min_awareness: 30 and any: [{'quest_completed': 'childs_drawing'}, {'quest_completed': 'not_right'}, "
         "{'quest_completed': 'rumour_made_true'},  and reputation: {'faction': 'unnamed_saints', 'min': 30} "
         "and min_day: 27"),
        ("You have not seen anything you could not explain to yourself by breakfast. The wrong things have "
         "been in front of you for weeks. You have not once looked twice. Knowing is not this. Staying with "
         "what you know is this, and you have not chosen it.",
         "You have not seen anything you could not explain to yourself by breakfast. The wrong things have "
         "been in front of you for weeks. You have not once looked twice. The shrine's women have not counted "
         "you among the ones who keep the count. Three counts of nine days have not yet passed with you here "
         "to see them."),
    ),
    "the_counted_march": (
        ("arc_unlocked: march and reputation: {'faction': 'militia', 'min': 20} and any: "
         "[{'quest_completed': 'militia_press'}, {'quest_completed': 'conscription_list'}, "
         "{'quest_completed': 'toll_roads'}, and flag: nf_hearth_book_closed",
         "arc_unlocked: march and reputation: {'faction': 'militia', 'min': 20} and any: "
         "[{'quest_completed': 'militia_press'}, {'quest_completed': 'conscription_list'}, "
         "{'quest_completed': 'toll_roads'},"),
        ("The road inward has soldiers on it, and you have not once stood where they could count you. Sera's "
         "ledger has your name in the column for strangers. Strangers are not mustered out; they are moved on. "
         "You have watched the arithmetic being done with people. Watching is not a discharge. The sergeant "
         "cannot strike a name that has not said it is done.",
         "The road inward has soldiers on it, and you have not once stood where they could count you. Sera's "
         "ledger has your name in the column for strangers. Strangers are not mustered out; they are moved on. "
         "You have watched the arithmetic being done with people, and never once stood your night on the wall "
         "or seen a levy through."),
    ),
    "the_named_wound": (
        ("quest_completed: naming_the_wound and quest_completed: what_edgewood_keeps",
         "quest_completed: naming_the_wound and quest_completed: what_edgewood_keeps and any: "
         "[{'quest_completed': 'the_last_quiet_thing'}, {'quest_state': {'quest': 'the_last_quiet_thing', "
         "'stage_at_least': 2"),
        ("It is still eleven separate wrong things to you. It has a shape, and you have not paid what looking "
         "at it costs. Edgewood does not know what you know, and what it does not know it cannot choose about.",
         "It is still eleven separate wrong things to you. It has a shape, and you have not paid what looking "
         "at it costs. Edgewood does not know what you know, and what it does not know it cannot choose about. "
         "You have not stood at the oven for the last quiet morning."),
    ),
    "the_price_asked": (
        ("quest_completed: the_sacrifice and flag: nf_sacrifice_paid",
         "quest_completed: naming_the_wound and flag: nf_sacrifice_chosen and flag: nf_sacrifice_paid"),
        ("Sympathy takes a like for a like, and you have not put anything on the table. It is still in your "
         "hands. Everything is negotiable until your hand comes off it.",
         "It has no name yet, and sympathy cannot price what has no name. Sympathy takes a like for a like, "
         "and you have not put anything on the table. It is still in your hands. Everything is negotiable "
         "until your hand comes off it."),
    ),
    "the_pin_and_the_join": (
        ("flag: nf_ninth_taken and has_item: {'id': 'ninth_pin', 'qty': 1} and quest_completed: "
         "the_heartland_road",
         "flag: nf_ninth_taken and has_item: {'id': 'ninth_pin', 'qty': 1} and any: "
         "[{'quest_completed': 'the_heartland_road'}, {'quest_state': {'quest': 'the_heartland_road', "
         "'stage_at_least': 2}}]"),
        ("The ninth pin is still on Ilya's felt, and he has never once said it is not for sale. You had it, "
         "and you spent it, or you left it somewhere a pin like that should never be left. You do not know "
         "where it goes. It goes where the two ends of the road were made to meet.",
         "The ninth pin is still on Ilya's felt, and he has never once said it is not for sale. You had it, "
         "and you spent it, or you left it somewhere a pin like that should never be left. You do not know "
         "where it goes. It goes where the two ends of the road were made to meet."),
    ),
}
#: Every ending's tease, as data/rules/endings.yaml writes it (all eight gain one).
S19_TEASES: dict[str, str] = {
    "the_hearth_holds": "Maris at the oven before dawn, and a question she has stopped needing to ask.",
    "the_long_witness": "Old Wenna at the shrine with her two candles, and room on her list for yours.",
    "the_counted_march": "Sergeant Venn's roll at the gate, and one name on it she can strike.",
    "the_named_wound": "The bakery at the morning firing, after the village has had its say.",
    "the_price_asked": "Ilya's book of prices, and the column he keeps for what is not coin.",
    "the_pin_and_the_join": "Ilya's felt, and the road past Millhaven gate that keeps getting shorter.",
    "the_stopped_wheel": "The square, on a morning when no bell in Edgewood rings the hour.",
    "the_dark_keeps_its_hours": "Edgewood's hours, kept whether or not you keep them.",
}
#: S19's payload fixtures and how many gallery blocks each carries.
S19_GALLERIES: dict[str, int] = {
    "clockwork-dark/http_turns.json": 2, "clockwork-dark/join_live.json": 2,
    "clockwork-dark/new_game.json": 2, "clockwork-dark/save_load.json": 1,
    "clockwork-dark/socket_resume.json": 2, "clockwork-dark/socket_stream_turn.json": 3,
    "clockwork-dark/socket_turns.json": 2, "clockwork-dark/state.json": 1,
}
#: S19's catalogue fixtures: each carries one flagship row, which gains `paths.decks`.
S19_CATALOGUES = ("games.json", "games_active.json", "games_clockwork-dark.json")
S19_DECKS = "games/clockwork-dark/data/scenes"


def named_doors_gallery(rows: list[dict[str, Any]]) -> None:
    """
    S19's change to one gallery block (v0.25.0 T6, §4.2): the six gates T6 rewrote
    read their new clauses and lock reasons, and every ending gains its tease.
    Shared with tests/test_social_seam.py, whose flagship payload carries the same
    block. Nothing else in a row moves.
    """
    assert [r["id"] for r in rows] == list(S19_TEASES), [r["id"] for r in rows]
    for row in rows:
        assert "tease" not in row, "S19 applied twice"
        if row["id"] in S19_GATES:
            (gate_was, gate_now), (reason_was, reason_now) = S19_GATES[row["id"]]
            assert (row["gate"], row["lock_reason"]) == (gate_was, reason_was), row["id"]
            row["gate"], row["lock_reason"] = gate_now, reason_now
        row["tease"] = S19_TEASES[row["id"]]


def _galleries(value: Any) -> list[list[dict[str, Any]]]:
    """Every flagship gallery block in a fixture, in document order."""
    found: list[list[dict[str, Any]]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "gallery" and isinstance(item, list) and any(
                    isinstance(r, dict) and r.get("id") == "the_hearth_holds" for r in item):
                found.append(item)
            else:
                found.extend(_galleries(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_galleries(item))
    return found


def with_named_doors(expected: int) -> Callable[[str], str]:
    """S19 on a payload fixture: exactly ``expected`` gallery blocks, each by ``named_doors_gallery``."""

    def transform(value: Any) -> None:
        blocks = _galleries(value)
        assert len(blocks) == expected, (len(blocks), expected)
        for rows in blocks:
            named_doors_gallery(rows)

    return json_sanction(transform)


def with_flagship_decks(value: Any) -> None:
    """S19 on a catalogue fixture: the flagship's row (and only it) gains `paths.decks`."""
    body = value["json"]
    rows = body["games"] if "games" in body else [body["manifest"]] if "manifest" in body else [body]
    flagship = [row for row in rows if row.get("id") == "clockwork-dark"]
    assert len(flagship) == 1, len(flagship)
    paths = flagship[0]["paths"]
    assert "decks" not in paths, "S19 applied twice"
    paths["decks"] = S19_DECKS


DOORS_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    *((name, with_named_doors(count)) for name, count in S19_GALLERIES.items()),
    *((name, json_sanction(with_flagship_decks)) for name in S19_CATALOGUES),
]


#: S20's payload fixtures and how many flagship state blocks each carries (v0.25.0 T8,
#: §5.1): the same fixtures, and the same counts, as S19's galleries, because each
#: flagship payload carries one state block beside each gallery.
S20_STATES: dict[str, int] = {
    "clockwork-dark/http_turns.json": 2, "clockwork-dark/join_live.json": 2,
    "clockwork-dark/new_game.json": 2, "clockwork-dark/save_load.json": 1,
    "clockwork-dark/socket_resume.json": 2, "clockwork-dark/socket_stream_turn.json": 3,
    "clockwork-dark/socket_turns.json": 2, "clockwork-dark/state.json": 1,
}
#: S20's catalogue rows: the flagship's row gains these two paths.
S20_PATHS: dict[str, str] = {
    "clocks": "games/clockwork-dark/data/rules/clocks.yaml",
    "threads": "games/clockwork-dark/data/rules/threads.yaml",
}


def _states(value: Any) -> list[dict[str, Any]]:
    """Every state block in a fixture (a dict carrying ``turn_number`` and ``stats``), in document order."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "turn_number" in value and "stats" in value:
            found.append(value)
        for item in value.values():
            found.extend(_states(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_states(item))
    return found


def levy_and_bargain_state(state: dict[str, Any]) -> None:
    """
    S20's change to one flagship state block (v0.25.0 T8, §5.1): it gains
    ``threads: []``. The flagship declares `paths.threads` (Sergeant Venn's bargain),
    and a state that declares threads carries their summary
    (engine/game/state.py, `threads_module.is_declared()`): empty, because no recorded
    run strikes one. The levy clock is `visibility: hidden`, so no payload shows it.
    Shared with tests/test_social_seam.py. Nothing else in the block moves.
    """
    assert "threads" not in state, "S20 applied twice"
    state["threads"] = []


def with_levy_and_bargain(expected: int) -> Callable[[str], str]:
    """S20 on a payload fixture: exactly ``expected`` state blocks, each by ``levy_and_bargain_state``."""

    def transform(value: Any) -> None:
        blocks = _states(value)
        assert len(blocks) == expected, (len(blocks), expected)
        for block in blocks:
            levy_and_bargain_state(block)

    return json_sanction(transform)


def with_flagship_clocks_and_threads(value: Any) -> None:
    """S20 on a catalogue fixture: the flagship's row (and only it) gains `paths.clocks` and `paths.threads`."""
    body = value["json"]
    rows = body["games"] if "games" in body else [body["manifest"]] if "manifest" in body else [body]
    flagship = [row for row in rows if row.get("id") == "clockwork-dark"]
    assert len(flagship) == 1, len(flagship)
    paths = flagship[0]["paths"]
    assert not set(S20_PATHS) & set(paths), "S20 applied twice"
    paths.update(S20_PATHS)


LEVY_SANCTION: list[tuple[str, Callable[[str], str]]] = [
    *((name, with_levy_and_bargain(count)) for name, count in S20_STATES.items()),
    *((name, json_sanction(with_flagship_clocks_and_threads)) for name in S19_CATALOGUES),
]


#: ``(fixture name, transform)``: the recording, as the sanctioned change
#: makes it. S1 since v0.20.0 T2, S2 since T3, S3-S10 since v0.21.0
#: (spec §1.2; S7 added in T3 fix round 1, S8 in fix round 2, S9 in the
#: encounter-resume fix, S10 in T13 fix round 1, S5 in T14), S11 since
#: v0.22.0 T2, S13 since v0.24.0 T4, S12 since T10, S14 since v0.25.0 T2, S15 since
#: v0.25.0 T3, S16 and S17 since v0.25.0 T4, S18 since v0.25.0 T5, S19 since v0.25.0 T6,
#: S20 since v0.25.0 T8; there are no others.
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
    RECEIPTS_SANCTION,
    SOUND_RULES_SANCTION,
    *SOUNDS_SANCTION,
    OVERLAY_SANCTION,
    FACTIONS_SANCTION,
    *DECLARED_SOULS_SANCTION,
    NESSA_SANCTION,
    MAP_SANCTION,
    *DOORS_SANCTION,
    *LEVY_SANCTION,
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


@pytest.mark.process
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

    name, transform = OVERLAY_SANCTION
    before, after = json.loads(recorded[name]), json.loads(transform(recorded[name]))
    added = [row for row in after["url_map"] if row not in before["url_map"]]
    assert added == [["/api/intents/overlay", ["GET", "HEAD", "OPTIONS"], "default_story.api_overlay_intents"]]
    assert sorted(set(after["socketio_handlers"]["/"]) - set(before["socketio_handlers"]["/"])) == ["overlay_action"]

    name, transform = FACTIONS_SANCTION
    before, after = json.loads(recorded[name]), json.loads(transform(recorded[name]))
    added = [row for row in after["url_map"] if row not in before["url_map"]]
    assert added == [["/api/factions", ["GET", "HEAD", "OPTIONS"], "default_story.api_factions"]]
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


def test_the_receipts_sanction_is_exact() -> None:
    """
    S11 adds one row to ``games.json`` -- READ RECEIPTS's, between NEON CITY
    and The Clockwork Dark, where ``catalog_key`` puts it -- and moves no other
    row or key; applied twice it raises; and its row is the live catalogue's.
    """
    from engine.games import registry

    name, transform = RECEIPTS_SANCTION
    before = json.loads(_recorded()[name])
    after = json.loads(transform(_recorded()[name]))
    slugs = [row["slug"] for row in after["json"]["games"]]
    assert slugs == ["dev-story", "hue-and-cry", "neon-city", "read-receipts",
                     "clockwork-dark", "the-long-con", "wicked-garden"], slugs
    rows = [row for row in after["json"]["games"] if row["slug"] != "read-receipts"]
    after["json"]["games"] = rows
    assert after == before
    with pytest.raises(AssertionError, match="S11 applied twice"):
        transform(transform(_recorded()[name]))
    live = next(row for row in registry.catalog() if row["slug"] == "read-receipts")
    assert {k: v for k, v in live.items() if k != "active"} == {
        k: v for k, v in READ_RECEIPTS_ROW.items() if k != "active"
    }


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


def test_the_sound_rules_sanction_is_exact() -> None:
    """S13 adds exactly the three sound rules to app_shape.json's url_map, and nothing else in the file moves."""
    before = _recorded()["app_shape.json"]
    after = SOUND_RULES_SANCTION[1](before)
    assert after != before
    changed = [l for l in difflib.ndiff(before.splitlines(), after.splitlines()) if l.startswith(("- ", "+ "))]
    assert changed and all(l.startswith("+ ") for l in changed), changed
    old, new = json.loads(before), json.loads(after)
    assert {k: v for k, v in new.items() if k != "url_map"} == {k: v for k, v in old.items() if k != "url_map"}
    added = [r for r in new["url_map"] if r not in old["url_map"]]
    assert sorted(map(json.dumps, added)) == sorted(map(json.dumps, SOUND_RULES))
    with pytest.raises(AssertionError, match="S13 applied twice"):
        SOUND_RULES_SANCTION[1](after)


def test_the_sounds_sanction_is_exact() -> None:
    """S12 changes each of its four fixtures by `"sounds": "games/<slug>/data/sounds"` lines only, one per
    declaring row (5/1/1/1), and dev-story's row never gains one (pre-flight F8, gap 3)."""
    counts = {"games.json": 5, "games_active.json": 1, "games_clockwork-dark.json": 1, "games_hue-and-cry.json": 1}
    allowed = {f'"sounds": "{path}"' for path in EXPECTED_SOUNDS_ROWS.values()}
    recorded = _recorded()
    for name, transform in SOUNDS_SANCTION:
        before = recorded[name]
        after = transform(before)
        assert after != before, name
        changed = [l for l in difflib.ndiff(before.splitlines(), after.splitlines()) if l.startswith(("- ", "+ "))]
        assert changed and all(l.startswith("+ ") for l in changed), (name, changed)
        assert all(l[2:].strip().rstrip(",") in allowed for l in changed), (name, changed)
        assert len(changed) == counts[name], (name, len(changed))
        assert "games/dev-story/data/sounds" not in after, name


def test_the_declared_cast_sanctions_are_exact() -> None:
    """
    S16 adds exactly the counted declared souls to each souls answer of its two fixtures,
    with their ids, and nothing else in either moves; S17 adds exactly Nessa's relation to
    the two memory files of the flagship's save tree, and nothing else moves.
    """
    recorded = _recorded()
    for name, transform in DECLARED_SOULS_SANCTION:
        before, after = json.loads(recorded[name]), json.loads(transform(recorded[name]))
        rows = S16_DECLARED[name]
        for route in SOULS_ROUTES:
            old, new = before[route]["json"]["souls"], after[route]["json"]["souls"]
            assert new[: len(old)] == old, (name, route)
            added = new[len(old):]
            assert len(added) == len(rows), (name, route, len(added))
            assert [soul["id"] for soul in added] == [f"s{i}" for i in range(len(old), len(old) + len(rows))]
            assert [(soul["role"], soul["place"]) for soul in added] == rows
            assert all(soul["met"] is False and soul["name"] == "Someone" for soul in added)
            after[route]["json"]["souls"] = old
        assert after == before, name
    before = json.loads(recorded[S17_FIXTURE])
    after = json.loads(NESSA_SANCTION[1](recorded[S17_FIXTURE]))
    for name in S17_MEMORIES:
        assert set(after[name]["relations"]) - set(before[name]["relations"]) == {"npc_nessa"}, name
        del after[name]["relations"]["npc_nessa"]
    assert after == before
    with pytest.raises(AssertionError, match="S17 applied twice"):
        NESSA_SANCTION[1](NESSA_SANCTION[1](recorded[S17_FIXTURE]))


def test_the_map_sanction_is_exact() -> None:
    """
    S18 rebands exactly the 22 counted roads in each map answer of the flagship's
    story routes and adds exactly the two secret places (and the road to each) to the
    no-session answer; nothing else in the fixture moves, and it cannot apply twice.
    """
    recorded = _recorded()
    before = json.loads(recorded[S18_FIXTURE])
    after = json.loads(MAP_SANCTION[1](recorded[S18_FIXTURE]))
    secret = {"the_works", "the_join"}
    for route in S18_ROUTES:
        new = after[route]["json"]["places"]
        added = [p["id"] for p in new if p["id"] in secret]
        assert added == (["the_works", "the_join"] if route == S18_ROUTES[0] else []), route
        new = [p for p in new if p["id"] not in secret]
        for place in new:
            place["roads"] = [r for r in place["roads"] if r["to"] not in secret]
            for road in place["roads"]:
                if f"{place['id']}>{road['to']}" in S18_BANDED:
                    road["danger_dc"] = 0
        after[route]["json"]["places"] = new
    assert after == before
    with pytest.raises(AssertionError, match="S18 applied twice"):
        MAP_SANCTION[1](MAP_SANCTION[1](recorded[S18_FIXTURE]))


def test_the_doors_sanction_is_exact() -> None:
    """
    S19 changes, in each flagship payload fixture, exactly its gallery blocks'
    six rewritten gates and lock reasons and the eight teases, and in each catalogue
    fixture exactly the flagship row's `paths.decks`; undone, every fixture is the
    recording again, and it cannot apply twice.
    """
    recorded = _recorded()
    for name, sanction in DOORS_SANCTION:
        before = json.loads(recorded[name])
        after = json.loads(sanction(recorded[name]))
        assert after != before, name
        if name in S19_GALLERIES:
            blocks = _galleries(after)
            assert len(blocks) == S19_GALLERIES[name], name
            for rows in blocks:
                for row in rows:
                    assert row.pop("tease") == S19_TEASES[row["id"]]
                    if row["id"] in S19_GATES:
                        (gate_was, gate_now), (reason_was, reason_now) = S19_GATES[row["id"]]
                        assert (row["gate"], row["lock_reason"]) == (gate_now, reason_now)
                        row["gate"], row["lock_reason"] = gate_was, reason_was
        else:
            body = after["json"]
            rows = body["games"] if "games" in body else [body["manifest"]] if "manifest" in body else [body]
            assert next(r for r in rows if r.get("id") == "clockwork-dark")["paths"].pop("decks") == S19_DECKS
        assert after == before, name
        with pytest.raises(AssertionError, match="S19 applied twice"):
            sanction(sanction(recorded[name]))


def test_the_levy_sanction_is_exact() -> None:
    """
    S20 adds, in each flagship payload fixture, exactly an empty `threads` list to
    each state block, and in each catalogue fixture exactly the flagship row's
    `paths.clocks` and `paths.threads`; undone, every fixture is the recording again,
    and it cannot apply twice.
    """
    recorded = _recorded()
    for name, sanction in LEVY_SANCTION:
        before = json.loads(recorded[name])
        after = json.loads(sanction(recorded[name]))
        assert after != before, name
        if name in S20_STATES:
            blocks = _states(after)
            assert len(blocks) == S20_STATES[name], name
            for block in blocks:
                assert block.pop("threads") == []
        else:
            body = after["json"]
            rows = body["games"] if "games" in body else [body["manifest"]] if "manifest" in body else [body]
            paths = next(r for r in rows if r.get("id") == "clockwork-dark")["paths"]
            assert {key: paths.pop(key) for key in S20_PATHS} == S20_PATHS
        assert after == before, name
        with pytest.raises(AssertionError, match="S20 applied twice"):
            sanction(sanction(recorded[name]))

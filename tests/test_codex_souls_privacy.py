"""
The codex never identifies a person the player has not met (v0.21.0 T3 fix
round 1; the review's finding 9, Risk 6's class).

WHAT LEAKED. ``GET /api/codex/souls`` sent every soul's NPC id, met or not --
the flagship's ids are names (``npc_maris``) and HUE & CRY's generated ids
lay out each household (``gen_chandlers_rise_1_chandler``) -- and its role
unmasked. With no session it called every canon NPC met, so a menu (or, in
hosted mode, any account with no run) got the cast by name and portrait.
``codex_things``' ``from`` named every vendor from its id ("Maris").

NOW. An unmet soul's ``id`` is an opaque per-response key (``s0``...), as
``people_here``'s ``key`` is; with no session nobody is met; the role passes
the awareness spoiler gate; an unmet vendor is "the <role>".

FIX ROUND 2 (re-review R2): the same rule, through one helper
(``default_api.known_as``), for the three sibling routes that still named
every vendor -- the map's vendor points, the pack's ``vendor`` and the
barter screen (whose stranger gets an opaque ``v<index>`` ``npc_id``).
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any

import pytest

import engine.scenes.default_api as default_api
from engine.game.state import GameState
from tests.test_activity_names_nobody import identifying_tokens, names_in

CAST = [
    {"id": "npc_maris", "name": "Maris Hearth", "role": "baker", "location_id": "", "traits": ["warm"]},
    {"id": "npc_odran", "name": "Odran Cartwright", "role": "caravan_master", "location_id": "", "traits": ["weathered"]},
]


def _state() -> GameState:
    state = GameState(rng_seed=3)
    state.procgen.npcs = [dict(npc) for npc in CAST]
    return state


def _ledger(*met: str) -> Any:
    return SimpleNamespace(relations={npc_id: SimpleNamespace(met=True) for npc_id in met})


def _names_anyone(text: str) -> list[str]:
    return [token for npc in CAST for token in names_in(text, identifying_tokens(npc["id"], npc["name"], npc["role"]))]


@pytest.fixture(autouse=True)
def _quiet_art(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(default_api, "shipped_art_url", lambda subject, kind="enemy", *a, **k: f"/art/{kind}/{subject}.jpg")


def test_an_unmet_soul_carries_no_id_or_name() -> None:
    souls = default_api.codex_souls(_state(), _ledger("npc_odran"))["souls"]
    unmet, met = souls
    assert unmet["met"] is False and unmet["id"] == "s0"
    assert not _names_anyone(json.dumps(unmet)), unmet
    assert met["met"] is True and met["id"] == "npc_odran" and met["name"] == "Odran Cartwright"


def test_with_no_session_nobody_is_met(monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.game.procgen as procgen

    monkeypatch.setattr(procgen, "load_templates", lambda *a, **k: {"canon_npcs": [dict(n, canon=True) for n in CAST]})
    souls = default_api.codex_souls(None, None)["souls"]
    assert [soul["met"] for soul in souls] == [False, False]
    assert [soul["id"] for soul in souls] == ["s0", "s1"]
    assert [soul["role"] for soul in souls] == ["baker", "caravan master"]
    assert not _names_anyone(json.dumps(souls)), souls


def test_a_souls_role_passes_the_spoiler_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.lore.interceptors as interceptors

    monkeypatch.setattr(
        interceptors, "spoiler_terms",
        lambda state=None: [(re.compile(r"caravan", re.IGNORECASE), "travelling")],
    )
    state = _state()
    state.awareness = 0.0
    roles = [soul["role"] for soul in default_api.codex_souls(state, _ledger("npc_odran"))["souls"]]
    assert roles == ["baker", "travelling master"]


def test_an_unmet_vendor_is_named_by_role(monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.media.providers.shipped as shipped

    monkeypatch.setattr(
        default_api, "_load_economy",
        lambda: {
            "npc_maris": {"sells": {"bread": {"name": "Bread", "price": 2}}},
            "npc_odran": {"sells": {"rope": {"name": "Rope", "price": 5}}},
        },
    )
    monkeypatch.setattr(shipped, "load_manifest", lambda *a, **k: {"items": {"bread": "b.jpg", "rope": "r.jpg"}})
    things = {t["id"]: t for t in default_api.codex_things(_state(), _ledger("npc_odran"))}
    assert things["bread"]["from"] == "the baker"
    assert things["rope"]["from"] == "Odran Cartwright"
    assert not _names_anyone(json.dumps(things["bread"])), things["bread"]


# -- the sibling routes (fix round 2, R2): one rule, `known_as` ---------------


def test_a_map_vendor_point_names_only_a_met_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.game.locations as locations
    import engine.game.trade as trade

    monkeypatch.setattr(locations, "LOCATIONS", {"bakery": {"name": "Bakery"}, "square": {"name": "Square"}})
    stalls = {"bakery": ["npc_maris"], "square": ["npc_odran"]}
    monkeypatch.setattr(trade, "vendors_at", lambda place_id, **_k: stalls.get(place_id, []))
    monkeypatch.setattr(
        trade, "browse",
        lambda state, npc_id: {"ok": True, "vendor": {"npc_maris": "Maris Hearth", "npc_odran": "Odran Cartwright"}[npc_id]},
    )
    points = default_api.map_points(_state(), _ledger("npc_odran"))
    vendor = {place: [p["label"] for p in rows if p["kind"] == "vendor"] for place, rows in points.items()}
    assert vendor["bakery"] == ["the baker"]
    assert vendor["square"] == ["Odran Cartwright"]
    assert not _names_anyone(json.dumps(vendor["bakery"]))


def test_the_packs_vendor_names_only_a_met_vendor(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    economy = tmp_path / "economy.yaml"
    economy.write_text(
        "npc_maris:\n  sells:\n    bread: {name: Bread, price: 2}\n"
        "npc_odran:\n  sells:\n    rope: {name: Rope, price: 5}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(default_api, "_story_dir", lambda key: economy if key == "paths.economy" else None)
    monkeypatch.setattr(default_api, "_load_item_registry", lambda: {"bread": {"name": "Bread"}, "rope": {"name": "Rope"}})
    items = {row["id"]: row for row in default_api.item_catalog(_state(), _ledger("npc_odran"))["items"]}
    assert items["bread"]["vendor"] == "the baker"
    assert items["rope"]["vendor"] == "Odran Cartwright"
    assert not _names_anyone(json.dumps(items["bread"]))
    # No session: nobody is met.
    menu = {row["id"]: row for row in default_api.item_catalog(None, None)["items"]}
    assert not _names_anyone(json.dumps(menu)), menu


def test_the_barter_screen_names_only_a_met_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Standing at a counter is not meeting: the ledger meets the people present
    only at the END of a turn, so the vendor at the place a run opens on is a
    stranger until the first turn (the recorded flagship's Odran).
    """
    monkeypatch.setattr(
        default_api, "_load_economy",
        lambda: {"npc_maris": {"sells": {"bread": {"name": "Bread", "price": 2}}},
                 "npc_odran": {"sells": {"rope": {"name": "Rope", "price": 5}}}},
    )
    state = _state()
    state.location_id = "square"
    for npc in state.procgen.npcs:
        npc["location_id"] = "square"
    stranger, known = default_api.trade_offer(state, _ledger("npc_odran"))["vendors"]
    assert (stranger["npc_id"], stranger["name"], stranger["known"]) == ("v0", "the baker", False)
    assert not _names_anyone(json.dumps(stranger)), stranger
    assert (known["npc_id"], known["name"], known["known"]) == ("npc_odran", "Odran Cartwright", True)


def test_the_route_answers_with_no_session_naming_nobody() -> None:
    from engine.scenes.default_scene import create_app, reset_store

    reset_store()
    try:
        _scene, app = create_app(testing=True, llm_fn=lambda _m: "{}")
        body = app.test_client().get("/api/codex/souls").get_json()
        assert all(soul["met"] is False and soul["name"] == "Someone" for soul in body["souls"])
        assert all(re.fullmatch(r"s\d+", soul["id"]) for soul in body["souls"])
        assert all(soul["portrait"] == "" for soul in body["souls"])
    finally:
        reset_store()

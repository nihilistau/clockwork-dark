"""
The overlay intent path (v0.25.0 E2, spec §6.2, §7.1-§7.2; rule 1).

An overlay hands the server `{action, target}`. The server checks it against
an UNCAPPED legality list for a closed set of verbs (`overlay_targets`), under
the turn lock, runs the turn with it -- and refuses in words otherwise: before
the turn (`turn_error`, nothing ran) for a pair not on offer, in the PROSE for
a scene that owns the turn. The narrator's capped catalogue does not move.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import pytest

from engine.games import registry
from tests import flagship_overhaul_recorder as rec

PROMPTS: list[str] = []


@pytest.fixture
def flagship() -> Iterator[None]:
    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


def _state(seed: int = 7) -> Any:
    from engine.game.procgen import new_game_state

    return new_game_state(seed=seed)


def _at(state: Any, place: str, hour: int) -> None:
    """Stand somewhere at an hour (the clock moved by its one writer)."""
    from engine.game.clock import advance_time, hours_until

    state.location_id = place
    if state.world_hour != hour:
        advance_time(state, hours_until(state, hour))


def _grant(state: Any, item_id: str, qty: int = 1) -> None:
    """Through ``inventory.grant`` (the ``item`` effect, name and tags from the registry), so a
    thing edible by its tags alone is carried as food, as every real grant carries it."""
    from engine.game import inventory

    inventory.grant(state, item_id, qty)


def _run(state: Any, intent: dict, *, overlay: bool) -> dict:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine, active_engine

    engine = GameEngine(state)
    with active_engine(engine):
        (receipt,) = execute_intent(intent, engine, overlay=overlay)
    return receipt


def _edible(n: int) -> list[str]:
    from engine.game import inventory

    return sorted(i for i in inventory.load_items() if inventory.is_edible(i))[:n]


def test_the_capped_catalogue_is_the_first_eight_uncapped_rows(flagship) -> None:
    from engine.game import intents

    state = _state()
    for item_id in _edible(10):
        _grant(state, item_id)
    rows = intents.overlay_targets(state)["eat"]
    assert len(rows) >= 10
    verb = intents.find_verb(intents.legal_intents(state), "eat")
    assert verb is not None and list(verb.options) == rows[:8]


def test_a_ninth_sellable_thing_is_legal_from_the_overlay_with_its_own_label(flagship, monkeypatch) -> None:
    from engine.game import intents, trade

    state = _state()
    _at(state, "edgewood_bakery", 9)
    monkeypatch.setattr(trade, "deals_in", lambda npc_id, item_id: True)
    monkeypatch.setattr(trade, "refusal_to_buy", lambda st, npc_id: "")
    monkeypatch.setattr(trade, "quote", lambda *a, **k: {"unit_price": 1, "unit_kind": "clean"})
    for item_id in _edible(10):
        _grant(state, item_id)
    rows = intents.overlay_targets(state)["sell"]
    verb = intents.find_verb(intents.legal_intents(state), "sell")
    assert verb is not None and len(verb.targets) == 8 and len(rows) >= 10
    assert list(verb.options) == rows[:8]
    ninth, label = rows[8]
    intent = {"action": "sell", "target": ninth}
    assert intents.describe_intent(state, intent) == ""
    assert intents.describe_overlay_intent(state, intent) == f"Sell: {label}"
    assert _run(state, intent, overlay=True)["skill"] == "trade_sell"
    assert _run(state, intent, overlay=False)["skill"] == "sell"          # a legality refusal


def _ten_rows(monkeypatch, state: Any, action: str) -> None:
    """Give ``buy``, ``work`` or ``craft`` ten legal rows here, past the narrator's eight: the
    flagship offers fewer than nine of each at any one place, so the source each row function
    reads is widened to ten (the rows themselves are still built by ``intents``)."""
    from engine.game import economy, trade
    from engine.skills.builtin import mechanics

    if action == "buy":
        monkeypatch.setattr(trade, "vendors_at", lambda *a, **k: ["npc_maris"])
        monkeypatch.setattr(trade, "browse", lambda st, npc_id: {
            "ok": True, "vendor": "Maris",
            "sells": [{"item_id": f"thing_{n:02d}", "name": f"Thing {n}", "price": 1, "affordable": True}
                      for n in range(10)]})
    elif action == "work":
        monkeypatch.setattr(economy, "available", lambda *a, **k: [
            {"id": f"shift_{n:02d}", "name": f"Shift {n}"} for n in range(10)])
    else:
        monkeypatch.setattr(mechanics, "craftable_here", lambda st: [
            (f"recipe_{n:02d}", f"Recipe {n}") for n in range(10)])


@pytest.mark.parametrize("action", ["buy", "work", "craft"])
def test_the_narrators_eight_are_the_first_eight_overlay_rows(flagship, monkeypatch, action: str) -> None:
    from engine.game import intents

    state = _state()
    _ten_rows(monkeypatch, state, action)
    rows = intents.overlay_targets(state)[action]
    verb = intents.find_verb(intents.legal_intents(state), action)
    assert len(rows) == 10
    assert verb is not None and list(verb.options) == rows[:8]
    ninth, label = rows[8]
    intent = {"action": action, "target": ninth}
    assert intents.describe_intent(state, intent) == ""
    assert intents.describe_overlay_intent(state, intent) == f"{intents.OVERLAY_WORDS[action]}: {label}"


def _first(items: dict, key: str, state: Any) -> str:
    from engine.game import inventory

    for item_id, row in sorted(items.items()):
        if isinstance(row.get(key), dict) and (key != "equip" or inventory.equip_spec(item_id)):
            _grant(state, item_id)
            if key != "use" or not inventory.use_refusal(state, item_id):
                return item_id
    raise AssertionError(f"no flagship item with a usable {key}: block")


def test_use_equip_and_unequip_pass_only_with_the_overlay_mark(flagship) -> None:
    from engine.game import intents, inventory

    state = _state()
    items = inventory.load_items()
    wear = _first(items, "equip", state)
    use = _first(items, "use", state)
    refused = _run(state, {"action": "equip", "target": wear}, overlay=False)
    assert refused["refused"] and refused["skill"] == "equip"
    worn = _run(state, {"action": "equip", "target": wear}, overlay=True)
    assert worn["skill"] == "equip_item" and worn["success"]
    assert wear in [t for t, _ in intents.overlay_targets(state)["unequip"]]
    off = _run(state, {"action": "unequip", "target": wear}, overlay=True)
    assert off["skill"] == "unequip_item" and off["success"]
    used = _run(state, {"action": "use", "target": use}, overlay=True)
    assert used["skill"] == "use_item"


@pytest.mark.parametrize("slug", rec.SEVEN)
def test_no_storys_grammar_offers_an_overlay_only_verb(slug: str) -> None:
    from engine.game import intents, procgen

    with rec.active(slug):
        state = procgen.new_game_state(player_name="Ash", seed=rec.OPENING_SEED)
        actions = {v.action for v in intents.legal_intents(state)}
    assert not actions & intents.OVERLAY_ONLY_ACTIONS


def test_a_press_while_an_encounter_is_open_is_refused_and_the_encounter_is_untouched(flagship) -> None:
    import copy

    from engine.game import encounter, intents

    state = _state()
    _grant(state, _edible(1)[0])
    encounter.begin(state, "lost_child_at_the_treeline")
    before = copy.deepcopy(state.encounter)
    target = intents.overlay_targets(state)["eat"][0][0]
    receipt = _run(state, {"action": "eat", "target": target}, overlay=True)
    assert receipt["refused"] and receipt["result"]["error"] == intents.OVERLAY_SCENE_REFUSAL
    assert state.encounter == before


def test_a_press_while_a_card_is_dealt_is_refused_and_the_card_is_untouched() -> None:
    import copy

    from engine.content import director
    from engine.game import intents

    with rec.active("dev-story"):
        from engine.content import deck as deck_module

        state = _state()
        deck_id = deck_module.deck_ids()[0]
        assert director.begin(state, deck_id, forced_card=deck_module.load_deck(deck_id).cards[0].id)["ok"]
        before = copy.deepcopy(state.scene)
        receipt = _run(state, {"action": "eat", "target": "anything"}, overlay=True)
    assert receipt["refused"] and receipt["result"]["error"] == intents.OVERLAY_SCENE_REFUSAL
    assert state.scene == before


# -- through the doors ----------------------------------------------------------------------------


def _stub_llm():
    from engine.agents.prompts import storyteller_persona

    def fake(messages, **_):
        persona = storyteller_persona().strip().splitlines()[0]
        if not any(persona in str(m.get("content", "")) for m in messages):
            return "Nothing is said, at length."
        PROMPTS.append(json.dumps(messages))
        return json.dumps({"narration": rec.NARRATION, "choices": [{"id": "a", "text": "Go on"},
                                                                   {"id": "b", "text": "Look about"}]})

    return fake


@pytest.fixture
def game(flagship, monkeypatch):
    from engine.scenes import default_scene, default_state

    PROMPTS.clear()
    monkeypatch.setattr(default_state, "_background_tick", lambda state: 0.0)
    scene, app = default_scene.create_app(testing=True, llm_fn=_stub_llm())
    http = app.test_client()
    body = http.post("/api/game/new", json={"seed": 7}).get_json()
    session = scene.store.require(body["session_id"])
    return scene, app, http, session


def test_the_route_lists_every_verb_and_whether_a_scene_owns_the_turn(game) -> None:
    from engine.game import intents

    _scene, _app, http, session = game
    answer = http.get("/api/intents/overlay", query_string={"session_id": session.session_id}).get_json()
    assert answer["scene_owns_turn"] is False
    assert set(answer["actions"]) == set(intents.OVERLAY_ACTIONS)
    assert http.get("/api/intents/overlay", query_string={"session_id": "000000000000"}).status_code == 404


def test_a_failed_offer_read_is_not_a_scene_owning_the_turn(game, monkeypatch) -> None:
    """T14 (review c-m5): a failed read answers nothing pressable, never `scene_owns_turn: true`, so no
    overlay says "Answer what is in front of you first" with nothing in front of the player."""
    from engine.scenes import default_api

    _scene, _app, http, session = game

    def broken(_state):
        raise RuntimeError("a half-moved world")

    monkeypatch.setattr(default_api, "overlay_offer", broken)
    answer = http.get("/api/intents/overlay", query_string={"session_id": session.session_id})
    assert answer.status_code == 200
    assert answer.get_json() == {"scene_owns_turn": False, "actions": {}}


def test_an_unknown_action_is_refused_before_any_turn(game) -> None:
    scene, app, _http, session = game
    sio = scene.socketio.test_client(app)
    turn = session.engine.state.turn_number
    sio.get_received()
    sio.emit("overlay_action", {"session_id": session.session_id, "intent": {"action": "dance", "target": "x"}})
    (event,) = [e for e in sio.get_received() if e["name"] == "turn_error"]
    assert event["args"][0]["busy"] is False and event["args"][0]["stale_choice"] is True
    assert session.engine.state.turn_number == turn and not PROMPTS


def test_an_overlay_pair_stale_before_the_turn_is_refused_with_nothing_run(game) -> None:
    _scene, _app, http, session = game
    gold = session.engine.state.stats.gold
    answer = http.post("/api/game/choice", json={
        "session_id": session.session_id, "overlay_intent": {"action": "buy", "target": "npc_maris/no_such_loaf"}})
    assert answer.status_code == 409 and answer.get_json()["stale_choice"] is True
    assert session.engine.state.stats.gold == gold and not PROMPTS


def test_a_pair_listed_a_turn_ago_and_gone_now_is_refused_with_nothing_run(game) -> None:
    """Review Focus 2, exactly (T14 review, d4): a pair the overlay list held, pressed after the world
    moved under it (the coin spent elsewhere), is refused before any turn: 409, stale, nothing run."""
    from engine.game import intents, inventory
    from engine.game.effects import apply_effect

    _scene, _app, http, session = game
    state = session.engine.state
    _at(state, "edgewood_bakery", 9)
    listed = http.get("/api/intents/overlay", query_string={"session_id": session.session_id}).get_json()
    target = listed["actions"]["buy"][0]["target"]
    assert target in [t for t, _ in intents.overlay_targets(state)["buy"]]
    apply_effect(state, {"type": "gold", "delta": -state.stats.gold})     # the coin spent since
    assert target not in [t for t, _ in intents.overlay_targets(state)["buy"]]
    item_id = target.split("/", 1)[1]
    carried, turn = inventory.quantity(state, item_id), state.turn_number
    answer = http.post("/api/game/choice", json={
        "session_id": session.session_id, "overlay_intent": {"action": "buy", "target": target}})
    assert answer.status_code == 409 and answer.get_json()["stale_choice"] is True
    assert state.stats.gold == 0 and inventory.quantity(state, item_id) == carried
    assert state.turn_number == turn and not PROMPTS


def test_a_pair_made_stale_under_the_lock_reaches_the_prose(game) -> None:
    from engine.game import intents
    from engine.game.effects import apply_effect
    from engine.scenes.default_state import run_turn

    _scene, _app, _http, session = game
    state = session.engine.state
    _at(state, "edgewood_bakery", 9)
    rows = intents.overlay_targets(state)["buy"]
    assert rows, "Maris sells at the bakery at nine"
    apply_effect(state, {"type": "gold", "delta": -state.stats.gold})     # the coin spent elsewhere
    run_turn(session, "The player chooses: buy", intent={"action": "buy", "target": rows[0][0]}, overlay=True)
    assert PROMPTS and intents.OVERLAY_STALE in PROMPTS[-1]      # the refusal, in the narrator's input


def test_a_press_while_an_encounter_is_open_reaches_the_prose_and_leaves_it_open(game) -> None:
    import copy

    from engine.game import encounter, intents
    from engine.scenes.default_state import run_turn

    _scene, _app, _http, session = game
    state = session.engine.state
    _grant(state, _edible(1)[0])
    encounter.begin(state, "lost_child_at_the_treeline")
    before = copy.deepcopy(state.encounter)
    target = intents.overlay_targets(state)["eat"][0][0]
    run_turn(session, "The player chooses: eat", intent={"action": "eat", "target": target}, overlay=True)
    assert intents.OVERLAY_SCENE_REFUSAL in PROMPTS[-1]
    assert encounter.active(state) and state.encounter["id"] == before["id"]


def test_a_legal_press_runs_its_skill_and_the_turn_carries_it(game) -> None:
    from engine.game import intents, inventory

    scene, app, _http, session = game
    state = session.engine.state
    _grant(state, _edible(1)[0])
    target = intents.overlay_targets(state)["eat"][0][0]
    carried = inventory.quantity(state, target)
    sio = scene.socketio.test_client(app)
    sio.emit("join_session", {"session_id": session.session_id})
    sio.get_received()
    sio.emit("overlay_action", {"session_id": session.session_id,
                                "intent": {"action": "eat", "target": target}, "label": "ignored"})
    names = [e["name"] for e in sio.get_received()]
    assert "turn_update" in names and "turn_error" not in names
    assert PROMPTS and "The player chooses: Eat:" in PROMPTS[-1]
    assert inventory.quantity(state, target) == carried - 1      # the eat skill ran: one eaten


def test_a_second_overlay_press_while_a_turn_runs_is_busy(game) -> None:
    """Review Focus 3 (T14 review, d5): a real listed purchase pressed while a turn holds the lock is
    answered busy and buys nothing; pressed again once the lock is free, it buys once."""
    from engine.game import intents, inventory

    scene, app, _http, session = game
    state = session.engine.state
    _at(state, "edgewood_bakery", 9)
    target = intents.overlay_targets(state)["buy"][0][0]
    item_id = target.split("/", 1)[1]
    gold, carried = state.stats.gold, inventory.quantity(state, item_id)
    press = {"session_id": session.session_id, "intent": {"action": "buy", "target": target}}
    sio = scene.socketio.test_client(app)
    sio.get_received()
    assert session.lock.acquire(blocking=False)
    try:
        sio.emit("overlay_action", press)
    finally:
        session.lock.release()
    (event,) = [e for e in sio.get_received() if e["name"] == "turn_error"]
    assert event["args"][0]["busy"] is True and not PROMPTS
    assert state.stats.gold == gold and inventory.quantity(state, item_id) == carried
    sio.emit("overlay_action", press)
    assert inventory.quantity(state, item_id) == carried + 1
    assert 0 < gold - state.stats.gold                  # one price paid, once


def test_typed_text_still_carries_no_intent(game) -> None:
    from engine.scenes.default_state import resolve_player_intent

    _scene, _app, _http, session = game
    assert resolve_player_intent(session, "custom", "I eat the loaf") == {}


def test_a_use_receipt_says_what_was_used_once() -> None:
    """An item with no authored ``text`` gets ``inventory.use``'s default line; the summary must not
    double it ("used the X: You use the X."). An authored line is kept after the name."""
    from engine.agents.prompts import summarise_receipt

    plain = {"skill": "use_item", "result": {"ok": True, "name": "Whetstone", "text": "You use the whetstone."}}
    assert summarise_receipt(plain) == "used the whetstone."
    authored = {"skill": "use_item", "result": {"ok": True, "name": "Poultice bandage",
                                                "text": "The wound closes under it."}}
    assert summarise_receipt(authored) == "used the poultice bandage: The wound closes under it."

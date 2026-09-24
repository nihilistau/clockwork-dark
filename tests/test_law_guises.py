"""
The Law, part four: guises.

THE SHAPE. A guise is a face the player wears: ``self`` always, plus any
other the law file declares with an ``item`` the pack carries. ``guise``'s
verb (``engine/game/intents.py``) offers exactly those, minus whichever one
is worn right now. The ``change_guise`` skill (``engine/skills/builtin/law.py``)
resolves it through ``law.change_guise``, which sets the guise through the
``law_guise`` effect and, if anyone present and available notices the change,
tells the watch the two faces are one person through ``law_link``. Neither
effect ever touches ``state.law`` except through the other -- both are
writers of record, re-validated independently of their one caller.

WHAT THESE TESTS HOLD. The verb offers only ``self`` (when not worn) and
guises whose item is carried, never the one already on; a change seen by
someone present links old and new; a change nobody could see does not; a
committed deed files whichever guise is CURRENTLY worn; a guise the watch has
never linked to anything, with a clean record, reads ``unknown``; the
flagship (no Law) never offers the verb; and a seed replays.

Version: v0.1.0 [2026-09-24]
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import intents
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.rng import LAW
from engine.game.state import GameState, InventoryItem
from engine.world import law, npc_sim

from test_law import SPEC as LAW_SPEC

SQUARE = "edgewood_square"
ALL_DAY = [{"hours": list(range(24)), "location": SQUARE, "activity": "idling"}]


def _dump(path: Path, doc: Any) -> str:
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(path)


@pytest.fixture()
def lawful(tmp_path: Path) -> Iterator[Path]:
    set_overlay({"paths": {"law": _dump(tmp_path / "law.yaml", LAW_SPEC)}})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _person(npc_id: str, role: str, routine: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": npc_id, "name": npc_id.replace("_", " ").title(), "role": role, "routine": routine}


def _world(people: list[dict[str, Any]], *, seed: int = 42) -> GameState:
    state = GameState(rng_seed=seed, location_id=SQUARE)
    state.procgen = generate_world(seed)
    state.procgen.npcs = people
    return state


def _carry(state: GameState, item_id: str) -> None:
    state.inventory.append(InventoryItem(id=item_id, name=item_id, qty=1))


# -- the verb: only what is carried, never what is worn ----------------------


def test_the_verb_offers_only_carried_guises(lawful: Path) -> None:
    state = _world([])
    # Nothing carried, own face worn: nothing to change into.
    assert intents.find_verb(intents.legal_intents(state), "guise") is None

    _carry(state, "golden_ring")  # the Magpie's item
    verb = intents.find_verb(intents.legal_intents(state), "guise")
    assert verb is not None
    assert verb.targets == ("magpie",)
    assert verb.label_for("magpie") == "change into the Magpie's mask"

    # Wearing the Magpie now: `self` is offered (it needs no item), the
    # Magpie is not (it is the one worn), and the porter still is not (its
    # item, `candle`, is not carried).
    state.law["guise"] = "magpie"
    verb = intents.find_verb(intents.legal_intents(state), "guise")
    assert verb is not None
    assert verb.targets == ("self",)
    assert verb.label_for("self") == "go as yourself"

    _carry(state, "candle")  # the porter's item
    verb = intents.find_verb(intents.legal_intents(state), "guise")
    assert set(verb.targets) == {"self", "porter"}


def test_to_tool_call_and_skill_mapping() -> None:
    assert intents.SKILL_FOR_ACTION["guise"] == "change_guise"
    assert intents.REFUSAL_KEY_FOR_ACTION["guise"] == "ok"
    intent = {"action": "guise", "target": "porter"}
    assert intents.to_tool_call(GameState(), intent) == ("change_guise", {"guise_id": "porter"})


# -- witnessed changes link, unwitnessed ones do not -------------------------


def test_a_seen_change_links_old_and_new(lawful: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _AlwaysNotices:
        def random(self) -> float:
            return 0.0

    monkeypatch.setattr("engine.game.rng.world_rng", lambda state, stream: _AlwaysNotices())
    state = _world([_person("gen_g_a", "labourer", ALL_DAY)])
    # `porter`, not `magpie`: the spec already links self-magpie, so becoming
    # the Magpie would tell the watch nothing it did not already assume.
    _carry(state, "candle")
    out = law.change_guise(state, "porter")
    assert out == {"ok": True, "guise": "porter", "label": "a porter", "seen": True}
    assert ["self", "porter"] in state.law["links"]
    # The file's own starting belief (self-magpie) is kept, not replaced by
    # the new pair of one.
    assert ["self", "magpie"] in state.law["links"]

    # Transitive with that starting belief: linking `porter` to `magpie` now
    # joins all three, through self on one side and the new pair on the other.
    _carry(state, "golden_ring")
    out = law.change_guise(state, "magpie")
    assert out["seen"] is True
    assert law.same_person(state, "magpie") == {"self", "magpie", "porter"}


def test_an_unseen_change_does_not_link(lawful: Path) -> None:
    state = _world([])  # nobody present to notice anything
    _carry(state, "golden_ring")
    out = law.change_guise(state, "magpie")
    assert out == {"ok": True, "guise": "magpie", "label": "the Magpie's mask", "seen": False}
    # The file's own starting belief (self-magpie) still reads through --
    # nothing was ADDED, but nothing already there was lost either.
    assert law.same_person(state, "magpie") == {"self", "magpie"}
    assert "links" not in state.law


def test_re_wearing_the_same_guise_rolls_nothing(lawful: Path) -> None:
    state = _world([_person("gen_g_a", "labourer", ALL_DAY)])
    out = law.change_guise(state, "self")
    assert out == {"ok": True, "guise": "self", "label": "your own face", "seen": False}
    assert LAW not in state.rng_counters


def test_change_guise_does_not_move_the_clock(lawful: Path) -> None:
    state = _world([_person("gen_g_a", "labourer", ALL_DAY)])
    hour_before = state.world_clock_hours
    _carry(state, "golden_ring")
    law.change_guise(state, "magpie")
    assert state.world_clock_hours == hour_before


# -- a refused change never rolls, and never moves the LAW stream -----------


def test_an_unknown_guise_is_refused_before_any_roll(lawful: Path) -> None:
    state = _world([_person("gen_g_a", "labourer", ALL_DAY)])
    out = law.change_guise(state, "highwayman")
    assert out == {"ok": False, "message": "unknown guise `highwayman`"}
    assert LAW not in state.rng_counters
    assert law.current_guise(state) == "self"


def test_an_uncarried_guise_is_refused_before_any_roll(lawful: Path) -> None:
    state = _world([_person("gen_g_a", "labourer", ALL_DAY)])
    out = law.change_guise(state, "porter")  # `candle` never carried
    assert out["ok"] is False and "candle" in out["message"]
    assert LAW not in state.rng_counters
    assert law.current_guise(state) == "self"


# -- an item that stops being carried stops the guise being worn ------------


def test_current_guise_falls_back_to_self_when_the_item_is_lost(lawful: Path) -> None:
    state = _world([])
    _carry(state, "candle")
    law.change_guise(state, "porter")
    assert law.current_guise(state) == "porter"
    # The stored value is untouched by a read -- it is only what the item
    # check makes of it that changes.
    assert state.law["guise"] == "porter"
    apply_effect(state, {"type": "remove_item", "item_id": "candle", "qty": 1})
    assert law.current_guise(state) == "self"
    assert state.law["guise"] == "porter"  # still stale; nothing here wrote it


def test_a_deed_files_the_effective_guise_not_the_stale_stored_one(lawful: Path) -> None:
    state = _world([_person("gen_g_w", "watch", ALL_DAY)])
    _carry(state, "candle")
    law.change_guise(state, "porter")
    apply_effect(state, {"type": "remove_item", "item_id": "candle", "qty": 1})
    law.commit_deed(state, "pickpocket", certain=("gen_g_w",))
    (row,) = state.law["witnessed"]
    assert row["guise"] == "self"
    (report,) = state.law["reports"]
    assert report["guise"] == "self"


def test_the_verb_reflects_the_effective_guise_once_the_item_is_lost(lawful: Path) -> None:
    state = _world([])
    _carry(state, "candle")
    law.change_guise(state, "porter")
    apply_effect(state, {"type": "remove_item", "item_id": "candle", "qty": 1})
    # No longer wearing the porter in effect (the item is gone) and no longer
    # carrying it either, so the verb offers nothing at all: `self` is what
    # the player effectively already is, and `porter` is not carried.
    assert intents.find_verb(intents.legal_intents(state), "guise") is None
    _carry(state, "golden_ring")
    verb = intents.find_verb(intents.legal_intents(state), "guise")
    assert verb is not None and verb.targets == ("magpie",)


# -- deeds file whichever guise is worn --------------------------------------


def test_a_deed_files_the_guise_currently_worn(lawful: Path) -> None:
    state = _world([_person("gen_g_w", "watch", ALL_DAY)])
    _carry(state, "candle")
    law.change_guise(state, "porter")
    law.commit_deed(state, "pickpocket", certain=("gen_g_w",))
    (row,) = state.law["witnessed"]
    assert row["guise"] == "porter"
    (report,) = state.law["reports"]
    assert report["guise"] == "porter"


# -- an unlinked guise with a clean record reads unknown ---------------------


def test_an_unlinked_guise_with_a_clean_record_is_unknown(lawful: Path) -> None:
    state = _world([])  # nobody present: the change of guise itself goes unseen
    _carry(state, "candle")
    law.change_guise(state, "porter")
    assert "links" not in state.law  # porter stays isolated -- nothing saw it
    assert law.wanted_band(state, "porter", "village") == "unknown"

    # A watchman now, for the deed only. Committing under the Magpie's name
    # must not touch the porter's file -- they are not linked in the spec,
    # and nothing here has linked them.
    state.procgen.npcs = [_person("gen_g_w", "watch", ALL_DAY)]
    state.law["guise"] = "magpie"
    law.commit_deed(state, "assault_watch", certain=("gen_g_w",))
    assert law.wanted_band(state, "porter", "village") == "unknown"
    assert law.wanted_band(state, "magpie", "village") != "unknown"


# -- the law_guise and law_link effects, directly ----------------------------


def test_law_guise_refuses_an_unknown_guise(lawful: Path) -> None:
    state = _world([])
    out = apply_effect(state, {"type": "law_guise", "guise": "highwayman"})
    assert out["ok"] is False and "highwayman" in out["message"]
    assert "guise" not in state.law


def test_law_guise_refuses_an_uncarried_item(lawful: Path) -> None:
    state = _world([])
    out = apply_effect(state, {"type": "law_guise", "guise": "porter"})
    assert out["ok"] is False and "candle" in out["message"]
    assert "guise" not in state.law


def test_law_guise_never_refuses_self(lawful: Path) -> None:
    state = _world([])
    out = apply_effect(state, {"type": "law_guise", "guise": "self"})
    assert out["ok"] is True and state.law["guise"] == "self"


def test_law_link_is_symmetric_and_deduplicated(lawful: Path) -> None:
    state = _world([])
    apply_effect(state, {"type": "law_link", "a": "magpie", "b": "porter"})
    assert state.law["links"].count(["magpie", "porter"]) + state.law["links"].count(
        ["porter", "magpie"]
    ) == 1
    before = copy.deepcopy(state.law["links"])
    # Asking the other way round a second time adds nothing.
    apply_effect(state, {"type": "law_link", "a": "porter", "b": "magpie"})
    assert state.law["links"] == before
    # The file's own starting belief (self-magpie) is kept, not replaced.
    assert ["self", "magpie"] in state.law["links"]


def test_law_link_refuses_unknown_guises_and_self_links(lawful: Path) -> None:
    state = _world([])
    bad = apply_effect(state, {"type": "law_link", "a": "self", "b": "nobody"})
    assert bad["ok"] is False
    same = apply_effect(state, {"type": "law_link", "a": "self", "b": "self"})
    assert same["ok"] is False
    assert "links" not in state.law


# -- undeclared law: inert end to end ----------------------------------------


def test_undeclared_law_change_guise_is_inert() -> None:
    state = GameState()
    out = law.change_guise(state, "self")
    assert out["ok"] is False
    assert state.law == {}


def test_the_flagship_offers_no_guise_verb() -> None:
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        assert not law.declared()
        state = GameState(rng_seed=1, location_id=SQUARE)
        state.procgen = generate_world(1)
        assert intents.find_verb(intents.legal_intents(state), "guise") is None
        out = law.change_guise(state, "self")
        assert out["ok"] is False
        assert state.law == {}
    finally:
        registry.deactivate()


# -- replay -------------------------------------------------------------------


def test_a_seed_replays(lawful: Path) -> None:
    def _run() -> tuple[dict[str, Any], dict[str, int]]:
        state = _world([_person(f"gen_g_{i}", "labourer", ALL_DAY) for i in range(5)], seed=7)
        _carry(state, "golden_ring")
        law.change_guise(state, "magpie")
        return copy.deepcopy(state.law), dict(state.rng_counters)

    first = _run()
    second = _run()
    assert first == second

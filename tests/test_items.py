"""
Item verbs: use, equip, collect — and the rule that nothing is decoration.

THE AUDIT THIS FILE FREEZES. Before v0.2.0 the 81 declared items broke down as
49 with some mechanical reach and 32 with none: 29 whose only verb was a sale
price and 3 -- goat_bell, mural_pigment, tinker_map -- that no code path in the
game could grant, consume or ask for. ``test_no_item_is_pure_decoration`` is
that audit turned into a gate: a new item without a verb fails the suite rather
than shipping as a picture with a price on it.

The other tests are here because each of them is a bug that was easy to write
and would have been silent: gear that outlives the day it was worn, a bandage
that heals a scratch while a deep wound is open, a shield that cancels a wound
outright, a collection that pays twice, and a second game crashing on a table
the first game has and it does not.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import engine.skills.builtin  # noqa: F401 — registers the item skills
from engine.game import checks, effects, inventory
from engine.game.clock import advance_time
from engine.game.state import GameState

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def state() -> GameState:
    return GameState()


# ---------------------------------------------------------------------------
# the audit, as a gate
# ---------------------------------------------------------------------------


def test_no_item_is_pure_decoration():
    """
    Every declared item answers to at least one verb that is not a sale price.

    ``verbs_for`` returns use / eat / equip / craft / collect / quest / trade.
    ``["trade"]`` alone is the shape the audit was counting: an object with a
    name, a weight and a picture whose only interaction is handing it to a
    vendor. Thirty-two items looked like that before v0.2.0 -- twenty-nine of
    them sellable, three of them not even that.
    """
    registry = inventory.load_items()
    assert len(registry) >= 80

    inert = sorted(i for i in registry if not inventory.verbs_for(i))
    assert not inert, f"items with no verb at all: {inert}"

    sell_only = sorted(i for i in registry if inventory.verbs_for(i) == ["trade"])
    assert not sell_only, f"items whose only verb is a sale price: {sell_only}"


def test_the_verb_list_names_the_real_systems():
    """
    A verb has to correspond to something the engine actually does.

    Asserted per-verb against a known item so that a future refactor cannot
    make ``verbs_for`` optimistic -- which would turn the gate above into a
    test that passes because it stopped looking.
    """
    assert "eat" in inventory.verbs_for("loaf")  # games/clockwork-dark/data/rules/survival.yaml
    assert "craft" in inventory.verbs_for("barley_flour")  # games/clockwork-dark/data/recipes/*.yaml
    assert "craft" in inventory.verbs_for("mortar_and_pestle")  # a recipe tool
    assert "equip" in inventory.verbs_for("wool_cloak")  # games/clockwork-dark/data/items/gear.yaml
    assert "use" in inventory.verbs_for("bandage")  # a use: block
    assert "collect" in inventory.verbs_for("hare_foot")  # games/clockwork-dark/data/tables/collections.yaml
    assert "quest" in inventory.verbs_for("cut_reed")  # a has_item condition
    assert inventory.verbs_for("no_such_item_at_all") == []


def test_the_three_unreachable_items_are_reachable():
    """
    goat_bell, mural_pigment and tinker_map were named by nothing.

    Not "hard to get" -- ungettable. No quest granted them, no recipe made
    them, no table dropped them, no condition asked for them. Each now has a
    source and a reason, and this test names all three so a refactor that
    quietly drops one is visible.
    """
    quests = "\n".join(
        p.read_text(encoding="utf-8") for p in (_ROOT / "games" / "clockwork-dark" / "data" / "quests").rglob("*.yaml")
    )
    recipes = "\n".join(
        p.read_text(encoding="utf-8") for p in (_ROOT / "games" / "clockwork-dark" / "data" / "recipes").glob("*.yaml")
    )
    collections = (_ROOT / "games" / "clockwork-dark" / "data" / "tables" / "collections.yaml").read_text(encoding="utf-8")

    # goat_bell: granted by lost_goat, required by lost_goat.
    assert "item_id: goat_bell" in quests
    assert "has_item: { id: goat_bell" in quests
    # mural_pigment: ground by a recipe, consumed by shrine_mural.
    assert "id: mural_pigment" in recipes
    assert "has_item: { id: mural_pigment" in quests
    # tinker_map: paid out by a collection, opens a stage in toll_roads.
    assert "item_id: tinker_map" in collections
    assert "has_item: { id: tinker_map" in quests


def test_every_item_has_a_generation_prompt_for_both_backends():
    """
    One source, two dialects, no gaps.

    52 of the 81 items had no packed plate AND no prompt, so neither backend
    could ever have produced one. Both dialects render off the same structured
    entry; asserting on both is what stops a future edit from adding a subject
    the tag renderer cannot see.
    """
    from engine.media.art import render_prose, render_tags

    subjects = yaml.safe_load(
        (_ROOT / "games" / "clockwork-dark" / "data" / "art" / "subjects.yaml").read_text(encoding="utf-8")
    )
    described = set(subjects["items"]) - {"defaults"}
    registry = set(inventory.load_items())
    assert registry - described == set(), f"no art prompt for: {sorted(registry - described)}"
    assert described - registry == set(), f"art prompt for unknown item: {sorted(described - registry)}"

    from engine.media.art import _item_fields

    for item_id in ("bent_nail", "goat_bell", "hobnail_boots"):
        # The "unknown subject" fallback in engine/media/art.py::_fields returns
        # the de-underscored id with empty details and the daypart as the
        # setting. A described item must not look like that.
        fields = _item_fields(item_id)
        assert fields is not None and fields["details"] and fields["setting"]

        prose = render_prose(item_id, kind="item")
        positive, negative = render_tags(item_id, kind="item")
        assert fields["details"] in prose and fields["details"] in positive
        assert negative, "ComfyUI needs a negative prompt; Grok Imagine must not get one"
        assert negative not in prose, "Grok Imagine takes positive description only"


def test_every_item_has_its_own_shipped_plate():
    """
    81 items, 81 pictures, no two the same.

    Before v0.2.0 the pack answered 25 of them and four of those 25 borrowed a
    neighbour's plate -- a crock of honey rendered as a potion vial, three
    different herbs all rendered as the same bundle. The rest fell through to
    the procedural wash. Sharing is caught as well as absence, because a shared
    plate is the failure that does not look like one.
    """
    from engine.media.providers.base import ImageRequest
    from engine.media.providers.shipped import ShippedArtProvider, reset_manifest_cache

    reset_manifest_cache()
    shipped = ShippedArtProvider()
    registry = inventory.load_items()

    unpainted = sorted(
        i for i in registry
        if not shipped.generate(ImageRequest(subject_id=i, kind="item")).ok
    )
    assert not unpainted, f"items with no shipped plate: {unpainted}"

    manifest = yaml.safe_load(
        (_ROOT / "games" / "clockwork-dark" / "data" / "art" / "manifest.yaml").read_text(encoding="utf-8")
    )
    plates = {i: manifest["items"][i] for i in registry}
    shared = sorted(p for p in set(plates.values()) if list(plates.values()).count(p) > 1)
    assert not shared, f"plates serving more than one item: {shared}"

    # An `art:` key that names a DIFFERENT item is how the borrowing happened,
    # and it survives a manifest fix because the UI prefers it (see
    # content/scenes/clockwork/clockwork_scene.py::item_catalog).
    borrowed = {
        i: row["art"] for i, row in registry.items() if row.get("art") and row["art"] != i
    }
    assert not borrowed, f"items pointing their art key at another item: {borrowed}"


# ---------------------------------------------------------------------------
# equipment
# ---------------------------------------------------------------------------


def test_worn_gear_appears_in_the_check_receipt_by_name(state: GameState):
    inventory.grant(state, "wool_cloak")
    assert inventory.equip(state, "wool_cloak")["ok"]

    labels = [label for label, _ in checks.gather_modifiers(state, "survival")]
    assert "wool cloak" in labels


def test_boots_help_survival_and_hurt_stealth(state: GameState):
    """The trade-off is the point: they ring on the Millhaven metalling."""
    inventory.grant(state, "hobnail_boots")
    inventory.equip(state, "hobnail_boots")

    survival = dict(checks.gather_modifiers(state, "survival"))
    stealth = dict(checks.gather_modifiers(state, "stealth"))
    assert survival["hobnailed boots"] == 2
    assert stealth["hobnailed boots"] == -1


def test_one_item_per_slot(state: GameState):
    inventory.grant(state, "wooden_shield")
    inventory.grant(state, "small_shield")
    inventory.equip(state, "wooden_shield")
    result = inventory.equip(state, "small_shield")

    assert result["displaced"] == "wooden_shield"
    assert inventory.equipped(state)["offhand"] == "small_shield"
    labels = [label for label, _ in checks.gather_modifiers(state, "stealth")]
    assert "board shield" not in labels


def test_gear_does_not_expire_with_the_clock(state: GameState):
    """
    Worn gear is a TimedEffect and the clock sweeps TimedEffects.

    The sentinel expiry is the whole reason this encoding is safe; a regression
    here would silently undress the player after one in-game day.
    """
    inventory.grant(state, "wool_cloak")
    inventory.equip(state, "wool_cloak")
    advance_time(state, 24 * 30)
    assert inventory.equipped(state) == {"body": "wool_cloak"}


def test_unequip_removes_every_bonus(state: GameState):
    inventory.grant(state, "hobnail_boots")
    inventory.equip(state, "hobnail_boots")
    inventory.unequip(state, "feet")

    assert inventory.equipped(state) == {}
    assert not any(e.id.startswith("equip:") for e in state.active_effects)


def test_equipping_something_you_do_not_carry_is_refused_not_raised(state: GameState):
    result = inventory.equip(state, "wool_cloak")
    assert result["ok"] is False and "carrying" in result["message"]


def test_equipping_something_unwearable_is_refused(state: GameState):
    inventory.grant(state, "loaf")
    assert inventory.equip(state, "loaf")["ok"] is False


def test_a_shield_absorbs_wound_severity_but_never_all_of_it(state: GameState):
    inventory.grant(state, "wooden_shield")
    inventory.equip(state, "wooden_shield")

    receipt = effects.apply_effect(
        state, {"type": "wound", "text": "Deep cut", "severity": 3, "check_penalty": -3}
    )
    assert receipt["absorbed"] == 2
    assert state.wounds[0].severity == 1
    assert state.wounds[0].check_penalty == -1

    # Severity 1 with a shield is still severity 1. Taking the hit is taking it.
    effects.apply_effect(
        state, {"type": "wound", "text": "Graze", "severity": 1, "check_penalty": -1}
    )
    assert state.wounds[1].severity == 1


def test_a_pack_raises_the_reported_carry_limit(state: GameState):
    before = inventory.carry_limit(state)
    inventory.grant(state, "travel_pack")
    inventory.equip(state, "travel_pack")
    assert inventory.carry_limit(state) == before + 15.0
    assert inventory.snapshot(state)["carry_limit"] == before + 15.0


# ---------------------------------------------------------------------------
# using things
# ---------------------------------------------------------------------------


def test_a_bandage_closes_a_wound_worst_first(state: GameState):
    effects.apply_effect(state, {"type": "wound", "text": "Graze", "severity": 1})
    effects.apply_effect(state, {"type": "wound", "text": "Deep cut", "severity": 4})
    inventory.grant(state, "bandage")

    result = inventory.use(state, "bandage")

    assert result["ok"] is True
    assert [w.text for w in state.wounds] == ["Graze"]
    assert inventory.quantity(state, "bandage") == 0


def test_a_draught_clears_a_condition(state: GameState):
    effects.apply_effect(
        state, {"type": "check_penalty", "text": "a fever", "delta": -2, "days": 5}
    )
    inventory.grant(state, "potion")
    state.stats.hp = 10

    inventory.use(state, "potion")

    assert not [e for e in state.active_effects if e.kind == "check_penalty"]
    assert state.stats.hp == 14


def test_a_draught_does_not_strip_gear_or_undo_a_finished_collection(state: GameState):
    """
    `clear_condition` walks the same list worn gear and set rewards live in.

    Both are ``check_penalty`` entries with the "never" expiry, because that is
    the one kind engine/game/checks.py itemises. A blanket clear that did not
    exclude them would take a cloak off your back and a completed set's
    standing away for the price of one draught.
    """
    for item_id in ("hare_foot", "wax_seal_saint", "bent_nail", "saint_candle", "birch_bark"):
        inventory.grant(state, item_id)
    inventory.grant(state, "wool_cloak")
    inventory.grant(state, "potion")
    inventory.equip(state, "wool_cloak")
    effects.apply_effect(
        state, {"type": "check_penalty", "text": "a fever", "delta": -2, "days": 5}
    )

    inventory.use(state, "potion")

    assert inventory.equipped(state) == {"body": "wool_cloak"}
    labels = [label for label, _ in checks.gather_modifiers(state, "sympathy")]
    assert "what the old women taught you" in labels
    assert "a fever" not in labels


def test_a_use_that_needs_a_companion_item_refuses_before_spending_anything(
    state: GameState,
):
    inventory.grant(state, "tinderbox")
    hours_before = state.world_clock_hours

    result = inventory.use(state, "tinderbox")

    assert result["ok"] is False
    assert "firewood" in result["message"]
    assert state.world_clock_hours == hours_before
    assert inventory.quantity(state, "tinderbox") == 1


def test_a_once_per_day_use_resets_with_the_day(state: GameState):
    inventory.grant(state, "tinderbox")
    inventory.grant(state, "firewood_bundle", 2)

    assert inventory.use(state, "tinderbox")["ok"] is True
    assert inventory.use(state, "tinderbox")["ok"] is False

    advance_time(state, 24)
    assert inventory.use(state, "tinderbox")["ok"] is True


def test_using_an_item_you_do_not_carry_is_refused_not_raised(state: GameState):
    assert inventory.use(state, "bandage")["ok"] is False


def test_an_item_with_no_verb_says_so(state: GameState):
    inventory.grant(state, "iron_stock")
    result = inventory.use(state, "iron_stock")
    assert result["ok"] is False and "nothing to do" in result["message"]


def test_coins_become_gold(state: GameState):
    """The purse was an inventory entry with no way to become the stat."""
    inventory.grant(state, "coins")
    before = state.stats.gold
    inventory.use(state, "coins")
    assert state.stats.gold == before + 12


# ---------------------------------------------------------------------------
# collections
# ---------------------------------------------------------------------------


def test_a_set_closes_when_its_last_piece_lands(state: GameState):
    for item_id in ("hare_foot", "wax_seal_saint", "bent_nail", "saint_candle"):
        inventory.grant(state, item_id)
    assert not state.flags.get("collection_folk_remedies_complete")

    inventory.grant(state, "birch_bark")

    assert state.flags["collection_folk_remedies_complete"] is True
    assert state.reputations.get("unnamed_saints", 0) == 7
    labels = [label for label, _ in checks.gather_modifiers(state, "sympathy")]
    assert "what the old women taught you" in labels


def test_a_set_pays_once(state: GameState):
    for item_id in ("hare_foot", "wax_seal_saint", "bent_nail", "saint_candle", "birch_bark"):
        inventory.grant(state, item_id)
    standing = state.reputations["unnamed_saints"]

    inventory.grant(state, "hare_foot")
    inventory.evaluate_collections(state)

    assert state.reputations["unnamed_saints"] == standing


def test_a_set_needs_the_declared_quantity(state: GameState):
    inventory.grant(state, "ninth_pin")
    inventory.grant(state, "brass_ward_pin", 8)
    assert not state.flags.get("collection_nine_pins_complete")

    inventory.grant(state, "brass_ward_pin")
    assert state.flags["collection_nine_pins_complete"] is True


def test_a_collection_reward_that_grants_an_item_does_not_recurse(state: GameState):
    """`turned_up_things` pays out an item, and items are what close sets."""
    for item_id in ("stone_knife", "iron_key", "golden_ring", "goat_bell"):
        inventory.grant(state, item_id)

    assert state.flags["collection_turned_up_things_complete"] is True
    assert inventory.quantity(state, "tinker_map") == 1


def test_collection_status_reports_what_is_missing(state: GameState):
    inventory.grant(state, "wool_cloak")
    row = next(r for r in inventory.collection_status(state) if r["id"] == "road_kit")
    assert row["complete"] is False
    assert "hobnail_boots" in row["missing"]
    assert not row["claimed"]


# ---------------------------------------------------------------------------
# the second game
# ---------------------------------------------------------------------------


def test_the_garden_declares_the_same_blocks():
    """
    Whatever exists here must exist there or be cleanly absent.

    The Wicked Garden carries its own items, its own collections and its own
    art prompts. This asserts the shapes agree, so a change to one game's
    schema cannot leave the other silently degraded.
    """
    garden = yaml.safe_load(
        (_ROOT / "games/wicked-garden/data/items/garden.yaml").read_text(encoding="utf-8")
    )
    rows = {r["id"]: r for r in garden["items"]}
    assert any("equip" in r for r in rows.values())
    assert any("use" in r for r in rows.values())

    for row in rows.values():
        equip = row.get("equip")
        if equip:
            assert equip["slot"] in inventory.EQUIP_SLOTS, row["id"]

    sets = yaml.safe_load(
        (_ROOT / "games/wicked-garden/data/tables/collections.yaml").read_text(
            encoding="utf-8"
        )
    )
    for entry in sets["collections"]:
        for member in entry["items"]:
            assert member in rows, (
                f"{entry['id']} names an item this garden has no row for: {member}"
            )

    subjects = yaml.safe_load(
        (_ROOT / "games/wicked-garden/data/art/subjects.yaml").read_text(encoding="utf-8")
    )
    assert set(rows) == set(subjects["items"]) - {"defaults"}


def test_a_game_with_no_collections_file_is_silent(monkeypatch, tmp_path):
    """
    An absent table is not a warning.

    A second story shipped without one for a release. A missing file must read
    as "this game has no sets", not as an error the player sees in a log.
    """
    from engine.config import get_config

    monkeypatch.setattr(
        inventory, "_collections_path", lambda: tmp_path / "collections.yaml"
    )
    assert inventory.load_collections() == []
    assert inventory.collection_status(GameState()) == []
    assert get_config() is not None


# ---------------------------------------------------------------------------
# the skills reach the model
# ---------------------------------------------------------------------------


def test_the_item_skills_register_without_the_dispatcher_naming_them():
    """
    Registration rides on the package import, not on a line in the dispatcher.

    engine/agents/tool_dispatcher.py imports four builtin modules by name and
    this pass does not own that file. It does not need to: importing any
    sibling imports engine/skills/builtin/__init__.py, which imports them all.
    If that indirection is ever removed, six tools go silently missing from
    every agent's toolset -- silently, because nothing else would fail.
    """
    import engine.skills.builtin.mechanics  # noqa: F401 — the dispatcher's import
    from engine.skills.registry import SKILL_REGISTRY

    names = {s.name for s in SKILL_REGISTRY.all_tools()}
    assert {
        "use_item",
        "equip_item",
        "unequip_item",
        "query_equipment",
        "inspect_item",
        "collections",
    } <= names


def test_inspect_item_answers_what_an_item_is_for():
    """The tool that exists so the narrator stops guessing."""
    import json

    from engine.game.engine import GameEngine, active_engine
    from engine.skills.builtin.items import inspect_item

    engine = GameEngine(GameState())
    with active_engine(engine):
        payload = json.loads(inspect_item("wild_mushroom"))

    assert payload["known"] is True
    assert "eat" in payload["verbs"] and "craft" in payload["verbs"]
    assert "dry_mushrooms" in payload["consumed_by_recipes"]


# ---------------------------------------------------------------------------
# the ComfyUI provider that did not exist
# ---------------------------------------------------------------------------


def test_the_comfyui_provider_can_be_built():
    """
    ``build_provider("comfyui")`` raised ImportError: the module was missing.

    The fallback chain in engine/media/providers/__init__.py is written to
    handle a provider that cannot run. It was never given the chance, because
    the import failed before ``available()`` could return False.
    """
    from engine.media.providers import build_provider

    provider = build_provider("comfyui")
    assert provider is not None
    assert provider.name == "comfyui"
    # Nothing is listening and it is disabled by default. Both must be a False,
    # not an exception.
    assert provider.available() is False


def test_the_comfyui_workflow_ends_in_a_saved_file():
    """A bare CLIPTextEncode node is accepted by ComfyUI and produces nothing."""
    from engine.media.providers.base import ImageRequest
    from engine.media.providers.comfy import build_workflow

    graph = build_workflow(
        ImageRequest(subject_id="bent_nail", kind="item"),
        checkpoint="sd_xl_base_1.0.safetensors",
        steps=28,
        cfg_scale=6.5,
        sampler="dpmpp_2m",
        scheduler="karras",
        seed=1234,
    )
    classes = {node["class_type"] for node in graph.values()}
    assert {"CheckpointLoaderSimple", "KSampler", "VAEDecode", "SaveImage"} <= classes
    # Positive and negative are separate encodes -- that is the whole reason
    # ComfyUI gets the tag dialect and Grok Imagine does not.
    assert sum(1 for n in graph.values() if n["class_type"] == "CLIPTextEncode") == 2
    assert graph["4"]["inputs"]["width"] == 256, "items render square at 256"

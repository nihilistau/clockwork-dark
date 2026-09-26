"""
Crafting — the `craft_item` skill against games/clockwork-dark/data/recipes/*.yaml.

WHAT THESE TESTS ARE DEFENDING. DESIGN.md makes "mundane craft as dignity" a
pillar, and the recipe files shipped for a full phase with a header reading
"DATA ONLY. Nothing reads this file yet." The skill reads them now, and these
tests hold the contract:

  1. Refusals are free. Unknown recipe, wrong station, missing tool, short of
     inputs -- none of them advance the clock or touch the pack.
  2. The attempt is not. Inputs and hours are spent pass or fail.
  3. Degrees mean something. A crit adds to the batch, a partial wastes some of
     it, a failure falls back to declared salvage.
  4. The receipt itemises everything, because a craft the player cannot audit
     is a number the narrator made up.
"""

from __future__ import annotations

import json
import re

import pytest

from engine.game import checks, inventory
from engine.game.dice import DiceResult
from engine.game.engine import GameEngine, active_engine
from engine.game.procgen import new_game_state


def _state(location_id: str = "forest_clearing"):
    state = new_game_state(seed=42, location_id=location_id)
    return state


def _craft(state, recipe_id: str) -> dict:
    from engine.skills.builtin.mechanics import craft_item

    with active_engine(GameEngine(state)):
        return json.loads(craft_item(recipe_id))


def _force_degree(monkeypatch, degree: str) -> None:
    """Pin the check outcome so a test asserts the contract, not the dice."""

    def fake_resolve(state, skill, difficulty="standard", **kwargs):
        dice = DiceResult(
            sides=20,
            rolls=[10],
            modifier=0,
            total=10,
            critical=False,
            fumble=False,
            reason="craft",
        )
        return checks.CheckResult(
            skill=skill,
            stat="craft",
            dc=10,
            difficulty=str(difficulty),
            dice=dice,
            modifiers=[],
            total=10,
            margin=0,
            degree=degree,
        )

    monkeypatch.setattr(checks, "resolve", fake_resolve)


# ---------------------------------------------------------------------------
# refusals are free
# ---------------------------------------------------------------------------


def test_an_unknown_recipe_is_refused_and_costs_nothing():
    state = _state()
    hours_before = state.world_clock_hours

    outcome = _craft(state, "recipe_that_does_not_exist")

    assert outcome["success"] is False
    assert "recipe_that_does_not_exist" in outcome["error"]
    assert state.world_clock_hours == hours_before


def test_missing_inputs_are_named_and_nothing_is_spent():
    state = _state()
    hours_before = state.world_clock_hours

    outcome = _craft(state, "dry_mushrooms")  # needs 5x wild_mushroom

    assert outcome["success"] is False
    assert "wild_mushroom" in outcome["error"]
    assert state.world_clock_hours == hours_before
    assert inventory.quantity(state, "dried_mushrooms") == 0


def test_the_wrong_station_is_refused_before_the_clock_moves():
    state = _state(location_id="forest_clearing")
    inventory.grant(state, "barley_flour", 1)
    inventory.grant(state, "baking_peel", 1)
    hours_before = state.world_clock_hours

    outcome = _craft(state, "bake_loaf")  # station: edgewood_bakery

    assert outcome["success"] is False
    assert "edgewood_bakery" in outcome["error"]
    assert state.world_clock_hours == hours_before
    assert inventory.quantity(state, "barley_flour") == 1


def test_a_missing_tool_is_refused_by_name():
    state = _state(location_id="edgewood_bakery")
    inventory.grant(state, "barley_flour", 1)

    outcome = _craft(state, "bake_loaf")  # tools: [baking_peel]

    assert outcome["success"] is False
    assert "baking_peel" in outcome["error"]


# ---------------------------------------------------------------------------
# the attempt spends, pass or fail
# ---------------------------------------------------------------------------


def test_a_failed_craft_still_costs_the_inputs_and_the_morning(monkeypatch):
    _force_degree(monkeypatch, "failure")
    state = _state()
    inventory.grant(state, "wild_mushroom", 5)
    hours_before = state.world_clock_hours

    outcome = _craft(state, "dry_mushrooms")

    assert outcome["success"] is False
    assert state.world_clock_hours > hours_before
    assert inventory.quantity(state, "wild_mushroom") == 2, (
        "failure salvages 2 of the 5 consumed mushrooms, per the recipe"
    )
    assert outcome["salvaged"] is True
    assert outcome["produced"]["id"] == "wild_mushroom"


def test_a_failure_with_no_salvage_produces_nothing(monkeypatch):
    _force_degree(monkeypatch, "failure")
    state = _state()
    inventory.grant(state, "birch_resin", 2)

    outcome = _craft(state, "press_pitch_torches")  # no salvage row declared

    assert outcome["success"] is False
    assert outcome["produced"] is None
    assert inventory.quantity(state, "birch_resin") == 0
    assert inventory.quantity(state, "pitch_torch") == 0


# ---------------------------------------------------------------------------
# degrees
# ---------------------------------------------------------------------------


def test_a_success_grants_the_declared_output(monkeypatch):
    _force_degree(monkeypatch, "success")
    state = _state()
    inventory.grant(state, "seed_grain", 1)

    outcome = _craft(state, "mill_flour")  # output: 2x barley_flour

    assert outcome["success"] is True
    assert outcome["degree"] == "success"
    assert inventory.quantity(state, "seed_grain") == 0
    assert inventory.quantity(state, "barley_flour") == 2
    assert outcome["produced"]["qty"] == 2


def test_a_critical_success_adds_one_to_the_batch(monkeypatch):
    _force_degree(monkeypatch, "crit_success")
    state = _state()
    inventory.grant(state, "seed_grain", 1)

    outcome = _craft(state, "mill_flour")

    assert inventory.quantity(state, "barley_flour") == 3
    assert outcome["produced"]["qty"] == 3


def test_a_partial_success_wastes_some_of_the_batch(monkeypatch):
    _force_degree(monkeypatch, "partial")
    state = _state(location_id="edgewood_bakery")
    inventory.grant(state, "barley_flour", 1)
    inventory.grant(state, "baking_peel", 1)

    outcome = _craft(state, "bake_loaf")  # output: 4x loaf

    assert outcome["success"] is True
    assert outcome["degree"] == "partial"
    assert inventory.quantity(state, "loaf") == 2, "half the batch, wasted material"
    assert outcome["produced"]["qty"] == 2


def test_a_tool_is_required_but_never_consumed(monkeypatch):
    _force_degree(monkeypatch, "success")
    state = _state(location_id="edgewood_bakery")
    inventory.grant(state, "barley_flour", 1)
    inventory.grant(state, "baking_peel", 1)

    _craft(state, "bake_loaf")

    assert inventory.quantity(state, "baking_peel") == 1


# ---------------------------------------------------------------------------
# receipt shape
# ---------------------------------------------------------------------------


def test_the_receipt_carries_the_whole_arithmetic(monkeypatch):
    _force_degree(monkeypatch, "success")
    state = _state()
    inventory.grant(state, "seed_grain", 1)

    outcome = _craft(state, "mill_flour")

    for key in (
        "success",
        "recipe_id",
        "degree",
        "check",
        "consumed",
        "produced",
        "salvaged",
        "hours",
        "world_day",
        "text",
    ):
        assert key in outcome, f"receipt lost its {key}"
    assert outcome["recipe_id"] == "mill_flour"
    assert outcome["hours"] == 2.0
    assert outcome["check"]["skill"] == "craft"
    assert outcome["consumed"][0]["item_id"] == "seed_grain"
    assert outcome["text"], "the recipe's own line must reach the narrator"


def test_a_real_unforced_craft_resolves_through_the_rules_engine():
    """No mock: the whole path, dice included, on a fixed seed."""
    state = _state()
    inventory.grant(state, "seed_grain", 1)

    outcome = _craft(state, "mill_flour")

    assert outcome["degree"] in ("crit_success", "success", "partial", "failure")
    assert outcome["check"]["dc"] > 0
    # Whatever the roll, the grain is gone and the hours are spent.
    assert inventory.quantity(state, "seed_grain") == 0
    assert state.world_clock_hours >= 2.0


def test_list_recipes_names_only_what_can_be_attempted_here():
    from engine.skills.builtin.mechanics import list_recipes

    state = _state(location_id="forest_clearing")
    with active_engine(GameEngine(state)):
        listing = json.loads(list_recipes())

    ids = {r["id"] for r in listing["recipes"]}
    assert "dry_mushrooms" in ids, "a stationless recipe is attemptable anywhere"
    assert "bake_loaf" not in ids, "a stationed recipe must not be offered elsewhere"


# ---------------------------------------------------------------------------
# the `craft` verb (v0.15.0): the recipe-selection surface
# ---------------------------------------------------------------------------
#
# `craft_item` was a storyteller skill with no intent verb, so no choice could
# reach it (tests/test_reachability.py carried it as "needs a recipe-selection
# surface first"). The verb IS that surface. Its enum is built per turn from
# the recipes craftable right here, right now -- station here (or none), every
# tool held, every input carried -- so an unaffordable recipe is unsamplable,
# and with nothing craftable the verb is absent altogether.

FORGE = "the_forge"
SQUARE = "edgewood_square"
#: Everything `forge_hearth_knife` needs, and nothing that completes any other
#: recipe: the buckler also wants a hide_roll.
KNIFE_KIT = {"whetstone": 1, "leather_apron": 1, "iron_stock": 1, "charcoal_sack": 1}


@pytest.fixture
def flagship():
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


def _packed(location_id: str, kit: dict[str, int]):
    from engine.game.state import GameState

    state = GameState(rng_seed=42, location_id=location_id)
    for item_id, qty in kit.items():
        inventory.grant(state, item_id, qty)
    return state


def _verbs(state) -> dict[str, tuple]:
    from engine.game.intents import legal_intents

    return {v.action: v.targets for v in legal_intents(state)}


def test_at_the_forge_craft_offers_exactly_the_affordable_recipes(flagship) -> None:
    state = _packed(FORGE, KNIFE_KIT)
    assert _verbs(state).get("craft") == ("forge_hearth_knife",)

    inventory.grant(state, "hide_roll", 1)
    assert set(_verbs(state)["craft"]) == {"forge_hearth_knife", "forge_buckler"}


def test_the_craft_label_is_the_recipes_own_name(flagship) -> None:
    from engine.game.intents import describe_intent

    state = _packed(FORGE, KNIFE_KIT)
    label = describe_intent(state, {"action": "craft", "target": "forge_hearth_knife"})
    assert label == "Forge a hearth knife"


def test_a_missing_tool_keeps_a_recipe_out_of_the_enum(flagship) -> None:
    kit = dict(KNIFE_KIT)
    del kit["whetstone"]
    assert "craft" not in _verbs(_packed(FORGE, kit))


def test_elsewhere_the_same_pack_offers_no_craft_verb(flagship) -> None:
    assert "craft" not in _verbs(_packed(SQUARE, KNIFE_KIT))


def test_a_stationless_recipe_is_craftable_wherever_its_inputs_are(flagship) -> None:
    state = _packed(SQUARE, {"wild_mushroom": 5})
    assert _verbs(state).get("craft") == ("dry_mushrooms",)
    state = _packed(SQUARE, {"wild_mushroom": 4})
    assert "craft" not in _verbs(state), "four mushrooms do not make a batch"


def test_craftable_here_is_the_executors_own_notion_of_legal(flagship) -> None:
    """Every enum entry must pass craft_item's refusals -- one rule, not two."""
    from engine.skills.builtin.mechanics import _craft_refusal, _load_recipes, craftable_here

    state = _packed(FORGE, {**KNIFE_KIT, "hide_roll": 1, "wild_mushroom": 5})
    recipes = _load_recipes()
    offered = {rid for rid, _ in craftable_here(state)}
    assert offered == {
        rid for rid, r in recipes.items() if _craft_refusal(state, rid, r) is None
    }
    assert offered == {"forge_hearth_knife", "forge_buckler", "dry_mushrooms"}


def _execute(state, recipe_id: str) -> dict:
    from engine.agents.tool_dispatcher import execute_intent

    receipts = execute_intent({"action": "craft", "target": recipe_id}, GameEngine(state))
    assert len(receipts) == 1, receipts
    return receipts[0]


@pytest.mark.parametrize("degree", ["crit_success", "success", "partial", "failure"])
def test_crafting_through_the_verb_spends_and_yields_by_degree(
    flagship, monkeypatch, degree: str
) -> None:
    from engine.skills.builtin.mechanics import _craft_yield, _load_recipes

    _force_degree(monkeypatch, degree)
    state = _packed(FORGE, KNIFE_KIT)
    hours_before = state.world_clock_hours

    receipt = _execute(state, "forge_hearth_knife")

    assert not receipt.get("refused"), receipt
    assert receipt["skill"] == "craft_item"
    assert receipt["result"]["ok"] is True, "an attempt that happened is not a refusal"
    assert state.world_clock_hours == hours_before + 6.0, "the recipe's six hours"
    assert inventory.quantity(state, "iron_stock") == 0
    assert inventory.quantity(state, "charcoal_sack") == 0
    assert inventory.quantity(state, "whetstone") == 1, "a tool is never consumed"
    assert inventory.quantity(state, "leather_apron") == 1

    expected = _craft_yield(degree, _load_recipes()["forge_hearth_knife"])
    if expected is None:
        assert inventory.quantity(state, "hearth_knife") == 0
        assert receipt["result"]["produced"] is None
    else:
        assert inventory.quantity(state, expected["id"]) == expected["qty"]
        assert receipt["result"]["produced"]["qty"] == expected["qty"]


def test_a_failed_craft_is_narrated_as_an_attempt_not_a_refusal(flagship, monkeypatch) -> None:
    from engine.agents import prompts

    _force_degree(monkeypatch, "failure")
    state = _packed(SQUARE, {"wild_mushroom": 5})
    receipt = _execute(state, "dry_mushrooms")

    assert receipt["success"] is True and not receipt.get("refused"), receipt
    block = prompts.receipts_block([receipt])
    assert "did NOT happen" not in block
    assert "badly" in block


def test_the_craft_line_says_what_was_made_how_well_and_what_was_spent(
    flagship, monkeypatch
) -> None:
    from engine.agents import prompts

    _force_degree(monkeypatch, "success")
    state = _packed(FORGE, KNIFE_KIT)
    receipt = _execute(state, "forge_hearth_knife")

    body = prompts.receipts_block([receipt]).split("\n", 2)[-1]
    assert body.startswith("- "), body
    lowered = body.lower()
    assert "hearth knife" in lowered, "what was made"
    assert "well" in lowered, "how well"
    assert "iron stock" in lowered and "charcoal" in lowered, "what was spent"
    assert "{" not in body and "'" not in body, "no dict dumped at the narrator"
    assert "forge_hearth_knife" not in body and "iron_stock" not in body, "no ids"
    assert not re.search(r"\bdc\b|d20", body, re.IGNORECASE), "no dice arithmetic"


def test_a_salvaged_failure_names_the_salvage(flagship, monkeypatch) -> None:
    from engine.agents import prompts

    _force_degree(monkeypatch, "failure")
    state = _packed(SQUARE, {"wild_mushroom": 5})
    body = prompts.receipts_block([_execute(state, "dry_mushrooms")]).lower()
    assert "salvaged" in body and "wild mushroom" in body


def test_an_input_spent_between_choice_and_execution_is_refused(flagship) -> None:
    from engine.agents import prompts

    state = _packed(FORGE, KNIFE_KIT)
    assert "forge_hearth_knife" in _verbs(state)["craft"], "legal when chosen"
    inventory.take(state, "iron_stock", 1)
    hours_before = state.world_clock_hours

    receipt = _execute(state, "forge_hearth_knife")

    assert receipt["refused"] is True and receipt["success"] is False, receipt
    assert state.world_clock_hours == hours_before, "a refusal costs no time"
    assert inventory.quantity(state, "charcoal_sack") == 1, "a refusal spends nothing"
    assert inventory.quantity(state, "hearth_knife") == 0
    block = prompts.receipts_block([receipt])
    assert "REFUSED" in block and "did NOT happen" in block


def test_leaving_the_station_between_choice_and_execution_is_refused(flagship) -> None:
    state = _packed(FORGE, KNIFE_KIT)
    assert "craft" in _verbs(state)
    state.location_id = SQUARE

    receipt = _execute(state, "forge_hearth_knife")

    assert receipt["refused"] is True, receipt
    assert inventory.quantity(state, "iron_stock") == 1


def test_craft_items_own_refusal_is_scored_as_a_refusal(flagship) -> None:
    """
    The executor's refusals come under ``ok: False`` -- the key the verb's
    REFUSAL_KEY_FOR_ACTION reads. ``success`` is how an attempt WENT (the v0.8
    ``work`` lesson), so it cannot be the refusal key.
    """
    from engine.game.intents import REFUSAL_KEY_FOR_ACTION, declined_reason

    assert REFUSAL_KEY_FOR_ACTION["craft"] == "ok"
    state = _packed(SQUARE, KNIFE_KIT)
    outcome = _craft(state, "forge_hearth_knife")
    assert outcome["ok"] is False
    assert FORGE in declined_reason("craft", outcome)


def test_the_craft_tables_agree() -> None:
    from engine.agents.evaluator import ROLLING_SKILLS
    from engine.game.intents import SKILL_FOR_ACTION, to_tool_call
    from engine.game.state import GameState

    assert SKILL_FOR_ACTION["craft"] == "craft_item"
    assert "craft_item" in ROLLING_SKILLS, "the check is rolled inside the skill"
    assert to_tool_call(GameState(), {"action": "craft", "target": "bake_loaf"}) == (
        "craft_item",
        {"recipe_id": "bake_loaf"},
    )


# -- where nothing is craftable, nothing moves --------------------------------


def _surface(state) -> tuple:
    from engine.agents import prompts
    from engine.game.intents import legal_intents
    from engine.lmstudio.schemas import storyteller_turn_schema

    verbs = legal_intents(state)
    return (
        verbs,
        prompts._intents_block(state),
        json.dumps(storyteller_turn_schema(intents=verbs), sort_keys=True),
    )


#: HUE & CRY left this list in v0.15 when it declared the Porters' Hall bench;
#: its nothing-craftable surfaces are held below, like the flagship's.
OTHER_STORIES = ["wicked-garden", "neon-city", "the-long-con", "dev-story"]


@pytest.mark.parametrize("slug", OTHER_STORIES)
def test_a_story_without_recipes_is_byte_identical(slug: str, monkeypatch) -> None:
    from engine.game import intents
    from engine.games import registry
    from engine.skills.builtin import mechanics

    manifest = registry.activate(slug)
    try:
        assert not mechanics._load_recipes(), f"{slug} declares no recipes"
        state = _packed(manifest.entry_location, KNIFE_KIT)
        assert "craft" not in _verbs(state)
        before = _surface(state)
        monkeypatch.setattr(intents, "_craft", lambda s: None)
        assert _surface(state) == before
    finally:
        registry.deactivate()


@pytest.mark.parametrize(
    "location_id, kit",
    [
        (SQUARE, KNIFE_KIT),  # the right pack, away from the forge
        (FORGE, {}),  # the forge, with nothing to work
        ("forest_clearing", {"road_bread": 2, "walking_staff": 1}),  # a new run's pack
    ],
    ids=["pack-away-from-station", "station-empty-handed", "opening-pack"],
)
def test_the_flagship_with_nothing_craftable_is_byte_identical(
    flagship, monkeypatch, location_id: str, kit: dict[str, int]
) -> None:
    from engine.game import intents

    state = _packed(location_id, kit)
    assert "craft" not in _verbs(state)
    before = _surface(state)
    monkeypatch.setattr(intents, "_craft", lambda s: None)
    assert _surface(state) == before


@pytest.mark.parametrize(
    "location_id, kit",
    [
        ("tallow_docks", {}),  # a new run: off the barge with nothing
        ("the_snuffs", {}),  # the Porters' Hall, empty-handed
        ("wickmarket", {"bent_wire": 1, "file_tang": 1}),  # the makings, off the bench
    ],
    ids=["opening", "bench-empty-handed", "makings-away-from-bench"],
)
def test_hue_and_cry_with_nothing_craftable_is_byte_identical(
    monkeypatch, location_id: str, kit: dict[str, int]
) -> None:
    """v0.15 declared HUE & CRY's recipes; wherever nothing can be made its
    turns are the ones it had before (the verb is absent, not empty)."""
    from engine.game import intents
    from engine.games import registry

    registry.activate("hue-and-cry")
    try:
        state = _packed(location_id, kit)
        assert "craft" not in _verbs(state)
        before = _surface(state)
        monkeypatch.setattr(intents, "_craft", lambda s: None)
        assert _surface(state) == before
    finally:
        registry.deactivate()


# ---------------------------------------------------------------------------
# the recipe memo: parsed once, reloaded on an edit or a story switch
# ---------------------------------------------------------------------------


def _count_parses(monkeypatch) -> list[int]:
    """Count the YAML parses of recipe files (one per file per parse)."""
    from engine.skills.builtin import mechanics

    calls = [0]
    real = mechanics.yaml.safe_load

    def counting(stream):
        if "recipes" in str(getattr(stream, "name", "")):
            calls[0] += 1
        return real(stream)

    monkeypatch.setattr(mechanics.yaml, "safe_load", counting)
    return calls


def test_the_recipes_are_parsed_once_across_repeated_calls(monkeypatch) -> None:
    """``legal_intents`` builds the ``craft`` verb 3-4 times a turn; each
    build used to re-parse every recipe file (~30 ms for the flagship's)."""
    from engine.skills.builtin import mechanics

    calls = _count_parses(monkeypatch)
    first = mechanics._load_recipes()
    assert first, "the flagship declares recipes"
    parsed = calls[0]
    assert parsed >= 1
    state = _state()
    for _ in range(5):
        assert mechanics._load_recipes() == first
        craftable_here_result = mechanics.craftable_here(state)
        assert isinstance(craftable_here_result, list)
    assert calls[0] == parsed, "the recipe files were parsed again"


def test_a_recipe_edit_reloads_the_memo(monkeypatch, tmp_path) -> None:
    import os

    from engine.skills.builtin import mechanics

    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    book = recipes_dir / "book.yaml"
    book.write_text("recipes:\n  - id: first_thing\n    name: First\n", encoding="utf-8")

    class _Config:
        def get(self, key, default=None):
            return "recipes" if key == "paths.recipes" else default

    monkeypatch.setattr(mechanics, "_ROOT", tmp_path)
    monkeypatch.setattr(mechanics, "get_config", lambda: _Config())

    assert set(mechanics._load_recipes()) == {"first_thing"}
    book.write_text("recipes:\n  - id: second_thing\n    name: Second\n", encoding="utf-8")
    stamp = book.stat().st_mtime_ns + 5_000_000_000
    os.utime(book, ns=(stamp, stamp))
    assert set(mechanics._load_recipes()) == {"second_thing"}

    # A new file in the directory is an edit too.
    (recipes_dir / "more.yaml").write_text(
        "recipes:\n  - id: third_thing\n", encoding="utf-8"
    )
    assert set(mechanics._load_recipes()) == {"second_thing", "third_thing"}


def test_a_story_switch_reloads_the_recipe_memo(monkeypatch) -> None:
    from engine.games import registry
    from engine.skills.builtin import mechanics

    flagship = set(mechanics._load_recipes())
    registry.activate("hue-and-cry")
    try:
        city = set(mechanics._load_recipes())
    finally:
        registry.deactivate()
    assert city and city != flagship
    assert set(mechanics._load_recipes()) == flagship


def test_the_recipe_memo_is_dropped_between_tests() -> None:
    """``tests/conftest.py::_content_caches_are_per_test`` nulls
    ``NULLED_ATTRIBUTES``; the memo must be one of them."""
    from engine.games.caches import NULLED_ATTRIBUTES

    assert ("engine.skills.builtin.mechanics", "_RECIPE_CACHE") in NULLED_ATTRIBUTES


def test_a_repointed_recipe_dir_reloads_the_memo(monkeypatch, tmp_path) -> None:
    """The directory is part of the key, not only the file names and mtimes:
    two stories' ``book.yaml`` stamped alike must not share one parse, even
    with no activation between them to null the memo."""
    import os

    from engine.skills.builtin import mechanics

    for story, recipe in (("a", "from_a"), ("b", "from_b")):
        (tmp_path / story).mkdir()
        book = tmp_path / story / "book.yaml"
        book.write_text(f"recipes:\n  - id: {recipe}\n", encoding="utf-8")
        os.utime(book, ns=(1_700_000_000_000_000_000,) * 2)

    where = {"paths.recipes": "a"}

    class _Config:
        def get(self, key, default=None):
            return where.get(key, default)

    monkeypatch.setattr(mechanics, "_ROOT", tmp_path)
    monkeypatch.setattr(mechanics, "get_config", lambda: _Config())

    assert set(mechanics._load_recipes()) == {"from_a"}
    where["paths.recipes"] = "b"
    assert set(mechanics._load_recipes()) == {"from_b"}

"""
Progress clocks, threads, ending eligibility, deck-drawn scenes, per-beat gates.

The five capabilities a structurally different second story needs, built as
ENGINE FEATURES CONFIGURED BY DATA rather than as a second story's code. So the
thing these tests have to prove is not "the Wicked Garden works" -- it is:

  * the flagship is untouched. Every system is INERT with no declaration, and
    the whole point of the exercise is that adding them cost The Clockwork Dark
    nothing. Asserted first, because it is the property most easily lost.
  * nothing hardcodes a story's nouns. The suite drives the real loaders against
    ``games/wicked-garden/``'s shipped rules, using a schema the engine has
    never seen -- everything bag-backed, no typed field anywhere.
  * the invariants hold under the new code: one writer, seeded replay, honest
    eligibility, no softlock.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.challenges import spec as spec_module
from engine.config import set_overlay
from engine.content import deck as deck_module
from engine.game import clocks, effects, endings, threads
from engine.game.state import GameState, InventoryItem
from engine.state import active as active_state
from engine.state.schema import load_schema

# The REAL story, not a fixture beside it.
#
# These files began life as worked examples under data/rules/examples/, because
# the game they described did not exist yet. It does now, so they moved into it
# and this points at the shipped article. That is strictly stronger: a test
# driving a copy proves the loaders work on a copy, and the copy is free to
# drift from the thing that actually ships.
GARDEN = "games/wicked-garden"
GARDEN_RULES = f"{GARDEN}/data/rules"
GARDEN_SCHEMA = Path(GARDEN) / "state.yaml"


def _garden_paths() -> dict[str, str]:
    """
    The Garden's own ``paths:``, read from the manifest that ships them.

    These used to be four string literals in the fixture below. When the day
    decks moved directory the manifest was updated and the literal was not, so
    thirteen tests went on loading a path that no longer existed -- they failed
    loudly here, but the same drift in the other direction (test literal still
    valid, manifest wrong) would have passed while the game shipped broken.
    A test that hardcodes what the manifest owns is not testing the manifest.
    """
    from engine.games.registry import discover

    manifest = discover()["wicked-garden"]
    return {key: manifest.paths[key] for key in ("clocks", "threads", "endings", "decks")}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def garden() -> Iterator[GameState]:
    """
    A story the engine has never heard of, fully wired.

    Points every new ``paths.*`` key at The Wicked Garden's shipped rules and
    installs its bag-backed schema, then puts both back. Deliberately uses the
    real loaders and the real files rather than fixtures written to pass: a
    shape that only works against a fixture invented for it has proved nothing,
    and a fixture is free to drift from the story that ships.
    """
    set_overlay({"paths": _garden_paths()})
    active_state._schema = load_schema(GARDEN_SCHEMA, slug="wicked-garden")
    state = GameState(rng_seed=42)
    try:
        yield state
    finally:
        active_state.reset_schema()
        set_overlay(None)


def _set(state: GameState, name: str, value: float) -> None:
    """Move a declared value to an exact number, through the one writer."""
    effects.apply_effect(state, {"type": "value", "name": name, "set": value})


# ---------------------------------------------------------------------------
# The flagship is untouched
# ---------------------------------------------------------------------------


def test_every_system_is_inert_without_a_declaration() -> None:
    """
    The Clockwork Dark declares no clocks, threads, endings or decks.

    This is the compatibility bar and it is why the simulator output is
    unchanged: a story that says nothing gets an empty table from every loader,
    and an empty table is a system that does not run.
    """
    assert clocks.load_clocks() == {}
    assert threads.templates() == {}
    assert endings.declared() == {}
    assert deck_module.deck_ids() == []

    state = GameState()
    assert clocks.resolve(state) == []
    assert threads.active(state) == []
    assert endings.eligible(state).eligible == []
    assert clocks.forced_scenes(state) == []


def test_a_story_with_no_endings_cannot_softlock_its_finale() -> None:
    """No declared endings means no finale to lock, not a finale with no exit."""
    report = endings.eligible(GameState())
    assert report.eligible == []
    assert report.fail_forward == ""
    assert endings.resolve(GameState()) == ""


# ---------------------------------------------------------------------------
# 1. Effect kinds are registrable; ceilings derive from the schema
# ---------------------------------------------------------------------------


def test_the_fourteen_original_kinds_are_still_registered() -> None:
    """The chain became a registry. Nothing about the flagship's kinds moved."""
    for kind in (
        "stat", "hp", "stamina", "focus", "craft", "gold", "hunger", "awareness",
        "reputation", "item", "remove_item", "wound", "heal_wound",
        "clear_condition", "equip", "unequip", "check_penalty", "flag",
        "ledger_fact",
    ):
        assert kind in effects.registered_kinds()


def test_a_registered_kind_wins_over_a_declared_value(garden: GameState) -> None:
    """
    Sugar must never shadow a handler.

    ``hunger`` is both a registered kind and, in some story, a plausible meter
    name. The registry resolves first, so adding a schema can never silently
    redirect an existing effect somewhere new.
    """
    before = garden.hunger
    effects.apply_effect(garden, {"type": "hunger", "delta": 5})
    assert garden.hunger == before + 5


def test_a_declared_value_is_reachable_by_bare_type(garden: GameState) -> None:
    """``{type: favor, delta: 8}`` -- the shape a content author reaches for."""
    receipt = effects.apply_effect(garden, {"type": "favor", "delta": 8})
    assert receipt["ok"] is True
    assert receipt["type"] == "value"
    assert receipt["after"] == 23  # default 15


def test_an_undeclared_name_is_still_unknown(garden: GameState) -> None:
    """The fallback must not turn a typo into a silent write."""
    receipt = effects.apply_effect(garden, {"type": "favour", "delta": 8})
    assert receipt["ok"] is False


def test_writes_clamp_to_the_declared_bounds(garden: GameState) -> None:
    effects.apply_effect(garden, {"type": "value", "name": "favor", "delta": 500})
    assert garden.meters["favor"] == 100


def test_the_owners_acl_is_enforced_through_the_dispatcher(garden: GameState) -> None:
    """
    ``by=`` reaches StateStore, so a refusal is a refusal AND a journal entry.

    Without this the ACL existed but nothing in the effect path could invoke it,
    which is the same as not having one.
    """
    refused = effects.apply_effect(
        garden, {"type": "value", "name": "corruption", "delta": 5}, by="sophia"
    )
    assert refused["ok"] is False
    assert garden.meters.get("corruption", 5) == 5

    allowed = effects.apply_effect(
        garden, {"type": "value", "name": "favor", "delta": 5}, by="sophia"
    )
    assert allowed["ok"] is True


def test_a_veiled_value_reports_its_visibility_in_the_receipt(garden: GameState) -> None:
    """A caller has to be told before it puts the number in front of a player."""
    receipt = effects.apply_effect(garden, {"type": "value", "name": "favor", "delta": 1})
    assert receipt["visibility"] == "veiled"


def test_challenge_ceilings_derive_from_the_running_story(garden: GameState) -> None:
    """
    A 0-100 meter and a 0-5 clock get proportional ceilings, from their own scale.

    The old hardcoded list meant a challenge in this story could not touch a
    single one of its meters -- every one would have been dropped as a
    disallowed type before reaching the dispatcher.
    """
    from engine.challenges import spec as spec_module

    ceilings = spec_module.effect_ceilings()
    assert ceilings["favor"] == 17          # 100 / 6, rounded
    assert ceilings["briar_hunger"] == 1    # a scene may tick a clock once
    assert ceilings["time_debt_mortal_days"] == spec_module.DEFAULT_UNBOUNDED_CEILING
    assert "favor" in spec_module.allowed_effect_types()


def test_the_engines_own_balance_numbers_still_win() -> None:
    """
    Gold is 25 because of data/economy.yaml, not because of a min/max pair.

    The base table is the floor under the derivation, not a thing it replaces.
    """
    from engine.challenges import spec as spec_module

    assert spec_module.effect_ceilings()["gold"] == spec_module.EFFECT_CEILINGS["gold"] == 25


def test_a_challenge_may_adjust_a_meter_but_never_set_one(garden: GameState) -> None:
    """`set:` would let a model write favor = 100 instead of moving it by 17."""
    from engine.challenges import spec as spec_module

    adjustments: list[str] = []
    out = spec_module.clamp_outcome(
        {"effects": [{"type": "value", "name": "favor", "delta": 900, "set": 100}]},
        adjustments,
    )
    assert out["effects"][0]["delta"] == 17
    assert "set" not in out["effects"][0]
    assert any("set" in a for a in adjustments)


# ---------------------------------------------------------------------------
# 2. Progress clocks
# ---------------------------------------------------------------------------


def test_a_clock_beat_fires_at_its_threshold_and_only_once(garden: GameState) -> None:
    _set(garden, "briar_hunger", 2)
    first = clocks.resolve(garden)
    assert any(r["value"] == "root_crypts" for r in first)
    assert garden.flags["discovery_root_crypts"] is True

    # Idempotency is owned below the caller: firing again applies nothing.
    assert clocks.resolve(garden) == []


def test_beats_fire_in_threshold_order_when_several_are_crossed_at_once(
    garden: GameState,
) -> None:
    """Normal after a load or a clock slammed several segments by one scene."""
    _set(garden, "briar_hunger", 5)
    clocks.resolve(garden)
    assert garden.flags.get("briar_heartbeat_heard") is True
    assert garden.flags.get("briar_finale_pending") is True


def test_a_full_clock_forces_a_setpiece(garden: GameState) -> None:
    """
    The whole difference between a clock and a meter.

    Recorded on the world ledger with a permanent horizon, because
    ``WorldSim.expire_events`` deletes anything with no ``expires_day``.
    """
    _set(garden, "briar_hunger", 5)
    clocks.resolve(garden)

    assert clocks.forced_scenes(garden) == ["briar_threshold"]
    entry = next(e for e in garden.world_events if e.get("forces_scene"))
    assert entry["expires_day"] == clocks.PERMANENT_HORIZON_DAY

    clocks.mark_scene_played(garden, "briar_threshold")
    assert clocks.forced_scenes(garden) == []


def test_a_beat_may_be_gated_on_more_than_its_number(garden: GameState) -> None:
    """``ashen_pressure`` only collects when something is actually owed."""
    _set(garden, "ashen_pressure", 5)
    assert clocks.resolve(garden) == []
    assert clocks.forced_scenes(garden) == []

    proposal = threads.offer(garden, "ashen_service_owed", source="ashen_vale")
    threads.seal(garden, proposal)
    clocks.resolve(garden)
    assert clocks.forced_scenes(garden) == ["ashen_collects"]


def test_a_recurring_clock_empties_and_refills(garden: GameState) -> None:
    """``reset_to`` -- a rival who runs out of patience once is a cutscene."""
    threads.seal(garden, threads.offer(garden, "ashen_service_owed", source="ashen_vale"))
    _set(garden, "ashen_pressure", 5)
    clocks.resolve(garden)
    assert clocks.value_of(garden, "ashen_pressure") == 0


def test_engine_side_pressure_winds_a_clock_and_fires_it_the_same_turn(
    garden: GameState,
) -> None:
    """
    A setpiece arriving a turn after its cause reads as unrelated.

    ``advance_when`` runs before the beat scan for exactly this reason.
    """
    _set(garden, "time_debt_mortal_days", 120)
    clocks.resolve(garden)
    assert clocks.value_of(garden, "mortal_collapse") == 5
    assert "empty_rooms" in clocks.forced_scenes(garden)


def test_auto_advance_fires_once_not_every_turn(garden: GameState) -> None:
    _set(garden, "corruption", 70)
    clocks.resolve(garden)
    after_first = clocks.value_of(garden, "briar_hunger")
    clocks.resolve(garden)
    assert clocks.value_of(garden, "briar_hunger") == after_first


def test_advance_reports_whether_it_just_filled(garden: GameState) -> None:
    _set(garden, "briar_hunger", 4)
    assert clocks.advance(garden, "briar_hunger", 1)["full"] is True


def test_the_doom_track_still_works_on_the_shared_engine() -> None:
    """
    world_effects now calls clocks.apply_mutations rather than its own copy.

    The doom beats are the flagship's, and they must land exactly as before --
    same flags, same rumours, same permanent world marks, same ``doom`` source
    tag that DoomSignsInterceptor filters on.
    """
    from engine.world import world_effects

    table = world_effects.load_doom_effects()
    assert table, "the flagship ships doom beats; this test is meaningless without them"

    state = GameState()
    state.evil_progress = 1.0
    applied = world_effects.apply_pending_beats(state)
    assert applied
    assert world_effects.apply_pending_beats(state) == []
    assert all(
        e["source"] == "doom"
        for e in state.world_events
        if e.get("beat")
    )


# ---------------------------------------------------------------------------
# 3. Threads
# ---------------------------------------------------------------------------


def test_offer_writes_nothing_until_it_is_sealed(garden: GameState) -> None:
    """"She offered and you walked away" must not equal "you agreed"."""
    proposal = threads.offer(garden, "obligation_gift", source="sophia")
    assert proposal is not None
    assert garden.threads == []
    assert garden.meters.get("favor", 15) == 15

    threads.seal(garden, proposal)
    assert len(threads.active(garden)) == 1
    assert garden.meters["favor"] == 21


def test_terms_offer_the_renegotiations_before_the_seal(garden: GameState) -> None:
    """Terms is its own step: the page the player reads before deciding."""
    terms = threads.terms_of(threads.offer(garden, "obligation_gift", source="sophia"))
    assert {r["id"] for r in terms["renegotiations"]} == {
        "costly_gift",
        "service_named",
        "refuse",
    }


def test_renegotiate_produces_a_different_contract_not_a_discount(
    garden: GameState,
) -> None:
    """
    The design claim, asserted.

    Different terms, different tags, different effects, different due date --
    and the negotiation is on the record.
    """
    base = threads.offer(garden, "obligation_gift", source="sophia")
    better = threads.renegotiate(garden, base, "costly_gift")

    assert better is not None
    assert better.terms != base.terms
    assert better.tags != base.tags
    assert better.due_in_days != base.due_in_days
    assert better.negotiated == ["costly_gift"]

    threads.seal(garden, better)
    assert garden.meters["knowledge"] == 8
    thread = threads.active(garden)[0]
    assert thread["negotiated"] == ["costly_gift"]
    assert "Knowledge" in thread["tags"]


def test_renegotiating_into_no_contract_is_a_real_outcome(garden: GameState) -> None:
    """Refusing well is a move. It costs and earns things; it just has no thread."""
    base = threads.offer(garden, "obligation_gift", source="sophia")
    refusal = threads.renegotiate(garden, base, "refuse")
    assert refusal is not None

    result = threads.seal(garden, refusal)
    assert result["ok"] is False
    assert result["outcome"] == threads.OUTCOME_NONE
    assert garden.threads == []
    assert garden.meters["autonomy"] == 76
    assert garden.meters["favor"] == 7


def test_renegotiation_can_be_gated_and_is_refused_not_granted(
    garden: GameState,
) -> None:
    """"She will discuss it with someone who has read the laws" is a mechanic."""
    _set(garden, "autonomy", 10)
    base = threads.offer(garden, "obligation_gift", source="sophia")
    assert threads.renegotiate(garden, base, "costly_gift") is None


def test_accepting_a_gift_without_negotiating_creates_an_obligation(
    garden: GameState,
) -> None:
    """A rule of the fiction that lives only in a prompt is not a rule."""
    result = threads.accept_gift(garden, "living_silk", from_id="sophia")

    assert result["obligated"] is True
    assert len(threads.active(garden)) == 1
    assert any(i.id == "living_silk" for i in garden.inventory)
    # The gift is bound to the contract it came with.
    assert threads.item_threads(garden, "living_silk") == [result["thread"]["id"]]


def test_asking_the_price_first_costs_the_gift_no_obligation(garden: GameState) -> None:
    result = threads.accept_gift(garden, "kiss_petal", from_id="sophia", negotiated=True)
    assert result["obligated"] is False
    assert threads.active(garden) == []
    assert any(i.id == "kiss_petal" for i in garden.inventory)


def test_a_thread_carries_its_own_outcome_effects(garden: GameState) -> None:
    """
    A transformed contract must not break with the ORIGINAL's penalty.

    That distinction is the entire reason renegotiate exists, so resolution
    reads the thread and never re-reads the template.
    """
    threads.seal(garden, threads.offer(garden, "obligation_gift", source="sophia"))
    thread_id = threads.active(garden)[0]["id"]
    threads.transform(garden, thread_id, "costly_gift")

    new_id = threads.active(garden)[0]["id"]
    favor_before = garden.meters["favor"]
    threads.break_thread(garden, new_id)
    # -6 from the variant, not -12 from the template it grew out of.
    assert garden.meters["favor"] == favor_before - 6


def test_transform_ends_the_old_thread_without_paying_or_reneging(
    garden: GameState,
) -> None:
    """The fourth lifecycle state exists because this is a real thing."""
    _set(garden, "knowledge", 30)  # service_named's own gate
    threads.seal(garden, threads.offer(garden, "obligation_gift", source="sophia"))
    old_id = threads.active(garden)[0]["id"]
    result = threads.transform(garden, old_id, "service_named")

    assert result["ok"] is True
    assert threads.get(garden, old_id)["status"] == threads.STATUS_TRANSFORMED
    assert result["thread"]["parent_id"] == old_id
    assert len(threads.active(garden)) == 1


def test_bound_items_follow_a_transformed_contract(garden: GameState) -> None:
    """A collar bound to the obligation you renegotiated is still around your neck."""
    _set(garden, "knowledge", 30)
    accepted = threads.accept_gift(garden, "collar_soft_thorns", from_id="sophia")
    result = threads.transform(garden, accepted["thread"]["id"], "service_named")
    assert threads.item_threads(garden, "collar_soft_thorns")[-1] == result["thread"]["id"]


def test_cutting_a_thread_breaks_it_and_costs_the_break_price(
    garden: GameState,
) -> None:
    """A knife that freed you for nothing would make every bargain optional."""
    threads.seal(garden, threads.offer(garden, "obligation_gift", source="sophia"))
    thread_id = threads.active(garden)[0]["id"]
    garden.inventory.append(InventoryItem(id="mirror_glass_knife", name="mirror-glass knife"))

    favor_before = garden.meters["favor"]
    result = threads.cut(garden, thread_id, using="mirror_glass_knife")

    assert result["ok"] is True
    assert threads.get(garden, thread_id)["status"] == threads.STATUS_BROKEN
    assert garden.meters["favor"] == favor_before - 12
    # A glass knife is spent on the bargain it cuts.
    assert not any(i.id == "mirror_glass_knife" for i in garden.inventory)


def test_cutting_cascades_to_the_item_the_thread_was_bound_to(
    garden: GameState,
) -> None:
    """The collar IS the bargain; severing it leaves you holding nothing."""
    accepted = threads.accept_gift(garden, "collar_soft_thorns", from_id="sophia")
    garden.inventory.append(InventoryItem(id="mirror_glass_knife", name="knife"))

    threads.cut(garden, accepted["thread"]["id"], using="mirror_glass_knife")
    assert not any(i.id == "collar_soft_thorns" for i in garden.inventory)


def test_cutting_the_item_cuts_the_thread_the_other_way(garden: GameState) -> None:
    accepted = threads.accept_gift(garden, "collar_soft_thorns", from_id="sophia")
    garden.inventory.append(InventoryItem(id="mirror_glass_knife", name="knife"))

    threads.cut_item(garden, "collar_soft_thorns", using="mirror_glass_knife")
    assert threads.get(garden, accepted["thread"]["id"])["status"] == threads.STATUS_BROKEN


def test_a_cutter_the_thread_does_not_name_is_refused_with_a_reason(
    garden: GameState,
) -> None:
    """Being told a knife will not cut this, and not why, is not being told."""
    threads.seal(garden, threads.offer(garden, "obligation_gift", source="sophia"))
    thread_id = threads.active(garden)[0]["id"]

    ok, reason = threads.can_cut(garden, thread_id, "law")
    assert ok is False and "does not cut" in reason


def test_a_law_cannot_be_invoked_by_someone_who_has_not_read_it(
    garden: GameState,
) -> None:
    """The cutter's own ``requires`` gate, from the shared grammar."""
    threads.seal(garden, threads.offer(garden, "ashen_service_owed", source="ashen_vale"))
    thread_id = threads.active(garden)[0]["id"]

    ok, reason = threads.can_cut(garden, thread_id, "law")
    assert ok is False and "half-remembered" in reason

    _set(garden, "knowledge", 40)
    assert threads.can_cut(garden, thread_id, "law")[0] is True


def test_an_undeclared_cutter_never_works(garden: GameState) -> None:
    """
    A contract must not advertise an escape route the world never built.

    Bounded when the offer is built AND checked again at the cut, because a
    thread can reach the cut without passing through ``offer`` -- loaded from a
    save written against a different rules file, most obviously.
    """
    proposal = threads.offer(garden, "obligation_gift", source="sophia")
    proposal.can_cut_with.append("wishing")
    threads.seal(garden, proposal)

    thread_id = threads.active(garden)[0]["id"]
    ok, reason = threads.can_cut(garden, thread_id, "wishing")
    assert ok is False and "not a thing that cuts" in reason


def test_a_cutter_outside_the_vocabulary_is_dropped_when_the_offer_is_built(
    garden: GameState,
) -> None:
    from engine.game.threads import _bound_cutters

    adjustments: list[str] = []
    assert _bound_cutters(["law", "wishing"], adjustments) == ["law"]
    assert adjustments


def test_a_thread_that_comes_due_unpaid_breaks(garden: GameState) -> None:
    """Silence is an answer too -- the shape StoryLedger.expire_promises has."""
    threads.seal(garden, threads.offer(garden, "obligation_gift", source="sophia"))
    thread_id = threads.active(garden)[0]["id"]

    garden.world_clock_hours += 24 * 40
    broken = threads.expire_due(garden)
    assert len(broken) == 1
    assert threads.get(garden, thread_id)["status"] == threads.STATUS_BROKEN


def test_an_arbitrary_cut_replays_from_the_seed(garden: GameState) -> None:
    """
    The mirror scene severs "a random bargain". Random, not unreproducible.

    Drawn from ``world_rng(state, THREAD)``: a bug report about the wrong thread
    being cut has to be actionable.
    """

    def run() -> str:
        set_overlay(
            {"paths": {"threads": f"{GARDEN_RULES}/threads.yaml", "endings": f"{GARDEN_RULES}/endings.yaml"}}
        )
        state = GameState(rng_seed=99)
        state.inventory.append(InventoryItem(id="mirror_glass_knife", name="knife"))
        for template in ("obligation_gift", "obligation_gift", "obligation_gift"):
            threads.seal(state, threads.offer(state, template, source="sophia"))
        return threads.cut_arbitrary(state, using="mirror_glass_knife")["thread"]["id"]

    assert run() == run()


def test_threads_mirror_into_the_ledger_as_promises(garden: GameState) -> None:
    """
    Built on ``Promise``, not beside it.

    A promise IS a thread with no tags and no way to be cut, so the memory layer
    keeps working on promises exactly as it does today while the thread carries
    the mechanical half.
    """
    from engine.memory.ledger import StoryLedger

    ledger = StoryLedger()
    threads.seal(
        garden, threads.offer(garden, "obligation_gift", source="sophia"), ledger=ledger
    )
    assert len(ledger.open_promises()) == 1
    assert "sophia" in ledger.relations

    threads.discharge(garden, threads.active(garden)[0]["id"], ledger=ledger)
    assert ledger.promises[0].status == "kept"


def test_a_thread_predicate_answers_the_finale_collision_table(
    garden: GameState,
) -> None:
    """``DAY-09-FINALE.md`` F2 is written entirely in terms of what is still live."""
    from engine.game.quests import evaluate_condition

    condition = {"thread": {"source": "ashen_vale", "status": "active"}}
    assert evaluate_condition(garden, condition) is False

    threads.seal(garden, threads.offer(garden, "ashen_service_owed", source="ashen_vale"))
    assert evaluate_condition(garden, condition) is True
    assert evaluate_condition(garden, {"no_thread": {"tag": "Service"}}) is False


# ---------------------------------------------------------------------------
# 4. Ending eligibility
# ---------------------------------------------------------------------------


def test_the_fail_forward_carries_a_state_that_qualifies_for_nothing(
    garden: GameState,
) -> None:
    """
    ``DAY-09-FINALE.md``: "never softlock title".

    And it is in the set because the story DECLARED it, flagged as forced, so a
    UI can tell "you earned this" from "this is what is left".
    """
    report = endings.eligible(garden)
    assert report.eligible == ["E4e"]
    assert report.forced is True
    assert endings.resolve(garden) == "E4e"


def test_eligibility_is_earned_by_meeting_the_declared_gate(garden: GameState) -> None:
    _set(garden, "autonomy", 60)
    _set(garden, "knowledge", 45)
    garden.flags["sophia_will_discuss_leave"] = True

    report = endings.eligible(garden)
    assert "E1a" in report.eligible
    assert report.forced is False


def test_an_ending_that_cannot_complete_is_never_offered(garden: GameState) -> None:
    """
    THE HONESTY REQUIREMENT (DAY-08-MIRRORS.md:182).

    E1a's gate is met in full. She cannot let you go tenderly while the roots
    are taking her Garden, so it is locked -- and the lock reason says which of
    the two halves failed, because "you have not earned it" and "something is in
    the way" are different problems with different remaining moves.
    """
    _set(garden, "autonomy", 60)
    _set(garden, "knowledge", 45)
    garden.flags["sophia_will_discuss_leave"] = True
    _set(garden, "briar_hunger", 5)

    report = endings.eligible(garden)
    assert "E1a" not in report.eligible
    assert any(r.startswith("cannot complete") for r in report.locked["E1a"])


def test_lock_reasons_are_the_storys_prose_not_a_rendered_dict(
    garden: GameState,
) -> None:
    """The mirror pool shows silhouettes with reasons; the reasons are authored."""
    reasons = endings.eligible(garden).locked["E2a"]
    assert "She is fond of you. Fond is not equal." in reasons


def test_a_variant_inherits_its_class_gate(garden: GameState) -> None:
    """E2b is "E2, plus you abandoned the Seat" -- not four clauses restated."""
    garden.flags["abandon_seat"] = True
    assert "E2b" not in endings.eligible(garden).eligible

    _set(garden, "favor", 80)
    _set(garden, "autonomy", 60)
    _set(garden, "equality_seed", 3)
    assert "E2b" in endings.eligible(garden).eligible


def test_scores_are_continuous_and_computed_for_ineligible_endings(
    garden: GameState,
) -> None:
    """
    The whole point of a score is to foreshadow what is NOT yet available.

    An omen that only appeared once you already qualified would be a receipt.
    """
    report = endings.eligible(garden)
    assert "E2a" in report.scores and "E2a" not in report.eligible

    _set(garden, "favor", 90)
    _set(garden, "autonomy", 90)
    hotter = endings.eligible(garden)
    assert hotter.scores["E2a"] > report.scores["E2a"]
    assert 0.0 <= hotter.scores["E2a"] <= 1.0


def test_intent_is_soft_and_refused_when_the_card_cannot_complete(
    garden: GameState,
) -> None:
    """
    Swearing toward an impossible card is worse at Day 8 than at Day 9.

    The player then spends a whole day preparing for it.
    """
    refused = endings.set_intent(garden, "E5a")
    assert refused["ok"] is False
    assert refused["reasons"]
    assert endings.intent(garden) == endings.NONE_ID


def test_swearing_an_intent_closes_its_opposites(garden: GameState) -> None:
    """Swearing is powerful; looking only is valid. So swearing has to cost."""
    _set(garden, "autonomy", 60)
    _set(garden, "knowledge", 45)
    garden.flags["sophia_will_discuss_leave"] = True

    receipt = endings.set_intent(garden, "E1a")
    assert receipt["ok"] is True
    assert endings.intent(garden) == "E1a"
    assert garden.flags["ending_closed_E3a"] is True


def test_lock_is_hard_and_happens_once(garden: GameState) -> None:
    """"Irreversible" is the tone the whole day is written in."""
    assert endings.lock(garden, "E4e")["ok"] is True
    assert endings.locked(garden) == "E4e"
    assert endings.lock(garden, "E4b")["ok"] is False
    assert endings.locked(garden) == "E4e"


def test_resolve_prefers_lock_then_intent_then_the_best_eligible(
    garden: GameState,
) -> None:
    """No branch returns nothing; a resolver that can is a softlock waiting."""
    _set(garden, "autonomy", 60)
    _set(garden, "knowledge", 45)
    garden.flags["sophia_will_discuss_leave"] = True

    assert endings.resolve(garden) in endings.eligible(garden).eligible

    endings.set_intent(garden, "E1a")
    assert endings.resolve(garden) == "E1a"

    # A lock overrides an intent. The player who swore the door and then walked
    # into the roots gets the roots.
    assert endings.lock(garden, "E4e")["ok"] is True
    assert endings.resolve(garden) == "E4e"


def test_recompute_commits_the_list_so_the_finale_can_read_it(
    garden: GameState,
) -> None:
    """``DAY-09-FINALE.md`` takes ``eligible_endings[]`` as its prerequisite."""
    report = endings.recompute(garden)
    assert garden.tracks[endings.TRACK_ELIGIBLE] == report.eligible
    assert garden.tracks[endings.TRACK_SCORES] == report.scores


def test_the_ending_tracks_are_written_through_the_dispatcher(
    garden: GameState,
) -> None:
    """
    CLAUDE.md rule 3, for enum-valued state.

    ``StateStore`` is numeric by construction and ``flags`` is boolean, so
    without a ``track`` effect kind these would be written by reaching into
    ``state.tracks`` from wherever was convenient -- the second writer the
    dispatcher exists to prevent.
    """
    receipt = effects.apply_effect(
        garden,
        {"type": "track", "name": endings.TRACK_INTENT, "value": "E9z", "allowed": ["E4e"]},
    )
    assert receipt["ok"] is False
    assert endings.intent(garden) == endings.NONE_ID


def test_the_ending_predicate_lets_a_scene_read_the_finale_state(
    garden: GameState,
) -> None:
    """``DAY-08-MIRRORS.md``'s night-before table, as data instead of a branch."""
    from engine.game.quests import evaluate_condition

    endings.lock(garden, "E4e")
    assert evaluate_condition(garden, {"ending": {"locked": "E4e"}}) is True
    assert evaluate_condition(garden, {"ending": {"eligible": "E4e"}}) is True
    assert evaluate_condition(garden, {"ending": {"intent": "E1a"}}) is False


# ---------------------------------------------------------------------------
# 5. Deck-drawn scenes
# ---------------------------------------------------------------------------


def test_the_required_spine_is_always_dealt_and_costs_no_draw_slot(
    garden: GameState,
) -> None:
    """
    A labyrinth that drops its Heart Trial is a labyrinth with no labyrinth.

    Required cards come first in authored order, which is the ordering an author
    writing L0 / L3 / L5 down the page expects.
    """
    hand = deck_module.draw(garden, "thorn_labyrinth")
    ids = [c.id for c in hand.cards]

    assert ids[:3] == ["L0_threshold", "L3_heart_trial", "L5_exit"]
    assert len(ids) == 5  # spine of 3 + declared draw of 2


def test_a_card_is_gated_by_the_shared_predicate_grammar(garden: GameState) -> None:
    """The Winter Mouth needs a passport, deep winter, or being properly lost."""
    hand = deck_module.draw(garden, "thorn_labyrinth", count=0, mark_drawn=False)
    assert hand.rejected["CC_winter_mouth"] == "conditions not met"

    _set(garden, "ashen_route", 2)
    hand = deck_module.draw(garden, "thorn_labyrinth", count=0, mark_drawn=False)
    assert "CC_winter_mouth" in hand.eligible


def test_the_same_seed_lays_out_the_same_labyrinth(garden: GameState) -> None:
    """Reproducible from a seed, or the scene most likely to be in a bug report
    is the one that cannot be reproduced from one."""

    def run() -> list[str]:
        set_overlay({"paths": _garden_paths()})
        state = GameState(rng_seed=7)
        return [c.id for c in deck_module.draw(state, "thorn_labyrinth").cards]

    assert run() == run()


def test_a_once_card_is_not_dealt_twice_on_one_save(garden: GameState) -> None:
    hand = deck_module.draw(garden, "thorn_labyrinth", count=8)
    assert "CA_gallery_of_almost_lovers" in [c.id for c in hand.cards]

    again = deck_module.draw(garden, "thorn_labyrinth", count=8)
    assert again.rejected["CA_gallery_of_almost_lovers"] == "already drawn"


def test_previewing_a_hand_does_not_spend_the_cards(garden: GameState) -> None:
    deck_module.draw(garden, "thorn_labyrinth", count=8, mark_drawn=False)
    assert not any(k.startswith(deck_module.DRAWN_FLAG_PREFIX) for k in garden.flags)


def test_a_missing_deck_is_reported_not_raised(garden: GameState) -> None:
    hand = deck_module.draw(garden, "no_such_deck")
    assert hand.cards == [] and hand.rejected == {"deck": "not found"}


def test_a_bands_range_is_clamped_by_the_storys_per_scene_ceiling() -> None:
    """An authored beat is still a scene, however greedily it was written."""
    adjustments: list[str] = []
    band = deck_module._bound_band({"value": "gold", "min": 5, "max": 400}, adjustments)
    assert band["max"] == 25
    assert adjustments


# ---------------------------------------------------------------------------
# 6. Per-beat resolution
# ---------------------------------------------------------------------------


def _beat(garden: GameState, card_id: str, beat_id: str) -> dict[str, Any]:
    deck = deck_module.load_deck("thorn_labyrinth")
    assert deck is not None
    card = next(c for c in deck.cards if c.id == card_id)
    return next(b for b in card.beats if b["id"] == beat_id)


def test_a_gate_on_a_hard_threshold_reads_state_and_never_rolls(
    garden: GameState,
) -> None:
    """A fact resolved by a roll is a fact the player cannot plan around."""
    beat = _beat(garden, "L3_heart_trial", "bind_rose_and_self")

    failed = deck_module.resolve_beat(garden, beat)
    assert failed.passed is False
    assert failed.roll is None
    assert garden.flags["labyrinth_result_devoted"] is True


def test_a_failed_gate_fails_forward_into_a_different_scene(
    garden: GameState,
) -> None:
    """
    "Fail gate -> default to devoted or self by nearest meter."

    ``on_fail`` is a branch, not an absence: the labyrinth never stops.
    """
    beat = _beat(garden, "L3_heart_trial", "bind_rose_and_self")
    result = deck_module.resolve_beat(garden, beat)
    assert result.effects and all(e["ok"] for e in result.effects)


def test_a_met_threshold_takes_the_pass_branch(garden: GameState) -> None:
    _set(garden, "autonomy", 60)
    _set(garden, "favor", 50)
    _set(garden, "desire", 45)

    result = deck_module.resolve_beat(garden, _beat(garden, "L3_heart_trial", "bind_rose_and_self"))
    assert result.passed is True
    assert garden.meters["equality_seed"] == 2


def test_a_seeded_hidden_check_replays_and_never_uses_bare_random() -> None:
    """``world_rng(state, stream)``. Same seed, same answer, every run."""

    def run() -> tuple[bool, float]:
        set_overlay({"paths": _garden_paths()})
        active_state._schema = load_schema(GARDEN_SCHEMA, slug="wicked-garden")
        state = GameState(rng_seed=1234)
        deck = deck_module.load_deck("thorn_labyrinth")
        card = next(c for c in deck.cards if c.id == "CE_name_well")
        out = deck_module.resolve_beat(state, card.beats[0])
        return out.passed, out.roll

    first, second = run(), run()
    assert first == second
    assert first[1] is not None


def test_a_hidden_check_draws_a_different_number_each_time(garden: GameState) -> None:
    """The other half of the RNG contract: consecutive draws must differ."""
    beat = _beat(garden, "CE_name_well", "whisper_your_name")
    rolls = {deck_module.resolve_beat(garden, beat).roll for _ in range(6)}
    assert len(rolls) > 1


def test_a_gate_may_require_both_a_threshold_and_a_check(garden: GameState) -> None:
    """The threshold is admission; the roll is whether it went well. One beat."""
    beat = _beat(garden, "CD_law_circle", "call_the_seat_law_aloud")

    result = deck_module.resolve_beat(garden, beat)
    assert result.passed is False
    assert result.check is None  # never reached the dice

    _set(garden, "knowledge", 40)
    with_knowledge = deck_module.resolve_beat(garden, beat)
    assert with_knowledge.check is not None
    assert with_knowledge.check["skill"] == "lore"


def test_a_band_resolves_to_its_midpoint_with_no_judgement(garden: GameState) -> None:
    """
    So the simulator and every test run this path without a model.

    A default at either end would make "the model did not answer" mechanically
    identical to "the model judged this perfect".
    """
    result = deck_module.resolve_beat(garden, _beat(garden, "L5_exit", "what_you_carry_out"))
    assert result.mode == "band"
    assert result.band == (2.0, 8.0)
    assert result.value == 5
    assert garden.meters["knowledge"] == 5


@pytest.mark.parametrize(
    "quality,expected",
    [(0.0, 2), (0.5, 5), (1.0, 8), (-3.0, 2), (9.0, 8)],
)
def test_an_agent_picks_inside_the_band_and_only_inside_it(
    garden: GameState, quality: float, expected: int
) -> None:
    """
    The narrowest thing worth trusting a model with.

    The engine owns the range and the clamp; the model owns only where inside
    it the moment landed -- and a judgement outside 0..1 is clamped, not obeyed.
    """
    result = deck_module.resolve_beat(
        garden, _beat(garden, "L5_exit", "what_you_carry_out"), quality=quality
    )
    assert result.value == expected
    assert garden.meters["knowledge"] == expected


def test_a_beat_declaring_both_a_gate_and_a_band_keeps_the_gate() -> None:
    """A beat is one question; two resolutions could not produce one receipt."""
    beats = deck_module._bound_beats(
        [{"id": "b", "gate": {"on_pass": {}}, "band": {"value": "favor", "min": 1, "max": 2}}],
        "d",
        "c",
    )
    assert "gate" in beats[0] and "band" not in beats[0]


def test_resolving_a_whole_card_walks_its_beats_in_order(garden: GameState) -> None:
    deck = deck_module.load_deck("thorn_labyrinth")
    card = next(c for c in deck.cards if c.id == "L3_heart_trial")
    results = deck_module.resolve_card(garden, card, qualities={"nothing": 1.0})
    assert [r.beat_id for r in results] == [b["id"] for b in card.beats]


def test_a_menu_card_resolves_exactly_the_beat_that_was_chosen(garden: GameState) -> None:
    """
    A menu card's beats are branches of one question, not steps.

    Content declares which it is (`tags: [menu]` / `[sequence]`) and for a while
    nothing in the engine read that tag -- so The Wicked Garden's first morning
    would have applied every branch, and the player both looked at their mortal
    home and refused to, taking the autonomy for one and the corruption for the
    other. Driven over the shipped card rather than a fixture, because the tag
    is a contract between authored content and this function.
    """
    card = next(c for c in deck_module.load_deck("day_01_guest").cards if c.id == "D1_01_waking")
    assert "menu" in card.tags and len(card.beats) > 1

    results = deck_module.resolve_card(garden, card, chosen="close_the_curtain")
    assert [r.beat_id for r in results] == ["close_the_curtain"]


def test_a_menu_card_with_no_choice_falls_forward_to_one_beat(garden: GameState) -> None:
    """
    Never zero, never all of them.

    There is no honest engine answer to "which branch" -- the choice is the
    player's. But a scene that resolves nothing leaves no mechanical trace at
    all, which is the harder failure to ever notice, so the first beat is taken.
    An unknown beat id lands the same way rather than silently resolving none.
    """
    card = next(c for c in deck_module.load_deck("day_01_guest").cards if c.id == "D1_01_waking")
    first = card.beats[0]["id"]

    assert [r.beat_id for r in deck_module.resolve_card(garden, card)] == [first]
    assert [r.beat_id for r in deck_module.resolve_card(garden, card, chosen="no_such")] == [first]


def test_a_sequence_card_ignores_a_chosen_beat(garden: GameState) -> None:
    """`chosen` is meaningless where the beats are steps, and must not truncate."""
    card = next(
        c
        for c in deck_module.load_deck("day_02_laws").cards
        if c.id == "D2_T_thornwake"
    )
    assert "sequence" in card.tags and len(card.beats) > 1
    results = deck_module.resolve_card(garden, card, chosen=card.beats[-1]["id"])
    assert [r.beat_id for r in results] == [b["id"] for b in card.beats]


def test_a_model_composed_challenge_cannot_end_the_story(garden: GameState) -> None:
    """
    `ending_lock` is authored-content-only.

    The bounder widened for the finale's own beat, and this is the half of that
    change that matters: the widening is scoped to YAML in the story's tree.
    A model composing a challenge mid-turn still cannot reach either ending
    phase -- same argument the module already makes about `track`, that an
    ending set by a dice table is not a scene but a hijack.
    """
    adjustments: list[str] = []
    outcome = spec_module.clamp_outcome(
        {"effects": [{"type": "ending_lock", "ending": "E1a"}]}, adjustments
    )
    assert outcome["effects"] == []
    assert any("ending_lock" in note for note in adjustments), adjustments

    # And the drop is a drop, not a silent pass-through to the dispatcher.
    assert endings.locked(garden) == endings.NONE_ID


def test_authored_content_may_end_the_story(garden: GameState) -> None:
    """The same block, from a file rather than a model, survives intact."""
    adjustments: list[str] = []
    outcome = spec_module.clamp_outcome(
        {"effects": [{"type": "ending_lock", "ending": "E1a"}]}, adjustments, authored=True
    )
    assert [e["type"] for e in outcome["effects"]] == ["ending_lock"]


def test_widening_for_authored_content_widens_only_the_structural_kinds(
    garden: GameState,
) -> None:
    """
    `authored=True` is not an escape hatch.

    Magnitude clamps still apply -- a beat written greedily is a mistake a human
    makes too -- and `track`, which the module deliberately excludes, stays
    excluded from both paths.
    """
    adjustments: list[str] = []
    outcome = spec_module.clamp_outcome(
        {
            "effects": [
                {"type": "favor", "delta": 500},
                {"type": "track", "name": "ending_intent", "value": "E1a"},
            ]
        },
        adjustments,
        authored=True,
    )
    kinds = [e["type"] for e in outcome["effects"]]
    assert "track" not in kinds
    assert outcome["effects"][0]["delta"] < 500


def test_a_beat_may_read_a_live_thread(garden: GameState) -> None:
    """
    The systems compose: a deck card's gate asks the thread system a question.

    Knowing what a gift-thread is, because you are carrying one, is what lets
    you name the trap.
    """
    beat = _beat(garden, "CF_bloom_ambush", "invoke_gift_thread_knowledge")
    assert deck_module.resolve_beat(garden, beat).passed is False

    threads.accept_gift(garden, "living_silk", from_id="sophia")
    assert deck_module.resolve_beat(garden, beat).passed is True

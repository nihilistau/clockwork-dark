"""
The multi-agent turn: plans, negotiation, scopes.

What this replaces: two agents that ran strictly sequentially and
one-directionally. The narrator ran to completion and COMMITTED, then the
companion was invoked with the final narration string as its only input.
Neither produced a plan, neither could object to the other, and the narrator
never saw the companion's output at all -- not that turn, not the next one,
because the companion's line was never written to the ledger.

The properties asserted here are the ones that make two agents worth running:

  * a plan is INERT -- constructing one changes nothing, which is the only
    reason a proposal can be argued with
  * safety outranks every agent goal and is not reorderable by a story
  * an agent cannot speak as a voice it does not own, and the attempt is
    recorded rather than dropped
  * knowledge is partitioned BY AGENT, not by player awareness

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from engine.agents.knowledge import (
    SCOPE_CHARACTER,
    SCOPE_GM,
    SCOPE_PUBLIC,
    KnowledgePolicy,
    policy_from_data,
)
from engine.agents.negotiate import (
    RULE_OWNERSHIP,
    RULE_SAFETY,
    Negotiator,
    Rule,
    rules_from_data,
)
from engine.agents.plan import (
    INTENT_INTERRUPT,
    INTENT_NARRATE,
    INTENT_SILENT,
    INTENT_SPEAK,
    AgentPlan,
    ProposedChoice,
    parse_plan,
    plan_schema,
)


def _plan(agent, intent=INTENT_SPEAK, **kwargs):
    return AgentPlan(agent=agent, intent=intent, **kwargs)


# -- plans are proposals ------------------------------------------------------


def test_a_plan_changes_nothing_by_itself():
    """
    The property the whole design rests on.

    A proposal that has already taken effect cannot be negotiated over; it can
    only be undone. Constructing a plan with effects must not touch state.
    """
    from engine.agents.plan import ProposedEffect
    from engine.game.state import GameState

    state = GameState()
    before = state.to_save_dict()

    _plan("gm", effects=[ProposedEffect(kind="stat", payload={"stat": "gold", "delta": 500})])

    assert state.to_save_dict() == before


def test_private_reasoning_is_withheld_from_serialisation_by_default():
    """
    `to_dict` output is what gets logged, journalled and sent to telemetry.

    A private motive that leaks into any of those is one the other agent can
    eventually read, so the default has to be the safe one.
    """
    plan = _plan("sophia", private="I want the iron pin gone before she finds it")

    assert "private" not in plan.to_dict()
    assert "private" in plan.to_dict(include_private=True)


def test_a_malformed_plan_costs_the_agent_its_turn_not_the_player_theirs():
    assert parse_plan("gm", {"intent": "conquer the world"}).intent == INTENT_SILENT
    assert parse_plan("gm", "not a dict").intent == INTENT_SILENT
    assert parse_plan("gm", {}).silent is True


def test_the_plan_schema_constrains_voices_to_what_the_agent_owns():
    """
    Same trick the turn schema already uses for NPCs actually present:
    enumerating makes the wrong answer unsamplable rather than discouraged.
    """
    schema = plan_schema("sophia", voices=("sophia_dialogue",))

    assert schema["properties"]["speaks_as"]["enum"] == ["sophia_dialogue"]


def test_the_schema_omits_the_enum_when_an_agent_owns_no_voices():
    """An empty enum matches nothing and would make the field unfillable."""
    schema = plan_schema("gm")

    assert "enum" not in schema["properties"]["speaks_as"]


# -- negotiation --------------------------------------------------------------


def test_safety_outranks_every_agent_goal():
    turn = Negotiator().negotiate(
        {"gm": _plan("gm", INTENT_NARRATE, beat="the door opens")},
        safety_block="past the session intensity ceiling",
    )

    assert turn.blocked is True
    assert any(r.rule == RULE_SAFETY for r in turn.resolutions)


def test_a_blocked_turn_still_produces_a_lead_and_choices():
    """
    Blocking must not leave the caller with nothing to render.

    The design's rule is that a refused direction comes back as an in-world
    interruption -- "not that door" -- never as customer service. A negotiator
    that returned an empty turn would force the caller to emit a refusal.
    """
    turn = Negotiator().negotiate(
        {
            "gm": _plan(
                "gm", INTENT_NARRATE, beat="the corridor bends",
                choices=[ProposedChoice(text="Turn back")],
            )
        },
        safety_block="hard limit",
    )

    assert turn.blocked is True
    assert turn.lead == "gm"
    assert turn.choices, "a blocked turn left nothing to show the player"


def test_an_agent_cannot_speak_as_a_voice_it_does_not_own():
    negotiator = Negotiator(
        owned_voices={"sophia": ("sophia_dialogue",), "gm": ("narration", "thornwake")}
    )

    turn = negotiator.negotiate(
        {"sophia": _plan("sophia", INTENT_SPEAK, speaks_as="thornwake", beat="she answers")}
    )

    assert turn.accepted["sophia"].speaks_as == ""
    assert any(r.rule == RULE_OWNERSHIP for r in turn.resolutions)


def test_a_legal_voice_claim_survives():
    negotiator = Negotiator(owned_voices={"sophia": ("sophia_dialogue",)})

    turn = negotiator.negotiate(
        {"sophia": _plan("sophia", INTENT_SPEAK, speaks_as="sophia_dialogue")}
    )

    assert turn.accepted["sophia"].speaks_as == "sophia_dialogue"


def test_a_story_rule_decides_who_leads():
    rules = [
        Rule(
            name="private_scene_wins",
            when={"sophia": INTENT_SPEAK, "gm": INTENT_INTERRUPT},
            winner="sophia",
            detail="her scene completes; the event becomes aftermath",
        )
    ]

    turn = Negotiator(rules).negotiate(
        {
            "sophia": _plan("sophia", INTENT_SPEAK, beat="she does not look up"),
            "gm": _plan("gm", INTENT_INTERRUPT, beat="a moth at the glass"),
        }
    )

    assert turn.lead == "sophia"
    assert turn.beats[0] == "she does not look up"


def test_the_loser_keeps_its_beat_demoted_when_the_rule_says_so():
    """'The event becomes aftermath' -- the world loses the lead, not its content."""
    rules = [
        Rule(name="r", when={"sophia": INTENT_SPEAK, "gm": INTENT_INTERRUPT},
             winner="sophia", keep_loser_beat=True)
    ]

    turn = Negotiator(rules).negotiate(
        {
            "sophia": _plan("sophia", INTENT_SPEAK, beat="she answers"),
            "gm": _plan("gm", INTENT_INTERRUPT, beat="a moth at the glass"),
        }
    )

    assert turn.beats == ["she answers", "a moth at the glass"]


def test_confidence_breaks_a_tie_no_rule_covers():
    turn = Negotiator().negotiate(
        {
            "gm": _plan("gm", INTENT_NARRATE, beat="road", confidence=0.2),
            "sophia": _plan("sophia", INTENT_SPEAK, beat="she speaks", confidence=0.9),
        }
    )

    assert turn.lead == "sophia"


def test_a_rule_with_no_when_never_fires():
    """
    A rule that matches everything would make table order silently
    load-bearing, so an empty `when` is inert rather than universal.
    """
    turn = Negotiator([Rule(name="greedy", winner="gm")]).negotiate(
        {"sophia": _plan("sophia", INTENT_SPEAK, confidence=0.9)}
    )

    assert turn.lead == "sophia"


def test_a_malformed_rule_row_is_skipped_not_fatal():
    table = rules_from_data(
        [
            "not a mapping",
            {"name": "", "when": {"gm": "narrate"}},
            {"name": "no_when"},
            {"name": "good", "when": {"gm": "narrate"}, "winner": "gm"},
        ]
    )

    assert [r.name for r in table] == ["good"]


# -- jointly authored choices -------------------------------------------------


def test_choices_from_both_agents_are_merged():
    turn = Negotiator().negotiate(
        {
            "gm": _plan("gm", INTENT_NARRATE, confidence=0.9,
                        choices=[ProposedChoice(text="Walk on")]),
            "sophia": _plan("sophia", INTENT_SPEAK, confidence=0.1,
                            choices=[ProposedChoice(text="Not that door")]),
        }
    )

    texts = [c.text for c in turn.choices]
    assert texts == ["Walk on", "Not that door"]


def test_duplicate_choices_collapse():
    """Two agents proposing 'Refuse' is one option, not a rendering bug."""
    turn = Negotiator().negotiate(
        {
            "gm": _plan("gm", INTENT_NARRATE, confidence=0.9,
                        choices=[ProposedChoice(text="Refuse")]),
            "sophia": _plan("sophia", INTENT_SPEAK, confidence=0.1,
                            choices=[ProposedChoice(text="refuse")]),
        }
    )

    assert len(turn.choices) == 1


def test_ids_are_positional_and_assigned_by_the_engine():
    """
    The 1-4 keyboard shortcuts depend on position, so letting an agent choose
    ids would let one agent's id collide with the other's.
    """
    turn = Negotiator().negotiate(
        {
            "gm": _plan(
                "gm", INTENT_NARRATE,
                choices=[ProposedChoice(text="One", id="zzz"), ProposedChoice(text="Two")],
            )
        }
    )

    assert [c.id for c in turn.choices] == ["a", "b"]


def test_a_choice_can_carry_a_consequence_whisper():
    turn = Negotiator().negotiate(
        {
            "gm": _plan(
                "gm", INTENT_NARRATE,
                choices=[ProposedChoice(text="Take it", whisper="This spends the key.")],
            )
        }
    )

    assert turn.choices[0].to_dict()["whisper"] == "This spends the key."


def test_all_silent_plans_produce_an_empty_turn_without_raising():
    turn = Negotiator().negotiate({"gm": AgentPlan(agent="gm")})

    assert turn.beats == []
    assert turn.choices == []


# -- knowledge scopes ---------------------------------------------------------


def test_public_is_readable_without_being_granted():
    """A scope system whose common case must be spelled out will be got wrong."""
    policy = KnowledgePolicy()

    assert policy.may_read("anyone", SCOPE_PUBLIC) is True
    assert policy.may_read("anyone", "") is True


def test_an_agent_absent_from_the_policy_sees_only_public():
    """
    The safe default: forgetting to grant a scope produces a slightly ignorant
    agent, not one reading the world's secrets.
    """
    policy = KnowledgePolicy({"gm": [SCOPE_GM]})

    assert policy.may_read("sophia", SCOPE_GM) is False


def test_the_world_and_the_character_cannot_read_each_other():
    policy = policy_from_data(
        {
            "gm": {"reads": [SCOPE_GM]},
            "sophia": {"reads": [SCOPE_CHARACTER]},
        }
    )

    assert policy.may_read("gm", SCOPE_GM) is True
    assert policy.may_read("gm", SCOPE_CHARACTER) is False
    assert policy.may_read("sophia", SCOPE_CHARACTER) is True
    assert policy.may_read("sophia", SCOPE_GM) is False


def test_blocks_are_dropped_rather_than_redacted():
    """
    A redacted block still tells the agent something was there, and a model
    that can see the shape of a secret writes around it in a way that reveals
    it.
    """
    policy = KnowledgePolicy({"sophia": [SCOPE_CHARACTER]})

    kept = policy.filter_blocks(
        "sophia",
        [
            (SCOPE_PUBLIC, "The square is busy."),
            (SCOPE_GM, "The scarecrow is already awake."),
            (SCOPE_CHARACTER, "You have not told her about the pin."),
        ],
    )

    assert kept == ["The square is busy.", "You have not told her about the pin."]
    assert not any("scarecrow" in block for block in kept)


def test_unknown_scopes_are_ignored_with_a_warning_not_granted():
    policy = KnowledgePolicy({"gm": ["gm_secrets", "everything"]})

    assert policy.may_read("gm", SCOPE_GM) is True
    assert policy.may_read("gm", "everything") is False


def test_lore_tags_always_include_public():
    policy = KnowledgePolicy({"gm": [SCOPE_GM]})

    assert SCOPE_PUBLIC in policy.lore_tags_for("gm")
    assert SCOPE_GM in policy.lore_tags_for("gm")

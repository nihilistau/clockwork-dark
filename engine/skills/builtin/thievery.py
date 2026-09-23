"""
Thievery Skills
===============

The tools of a thief who is not yet a burglar: watching a house to learn when
it stands empty, what guards it and what is worth taking.

Thin wrappers, for the reason ``livelihood.py`` gives: each one moves time or
state, so the engine resolves it and the narrator is handed the receipt. The
maths lives in ``engine/world/premises.py``; nothing here writes state itself.

Registered by importing this module; ``engine/skills/builtin/__init__.py`` does
that.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

import json

from engine.game.engine import get_active_engine
from engine.skills.registry import AGENT_STORYTELLER, skill


@skill(
    pack="core",
    description=(
        "Case a house in this district: watch it for a couple of hours and "
        "learn the next thing about it -- when it stands empty, one of its "
        "defences, what is worth taking, or that somebody inside is hiding "
        "something. Spends the hours. MUST call before narrating what the "
        "player learned by watching."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def case_premise(premise_id: str) -> str:
    """
    Watch one premise and learn one more thing about it.

    Args:
        premise_id: A premise in the player's current district.

    Returns:
        JSON receipt from ``premises.case``: ``ok``, the house's name, the line
        learned, how much is now known of how much, and the hours spent -- or
        ``ok: false`` with the engine's reason.
    """
    from engine.world import premises

    engine = get_active_engine()
    return json.dumps(premises.case(engine.state, premise_id))


@skill(
    pack="core",
    description=(
        "Try to lift the purse of somebody here and awake. Rolls stealth "
        "against how watchful they are; on a success takes coin or a thing "
        "from them, on a partial a little coin, on a failure nothing -- and "
        "they noticed. Takes a moment, not hours. MUST call before narrating "
        "a pocket picked or a hand caught."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def lift_purse(npc_id: str) -> str:
    """
    Try one mark's purse.

    Args:
        npc_id: A person present at the player's location.

    Returns:
        JSON receipt from ``thievery.lift``: ``ok`` (the attempt happened),
        ``success``, ``degree``, ``noticed``, what was taken -- or ``ok: false``
        with the engine's reason.
    """
    from engine.world import thievery

    engine = get_active_engine()
    return json.dumps(thievery.lift(engine.state, npc_id))

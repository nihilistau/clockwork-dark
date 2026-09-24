"""
Law Skills
==========

What a player under a watch can do about it: put on a different guise, and,
once held, pay the fine or serve the sentence.

Thin wrapper, for the ``thievery.py`` reason: the maths and the writes live in
``engine/world/law.py``; this module only hands the narrator the receipt.

Registered by importing this module; ``engine/skills/builtin/__init__.py``
does that.

Version: v0.2.0 [2026-09-24]
"""

from __future__ import annotations

import json

from engine.game.engine import get_active_engine
from engine.skills.registry import AGENT_STORYTELLER, skill


@skill(
    pack="core",
    description=(
        "Change which face you show the street: your own, or a guise whose "
        "costume you are carrying. Takes no time. If anyone present notices "
        "the change, the watch starts believing the two faces are one "
        "person. MUST call before narrating a change of guise."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def change_guise(guise_id: str) -> str:
    """
    Put on a different guise, or the player's own face.

    Args:
        guise_id: A guise the Law declares, either ``self`` or one whose item
            the player is carrying.

    Returns:
        JSON receipt from ``law.change_guise``: ``ok``, ``guise``, ``label``,
        ``seen`` -- or ``ok: false`` with the engine's reason.
    """
    from engine.world import law

    engine = get_active_engine()
    return json.dumps(law.change_guise(engine.state, guise_id))


@skill(
    pack="core",
    description=(
        "Pay the fine and walk out of the cells. Only while held, and only "
        "with the coin; the charge that put you there is closed. MUST call "
        "before narrating a fine paid."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def pay_fine() -> str:
    """
    Pay what the watch asks and be released.

    Returns:
        JSON receipt from ``law.pay_fine``: ``ok``, ``paid``, ``gaol`` -- or
        ``ok: false`` with the engine's reason (not held, or short of coin).
    """
    from engine.world import law

    engine = get_active_engine()
    return json.dumps(law.pay_fine(engine.state))


@skill(
    pack="core",
    description=(
        "Serve the sentence: the days pass in the cells, then you are let "
        "out and the charge is closed. Always possible while held. MUST call "
        "before narrating a sentence served."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def serve_sentence() -> str:
    """
    Wait out the sentence and be released.

    Returns:
        JSON receipt from ``law.serve_sentence``: ``ok``, ``days``, ``gaol``
        -- or ``ok: false`` when not held.
    """
    from engine.world import law

    engine = get_active_engine()
    return json.dumps(law.serve_sentence(engine.state))

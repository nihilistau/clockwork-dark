"""
Quest Skills
============

The Storyteller's entire surface area onto the quest system.

There are two tools here and there is a reason there are only two. The model
may **observe** ("the player did ask Maris for work") and it may **read** ("what
is open right now"). It cannot advance a stage, complete a quest, start one, or
unlock an arc. Those are engine decisions taken in ``engine.game.quests`` from
predicates the model cannot reach.

The distinction is the whole feature. A tool named ``complete_quest`` would
hand narrative bookkeeping to the same component that, elsewhere in this
codebase, had to be stopped from inventing dice results. ``set_narrative_flag``
is the narrow version: the model reports what happened in the fiction, the
engine decides what that means mechanically, and a flag no active quest is
listening for comes back rejected with the list it could have used.

Version: v0.1.0 [2026-08-07]
"""

from __future__ import annotations

import json

from engine.game.engine import get_active_engine
from engine.game.quests import QuestEngine
from engine.skills.registry import (
    AGENT_STORYTELLER,
    TRIGGER_OPTIONAL,
    skill,
)


@skill(
    pack="core",
    description=(
        "Report that a specific story beat happened, by raising a narrative "
        "flag a quest is listening for. Use ONLY the flag ids listed in your "
        "OBJECTIVES block. This does NOT complete a quest -- the engine decides "
        "that. An unrecognised flag is rejected and lists the valid ones."
    ),
    category="NARRATIVE",
    trigger=TRIGGER_OPTIONAL,
    agents=[AGENT_STORYTELLER],
)
def set_narrative_flag(flag_id: str) -> str:
    """
    Raise one narrative flag on behalf of the narration.

    Args:
        flag_id: Flag declared by a currently active quest or its current stage.

    Returns:
        JSON receipt. On rejection it carries ``allowed`` so the model can
        correct itself on the next call instead of repeating an invalid one --
        a silent False teaches it nothing.
    """
    state = get_active_engine().state
    allowed = sorted(QuestEngine.allowed_narrative_flags(state))
    accepted = QuestEngine.set_narrative_flag(state, flag_id)

    if not accepted:
        return json.dumps(
            {
                "success": False,
                "flag_id": flag_id,
                "reason": (
                    "No active quest is listening for that flag. Narrate the "
                    "beat, but do not claim mechanical progress."
                ),
                "allowed": allowed,
            }
        )

    return json.dumps(
        {
            "success": True,
            "flag_id": flag_id,
            "note": (
                "Recorded. The engine will decide whether this closes a stage; "
                "do not narrate a quest as finished."
            ),
            "objectives": QuestEngine.active_objectives(state),
        }
    )


@skill(
    pack="core",
    description=(
        "List what the player currently has open: quest names, the objective "
        "in play, and the narrative flags you are permitted to raise."
    ),
    category="NARRATIVE",
    trigger=TRIGGER_OPTIONAL,
    agents=[AGENT_STORYTELLER],
)
def query_quests() -> str:
    """
    Report the open objectives and the legal flag vocabulary.

    Returns:
        JSON with ``objectives`` (player-facing lines), ``active_arc``,
        ``arcs_unlocked`` and ``narrative_flags``.
    """
    state = get_active_engine().state
    return json.dumps(
        {
            "active_arc": state.active_arc,
            "arcs_unlocked": list(state.arcs_unlocked),
            "objectives": QuestEngine.active_objectives(state),
            "narrative_flags": sorted(QuestEngine.allowed_narrative_flags(state)),
        }
    )

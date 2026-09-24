"""
Job Skills
==========

What a thief does with a house they have cased: go in, stage by stage, or
walk away.

Thin wrapper, for the ``thievery.py`` reason: the rules and the writes live in
``engine/world/jobs.py``; this module only hands the narrator the receipt.

Registered by importing this module; ``engine/skills/builtin/__init__.py``
does that.

Version: v0.3.0 [2026-09-24]
"""

from __future__ import annotations

import json

from engine.game.engine import get_active_engine
from engine.skills.registry import AGENT_STORYTELLER, skill


@skill(
    pack="core",
    description=(
        "Start a burglary on a house in this district that has not already "
        "been robbed. Takes no time by itself; the job then runs stage by "
        "stage and owns the turn until it ends. MUST call before narrating "
        "the player setting out to break in."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def begin_job(premise_id: str) -> str:
    """
    Open a job on one premise.

    Args:
        premise_id: A premise in the player's current district, not robbed.

    Returns:
        JSON receipt from ``jobs.begin``: ``ok``, ``job_id``, ``premise``,
        the house's ``name`` and its ``stages`` -- or ``ok: false`` with the
        engine's reason.
    """
    from engine.world import jobs

    engine = get_active_engine()
    return json.dumps(jobs.begin(engine.state, premise_id))


@skill(
    pack="core",
    description=(
        "Attempt the open job's current stage by one of its approaches (at "
        "the entry, the way in). Spends the stage's hours, then rolls; a "
        "failure raises the alarm and the stage must be tried again. MUST "
        "call before narrating any step of a burglary."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def job_stage(approach: str) -> str:
    """
    Resolve one turn of the open job's current stage.

    Args:
        approach: An approach the current stage offers -- an entry id at the
            entry, else the stage's own id.

    Returns:
        JSON receipt from ``jobs.resolve_stage``: ``ok``, ``stage``,
        ``outcome`` (clean, noisy, seen, hurt, aborted, caught), ``closed``
        and the rest -- or ``ok: false`` with the engine's reason.
    """
    from engine.world import jobs

    engine = get_active_engine()
    return json.dumps(jobs.resolve_stage(engine.state, approach))


@skill(
    pack="core",
    description=(
        "Call on a flashback at the open job's current stage: something the "
        "thief set up beforehand. Spends prep (and coin, where named), moves "
        "the current stage's odds or clears an obstacle, and never spends "
        "time. MUST call before narrating the player remembering they "
        "arranged for something."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def call_flashback(kind: str) -> str:
    """
    Spend one flashback the open job's current stage still allows.

    Args:
        kind: A flashback kind the job currently offers.

    Returns:
        JSON receipt from ``jobs.flashback``: ``ok``, ``kind``, ``label``,
        ``cost``, ``band_before``, ``band_after`` and ``exposure_witness``
        where one was made -- or ``ok: false`` with the engine's reason.
    """
    from engine.world import jobs

    engine = get_active_engine()
    return json.dumps(jobs.flashback(engine.state, kind))


@skill(
    pack="core",
    description=(
        "Walk away from the open job with nothing. Takes no time; anything "
        "taken at the score is left behind. MUST call before narrating the "
        "player giving a burglary up."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def abort_job() -> str:
    """
    Abandon the open job.

    Returns:
        JSON receipt from ``jobs.abort``: ``ok``, ``outcome: aborted``,
        ``closed`` -- or ``ok: false`` when no job is open.
    """
    from engine.world import jobs

    engine = get_active_engine()
    return json.dumps(jobs.abort(engine.state))

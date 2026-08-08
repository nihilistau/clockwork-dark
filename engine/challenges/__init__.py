"""
Challenges — AI-composed, engine-validated multi-step encounters
================================================================

Combat and a single skill check were the entire mechanical vocabulary. A
challenge adds structure the Storyteller can compose mid-scene and the engine
then owns:

  * ``skill_gauntlet`` — an ordered run of d20 skill checks; one failure ends it.
  * ``decision_tree``  — branching nodes ending in a terminal outcome.
  * ``puzzle``         — a typed answer, checked, with limited attempts.
  * ``dice_table``     — a weighted outcome table.

The split that makes this safe: ``spec`` validates and BOUNDS what the model
proposed, ``runner`` resolves it through the ordinary check and effect layers,
and ``set_pieces`` gates authored ones behind world flags.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from engine.challenges.runner import (
    STATUS_ACTIVE,
    STATUS_ERROR,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    ChallengeResult,
    abandon,
    resolve,
    start,
)
from engine.challenges.spec import KINDS, SpecResult, validate

__all__ = [
    "KINDS",
    "STATUS_ACTIVE",
    "STATUS_ERROR",
    "STATUS_FAILURE",
    "STATUS_SUCCESS",
    "ChallengeResult",
    "SpecResult",
    "abandon",
    "resolve",
    "start",
    "validate",
]

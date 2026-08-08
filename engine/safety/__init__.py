"""
Safety Layer
============

A boundary sheet and an intensity ceiling that sit ABOVE every agent in this
engine, expressed as data rather than as prompt text.

    engine/safety/tiers.py        the three-step ladder, and its ordering
    engine/safety/boundaries.py   hard nos, soft nos, green lights, tier markers
    engine/safety/policy.py       resolution, the actor ratchet, per-session store
    engine/safety/verdict.py      what a decision is allowed to be shaped like
    engine/safety/redirect.py     what a blocked generation comes back as
    engine/safety/gate.py         the seam the rest of the engine calls
    engine/safety/governor.py     the two governance hooks that put it in a turn

THE FOUR CLAIMS, AND WHERE EACH IS ENFORCED:

  "A character's motivation never raises the ceiling."
      ``policy.Actor``. The only mutator takes an actor, and AGENT is a min().
      There is no second path.

  "Content above the session's setting collapses to summary."
      ``gate.SafetyGate._decide`` step 2. One comparison, one place.

  "A faded scene still applies its mechanical outcomes."
      ``verdict.Verdict`` has no effects field, and ``governor._fade`` touches
      no plan. The invariant is the absence of code, not the presence of a
      comment.

  "A block comes back as an in-world redirect, not a refusal."
      ``redirect.Redirect`` carries a beat and a fallback line, never an
      apology. ``governor._redirect`` puts the beat on the turn context.

NOTHING IN HERE IS ON BY DEFAULT. A policy with no limits and a suggestive
ceiling is ``inert``, and an inert policy short-circuits to ALLOW at every
surface, contributes no prompt text, and draws no RNG. Both shipped stories are
inert, so they behave exactly as they did before this package existed.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from engine.safety.boundaries import (
    EMPTY_SHEET,
    NO_MARKERS,
    BoundarySheet,
    Limit,
    TierMarkers,
    sheet_from_limits,
)
from engine.safety.gate import FADE_SUMMARY_HINT, SafetyGate, gate_for
from engine.safety.governor import (
    SafetyCeiling,
    SafetyDirective,
    register_safety_interceptors,
)
from engine.safety.policy import (
    INERT_POLICY,
    Actor,
    SafetyPolicy,
    policy_for,
    reset_policies,
    resolve,
    set_policy,
)
from engine.safety.redirect import DEFAULT_PACK, Redirect, RedirectPack
from engine.safety.tiers import HIGHEST, LOWEST, TIER_ORDER, IntensityTier
from engine.safety.verdict import Disposition, FadeCard, Verdict, fade_card

__all__ = [
    "DEFAULT_PACK",
    "EMPTY_SHEET",
    "FADE_SUMMARY_HINT",
    "HIGHEST",
    "INERT_POLICY",
    "LOWEST",
    "NO_MARKERS",
    "TIER_ORDER",
    "Actor",
    "BoundarySheet",
    "Disposition",
    "FadeCard",
    "IntensityTier",
    "Limit",
    "Redirect",
    "RedirectPack",
    "SafetyCeiling",
    "SafetyDirective",
    "SafetyGate",
    "SafetyPolicy",
    "TierMarkers",
    "Verdict",
    "fade_card",
    "gate_for",
    "policy_for",
    "register_safety_interceptors",
    "reset_policies",
    "resolve",
    "set_policy",
    "sheet_from_limits",
]

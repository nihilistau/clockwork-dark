"""
Intensity Tiers
===============

The three-step content ladder every other module in this package compares
against: ``suggestive`` < ``explicit`` < ``extreme``.

WHY AN ORDERED TYPE AND NOT A STRING. The whole safety layer is one comparison
-- "is what is about to be written above what this session allows?" -- and a
comparison written against bare strings is a comparison nobody can trust:
``"extreme" < "suggestive"`` is True in Python, alphabetically, and that bug
fails in the one direction that matters. Making the ladder a type means the
ceiling check is ``tier > policy.intensity`` and it means what it reads as.

WHY PARSING NEVER RAISES. A tier arrives from a YAML file an author typed, a
manifest, a saved session, or a model's JSON. Every one of those can be wrong,
and a ValueError on any of them takes down a turn the layer exists to protect
(see the module docstring in ``gate.py``). Unparseable input therefore lands on
the LOWEST tier, which is both the documented default and the safe direction to
fail in -- a typo makes the game tamer, never coarser.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class IntensityTier(Enum):
    """
    How far a scene may be taken, lowest first.

    The values are the strings that appear in config, manifests and save data.
    The ORDER is carried by ``rank`` rather than by the values, so renaming a
    tier's wire format could never silently reorder the ladder.
    """

    SUGGESTIVE = "suggestive"
    EXPLICIT = "explicit"
    EXTREME = "extreme"

    @property
    def rank(self) -> int:
        """Position on the ladder. 0 is the safest."""
        return _RANK[self]

    # -- ordering ---------------------------------------------------------
    #
    # Written out rather than reached for via functools.total_ordering: Enum
    # already defines __eq__ by identity, and a decorator that fills in three
    # of four operators from an __eq__ it does not own is the kind of subtlety
    # this comparison must not depend on.

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, IntensityTier):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, IntensityTier):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, IntensityTier):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, IntensityTier):
            return NotImplemented
        return self.rank >= other.rank

    # -- parsing ----------------------------------------------------------

    @classmethod
    def parse(
        cls,
        value: Any,
        *,
        default: Optional["IntensityTier"] = None,
        source: str = "",
    ) -> "IntensityTier":
        """
        Read a tier from anything, never raising.

        Args:
            value: A tier, a tier's name in any case, or junk.
            default: Where junk lands. Defaults to the lowest tier, which is
                the only safe direction to guess in.
            source: Where the value came from, for the log line. An author who
                typed ``sugestive`` gets told which file to look in.

        Returns:
            A tier. Always.
        """
        fallback = default if default is not None else LOWEST
        if isinstance(value, IntensityTier):
            return value
        text = str(value or "").strip().lower()
        if not text:
            return fallback
        for tier in cls:
            if tier.value == text:
                return tier
        logger.warning(
            "[safety] Unreadable intensity tier, using %s "
            "(operation=parse, value=%r, source=%s)",
            fallback.value,
            value,
            source or "unknown",
        )
        return fallback


_RANK: dict[IntensityTier, int] = {
    IntensityTier.SUGGESTIVE: 0,
    IntensityTier.EXPLICIT: 1,
    IntensityTier.EXTREME: 2,
}

#: The ladder in order. Useful for building a settings dial.
TIER_ORDER: tuple[IntensityTier, ...] = (
    IntensityTier.SUGGESTIVE,
    IntensityTier.EXPLICIT,
    IntensityTier.EXTREME,
)

#: Where an unconfigured session sits, and where junk lands.
LOWEST: IntensityTier = IntensityTier.SUGGESTIVE
HIGHEST: IntensityTier = IntensityTier.EXTREME


def clamp(tier: IntensityTier, ceiling: IntensityTier) -> IntensityTier:
    """The lower of the two. The one operation the ceiling is made of."""
    return tier if tier <= ceiling else ceiling


__all__ = [
    "HIGHEST",
    "LOWEST",
    "TIER_ORDER",
    "IntensityTier",
    "clamp",
]

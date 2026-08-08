"""
Verdicts
========

What the safety layer is allowed to say back, and -- more importantly -- what
it is NOT shaped to say.

THE ONE DETAIL EVERY IMPLEMENTATION GETS WRONG. ``docs/design/06-UI-UX.md:208``
says of a faded scene: "Summary card if Fade used: mechanical outcomes still
apply." A fade is a change of CAMERA, not a change of WORLD. The scene happened;
the player simply is not being shown it in detail. Favor still moved, the gift
was still accepted, the hour still passed.

The usual bug is that the safety check sits on the same code path as the effect
application, so declining to narrate declines to apply. This module prevents
that shape rather than warning against it:

  * ``Verdict`` carries text and a disposition. It has no effects field, no
    deltas field and no state handle. There is nothing here for a caller to
    apply, so nothing here can fail to be applied.
  * ``outcomes_apply`` is a plain boolean the caller reads, and it is True for
    every disposition except REDIRECT -- including FADE. A REDIRECT is the one
    case where the world genuinely did not do the thing, because the fiction
    interrupted before it happened.
  * ``FadeCard`` is presentation only. Building one is not applying anything,
    and its ``outcomes`` are already-rendered player-facing lines, not deltas.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from engine.safety.tiers import LOWEST, IntensityTier


class Disposition(Enum):
    """
    What should happen to a piece of content.

    Ordered loosely by how much they intervene, but never compared -- a caller
    that wants "is this at least as strict as X" wants a different question.
    """

    #: Nothing to do. The overwhelming majority of turns, and the only verdict
    #: an inert policy ever produces.
    ALLOW = "allow"
    #: Write it, with cosmetic renames applied. Same mechanics, different noun.
    SUBSTITUTE = "substitute"
    #: Do not write it in detail. Narrate the outcome as summary. The world
    #: still moves -- see the module docstring.
    FADE = "fade"
    #: Do not write it at all. The turn continues as an in-fiction
    #: interruption, and the thing did not happen.
    REDIRECT = "redirect"


#: Dispositions after which the turn's mechanical outcomes still apply.
#: FADE is in this set on purpose and the tests say so out loud.
OUTCOMES_STILL_APPLY: frozenset[Disposition] = frozenset(
    {Disposition.ALLOW, Disposition.SUBSTITUTE, Disposition.FADE}
)


@dataclass(frozen=True)
class Verdict:
    """
    One safety decision.

    Attributes:
        disposition: What to do.
        intensity: The tier in force when this was decided. Carried so a caller
            logging a verdict does not have to reach back into the policy and
            risk reading a different session's.
        reasons: Limit topics and rule ids that fired. Machine-readable, for
            logs and telemetry. NEVER shown to the player: the character must
            not recite the player's own limit sheet back at them
            (SOPHIA-VOICE-BIBLE.md:98, "safety is UI, not her morality
            monologue").
        substitutions: Surface form -> replacement, for SUBSTITUTE.
        redirect: The in-fiction direction for REDIRECT -- what should happen
            INSTEAD, phrased as a beat for the narrator rather than as prose.
        fallback: A usable line of prose for when there is no model to hand the
            redirect beat to. The engine already degrades this way everywhere
            else; a redirect that produced nothing when the LLM was down would
            be a blank turn.
        summary_hint: The instruction handed to whatever writes the summary,
            for FADE.
    """

    disposition: Disposition = Disposition.ALLOW
    intensity: IntensityTier = LOWEST
    reasons: tuple[str, ...] = ()
    substitutions: dict[str, str] = field(default_factory=dict)
    redirect: str = ""
    fallback: str = ""
    summary_hint: str = ""

    # -- queries ----------------------------------------------------------

    @property
    def allowed(self) -> bool:
        """True when the content may be generated as written."""
        return self.disposition is Disposition.ALLOW

    @property
    def outcomes_apply(self) -> bool:
        """
        Whether the turn's mechanical outcomes should still be applied.

        True for FADE. That is the whole point (06-UI-UX.md:208).
        """
        return self.disposition in OUTCOMES_STILL_APPLY

    @property
    def blocked(self) -> bool:
        """True when the direction was refused and must be redirected in fiction."""
        return self.disposition is Disposition.REDIRECT

    def to_dict(self) -> dict[str, Any]:
        """
        Serialisable form for telemetry and the turn journal.

        ``reasons`` is included because this dict never reaches the player --
        it reaches the log. The player-facing artifact is ``FadeCard``.
        """
        return {
            "disposition": self.disposition.value,
            "intensity": self.intensity.value,
            "reasons": list(self.reasons),
            "substitutions": dict(self.substitutions),
            "outcomes_apply": self.outcomes_apply,
        }

    # -- constructors -----------------------------------------------------

    @classmethod
    def allow(cls, intensity: IntensityTier = LOWEST) -> "Verdict":
        """The default answer, and the one an inert policy always gives."""
        return cls(disposition=Disposition.ALLOW, intensity=intensity)


@dataclass(frozen=True)
class FadeCard:
    """
    The player-facing artifact of a faded scene.

    ``06-UI-UX.md`` calls this the "summary card". It carries the fiction at a
    lower resolution plus the consequences in plain words, because the whole
    contract of a fade is that the player loses the detail and keeps the
    information.

    Attributes:
        heading: One line naming what was skipped, in-world.
        summary: The scene at summary resolution.
        outcomes: Already-rendered player-facing consequence lines ("She keeps
            the gift.", "An hour passes."). Strings, not deltas -- see the
            module docstring on why this class must not be able to apply
            anything.
        aftercare: Whether the session asked for an aftercare beat to follow.
    """

    heading: str = ""
    summary: str = ""
    outcomes: tuple[str, ...] = ()
    aftercare: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "heading": self.heading,
            "summary": self.summary,
            "outcomes": list(self.outcomes),
            "aftercare": self.aftercare,
        }


def fade_card(
    verdict: Verdict,
    *,
    summary: str = "",
    outcomes: tuple[str, ...] = (),
    heading: str = "",
    aftercare: bool = False,
) -> Optional[FadeCard]:
    """
    Build the summary card for a faded verdict.

    Args:
        verdict: The decision. Anything other than FADE returns None, so a
            caller can hand every verdict here without branching first.
        summary: The scene at summary resolution, from whoever writes prose.
        outcomes: Rendered consequence lines. The caller has ALREADY applied
            these; this argument is what they looked like, not a request.
        heading: Overrides the default heading.
        aftercare: Whether an aftercare beat follows.

    Returns:
        A card, or None when the verdict was not a fade.
    """
    if verdict.disposition is not Disposition.FADE:
        return None
    return FadeCard(
        heading=heading or "The scene passes.",
        summary=summary,
        outcomes=tuple(outcomes),
        aftercare=aftercare,
    )


__all__ = [
    "OUTCOMES_STILL_APPLY",
    "Disposition",
    "FadeCard",
    "Verdict",
    "fade_card",
]

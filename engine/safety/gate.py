"""
Safety Gate
===========

The one object the rest of the engine talks to. Everything else in this package
is data it reads.

WHAT IT IS ASKED, AND WHEN:

    review_input(text)          player input, before anything is planned
    review_plan(plan)           an agent's proposal, before it is narrated
    review_beat(text)           a beat or brief, at the pre-commit phase
    review_narration(text)      prose, before it reaches the player
    rename(text)                cosmetic substitution on a display string
    directive_text()            the standing constraint block for the GM prompt

THE ORDER OF THE DECISION, which is the whole design:

    1. inert policy              -> ALLOW, immediately, having touched nothing
    2. a hard no is present      -> REDIRECT. Nothing below this line is
                                    consulted; no tier, no green light and no
                                    character motivation reaches past it.
    3. tier above the session's  -> FADE. Collapse to summary. Outcomes apply.
    4. a soft no is present      -> SUBSTITUTE if every hit offered a rename,
                                    otherwise FADE.
    5. otherwise                 -> ALLOW

IT CANNOT TAKE THE GAME DOWN. Every public method is wrapped: an exception
inside this package is logged and turned into a documented fallback verdict,
never re-raised. A safety layer that can crash the game it protects is worse
than none. The fallbacks are chosen per method rather than uniformly, because
"safe" means a different thing at each seam:

  * ``review_input`` falls back to ALLOW. It is the first of several checks,
    and refusing to let a player type because of a bug in the matcher would be
    an outage dressed as caution.
  * ``review_beat`` and ``review_narration`` fall back to FADE when the policy
    is active. FADE is the one disposition that is simultaneously safe and
    non-blocking: the turn completes, the outcomes still apply, and the prose
    the layer failed to inspect is not shipped.
  * An INERT policy falls back to ALLOW everywhere, so a story with nothing
    configured cannot be made worse by a bug in a layer it is not using.

WHAT IT NEVER DOES. It does not touch state, does not apply effects, does not
hold a transaction and has no writer for any meter. A Verdict is text and a
disposition. That is why a fade cannot silently swallow a consequence -- see
``verdict.py``.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from engine.safety.policy import INERT_POLICY, SafetyPolicy, policy_for
from engine.safety.redirect import DEFAULT_PACK, RedirectPack
from engine.safety.tiers import LOWEST, IntensityTier
from engine.safety.verdict import Disposition, FadeCard, Verdict, fade_card

logger = logging.getLogger(__name__)

#: Handed to whatever writes the summary when a scene is faded. Deliberately
#: says what to KEEP, not only what to omit -- a summariser told only to be
#: vague produces prose with no information in it, and the contract of a fade
#: is that the player loses the detail and keeps the consequences.
FADE_SUMMARY_HINT = (
    "Do not write this scene in detail. Give one short paragraph of summary at "
    "a distance -- what happened, what it cost, how it left them. Keep every "
    "consequence: promises made, things given or taken, time spent, how the "
    "relationship stands afterwards. Do not mention that anything was skipped."
)


class SafetyGate:
    """
    A policy plus a redirect pack, with the decision on top.

    Cheap to construct and safe to build per turn: the policy is cached per
    session in ``policy.policy_for`` and the redirect pack is immutable.
    """

    def __init__(
        self,
        policy: Optional[SafetyPolicy] = None,
        *,
        redirects: Optional[RedirectPack] = None,
        state: Optional[Any] = None,
    ) -> None:
        self.policy = policy if policy is not None else INERT_POLICY
        self.redirects = redirects if redirects is not None else DEFAULT_PACK
        #: Used only to seed the redirect draw. Never written to.
        self.state = state

    # -- construction ------------------------------------------------------

    @classmethod
    def for_state(cls, state: Optional[Any]) -> "SafetyGate":
        """
        The gate for a running session.

        Reads ``state.session_id`` when there is one. A state object without
        that attribute -- a stub in a test, a partially built state -- gets the
        process default policy rather than an AttributeError.
        """
        session_id = str(getattr(state, "session_id", "") or "")
        return cls(policy_for(session_id), state=state)

    @classmethod
    def for_session(cls, session_id: str = "") -> "SafetyGate":
        """The gate for a session id, with no state to seed redirects from."""
        return cls(policy_for(session_id))

    # -- queries -----------------------------------------------------------

    @property
    def inert(self) -> bool:
        """True when this gate has nothing to enforce. See SafetyPolicy.inert."""
        return self.policy.inert

    # -- the decision ------------------------------------------------------

    def _decide(
        self,
        text: str,
        *,
        declared: IntensityTier,
        tags: Sequence[str],
    ) -> Verdict:
        """
        The single decision function. Every review method funnels here.

        One implementation so the ORDER of the checks -- hard no, then ceiling,
        then soft no -- exists once and is tested once. Four copies of an
        ordered decision is four chances for the hard-no check to end up second.
        """
        policy = self.policy
        sheet = policy.sheet

        # 1. Hard nos. First, unconditionally, and with nothing after it that
        #    could reverse the answer.
        hard = sheet.hard_hits(text)
        if hard:
            choice = self.redirects.pick(self.state, tags=tags)
            return Verdict(
                disposition=Disposition.REDIRECT,
                intensity=policy.intensity,
                reasons=tuple(f"hard:{l.topic}" for l in hard),
                redirect=choice.beat,
                fallback=choice.line,
            )

        # 2. The ceiling. `declared` is what the caller says the content is;
        #    markers may raise that estimate but never lower it.
        tier = policy.markers.tier_of(text, floor=declared)
        if tier > policy.intensity:
            return Verdict(
                disposition=Disposition.FADE,
                intensity=policy.intensity,
                reasons=(f"ceiling:{tier.value}>{policy.intensity.value}",),
                summary_hint=FADE_SUMMARY_HINT,
            )

        # 3. Soft nos. A rename is offered only when EVERY hit had one --
        #    substituting three nouns out of four leaves the fourth on the page,
        #    which is worse than fading, because it looks like the limit was
        #    honoured.
        soft = sheet.soft_hits(text)
        if soft:
            reasons = tuple(f"soft:{l.topic}" for l in soft)
            if all(l.substitute for l in soft):
                return Verdict(
                    disposition=Disposition.SUBSTITUTE,
                    intensity=policy.intensity,
                    reasons=reasons,
                    substitutions=sheet.substitutions(text),
                )
            return Verdict(
                disposition=Disposition.FADE,
                intensity=policy.intensity,
                reasons=reasons,
                summary_hint=FADE_SUMMARY_HINT,
            )

        return Verdict.allow(policy.intensity)

    def _fallback(self, rule: str, exc: BaseException, *, safe: Disposition) -> Verdict:
        """
        The verdict an internal failure produces.

        Logged at warning, not error: this is a bug in the safety layer, and it
        should be visible without being a crash the player experiences.
        """
        logger.warning(
            "[safety] Review failed, degrading to %s "
            "(operation=%s, inert=%s): %s",
            safe.value,
            rule,
            self.policy.inert,
            exc,
        )
        if self.policy.inert or safe is Disposition.ALLOW:
            return Verdict.allow(self.policy.intensity)
        return Verdict(
            disposition=Disposition.FADE,
            intensity=self.policy.intensity,
            reasons=(f"internal:{rule}",),
            summary_hint=FADE_SUMMARY_HINT,
        )

    # -- review surfaces ---------------------------------------------------

    def review_input(self, text: str) -> Verdict:
        """
        Inspect player input before anything plans against it.

        This is the seam that does not exist today -- player input is passed
        straight through with no inspection. A hard-no hit here comes back as a
        REDIRECT, which means the turn still runs: the player asked for
        something the session has ruled out, and the fiction declines rather
        than the interface refusing.

        Falls back to ALLOW on internal failure. See the module docstring.
        """
        if self.policy.inert:
            return Verdict.allow(self.policy.intensity)
        try:
            return self._decide(
                text or "",
                declared=LOWEST,
                tags=("interruption", "refusal"),
            )
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            return self._fallback("review_input", exc, safe=Disposition.ALLOW)

    def review_beat(
        self,
        text: str,
        *,
        declared: Any = None,
        tags: Sequence[str] = (),
    ) -> Verdict:
        """
        Inspect a beat, brief or piece of scene direction.

        This is the pre-commit surface: a beat is what an agent WANTS to
        happen, and reviewing it before the transaction commits is the only
        point at which "this must not happen" can still mean it.

        Args:
            declared: The tier the caller says this content is. Any parseable
                form; absent means the lowest.
            tags: Preferred redirect kinds.

        Falls back to FADE on internal failure when the policy is active.
        """
        if self.policy.inert:
            return Verdict.allow(self.policy.intensity)
        try:
            return self._decide(
                text or "",
                declared=IntensityTier.parse(declared, source="review_beat"),
                tags=tags or ("interruption", "threshold"),
            )
        except Exception as exc:  # noqa: BLE001
            return self._fallback("review_beat", exc, safe=Disposition.FADE)

    def review_narration(self, text: str, *, declared: Any = None) -> Verdict:
        """
        Inspect prose before it reaches the player.

        The last line, and the weakest one: by the time there is prose, the
        turn has been planned and resolved. It exists because the earlier
        surfaces read intent and this one reads what was actually written.

        Falls back to FADE on internal failure when the policy is active.
        """
        if self.policy.inert:
            return Verdict.allow(self.policy.intensity)
        try:
            return self._decide(
                text or "",
                declared=IntensityTier.parse(declared, source="review_narration"),
                tags=("interruption", "time"),
            )
        except Exception as exc:  # noqa: BLE001
            return self._fallback("review_narration", exc, safe=Disposition.FADE)

    def review_plan(self, plan: Any) -> Verdict:
        """
        Inspect one agent's proposal.

        Reads the plan's ``beat`` and its choice texts. Deliberately does NOT
        read ``private``: that field is the character's own reasoning, it is
        withheld from the other agent and from every log, and a safety layer
        that read it would be the leak the knowledge partition exists to
        prevent. A motive is not content. What the character DOES is content,
        and that is the beat.

        Duck-typed rather than importing ``AgentPlan``: this package must not
        depend on the agents package, because the agents package will import
        this one.
        """
        if self.policy.inert:
            return Verdict.allow(self.policy.intensity)
        try:
            parts: list[str] = [str(getattr(plan, "beat", "") or "")]
            for choice in getattr(plan, "choices", ()) or ():
                parts.append(str(getattr(choice, "text", "") or ""))
                parts.append(str(getattr(choice, "whisper", "") or ""))
            declared = getattr(plan, "extras", {}) or {}
            return self._decide(
                "\n".join(p for p in parts if p),
                declared=IntensityTier.parse(
                    declared.get("intensity") if isinstance(declared, dict) else None,
                    source="plan.extras.intensity",
                ),
                tags=("interruption", "threshold"),
            )
        except Exception as exc:  # noqa: BLE001
            return self._fallback("review_plan", exc, safe=Disposition.FADE)

    # -- outputs -----------------------------------------------------------

    def rename(self, text: str) -> str:
        """
        Apply cosmetic substitutions to a display string.

        ``DAY-01-GUEST.md:152``: an item renames itself when its noun lands on a
        player limit -- "same mechanics, cosmetic rename from boundaries". This
        is that, and it is deliberately a pure string function: it never sees an
        id, so the renamed thing cannot diverge mechanically from the thing.

        Returns the input unchanged on any failure. A display string that did
        not get renamed is a cosmetic problem; an exception here would be a
        blank inventory panel.
        """
        if self.policy.inert or not text:
            return text
        try:
            return self.policy.sheet.rename(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[safety] Cosmetic rename failed, leaving the text as written "
                "(operation=rename): %s",
                exc,
            )
            return text

    def fade_card(
        self,
        verdict: Verdict,
        *,
        summary: str = "",
        outcomes: Sequence[str] = (),
        heading: str = "",
    ) -> Optional[FadeCard]:
        """
        Build the summary card for a faded verdict.

        The ``outcomes`` argument is what the caller ALREADY applied, rendered
        for display. This method applies nothing -- see ``verdict.py``.
        """
        try:
            return fade_card(
                verdict,
                summary=summary,
                outcomes=tuple(outcomes),
                heading=heading,
                aftercare=self.policy.aftercare,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[safety] Fade card build failed (operation=fade_card): %s", exc
            )
            return None

    def directive_text(self) -> str:
        """
        The standing constraint block for the GM prompt.

        Returns "" for an inert policy, which of the shipped stories is only the
        flagship: no text, no tokens, no change to a budget that is already over
        (R-01). Wicked-garden, neon-city and dev-story resolve non-inert, so they
        DO spend budget here -- this block is a real line item on three of four,
        which is the reason the paragraph below is about saying less, not more.

        WHAT IT DOES AND DOES NOT SAY. It names the tier and the limit TOPICS.
        It never lists the limit NOUNS. Enumerating the exact surface forms a
        player does not want to read puts those words in the context window,
        where they are as available to the sampler as anything else -- a prompt
        that lists what not to write is a prompt that has written it. The topics
        are enough for the model to steer; the enforcement is the gate, not this
        paragraph. That is the requirement to enforce structurally rather than
        by prompt text, applied to the prompt text itself.
        """
        if self.policy.inert:
            return ""
        try:
            lines = [
                "CONTENT LIMITS (product layer -- above every character's wants):",
                f"- Intensity in force: {self.policy.intensity.value}. Anything "
                "beyond it is summarised at a distance, not written in detail.",
            ]
            hard = tuple(l.topic for l in self.policy.sheet.hard_nos)
            if hard:
                lines.append(
                    "- Off the table entirely: " + ", ".join(hard) + "."
                )
            soft = tuple(
                l.topic
                for l in self.policy.sheet.soft_nos
                if l.topic not in set(self.policy.sheet.green_lights)
            )
            if soft:
                lines.append("- Handled at a distance: " + ", ".join(soft) + ".")
            lines.append(
                "- If a scene reaches a limit, redirect IN FICTION -- an "
                "interruption, an errand, a closed door. Never announce a "
                "refusal, never apologise, never mention rules or settings."
            )
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[safety] Directive build failed, contributing nothing "
                "(operation=directive_text): %s",
                exc,
            )
            return ""


def gate_for(state: Optional[Any] = None) -> SafetyGate:
    """Convenience: the gate for a game state, or the process default."""
    return SafetyGate.for_state(state)


__all__ = [
    "FADE_SUMMARY_HINT",
    "SafetyGate",
    "gate_for",
]

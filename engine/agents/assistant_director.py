"""
Assistant Director — whether the companion shows up, and whether it is right
===========================================================================

Today the Assistant speaks on a flat coin-flip: ``help_probability`` against one
RNG draw, the same odds whether the player is chatting in the bakery or bleeding
out in the barrows. It has no reason to appear and no reason to be wrong.

This decides three things instead of one:

  * **whether** it appears — base willingness, raised by the player's struggle
    and by the drama of the phase, lowered if it just spoke.
  * **with what intent** — quip, hint, lore, warning, or a gift at the moment
    the gift matters.
  * **how reliably** — ``0.45 + 0.5 * trust``. At zero trust the companion is
    right barely half the time.

THAT LAST NUMBER IS THE FEATURE, not a bug to be tuned away. A companion that
is always correct is a hint system with a personality bolted on; the player
optimises around it and stops thinking. One that may be confidently wrong until
you have earned its trust makes trust a mechanic and makes its advice worth
weighing. ``reliable=False`` does not mean "say nothing" -- it means the caller
should let it be wrong.

COMPATIBILITY. In a calm default state (no struggle, dormant phase, no recent
appearance) the appear-roll consumes exactly one draw against exactly
``help_probability``, so a session that never gets tense behaves as before and
replays identically from the same seed. Bonuses only apply under pressure.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Optional

from engine.config import get_config
from engine.game.rng import ASSISTANT as RNG_ASSISTANT
from engine.game.rng import world_rng
from engine.game.state import EvilPhase, GameState

logger = logging.getLogger(__name__)

INTENT_SILENT = "silent"
INTENT_QUIP = "quip"
INTENT_HINT = "hint"
INTENT_LORE = "lore"
INTENT_WARNING = "warning"
INTENT_GIFT = "gift"

#: Ordered phases, for the drama ramp. Indexing the enum keeps this in step
#: with engine/game/evil_ticker.py without importing its thresholds.
_PHASE_ORDER: tuple[EvilPhase, ...] = (
    EvilPhase.DORMANT,
    EvilPhase.STIRRING,
    EvilPhase.SPREADING,
    EvilPhase.CONSUMING,
)

#: Turn flags. Underscore-prefixed because they are director bookkeeping, not
#: world state a designer would ever gate content on. They hold a turn NUMBER
#: rather than a boolean -- ``GameState.flags`` is annotated ``dict[str, bool]``
#: but is only ever read for truthiness or compared explicitly, and a cooldown
#: needs to know when, not whether. Both survive a save round trip unchanged.
FLAG_LAST_TURN = "_assistant_last_turn"
FLAG_GIFT_TURN = "_assistant_gift_turn"


@dataclass
class AssistantDecision:
    """What the director decided for one turn."""

    appear: bool = False
    intent: str = INTENT_SILENT
    reliability: float = 1.0
    reliable: bool = True
    gift_item: Optional[dict[str, str]] = None
    score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "appear": self.appear,
            "intent": self.intent,
            "reliability": round(self.reliability, 3),
            "reliable": self.reliable,
            "gift_item": self.gift_item,
            "score": round(self.score, 3),
            "reason": self.reason,
        }


class AssistantDirector:
    """Decides whether, why and how well the Assistant intervenes."""

    #: Turns between unsolicited gifts. A companion that hands you a poultice
    #: every fight is a vending machine.
    GIFT_COOLDOWN = 5

    #: Turns within which a repeat appearance is discouraged.
    RECENT_WINDOW = 2

    #: Penalty for having just spoken.
    RECENT_PENALTY = 0.3

    #: Struggle at or above this is "real danger" and pins the appear chance high.
    RESCUE_THRESHOLD = 0.85
    RESCUE_FLOOR = 0.9

    def decide(
        self,
        state: GameState,
        *,
        rng: Optional[random.Random] = None,
    ) -> AssistantDecision:
        """
        Decide this turn's intervention.

        Args:
            state: Game state. Read only; the caller records the appearance.
            rng: Optional override. Defaults to the deterministic assistant
                stream, so whether the companion spoke replays from a seed.

        Returns:
            AssistantDecision. ``appear=False`` means stay silent.
        """
        draw = rng if rng is not None else world_rng(state, RNG_ASSISTANT)
        mind = state.assistant_mind
        trust = max(0.0, min(1.0, mind.trust_level / 100.0))

        struggle = self._struggle(state)
        drama = self._drama(state)
        penalty = self.RECENT_PENALTY if self._spoke_recently(state) else 0.0

        score = float(mind.help_probability) + struggle + drama - penalty
        if struggle >= self.RESCUE_THRESHOLD:
            # The one moment it should not be indifferent.
            score = max(score, self.RESCUE_FLOOR)
        score = max(0.0, min(1.0, score))

        # The appear roll is drawn FIRST and compared exactly as the legacy
        # should_assistant_speak did, so a calm turn is bit-identical.
        if draw.random() > score:
            return AssistantDecision(
                appear=False,
                intent=INTENT_SILENT,
                score=score,
                reason="indifferent",
            )

        reliability = max(0.0, min(1.0, 0.45 + 0.5 * trust))
        reliable = draw.random() <= reliability
        intent, gift = self._intent(state, trust, struggle, drama, draw)

        logger.debug(
            "[assistant_director] Appearing (operation=decide, intent=%s, "
            "score=%.2f, reliability=%.2f, reliable=%s)",
            intent,
            score,
            reliability,
            reliable,
        )
        return AssistantDecision(
            appear=True,
            intent=intent,
            reliability=reliability,
            reliable=reliable,
            gift_item=gift,
            score=score,
            reason=intent,
        )

    # -- signals ---------------------------------------------------------

    @staticmethod
    def _struggle(state: GameState) -> float:
        """
        How badly the turn is going, 0..1.

        Maximum rather than sum: a player who is wounded AND starving is in one
        bad situation, not two, and adding the signals would saturate the score
        long before the situation was actually dire.
        """
        signal = 0.0
        if state.encounter:
            signal = max(signal, 0.4)
        hp_fraction = state.stats.hp / max(1, state.stats.max_hp)
        if hp_fraction < 0.4:
            signal = max(signal, 0.6)
        if hp_fraction < 0.2:
            signal = max(signal, 0.85)
        if state.wounds:
            signal = max(signal, 0.35)
        # Against the EFFECTIVE cap: a hungry player pinned at 40/100 is out of
        # stamina even though the raw number does not look like it.
        if state.stats.stamina < max(1, state.effective_stamina_cap) * 0.15:
            signal = max(signal, 0.4)
        return signal

    @staticmethod
    def _drama(state: GameState) -> float:
        """Escalation pressure from the evil phase."""
        try:
            index = _PHASE_ORDER.index(state.evil_phase)
        except ValueError:
            index = 0
        return 0.15 * index

    def _spoke_recently(self, state: GameState) -> bool:
        last = state.flags.get(FLAG_LAST_TURN)
        return isinstance(last, int) and (state.turn_number - last) < self.RECENT_WINDOW

    def _gifted_recently(self, state: GameState) -> bool:
        last = state.flags.get(FLAG_GIFT_TURN)
        return isinstance(last, int) and (state.turn_number - last) < self.GIFT_COOLDOWN

    def _intent(
        self,
        state: GameState,
        trust: float,
        struggle: float,
        drama: float,
        draw: random.Random,
    ) -> tuple[str, Optional[dict[str, str]]]:
        """Pick what it turns up to do."""
        if struggle >= 0.4:
            # Gifts need earned trust: a companion the player does not trust
            # handing over an item is a plot device, not a relationship.
            if trust >= 0.3 and not self._gifted_recently(state):
                if draw.random() <= 0.5:
                    gift = self._pick_gift(state)
                    if gift is not None:
                        return INTENT_GIFT, gift
            return INTENT_HINT, None

        reflection_min = float(get_config().get("awareness.reflection_form_min", 40))
        if state.awareness >= reflection_min:
            return INTENT_LORE, None
        if drama >= 0.3:
            return INTENT_WARNING, None
        return INTENT_QUIP, None

    @staticmethod
    def _pick_gift(state: GameState) -> Optional[dict[str, str]]:
        """
        The right item for the actual problem, or nothing.

        Returning None is a real answer: a companion that produces a bandage
        for a player who is merely tired is why the gift stops landing.
        """
        hp_fraction = state.stats.hp / max(1, state.stats.max_hp)
        if hp_fraction < 0.5:
            return {"id": "bandage_poultice", "name": "Bandage Poultice"}
        if state.wounds:
            return {"id": "bandage_poultice", "name": "Bandage Poultice"}
        if state.stats.stamina < max(1, state.effective_stamina_cap) * 0.3:
            return {"id": "forest_tonic", "name": "Forest Tonic"}
        return None


def record_appearance(state: GameState, decision: AssistantDecision) -> None:
    """
    Note that the companion appeared, so the cooldowns mean something.

    Separated from ``decide`` because deciding must stay side-effect free --
    a caller that previews a decision and then discards it (a retry, a
    rejected draft) must not have burned the cooldown.
    """
    if not decision.appear:
        return
    state.flags[FLAG_LAST_TURN] = state.turn_number
    if decision.intent == INTENT_GIFT:
        state.flags[FLAG_GIFT_TURN] = state.turn_number


__all__ = [
    "FLAG_GIFT_TURN",
    "FLAG_LAST_TURN",
    "INTENT_GIFT",
    "INTENT_HINT",
    "INTENT_LORE",
    "INTENT_QUIP",
    "INTENT_SILENT",
    "INTENT_WARNING",
    "AssistantDecision",
    "AssistantDirector",
    "record_appearance",
]

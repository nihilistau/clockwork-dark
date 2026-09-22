"""
Storyteller Evaluator
=====================

Quality gate for Storyteller output — especially anti-hallucination
for mechanical claims without tool receipts, and for characters who are not
in the room.

Two criteria can fail a turn on their own rather than by dragging the weighted
total down: a mechanical outcome with no tool receipt, and a named character
who is not present. Both are the same kind of error — the model asserting
something the engine did not give it — and both are worth a retry even when the
prose around them is good.

Version: v0.3.0 [2026-09-23]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from engine.agents.cast import cast_note, find_intrusion
from engine.agents.continuity import continuity_note, find_reintroduction


_MECHANICS_CLAIM = re.compile(
    r"(?i)\b("
    r"rolled?\s+(a\s+)?\d+|"
    r"natural\s+(1|20)|"
    r"nat\s+(1|20)|"
    r"you\s+(succeed|fail|passed|failed)|"
    r"beat\s+the\s+dc|"
    r"against\s+dc\s*\d+"
    r")\b"
)

#: Registered skills that roll dice INSIDE themselves. A receipt from any of
#: these IS the roll. Counting only `roll_dice` and `resolve_skill_check`
#: scored a real work shift, honestly narrated as a success, at 0.2 and forced a
#: retry -- which pushed the narrator AWAY from reporting real outcomes, the
#: opposite of what this gate exists to do.
ROLLING_SKILLS = frozenset(
    {
        "roll_dice",
        "resolve_skill_check",
        "work",
        "forage",
        "encounter_approach",
        "resolve_scene_card",
        "resolve_challenge",
    }
)

# Anchored to a sentence start or a plain "and", so "Whether you succeed
# tomorrow is another matter" and "You don't succeed" are not claims.
_CLAIMS_SUCCESS = re.compile(
    r"(?i)(?:^|[.!?]\s+|\band\s+)you\s+(?:succeed|manage\s+it|pull\s+it\s+off)\b"
)
_CLAIMS_ARRIVAL = re.compile(
    r"(?i)(?:^|[.!?]\s+|\band\s+)you\s+(?:arrive|reach|come\s+out\s+at|step\s+into)\b"
)


def contradicts(narration: str, receipts: Sequence[Mapping[str, Any]]) -> str:
    """
    A note when the prose states the OPPOSITE of what the engine decided.

    Deliberately narrow: two unambiguous opposites and nothing else -- success
    narrated over a failed check, and arrival narrated over a refused move.
    Anything subtler is a judgement a regex cannot make, and a gate that fires
    on honest prose is a gate somebody deletes.

    Returns:
        A short note naming the contradiction, or "" when there is none.
    """
    for receipt in receipts:
        result = receipt.get("result")
        result = result if isinstance(result, Mapping) else {}
        skill = receipt.get("skill")
        if skill == "resolve_skill_check" and result.get("success") is False:
            if _CLAIMS_SUCCESS.search(narration):
                return "narrated success over a failed check"
        if skill in ("move_to", "travel") and (
            receipt.get("refused") or receipt.get("success") is False
        ):
            if _CLAIMS_ARRIVAL.search(narration):
                return "narrated arrival over a refused move"
    return ""


@dataclass
class EvaluationResult:
    """Evaluator scorecard."""

    overall: float
    tone: float
    lore: float
    no_hallucinated_mechanics: float
    length: float
    valid_json: float
    choices: float
    passed: bool
    #: 1.0 when the prose named nobody who is absent, 0.0 when it did. A story
    #: with no NPC roster always scores 1.0 -- there is nothing to intrude.
    cast: float = 1.0
    #: 1.0 when the prose agreed with what the world remembers, 0.0 when it
    #: introduced somebody the ledger says the player has already met. Inert
    #: (1.0) on turn zero and for a story with no roster: no history is not a
    #: contradiction.
    continuity: float = 1.0
    notes: list[str] = field(default_factory=list)
    flag: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "tone": self.tone,
            "lore": self.lore,
            "no_hallucinated_mechanics": self.no_hallucinated_mechanics,
            "length": self.length,
            "valid_json": self.valid_json,
            "choices": self.choices,
            "cast": self.cast,
            "continuity": self.continuity,
            "passed": self.passed,
            "notes": self.notes,
            "flag": self.flag,
        }


class StorytellerEvaluator:
    """Score Storyteller turns against a 6-point rubric."""

    PASS_THRESHOLD = 0.6
    MECHANICS_FAIL_THRESHOLD = 0.5
    CAST_FAIL_THRESHOLD = 0.5
    #: Same shape as the cast gate, and for the same reason: a narrator that
    #: has forgotten who the player knows has written the wrong scene, not a
    #: slightly worse one, so it is a hard fail rather than a weighted nudge.
    CONTINUITY_FAIL_THRESHOLD = 0.5

    def evaluate(
        self,
        narration: str,
        parsed: dict[str, Any],
        *,
        tool_receipts: list[dict[str, Any]],
        lore_snippets: list[str] | None = None,
        absent_cast: Optional[Mapping[str, Sequence[str]]] = None,
        known_cast: Optional[Mapping[str, Sequence[str]]] = None,
        player_action: str = "",
    ) -> EvaluationResult:
        """
        Score a Storyteller turn.

        Args:
            narration: Prose narration text.
            parsed: Parsed JSON epilogue dict.
            tool_receipts: Skills invoked this turn.
            lore_snippets: Optional RAG chunks for lore check.
            absent_cast: ``{npc_id: (surface forms...)}`` from
                ``engine.agents.cast.absent_cast`` -- characters this story
                knows who are NOT in the scene and whom the player has never
                met. Empty or omitted (a story with no NPC roster, or a
                caller with no state) makes the criterion inert rather than
                failing.
            player_action: The player's own words, so a character the PLAYER
                named is not counted against the narrator.

        Returns:
            EvaluationResult with pass/fail.
        """
        notes: list[str] = []
        lore_snippets = lore_snippets or []

        tone = self._score_tone(narration)
        lore = self._score_lore(narration, lore_snippets)
        mechanics = self._score_mechanics(narration, parsed, tool_receipts, notes)
        length = self._score_length(narration)
        valid_json = 1.0 if parsed.get("narration") else 0.0
        choices = self._score_choices(parsed.get("choices", []))
        cast = self._score_cast(narration, absent_cast, player_action, notes)
        continuity = self._score_continuity(narration, known_cast, notes)

        if not parsed.get("narration"):
            notes.append("Missing narration in JSON epilogue.")
        if mechanics < self.MECHANICS_FAIL_THRESHOLD:
            notes.append("Mechanical outcome claimed without tool receipt.")

        overall = (
            tone * 0.15
            + lore * 0.15
            + mechanics * 0.3
            + length * 0.1
            + valid_json * 0.1
            + choices * 0.1
            + cast * 0.1
        )
        # Not in the weighted sum. Both cast and continuity are GATES: a scene
        # with the wrong people in it, or one that forgets who the player
        # knows, does not become acceptable by scoring well on tone. Adding
        # them to the average would let exactly that happen.

        passed = (
            overall >= self.PASS_THRESHOLD
            and mechanics >= self.MECHANICS_FAIL_THRESHOLD
            and cast >= self.CAST_FAIL_THRESHOLD
            and continuity >= self.CONTINUITY_FAIL_THRESHOLD
        )

        return EvaluationResult(
            overall=round(overall, 3),
            tone=round(tone, 3),
            lore=round(lore, 3),
            no_hallucinated_mechanics=round(mechanics, 3),
            length=round(length, 3),
            valid_json=round(valid_json, 3),
            choices=round(choices, 3),
            cast=round(cast, 3),
            continuity=round(continuity, 3),
            passed=passed,
            notes=notes,
            flag=not passed,
        )

    @staticmethod
    def _score_cast(
        narration: str,
        absent_cast: Optional[Mapping[str, Sequence[str]]],
        player_action: str,
        notes: list[str],
    ) -> float:
        """
        Penalise a narration that walks an absent character into the scene.

        The note is the feedback the retry gets, so it names the character.
        Anything else ("do not invent people") is unactionable: the model has
        no way to know which of the names it wrote was the wrong one.
        """
        if not absent_cast:
            return 1.0
        intruder = find_intrusion(
            narration,
            {k: tuple(v) for k, v in absent_cast.items()},
            player_action=player_action,
        )
        if intruder is None:
            return 1.0
        notes.append(cast_note(intruder))
        return 0.0

    @staticmethod
    def _score_continuity(
        narration: str,
        known_cast: Optional[Mapping[str, Sequence[str]]],
        notes: list[str],
    ) -> float:
        """
        Penalise a narration that meets somebody the player already knows.

        Inert without a `known_cast`, which is the honest default: turn zero,
        a story with no roster, and a caller with no ledger all have no history
        to contradict, and failing them would be inventing a rule.
        """
        if not known_cast:
            return 1.0
        forgotten = find_reintroduction(
            narration, {k: tuple(v) for k, v in known_cast.items()}
        )
        if forgotten is None:
            return 1.0
        notes.append(continuity_note(forgotten))
        return 0.0

    @staticmethod
    def _score_tone(narration: str) -> float:
        """Grounded fantasy tone heuristic."""
        if not narration.strip():
            return 0.0
        lower = narration.lower()
        penalty = 0.0
        if any(w in lower for w in ("fireball", "lol", "npc", "hit points", "mana bar")):
            penalty += 0.4
        # No bonus for any story's nouns. This rewarded "mist", "oven" and
        # "tinker" -- the flagship's village -- so every other story's
        # narration scored lower for being set somewhere else.
        return max(0.0, min(1.0, 0.75 - penalty))

    @staticmethod
    def _score_lore(narration: str, snippets: list[str]) -> float:
        """Lore consistency against retrieved RAG chunks."""
        if not snippets:
            return 0.8
        text = narration.lower()
        hits = 0
        for snippet in snippets:
            words = [w for w in snippet.lower().split() if len(w) > 4][:6]
            if any(w in text for w in words):
                hits += 1
        return min(1.0, 0.55 + hits * 0.15)

    def _score_mechanics(
        self,
        narration: str,
        parsed: dict[str, Any],
        tool_receipts: list[dict[str, Any]],
        notes: list[str],
    ) -> float:
        """
        Penalize dice/outcome claims without matching receipts, and prose that
        contradicts the receipts it has.
        """
        contradiction = contradicts(narration, tool_receipts)
        if contradiction:
            notes.append(contradiction)
            return 0.0

        skill_names = {r.get("skill") for r in tool_receipts}
        has_roll = bool(skill_names & ROLLING_SKILLS)

        claims_mechanics = bool(_MECHANICS_CLAIM.search(narration))
        skill_check = parsed.get("skill_check")
        needs_roll = skill_check is not None and skill_check is not False

        if needs_roll and not has_roll:
            notes.append("skill_check requested in JSON but no resolve_skill_check called.")
            return 0.0

        if claims_mechanics and not has_roll:
            return 0.2

        if needs_roll and has_roll:
            return 1.0
        return 1.0

    @staticmethod
    def _score_length(narration: str) -> float:
        words = len(narration.split())
        if 40 <= words <= 200:
            return 1.0
        if 20 <= words < 40 or 200 < words <= 280:
            return 0.7
        return 0.4

    @staticmethod
    def _score_choices(choices: list[Any]) -> float:
        if not isinstance(choices, list):
            return 0.0
        n = len(choices)
        if 2 <= n <= 4:
            return 1.0
        if n == 1:
            return 0.5
        return 0.3
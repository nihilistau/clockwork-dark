"""
Oracle — turn telemetry
=======================

A ring buffer of recent turns plus running aggregates, so the Assistant, the
Storyteller prompt and the governance rules can be tuned against data instead
of against vibes.

THE MEASUREMENT THIS EXISTS FOR: the engine owns every mechanical mutation, so
when a model writes ``"stat_changes": {"gold": 50}`` into its narration JSON
nothing happens -- the claim is dropped on the floor and the turn looks fine.
That silence is the problem. A model that tries to award itself fifty gold on
one turn in three is not a rules violation the player ever sees; it is a *prompt
defect*, and the only way to know it is happening is to count it. So unearned
claims are recorded per stat with their sizes, and ``metrics()`` surfaces them.

Pure in-memory and process-wide. Nothing here is persisted: these are numbers
about a running process, not about a save file.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# How many recent turns stay individually inspectable. Aggregates are computed
# incrementally and are NOT limited by this, so a long session still reports an
# honest lifetime average.
DEFAULT_RING = 200


@dataclass
class UnearnedClaim:
    """
    Running tally of one stat the model claimed without a tool receipt.

    ``max_delta`` is kept because size is diagnostic: a model nudging gold by 1
    is sloppy prose, a model claiming +500 is a prompt that has lost the plot,
    and an average would hide the difference between them.
    """

    stat: str
    count: int = 0
    total_delta: int = 0
    max_delta: int = 0

    def record(self, delta: int) -> None:
        self.count += 1
        self.total_delta += delta
        if abs(delta) > abs(self.max_delta):
            self.max_delta = delta

    def to_dict(self) -> dict[str, Any]:
        return {
            "stat": self.stat,
            "count": self.count,
            "total_delta": self.total_delta,
            "max_delta": self.max_delta,
        }


@dataclass
class TurnRecord:
    """One turn, as the Oracle saw it."""

    turn: int
    latency_ms: float = 0.0
    violations: int = 0
    rule_ids: list[str] = field(default_factory=list)
    assistant_spoke: bool = False
    assistant_intent: str = "silent"
    assistant_reliable: bool = True
    gift: bool = False
    tools: int = 0
    evil_progress: float = 0.0
    challenge_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "latency_ms": round(self.latency_ms, 1),
            "violations": self.violations,
            "rule_ids": list(self.rule_ids),
            "assistant_spoke": self.assistant_spoke,
            "assistant_intent": self.assistant_intent,
            "assistant_reliable": self.assistant_reliable,
            "gift": self.gift,
            "tools": self.tools,
            "evil_progress": round(self.evil_progress, 4),
            "challenge_kind": self.challenge_kind,
        }


class Oracle:
    """
    Turn metrics with a recent-turn ring buffer.

    Not thread-safe by design. The turn loop is serial per session, and a lock
    around a counter would cost more than the number is worth.
    """

    def __init__(self, *, ring: int = DEFAULT_RING) -> None:
        self._ring: deque[TurnRecord] = deque(maxlen=ring)
        self._turns = 0
        self._violation_turns = 0
        self._violations_total = 0
        self._rule_counts: dict[str, int] = {}
        self._assistant_spoke = 0
        self._assistant_misled = 0
        self._gifts = 0
        self._latency_sum = 0.0
        self._last_evil = 0.0
        self._unearned: dict[str, UnearnedClaim] = {}
        self._challenges: dict[str, int] = {}

    # -- recording -------------------------------------------------------

    def record_turn(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        latency_ms: float = 0.0,
        evil_progress: float = 0.0,
    ) -> TurnRecord:
        """
        Fold one finished turn into the aggregates.

        Args:
            payload: The turn payload as sent to the client. Every key is
                optional -- a caller wiring this in incrementally should not
                have to construct a complete record to get latency counted.
            latency_ms: Wall time for the whole turn.
            evil_progress: Doom progress after the turn.

        Returns:
            The stored record.
        """
        data = payload or {}
        governance = data.get("governance") or []
        assistant = data.get("assistant") or {}
        challenge = data.get("challenge") or {}

        rule_ids = [
            str(v.get("rule_id", "")) for v in governance if isinstance(v, dict)
        ]
        record = TurnRecord(
            turn=self._turns + 1,
            latency_ms=float(latency_ms),
            violations=len(governance),
            rule_ids=rule_ids,
            assistant_spoke=bool(assistant.get("spoke", False)),
            assistant_intent=str(assistant.get("intent", "silent")),
            assistant_reliable=bool(assistant.get("reliable", True)),
            gift=bool(assistant.get("gift")),
            tools=len(data.get("tool_receipts") or []),
            evil_progress=float(evil_progress),
            challenge_kind=str(challenge.get("kind", "")),
        )

        self._ring.append(record)
        self._turns += 1
        if record.violations:
            self._violation_turns += 1
            self._violations_total += record.violations
        for rule_id in rule_ids:
            if rule_id:
                self._rule_counts[rule_id] = self._rule_counts.get(rule_id, 0) + 1
        if record.assistant_spoke:
            self._assistant_spoke += 1
            if not record.assistant_reliable:
                self._assistant_misled += 1
        if record.gift:
            self._gifts += 1
        if record.challenge_kind:
            self._challenges[record.challenge_kind] = (
                self._challenges.get(record.challenge_kind, 0) + 1
            )
        self._latency_sum += record.latency_ms
        self._last_evil = record.evil_progress
        return record

    def record_unearned_claim(self, stat: str, delta: int) -> None:
        """
        Note that the model claimed a stat delta it had no receipt for.

        Called by the governance RulesGovernor (R003). The engine already
        ignored the claim; this is the only place it becomes visible.
        """
        name = str(stat).strip() or "unknown"
        try:
            amount = int(delta)
        except (TypeError, ValueError):
            amount = 0
        claim = self._unearned.get(name)
        if claim is None:
            claim = UnearnedClaim(stat=name)
            self._unearned[name] = claim
        claim.record(amount)
        logger.debug(
            "[telemetry] Unearned claim recorded "
            "(operation=record_unearned_claim, stat=%s, delta=%+d, seen=%d)",
            name,
            amount,
            claim.count,
        )

    # -- reading ---------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        """Aggregates over every turn seen, not just the ring."""
        # Rates on a fresh Oracle must read 0.0, not divide by zero. Guarding
        # the denominator rather than the whole block keeps the key set stable,
        # which matters because a metrics endpoint with conditional keys is one
        # a dashboard cannot render.
        turns = self._turns or 1
        return {
            "turns": self._turns,
            "violation_rate": round(self._violation_turns / turns, 3),
            "violations_total": self._violations_total,
            "violations_by_rule": dict(sorted(self._rule_counts.items())),
            "assistant_intervention_rate": round(self._assistant_spoke / turns, 3),
            "assistant_misled_count": self._assistant_misled,
            "gifts": self._gifts,
            "avg_latency_ms": round(self._latency_sum / turns, 1),
            "last_evil_progress": round(self._last_evil, 4),
            "unearned_claims": {
                stat: claim.to_dict()
                for stat, claim in sorted(self._unearned.items())
            },
            "unearned_claims_total": sum(c.count for c in self._unearned.values()),
            "challenges_started": dict(sorted(self._challenges.items())),
        }

    def recent(self, count: int = 20) -> list[dict[str, Any]]:
        """The last ``count`` turn records, oldest first."""
        limit = max(0, int(count))
        return [r.to_dict() for r in list(self._ring)[-limit:]] if limit else []


_oracle: Optional[Oracle] = None


def get_oracle() -> Oracle:
    """Process-wide Oracle."""
    global _oracle
    if _oracle is None:
        _oracle = Oracle()
    return _oracle


def reset_oracle() -> None:
    """Drop the collector. Tests, and any place a fresh session must start clean."""
    global _oracle
    _oracle = None

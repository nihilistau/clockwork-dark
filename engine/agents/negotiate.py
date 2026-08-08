"""
Negotiation
===========

Reconciling two agents' proposals into one turn, before anything is committed.

WHY RULES ARE DATA. A second story's design states its conflict resolutions as a
table -- "Sophia blocks exit vs player invoked the Threshold Law correctly: the
law wins, and her regard shifts"; "her private scene vs a world event: the scene
completes and the event becomes aftermath"; "product safety vs any character
goal: safety wins". Those are that story's dramatic priorities, not the
engine's. Written as Python they would be one story's `if` chain in a module
every story imports, which is the exact shape this whole overhaul is undoing.

So a rule is a row: which agents, which intents, who wins, and what it costs.
A story ships its own table; the engine ships the two rules that are structural
rather than dramatic and therefore belong to everyone:

    SAFETY_FIRST   a refusal from the safety layer outranks every agent goal,
                   including the world's. Not overridable by a story table --
                   a story that could reorder this could write itself above the
                   player's stated limits.
    OWNERSHIP      an agent may not act as a voice it does not own, or write a
                   value it does not own. Enforced elsewhere too (the skill ACL
                   at dispatch, the state store's per-field owners); repeated
                   here because negotiation is where an agent's INTENT to do it
                   is visible, and recording the attempt is worth more than
                   silently dropping it.

WHAT NEGOTIATION IS NOT. It does not merge prose and it does not choose words.
It decides whose intent shapes the turn, which choices reach the player, and
what each side gives up -- then narration happens once, downstream, knowing the
answer. Two agents writing prose independently and stitching it together is the
failure mode this exists to avoid.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from engine.agents.plan import AgentPlan, ProposedChoice

logger = logging.getLogger(__name__)

#: Structural rules the engine always applies, ahead of any story table.
RULE_SAFETY = "safety_first"
RULE_OWNERSHIP = "ownership"
#: Applied last, when nothing else decided it.
RULE_CONFIDENCE = "confidence"


@dataclass
class Resolution:
    """
    One decision the negotiator made, and why.

    Recorded rather than merely applied. A turn where the companion wanted to
    interrupt and the world won is a turn whose shape has an explanation, and
    without this the only evidence is prose that reads slightly differently.
    """

    rule: str
    winner: str = ""
    loser: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "winner": self.winner,
            "loser": self.loser,
            "detail": self.detail,
        }


@dataclass
class NegotiatedTurn:
    """The single agreed shape of a turn, handed to narration and commit."""

    #: Whose intent leads. Narration is written from this agent's beat.
    lead: str = ""
    #: Beats that survived, in the order they should be narrated.
    beats: list[str] = field(default_factory=list)
    choices: list[ProposedChoice] = field(default_factory=list)
    #: Plans as accepted, keyed by agent. Effects are applied from these.
    accepted: dict[str, AgentPlan] = field(default_factory=dict)
    resolutions: list[Resolution] = field(default_factory=list)
    #: Set when the safety layer refused the turn's direction entirely. The
    #: caller is expected to redirect IN FICTION rather than emit a refusal.
    blocked: bool = False
    block_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead": self.lead,
            "beats": list(self.beats),
            "choices": [c.to_dict() for c in self.choices],
            "resolutions": [r.to_dict() for r in self.resolutions],
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


@dataclass(frozen=True)
class Rule:
    """
    One story-declared resolution.

    Attributes:
        name: Identifier, recorded on the Resolution it produces.
        when: Intent pairs this rule covers, as ``{agent_id: intent}``. A rule
            matches when every named agent holds the named intent. An empty
            mapping matches nothing -- a rule that fires on everything is
            almost certainly a mistake, and defaulting to "always" would make
            table order silently load-bearing.
        winner: Agent id whose intent leads when this rule fires.
        keep_loser_beat: Whether the losing agent's beat still appears, demoted.
            The Garden's "the event becomes aftermath" is exactly this: the
            world does not lose its content, it loses the lead.
        detail: Human-readable reason, recorded.
    """

    name: str
    when: dict[str, str] = field(default_factory=dict)
    winner: str = ""
    keep_loser_beat: bool = True
    detail: str = ""

    def matches(self, plans: dict[str, AgentPlan]) -> bool:
        if not self.when:
            return False
        for agent, intent in self.when.items():
            plan = plans.get(agent)
            if plan is None or plan.intent != intent:
                return False
        return True


def rules_from_data(rows: Any) -> list[Rule]:
    """
    Build a rule table from a story's declaration.

    Malformed rows are skipped with a warning rather than raising: a story with
    one bad rule should lose that rule, not the ability to take a turn. The two
    structural rules are applied regardless of what this returns.
    """
    table: list[Rule] = []
    for row in rows or []:
        if not isinstance(row, dict):
            logger.warning("[negotiate] Skipping non-mapping rule row: %r", row)
            continue
        name = str(row.get("name") or "").strip()
        when = row.get("when") or {}
        if not name or not isinstance(when, dict) or not when:
            logger.warning(
                "[negotiate] Skipping rule with no name or no 'when' (name=%r)", name
            )
            continue
        table.append(
            Rule(
                name=name,
                when={str(k): str(v) for k, v in when.items()},
                winner=str(row.get("winner") or ""),
                keep_loser_beat=bool(row.get("keep_loser_beat", True)),
                detail=str(row.get("detail") or ""),
            )
        )
    return table


class Negotiator:
    """
    Reconciles plans into one turn.

    Args:
        rules: The story's resolution table. The engine's structural rules are
            applied first regardless, and cannot be reordered by a story.
        owned_voices: ``{agent_id: (voice ids,)}``, used by the ownership rule.
    """

    def __init__(
        self,
        rules: Optional[list[Rule]] = None,
        *,
        owned_voices: Optional[dict[str, tuple[str, ...]]] = None,
    ) -> None:
        self.rules = list(rules or [])
        self.owned_voices = dict(owned_voices or {})

    def negotiate(
        self,
        plans: dict[str, AgentPlan],
        *,
        safety_block: str = "",
    ) -> NegotiatedTurn:
        """
        Decide the turn.

        Args:
            plans: Every agent's proposal, keyed by agent id.
            safety_block: Non-empty when the safety layer refused this
                direction. Applied FIRST and unconditionally.

        Returns:
            The agreed turn. Never raises: a negotiation that could fail would
            be a new way to lose a player's turn, and the fallback -- the
            highest-confidence plan leads -- is always available.
        """
        turn = NegotiatedTurn()

        # 1. Safety. Ahead of everything, not orderable by a story table.
        if safety_block:
            turn.blocked = True
            turn.block_reason = safety_block
            turn.resolutions.append(
                Resolution(rule=RULE_SAFETY, winner="safety", detail=safety_block)
            )
            logger.info(
                "[negotiate] Turn direction refused by the safety layer "
                "(operation=negotiate, reason=%s)",
                safety_block,
            )
            # Deliberately NOT an early return: the caller still needs choices
            # and a lead so it can redirect in fiction rather than show the
            # player an out-of-character refusal.

        live = {a: p for a, p in plans.items() if not p.silent}
        if not live:
            turn.lead = next(iter(plans), "")
            return turn

        # 2. Ownership. An agent that proposed speaking as a voice it does not
        #    own loses that claim here, and the attempt is recorded.
        for agent, plan in list(live.items()):
            voice = plan.speaks_as
            if not voice:
                continue
            owned = self.owned_voices.get(agent, ())
            if owned and voice not in owned:
                plan.speaks_as = ""
                turn.resolutions.append(
                    Resolution(
                        rule=RULE_OWNERSHIP,
                        winner="engine",
                        loser=agent,
                        detail=f"{agent} tried to speak as '{voice}', which it does not own",
                    )
                )
                logger.warning(
                    "[negotiate] Voice claim refused (operation=negotiate, "
                    "agent=%s, voice=%s)",
                    agent,
                    voice,
                )

        # 3. The story's table, in declared order. First match wins: later rules
        #    are more specific only if the author ordered them that way, and
        #    saying so out loud beats a scoring function nobody can predict.
        lead = ""
        demoted: list[str] = []
        for rule in self.rules:
            if not rule.matches(live):
                continue
            winner = rule.winner if rule.winner in live else ""
            if not winner:
                continue
            lead = winner
            losers = [a for a in live if a != winner]
            for loser in losers:
                turn.resolutions.append(
                    Resolution(
                        rule=rule.name,
                        winner=winner,
                        loser=loser,
                        detail=rule.detail,
                    )
                )
                if rule.keep_loser_beat:
                    demoted.append(loser)
            break

        # 4. Nothing matched: the most committed agent leads.
        if not lead:
            lead = max(live, key=lambda a: live[a].confidence)
            if len(live) > 1:
                turn.resolutions.append(
                    Resolution(
                        rule=RULE_CONFIDENCE,
                        winner=lead,
                        detail="no rule matched; highest confidence leads",
                    )
                )
            demoted = [a for a in live if a != lead]

        turn.lead = lead
        turn.accepted = dict(live)

        # Beats in narration order: the lead first, then whatever survived.
        if live[lead].beat:
            turn.beats.append(live[lead].beat)
        for agent in demoted:
            plan = live.get(agent)
            if plan is not None and plan.beat:
                turn.beats.append(plan.beat)

        turn.choices = self._merge_choices(live, lead)
        return turn

    @staticmethod
    def _merge_choices(
        plans: dict[str, AgentPlan],
        lead: str,
        *,
        limit: int = 4,
    ) -> list[ProposedChoice]:
        """
        Combine both agents' proposed choices into one set.

        The lead's choices come first because they follow from the beat the
        player is about to read. Duplicates are dropped case-insensitively --
        two agents proposing "Refuse" should produce one option, not two that
        look like a rendering bug.

        Ids are assigned HERE rather than by either agent: they are positional
        (a, b, c, d) and the keyboard shortcuts depend on that, so letting an
        agent choose them would let one agent's id collide with the other's.
        """
        ordered: list[ProposedChoice] = list(plans[lead].choices)
        for agent, plan in plans.items():
            if agent != lead:
                ordered.extend(plan.choices)

        seen: set[str] = set()
        merged: list[ProposedChoice] = []
        for choice in ordered:
            key = choice.text.strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(choice)
            if len(merged) >= limit:
                break

        for index, choice in enumerate(merged):
            choice.id = chr(ord("a") + index)
        return merged


__all__ = [
    "RULE_CONFIDENCE",
    "RULE_OWNERSHIP",
    "RULE_SAFETY",
    "NegotiatedTurn",
    "Negotiator",
    "Resolution",
    "Rule",
    "rules_from_data",
]

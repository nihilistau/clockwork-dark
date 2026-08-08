"""
Knowledge Scopes
================

Which agent is allowed to know what.

THE GAP. There is exactly one redaction primitive in the engine today --
``mark_spoiler`` plus ``AwarenessGateInterceptor`` -- and it partitions by the
PLAYER's awareness, not by agent. It has one call site (the GM-only evil-phase
line) and three hardcoded regexes. Beyond that, nothing separates what one agent
sees from another: ``assistant_system_prompt`` receives the whole ``GameState``
and could read any of it. The GM-only evil snapshot is threaded to the
Storyteller alone by convention, not by enforcement.

That is survivable with a narrator and a hint system. It is not survivable with
a second character who has private motives, who is permitted to LIE in dialogue,
and whose secrets the world narrator must not be able to accidentally narrate.
Asymmetric information between agents is what makes two agents worth running;
without it you have one agent with two voices.

THE FOUR SCOPES, and who they are for:

    public_world       everything both agents may use. The default.
    gm_secrets         the world's knowledge: what is really behind the door,
                       which NPC is lying, what the doom clock is at. The
                       character agent must not read this -- not because it
                       would cheat, but because a character who knows the
                       world's secrets stops being a character.
    character_private  one character's own knowledge and motive. The world
                       narrator must not read it, or the narration quietly
                       confirms or contradicts a secret the character is still
                       keeping.
    player_facing      what may reach the browser. Already enforced by
                       `GameState.to_client_dict` and the state schema's
                       `visibility`; named here so all four live in one place.

LIES ARE TRACKED, NOT PREVENTED. A character agent may assert something the
board contradicts -- that is a feature, and the existing companion already has
an unreliability roll. What was missing is any record of WHAT was asserted
falsely, so nothing could ever catch it out later. ``record_claim`` puts the
claim in the ledger marked false, which turns "the companion lied" from a dice
roll nobody can reference into a fact a later scene can use.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

SCOPE_PUBLIC = "public_world"
SCOPE_GM = "gm_secrets"
SCOPE_CHARACTER = "character_private"
SCOPE_PLAYER = "player_facing"
SCOPES = (SCOPE_PUBLIC, SCOPE_GM, SCOPE_CHARACTER, SCOPE_PLAYER)


@dataclass(frozen=True)
class ScopeGrant:
    """
    What one agent may read.

    ``public_world`` is granted implicitly to every agent -- a scope system
    whose common case must be spelled out in every story's config is one that
    will be got wrong.
    """

    agent: str
    scopes: frozenset[str] = frozenset()

    def may_read(self, scope: str) -> bool:
        if not scope or scope == SCOPE_PUBLIC:
            return True
        return scope in self.scopes


class KnowledgePolicy:
    """
    Per-agent read permissions, declared by a story.

    Args:
        grants: ``{agent_id: [scope, ...]}``. An agent absent from this mapping
            sees only ``public_world``, which is the safe default: a story that
            forgets to grant a scope gets a slightly ignorant agent, not one
            that reads the world's secrets.
    """

    def __init__(self, grants: Optional[dict[str, Any]] = None) -> None:
        self._grants: dict[str, ScopeGrant] = {}
        for agent, scopes in (grants or {}).items():
            if isinstance(scopes, str):
                scopes = [scopes]
            named = frozenset(str(s) for s in (scopes or []) if str(s) in SCOPES)
            unknown = {str(s) for s in (scopes or [])} - set(SCOPES)
            if unknown:
                logger.warning(
                    "[knowledge] Unknown scopes ignored "
                    "(operation=__init__, agent=%s, scopes=%s)",
                    agent,
                    sorted(unknown),
                )
            self._grants[str(agent)] = ScopeGrant(agent=str(agent), scopes=named)

    def grant_for(self, agent: str) -> ScopeGrant:
        return self._grants.get(agent, ScopeGrant(agent=agent))

    def may_read(self, agent: str, scope: str) -> bool:
        return self.grant_for(agent).may_read(scope)

    def filter_blocks(
        self,
        agent: str,
        blocks: list[tuple[str, str]],
    ) -> list[str]:
        """
        Keep only the prompt blocks this agent may read.

        Args:
            agent: Who the prompt is being built for.
            blocks: ``[(scope, text), ...]`` in the order they should appear.

        Returns:
            The surviving texts. Dropping rather than redacting is deliberate:
            a redacted block still tells the agent that something was there,
            and a model that can see the shape of a secret will write around
            it in a way that reveals it.
        """
        kept: list[str] = []
        dropped = 0
        for scope, text in blocks:
            if not text:
                continue
            if self.may_read(agent, scope):
                kept.append(text)
            else:
                dropped += 1
        if dropped:
            logger.debug(
                "[knowledge] Withheld blocks (operation=filter_blocks, "
                "agent=%s, dropped=%d)",
                agent,
                dropped,
            )
        return kept

    def lore_tags_for(self, agent: str) -> tuple[str, ...]:
        """
        Lore tags this agent's retrieval may return.

        ``LoreChunk.tags`` has been stored since the lore index was written and
        filtered on by nothing -- ``search`` selects the column, returns it, and
        no caller reads it. That unused column is the scope key: a chunk tagged
        ``gm_secrets`` is simply not retrievable by an agent without the grant.
        """
        return tuple(sorted(self.grant_for(agent).scopes | {SCOPE_PUBLIC}))


def policy_from_data(data: Any) -> KnowledgePolicy:
    """Build a policy from a story's ``agents.yaml`` knowledge block."""
    if not isinstance(data, dict):
        return KnowledgePolicy()
    return KnowledgePolicy(
        {agent: row.get("reads") if isinstance(row, dict) else row
         for agent, row in data.items()}
    )


def record_claim(
    ledger: Any,
    text: str,
    *,
    agent: str,
    truthful: bool,
    turn: int = 0,
    day: int = 0,
    subject_id: str = "",
) -> None:
    """
    Note that an agent asserted something, and whether it was true.

    A character allowed to lie whose lies are not written down cannot be caught
    out, which makes the lying decorative. ``LedgerFact.kind`` already declares
    a ``secret`` value that nothing writes; a false claim is recorded with that
    kind and a marker, so a later scene can find "what did it tell me about the
    barrows" and discover the answer was invented.

    Never raises: memory is best-effort and must not cost a turn.
    """
    if not text.strip():
        return
    try:
        add_fact = getattr(ledger, "add_fact", None)
        if not callable(add_fact):
            return
        add_fact(
            text=text.strip(),
            kind="secret" if not truthful else "fact",
            subject_id=subject_id or agent,
            turn=turn,
            day=day,
            source=f"claim:{agent}:{'true' if truthful else 'false'}",
        )
    except Exception as exc:  # noqa: BLE001 -- memory must not break a turn
        logger.debug("[knowledge] Could not record claim: %s", exc)


__all__ = [
    "SCOPES",
    "SCOPE_CHARACTER",
    "SCOPE_GM",
    "SCOPE_PLAYER",
    "SCOPE_PUBLIC",
    "KnowledgePolicy",
    "ScopeGrant",
    "policy_from_data",
    "record_claim",
]

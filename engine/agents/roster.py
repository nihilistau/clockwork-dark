"""
Agent Roster
============

Which agents a story runs, what each may say, read and write.

WHY THIS IS DATA. The two agents in this engine were, for the project's whole
life, named in Python (``clockwork_storyteller``, ``clockwork_assistant``),
their personas were string literals, their voices implicit, and the only
permission model a skill allowlist checked at dispatch. That was a description
of one story's cast written into the runtime. The names live in the flagship's
own ``agents.yaml`` now, and the engine resolves an agent's id through
:func:`agent_id_for_role`; the old literals survive only as the fallback for a
story that declares no roster at all.

A second story has a different cast with different rules: a world agent owning
ten voices, a character agent owning three, each barred from the other's
secrets, each permitted to write a different set of meters -- one of them only
"with reason", one of them only in particular contexts. None of that can be
expressed by adding another string constant.

So a story declares its roster:

    agents:
      gm:
        role: world
        voices: [narration, thornwake, lior]
        reads: [gm_secrets]
        writes: [favor, autonomy]
        profile: big
      sophia:
        role: character
        voices: [sophia_dialogue]
        reads: [character_private]
        writes: [favor, desire]
        writes_with_reason: [autonomy]

    negotiation:
      - name: private_scene_wins
        when: {sophia: speak, gm: interrupt}
        winner: sophia
        detail: her scene completes; the event becomes aftermath

WHERE THE PERMISSIONS ARE ACTUALLY ENFORCED. This module DECLARES them; three
existing layers enforce them, and that separation is deliberate:

  * voices  -> ``engine/agents/negotiate.py``, at the point an agent's INTENT
               to speak as someone is visible, so the attempt is recorded
  * reads   -> ``engine/agents/knowledge.py``, filtering prompt blocks and
               lore retrieval
  * writes  -> ``engine/state/store.py``, whose per-value ``owners`` refuses
               and journals the write itself

A roster that enforced anything on its own would be a fourth place to get it
wrong.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.agents.knowledge import KnowledgePolicy
from engine.agents.negotiate import Rule, rules_from_data

logger = logging.getLogger(__name__)

ROLE_WORLD = "world"
ROLE_CHARACTER = "character"
ROLE_COMPANION = "companion"
ROLES = (ROLE_WORLD, ROLE_CHARACTER, ROLE_COMPANION)


class RosterError(ValueError):
    """A story's agent declaration is unusable. Raised at load, never mid-turn."""


@dataclass(frozen=True)
class AgentSpec:
    """
    One declared agent.

    Attributes:
        id: Addressed by plans, the state store's ``owners``, and the skill
            registry's agent allowlist. One id, three enforcement points.
        role: world | character | companion. Shapes defaults, not permissions.
        voices: Voice ids this agent may speak as.
        reads: Knowledge scopes granted.
        writes: Declared state values it may write freely.
        writes_with_reason: Values it may write only with a stated reason.
            Recorded in the store's journal, so "she took something from you"
            is attached to the number that moved.
        profile: LM Studio profile. A character agent that must answer quickly
            and a world agent that may think are not the same call.
        prompt: Path to this agent's persona, relative to the story root.
        pipeline: Whether this agent takes part in the plan -> negotiate ->
            commit turn. Defaults to True because a declared agent normally IS
            a negotiation participant; the flagship's companion is the case
            that needed the flag -- it is a real member of the cast with an id
            and a persona, but it speaks AFTER narration through the assistant
            director, so counting it as a negotiator would spend a model call
            asking it to plan a turn it never leads.
    """

    id: str
    role: str = ROLE_WORLD
    voices: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    writes_with_reason: tuple[str, ...] = ()
    profile: str = "big"
    prompt: str = ""
    pipeline: bool = True

    @property
    def all_writes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.writes + self.writes_with_reason))

    def needs_reason(self, value: str) -> bool:
        return value in self.writes_with_reason


@dataclass
class Roster:
    """Every agent a story runs, plus how their proposals are reconciled."""

    agents: dict[str, AgentSpec] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.agents)

    def get(self, agent_id: str) -> Optional[AgentSpec]:
        return self.agents.get(agent_id)

    def of_role(self, role: str) -> list[AgentSpec]:
        return [a for a in self.agents.values() if a.role == role]

    def pipeline_agents(self) -> list[AgentSpec]:
        """
        The agents that plan and negotiate, in declared order.

        This is the list the multi-agent turn counts and gathers -- a declared
        agent with ``pipeline: false`` is still in the cast (its voices are
        owned, its scopes filter prompts, its writes reach the schema) but it
        does not propose, so it cannot trip the pipeline's two-participant
        threshold. The flagship's companion is exactly this: present, named,
        and deliberately not a negotiator.
        """
        return [a for a in self.agents.values() if a.pipeline]

    def owned_voices(self) -> dict[str, tuple[str, ...]]:
        """The mapping ``Negotiator`` needs to enforce voice ownership."""
        return {a.id: a.voices for a in self.agents.values()}

    def knowledge(self) -> KnowledgePolicy:
        """The policy ``knowledge.py`` needs to filter prompts and retrieval."""
        return KnowledgePolicy({a.id: list(a.reads) for a in self.agents.values()})

    def owners_for(self, value: str) -> tuple[str, ...]:
        """
        Which agents may write one declared value.

        The state schema declares ``owners`` per value and is the enforcement
        point; this is the reverse index, so a story can express permissions
        agent-first (which is how a cast reads) and the schema can still be
        checked value-first (which is how a write is checked).
        """
        return tuple(
            a.id for a in self.agents.values() if value in a.all_writes
        )


def parse_roster(data: Any, *, slug: str = "") -> Roster:
    """
    Build a roster from a story's ``agents.yaml`` body.

    Raises:
        RosterError: On a malformed declaration. Fatal and at load time -- a
            story whose cast does not parse must refuse to start rather than
            discover mid-scene that nobody owns a voice.
    """
    if data is None:
        return Roster()
    if not isinstance(data, dict):
        raise RosterError(f"agent roster for '{slug}' is not a mapping")

    roster = Roster()
    block = data.get("agents") or {}
    if not isinstance(block, dict):
        raise RosterError(f"'agents' for '{slug}' must be a mapping")

    seen_voices: dict[str, str] = {}
    for agent_id, raw in block.items():
        key = str(agent_id)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise RosterError(f"agent '{key}' in '{slug}' must be a mapping")

        role = str(raw.get("role", ROLE_WORLD))
        if role not in ROLES:
            raise RosterError(
                f"agent '{key}' declares role '{role}'; expected one of {ROLES}"
            )

        def _tuple(name: str) -> tuple[str, ...]:
            value = raw.get(name) or ()
            if isinstance(value, str):
                value = [value]
            return tuple(str(v) for v in value)

        voices = _tuple("voices")
        for voice in voices:
            # Two agents owning one voice means the negotiator cannot decide
            # who spoke, and the answer would silently depend on dict order.
            if voice in seen_voices:
                raise RosterError(
                    f"voice '{voice}' is claimed by both '{seen_voices[voice]}' "
                    f"and '{key}' in '{slug}'"
                )
            seen_voices[voice] = key

        roster.agents[key] = AgentSpec(
            id=key,
            role=role,
            voices=voices,
            reads=_tuple("reads"),
            writes=_tuple("writes"),
            writes_with_reason=_tuple("writes_with_reason"),
            profile=str(raw.get("profile", "big")),
            prompt=str(raw.get("prompt", "") or ""),
            pipeline=bool(raw.get("pipeline", True)),
        )

    roster.rules = rules_from_data(data.get("negotiation"))

    # A rule naming an agent that does not exist can never fire, and would sit
    # in the table looking like it works.
    for rule in roster.rules:
        unknown = set(rule.when) - set(roster.agents)
        if rule.winner and rule.winner not in roster.agents:
            unknown.add(rule.winner)
        if unknown:
            raise RosterError(
                f"negotiation rule '{rule.name}' in '{slug}' names unknown "
                f"agents: {sorted(unknown)}"
            )

    logger.info(
        "[roster] Parsed (operation=parse_roster, slug=%s, agents=%d, rules=%d)",
        slug or "?",
        len(roster.agents),
        len(roster.rules),
    )
    return roster


def agent_id_for_role(role: str, fallback: str) -> str:
    """
    The active story's agent id for a role, or the legacy fallback.

    This is how the engine's built-in agents get their names now. The fallbacks
    callers pass are the HISTORICAL CANON IDS (``clockwork_storyteller``,
    ``clockwork_assistant`` -- CLAUDE.md, do not rename): they were engine
    literals for the project's whole life and external records (transcripts,
    telemetry, tooling) may carry them, so a story that ships no ``agents.yaml``
    keeps them exactly as before. A story WITH a roster names its own cast, and
    the flagship's roster declares the canon pair itself -- which means the
    fallback path is exercised only by a rosterless story, never by a shipped
    one.

    Where a role has several agents, the first declared wins; a story that
    needs the engine to tell its two world agents apart has outgrown this
    helper and should be addressing them by id.
    """
    try:
        from engine.state.active import active_roster

        agents = active_roster().of_role(role)
    except Exception as exc:  # noqa: BLE001 -- never block a turn on the roster
        logger.debug("[roster] No active roster for id lookup: %s", exc)
        return fallback
    return agents[0].id if agents else fallback


def load_roster(path: Path | str, *, slug: str = "") -> Roster:
    """
    Read a story's ``agents.yaml``.

    A missing file is NOT an error: the story runs the engine's built-in pair.
    No shipped game takes that path any more -- all four declare an
    ``agents.yaml`` -- so this is the contract for a story being authored, not
    a description of what ships. Keeping it additive is what let the
    multi-agent runtime land without touching the games that predated it.
    """
    source = Path(path)
    if not source.is_file():
        logger.debug(
            "[roster] No agent roster, using the engine default "
            "(operation=load_roster, path=%s)",
            source,
        )
        return Roster()

    try:
        with source.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RosterError(f"could not read agent roster at {source}: {exc}") from exc

    return parse_roster(data, slug=slug)


__all__ = [
    "ROLES",
    "ROLE_CHARACTER",
    "ROLE_COMPANION",
    "ROLE_WORLD",
    "AgentSpec",
    "Roster",
    "RosterError",
    "agent_id_for_role",
    "load_roster",
    "parse_roster",
]

"""
The Multi-Agent Turn
====================

plan → negotiate → govern → commit, in front of narration.

WHAT RAN BEFORE. Two agents, strictly sequential and one-directional: the
narrator ran to completion and committed, then the second agent was handed the
finished prose and allowed to react to it. Neither produced a proposal, neither
could object to the other, and the only shared artifact was already-written
``GameState``. ``plan.py``, ``negotiate.py``, ``knowledge.py`` and ``roster.py``
were all built and tested against that gap and nothing called them.

WHAT RUNS NOW, for a story that declares two or more agents:

    1. PLAN      each agent proposes, from the same pre-commit state and the
                 same player action, seeing only what its scopes allow
    2. NEGOTIATE the story's rule table decides whose intent leads, which
                 choices reach the player, and what each side gives up
    3. GOVERN    the PHASE_COMMIT chain reviews the reconciled proposals while
                 they are still proposals -- the safety ceiling lives here, and
                 a hook may veto the turn's effects outright
    4. COMMIT    the accepted effects are applied ONCE, atomically, through the
                 single writer, with the proposing agent recorded
    5. NARRATE   downstream and unchanged, except that it now knows the answer

The ordering is the point. An agent that has already written cannot be argued
with, so nothing is written until the argument is over.

ONE COMMIT, NOT TWO. Every accepted effect lands inside one
``StateTransaction``. A negotiation that half-applied -- the character's regard
moved, the world's consequence did not -- would leave a state neither agent
proposed and no rule produced.

INERT WITHOUT A ROSTER. A story declaring fewer than two agents gets
``ran=False`` and the caller keeps the path it had. The flagship declares no
roster and keeps the turn it always had; The Wicked Garden ships an
``agents.yaml`` with two agents, and this pipeline is its turn.

Version: v0.2.0 [2026-08-13]
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from engine.agents.negotiate import NegotiatedTurn, Negotiator
from engine.agents.plan import AgentPlan
from engine.agents.planner import plan_for

logger = logging.getLogger(__name__)

#: Below this, there is nobody to negotiate with. A single declared agent is a
#: narrator, and running a negotiation against itself would spend a model call
#: to reach the conclusion it started from.
MIN_AGENTS = 2


@dataclass
class PipelineResult:
    """Everything the turn needs to know about what the agents agreed."""

    ran: bool = False
    turn: NegotiatedTurn = field(default_factory=NegotiatedTurn)
    plans: dict[str, AgentPlan] = field(default_factory=dict)
    #: Receipts from the one writer, in application order.
    receipts: list[dict[str, Any]] = field(default_factory=list)
    #: Writes an agent asked for and did not get, from either the plan filter or
    #: the store's own ACL.
    refused: list[dict[str, Any]] = field(default_factory=list)
    #: Non-empty when a PHASE_COMMIT governor vetoed the turn: nothing was
    #: applied, every proposed write is in ``refused``, and the negotiated turn
    #: is marked blocked so the narrator declines in fiction.
    veto: str = ""

    @property
    def lead(self) -> str:
        return self.turn.lead

    def speaker(self) -> Optional[AgentPlan]:
        """
        The plan carrying a spoken line, if any.

        There is at most one: a turn with two characters talking over each other
        is a turn the negotiator was supposed to resolve.
        """
        for plan in self.turn.accepted.values():
            if plan.line:
                return plan
        return None

    def to_dict(self) -> dict[str, Any]:
        """
        The turn journal's view.

        ``include_private`` is deliberately not passed: this dict is logged,
        shipped in the turn payload and sent to telemetry, and a private motive
        that reaches any of those is one the other agent can eventually read.
        """
        return {
            "ran": self.ran,
            **self.turn.to_dict(),
            "plans": [p.to_dict() for p in self.plans.values()],
            "receipts": list(self.receipts),
            "refused": list(self.refused),
            "veto": self.veto,
        }


def _gather(
    roster: Any,
    state: Any,
    player_action: str,
    llm_fn: Optional[Callable[..., Any]],
) -> dict[str, AgentPlan]:
    """
    Every agent's proposal, planned concurrently.

    Concurrent because the plans are independent by construction -- each sees
    the same pre-commit state and neither sees the other, which is what makes
    negotiation meaningful. Running them in series would add a full model wait
    to every turn for no ordering benefit.

    A thread pool rather than the media queue: these are blocking HTTP calls to
    LM Studio, and the lane config (`lmstudio.lanes`) is what actually bounds
    concurrency against the model server.
    """
    specs = list(roster.agents.values())
    policy = roster.knowledge()

    def _one(spec: Any) -> tuple[str, AgentPlan]:
        return spec.id, plan_for(spec, state, player_action, policy=policy, llm_fn=llm_fn)

    if len(specs) == 1:
        return dict([_one(specs[0])])

    with ThreadPoolExecutor(max_workers=len(specs)) as pool:
        return dict(pool.map(_one, specs))


def _govern_commit(
    state: Any,
    turn: NegotiatedTurn,
    plans: dict[str, AgentPlan],
    governance: Any = None,
) -> str:
    """
    Run the PHASE_COMMIT governance chain over the reconciled turn.

    This is the call that did not exist: ``GovernancePipeline.run_commit`` and
    the ``governance.commit`` config key were both shipped, and nothing invoked
    the one phase with veto authority. It runs here, BEFORE the transaction, so
    the safety ceiling reviews proposals while they are still proposals -- a
    redirect clears the offending plans' effects (which is why ``proposed`` is
    gathered after this call), and a veto stops the commit entirely.

    Args:
        governance: Explicit pipeline, overriding the configured one. Tests use
            this to exercise one hook in isolation.

    Returns:
        The veto reason, or "" when the turn may commit. Never raises: the
        chain already skips a hook that throws, so an exception here means the
        pipeline could not be BUILT at all, and an unbuildable governance
        config must not cost the player the turn.
    """
    try:
        from engine.agents.governance import TurnContext, get_governance

        pipeline = governance if governance is not None else get_governance()
        ctx = TurnContext(state=state, plans=dict(plans), negotiated=turn)
        ctx = pipeline.run_commit(ctx)
        return str(ctx.veto or "")
    except Exception as exc:  # noqa: BLE001 -- see docstring
        logger.warning(
            "[pipeline] Commit governance unavailable, proceeding "
            "(operation=_govern_commit): %s",
            exc,
        )
        return ""


def _commit(
    state: Any,
    turn: NegotiatedTurn,
    *,
    plans: Optional[dict[str, AgentPlan]] = None,
    ledger: Any = None,
    governance: Any = None,
) -> tuple[list, list, str]:
    """
    Apply every accepted plan's effects, atomically, through the one writer.

    The PHASE_COMMIT governance chain runs first, before the transaction opens:
    it is the one chain with authority over whether these proposals are applied
    at all (engine/agents/governance.py::run_commit). A veto marks the turn
    blocked and refuses every proposed write; nothing is applied, so there is
    nothing to roll back.

    ``by=`` carries the proposing agent into the state store, so its per-value
    ``owners`` ACL and its write journal both see who asked. An effect the store
    refuses comes back as a receipt with ``ok: False`` and is collected as a
    refusal rather than discarded -- the plan filter catches most of these
    first, and the two together are belt and braces on the one permission that
    can quietly close an ending.
    """
    from engine.game import effects as effects_module
    from engine.game.transaction import StateTransaction

    receipts: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []

    veto = _govern_commit(state, turn, plans or {}, governance)
    if veto:
        turn.blocked = True
        turn.block_reason = turn.block_reason or veto
        for agent, plan in turn.accepted.items():
            for effect in plan.effects:
                refused.append(
                    {"agent": agent, **effect.to_effect(), "why": f"vetoed: {veto}"}
                )
        logger.warning(
            "[pipeline] Turn vetoed, nothing applied (operation=_commit, "
            "reason=%s, refused=%d)",
            veto,
            len(refused),
        )
        return receipts, refused, veto

    # Gathered AFTER governance: a redirected plan's effects were cleared by
    # the chain, and applying a list snapshotted before it would re-apply the
    # exact writes the redirect dropped.
    proposed = [
        (agent, effect)
        for agent, plan in turn.accepted.items()
        for effect in plan.effects
    ]
    if not proposed:
        return receipts, refused, ""

    tx = StateTransaction(state)
    try:
        for agent, effect in proposed:
            payload = effect.to_effect()
            if effect.reason:
                payload["why"] = effect.reason
            receipt = effects_module.apply_effect(
                state, payload, ledger=ledger, by=agent, turn=state.turn_number
            )
            receipt["agent"] = agent
            receipts.append(receipt)
            if not receipt.get("ok", True):
                refused.append({"agent": agent, **payload, "why": receipt.get("text", "")})
        tx.commit()
    except Exception:
        # A commit that raised halfway leaves state neither agent proposed.
        tx.rollback()
        logger.exception("[pipeline] Commit failed, rolled back (operation=_commit)")
        raise

    logger.info(
        "[pipeline] Committed (operation=_commit, effects=%d, refused=%d)",
        len(receipts),
        len(refused),
    )
    return receipts, refused, ""


def run_pipeline(
    state: Any,
    player_action: str,
    *,
    ledger: Any = None,
    safety_block: str = "",
    llm_fn: Optional[Callable[..., Any]] = None,
    roster: Any = None,
    governance: Any = None,
) -> PipelineResult:
    """
    Plan, negotiate, govern and commit, ahead of narration.

    Args:
        state: The live game state. Written only in the commit phase.
        player_action: What the player did, which both agents plan against.
        safety_block: Non-empty when the safety layer refused this direction.
            Passed straight to the negotiator, which applies it ahead of every
            story rule and cannot be reordered out of the way.
        llm_fn: Injected model, for tests.
        roster: Override, for tests. Defaults to the active story's.
        governance: Explicit GovernancePipeline for the PHASE_COMMIT review.
            Tests use it; the turn defaults to the configured one.

    Returns:
        ``ran=False`` for a story with fewer than two declared agents, with
        everything else empty. Never raises for an agent-side failure: a model
        outage produces silent plans and a turn that still happens.
    """
    if roster is None:
        try:
            from engine.state.active import active_roster

            roster = active_roster()
        except Exception as exc:  # noqa: BLE001 -- never block a turn on the roster
            logger.debug("[pipeline] No roster available: %s", exc)
            roster = None

    if not roster or len(getattr(roster, "agents", {})) < MIN_AGENTS:
        return PipelineResult(ran=False)

    plans = _gather(roster, state, player_action, llm_fn)
    negotiator = Negotiator(roster.rules, owned_voices=roster.owned_voices())
    turn = negotiator.negotiate(plans, safety_block=safety_block)

    receipts, refused, veto = _commit(
        state, turn, plans=plans, ledger=ledger, governance=governance
    )
    # Writes the plan filter refused before they ever reached the store.
    for plan in plans.values():
        for row in plan.refused:
            refused.append({"agent": plan.agent, **row})

    logger.info(
        "[pipeline] Turn negotiated (operation=run_pipeline, lead=%s, agents=%d, "
        "resolutions=%d, blocked=%s, veto=%s)",
        turn.lead,
        len(plans),
        len(turn.resolutions),
        turn.blocked,
        bool(veto),
    )
    return PipelineResult(
        ran=True, turn=turn, plans=plans, receipts=receipts, refused=refused, veto=veto
    )


def narration_block(result: PipelineResult) -> str:
    """
    What the negotiation decided, as a prompt block for the narrator.

    This is the seam that makes the pipeline worth having: the narrator writes
    ONCE, knowing what the other agent decided and what it gave up, rather than
    writing first and having a second agent comment afterwards.

    Deliberately carries beats and lines, never ``private``. A narrator that
    could read the character's real motive would narrate it, and the knowledge
    partition would be decorative.
    """
    if not result.ran or not result.turn.accepted:
        return ""

    lines: list[str] = ["THIS TURN HAS ALREADY BEEN AGREED. Narrate it; do not re-decide it."]
    if result.turn.lead:
        lines.append(f"Leading: {result.turn.lead}.")
    for beat in result.turn.beats:
        lines.append(f"- {beat}")

    speaker = result.speaker()
    if speaker is not None and speaker.line:
        lines.append(
            f"{speaker.agent} speaks, and these are her words -- use them as they "
            f"are, do not paraphrase them:\n\"{speaker.line}\""
        )

    if result.receipts:
        moved = [
            f"{r.get('name', '?')} {r.get('after', '?')}"
            for r in result.receipts
            if r.get("ok", True) and r.get("name")
        ]
        if moved:
            lines.append("Already applied, narrate as done: " + ", ".join(moved))

    if result.turn.blocked:
        lines.append(
            "The direction the player asked for is refused. Decline IN FICTION -- "
            "something in the world gets in the way. Never break frame."
        )

    return "\n".join(lines)


def merge_choices(
    result: PipelineResult,
    narrated: list[dict[str, Any]],
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """
    One option list from the narrator's and the agents' proposals.

    The narrator's come first: they follow from the paragraph the player is
    about to read, and an option that does not follow from the prose reads as a
    bug however good it is. The agents' surviving choices are appended -- this
    is what lets a character who just warned you about a door put "not that
    door" on the table, which she could not do when choices were written solely
    by the narrator and she never saw them.

    Ids are reassigned positionally over the FINAL list. They are keyboard
    shortcuts, so two sources numbering independently would collide, and a gap
    would leave a shortcut pointing at nothing.
    """
    rows = [dict(row) for row in narrated or []]
    if result.ran:
        rows.extend(choice.to_dict() for choice in result.turn.choices)

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("text") or "").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) >= limit:
            break

    for index, row in enumerate(merged):
        row["id"] = chr(ord("a") + index)
    return merged


__all__ = [
    "MIN_AGENTS",
    "PipelineResult",
    "merge_choices",
    "narration_block",
    "run_pipeline",
]

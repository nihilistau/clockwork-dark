"""
Safety Governors
================

The two governance hooks that put ``SafetyGate`` inside a turn.

    SafetyDirective   PHASE_DIRECTIVE, priority 10 -- the standing constraint
                      block, built once and budgeted like any other block.
    SafetyCeiling     PHASE_COMMIT,    priority 10 -- the decision, taken over
                      reconciled proposals while they are still proposals.

WHY PHASE_COMMIT AND NOT PHASE_POST. POST runs after ``tx.commit()``. A hook
there can record that something was wrong and clamp a number back into range;
it cannot stop the thing happening, because it already happened. A safety
ceiling that can only file a report is not a ceiling. PHASE_COMMIT sees the
negotiated turn while it is still a proposal, which is the only place "this
must not happen" can be made true.

WHY PRIORITY 10. Lowest number runs first. The safety layer decides before any
other governor shapes the turn, so no later hook can be the reason a limit was
missed -- and, in the directive chain, so the constraint block sits at the top
of the directives rather than after three paragraphs about evil-phase tone.

THE FADE INVARIANT, IN CODE. ``_fade`` touches ``ctx.metadata`` and nothing
else. It does not read, clear, filter or rewrite ``plan.effects``. That is the
implementation of ``06-UI-UX.md:208`` -- "mechanical outcomes still apply" --
and it is a property of which lines exist in this file, not of a comment asking
future readers to be careful. ``_redirect`` is the one path that clears
effects, because a redirect means the fiction interrupted and the thing did not
occur.

WIRED. ``engine/agents/governance.py`` calls ``register_safety_interceptors()``
at import (``_register_safety``), so both classes resolve by their config
names; ``config/default.yaml`` puts SafetyDirective in ``governance.directives``
and SafetyCeiling in ``governance.commit``; and the commit chain itself is run
by ``engine/agents/pipeline.py::_commit`` before the turn's transaction, which
is what makes the ceiling a ceiling rather than a report.

Version: v0.2.0 [2026-08-13]
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.safety.gate import SafetyGate
from engine.safety.verdict import Disposition, Verdict

logger = logging.getLogger(__name__)

#: Metadata keys this layer writes on a TurnContext. Named constants so a
#: consumer in another package binds to a symbol rather than to a string.
META_VERDICT = "safety_verdict"
META_FADE = "safety_fade"
META_SUBSTITUTIONS = "safety_substitutions"
META_REDIRECT_FALLBACK = "safety_redirect_fallback"


class SafetyDirective:
    """
    PHASE_DIRECTIVE: the standing content constraint, as one budgeted block.

    Contributes NOTHING for an inert policy, which is what both shipped stories
    have. That is not an optimisation -- ``build_directives`` output is fitted
    into a prompt budget that is already over (R-01), and a safety layer that
    cost every existing game tokens it did not ask for would be paid for by the
    narration those games do want.
    """

    priority = 10
    name = "SafetyDirective"

    def run_pre(
        self,
        state: Any,
        system_prompt: str,
        *,
        player_action: str = "",
        **_: Any,
    ) -> str:
        block = SafetyGate.for_state(state).directive_text()
        if not block:
            return system_prompt
        return f"{system_prompt}\n\n{block}" if system_prompt else block


class SafetyCeiling:
    """
    PHASE_COMMIT: review the negotiated turn before its effects are applied.

    Reads ``ctx.plans``, ``ctx.negotiated`` and ``ctx.narration``. Writes
    ``ctx.intensity``, ``ctx.safety_block`` and ``ctx.metadata`` -- the fields
    ``TurnContext`` already declares for this layer.

    Deliberately does NOT set ``ctx.veto``. A veto rolls the whole transaction
    back, including the clock; a limit reached mid-scene should cost the player
    the scene, not the hour. The redirect path clears the offending plan's
    effects instead, which is the same refusal at the right granularity.
    """

    priority = 10
    name = "SafetyCeiling"

    def run_post(self, ctx: Any) -> Any:
        """
        Named ``run_post`` because that is the method GovernancePipeline calls
        for every context-carrying phase, PHASE_COMMIT included. The name is
        the pipeline's, not a claim about when this runs.
        """
        gate = SafetyGate.for_state(getattr(ctx, "state", None))
        try:
            ctx.intensity = gate.policy.intensity.value
        except Exception:  # noqa: BLE001 -- a stub context in a test
            pass
        if gate.inert:
            return ctx

        worst: Optional[Verdict] = None
        offenders: list[str] = []

        for agent, plan in (getattr(ctx, "plans", {}) or {}).items():
            verdict = gate.review_plan(plan)
            if verdict.allowed:
                continue
            offenders.append(str(agent))
            worst = _stricter(worst, verdict)

        narration = str(getattr(ctx, "narration", "") or "")
        if narration:
            worst = _stricter(worst, gate.review_narration(narration))

        if worst is None or worst.allowed:
            return ctx

        _record(ctx, worst)
        if worst.disposition is Disposition.REDIRECT:
            _redirect(ctx, worst, offenders)
        elif worst.disposition is Disposition.FADE:
            _fade(ctx, worst)
        elif worst.disposition is Disposition.SUBSTITUTE:
            _substitute(ctx, worst)
        return ctx


# ---------------------------------------------------------------------------
# the three outcomes
# ---------------------------------------------------------------------------
#
# Separate functions so the difference between them is visible as a diff: the
# fade path is four lines and none of them mention effects.


def _record(ctx: Any, verdict: Verdict) -> None:
    """Put the verdict on the context and in the log, whatever happens next."""
    meta = getattr(ctx, "metadata", None)
    if isinstance(meta, dict):
        meta[META_VERDICT] = verdict.to_dict()
    logger.info(
        "[safety] Turn reviewed (operation=run_post, disposition=%s, "
        "intensity=%s, reasons=%s)",
        verdict.disposition.value,
        verdict.intensity.value,
        list(verdict.reasons),
    )


def _redirect(ctx: Any, verdict: Verdict, offenders: list[str]) -> None:
    """
    A hard limit was reached. The fiction interrupts and nothing is applied.

    Clears the offending plans' effects because the thing did not happen. The
    turn itself still resolves: the player gets a beat, the clock still moved,
    and no interface anywhere says the word "refused".
    """
    ctx.safety_block = verdict.redirect
    meta = getattr(ctx, "metadata", None)
    if isinstance(meta, dict):
        meta[META_REDIRECT_FALLBACK] = verdict.fallback

    negotiated = getattr(ctx, "negotiated", None)
    if negotiated is not None:
        try:
            negotiated.blocked = True
            negotiated.block_reason = verdict.redirect
        except Exception as exc:  # noqa: BLE001 -- a stub in a test
            logger.debug("[safety] Negotiated turn not markable: %s", exc)

    for agent in offenders:
        plan = (getattr(ctx, "plans", {}) or {}).get(agent)
        _drop_effects(plan, agent)
        accepted = getattr(negotiated, "accepted", None) if negotiated else None
        if isinstance(accepted, dict):
            _drop_effects(accepted.get(agent), agent)


def _drop_effects(plan: Any, agent: str) -> None:
    """Empty one plan's proposed effects, tolerating a plan that has none."""
    if plan is None:
        return
    effects = getattr(plan, "effects", None)
    if not effects:
        return
    try:
        plan.effects = []
        logger.info(
            "[safety] Dropped proposed effects behind a redirect "
            "(operation=_drop_effects, agent=%s, count=%d)",
            agent,
            len(effects),
        )
    except Exception as exc:  # noqa: BLE001 -- frozen or exotic plan object
        logger.warning(
            "[safety] Could not drop effects behind a redirect "
            "(operation=_drop_effects, agent=%s): %s",
            agent,
            exc,
        )


def _fade(ctx: Any, verdict: Verdict) -> None:
    """
    The scene is above the session's tier. Summarise it.

    NOTE WHAT IS NOT HERE. No plan is touched, no effect list is read, nothing
    is dropped. The scene happened; the camera looked away. See the module
    docstring.
    """
    meta = getattr(ctx, "metadata", None)
    if isinstance(meta, dict):
        meta[META_FADE] = {
            "summary_hint": verdict.summary_hint,
            "reasons": list(verdict.reasons),
            "aftercare": SafetyGate.for_state(
                getattr(ctx, "state", None)
            ).policy.aftercare,
        }


def _substitute(ctx: Any, verdict: Verdict) -> None:
    """
    A soft limit's noun appeared and a rename was offered.

    Records the map. Applying it is the renderer's job, through
    ``SafetyGate.rename``, on display strings only -- so an id cannot be
    renamed and the mechanics cannot drift from the label.
    """
    meta = getattr(ctx, "metadata", None)
    if isinstance(meta, dict):
        meta[META_SUBSTITUTIONS] = dict(verdict.substitutions)


#: Strictest first. Used to fold several verdicts into the one that governs.
_STRICTNESS: dict[Disposition, int] = {
    Disposition.ALLOW: 0,
    Disposition.SUBSTITUTE: 1,
    Disposition.FADE: 2,
    Disposition.REDIRECT: 3,
}


def _stricter(left: Optional[Verdict], right: Verdict) -> Verdict:
    """
    The stricter of two verdicts, merging their reasons.

    A turn where one agent's beat needs a fade and another's hits a hard no is
    a redirected turn. Taking the max rather than the first means the order the
    plans happen to be iterated in cannot change the answer.
    """
    if left is None:
        return right
    if _STRICTNESS[right.disposition] <= _STRICTNESS[left.disposition]:
        merged = tuple(dict.fromkeys((*left.reasons, *right.reasons)))
        return type(left)(
            disposition=left.disposition,
            intensity=left.intensity,
            reasons=merged,
            substitutions={**right.substitutions, **left.substitutions},
            redirect=left.redirect,
            fallback=left.fallback,
            summary_hint=left.summary_hint,
        )
    merged = tuple(dict.fromkeys((*left.reasons, *right.reasons)))
    return type(right)(
        disposition=right.disposition,
        intensity=right.intensity,
        reasons=merged,
        substitutions={**left.substitutions, **right.substitutions},
        redirect=right.redirect,
        fallback=right.fallback,
        summary_hint=right.summary_hint,
    )


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def register_safety_interceptors() -> bool:
    """
    Register both governors with the governance pipeline.

    Explicit rather than a module-import side effect, and the import of
    ``engine.agents.governance`` happens INSIDE the function on purpose:
    ``engine/agents/governance.py`` registers the legacy lore interceptors at
    import time and ``engine/agents/__init__.py`` eagerly imports the
    storyteller, so a module-scope import here would close an import loop the
    moment anything in ``engine.agents`` imported this package.

    Idempotent -- registration is a dict assignment keyed by class name, so
    calling this twice installs the same two entries twice over.

    Returns:
        True when both were registered, False when the governance module could
        not be imported. Never raises: failing to register a safety hook is a
        problem to see in the log, not a reason the process will not start.
    """
    try:
        from engine.agents.governance import (
            PHASE_COMMIT,
            PHASE_DIRECTIVE,
            register,
        )
    except Exception as exc:  # noqa: BLE001 -- see the docstring
        logger.warning(
            "[safety] Governance pipeline unavailable, hooks not registered "
            "(operation=register_safety_interceptors): %s",
            exc,
        )
        return False

    register(PHASE_DIRECTIVE, SafetyDirective)
    register(PHASE_COMMIT, SafetyCeiling)
    logger.info(
        "[safety] Governors registered (operation=register_safety_interceptors, "
        "phases=directive+commit)"
    )
    return True


__all__ = [
    "META_FADE",
    "META_REDIRECT_FALLBACK",
    "META_SUBSTITUTIONS",
    "META_VERDICT",
    "SafetyCeiling",
    "SafetyDirective",
    "register_safety_interceptors",
]

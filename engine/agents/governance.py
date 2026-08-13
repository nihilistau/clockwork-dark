"""
Governance Pipeline
===================

One priority-ordered interceptor registry around an agent turn, replacing the
two hand-rolled chains the engine grew independently.

WHY THIS EXISTS. The engine already owns truth -- dice, inventory, travel and
time all move through ``@skill`` tools -- but a language model can still
*claim* things in its prose and its JSON that it never earned. Nothing was
watching for that. ``engine/mcp/scene_rules_engine.py`` was written to watch for
exactly it (R001-R005) and then never called by anything, so the rules existed
as documentation of an intent rather than as an enforced property.

Meanwhile the dispatch logic that would have called it was duplicated:

  * ``engine/lore/interceptors.py::run_pre_interceptors`` -- builds a registry
    from ``comms.interceptors``, sorts by priority, threads a prompt through.
  * ``engine/media/interceptors.py::run_media_interceptors`` -- declares three
    interceptor classes with priorities and then ignores all three, calling
    ``MediaPipeline.process_tags`` directly.

Two copies of "ordered chain of hooks", neither of which could host a rule
check. This module is the single implementation both delegate to. Phases are
named, so PRE (prompt shaping), POST (audit) and MEDIA (tag fan-out) share
registration, ordering and failure semantics without sharing a signature.

FAILURE SEMANTICS. An interceptor that raises is logged and skipped. A hook
that shapes a prompt or records a metric must never be able to take down the
turn it was observing -- that trades a cosmetic problem for a fatal one.

Version: v0.1.1 [2026-08-09]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from engine.config import get_config
from engine.game.state import GameState

logger = logging.getLogger(__name__)

PHASE_PRE = "pre"
PHASE_DIRECTIVE = "directive"
#: Runs over reconciled proposals BEFORE the transaction commits, with the
#: authority to alter them.
#:
#: POST has always run after `tx.commit()`, which makes it a post-mortem audit:
#: it can record that something was wrong and clamp a value back into range,
#: but it cannot stop the turn that did it. Everything that has to decide
#: whether a change happens at all -- the safety ceiling, per-agent write
#: permission, an ending gate that must never offer an impossible card -- needs
#: to run while the answer is still a proposal. The rollback machinery to
#: support this already existed and was proven by the evaluator retry loop; the
#: phase did not.
PHASE_COMMIT = "commit"
PHASE_POST = "post"
PHASE_MEDIA = "media"

# phase -> interceptor name -> class. Populated by @interceptor at import.
_REGISTRY: dict[str, dict[str, type]] = {
    PHASE_PRE: {},
    PHASE_DIRECTIVE: {},
    PHASE_COMMIT: {},
    PHASE_POST: {},
    PHASE_MEDIA: {},
}

_GOVERNANCE: Optional["GovernancePipeline"] = None

# Chains used when config names none. Falling back to an empty chain would make
# a missing config key silently disable the rules engine again, which is the
# precise failure this module was written to end.
#
# PHASE_PRE deliberately keeps exactly the two hooks ``comms.interceptors``
# already names, so delegating the legacy chain here is behaviour-preserving.
# New prompt shapers go in PHASE_DIRECTIVE instead -- see build_directives.
_DEFAULT_CHAINS: dict[str, tuple[str, ...]] = {
    PHASE_PRE: ("LoreInjectInterceptor", "AwarenessGateInterceptor"),
    PHASE_DIRECTIVE: ("EvilPhaseTone", "DoomSignsInterceptor", "StorytellerMind"),
    # Empty by default and deliberately so. A pre-commit hook can VETO a turn's
    # changes, which is the most dangerous kind of default to ship implicitly --
    # a story gets one only by asking for it.
    PHASE_COMMIT: (),
    PHASE_POST: ("RulesGovernor",),
    PHASE_MEDIA: ("MediaGovernor",),
}


def interceptor(
    phase: str,
    *,
    priority: int = 50,
    name: Optional[str] = None,
) -> Callable[[type], type]:
    """
    Register an interceptor class under a phase.

    Args:
        phase: ``pre``, ``post`` or ``media``.
        priority: Lower runs first. Matches the convention the existing lore
            interceptors already carry as class attributes.
        name: Registry key. Defaults to the class name, which is what config
            files reference.
    """

    def decorate(cls: type) -> type:
        cls.priority = priority  # type: ignore[attr-defined]
        cls.name = name or cls.__name__  # type: ignore[attr-defined]
        _REGISTRY.setdefault(phase, {})[cls.name] = cls  # type: ignore[attr-defined]
        return cls

    return decorate


def register(phase: str, cls: type, *, name: Optional[str] = None) -> None:
    """
    Register a class that already exists and cannot carry the decorator.

    Used for the lore and media interceptors, which predate this module and are
    imported by other code by name.
    """
    key = name or getattr(cls, "name", None) or cls.__name__
    _REGISTRY.setdefault(phase, {})[key] = cls


@dataclass
class TurnContext:
    """
    Mutable carrier threaded through one turn's governance.

    PRE hooks shape ``system_prompt``; POST hooks read the resolved turn and
    append to ``violations``. Any hook may set ``abort`` to stop the remaining
    chain -- used by nothing today, present because a governor that finds a
    state it must not let continue has no other way to say so.
    """

    state: GameState
    player_action: str = ""
    #: The agent this context is ABOUT, for single-agent phases. Kept because
    #: every existing hook reads it; multi-agent phases read `plans` instead.
    agent: str = "storyteller"
    system_prompt: str = ""
    raw: str = ""
    parsed: dict[str, Any] = field(default_factory=dict)
    narration: str = ""
    voice_style: str = ""
    tool_receipts: list[dict[str, Any]] = field(default_factory=list)
    processed_tags: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    violations: list[dict[str, Any]] = field(default_factory=list)
    media: dict[str, Any] = field(default_factory=dict)
    abort: bool = False

    # -- multi-agent turn ------------------------------------------------
    #
    # `agent: str` above was the one-line assertion that this is a
    # single-agent engine -- it is never assigned a non-default value anywhere
    # in the original codebase. These carry a turn in which two agents each
    # proposed something and one shape was agreed.
    #
    # All default empty, so every existing hook sees exactly what it saw
    # before and a story that runs one agent pays nothing for these.

    #: Each agent's proposal, keyed by agent id. Populated before PHASE_COMMIT.
    plans: dict[str, Any] = field(default_factory=dict)
    #: The agreed turn: lead, beats, merged choices, resolutions.
    negotiated: Optional[Any] = None
    #: Choices as they will be offered, after merge and id assignment.
    choices: list[dict[str, Any]] = field(default_factory=list)
    #: Structured creative direction emitted this turn, if any.
    briefs: dict[str, Any] = field(default_factory=dict)
    #: Content intensity in force. The safety layer owns this; an agent may
    #: never raise it.
    intensity: str = ""
    #: Non-empty when the safety layer refused this turn's direction. The
    #: caller redirects IN FICTION rather than emitting a refusal.
    safety_block: str = ""
    #: Set by a PHASE_COMMIT hook to stop the proposed changes being applied.
    #: Distinct from `abort`, which stops the remaining chain: a veto rejects
    #: the turn's effects, and the caller is expected to roll back.
    veto: str = ""

    def add_violation(
        self,
        rule_id: str,
        message: str,
        severity: str = "error",
    ) -> None:
        """Record a rule breach. Never raises; the turn continues."""
        self.violations.append(
            {"rule_id": rule_id, "message": message, "severity": severity}
        )


class GovernancePipeline:
    """Ordered interceptor chains, one per phase."""

    def __init__(self, chains: Optional[dict[str, list[Any]]] = None) -> None:
        self.chains: dict[str, list[Any]] = {}
        for phase, members in (chains or {}).items():
            self.chains[phase] = sorted(
                members, key=lambda i: getattr(i, "priority", 50)
            )

    # -- construction ----------------------------------------------------

    @classmethod
    def from_config(cls) -> GovernancePipeline:
        """
        Build every phase from config, falling back to the built-in chains.

        PRE reads ``comms.interceptors`` -- the key that already exists and is
        already populated -- rather than inventing a second name for the same
        list. POST and MEDIA read ``governance.post`` / ``governance.media``.
        """
        cfg = get_config()
        wanted: dict[str, list[str]] = {
            PHASE_PRE: list(cfg.get("comms.interceptors", []) or []),
            PHASE_DIRECTIVE: list(cfg.get("governance.directives", []) or []),
            PHASE_COMMIT: list(cfg.get("governance.commit", []) or []),
            PHASE_POST: list(cfg.get("governance.post", []) or []),
            PHASE_MEDIA: list(cfg.get("governance.media", []) or []),
        }

        chains: dict[str, list[Any]] = {}
        for phase, names in wanted.items():
            available = _REGISTRY.get(phase, {})
            selected = [n for n in names if n in available]
            for missing in [n for n in names if n not in available]:
                logger.warning(
                    "[governance] Unknown interceptor named in config, skipping "
                    "(operation=from_config, phase=%s, name=%s)",
                    phase,
                    missing,
                )
            if not selected:
                selected = [
                    n for n in _DEFAULT_CHAINS.get(phase, ()) if n in available
                ]
            chains[phase] = [available[n]() for n in selected]

        logger.info(
            "[governance] Pipeline built (operation=from_config, pre=%d, "
            "directive=%d, commit=%d, post=%d, media=%d)",
            len(chains.get(PHASE_PRE, [])),
            len(chains.get(PHASE_DIRECTIVE, [])),
            len(chains.get(PHASE_COMMIT, [])),
            len(chains.get(PHASE_POST, [])),
            len(chains.get(PHASE_MEDIA, [])),
        )
        return cls(chains)

    # -- execution -------------------------------------------------------

    def run_pre(
        self,
        state: GameState,
        system_prompt: str,
        *,
        player_action: str = "",
        interceptors: Optional[list[Any]] = None,
    ) -> str:
        """
        Thread a system prompt through the PRE chain.

        Args:
            interceptors: Explicit chain, overriding the configured one. Tests
                use this to exercise one hook in isolation; it is sorted by
                priority like any other chain, so an override cannot
                accidentally depend on the order it was written in.

        Returns:
            The shaped prompt. On a hook failure, the prompt as it stood before
            that hook -- a partially shaped prompt still plays.
        """
        chain = (
            sorted(interceptors, key=lambda i: getattr(i, "priority", 50))
            if interceptors is not None
            else self.chains.get(PHASE_PRE, [])
        )
        result = system_prompt
        for hook in chain:
            run = getattr(hook, "run_pre", None)
            if not callable(run):
                continue
            try:
                result = run(state, result, player_action=player_action)
            except Exception as exc:  # noqa: BLE001 -- a shaper must not kill a turn
                logger.warning(
                    "[governance] PRE hook failed, skipping "
                    "(operation=run_pre, hook=%s): %s",
                    getattr(hook, "name", hook),
                    exc,
                )
        return result

    def build_directives(
        self,
        state: GameState,
        *,
        player_action: str = "",
    ) -> str:
        """
        Render the GM directive block as ONE string, appending to nothing.

        WHY THIS IS NOT ``run_pre``. The obvious wiring -- run the PRE chain
        over the assembled prompt -- is the bug ``StorytellerAgent._build_messages``
        already documents at length: that loop visits every system message and
        runs *after* ``build_storyteller_messages`` has fitted the prompt to the
        token budget, so each shaper's block is appended once per system block
        and none of the copies are counted. Measured at 7,550 tokens against a
        6,198 budget (issue R-01).

        So the directive chain never touches the assembled prompt. It builds a
        single block from an empty seed, and the caller hands that block to
        ``context.build_storyteller_messages``, which budgets it like any other.

        Returns:
            The directive text, or "" when no shaper had anything to say.
        """
        chain = self.chains.get(PHASE_DIRECTIVE, [])
        result = ""
        for hook in chain:
            run = getattr(hook, "run_pre", None)
            if not callable(run):
                continue
            try:
                result = run(state, result, player_action=player_action)
            except Exception as exc:  # noqa: BLE001 -- a shaper must not kill a turn
                logger.warning(
                    "[governance] Directive hook failed, skipping "
                    "(operation=build_directives, hook=%s): %s",
                    getattr(hook, "name", hook),
                    exc,
                )
        return result.strip()

    def run_commit(self, ctx: TurnContext) -> TurnContext:
        """
        Run the pre-commit chain over reconciled proposals.

        The difference from POST is authority, not timing alone. POST audits a
        turn that already happened and can only record or clamp; a hook here
        can set ``ctx.veto`` and the caller rolls the transaction back, so a
        change that must not happen does not happen.

        Callers MUST honour ``ctx.veto``. A chain that can veto and a caller
        that ignores it is worse than no chain, because the log will claim the
        turn was stopped.
        """
        result = self._run_ctx_chain(PHASE_COMMIT, ctx)
        if result.veto:
            logger.warning(
                "[governance] Turn vetoed before commit "
                "(operation=run_commit, reason=%s)",
                result.veto,
            )
        return result

    def run_post(self, ctx: TurnContext) -> TurnContext:
        """Run the audit chain over a resolved turn."""
        return self._run_ctx_chain(PHASE_POST, ctx)

    def run_media(self, ctx: TurnContext) -> TurnContext:
        """Run the media fan-out chain, populating ``ctx.media``."""
        return self._run_ctx_chain(PHASE_MEDIA, ctx)

    def _run_ctx_chain(self, phase: str, ctx: TurnContext) -> TurnContext:
        for hook in self.chains.get(phase, []):
            if ctx.abort:
                logger.info(
                    "[governance] Chain aborted (operation=_run_ctx_chain, phase=%s)",
                    phase,
                )
                break
            run = getattr(hook, "run_post", None)
            if not callable(run):
                continue
            try:
                run(ctx)
            except Exception as exc:  # noqa: BLE001 -- an auditor must not kill a turn
                logger.warning(
                    "[governance] %s hook failed, skipping "
                    "(operation=_run_ctx_chain, hook=%s): %s",
                    phase.upper(),
                    getattr(hook, "name", hook),
                    exc,
                )
        return ctx


def get_governance() -> GovernancePipeline:
    """Process-wide pipeline, built on first use."""
    global _GOVERNANCE
    if _GOVERNANCE is None:
        _GOVERNANCE = GovernancePipeline.from_config()
    return _GOVERNANCE


def reset_governance() -> None:
    """
    Drop the cached pipeline.

    Registered in ``engine/games/caches.py``: the PRE chain is built from a
    config list, so a game swap that rebinds ``comms.interceptors`` must not
    keep serving the previous game's chain.
    """
    global _GOVERNANCE
    _GOVERNANCE = None


# ---------------------------------------------------------------------------
# Built-in governors
# ---------------------------------------------------------------------------


@interceptor(PHASE_DIRECTIVE, priority=20)
class EvilPhaseTone:
    """
    PRE: bias narration tone to the current evil phase without naming it.

    The phase is a hidden stat. Handing the model the word "consuming" invites
    it to write the word; handing it a tone gets the same escalation in fiction.

    The four lines describe an ESCALATION CURVE and nothing else. They used to
    describe The Clockwork Dark's -- "cosy frontier life", "brass glints" --
    which put the flagship's imagery into every story's directive block on
    every turn, one layer quieter than the persona did. A story that wants its
    own images writes them in ``prompts/storyteller.md``, which sits above this
    in the prompt; a story-neutral engine may say the wrongness is growing and
    must not say what it looks like.
    """

    _TONE: dict[str, str] = {
        "dormant": "Tone: ordinary life; the wrongness is barely a rumour.",
        "stirring": "Tone: small wrongnesses creep in -- odd details, odd silences.",
        "spreading": "Tone: dread thickens; the wrongness is undeniable to the watchful.",
        "consuming": "Tone: stark, high-contrast horror; the world is coming apart.",
    }

    def run_pre(
        self,
        state: GameState,
        system_prompt: str,
        *,
        player_action: str = "",
        **_: Any,
    ) -> str:
        line = self._TONE.get(state.evil_phase.value)
        return f"{system_prompt}\n\n{line}" if line else system_prompt


@interceptor(PHASE_DIRECTIVE, priority=25)
class DoomSignsInterceptor:
    """
    PRE: tell the Narrator what the Dark has already done to the world.

    Reads the world-event ledger that ``engine/world/world_effects.py`` writes
    when a doom beat lands, so narration and the actual world state cannot drift
    apart. Without this the village empties in the data and stays full in the
    prose.
    """

    #: Only the most recent marks. The whole ledger would crowd the budget out.
    MAX_SIGNS = 3

    def run_pre(
        self,
        state: GameState,
        system_prompt: str,
        *,
        player_action: str = "",
        **_: Any,
    ) -> str:
        signs = [
            str(event.get("text", "")).strip()
            for event in state.world_events
            if event.get("source") == "doom" and event.get("text")
        ]
        if not signs:
            return system_prompt
        recent = signs[-self.MAX_SIGNS :]
        lines = "\n".join(f"- {s}" for s in recent)
        block = (
            "WHAT THE DARK HAS ALREADY DONE (true; do not contradict):\n"
            f"{lines}\n"
            "Let this show as background dread the player may notice or ignore. "
            "Do not resolve it for them."
        )
        return f"{system_prompt}\n\n{block}"


@interceptor(PHASE_DIRECTIVE, priority=30)
class StorytellerMind:
    """PRE: translate the Storyteller's agency knobs into GM directives."""

    def run_pre(
        self,
        state: GameState,
        system_prompt: str,
        *,
        player_action: str = "",
        **_: Any,
    ) -> str:
        mind = state.storyteller_mind
        bits: list[str] = []
        if mind.cruelty_bias >= 0.5:
            bits.append("lean harsher with consequences")
        elif mind.cruelty_bias <= 0.2:
            bits.append("be merciful with consequences")
        if mind.reward_generosity >= 0.6:
            bits.append("reward clever play generously")
        if mind.patience <= 20:
            bits.append("the world grows impatient; raise the stakes")
        if not bits:
            return system_prompt
        return f"{system_prompt}\n\nGM disposition: " + "; ".join(bits) + "."


@interceptor(PHASE_POST, priority=50)
class RulesGovernor:
    """
    POST: run SceneRulesEngine (R001-R005) over the resolved turn.

    This is the call that did not exist. Each rule is defence in depth -- the
    engine's own writers already maintain most of these invariants -- so a
    violation here means something bypassed a writer, and that is worth seeing.

    R003 is different in kind: the model *claiming* a stat delta it has no tool
    receipt for is not a state corruption (the claim was already dropped) but a
    prompt defect. It is recorded as a warning and counted in telemetry.
    """

    def run_post(self, ctx: TurnContext) -> TurnContext:
        from engine.mcp.scene_rules_engine import get_rules_engine

        engine = get_rules_engine()
        state = ctx.state

        self._check_awareness(engine, ctx, state)
        self._check_evil_progress(engine, ctx, state)
        self._check_location(engine, ctx, state)
        self._check_stat_claims(engine, ctx)

        if ctx.violations:
            logger.info(
                "[governance] Rule violations recorded "
                "(operation=run_post, count=%d, rules=%s)",
                len(ctx.violations),
                sorted({v["rule_id"] for v in ctx.violations}),
            )
        return ctx

    @staticmethod
    def _check_awareness(engine: Any, ctx: TurnContext, state: GameState) -> None:
        """R005 -- awareness in [0, 100]. Clamped as well as recorded."""
        result = engine.validate_awareness(state.awareness)
        if result.allowed:
            return
        for violation in result.violations:
            ctx.add_violation(violation.rule_id, violation.message, violation.severity)
        # Recording an out-of-range value and leaving it there would let the
        # next turn read a percentage above 100. A zero-delta write through the
        # one writer IS the clamp: the awareness kind bounds to [0, 100].
        from engine.game import effects as effects_module

        effects_module.apply_effect(state, {"type": "awareness", "delta": 0.0})

    @staticmethod
    def _check_evil_progress(engine: Any, ctx: TurnContext, state: GameState) -> None:
        """R004 -- evil_progress must not fall across a turn."""
        before = ctx.metadata.get("evil_before")
        if before is None:
            return
        try:
            previous = float(before)
        except (TypeError, ValueError):
            return
        result = engine.validate_evil_progress(previous, float(state.evil_progress))
        for violation in result.violations:
            ctx.add_violation(violation.rule_id, violation.message, violation.severity)

    @staticmethod
    def _check_location(engine: Any, ctx: TurnContext, state: GameState) -> None:
        """
        R001 -- the player stands somewhere that exists.

        Deliberately validates against the full location graph, not the five
        canon ids. ``engine/game/procgen.py`` generates real, reachable places
        (``deeper_forest``, ``old_barrows``, ``herb_glen``) that are in the
        graph and are not canon; checking canon here would flag a legal
        position as a violation on every turn the player spends foraging.

        Routing through ``validate_location`` also keeps the multi-game rebind
        working: ``LOCATION_IDS`` is a frozenset that a game swap *rebinds*
        rather than mutates, and ``engine/games/caches.py`` refreshes the copy
        held inside the rules engine. Reading it through that module is what
        makes the refresh take effect; a ``from ... import`` here would
        reintroduce the stale-map bug in a second game.

        Stands down entirely for a story that declares no location graph, and
        for a state with no position: both are declarations ("this story has
        no map" / "nobody is anywhere yet"), not corruptions, and flagging
        them every turn teaches players of graph-less stories to ignore R001.
        """
        if not state.location_id:
            return
        from engine.mcp import scene_rules_engine as rules_module

        if not rules_module.LOCATION_IDS:
            return
        result = engine.validate_location(state, state.location_id)
        for violation in result.violations:
            # R002 cannot fire for a self-target, so anything here is R001.
            ctx.add_violation(violation.rule_id, violation.message, violation.severity)

    @staticmethod
    def _check_stat_claims(engine: Any, ctx: TurnContext) -> None:
        """R003 -- stat deltas the model asserted without a tool receipt."""
        from engine.telemetry import get_oracle

        claims = ctx.parsed.get("stat_changes") or {}
        if not isinstance(claims, dict) or not claims:
            return

        receipt_context = {"tool_receipts": ctx.tool_receipts}
        oracle = get_oracle()
        for stat, raw_delta in claims.items():
            try:
                delta = int(raw_delta)
            except (TypeError, ValueError):
                continue
            if delta == 0:
                continue
            result = engine.validate_stat_delta(receipt_context, str(stat), delta)
            if result.allowed:
                continue
            for violation in result.violations:
                # Severity warning, not error: the engine never applied it. The
                # turn is correct; the prompt is not.
                ctx.add_violation(violation.rule_id, violation.message, "warning")
            oracle.record_unearned_claim(str(stat), delta)


@interceptor(PHASE_MEDIA, priority=80)
class MediaGovernor:
    """
    MEDIA: fan a resolved turn's tags out to the media pipeline.

    Replaces the bypass in ``engine/media/interceptors.py``, which declared
    three interceptor classes with priorities and then called
    ``MediaPipeline.process_tags`` directly, so the priorities described an
    ordering that never ran.
    """

    def run_post(self, ctx: TurnContext) -> TurnContext:
        from engine.media.pipeline import MediaPipeline

        tags = ctx.processed_tags or {}
        result = MediaPipeline().process_tags(
            ctx.state,
            image_tags=tags.get("image"),
            cutscene_tags=tags.get("cutscene"),
            narration=ctx.narration,
            voice_style=ctx.voice_style,
        )
        ctx.media = result.to_dict()
        return ctx


def _register_legacy_interceptors() -> None:
    """
    Make the pre-existing lore hooks resolvable by config name.

    They are ordinary ``run_pre`` classes already carrying ``priority`` and
    ``name``; they simply predate the registry. Imported at module scope
    because ``engine.lore.interceptors`` does not import this module -- the
    delegation there is a function-local import, precisely so this stays
    acyclic.
    """
    from engine.lore.interceptors import (
        AwarenessGateInterceptor,
        LoreInjectInterceptor,
    )

    register(PHASE_PRE, LoreInjectInterceptor)
    register(PHASE_PRE, AwarenessGateInterceptor)


_register_legacy_interceptors()


def _register_safety() -> None:
    """
    Make the safety governors resolvable by config name.

    Registered here rather than by ``engine.safety`` importing this module: the
    safety layer must not depend on the governance layer, because it also has
    to work at seams governance does not reach (player input, display strings).
    The dependency points one way, and this is that way.

    Failure is logged rather than raised. A missing safety module must not stop
    the engine building its pipeline -- and the two shipped stories configure no
    safety chain at all, so on those it changes nothing either way.
    """
    try:
        from engine.safety.governor import register_safety_interceptors

        register_safety_interceptors()
    except Exception as exc:  # noqa: BLE001 -- see docstring
        logger.warning(
            "[governance] Safety interceptors unavailable "
            "(operation=_register_safety): %s",
            exc,
        )


_register_safety()


__all__ = [
    "PHASE_COMMIT",
    "PHASE_DIRECTIVE",
    "PHASE_MEDIA",
    "PHASE_POST",
    "PHASE_PRE",
    "DoomSignsInterceptor",
    "EvilPhaseTone",
    "GovernancePipeline",
    "MediaGovernor",
    "RulesGovernor",
    "StorytellerMind",
    "TurnContext",
    "get_governance",
    "interceptor",
    "register",
    "reset_governance",
]

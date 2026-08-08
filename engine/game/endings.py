"""
Ending Eligibility — an honest answer to "how can this end"
===========================================================

A rules engine over state that produces two things:

  a. an **eligible set** -- endings that can actually complete, and
  b. a **continuous score** per ending -- how close each one is, for omens and
     foreshadowing long before anything is eligible.

THE HONESTY REQUIREMENT IS THE FEATURE. ``DAY-08-MIRRORS.md`` states it flatly:
"Eligibility must be honest -- no fake cards that cannot complete Day 9." An
ending shown as available and then unreachable is worse than one never offered,
because the player spent their remaining choices steering toward it. So a class
is eligible only when BOTH halves hold:

    requires:     you have earned it
    completable:  nothing still live makes it impossible

Those are separate on purpose. High Autonomy earns the door home; an unpaid
service debt to the Vale is what makes walking through it something other than
walking through it. The first is a gate, the second is an obstruction, and
folding them together loses the ability to tell the player which one they are
looking at -- which is exactly the lock-reason text the mirror pool renders.

TWO PHASES, BECAUSE COMMITTING IS ITSELF A CHOICE. ``intent`` is soft: it can be
set, changed and dropped, and Day 8 exists for it. ``lock`` is hard and Day 9
only. Swearing early is powerful and looking only is valid, so the engine has to
be able to represent "I want this" separately from "this is what happens".

FAIL-FORWARD IS NOT A SAFETY NET, IT IS A DECLARED ENDING. The finale's failure
policy is "never softlock title". So ``eligible()`` cannot return an empty set:
if nothing qualifies, the story's declared ``fail_forward`` id is added with an
explicit reason. It is in the set because the story said it always is, not
because the engine panicked -- and it is a real ending with real epilogue cards,
not an error screen.

GATES ARE DATA. Every threshold lives in ``data/rules/endings.yaml`` as a
condition tree in the shared grammar (``engine/game/quests.py``). There is no
Python in this file that knows what ``autonomy`` or ``briar_key`` are.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.game import effects as effects_module
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

#: Where the two phases are stored. Written through the ``track`` effect kind so
#: the dispatcher stays the only writer, and read back from ``state.tracks``.
#: Enum-valued rather than boolean or numeric, which is why neither ``flags``
#: nor ``StateStore`` could hold them.
TRACK_INTENT = "ending_intent"
TRACK_LOCKED = "ending_locked"
#: The ending whose Speak/Act/Seal beats have played. Separate from
#: TRACK_LOCKED because "committed to this ending" and "has watched it happen"
#: are different states, and the epilogue waits for the second one.
TRACK_MODULE = "ending_module_ran"
TRACK_ELIGIBLE = "ending_eligible"
TRACK_SCORES = "ending_scores"

#: The value both tracks hold before anything is chosen. Spelled, not None, so
#: a save round trip and a fresh state read the same.
NONE_ID = "none"

#: Reason string attached to a fail-forward entry, so a UI can tell "you earned
#: this" from "this is what is left".
REASON_FAIL_FORWARD = "fail_forward"


@dataclass
class EligibilityReport:
    """Everything the mirror pool and the finale need, computed once."""

    eligible: list[str] = field(default_factory=list)
    #: id -> the clauses that failed, in the order the story declared them.
    locked: dict[str, list[str]] = field(default_factory=dict)
    #: id -> 0.0-1.0. Computed for EVERY declared ending, eligible or not --
    #: the whole point of a continuous score is to foreshadow what is not yet
    #: available.
    scores: dict[str, float] = field(default_factory=dict)
    fail_forward: str = ""
    #: True when the set contains nothing but the fail-forward.
    forced: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": list(self.eligible),
            "locked": {k: list(v) for k, v in self.locked.items()},
            "scores": dict(self.scores),
            "fail_forward": self.fail_forward,
            "forced": self.forced,
        }

    def top(self, limit: int = 3) -> list[tuple[str, float]]:
        """Highest-scoring endings, for omens. Ties broken by id, so it replays."""
        return sorted(self.scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


# ---------------------------------------------------------------------------
# The rules file
# ---------------------------------------------------------------------------


def _table_path() -> Path:
    from engine.config import get_config

    rel = get_config().get("paths.endings", "data/rules/endings.yaml")
    return _ROOT / str(rel)


@lru_cache(maxsize=8)
def _read_table(path_str: str, _mtime: float) -> dict[str, Any]:
    """Parse endings.yaml, memoized on (path, mtime). See engine/game/survival.py."""
    try:
        with Path(path_str).open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error("[endings] Unreadable endings table: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def load_rules() -> dict[str, Any]:
    """
    The story's ending declarations.

    A missing file yields an empty table. A story with no declared endings gets
    an empty eligible set and no fail-forward -- which is correct, because a
    story that never ends cannot softlock its ending.
    """
    path = _table_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    return _read_table(str(path), mtime)


def declared() -> dict[str, Any]:
    """id -> declaration, flattened across classes and their variants."""
    out: dict[str, Any] = {}
    for class_id, body in (load_rules().get("classes") or {}).items():
        if not isinstance(body, dict):
            continue
        variants = body.get("variants") or {}
        if not isinstance(variants, dict) or not variants:
            out[str(class_id)] = {**body, "class": str(class_id)}
            continue
        for variant_id, variant in variants.items():
            if not isinstance(variant, dict):
                continue
            # A variant inherits its class's gates and adds its own. E2b is
            # "E2, plus you abandoned the Seat" -- restating E2's four clauses
            # under every variant is how a gate table drifts out of agreement
            # with itself.
            out[str(variant_id)] = {
                "class": str(class_id),
                "label": variant.get("label") or body.get("label") or str(variant_id),
                "requires": _merge_conditions(body.get("requires"), variant.get("requires")),
                "completable": _merge_conditions(
                    body.get("completable"), variant.get("completable")
                ),
                "score": variant.get("score") or body.get("score") or [],
                "closes": list(variant.get("closes") or body.get("closes") or []),
                "lock_reasons": {
                    **(body.get("lock_reasons") or {}),
                    **(variant.get("lock_reasons") or {}),
                },
                # The finale's three beats -- Speak, Act, Seal. Dropped by this
                # flattener until now, so a story could author them and the
                # only way to reach them was to bypass this function and
                # re-read the YAML, which is how two readers of one file end up
                # disagreeing about it.
                "beats": list(variant.get("beats") or body.get("beats") or []),
            }
    return out


def _merge_conditions(outer: Any, inner: Any) -> Any:
    """Both must hold. Absent means "no condition", which is a satisfied one."""
    parts = [c for c in (outer, inner) if c]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"all": parts}


def fail_forward_id() -> str:
    """The ending that is always available. Declared, never invented."""
    return str(load_rules().get("fail_forward") or "")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _clause_list(condition: Any) -> list[Any]:
    """
    Split a condition tree into the clauses worth reporting a failure for.

    An ``all`` of four things that fails is four candidate reasons; a single
    predicate that fails is one. Anything else is reported whole, because
    decomposing an ``any`` into reasons would produce a lock message that lists
    alternatives the player only needed one of.
    """
    if condition is None:
        return []
    if isinstance(condition, list):
        return list(condition)
    if isinstance(condition, dict) and "all" in condition and len(condition) == 1:
        raw = condition["all"]
        return list(raw) if isinstance(raw, list) else [raw]
    return [condition]


def _reasons(
    state: GameState,
    condition: Any,
    labels: dict[str, Any],
    ledger: Optional[Any],
) -> list[str]:
    """Which clauses of a failed condition are the ones that failed."""
    from engine.game.quests import evaluate_condition

    out: list[str] = []
    for index, clause in enumerate(_clause_list(condition)):
        if evaluate_condition(state, clause, ledger=ledger):
            continue
        # A story may name its clauses so the lock text is prose rather than a
        # rendered dict. Unnamed clauses still report, badly but honestly --
        # silence would be the failure this whole module exists to avoid.
        key = ""
        if isinstance(clause, dict):
            key = str(clause.get("id") or "")
        out.append(str(labels.get(key or str(index)) or key or _describe(clause)))
    return out


def _describe(clause: Any) -> str:
    """Last-resort human rendering of an unnamed clause."""
    if isinstance(clause, dict):
        return ", ".join(f"{k}: {v}" for k, v in clause.items() if k != "id")[:120]
    return str(clause)[:120]


def _score(state: GameState, rows: Any, ledger: Optional[Any]) -> float:
    """
    Continuous 0.0-1.0 closeness, for omens.

    A weighted blend of normalised value readings and satisfied conditions. The
    weights are the story's; this only has to be monotone and bounded, because
    what it feeds is "the water shows this one more clearly than that one" and
    never a threshold.
    """
    if not isinstance(rows, list) or not rows:
        return 0.0

    from engine.game.quests import evaluate_condition

    store = None
    try:
        from engine.state.active import store_for

        store = store_for(state)
    except Exception as exc:  # noqa: BLE001 -- scoring must never block a turn
        logger.debug("[endings] No state store for scoring: %s", exc)

    total_weight = 0.0
    earned = 0.0
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            weight = float(raw.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        if weight <= 0:
            continue
        total_weight += weight

        name = str(raw.get("value") or "")
        if name and store is not None and store.has(name):
            spec = store.schema.get(name)
            current = store.get(name)
            try:
                target = float(raw.get("at", spec.maximum if spec else 0) or 0)
            except (TypeError, ValueError):
                target = 0.0
            floor = float(spec.minimum) if spec and spec.minimum is not None else 0.0
            span = target - floor
            ratio = 1.0 if span <= 0 else (current - floor) / span
            # Below the floor is 0 and above the target is 1: past the point
            # where an axis is maxed for this ending, more of it is not more
            # of this ending.
            earned += weight * max(0.0, min(1.0, ratio))
            continue

        if "when" in raw:
            if evaluate_condition(state, raw.get("when"), ledger=ledger):
                earned += weight
            continue

        # A bare `{flag: x, weight: n}` row: the whole row minus `weight`/`at`
        # is the condition.
        condition = {k: v for k, v in raw.items() if k not in ("weight", "at", "value")}
        if condition and evaluate_condition(state, condition, ledger=ledger):
            earned += weight

    return 0.0 if total_weight <= 0 else round(earned / total_weight, 4)


def eligible(
    state: GameState,
    *,
    ledger: Optional[Any] = None,
) -> EligibilityReport:
    """
    Which endings can actually happen, which cannot, and how close each is.

    Args:
        state: Game state to read. Nothing is written; use ``recompute`` for
            that.
        ledger: Optional StoryLedger, for gates that read disposition.

    Returns:
        An EligibilityReport. ``eligible`` is never empty when the story
        declares a ``fail_forward``.
    """
    from engine.game.quests import evaluate_condition

    table = declared()
    report = EligibilityReport(fail_forward=fail_forward_id())

    for ending_id, body in table.items():
        labels = body.get("lock_reasons") or {}
        report.scores[ending_id] = _score(state, body.get("score"), ledger)

        gate_ok = evaluate_condition(state, body.get("requires"), ledger=ledger)
        done_ok = evaluate_condition(state, body.get("completable"), ledger=ledger)
        if gate_ok and done_ok:
            report.eligible.append(ending_id)
            continue

        reasons: list[str] = []
        if not gate_ok:
            reasons += _reasons(state, body.get("requires"), labels, ledger)
        if not done_ok:
            # Distinguished in the text, because "you have not earned it" and
            # "something in the way" are different problems with different
            # remaining moves.
            reasons += [
                f"cannot complete: {r}"
                for r in _reasons(state, body.get("completable"), labels, ledger)
            ]
        report.locked[ending_id] = reasons or ["not yet"]

    # Stable order, so the mirror pool lays the cards out the same way twice.
    report.eligible.sort()

    if report.fail_forward and report.fail_forward not in report.eligible:
        # Its own gate did not pass, so it is here purely by declaration. That
        # is the point: it is the ending that is always available.
        report.eligible.append(report.fail_forward)
        report.locked.pop(report.fail_forward, None)
        logger.info(
            "[endings] Fail-forward added by declaration "
            "(operation=eligible, fail_forward=%s)",
            report.fail_forward,
        )

    # FORCED means "there is nothing here but the way out". Distinguished from
    # ordinary eligibility so a UI can tell "you earned this" from "this is what
    # is left", and so a designer can find the states where the gate tables have
    # quietly closed every door.
    report.forced = report.eligible == [report.fail_forward] if report.fail_forward else False

    if not report.eligible:
        logger.error(
            "[endings] No eligible ending AND no declared fail_forward -- this "
            "story can softlock its finale (operation=eligible)"
        )

    return report


# ---------------------------------------------------------------------------
# Writing: the two phases
# ---------------------------------------------------------------------------


def _write_track(state: GameState, name: str, value: Any, allowed: Any = None) -> dict[str, Any]:
    """Every write here goes through the dispatcher. CLAUDE.md rule 3."""
    effect: dict[str, Any] = {"type": "track", "name": name, "value": value}
    if allowed is not None:
        effect["allowed"] = allowed
    return effects_module.apply_effect(state, effect)


def recompute(state: GameState, *, ledger: Optional[Any] = None) -> EligibilityReport:
    """
    Compute eligibility AND commit it to state, so Day 9 reads Day 8's answer.

    ``DAY-09-FINALE.md`` takes ``eligible_endings[]`` as its prerequisite and
    says "recompute if missing". Both halves are here: the list is committed so
    the finale has a committed list, and the computation is cheap enough to
    redo, so a save that predates the commit is not stuck.
    """
    report = eligible(state, ledger=ledger)
    _write_track(state, TRACK_ELIGIBLE, list(report.eligible))
    _write_track(state, TRACK_SCORES, dict(report.scores))
    return report


def intent(state: GameState) -> str:
    """The ending the player has marked. Soft; changeable until locked."""
    return str(state.tracks.get(TRACK_INTENT) or NONE_ID)


def locked(state: GameState) -> str:
    """The ending that is happening. Hard; set once."""
    return str(state.tracks.get(TRACK_LOCKED) or NONE_ID)


def set_intent(
    state: GameState,
    ending_id: str,
    *,
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Mark an intent. Soft phase.

    Refused when the ending is not eligible -- swearing toward a card that
    cannot complete is the dishonesty this module exists to prevent, and it is
    worse at Day 8 than at Day 9 because the player then spends a whole day
    preparing for it.

    ``closes:`` is honoured here: swearing some reflections shuts others, which
    is what makes swearing cost something. The closed ids are recorded as flags
    so the gate tables can read them like any other state.
    """
    report = eligible(state, ledger=ledger)
    if ending_id == NONE_ID:
        return {
            **_write_track(state, TRACK_INTENT, NONE_ID),
            "eligible": report.eligible,
            "text": "intent cleared",
        }
    if ending_id not in report.eligible:
        return {
            "type": "track",
            "name": TRACK_INTENT,
            "ok": False,
            "eligible": report.eligible,
            "reasons": report.locked.get(ending_id, ["not a declared ending"]),
            "text": f"{ending_id} is not eligible",
        }

    receipt = _write_track(state, TRACK_INTENT, ending_id, allowed=sorted(declared()) + [NONE_ID])
    closed = list((declared().get(ending_id) or {}).get("closes") or [])
    for other in closed:
        effects_module.apply_effect(
            state, {"type": "flag", "flag": f"ending_closed_{other}", "value": True}
        )
    receipt["closes"] = closed
    receipt["eligible"] = report.eligible
    logger.info(
        "[endings] Intent sworn (operation=set_intent, ending=%s, closes=%s)",
        ending_id,
        closed,
    )
    return receipt


def lock(
    state: GameState,
    ending_id: str,
    *,
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Commit. Hard phase, the point of no return.

    Refused on a non-eligible id and refused a second time on an already-locked
    save. Re-locking would let a finale be walked back, and "irreversible" is
    the tone the whole day is written in.
    """
    already = locked(state)
    if already != NONE_ID:
        return {
            "type": "track",
            "name": TRACK_LOCKED,
            "ok": False,
            "locked": already,
            "text": f"already locked to {already}",
        }

    report = eligible(state, ledger=ledger)
    if ending_id not in report.eligible:
        return {
            "type": "track",
            "name": TRACK_LOCKED,
            "ok": False,
            "eligible": report.eligible,
            "reasons": report.locked.get(ending_id, ["not a declared ending"]),
            "text": f"{ending_id} cannot complete; it will not be locked",
        }

    receipt = _write_track(state, TRACK_LOCKED, ending_id, allowed=sorted(declared()) + [NONE_ID])
    receipt["eligible"] = report.eligible
    receipt["forced"] = report.forced
    logger.info(
        "[endings] Ending locked (operation=lock, ending=%s, forced=%s)",
        ending_id,
        report.forced,
    )
    return receipt


def module_ran(state: GameState) -> str:
    """The ending whose Speak/Act/Seal beats have played, or ``none``."""
    return str(state.tracks.get(TRACK_MODULE) or NONE_ID)


def module_beats(ending_id: str) -> list[dict[str, Any]]:
    """
    One ending's three beats, bounded, in authored order.

    Bounded through ``deck.bound_beats`` rather than handed to the resolver raw.
    They are authored in the deck grammar and there is no argument for a beat
    being exempt from the per-scene ceilings because of which file it lives in
    -- an ending that awards +40 autonomy is a finale written greedily, which is
    exactly what the clamp is for.
    """
    from engine.content import deck as deck_module

    body = declared().get(str(ending_id)) or {}
    return deck_module.bound_beats(body.get("beats"), str(ending_id), "module")


def run_module(
    state: GameState,
    *,
    ledger: Optional[Any] = None,
    by: str = "engine",
) -> dict[str, Any]:
    """
    Play the locked ending's Speak · Act · Seal, in order.

    ``DAY-09-FINALE.md``'s F4 is a pointer: the three beats of the locked ending
    are authored under that variant's ``beats:`` key, in the same order for all
    twenty-three, and the finale card says "read them and resolve each through
    ``deck.resolve_beat``". Nothing did -- so a run went from the point of no
    return straight to the epilogue, and the sixty-nine authored beats that are
    the actual last scene of the story were skipped.

    Runs ONCE. The receipt records which ending played, so a replayed card, a
    reconnect or a re-resolved turn cannot award Seal's flags twice.

    Refused before an ending is locked, because there is no module to run: which
    three beats these are is decided by the lock, and running them off an
    ``intent`` would play a finale the player has not committed to.
    """
    ending_id = locked(state)
    if ending_id == NONE_ID:
        return {
            "type": "track",
            "name": TRACK_MODULE,
            "ok": False,
            "text": "no ending is locked; there is no module to run",
        }

    already = module_ran(state)
    if already != NONE_ID:
        return {
            "type": "track",
            "name": TRACK_MODULE,
            "ok": False,
            "ran": already,
            "text": f"the {already} module has already played",
        }

    from engine.content import deck as deck_module

    beats = module_beats(ending_id)
    results = [
        deck_module.resolve_beat(state, beat, ledger=ledger, by=by) for beat in beats
    ]
    # Marked run even when the ending declares no beats. "Nothing to play" and
    # "not played yet" have to be distinguishable, or an ending with no module
    # would leave the finale waiting for a scene that is never coming.
    receipt = _write_track(state, TRACK_MODULE, ending_id, allowed=sorted(declared()) + [NONE_ID])
    receipt["beats"] = [r.beat_id for r in results]
    receipt["results"] = [r.to_dict() for r in results]
    logger.info(
        "[endings] Module played (operation=run_module, ending=%s, beats=%d)",
        ending_id,
        len(results),
    )
    return receipt


def resolve(state: GameState, *, ledger: Optional[Any] = None) -> str:
    """
    The ending that happens, whatever the player did or failed to do.

    Precedence: what was locked, else what was sworn if it is still eligible,
    else the highest-scoring eligible one, else the fail-forward. There is no
    branch that returns nothing -- ``DAY-09-FINALE.md``'s failure policy is
    "never softlock title", and a resolver that can return "" is a softlock
    waiting for the one save that reaches it.
    """
    committed = locked(state)
    if committed != NONE_ID:
        return committed

    report = eligible(state, ledger=ledger)
    sworn = intent(state)
    if sworn in report.eligible:
        return sworn
    for ending_id, _ in report.top(limit=len(report.scores) or 1):
        if ending_id in report.eligible:
            return ending_id
    return report.eligible[0] if report.eligible else report.fail_forward


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def _p_ending(state: GameState, value: Any, ctx: Any) -> bool:
    """
    ``{ending: {eligible: E2a}}`` / ``{ending: {intent: E1a}}`` /
    ``{ending: {locked: E5b}}`` / ``{ending: {min_score: {id: E3a, at: 0.6}}}``

    Lets a scene, a clock beat or a thread gate read the ending state -- which
    is how ``DAY-08-MIRRORS.md``'s night-before table ("Intent E1 -> quiet;
    E3 -> surrender romance") becomes data instead of a branch.
    """
    if not isinstance(value, dict):
        return False
    if "intent" in value:
        return intent(state) == str(value["intent"])
    if "locked" in value:
        return locked(state) == str(value["locked"])
    if "eligible" in value:
        wanted = value["eligible"]
        options = wanted if isinstance(wanted, list) else [wanted]
        current = eligible(state, ledger=getattr(ctx, "ledger", None)).eligible
        return all(str(o) in current for o in options)
    if "min_score" in value:
        row = value["min_score"]
        if not isinstance(row, dict):
            return False
        scores = eligible(state, ledger=getattr(ctx, "ledger", None)).scores
        try:
            return scores.get(str(row.get("id")), 0.0) >= float(row.get("at", 1.0))
        except (TypeError, ValueError):
            return False
    return False


def _register() -> None:
    from engine.game.quests import register_predicate

    register_predicate("ending", _p_ending)


_register()


__all__ = [
    "NONE_ID",
    "REASON_FAIL_FORWARD",
    "TRACK_ELIGIBLE",
    "TRACK_INTENT",
    "TRACK_LOCKED",
    "TRACK_MODULE",
    "TRACK_SCORES",
    "EligibilityReport",
    "declared",
    "eligible",
    "fail_forward_id",
    "intent",
    "load_rules",
    "lock",
    "locked",
    "module_beats",
    "module_ran",
    "recompute",
    "resolve",
    "run_module",
    "set_intent",
]

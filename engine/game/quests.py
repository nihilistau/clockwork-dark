"""
Quest Engine
============

Arcs, quests, stages -- and the hard boundary that keeps the model out of them.

The gap this closes: the game had ``GameState.quests``, ``active_arc`` and
``arcs_unlocked`` since PR7 with no writer anywhere. Four arcs were documented
in DESIGN.md and none of them existed in code, so "awareness-gated story arcs"
was a table in a design document and nothing else. Meanwhile the only pacing
formula the game had (``engine/game/plot.py``) keyed off a flag,
``main_quest_started``, that nothing ever set -- a permanently dead term.

The design rule that shapes everything here:

    **The engine decides when a stage is complete. The model never does.**

Every ``complete_when`` predicate is engine-evaluable: a flag, a location, an
item, a disposition, a reputation, a day, an hour, awareness, evil phase, the
state of another quest, or a world event. There is no "the narrator says it
happened" predicate and there must never be one, because a model that can
declare a quest finished has not been given a quest system -- it has been given
permission to narrate whatever it likes and call it progress.

The model gets exactly one lever: :meth:`QuestEngine.set_narrative_flag`. It may
raise a flag that a currently active quest has explicitly declared it is
listening for, and nothing else. Anything else comes back rejected with the list
of flags it *could* have set, so the rejection is legible to the model rather
than a silent no-op.

Storage note: quest bookkeeping that is not per-quest (which world events have
occurred, which locations have been stood in) lives under the reserved
``state.quests["_meta"]`` key. It goes there rather than in ``state.flags``
because flags are ``dict[str, bool]`` and the arc gates need the *day* an event
happened, not just that it did. Quest ids are validated to reject a leading
underscore so nothing can collide with it.

Version: v0.1.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.effects import apply_effects
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

#: Reserved key inside ``state.quests`` for non-quest bookkeeping.
META_KEY = "_meta"

#: Quest ids must look like this. The leading-underscore ban keeps ``_meta``
#: unreachable from content.
_QUEST_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

EVENT_STARTED = "started"
EVENT_STAGE_COMPLETE = "stage_complete"
EVENT_COMPLETED = "completed"
EVENT_FAILED = "failed"
EVENT_ARC_UNLOCKED = "arc_unlocked"

#: Evil phases are ordered, so ``min_phase`` needs a rank rather than equality.
PHASE_ORDER: dict[str, int] = {
    "dormant": 0,
    "stirring": 1,
    "spreading": 2,
    "consuming": 3,
}

_DEFAULT_ARC = "quiet_life"

_ARC_CACHE: Optional[dict[str, Any]] = None
_QUEST_CACHE: Optional[dict[str, dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class QuestProgress:
    """
    Where the player stands in one quest.

    Attributes:
        quest_id: Content id of the quest.
        stage_index: Zero-based index of the stage currently in play.
        status: ``active`` | ``completed`` | ``failed``.
        started_day: World day the quest began.
        stage_started_day: World day the current stage began. Separate from
            ``started_day`` so a stage can carry its own deadline.
        flags_seen: Narrative flags the model successfully raised for this
            quest, kept as an audit trail of what the narration claimed.
    """

    quest_id: str
    stage_index: int = 0
    status: str = STATUS_ACTIVE
    started_day: int = 0
    stage_started_day: int = 0
    flags_seen: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form, which is what ``GameState.quests`` stores."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Optional[QuestProgress]:
        """
        Rebuild from a save dict, ignoring unknown keys.

        Returns None for anything unusable so a corrupt entry drops out of the
        quest log instead of taking the turn down.
        """
        if not isinstance(data, dict):
            return None
        quest_id = str(data.get("quest_id", "") or "")
        if not quest_id:
            return None
        return cls(
            quest_id=quest_id,
            stage_index=int(data.get("stage_index", 0) or 0),
            status=str(data.get("status", STATUS_ACTIVE) or STATUS_ACTIVE),
            started_day=int(data.get("started_day", 0) or 0),
            stage_started_day=int(data.get("stage_started_day", 0) or 0),
            flags_seen=[str(f) for f in (data.get("flags_seen") or [])],
        )


@dataclass
class QuestEvent:
    """
    Something the quest engine did this evaluation.

    Returned rather than logged-and-forgotten because the turn loop needs to
    show receipts: a stage that closed silently is indistinguishable, from the
    player's seat, from a stage that never existed.

    Attributes:
        kind: ``started`` | ``stage_complete`` | ``completed`` | ``failed`` |
            ``arc_unlocked``.
        quest_id: Quest id, or the arc id for ``arc_unlocked``.
        stage_id: Stage id where applicable, else empty.
        text: Player-facing line.
    """

    kind: str
    quest_id: str
    stage_id: str = ""
    text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Content loading
# ---------------------------------------------------------------------------


def quests_root() -> Path:
    """Resolve the quest content directory."""
    rel = get_config().get("paths.quests", "data/quests")
    return _ROOT / str(rel)


def reset_cache() -> None:
    """Drop the content caches. Tests that write quest YAML need this."""
    global _ARC_CACHE, _QUEST_CACHE
    _ARC_CACHE = None
    _QUEST_CACHE = None


def load_arcs() -> dict[str, dict[str, Any]]:
    """
    Load ``data/quests/arcs.yaml``.

    Returns:
        Mapping of arc id to arc definition. Empty when the file is absent --
        a missing content pack degrades to "quiet_life only" rather than
        raising, because content is loaded at runtime.
    """
    global _ARC_CACHE
    if _ARC_CACHE is not None:
        return _ARC_CACHE

    path = quests_root() / "arcs.yaml"
    if not path.exists():
        logger.warning(
            "[quests] Arc content missing (operation=load_arcs, path=%s)", path
        )
        _ARC_CACHE = {}
        return _ARC_CACHE

    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}

    arcs = doc.get("arcs") or {}
    if not isinstance(arcs, dict):
        arcs = {}

    resolved: dict[str, dict[str, Any]] = {}
    for arc_id, raw in arcs.items():
        entry = dict(raw or {})
        entry.setdefault("id", str(arc_id))
        entry.setdefault("involvement", 0)
        resolved[str(arc_id)] = entry

    _ARC_CACHE = resolved
    logger.info("[quests] Arcs loaded (operation=load_arcs, count=%s)", len(resolved))
    return _ARC_CACHE


def arc_order(arc_id: str) -> int:
    """
    Rank an arc for "furthest along" comparisons.

    Explicit ``order`` wins; otherwise involvement is the natural ordering,
    since a heavier arc is by definition a later one.
    """
    arc = load_arcs().get(arc_id)
    if not arc:
        return -1
    if "order" in arc:
        try:
            return int(arc["order"])
        except (TypeError, ValueError):
            pass
    try:
        return int(arc.get("involvement", 0))
    except (TypeError, ValueError):
        return 0


def arc_involvement(arc_id: str) -> float:
    """
    Plot-involvement weight contributed by being in a given arc.

    This is the number ``plot.py`` reads. It replaces the ``main_quest_started``
    flag bonus, which was worth a flat 15 points to a flag nothing set.
    """
    arc = load_arcs().get(arc_id)
    if not arc:
        return 0.0
    try:
        return float(arc.get("involvement", 0))
    except (TypeError, ValueError):
        return 0.0


def load_quests() -> dict[str, dict[str, Any]]:
    """
    Load every quest definition under ``data/quests/<arc>/*.yaml``.

    Returns:
        Mapping of quest id to definition, sorted by (arc order, quest id) so
        that evaluation order is deterministic across runs and platforms.
        ``os.listdir`` order is not.
    """
    global _QUEST_CACHE
    if _QUEST_CACHE is not None:
        return _QUEST_CACHE

    root = quests_root()
    found: dict[str, dict[str, Any]] = {}
    if not root.exists():
        logger.warning(
            "[quests] Quest content missing (operation=load_quests, path=%s)", root
        )
        _QUEST_CACHE = {}
        return _QUEST_CACHE

    for path in sorted(root.glob("*/*.yaml")):
        try:
            with path.open(encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:
            # A YAML typo in one quest must not remove every other quest from
            # the game. Skip the file, keep the pack.
            logger.warning(
                "[quests] Unparseable quest skipped (operation=load_quests, "
                "path=%s, error=%s)",
                path,
                exc,
            )
            continue

        quest_id = str(doc.get("id", "") or "")
        if not _QUEST_ID_RE.match(quest_id):
            logger.warning(
                "[quests] Quest rejected for bad id (operation=load_quests, "
                "path=%s, id=%r)",
                path,
                quest_id,
            )
            continue
        if quest_id in found:
            logger.warning(
                "[quests] Duplicate quest id overwritten "
                "(operation=load_quests, id=%s, path=%s)",
                quest_id,
                path,
            )
        doc.setdefault("arc", path.parent.name)
        doc.setdefault("name", quest_id.replace("_", " ").title())
        doc["stages"] = [s for s in (doc.get("stages") or []) if isinstance(s, dict)]
        found[quest_id] = doc

    ordered = dict(
        sorted(found.items(), key=lambda kv: (arc_order(str(kv[1].get("arc"))), kv[0]))
    )
    _QUEST_CACHE = ordered
    logger.info(
        "[quests] Quests loaded (operation=load_quests, count=%s)", len(ordered)
    )
    return _QUEST_CACHE


# ---------------------------------------------------------------------------
# Bookkeeping stored on state
# ---------------------------------------------------------------------------


def _meta(state: GameState) -> dict[str, Any]:
    """Get or create the reserved bookkeeping block inside ``state.quests``."""
    meta = state.quests.get(META_KEY)
    if not isinstance(meta, dict):
        meta = {}
        state.quests[META_KEY] = meta
    if not isinstance(meta.get("events_seen"), dict):
        meta["events_seen"] = {}
    if not isinstance(meta.get("visited"), list):
        meta["visited"] = []
    return meta


def progress_records(state: GameState) -> dict[str, QuestProgress]:
    """
    Every quest progress record on this state, keyed by quest id.

    Skips the reserved meta block and anything that will not coerce.
    """
    out: dict[str, QuestProgress] = {}
    for key, raw in state.quests.items():
        if key == META_KEY:
            continue
        record = QuestProgress.from_dict(raw)
        if record is not None:
            out[str(key)] = record
    return out


def _write(state: GameState, record: QuestProgress) -> None:
    """Persist a progress record back into ``state.quests``."""
    state.quests[record.quest_id] = record.to_dict()


# ---------------------------------------------------------------------------
# Predicates -- the engine-evaluable vocabulary
# ---------------------------------------------------------------------------


@dataclass
class _Ctx:
    """Everything a predicate may read besides the game state."""

    progress: Optional[QuestProgress] = None
    ledger: Optional[Any] = None
    #: Event id supplied by a sibling ``event_seen`` clause, so content can
    #: write the short form ``{event_seen: X, days_since_event: 10}``.
    anchor_event: str = ""


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else [value]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _p_flag(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return all(bool(state.flags.get(str(f))) for f in _as_list(value))


def _p_not_flag(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return not any(bool(state.flags.get(str(f))) for f in _as_list(value))


def _p_at_location(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return state.location_id in {str(v) for v in _as_list(value)}


def _p_visited(state: GameState, value: Any, ctx: _Ctx) -> bool:
    seen = set(_meta(state)["visited"])
    return all(str(v) in seen for v in _as_list(value))


def _p_has_item(state: GameState, value: Any, ctx: _Ctx) -> bool:
    if isinstance(value, dict):
        wanted = {str(value.get("id") or value.get("item_id") or ""): int(
            _num(value.get("qty"), 1)
        )}
    else:
        wanted = {str(v): 1 for v in _as_list(value)}
    for item_id, qty in wanted.items():
        if not item_id:
            return False
        entry = next((i for i in state.inventory if i.id == item_id), None)
        if entry is None or entry.qty < qty:
            return False
    return True


def _p_not_has_item(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return not _p_has_item(state, value, ctx)


def _p_disposition(state: GameState, value: Any, ctx: _Ctx) -> bool:
    """
    Compare an NPC's ledger disposition.

    Returns False with no ledger in scope. Refusing to guess is deliberate: a
    stage that says "Maris trusts you" must not close because nobody was
    holding the record of whether she does.
    """
    if not isinstance(value, dict) or ctx.ledger is None:
        return False
    npc_id = str(value.get("npc") or value.get("npc_id") or "")
    if not npc_id:
        return False
    relation = ctx.ledger.relations.get(npc_id)
    current = int(getattr(relation, "disposition", 0)) if relation else 0
    if "min" in value and current < _num(value["min"]):
        return False
    if "max" in value and current > _num(value["max"]):
        return False
    return True


def _p_reputation(state: GameState, value: Any, ctx: _Ctx) -> bool:
    if not isinstance(value, dict):
        return False
    faction = str(value.get("faction") or value.get("id") or "")
    if not faction:
        return False
    current = int(state.reputations.get(faction, 0))
    if "min" in value and current < _num(value["min"]):
        return False
    if "max" in value and current > _num(value["max"]):
        return False
    return True


def _p_min_day(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return state.world_day >= _num(value)


def _p_max_day(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return state.world_day <= _num(value)


def _p_hour_between(state: GameState, value: Any, ctx: _Ctx) -> bool:
    """
    Hour-of-day window, inclusive start and exclusive end.

    Wraps across midnight when start > end, so ``[22, 4]`` means the small
    hours rather than the empty set.
    """
    pair = _as_list(value)
    if len(pair) != 2:
        return False
    start, end = int(_num(pair[0])), int(_num(pair[1]))
    hour = state.world_hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def _p_time_of_day(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return state.time_of_day in {str(v) for v in _as_list(value)}


def _p_min_awareness(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return state.awareness >= _num(value)


def _p_max_awareness(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return state.awareness <= _num(value)


def _p_min_phase(state: GameState, value: Any, ctx: _Ctx) -> bool:
    want = PHASE_ORDER.get(str(value).strip().lower())
    if want is None:
        return False
    return PHASE_ORDER.get(state.evil_phase.value, 0) >= want


def _p_max_phase(state: GameState, value: Any, ctx: _Ctx) -> bool:
    want = PHASE_ORDER.get(str(value).strip().lower())
    if want is None:
        return False
    return PHASE_ORDER.get(state.evil_phase.value, 0) <= want


def _p_min_gold(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return state.stats.gold >= _num(value)


def _p_min_stat(state: GameState, value: Any, ctx: _Ctx) -> bool:
    if not isinstance(value, dict):
        return False
    name = str(value.get("stat", ""))
    if not hasattr(state.stats, name):
        return False
    return _num(getattr(state.stats, name)) >= _num(value.get("min"))


def _p_quest_state(state: GameState, value: Any, ctx: _Ctx) -> bool:
    if not isinstance(value, dict):
        return False
    quest_id = str(value.get("quest") or value.get("id") or "")
    record = progress_records(state).get(quest_id)
    wanted = str(value.get("status", STATUS_COMPLETED))
    if "stage_at_least" in value:
        if record is None:
            return False
        return record.stage_index >= int(_num(value["stage_at_least"]))
    if wanted == "not_started":
        return record is None
    return record is not None and record.status == wanted


def _p_quest_completed(state: GameState, value: Any, ctx: _Ctx) -> bool:
    records = progress_records(state)
    return all(
        (records.get(str(q)) is not None and records[str(q)].status == STATUS_COMPLETED)
        for q in _as_list(value)
    )


def _p_event_seen(state: GameState, value: Any, ctx: _Ctx) -> bool:
    seen = _meta(state)["events_seen"]
    return all(str(v) in seen for v in _as_list(value))


def _p_event_active(state: GameState, value: Any, ctx: _Ctx) -> bool:
    live = {str(e.get("event_id")) for e in state.world_events}
    return all(str(v) in live for v in _as_list(value))


def _p_days_since_event(state: GameState, value: Any, ctx: _Ctx) -> bool:
    """
    Time elapsed since a world event first occurred.

    Two forms, because both read naturally in content:
      - ``{days_since_event: {event: caravan_arrival, days: 10}}``
      - ``{event_seen: caravan_arrival, days_since_event: 10}`` -- the event is
        taken from the sibling ``event_seen`` clause in the same group.
    """
    if isinstance(value, dict):
        event_id = str(value.get("event") or value.get("event_id") or "")
        days = _num(value.get("days"))
    else:
        event_id = ctx.anchor_event
        days = _num(value)
    if not event_id:
        return False
    first_day = _meta(state)["events_seen"].get(event_id)
    if first_day is None:
        return False
    return (state.world_day - int(first_day)) >= days


def _p_arc_unlocked(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return all(str(v) in state.arcs_unlocked for v in _as_list(value))


def _p_active_arc(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return state.active_arc in {str(v) for v in _as_list(value)}


def _p_days_in_stage(state: GameState, value: Any, ctx: _Ctx) -> bool:
    if ctx.progress is None:
        return False
    return (state.world_day - ctx.progress.stage_started_day) >= _num(value)


def _p_days_since_started(state: GameState, value: Any, ctx: _Ctx) -> bool:
    if ctx.progress is None:
        return False
    return (state.world_day - ctx.progress.started_day) >= _num(value)


def _p_procgen_day(state: GameState, value: Any, ctx: _Ctx) -> bool:
    """
    World day has reached a day chosen by seeded world generation.

    ``ProcgenResult.bakery_job_day`` was generated on every run and read by
    nothing at all. This is the predicate that finally reads it, so the day
    Maris starts looking for hands actually varies with the world seed.
    """
    name = str(value)
    if not hasattr(state.procgen, name):
        return False
    return state.world_day >= _num(getattr(state.procgen, name))


def _p_min_turn(state: GameState, value: Any, ctx: _Ctx) -> bool:
    return state.turn_number >= _num(value)


_PREDICATES: dict[str, Any] = {
    "flag": _p_flag,
    "not_flag": _p_not_flag,
    "at_location": _p_at_location,
    "visited": _p_visited,
    "has_item": _p_has_item,
    "not_has_item": _p_not_has_item,
    "disposition": _p_disposition,
    "reputation": _p_reputation,
    "min_day": _p_min_day,
    "max_day": _p_max_day,
    "hour_between": _p_hour_between,
    "time_of_day": _p_time_of_day,
    "min_awareness": _p_min_awareness,
    "max_awareness": _p_max_awareness,
    "min_phase": _p_min_phase,
    "max_phase": _p_max_phase,
    "min_gold": _p_min_gold,
    "min_stat": _p_min_stat,
    "quest_state": _p_quest_state,
    "quest_completed": _p_quest_completed,
    "event_seen": _p_event_seen,
    "event_active": _p_event_active,
    "days_since_event": _p_days_since_event,
    "arc_unlocked": _p_arc_unlocked,
    "active_arc": _p_active_arc,
    "days_in_stage": _p_days_in_stage,
    "days_since_started": _p_days_since_started,
    "procgen_day": _p_procgen_day,
    "min_turn": _p_min_turn,
}

#: Group combinators, kept out of the predicate table so a content author
#: cannot accidentally shadow one with a predicate name.
_GROUP_KEYS = ("all", "any", "none")


def evaluate_condition(
    state: GameState,
    condition: Any,
    *,
    progress: Optional[QuestProgress] = None,
    ledger: Optional[Any] = None,
) -> bool:
    """
    Evaluate a content-declared condition tree.

    Shapes accepted:
      - ``None`` / ``[]`` / ``{}`` -> True (no condition is a satisfied one)
      - a list -> every entry must hold
      - ``{all: [...]}``, ``{any: [...]}``, ``{none: [...]}``
      - a predicate dict, possibly with several keys, all of which must hold

    Args:
        state: Game state to read.
        condition: Condition tree from YAML.
        progress: Progress record, for stage-relative predicates.
        ledger: Optional StoryLedger, required only by ``disposition``.

    Returns:
        True when the condition holds. Unknown predicate names are logged and
        treated as False -- a stage guarded by a predicate this build does not
        understand must stay shut, never fall open.
    """
    ctx = _Ctx(progress=progress, ledger=ledger)
    return _eval(state, condition, ctx)


def _eval(state: GameState, condition: Any, ctx: _Ctx) -> bool:
    if condition is None:
        return True
    if isinstance(condition, list):
        return _eval_all(state, condition, ctx)
    if not isinstance(condition, dict):
        logger.warning(
            "[quests] Malformed condition ignored "
            "(operation=evaluate_condition, condition=%r)",
            condition,
        )
        return False
    if not condition:
        return True

    if any(key in condition for key in _GROUP_KEYS):
        if "all" in condition and not _eval_all(state, _as_list(condition["all"]), ctx):
            return False
        if "any" in condition:
            options = _as_list(condition["any"])
            if options and not any(_eval(state, opt, ctx) for opt in options):
                return False
        if "none" in condition:
            if any(_eval(state, opt, ctx) for opt in _as_list(condition["none"])):
                return False
        return True

    return _eval_predicate_dict(state, condition, ctx)


def _eval_all(state: GameState, entries: list[Any], ctx: _Ctx) -> bool:
    """
    Every entry must hold, with ``event_seen`` acting as an anchor.

    The anchor is resolved before evaluation so a later ``days_since_event: 10``
    in the same group knows which event it is counting from, regardless of the
    order the author wrote them in.
    """
    local = _Ctx(progress=ctx.progress, ledger=ctx.ledger, anchor_event=ctx.anchor_event)
    for entry in entries:
        if isinstance(entry, dict) and "event_seen" in entry:
            anchors = _as_list(entry["event_seen"])
            if anchors:
                local.anchor_event = str(anchors[0])
                break
    return all(_eval(state, entry, local) for entry in entries)


def _eval_predicate_dict(state: GameState, condition: dict[str, Any], ctx: _Ctx) -> bool:
    local = ctx
    if "event_seen" in condition:
        anchors = _as_list(condition["event_seen"])
        if anchors:
            local = _Ctx(
                progress=ctx.progress,
                ledger=ctx.ledger,
                anchor_event=str(anchors[0]),
            )
    for key, value in condition.items():
        handler = _PREDICATES.get(str(key))
        if handler is None:
            logger.warning(
                "[quests] Unknown predicate treated as unmet "
                "(operation=evaluate_condition, predicate=%s)",
                key,
            )
            return False
        if not handler(state, value, local):
            return False
    return True


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class QuestEngine:
    """
    Arc unlocking, quest starting, stage advancement and failure.

    Every method is a staticmethod taking explicit state: there is no quest
    singleton, because two sessions in one process must not share a quest log.
    """

    # -- observation -----------------------------------------------------

    @staticmethod
    def observe(state: GameState) -> None:
        """
        Record the durable facts the arc gates need.

        World events expire from ``state.world_events`` after a couple of days
        (``WorldSim.expire_events``), so "the caravan came on day six" is gone
        from state by day eight -- and the Whisper arc gate needs exactly that,
        ten days later. This writes it down while it is still true.

        Args:
            state: Mutable game state.
        """
        meta = _meta(state)
        visited: list[str] = meta["visited"]
        if state.location_id and state.location_id not in visited:
            visited.append(state.location_id)
        events: dict[str, Any] = meta["events_seen"]
        for raw in state.world_events:
            event_id = str(raw.get("event_id", "") or "")
            if event_id and event_id not in events:
                day = raw.get("day", state.world_day)
                try:
                    events[event_id] = int(day)
                except (TypeError, ValueError):
                    events[event_id] = state.world_day

    # -- arcs ------------------------------------------------------------

    @staticmethod
    def unlock_arcs(state: GameState) -> list[QuestEvent]:
        """
        Unlock any arc whose gate now holds, and move ``active_arc`` forward.

        Arcs are monotonic. An arc never re-locks and ``active_arc`` never
        walks back down the ladder, because the fiction cannot un-happen: once
        the player has seen the militia take a farmer's son, "quiet life" is
        still a way to play but it is no longer the story they are in.

        Args:
            state: Mutable game state.

        Returns:
            One ``arc_unlocked`` event per newly opened arc.
        """
        events: list[QuestEvent] = []
        arcs = load_arcs()

        for arc_id, arc in sorted(arcs.items(), key=lambda kv: arc_order(str(kv[0]))):
            if arc_id in state.arcs_unlocked:
                continue
            if arc.get("default"):
                state.arcs_unlocked.append(arc_id)
                continue
            gate_all = arc.get("requires_all")
            gate_any = arc.get("requires_any")
            if gate_all is None and gate_any is None:
                continue
            condition: dict[str, Any] = {}
            if gate_all is not None:
                condition["all"] = gate_all
            if gate_any is not None:
                condition["any"] = gate_any
            if not evaluate_condition(state, condition):
                continue
            state.arcs_unlocked.append(arc_id)
            events.append(
                QuestEvent(
                    kind=EVENT_ARC_UNLOCKED,
                    quest_id=arc_id,
                    text=str(arc.get("unlock_text") or f"A new thread opens: {arc_id}."),
                )
            )
            logger.info(
                "[quests] Arc unlocked (operation=unlock_arcs, arc=%s, day=%s)",
                arc_id,
                state.world_day,
            )

        # active_arc is the furthest-along unlocked arc, and only ever climbs.
        best = max(
            state.arcs_unlocked or [_DEFAULT_ARC],
            key=lambda a: arc_order(str(a)),
        )
        if arc_order(str(best)) > arc_order(state.active_arc):
            state.active_arc = str(best)
        return events

    # -- quests ----------------------------------------------------------

    @staticmethod
    def active_quests(state: GameState) -> list[tuple[dict[str, Any], QuestProgress]]:
        """Definitions and progress for every quest currently in play."""
        definitions = load_quests()
        out: list[tuple[dict[str, Any], QuestProgress]] = []
        for quest_id, record in progress_records(state).items():
            if record.status != STATUS_ACTIVE:
                continue
            definition = definitions.get(quest_id)
            if definition is not None:
                out.append((definition, record))
        return out

    @staticmethod
    def current_stage(
        definition: dict[str, Any], record: QuestProgress
    ) -> Optional[dict[str, Any]]:
        """Stage dict the record points at, or None when past the end."""
        stages = definition.get("stages") or []
        if 0 <= record.stage_index < len(stages):
            return stages[record.stage_index]
        return None

    @staticmethod
    def active_objectives(state: GameState) -> list[str]:
        """
        Player-facing objective lines for the Storyteller prompt.

        One line per active quest, naming the quest and what is currently being
        asked. Written to be dropped straight into a prompt block: no ids, no
        mechanics, no numbers the narrator would then leak into prose.

        Args:
            state: Game state to read.

        Returns:
            Lines like ``"Flour on Your Sleeves - Ask Maris whether she needs
            hands before the frost."`` Empty when nothing is open.
        """
        lines: list[str] = []
        for definition, record in QuestEngine.active_quests(state):
            stage = QuestEngine.current_stage(definition, record)
            if stage is None:
                continue
            objective = str(stage.get("objective", "") or "").strip()
            if not objective:
                continue
            name = str(definition.get("name") or record.quest_id)
            lines.append(f"{name} - {objective}")
        return lines

    # -- narrative flags -------------------------------------------------

    @staticmethod
    def allowed_narrative_flags(state: GameState) -> set[str]:
        """
        The complete set of flags the model is permitted to raise right now.

        Scoped to quest-level flags plus the *current* stage of each active
        quest. A later stage's flags are deliberately out of reach: if the model
        could set them it could raise stage four's flag during stage one and
        skip the intervening fiction entirely.
        """
        allowed: set[str] = set()
        for definition, record in QuestEngine.active_quests(state):
            allowed.update(str(f) for f in (definition.get("narrative_flags") or []))
            stage = QuestEngine.current_stage(definition, record)
            if stage is not None:
                allowed.update(str(f) for f in (stage.get("narrative_flags") or []))
        return allowed

    @staticmethod
    def set_narrative_flag(state: GameState, flag_id: str) -> bool:
        """
        Raise a narrative flag on behalf of the narrating model.

        This is the model's ONLY write into quest progress, and it is not a
        completion: it is an observation ("the player did in fact ask Maris for
        work") that a ``complete_when`` predicate may then read. The engine
        still decides whether the stage closes.

        Args:
            state: Mutable game state.
            flag_id: Flag the model wants to raise.

        Returns:
            True when the flag was accepted and set. False when it is not
            declared by any active quest -- callers should surface the rejection
            plus :meth:`allowed_narrative_flags` so the model can correct itself
            rather than repeat the same invalid call.
        """
        flag_id = str(flag_id or "").strip()
        allowed = QuestEngine.allowed_narrative_flags(state)
        if not flag_id or flag_id not in allowed:
            logger.warning(
                "[quests] Narrative flag rejected (operation=set_narrative_flag, "
                "flag=%s, allowed=%s)",
                flag_id or "<empty>",
                sorted(allowed),
            )
            return False

        apply_effects(state, [{"type": "flag", "flag": flag_id, "value": True}])
        for definition, record in QuestEngine.active_quests(state):
            stage = QuestEngine.current_stage(definition, record)
            declared = set(str(f) for f in (definition.get("narrative_flags") or []))
            if stage is not None:
                declared.update(str(f) for f in (stage.get("narrative_flags") or []))
            if flag_id in declared and flag_id not in record.flags_seen:
                record.flags_seen.append(flag_id)
                _write(state, record)
        logger.info(
            "[quests] Narrative flag set (operation=set_narrative_flag, flag=%s)",
            flag_id,
        )
        return True

    # -- evaluation ------------------------------------------------------

    @staticmethod
    def evaluate(state: GameState, ledger: Optional[Any] = None) -> list[QuestEvent]:
        """
        Run the whole quest machine once.

        Call this on every turn end and every clock advance. It is idempotent:
        running it twice with nothing changed produces no second batch of
        events, because every transition it makes is recorded on state first.

        Order matters. Observation runs first so an arc gate can see an event
        that expires this same tick; arcs unlock before quests start so a quest
        gated on a fresh arc is available immediately rather than a turn late;
        failure is checked before completion so a stage cannot be completed on
        the day its deadline passed.

        Args:
            state: Mutable game state.
            ledger: Optional StoryLedger. Quest events write facts to it and
                keep ``open_threads`` in sync with the active quest list.

        Returns:
            Every transition that happened, in the order it happened.
        """
        events: list[QuestEvent] = []
        QuestEngine.observe(state)
        events.extend(QuestEngine.unlock_arcs(state))
        events.extend(QuestEngine._start_eligible(state, ledger))
        events.extend(QuestEngine._advance_active(state, ledger))
        QuestEngine._sync_threads(state, ledger)

        if events:
            logger.info(
                "[quests] Evaluation produced transitions "
                "(operation=evaluate, count=%s, day=%s)",
                len(events),
                state.world_day,
            )
        return events

    @staticmethod
    def _start_eligible(
        state: GameState, ledger: Optional[Any]
    ) -> list[QuestEvent]:
        """Start every quest whose arc is open and whose preconditions hold."""
        events: list[QuestEvent] = []
        records = progress_records(state)
        for quest_id, definition in load_quests().items():
            if quest_id in records:
                continue
            if not definition.get("auto_start", True):
                continue
            arc = str(definition.get("arc", _DEFAULT_ARC))
            if arc not in state.arcs_unlocked:
                continue
            if not evaluate_condition(
                state, definition.get("preconditions"), ledger=ledger
            ):
                continue

            record = QuestProgress(
                quest_id=quest_id,
                stage_index=0,
                status=STATUS_ACTIVE,
                started_day=state.world_day,
                stage_started_day=state.world_day,
            )
            _write(state, record)
            QuestEngine._apply_hook(state, definition.get("on_start"), ledger)
            stage = QuestEngine.current_stage(definition, record)
            if stage is not None:
                QuestEngine._apply_hook(state, stage.get("on_enter"), ledger)
            text = str(
                definition.get("start_text")
                or definition.get("summary")
                or f"{definition.get('name', quest_id)} begins."
            )
            events.append(
                QuestEvent(
                    kind=EVENT_STARTED,
                    quest_id=quest_id,
                    stage_id=str(stage.get("id", "")) if stage else "",
                    text=text,
                )
            )
            QuestEngine._remember(
                state, ledger, f"Began: {definition.get('name', quest_id)}."
            )
            logger.info(
                "[quests] Quest started (operation=evaluate, quest=%s, day=%s)",
                quest_id,
                state.world_day,
            )
        return events

    @staticmethod
    def _advance_active(
        state: GameState, ledger: Optional[Any]
    ) -> list[QuestEvent]:
        """Fail, advance or complete each active quest."""
        events: list[QuestEvent] = []
        definitions = load_quests()

        for quest_id, record in progress_records(state).items():
            if record.status != STATUS_ACTIVE:
                continue
            definition = definitions.get(quest_id)
            if definition is None:
                # Content removed under a live save. Leave the record alone so
                # reinstalling the pack resumes rather than restarts.
                continue

            # A single evaluation may close several stages when the player has
            # already satisfied them (for instance after a long sleep). Bounded
            # by the stage count so malformed content cannot spin here.
            for _ in range(len(definition.get("stages") or []) + 1):
                stage = QuestEngine.current_stage(definition, record)
                if stage is None:
                    events.append(
                        QuestEngine._complete(state, definition, record, ledger)
                    )
                    break

                failure = QuestEngine._check_failure(state, definition, record, stage)
                if failure is not None:
                    events.append(
                        QuestEngine._fail(state, definition, record, stage, failure, ledger)
                    )
                    break

                if not evaluate_condition(
                    state, stage.get("complete_when"), progress=record, ledger=ledger
                ):
                    break

                QuestEngine._apply_hook(state, stage.get("on_complete"), ledger)
                events.append(
                    QuestEvent(
                        kind=EVENT_STAGE_COMPLETE,
                        quest_id=quest_id,
                        stage_id=str(stage.get("id", "")),
                        text=str(stage.get("complete_text") or stage.get("objective", "")),
                    )
                )
                logger.info(
                    "[quests] Stage complete (operation=evaluate, quest=%s, stage=%s)",
                    quest_id,
                    stage.get("id"),
                )
                record.stage_index += 1
                record.stage_started_day = state.world_day
                _write(state, record)

                next_stage = QuestEngine.current_stage(definition, record)
                if next_stage is not None:
                    QuestEngine._apply_hook(state, next_stage.get("on_enter"), ledger)
                else:
                    events.append(
                        QuestEngine._complete(state, definition, record, ledger)
                    )
                    break
        return events

    @staticmethod
    def _check_failure(
        state: GameState,
        definition: dict[str, Any],
        record: QuestProgress,
        stage: dict[str, Any],
    ) -> Optional[str]:
        """
        Return a failure reason, or None if the quest is still viable.

        Deadlines are inclusive of the final day: a stage with
        ``expires_after_days: 2`` started on day 3 is still live on day 5 and
        fails on day 6. Written out because off-by-one here is the difference
        between a fair deadline and a stolen day.
        """
        stage_limit = stage.get("expires_after_days")
        if stage_limit is not None:
            if state.world_day > record.stage_started_day + _num(stage_limit):
                return "expired"
        quest_limit = definition.get("expires_after_days")
        if quest_limit is not None:
            if state.world_day > record.started_day + _num(quest_limit):
                return "expired"
        fail_when = stage.get("fail_when") or definition.get("fail_when")
        if fail_when is not None and evaluate_condition(
            state, fail_when, progress=record
        ):
            return "failed"
        return None

    @staticmethod
    def _complete(
        state: GameState,
        definition: dict[str, Any],
        record: QuestProgress,
        ledger: Optional[Any],
    ) -> QuestEvent:
        record.status = STATUS_COMPLETED
        _write(state, record)
        QuestEngine._apply_hook(state, definition.get("on_complete"), ledger)
        name = str(definition.get("name", record.quest_id))
        text = str(definition.get("complete_text") or f"{name} is finished.")
        QuestEngine._remember(state, ledger, f"Finished: {name}.")
        logger.info(
            "[quests] Quest completed (operation=evaluate, quest=%s, day=%s)",
            record.quest_id,
            state.world_day,
        )
        return QuestEvent(
            kind=EVENT_COMPLETED, quest_id=record.quest_id, stage_id="", text=text
        )

    @staticmethod
    def _fail(
        state: GameState,
        definition: dict[str, Any],
        record: QuestProgress,
        stage: dict[str, Any],
        reason: str,
        ledger: Optional[Any],
    ) -> QuestEvent:
        record.status = STATUS_FAILED
        _write(state, record)
        hook = stage.get("on_fail") or definition.get("on_fail")
        QuestEngine._apply_hook(state, hook, ledger)
        name = str(definition.get("name", record.quest_id))
        text = str(
            stage.get("fail_text")
            or definition.get("fail_text")
            or f"{name} slipped past you."
        )
        QuestEngine._remember(state, ledger, f"Let slip: {name}.")
        logger.info(
            "[quests] Quest failed (operation=evaluate, quest=%s, stage=%s, reason=%s)",
            record.quest_id,
            stage.get("id"),
            reason,
        )
        return QuestEvent(
            kind=EVENT_FAILED,
            quest_id=record.quest_id,
            stage_id=str(stage.get("id", "")),
            text=text,
        )

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _apply_hook(
        state: GameState, hook: Any, ledger: Optional[Any]
    ) -> list[dict[str, Any]]:
        """
        Apply a content hook's effects through the single mutation dispatcher.

        Rewards go through ``effects.apply_effect`` and nowhere else, so a
        quest that pays five gold is clamped, described and receipted exactly
        like a table draw that pays five gold.
        """
        if not isinstance(hook, dict):
            return []
        return apply_effects(state, hook.get("effects") or [], ledger=ledger)

    @staticmethod
    def _remember(state: GameState, ledger: Optional[Any], text: str) -> None:
        """Write an engine-sourced fact so the narrator's prompt knows."""
        if ledger is None:
            return
        ledger.add_fact(
            text,
            kind="event",
            turn=state.turn_number,
            day=state.world_day,
            source="engine",
        )

    @staticmethod
    def _sync_threads(state: GameState, ledger: Optional[Any]) -> None:
        """
        Keep ``ledger.open_threads`` equal to the active quest ids.

        ``open_threads`` was declared for exactly this and never written to.
        """
        if ledger is None:
            return
        ledger.open_threads = [
            record.quest_id for _, record in QuestEngine.active_quests(state)
        ]

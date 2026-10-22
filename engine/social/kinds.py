"""
Names the social engine shares with the rest of the engine (v0.22.0).

Imports nothing from `engine`: `engine/game/effects.py` reads
SOCIAL_EFFECT_KINDS at import, and a story without `paths.social` must not
pull the social package in (spec §2.1).
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger(__name__)

SOCIAL_EFFECT_KINDS: frozenset[str] = frozenset({
    "social_profile", "social_event", "social_queue", "social_person", "social_app",
    "social_match", "social_unmatch", "social_message", "social_read", "social_settings",
    "social_regard", "social_stage", "social_request", "social_history", "social_voiced",
    "social_memory", "social_media_decision", "social_media", "social_game",
    "social_growth",                                                    # v0.23.0 T2
    "social_episode",                                                   # v0.23.0 T3
    "social_promise",                                                   # v0.23.0 T4
    "social_go",                                                        # v0.23.0 T11
    "social_plan",                                                      # v0.23.0 T12
    "social_scene",                                                     # v0.23.0 T13 (and v0.22's social_meet retired)
    "social_life",                                                      # v0.23.0 T17
    "social_household",                                                 # v0.23.0 T18
    "social_migrate",                                                   # v0.23.0 T20
})


#: The social slice's own schema (v0.23.0 spec §16): a v0.22.0 slice has no `schema` key (read as 1)
#: and is upgraded at load. `CURRENT_SAVE_VERSION` is untouched, so no other story's save moves.
SCHEMA: int = 2


def empty_slice() -> dict[str, Any]:
    """The skeleton `state.social` gets at creation (see the plan's shared interfaces)."""
    return {
        "schema": SCHEMA,
        "player": {}, "seq": 0, "queue": [], "people": {}, "threads": {},
        "notifications": [], "apps": {}, "requests": {}, "media": {}, "games": {},
        "promises": {},                      # promise id ("pr<n>") -> its row (spec §5.1)
        "plans": {},                         # plan id ("pl<n>") -> its row (spec §9.1)
        "scene": {},                         # the one open scene, {} when none (spec §10.1)
        "household": "",                     # the partner's pid, "" when none (spec §12.3)
        "phone_up": True,                    # the phone is in the player's hand (spec §8.2)
        "at_work": False,                    # the player is at work (spec §8.4)
        "settings": {"receipts": True, "wake_for_messages": False},
        "open_thread": "",
        # Notifications keep v0.22's own `counters["notification"]`, set by messaging.notify (F25).
        "counters": {"message": 0, "request": 0, "media": 0, "game": 0,
                     "episode": 0, "promise": 0, "plan": 0},
        "last_active_wall": 0.0, "dirty_reason": "",
    }


#: What a plan is of, and when it is, in words (spec §9.1; engine/social/plans.py, whose data checks them against
#: plans.yaml). Here so the `ask` verb's payload can name them without importing plans.
PLAN_KINDS: tuple[str, ...] = ("coffee", "drinks", "dinner", "walk", "visit", "film", "climbing", "games",
                               "gig", "their_place", "your_place")
PLAN_WHENS: tuple[str, ...] = ("now", "tonight", "soon")


#: What a person may send, or the player ask for, beside words (spec §13.1):
#: messaging's `ask` and `send` and engine/social/media.py share it.
MEDIA_KINDS: tuple[str, ...] = ("photo", "voice", "video")


#: Every stage a person can be at with the player (spec §10.3), plus T7's
#: `expired` (a match nobody wrote in), and v0.23.0's three long-term stages
#: (spec §12.1), each ranked after `exclusive`. Transitions are T9's (`social_stage`);
#: messaging reads the order for an initiation's `stage_min`.
STAGES: tuple[str, ...] = (
    "matched", "talking", "numbers", "meeting", "dating", "friends", "fling", "exclusive",
    "living_together", "engaged", "married",
    "winding_down", "ended", "faded", "expired",
)

#: How far along a LIVE stage is (spec §10.3's "From" column); a stage not
#: listed (winding down, ended, faded, expired) is behind every live one.
STAGE_RANKS: tuple[tuple[str, int], ...] = (
    ("matched", 0), ("talking", 1), ("numbers", 2), ("meeting", 3),
    ("dating", 4), ("friends", 4), ("fling", 4), ("exclusive", 5),
    ("living_together", 6), ("engaged", 7), ("married", 8),   # v0.23.0 spec §12.1
)


def stage_rank(stage: Any) -> int:
    """A stage's place in STAGE_RANKS; -1 for any stage that is not a live one."""
    return dict(STAGE_RANKS).get(str(stage or ""), -1)


#: How full a reply runs (spec §4.5).
MODES: tuple[str, ...] = ("quick", "chatting", "deep")
#: How a decided reply ends its episode (spec §4.4, §5.2).
DECISION_ENDS: tuple[str, ...] = ("none", "winding", "sign_off")


@dataclass(frozen=True)
class Decision:
    """
    What the engine decided a due message IS, before any model writes it
    (spec §9.1, §11.2; Plan decision 16). Stored as its `asdict` in the
    message row's `decision`. `engine/social/voicing.py` (T13) re-exports
    this class: one class, two import paths.
    """

    situation: str                 # an id in texter.md's instruction table: opener, reply, double_text, ...
    kind: str = "text"             # text | voice | photo | video | decline
    max_bubbles: int = 3
    media_kind: str = ""           # "", photo, voice, video -- set exactly when media is attached
    subject: str = ""              # a media.yaml subject id when media_kind is set
    reveal: str = ""               # an arc's canon row id (§5.3)
    request_id: str = ""           # the request this answers/declines
    game_id: str = ""              # game_banter
    # v0.23.0 (spec §4.5, §5.2, §7.3; Plan decision 10)
    mode: str = "quick"            # one of MODES
    min_bubbles: int = 1           # the burst minimum (§4.5)
    end: str = "none"              # one of DECISION_ENDS
    reason: str = ""               # the engine's words for why, voiced by the model
    promise_id: str = ""
    followup_id: str = ""
    plan_id: str = ""              # invite, flake, stood_up, arrived (v0.23.0 T23C)
    after_together: bool = False   # held while they were with the player, landing now they are apart (W5)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"Decision.mode: {self.mode!r} is not one of {', '.join(MODES)}")
        if self.end not in DECISION_ENDS:
            raise ValueError(f"Decision.end: {self.end!r} is not one of {', '.join(DECISION_ENDS)}")


def decision_from_row(row: Any, *, where: str = "") -> Decision:
    """
    A stored decision dict (a message row's or an event's `decision`) rebuilt as a `Decision`:
    unknown keys dropped, `situation` defaulting to `reply`, and an unknown `mode` or `end` CLAMPED
    to its default with a WARNING naming it (v0.23.0 T3) -- a save written by another version, or
    a hand-edited one, must never make a due message unvoiceable. A NEW decision is still built
    with `Decision(...)`, whose own check raises (an engine bug must be loud).
    """
    known = {f.name for f in dataclasses.fields(Decision)}
    raw = {k: v for k, v in dict(row or {}).items() if k in known}
    raw.setdefault("situation", "reply")
    for key, allowed, default in (("mode", MODES, "quick"), ("end", DECISION_ENDS, "none")):
        if key in raw and raw[key] not in allowed:
            logger.warning("[social] A stored decision's %s %r is unknown; read as %r (operation=decision_from_row, "
                           "where=%s)", key, raw[key], default, where or "?")
            raw[key] = default
    return Decision(**raw)


#: The applied social effects' results of the phone action running in this
#: context (v0.22.0 T10): set by `collecting`, appended to by every handler
#: wrapped in `recorded`. None outside an action, so nothing is kept.
_APPLIED: ContextVar[Optional[list[dict[str, Any]]]] = ContextVar("social_applied", default=None)
#: The presence memo of ONE pass (a world turn, a phone action; `presence.one_pass`): the chance tier computed once
#: and read by every caller in that pass (A4 W9, I7). None outside a pass. Any social effect drops what it holds
#: (`recorded`), so a pass never reads a tier from before a write.
PRESENCE_PASS: ContextVar[Optional[dict[Any, Any]]] = ContextVar("social_presence_pass", default=None)


@contextlib.contextmanager
def collecting() -> Iterator[list[dict[str, Any]]]:
    """Collect, in order, the result of every social effect applied inside the block (nested ones too)."""
    rows: list[dict[str, Any]] = []
    token = _APPLIED.set(rows)
    try:
        yield rows
    finally:
        _APPLIED.reset(token)


def recorded(handler: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """
    A social effect handler whose result joins the collecting action's list,
    so a phone action's result carries every effect it applied -- those its
    events applied while time passed included -- and the mechanics action
    reads its save triggers (`save_reason`) off them (spec §16.1 step 4).
    """
    @functools.wraps(handler)
    def run(state: Any, effect: dict[str, Any], ctx: Any) -> dict[str, Any]:
        result = handler(state, effect, ctx)
        memo = PRESENCE_PASS.get()
        if memo:
            memo.clear()                      # a write: presence is read afresh for the rest of the pass
        rows = _APPLIED.get()
        if rows is not None and isinstance(result, dict):
            rows.append(result)
        return result

    return run

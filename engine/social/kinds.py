"""
Names the social engine shares with the rest of the engine (v0.22.0).

Imports nothing from `engine`: `engine/game/effects.py` reads
SOCIAL_EFFECT_KINDS at import, and a story without `paths.social` must not
pull the social package in (spec §2.1).
"""

from __future__ import annotations

import contextlib
import functools
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

SOCIAL_EFFECT_KINDS: frozenset[str] = frozenset({
    "social_profile", "social_event", "social_queue", "social_person", "social_app",
    "social_match", "social_unmatch", "social_message", "social_read", "social_settings",
    "social_regard", "social_stage", "social_request", "social_history", "social_voiced",
    "social_memory", "social_media_decision", "social_media", "social_game", "social_meet",
})


def empty_slice() -> dict[str, Any]:
    """The skeleton `state.social` gets at creation (see the plan's shared interfaces)."""
    return {
        "player": {}, "seq": 0, "queue": [], "people": {}, "threads": {},
        "notifications": [], "apps": {}, "requests": {}, "media": {}, "games": {},
        "meets": {}, "settings": {"receipts": True, "auto_wait": False},
        "open_thread": "",
        "counters": {"message": 0, "request": 0, "media": 0, "game": 0, "meet": 0},
        "last_active_wall": 0.0, "dirty_reason": "",
    }


#: What a person may send, or the player ask for, beside words (spec §13.1):
#: messaging's `ask` and `send` and engine/social/media.py share it.
MEDIA_KINDS: tuple[str, ...] = ("photo", "voice", "video")


#: Every stage a person can be at with the player (spec §10.3), plus T7's
#: `expired` (a match nobody wrote in). Transitions are T9's (`social_stage`);
#: messaging reads the order for an initiation's `stage_min`.
STAGES: tuple[str, ...] = (
    "matched", "talking", "numbers", "meeting", "dating", "friends", "fling", "exclusive",
    "winding_down", "ended", "faded", "expired",
)

#: How far along a LIVE stage is (spec §10.3's "From" column); a stage not
#: listed (winding down, ended, faded, expired) is behind every live one.
STAGE_RANKS: tuple[tuple[str, int], ...] = (
    ("matched", 0), ("talking", 1), ("numbers", 2), ("meeting", 3),
    ("dating", 4), ("friends", 4), ("fling", 4), ("exclusive", 5),
)


def stage_rank(stage: Any) -> int:
    """A stage's place in STAGE_RANKS; -1 for any stage that is not a live one."""
    return dict(STAGE_RANKS).get(str(stage or ""), -1)


@dataclass(frozen=True)
class Decision:
    """
    What the engine decided a due message IS, before any model writes it
    (spec §9.1, §11.2; Plan decision 16). Stored as its `asdict` in the
    message row's `decision`. `engine/social/voicing.py` (T13) re-exports
    this class: one class, two import paths.
    """

    situation: str                 # an id in texter.md's instruction table: opener, reply, double_text, ...
    kind: str = "text"             # text | voice | photo | video | decline | recap
    max_bubbles: int = 3
    media_kind: str = ""           # "", photo, voice, video -- set exactly when media is attached
    subject: str = ""              # a media.yaml subject id when media_kind is set
    reveal: str = ""               # an arc's canon row id (§5.3)
    request_id: str = ""           # the request this answers/declines
    game_id: str = ""              # game_banter
    meet_id: str = ""              # post_meet / recap


#: The applied social effects' results of the phone action running in this
#: context (v0.22.0 T10): set by `collecting`, appended to by every handler
#: wrapped in `recorded`. None outside an action, so nothing is kept.
_APPLIED: ContextVar[Optional[list[dict[str, Any]]]] = ContextVar("social_applied", default=None)


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
        rows = _APPLIED.get()
        if rows is not None and isinstance(result, dict):
            rows.append(result)
        return result

    return run

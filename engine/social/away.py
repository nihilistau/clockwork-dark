"""
Away and resume (v0.22.0 spec §15.2-15.3).

The in-game clock moves only by the player's actions while they are on the
phone (§15.1). Since v0.23.0 the default is `social.away.mode: none` (spec
§3.6): a returning player picks up at the same in-game minute, and this
module's advance runs only under `mode: real`. When they come back -- `SessionStore.resume`, in a story
declaring `paths.social` -- the time they were gone passes as ONE
`clock.advance_time` (rule 2), measured from the wall stamp
`state.social["last_active_wall"]` (stamped by every mechanics action and by
the away advance itself):

    hours = min(elapsed_real_seconds / 3600 x social.away.rate, social.away.max_hours)

Fractional hours are kept (the clock takes floats). The advance is recorded
as `{kind: away, hours, real_seconds}` in the transcript and saved at once
(`saves.save_now`, Plan decision 5), and it re-stamps `last_active_wall`, so
a second resume of the same save adds only the minutes between, never the
absence twice. A wall clock that went backwards adds nothing.

`away_since` (the in-game hour the absence began) is kept in the slice until
the next mechanics action clears it: `lock_screen` counts what arrived after
it -- the resume frame's "While you were away: 5 messages from 3 people,
1 new match, 1 match expired".

**Why this does not break R-03** (docs/DESIGN.md): the advance is one
recorded input at a defined moment; a replay from the inputs reproduces it.
Within a session nothing moves on the wall clock.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from engine import social
from engine.game import clock
from engine.game.effects import apply_effect
from engine.game.state import GameState

logger = logging.getLogger(__name__)


def away_hours(state: GameState, now_wall: float) -> float:
    """The in-game hours an absence up to `now_wall` (seconds since the epoch) is worth (spec §15.2)."""
    cfg = social.setting("away", {"mode": "real", "rate": 1.0, "max_hours": 72})
    if str(cfg.get("mode", "real")) == "none":
        return 0.0
    last = float(state.social.get("last_active_wall") or 0.0)
    if last <= 0.0:
        return 0.0                                   # never stamped: no absence to measure
    elapsed = max(0.0, float(now_wall) - last)       # a clock that went backwards adds nothing
    return min(elapsed / 3600.0 * float(cfg.get("rate", 1.0)), float(cfg.get("max_hours", 72)))


def apply_on_resume(session: Any, *, wall: Optional[Callable[[], float]] = None) -> Optional[dict[str, Any]]:
    """
    One `advance_time` for the whole absence, recorded, stamped and saved
    (spec §15.2), under the session's turn lock (Plan decision 15). The
    record `{kind: away, hours, real_seconds}`, or None when no time passed
    (or the lock was held: a fresh session's lock is free, so refusing is the
    safe answer). `wall` is the wall clock (the harness passes its own; it
    defaults to `time.time`, read at the call).
    """
    from engine.social import saves

    if not session.lock.acquire(blocking=False):
        # It drops real time (local two tabs, CLAUDE.md finding 7): said at WARNING.
        logger.warning("[social] Away advance skipped: the turn lock is held (operation=apply_on_resume, id=%s)",
                       session.session_id)
        return None
    try:
        state = session.engine.state
        now = float((wall or time.time)())
        hours = away_hours(state, now)
        real = max(0.0, now - float(state.social.get("last_active_wall") or now))
        apply_effect(state, {"type": "social_settings", "field": "last_active_wall", "value": now})
        if hours <= 0.0:
            saves.mark_dirty(session, "away")        # the stamp alone: the timer saves it
            return None
        before = state.world_clock_hours
        try:
            clock.advance_time(state, hours)
        except Exception:
            # The stamp is written and the clock has moved: never left unsaved (final review M2).
            saves.mark_dirty(session, "away")
            raise
        apply_effect(state, {"type": "social_settings", "field": "away_since", "value": before})
        record = {"kind": "away", "hours": hours, "real_seconds": real}
        saves.save_now(session, entry=record)
        logger.info("[social] Away advance (operation=apply_on_resume, id=%s, hours=%.3f, real_seconds=%.0f)",
                    session.session_id, hours, real)
        return record
    finally:
        saves.release_turn(session)                  # never a bare release: end_after_turn too (Plan decision 31)


def away_since(state: GameState) -> Optional[float]:
    """The in-game hour the last absence began, until the next mechanics action; None when none."""
    value = state.social.get("away_since")
    return None if value is None else float(value)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def lock_screen(state: GameState, since_hours: float) -> dict[str, Any]:
    """
    What arrived after in-game hour `since_hours` (spec §15.3): `lines`, one
    per kind that arrived ("5 messages from 3 people", "1 new match", "1 match
    expired"), `text` (the sentence the lock screen shows, "" when nothing
    arrived) and `notifications` (the `notifications` section's rows after it,
    oldest first).
    """
    from engine.social import matching, messaging

    since = float(since_hours)
    people = state.social.get("people") or {}
    messages = 0
    senders: set[str] = set()
    new_matches = 0
    expired = 0
    for t in (state.social.get("threads") or {}).values():
        if not matching.listed(t):
            continue                                 # unmatched and blocked threads are not shown
        pid = str(t.get("pid") or "")
        # A thread a save emptied (its closed conversation in the archive, v0.23.0 T9 fix round 2) answers
        # with its stamp's last word: an expired match's line, say. Unread messages always stay in state.
        rows = t.get("messages") or [r for r in (messaging.last_shown(t),) if r]
        for m in rows:
            if float(m.get("at", -1.0)) <= since or not messaging.shown(m):
                continue
            if m.get("from") == pid:
                messages += 1
                senders.add(pid)
            elif m.get("kind") == "system" and list(m.get("bubbles") or [])[:1] == [matching.EXPIRED_LINE]:
                expired += 1
        matched_at = ((people.get(pid) or {}).get("apps") or {}).get(str(t.get("app") or ""), {}).get("matched_at")
        if matched_at is not None and float(matched_at) > since:
            new_matches += 1
    lines: list[str] = []
    if messages:
        lines.append(f"{_plural(messages, 'message', 'messages')} from {_plural(len(senders), 'person', 'people')}")
    if new_matches:
        lines.append(_plural(new_matches, "new match", "new matches"))
    if expired:
        lines.append(f"{_plural(expired, 'match', 'matches')} expired")
    notifications = [row for row in messaging.notification_rows(state) if float(row.get("at", -1.0)) > since]
    return {"lines": lines, "text": ("While you were away: " + ", ".join(lines)) if lines else "",
            "notifications": notifications}


def world_choices(state: GameState, *, prefix: str = "resume", legal: Any = None) -> list[dict[str, Any]]:
    """
    The world layer's choices for a frame no narrated turn wrote (v0.23.0 T22, spec §14.1): "Look around"
    (no intent: a narrated look) and every world verb the engine will honour now -- `do`, `go`, `scene`,
    `close`, and (T23A) core `travel`, the flat's room moves, labelled by the place's name -- as
    `intents.legal_intents` offers them, one choice per target, so a resumed run's world is not a dead end
    until the player picks the phone up and puts it down. Ids are `<prefix>_<action>_<target>`: `resume` for
    the resume frame, `world` for a phone action's row. Never raises: a fault costs the choices, not the resume.
    """
    try:
        from engine.game import intents
        from engine.game.locations import LOCATIONS

        out: list[dict[str, Any]] = [{"id": f"{prefix}_look", "text": intents.ENGINE_CHOICE_WORDS["look"]}]
        for verb in (intents.legal_intents(state) if legal is None else legal):
            if verb.action not in intents.SOCIAL_WORLD_ACTIONS and verb.action != "travel":
                continue
            for target, label in verb.options:
                if verb.action == "travel":
                    words = str((LOCATIONS.get(target) or {}).get("name") or target)
                else:
                    words = str(intents.player_label(state, verb.action, str(target)) or label or target)
                    if verb.action == "go":
                        words = f"Go to {words}"
                out.append({"id": f"{prefix}_{verb.action}_{target}", "text": words[:1].upper() + words[1:],
                            "intent": {"action": verb.action, "target": str(target)}})
        return out
    except Exception:  # noqa: BLE001 -- the choices are a convenience; the resume must land
        logger.exception("[social] No world choices for the resume frame (operation=resume)")
        return []


def resume_frame(state: GameState) -> dict[str, Any]:
    """
    The resume frame of a phone story (spec §15.3; `default_state.resume_opening`'s
    phone branch): no narration -- the phone is played by its actions -- the lock
    screen of what arrived while the player was away, and the world layer's legal
    choices (`world_choices`, v0.23.0 T22) so the world is not dead on arrival.
    """
    from engine.scenes.default_state import scene_image_url

    since = away_since(state)
    return {
        "narration": "",
        "choices": world_choices(state),
        "state": state.to_client_dict(),
        # The world layer's plate (core's ScenePlate reads it): without it a resumed run showed the wash.
        "scene_image": scene_image_url(state),
        "resumed": True,
        "lock_screen": lock_screen(state, state.world_clock_hours if since is None else since),
    }


__all__ = ["apply_on_resume", "away_hours", "away_since", "lock_screen", "resume_frame", "world_choices"]

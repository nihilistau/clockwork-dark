"""
The `phone` block of the payload (v0.22.0 spec §17.3). Sections are
registered by the module that owns them (Plan decision 12). Hidden values
(warmth, interest, trust, mood, ghosted, arc, rev) never leave the server:
tests/test_ui_contract.py's key scan covers this block and both pushes.
"""

from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Optional

from engine import social
from engine.game.state import GameState

logger = logging.getLogger(__name__)

SectionFn = Callable[[GameState, Any], Any]
_SECTIONS: dict[str, SectionFn] = {}

#: Keys whose contents may move while in-game time passes with the player away
#: (pre-flight F14): T16's 72-hour test allows exactly these to change. A
#: section joins by registering with time_varying=True.
TIME_VARYING_SECTIONS: set[str] = {"now", "apps"}

#: (session, receipt) for the payload being built by run_mechanics (Plan
#: decision 32): read by phone_block when it is called with neither.
_BUILDING: ContextVar[Optional[tuple[Any, Optional[dict[str, Any]]]]] = ContextVar("phone_building", default=None)


def section(name: str, *, time_varying: bool = False) -> Callable[[SectionFn], SectionFn]:
    def decorator(fn: SectionFn) -> SectionFn:
        _SECTIONS[name] = fn
        if time_varying:
            TIME_VARYING_SECTIONS.add(name)
        return fn
    return decorator


@contextlib.contextmanager
def building(session: Any, receipt: Optional[dict[str, Any]] = None) -> Iterator[None]:
    """Build the payload's phone block with this session and receipt (to_client_dict calls phone_block(state))."""
    token = _BUILDING.set((session, receipt))
    try:
        yield
    finally:
        _BUILDING.reset(token)


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def now_block(state: GameState) -> dict[str, Any]:
    total = state.world_clock_hours
    minutes = int(round((total % 1.0) * 60)) % 60
    return {"day": state.world_day, "hour": state.world_hour, "minute": minutes,
            "weekday": WEEKDAYS[(state.world_day - 1) % 7]}


def phone_block(state: GameState, session: Any = None, *, receipt: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from engine.config import hosting_enabled

    if session is None and receipt is None:
        context = _BUILDING.get()
        if context is not None:
            session, receipt = context

    from engine.social import messaging

    apps = social.data("apps").get("apps") or {}
    badges = messaging.badges(state)
    block: dict[str, Any] = {
        "now": now_block(state),
        # Whether the client may offer "Let time pass" (spec §15.1): local mode only. The preference
        # itself is the client's (T29: kept in the browser); hosted mode never offers it, since each
        # wait can create due messages and so a voicing admission (§22 NOT WIRED: persisting it).
        "auto_wait": not hosting_enabled(),
        # The player's own switches the Settings app shows (T29): Natter's read receipts, and the
        # cap the engine puts on a bio (`edit_profile`'s text cap, review M10).
        "settings": {"receipts": bool((state.social.get("settings") or {}).get("receipts", True)),
                     "bio_max": int(social.setting("max_text_chars", 600))},
        # `capabilities`: what a thread on the app can carry (apps.yaml), so the
        # compose bar offers only those attachments (spec §18.2; the engine still refuses the rest).
        "apps": [{"id": k, "label": str(v.get("label", k.title())), "kind": str(v.get("kind", "")),
                  "badge": int(badges.get(k, 0)),
                  "capabilities": [str(c) for c in v.get("capabilities") or ()]}
                 for k, v in apps.items()],
        "player": _player(state),
        "refusal": _refusal(receipt),
    }
    for name, fn in _SECTIONS.items():
        try:
            block[name] = fn(state, session)
        except Exception:  # noqa: BLE001 -- one section's fault costs that section
            logger.exception("[social] Payload section failed (operation=phone_block, section=%s)", name)
            block[name] = None
    return block


def thread_row(state: GameState, thread_id: str, session: Any = None) -> Optional[dict[str, Any]]:
    """
    One row of the `threads` section (spec §17.3), the same the section
    builds: T14's `phone_message` push carries it so the thread list stays
    current between actions. None for no such thread.
    """
    from engine.social import messaging

    return messaging.thread_row(state, thread_id, session)


def _player(state: GameState) -> dict[str, Any]:
    player = state.social.get("player") or {}
    keep = ("name", "sex", "age", "looking_for", "hobbies", "attributes", "personality",
            "discovery", "photos", "bios")
    out = {k: player[k] for k in keep if k in player}
    # What the compose bar may attach (spec §13.7): the camera roll (their
    # profile photos, `photo_set` labels) and the `player_subjects` rows.
    # Each fenced like a section (review M2): a fault costs that field ([]).
    out["camera_roll"] = _fenced("camera_roll", _camera_roll, state)
    out["subjects"] = _fenced("subjects", _send_subjects, state)
    return out


def _fenced(name: str, fn: Callable[[GameState], list[dict[str, Any]]], state: GameState) -> list[dict[str, Any]]:
    try:
        return fn(state)
    except Exception:  # noqa: BLE001 -- one field's fault costs that field
        logger.exception("[social] Payload field failed (operation=phone_block, field=player.%s)", name)
        return []


def _camera_roll(state: GameState) -> list[dict[str, Any]]:
    from engine.social import media, population

    labels = {str(r.get("id")): str(r.get("label") or r.get("id")) for r in population.table("photo_set")
              if isinstance(r, dict)}
    return [{"id": pid, "label": labels.get(pid, pid.replace("_", " "))} for pid in media.player_photos(state)]


def _send_subjects(state: GameState) -> list[dict[str, Any]]:
    from engine.social import media

    return [{"id": str(r["id"]), "kinds": [str(k) for k in r.get("kinds") or ()], "label": str(r.get("label") or r["id"])}
            for r in media.player_subjects() if r.get("id")]


def _refusal(receipt: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not receipt or not receipt.get("refused"):
        return None
    intent = receipt.get("intent") or {}
    return {"action": intent.get("action", ""), "target": intent.get("target", ""),
            "reason": str((receipt.get("result") or {}).get("error") or "That didn't work.")}

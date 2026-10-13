"""
The phone's mechanics action (v0.22.0 spec §16.1): no model, no admission,
the turn lock held briefly by run_guarded. Steps, each added by the task
that builds it (no stub): 1 drain the inbox (T14); 2 execute; 3 create media
jobs (T19, `media.submit_due`); 4 mark dirty and stamp, or save at once (T10); 5 emit.

The three actions that exist from T6 live here too: `wait` (§15.1),
`edit_profile` and `set_receipts`. Each writes state only through
`clock.advance_time` (rule 2) and `effects.apply_effect` (rule 3).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from engine import social
from engine.game import clock
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.social.kinds import recorded
from engine.game.intents import IntentVerb
from engine.game.state import GameState
from engine.social.intents import ArgSpec, phone_verb

logger = logging.getLogger(__name__)

WAIT_UNTIL = ("next", "15m", "1h", "morning")
#: Event kinds that notify the player, which `wait {until: next}` stops at (§15.1).
NOTIFYING = frozenset({"reply", "initiate", "double_text", "see_like", "likes_you", "game_move", "meet_start"})


def played_on_the_phone() -> str:
    """
    What `player_choice` is answered with in a phone story (spec §7.2), built
    from the ACTIVE manifest's title so this engine module names no story
    (Plan decision 26). READ RECEIPTS: "Read Receipts is played on the phone."
    """
    from engine.games import registry

    manifest = registry.peek()
    title = manifest.title if manifest is not None else "This story"
    return f"{title} is played on the phone."


def run_mechanics(session: Any, action: str, intent: Any = None, *, authored: Any = None,
                  emit_callback: Optional[Callable[[str, dict[str, Any]], None]] = None) -> dict[str, Any]:
    """
    One phone action, in `run_turn`'s calling shape (Plan decision 7), so
    `run_guarded` calls whichever runner it was given the same way. `action`
    is the verb's name; `intent` the normalised `phone_action` body. The
    player's label is read here, under the turn lock (`intents.label_of`),
    before the action runs, and rides on the receipt as `label`. The answer
    is a turn payload with no narration and no choices: the receipt (or
    refusal) and the state, its `phone` block built once.
    """
    from engine.agents.tool_dispatcher import execute_phone_intent
    from engine.social import intents as phone
    from engine.social import payload

    state = session.engine.state
    # 1. Drain the inbox, each item re-validated (§16.4): replies a voicing
    # pass could not commit, parked for the next holder of the turn lock.
    from engine.social import voicer

    voicer.drain_inbox(session)
    parsed = phone.normalise_phone(intent)
    label = phone.label_of(state, parsed) if parsed is not None else str(action or "")
    # 2. Execute (a receipt or a refusal; costs and waits through advance_time).
    receipt = execute_phone_intent(intent, session.engine)
    receipt["label"] = label
    # 3. Create media jobs for due messages decided to carry media, and
    # portraits by policy (§13.4): each to the job worker, which holds no
    # session lock; one past the day's cap is a procedural tile at once.
    from engine.social import media

    try:
        media.submit_due(session)
    except Exception as exc:  # noqa: BLE001 -- the action is done; its rows stay `requested` for the next one
        logger.warning("[social] Media jobs not submitted (operation=run_mechanics, id=%s): %s",
                       session.session_id, exc)
    # 4. Mark dirty and stamp; save at once after a match, a stage change, an
    # ending or an away advance (spec §17.2); otherwise the dirty timer saves
    # within social.autosave_seconds.
    from engine.social import saves

    applied = _effects_of(receipt)
    apply_effect(state, {"type": "social_settings", "field": "last_active_wall", "value": time.time()})
    if state.social.get("away_since") is not None:
        # The lock screen of the last absence is seen once acted past (spec §15.3).
        apply_effect(state, {"type": "social_settings", "field": "away_since", "value": None})
    opening = getattr(session, "last_turn", None)
    if isinstance(opening, dict) and (opening.get("lock_screen") or {}).get("text"):
        # ...and so is the saved opening's copy of it: a page joining later
        # (a reload) is sent `last_turn`, never that absence again (final review M5).
        session.last_turn = {**opening, "lock_screen": {"lines": [], "text": "", "notifications": []}}
    reasons = {str(r.get("save_reason") or "") for r in applied} & saves.IMMEDIATE
    if reasons:
        saves.save_now(session, entry={"phone": (parsed or {}).get("action", "") or str(action or ""),
                                       "day": state.world_day, "hour": state.world_hour})
    else:
        saves.mark_dirty(session, "action")
    # The phone block is built ONCE, inside to_client_dict, with this session's
    # typing marks and this receipt's refusal (Plan decision 32).
    with payload.building(session, receipt):
        client_state = state.to_client_dict()
    turn_payload: dict[str, Any] = {
        "narration": "",
        "choices": [],
        "receipts": [receipt],
        "state": client_state,
    }
    # 5. Emit.
    if emit_callback is not None:
        emit_callback("turn_update", turn_payload)
    return turn_payload


def _effects_of(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The applied effects' results the phone skill returned under `effects`
    (every social effect of the action, its events' included), TAKEN OFF the
    receipt: they carry hidden values (regard, interest) and the receipt goes
    to the client, so they never leave the server (spec §17.3).
    """
    result = receipt.get("result")
    if not isinstance(result, dict):
        return []
    rows = result.pop("effects", None)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _next_notifying_at(state: GameState) -> Optional[float]:
    for event in state.social.get("queue", []):
        if event["kind"] in NOTIFYING and not _stale_lapse(state, event):
            return float(event["at"])
    return None


def _stale_lapse(state: GameState, event: dict[str, Any]) -> bool:
    """
    A `meet_start` that is a request's lapse (`request_id`) whose request is
    answered or can no longer be met: its handler will write nothing the
    player waits for, so `wait {until: next}` runs past it (final review M1).
    Read here, at the one reader, rather than cancelled at every answer: it
    holds for every way a request closes (an answer, the morning's lapse, a
    person who left) and for the events already queued in a save.
    """
    if event["kind"] != "meet_start" or not event.get("request_id"):
        return False
    from engine.social import meets

    request = (state.social.get("requests") or {}).get(str(event["request_id"]))
    return (request is None or request.get("status") not in ("pending", "later")
            or not meets.still_open(state, request))


def wait(state: GameState, args: dict[str, Any]) -> dict[str, Any]:
    """Let in-game time pass (§15.1), through `clock.advance_time` only."""
    until = str(args.get("until") or "15m")
    now = state.world_clock_hours
    cap = float(social.setting("wait_next_cap_hours", 8))
    if until == "15m":
        hours = 0.25
    elif until == "1h":
        hours = 1.0
    elif until == "morning":
        hour = now % 24
        hours = (8 - hour) % 24 or 24.0
    else:
        due = _next_notifying_at(state)
        hours = cap if due is None else min(cap, max(0.0, due - now))
    clock.advance_time(state, hours)
    return {"ok": True, "waited_hours": hours}


@phone_verb("wait", payload={"until": ArgSpec("enum", WAIT_UNTIL, required=True)}, skill="social_wait",
            label=lambda s, i: "Put the phone down")
def _wait_verb(state: GameState) -> Optional[IntentVerb]:
    return IntentVerb("wait", extra={"until": WAIT_UNTIL})


def cost_hours(state: GameState, app: str, what: str) -> float:
    """Minutes an action costs on an app (apps.yaml cost_minutes), as hours."""
    apps = social.data("apps").get("apps") or {}
    return float((apps.get(app) or {}).get("cost_minutes", {}).get(what, 0.0)) / 60.0


def edit_profile(state: GameState, app: str, args: dict[str, Any], text: str) -> dict[str, Any]:
    """A dating app's bio, written; then the edit's time (apps.yaml `settings.cost_minutes.edit`)."""
    result = apply_effect(state, {"type": "social_settings", "field": "bio", "app": app, "value": text})
    if result.get("ok"):
        clock.advance_time(state, cost_hours(state, "settings", "edit"))
    return result


def set_receipts(state: GameState, app: str, args: dict[str, Any]) -> dict[str, Any]:
    return apply_effect(state, {"type": "social_settings", "field": "receipts", "value": args.get("to") == "on"})


def _dating_apps() -> tuple[tuple[str, str], ...]:
    apps = social.data("apps").get("apps") or {}
    return tuple((k, str(v.get("label", k))) for k, v in apps.items() if v.get("kind") == "dating")


@phone_verb("edit_profile", payload={"field": ArgSpec("enum", ("bio",), required=True)},
            skill="social_edit_profile", takes_text=True, text_cap="social.max_text_chars",
            label=lambda s, i: "Edit your profile")
def _edit_profile_verb(state: GameState) -> Optional[IntentVerb]:
    options = _dating_apps()
    return IntentVerb("edit_profile", options=options) if options else None


@phone_verb("set_receipts", payload={"to": ArgSpec("enum", ("on", "off"), required=True)},
            skill="social_set_receipts", label=lambda s, i: "Read receipts")
def _set_receipts_verb(state: GameState) -> Optional[IntentVerb]:
    return IntentVerb("set_receipts", options=(("natter", "Natter"),))


@effect_kind("social_settings")
@recorded
def _e_settings(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """Engine-only: the player's own settings and profile fields (bio, read receipts)."""
    field = effect.get("field")
    if field == "bio":
        state.social["player"].setdefault("bios", {})[str(effect["app"])] = str(effect["value"])
    elif field == "receipts":
        state.social["settings"]["receipts"] = bool(effect["value"])
    elif field == "last_active_wall":
        # A WALL stamp (seconds since the epoch), stamped by every mechanics
        # action (spec §16.1 step 4) and read by the away advance (T16); never
        # part of a replay's comparison.
        state.social["last_active_wall"] = float(effect["value"])
    elif field == "away_since":
        # The in-game hour an absence began (the away advance, T16), read by
        # the resume frame's lock screen; None clears it (the next mechanics
        # action does, spec §15.3).
        if effect.get("value") is None:
            state.social.pop("away_since", None)
        else:
            state.social["away_since"] = float(effect["value"])
            return {"type": "social_settings", "ok": True, "text": "away_since updated", "save_reason": "away"}
    else:
        return {"type": "social_settings", "ok": False, "text": f"unknown setting {field!r}"}
    return {"type": "social_settings", "ok": True, "text": f"{field} updated"}

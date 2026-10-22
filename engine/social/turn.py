"""
The phone's mechanics action (v0.22.0 spec §16.1): no model, no admission,
the turn lock held briefly by run_guarded. Steps, each added by the task
that builds it (no stub): 1 drain the inbox (T14); 2 execute; 3 create media
jobs (T19, `media.submit_due`); 4 mark dirty and stamp, or save at once (T10); 5 emit.

The three actions that exist from T6 live here too: `wait` (§15.1),
`edit_profile` and `set_receipts`; and v0.23.0 T11's two that hand over to
the world (spec §8.2, §8.5): `put_down` and the Places app's `go`. Each
writes state only through `clock.advance_time` (rule 2) and
`effects.apply_effect` (rule 3). Every action picks the phone up first
(`world.pick_up`, right after the inbox is drained).
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

#: `wait`'s fixed targets (v0.23.0 spec §3.6): `15m` went with the auto-wait it existed for. Each open
#: promise adds its own, `promise:<id>` (`PROMISE_TARGET` + its id), offered through `IntentVerb.extra`.
WAIT_UNTIL: tuple[str, ...] = ("next", "1h", "evening", "morning")
#: The prefix of a promise's `wait` target (v0.23.0 T4).
PROMISE_TARGET = "promise:"
#: Event kinds that notify the player, which `wait {until: next}` stops at (§15.1); a person's promised
#: message (`promise_due`, v0.23.0 T4) among them.
NOTIFYING = frozenset({"reply", "initiate", "double_text", "see_like", "likes_you", "game_move",
                       "promise_due"})


_FINGERPRINT_ACTIONS = frozenset({"do", "go", "scene", "close", "travel"})


def world_fingerprint(state: GameState, legal: Any = None) -> tuple:
    """What the world row depends on (A4 W1): the place, the scene, work, the clock, and the legal world targets."""
    from engine import social
    from engine.game import intents
    from engine.social import plans, scene

    scn = scene.current(state) if social.scene_open(state) else {}
    verbs = intents.legal_intents(state) if legal is None else legal
    targets = tuple(sorted((v.action, t) for v in verbs
                           if v.action in _FINGERPRINT_ACTIONS for t in v.targets))
    # The open plans and whether each one's person has arrived (A4 W2-W4, T23C): a plan made, kept or arrived
    # changes what the row may offer ("Wait for {name}", a plan's place first), so it rebuilds the row.
    kept = tuple(sorted((str(r["id"]), str(r.get("when") or ""), plans.has_arrived(r)) for r in plans.open_for(state)))
    return (state.location_id, str(scn.get("pid") or ""), str(scn.get("kind") or ""),
            bool(state.social.get("at_work")), round(state.world_clock_hours, 4), targets, kept)


def _fingerprint_or_none(state: GameState, legal: Any = None) -> Optional[tuple]:
    """`world_fingerprint`, or None on a fault: the row is a convenience, never a reason to fail the action."""
    try:
        return world_fingerprint(state, legal)
    except Exception:  # noqa: BLE001
        logger.exception("[social] No world fingerprint (operation=run_mechanics)")
        return None


def run_mechanics(session: Any, action: str, intent: Any = None, *, authored: Any = None,
                  emit_callback: Optional[Callable[[str, dict[str, Any]], None]] = None) -> dict[str, Any]:
    """
    One phone action, in `run_turn`'s calling shape (Plan decision 7), so
    `run_guarded` calls whichever runner it was given the same way. `action`
    is the verb's name; `intent` the normalised `phone_action` body. The
    player's label is read here, under the turn lock (`intents.label_of`),
    before the action runs, and rides on the receipt as `label`. The answer
    is a turn payload with no narration and the world layer's choices (`away.world_choices`): the receipt (or
    refusal) and the state, its `phone` block built once.
    """
    from engine.social import presence

    with presence.one_pass():               # the chance tier read once for the whole action (A4 W9, I7)
        return _run_mechanics(session, action, intent, authored=authored, emit_callback=emit_callback)


def _run_mechanics(session: Any, action: str, intent: Any = None, *, authored: Any = None,
                   emit_callback: Optional[Callable[[str, dict[str, Any]], None]] = None) -> dict[str, Any]:
    """`run_mechanics`' body, inside its presence pass."""
    from engine.agents.tool_dispatcher import execute_phone_intent
    from engine.social import intents as phone
    from engine.social import payload

    state = session.engine.state
    # 1. Drain the inbox, each item re-validated (§16.4): replies a voicing
    # pass could not commit, parked for the next holder of the turn lock.
    from engine.social import voicer

    voicer.drain_inbox(session)
    # Any phone action picks the phone up (v0.23.0 spec §8.2, MINOR 6): there is no refused phone verb.
    # The `put_down` verb then sets it false within this same action.
    from engine.social import world

    world.pick_up(state)
    before = _fingerprint_or_none(state)
    parsed = phone.normalise_phone(intent)
    label = phone.label_of(state, parsed) if parsed is not None else str(action or "")
    # 2. Execute (a receipt or a refusal; costs and waits through advance_time). The due messages a
    # voicing pass has marked are visible to the action (Plan decision 9): a send never re-decides
    # one a pass is already wording (convo.on_player_send). Read from a copy (lesson 10).
    from engine.social import convo

    with convo.marking(tuple(session.voicing)):
        receipt = execute_phone_intent(intent, session.engine)
    receipt["label"] = label
    # Presence re-read now the action is done (A4 W5, W9): whoever was with the player and is not now -- a chance
    # person whose block moved them on, say -- has their held texts land at once; the pass after the action
    # (`routes._request_pass`) voices them.
    from engine.social import messaging

    messaging.release_held(state)
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
    # The world layer's choices (v0.23.0 T23, found by the layout probe): a phone action's answer used to carry
    # none, so the client -- which keeps a turn's choices -- lost the world's the moment the phone was used.
    from engine import social
    from engine.social import away, scene

    # The row (A4 W1): the narrator's own while nothing in the world changed, else rebuilt from what is legal
    # now -- and written into `last_turn`, so a press of it is never stale and a refresh restores it.
    from engine.game import intents as game_intents

    try:
        legal = game_intents.legal_intents(state)       # once: the fingerprint and a rebuilt row share it
    except Exception:  # noqa: BLE001
        logger.exception("[social] No legal intents for the world row (operation=run_mechanics)")
        legal = None
    after = _fingerprint_or_none(state, legal) if legal is not None else None
    last = getattr(session, "last_turn", None) or {}
    keep = before is not None and after is not None and after == before
    row = list(last.get("choices") or []) if keep else away.world_choices(state, prefix="world", legal=legal)
    # The world layer's plate for where the player is now and the hour it is (a Places-app `go`, a `wait` into
    # another daypart), in the answer and in `last_turn`, so neither a phone action nor a refresh after it keeps
    # the last place's plate.
    from engine.scenes.default_state import scene_image_url

    plate = scene_image_url(state)
    session.last_turn = {**last, "choices": row, "scene_image": plate}
    turn_payload: dict[str, Any] = {
        "narration": "",
        "choices": row,
        "receipts": [receipt],
        "state": client_state,
        "scene_image": plate,
    }
    if after and social.scene_open(state) and not (before or ((),) * 2)[1] and after[1]:   # a scene opened by this phone action
        turn_payload["narration"] = scene.receipt_lines(state).splitlines()[0]
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
        if ((event["kind"] in NOTIFYING or _awaited_read(state, event) or _arrival_here(state, event))
                and not _stale_promise(state, event)):
            return float(event["at"])
    return None


def _arrival_here(state: GameState, event: dict[str, Any]) -> bool:
    """A `plan_arrive` at the player's place (A4 W4): no text comes (they will see them), so `wait next` stops
    at the arrival itself."""
    if event["kind"] != "plan_arrive":
        return False
    from engine.social import plans   # lazily: plans imports this module's package

    row = plans.get(state, str(event.get("plan_id") or ""))
    return bool(row) and row.get("status") == "open" and plans.player_at(state, row)


def _awaited_read(state: GameState, event: dict[str, Any]) -> bool:
    """A `read` of a thread whose last shown word is the player's (v0.23.0 T9 fix round 1): it decides the
    reply at its own minute (spec §4.3, `convo._on_read`), so `wait next` stops there, never past the reply.
    Only a read the player can SEE stops it (fix round 3): a receipt on a thread they can see (listed, its
    app keeping receipts, their own receipts on); a read that shows nothing is run past."""
    if event["kind"] != "read":
        return False
    from engine.social import matching, messaging

    thread = messaging.thread(state, str(event.get("thread_id") or ""))
    last = messaging.last_shown(thread) if thread else None
    return (bool(last) and last.get("from") == "player" and matching.listed(thread)
            and messaging._receipts_shown(state, thread))


def _stale_promise(state: GameState, event: dict[str, Any]) -> bool:
    """A `promise_due` whose promise is no longer open writes nothing: `wait next` runs past it (review M1)."""
    if event["kind"] != "promise_due":
        return False
    row = ((state.social or {}).get("promises") or {}).get(str(event.get("promise_id") or ""))
    return not row or row.get("status") != "open"


def promise_arrival(state: GameState, promise_id: str) -> Optional[float]:
    """Where `wait {until: promise:<id>}` lands (v0.23.0 T4): a person's promise at its `promise_due`
    (their message due on arrival), a player's at its window's opening. None when it is not open, or
    already here. Reads only."""
    row = ((state.social or {}).get("promises") or {}).get(promise_id)
    if not row or row.get("status") != "open":
        return None
    at = float(row["opens_at"])
    if row.get("by") == "person":
        due = [float(e["at"]) for e in state.social.get("queue") or []
               if e["kind"] == "promise_due" and e.get("promise_id") == promise_id]
        at = min(due) if due else at
    return at if at > state.world_clock_hours else None


def _promise_targets(state: GameState) -> tuple[str, ...]:
    """Each open promise still ahead, soonest first, as a `wait` target."""
    rows = sorted(((state.social or {}).get("promises") or {}).values(),
                  key=lambda r: (float(r.get("opens_at", 0.0)), str(r.get("id"))))
    return tuple(f"{PROMISE_TARGET}{r['id']}" for r in rows if promise_arrival(state, str(r["id"])) is not None)


def wait(state: GameState, args: dict[str, Any]) -> dict[str, Any]:
    """Let in-game time pass (v0.23.0 §3.6) through `clock.advance_time` only; the jump is the player's choice.
    `next`: until someone writes or a promise falls due (capped); `1h`; `evening` and `morning`:
    conversation.yaml `clock:`; `promise:<id>`: until that promise (`promise_arrival`)."""
    until = str(args.get("until") or "next")
    now = state.world_clock_hours
    clock_rows = social.data("conversation").get("clock") or {}
    if until.startswith(PROMISE_TARGET):
        arrival = promise_arrival(state, until[len(PROMISE_TARGET):])
        if arrival is None:
            return {"ok": False, "error": "That promise isn't still ahead."}
        hours = arrival - now
    elif until == "1h":
        hours = 1.0
    elif until in ("evening", "morning"):
        target = float(clock_rows.get(until, 18 if until == "evening" else 7))
        hours = (target - now % 24) % 24 or 24.0
    else:
        due = _next_notifying_at(state)
        cap = float(social.setting("wait_next_cap_hours", 8))
        hours = cap if due is None else min(cap, max(0.0, due - now))
    clock.advance_time(state, hours)
    out: dict[str, Any] = {"ok": True, "waited_hours": hours}
    from engine.social import plans   # lazily: plans imports this module's package

    met = plans.meet_if_here(state)    # the clock stopped (fix round 1, I1); the phone in hand keeps it quiet
    if met.get("scene"):
        out["met"] = met.get("met")
    return out


def _wait_label(state: GameState, intent: dict[str, Any]) -> str:
    """ "Wait"; for a person's promise "Wait for <name>" (the world's "Until <name> messages"); for the
    player's own, "Wait until <window> (you said you'd message <name>)" (review M7)."""
    until = str((intent.get("args") or {}).get("until") or "")
    rows = (state.social or {}).get("promises") or {}
    row = rows.get(until[len(PROMISE_TARGET):]) if until.startswith(PROMISE_TARGET) else None
    if not row:
        return "Wait"
    from engine.social import matching, promises

    name = matching._name(state, str(row["pid"]))
    if row.get("by") == "player":
        return f"Wait until {promises.window_words(row)} (you said you'd message {name})"
    return f"Wait for {name}"


@phone_verb("wait", payload={"until": ArgSpec("enum", WAIT_UNTIL, required=True)}, skill="social_wait",
            label=_wait_label)
def _wait_verb(state: GameState) -> Optional[IntentVerb]:
    return IntentVerb("wait", extra={"until": WAIT_UNTIL + _promise_targets(state)})


#: What a message costs is conversation.yaml's (v0.23.0 spec §3.3), the same on every app.
MESSAGE_COSTS: tuple[str, ...] = ("text", "voice", "photo", "video")


def cost_hours(state: GameState, app: str, what: str) -> float:
    """Minutes an action costs, as hours: a message's from conversation.yaml `costs:` (§3.3), any other
    verb's (a swipe, a like, an edit, a game move) from its app's apps.yaml `cost_minutes`."""
    if what in MESSAGE_COSTS:
        return float((social.data("conversation").get("costs") or {}).get(what, 0.0)) / 60.0
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


def set_wake(state: GameState, args: dict[str, Any]) -> dict[str, Any]:
    """"Wake me for messages" (v0.23.0 spec §8.4, T22's Settings switch): on or off, read by a sleep."""
    return apply_effect(state, {"type": "social_settings", "field": "wake_for_messages", "value": args.get("to") == "on"})


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


@phone_verb("set_wake", payload={"to": ArgSpec("enum", ("on", "off"), required=True)},
            skill="social_set_wake", label=lambda s, i: "Wake me for messages")
def _set_wake_verb(state: GameState) -> Optional[IntentVerb]:
    return IntentVerb("set_wake")


@phone_verb("put_down", payload={}, skill="social_put_down", label=lambda s, i: "Put the phone down")
def _put_down_verb(state: GameState) -> Optional[IntentVerb]:
    """Always legal (v0.23.0 spec §8.2): the action that runs it has just picked the phone up."""
    return IntentVerb("put_down")


def _places_label(state: GameState, intent: dict[str, Any]) -> str:
    from engine.social import places

    target = str(intent.get("target") or "")
    return f"Go to {places.label(target)}" if target else "Go"


def _places_why_not(state: GameState) -> str:
    if (state.social or {}).get("at_work"):
        return "You're at work."
    return "Nowhere to go from here right now."


@phone_verb("go", payload={}, skill="social_places_go", label=_places_label, why_not=_places_why_not)
def _places_go_verb(state: GameState) -> Optional[IntentVerb]:
    """The Places app (v0.23.0 spec §8.5): every venue, no cap (`world.places_targets`, which the payload's
    `places` section lists too). Choosing one puts the phone down and goes."""
    from engine.social import world

    options = tuple(world.places_targets(state))
    return IntentVerb("go", options=options) if options else None


@effect_kind("social_settings")
@recorded
def _e_settings(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """Engine-only: the player's own settings and profile fields (bio, read receipts), and the world's
    flags (v0.23.0 T11): `phone_up`, `at_work`, `work_until`, `buzz_from`, `resume`, `wake_for_messages`."""
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
    elif field in ("phone_up", "at_work"):
        # The phone in the hand (spec §8.2) and the player at work (§8.4), v0.23.0 T11.
        state.social[field] = bool(effect["value"])
    elif field == "work_until":
        # The end of the shift the player went to (§8.4); None when they are not at work.
        if effect.get("value") is None:
            state.social.pop("work_until", None)
        else:
            state.social["work_until"] = float(effect["value"])
    elif field == "buzz_from":
        # The notification count when the phone was last put down: the buzz counts from it (§8.2).
        state.social["buzz_from"] = int(effect["value"])
    elif field == "resume":
        # An activity a buzz cut short and where it was to end, {activity, until}: "Carry on" resumes to
        # that end (§8.4); None forgets it.
        if effect.get("value") is None:
            state.social.pop("resume", None)
        else:
            value = dict(effect["value"])
            state.social["resume"] = {"activity": str(value["activity"]), "until": float(value["until"])}
    elif field == "wake_for_messages":
        # "Wake me for messages" (§8.4): off by default, read by a sleep.
        state.social.setdefault("settings", {})["wake_for_messages"] = bool(effect["value"])
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

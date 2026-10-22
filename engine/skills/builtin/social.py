"""
The phone's skills (v0.22.0 spec §7.3) and, since v0.23.0 T11, the world's
(`social_do`, `social_go`; T13 `social_scene`, `social_close`: category WORLD). System-only (Plan decision 4): no
storyteller or MCP agent can call them; the phone catalogue
(tool_dispatcher.execute_phone_intent) calls the phone's, and a narrated
turn's chosen option (tool_dispatcher.execute_intent, which resolves
`intents.SOCIAL_WORLD_ACTIONS` as the system) the world's. Each is a thin
shell over the owning engine.social module, imported lazily so a story
without paths.social never loads it (spec §2.1).
"""

from __future__ import annotations

import functools
import json
import logging
from typing import Any, Callable, Optional

from engine.game.engine import get_active_engine
from engine.skills.registry import AGENT_SYSTEM, TRIGGER_SYSTEM, skill

logger = logging.getLogger(__name__)

PACK = "social"
CATEGORY = "PHONE"


def _phone_skill(description: str) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """
    Register a system-only phone skill. A fault inside it is logged here with
    its traceback (the registry turns it into an ``error`` result, which
    execute_phone_intent answers with a refusal), then re-raised.
    """
    register = skill(pack=PACK, description=description, category=CATEGORY,
                     trigger=TRIGGER_SYSTEM, agents=[AGENT_SYSTEM])

    def decorator(func: Callable[..., str]) -> Callable[..., str]:
        @functools.wraps(func)
        def logged(*args: Any, **kwargs: Any) -> str:
            try:
                return func(*args, **kwargs)
            except Exception:
                logger.exception("[social] A phone skill raised (operation=%s)", func.__name__)
                raise

        return register(logged)

    return decorator


def _answer(run: Callable[[], dict[str, Any]]) -> str:
    """
    The owning module's result, with ``effects``: the result of every social
    effect it applied, those its events applied while time passed included
    (v0.22.0 T10). The mechanics action reads its save triggers off them and
    strips them before the payload leaves (hidden values never do).
    """
    from engine.social.kinds import collecting

    with collecting() as applied:
        result = dict(run())   # a copy: the result may itself be one of the applied
    result["effects"] = applied
    return json.dumps(result, default=str)


@_phone_skill("Let in-game time pass on the phone.")
def social_wait(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import turn

    return _answer(lambda: turn.wait(get_active_engine().state, args or {}))


@_phone_skill("Say talk later in a conversation going now, with a promise: the player's to message them in a "
              "window, or theirs to message the player (the engine resolves the window and keeps it).")
def social_sign_off(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import promises

    args = args or {}
    return _answer(lambda: promises.sign_off(get_active_engine().state, target, str(args.get("who") or ""),
                                             str(args.get("window") or ""), text))


@_phone_skill("Edit one of the player's profile fields on an app.")
def social_edit_profile(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import turn

    return _answer(lambda: turn.edit_profile(get_active_engine().state, target, args or {}, text))


@_phone_skill("Turn the player's read receipts on or off.")
def social_set_receipts(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import turn

    return _answer(lambda: turn.set_receipts(get_active_engine().state, target, args or {}))


@_phone_skill("Turn \"Wake me for messages\" on or off: whether a message can wake the player from a sleep.")
def social_set_wake(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import turn

    return _answer(lambda: turn.set_wake(get_active_engine().state, args or {}))


def _deck(action: str, target: str, args: Optional[dict]) -> str:
    from engine.social import matching

    return _answer(lambda: matching.act(get_active_engine().state, action, target, args or {}))


@_phone_skill("Swipe on the top card of a swipe deck: like, pass or super like.")
def social_swipe(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    return _deck("swipe", target, args)


@_phone_skill("Like a profile shown on a browse deck, on a photo or a prompt, with an optional comment.")
def social_like(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    return _deck("like", target, args)


@_phone_skill("Like back someone in Likes you: a match at once.")
def social_like_back(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    return _deck("like_back", target, args)


@_phone_skill("Pass on a profile shown on a browse deck, or on someone in Likes you.")
def social_pass(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    return _deck("pass", target, args)


@_phone_skill("Unmatch a match: the thread leaves the app.")
def social_unmatch(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    return _deck("unmatch", target, args)


@_phone_skill("Block someone the player has a thread with: every thread with them closes.")
def social_block(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    return _deck("block", target, args)


@_phone_skill("Send a message in a thread: text, a photo or video (a camera-roll photo or a subject) "
              "with an optional caption, or a voice note by its transcript (`audio_transcript`; its audio "
              "is not kept), where the app allows it.")
def social_send(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import messaging

    args = args or {}
    return _answer(lambda: messaging.send(get_active_engine().state, target, str(args.get("kind") or "text"), text,
                                          photo_id=str(args.get("photo_id") or ""),
                                          subject=str(args.get("subject") or ""),
                                          transcript=str(args.get("audio_transcript") or "")))


@_phone_skill("Open a thread: the player reads it, and it is voiced first.")
def social_open_thread(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import messaging

    return _answer(lambda: messaging.open_thread(get_active_engine().state, target))


@_phone_skill("Ask the person in a thread for something: their number, to be exclusive, a plan to meet (a kind, "
              "a venue and now, tonight or soon; the engine picks what is left out), or a photo, a voice note or "
              "a video (the person decides).")
def social_ask(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import messaging

    args = args or {}
    meet = {k: args.get(k) for k in ("kind", "venue", "when") if args.get(k)}
    return _answer(lambda: messaging.ask(get_active_engine().state, target, str(args.get("what") or ""), meet))


@_phone_skill("Answer a request of theirs: yes, no or later.")
def social_answer(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import relationships

    return _answer(lambda: relationships.answer(get_active_engine().state, target, str((args or {}).get("reply") or "")))


@_phone_skill("End things with someone: the relationship is over, their thread stays.")
def social_end(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import relationships

    return _answer(lambda: relationships.end(get_active_engine().state, target))


@_phone_skill("Start a game with someone (Tile Talk): it starts at once, and the player moves first.")
def social_game_invite(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import games

    return _answer(lambda: games.invite(get_active_engine().state, target, str((args or {}).get("game") or "")))


@_phone_skill("Make a move in a game: play tiles, pass, or swap tiles (the engine judges and scores it).")
def social_game_move(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import games

    return _answer(lambda: games.move(get_active_engine().state, target, dict(args or {})))


@_phone_skill("Put the phone down: the world comes forward (the next narrated turn may run).")
def social_put_down(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import world

    return _answer(lambda: world.put_down(get_active_engine().state))


@_phone_skill("Go somewhere from the phone's Places app: the phone goes down and the player goes (the engine "
              "charges the travel).")
def social_places_go(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import world

    return _answer(lambda: world.places_go(get_active_engine().state, target))


# -- the world's verbs (v0.23.0 T11, spec §8.4-§8.5; Plan decision 4) --------------------------------
#
# System-only like the phone's (a storyteller-callable skill would join every story's tool list), but
# reached by a narrated turn's chosen option: `execute_intent` resolves `intents.SOCIAL_WORLD_ACTIONS`
# as AGENT_SYSTEM, and those actions are legal only in a story declaring `paths.social`.

WORLD_CATEGORY = "WORLD"


def _world_skill(description: str) -> Callable[[Callable[..., str]], Callable[..., str]]:
    register = skill(pack=PACK, description=description, category=WORLD_CATEGORY,
                     trigger=TRIGGER_SYSTEM, agents=[AGENT_SYSTEM])

    def decorator(func: Callable[..., str]) -> Callable[..., str]:
        @functools.wraps(func)
        def logged(*args: Any, **kwargs: Any) -> str:
            try:
                return func(*args, **kwargs)
            except Exception:
                logger.exception("[social] A world skill raised (operation=%s)", func.__name__)
                raise

        return register(logged)

    return decorator


@_world_skill("Do something in the world (an activity of the place the player is in): the engine spends its time.")
def social_do(activity: str = "") -> str:
    from engine.social import world

    return json.dumps(world.do(get_active_engine().state, activity), default=str)


@_world_skill("Go somewhere in the city (a venue, a home with a plan, or home): the engine charges the travel.")
def social_go(to: str = "") -> str:
    from engine.social import world

    return json.dumps(world.go(get_active_engine().state, to), default=str)


# -- a scene's verbs (v0.23.0 T13, spec §10.3-§10.4; Plan decision 5) ---------------------------------


@_world_skill("Make a move in an in-person scene (ask about one of their topics, tell them about yours, be playful, "
              "let a silence sit, talk): the engine scores it and spends its minutes.")
def social_scene(target: str = "") -> str:
    from engine.social import scene

    return json.dumps(scene.move(get_active_engine().state, target), default=str)


@_world_skill("End or move on an in-person scene (call it a night, another round, go somewhere else, walk them "
              "home, back to yours or theirs): the engine records what was agreed and charges the travel.")
def social_close(target: str = "") -> str:
    from engine.social import scene

    return json.dumps(scene.close(get_active_engine().state, target), default=str)

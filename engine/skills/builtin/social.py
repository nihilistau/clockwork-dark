"""
The phone's skills (v0.22.0 spec §7.3). System-only (Plan decision 4): no
storyteller or MCP agent can call them; the phone catalogue is their one
caller (tool_dispatcher.execute_phone_intent). Each is a thin shell over the
owning engine.social module, imported lazily so a story without paths.social
never loads it (spec §2.1).
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


@_phone_skill("Edit one of the player's profile fields on an app.")
def social_edit_profile(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import turn

    return _answer(lambda: turn.edit_profile(get_active_engine().state, target, args or {}, text))


@_phone_skill("Turn the player's read receipts on or off.")
def social_set_receipts(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import turn

    return _answer(lambda: turn.set_receipts(get_active_engine().state, target, args or {}))


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


@_phone_skill("Ask the person in a thread for something: their number, to be exclusive, a meet-up "
              "(the engine picks where and when), or a photo, a voice note or a video (the person decides).")
def social_ask(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import messaging

    return _answer(lambda: messaging.ask(get_active_engine().state, target, str((args or {}).get("what") or "")))


@_phone_skill("Answer a request of theirs: yes, no or later.")
def social_answer(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import relationships

    return _answer(lambda: relationships.answer(get_active_engine().state, target, str((args or {}).get("reply") or "")))


@_phone_skill("End things with someone: the relationship is over, their thread stays.")
def social_end(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import relationships

    return _answer(lambda: relationships.end(get_active_engine().state, target))


@_phone_skill("Propose a meet-up to someone: a venue, a day ahead and a slot (the engine answers: yes, "
              "another time, or not yet).")
def social_propose_meet(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import meets

    args = args or {}
    return _answer(lambda: meets.propose(get_active_engine().state, target, str(args.get("venue") or ""),
                                         int(args.get("day") or 0), str(args.get("slot") or "")))


@_phone_skill("Go to a meet-up that is due, or cancel a planned one (the engine resolves how it went).")
def social_meet(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import meets

    return _answer(lambda: meets.meet(get_active_engine().state, target, str((args or {}).get("do") or "")))


@_phone_skill("Start a game with someone (Tile Talk): it starts at once, and the player moves first.")
def social_game_invite(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import games

    return _answer(lambda: games.invite(get_active_engine().state, target, str((args or {}).get("game") or "")))


@_phone_skill("Make a move in a game: play tiles, pass, or swap tiles (the engine judges and scores it).")
def social_game_move(target: str = "", args: Optional[dict] = None, text: str = "") -> str:
    from engine.social import games

    return _answer(lambda: games.move(get_active_engine().state, target, dict(args or {})))

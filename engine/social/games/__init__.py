"""
The phone's two-player games (v0.22.0 spec §21): Tile Talk (T22) and This or
That (T23), played against a match or a contact, each side on its own clock.

A game is a row in `state.social["games"]` (`g<n>` ids, Plan decision 14):

    {id, game, pid, status: active | finished | abandoned, started_at,
     ended_at, moves: [last social.game_moves_kept records], winner, ...}

plus its game module's own part (`wordgame.new_game`). Every write is the
`social_game` effect (rule 3): `op: start` (a new row), `op: move` (one move
by the player or the person, judged and applied by the game module, rule 1),
`op: abandon` (the person left: unmatched, blocked, ended). A finished game
adds familiarity and interest (games.yaml `effects.finished`), and a
crushing win over a person of an archetype with a `<archetype>_crushing_warmth`
row costs that much warmth (spec §21.1), through `social_regard`.

**Their move** is a `game_move` event, queued at their pace (their reply
latency x `pace_mult`, moved past their sleep) when the player's move hands
them the turn. When it falls due the engine finds and picks their move
(`wordgame.their_move` on their SOCIAL_GAME stream) and, on a
`banter_prob` draw, lands a due `game_banter` message in their thread for
the voicing pass. A ghosted person lets the game sit; a gone one abandons it.

**Who starts a game**: the player's `game_invite` (the game starts at once,
the player moves first), or the person's `invite_game` proposal (§10.5): a
request the player answers yes to.

**Their own invite** (T23): each morning (a `daily` step) a person with
games open and none running or asked draws once on their SOCIAL_GAME stream
against their archetype's `games.invite_prob_per_day` (behaviours.yaml);
on a yes a `game_move` event carrying `invite: true` is queued at the
morning's hour, or when they wake, and when it falls due the proposal is
made through `relationships.apply_proposal` -- the path a voiced reply's
`invite_game` takes -- re-checked then, with a notification.

**Which game they ask for** (§10.5's draw is "none"): the offered game the
pair has played least among the rows kept, ties to apps.yaml's `offers`
order (`proposed_game`).

`GAMES` is the registry the catalogue, the effect and the payload read. Each
module provides `GAME`, `REVEALS`, `label`, `spec`, `new_game`,
`apply_move`, `their_move`, `winner`, `margin`, `bonus`, `compact`, `view`
and `banter_note`; a module whose `REVEALS` is true (This or That) also
provides `reveal(state, game_id, at=)`, which the `game_move` event runs
right after their move instead of the banter draw.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine import social
from engine.game import clock
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.intents import IntentVerb
from engine.game.rng import SOCIAL_GAME, SOCIAL_PACE
from engine.game.state import GameState
from engine.social import apps, behaviour, events, matching, messaging, population, relationships
from engine.social.games import this_or_that, wordgame
from engine.social.intents import ArgSpec, phone_verb
from engine.social.kinds import Decision, recorded, stage_rank
from engine.social.payload import section
from engine.social.turn import cost_hours

logger = logging.getLogger(__name__)

#: game id -> its module.
GAMES: dict[str, Any] = {wordgame.GAME: wordgame, this_or_that.GAME: this_or_that}
#: The app every game lives in (apps.yaml `kind: games`).
APP = "games"
#: A row's statuses.
STATUSES: tuple[str, ...] = ("active", "finished", "abandoned", "resigned")
#: What a `game_move` may be (spec §7.1: Tile Talk's tiles, a pass or a swap; This or That's answers, T23;
#: and the player's resign, on either turn: the game ends as their loss and the pair may start another,
#: T22 review I1). Each game's module refuses the kinds that are not its own.
MOVES: tuple[str, ...] = ("play", "pass", "swap", "answer", "resign")
RESIGN = "resign"
NOT_YOUR_TURN = "It's not your turn"


def _no(reason: str) -> dict[str, Any]:
    return {"ok": False, "error": reason}


def _name(state: GameState, pid: str) -> str:
    return matching._name(state, pid)


def _games(state: GameState) -> dict[str, Any]:
    return state.social.get("games") or {}


def _app_row() -> dict[str, Any]:
    rows = social.data("apps").get("apps") or {}
    for name, row in rows.items():
        if isinstance(row, dict) and row.get("kind") == "games":
            return {"id": name, **row}
    return {}


def offered() -> tuple[str, ...]:
    """The games the phone offers: apps.yaml's games app `offers` that this engine plays, in its order."""
    return tuple(g for g in (_app_row().get("offers") or ()) if g in GAMES)


def label_of(game: str) -> str:
    module = GAMES.get(game)
    return module.label() if module is not None else game


def running(state: GameState, pid: str) -> Optional[dict[str, Any]]:
    """`pid`'s active game, if any (one at a time with each person)."""
    for row in _games(state).values():
        if row.get("pid") == pid and row.get("status") == "active":
            return row
    return None


def _person(state: GameState, pid: str) -> dict[str, Any]:
    return (state.social.get("people") or {}).get(pid) or {}


def unlocked(state: GameState, pid: str) -> bool:
    """Games are open with `pid`: a listed thread, still there, live, at the games app's `unlock` stage or past."""
    row = _app_row()
    if not row or apps.gone(state, pid):
        return False
    stage = _person(state, pid).get("stage")
    if stage not in relationships.LIVE_STAGES or stage == "winding_down":
        return False
    if stage_rank(stage) < stage_rank(row.get("unlock") or "matched"):
        return False
    return any(t.get("pid") == pid and matching.listed(t) and not t.get("closed")
               for t in (state.social.get("threads") or {}).values())


def _pending_invite(state: GameState, pid: str) -> Optional[dict[str, Any]]:
    for r in (state.social.get("requests") or {}).values():
        if r["pid"] == pid and r["what"] == "game" and r["status"] in ("pending", "later"):
            return r
    return None


def invite_refusal(state: GameState, pid: str) -> str:
    """Why the player cannot start a game with `pid` now, in the engine's words; "" when they can."""
    name = _name(state, pid)
    if apps.gone(state, pid):
        return f"{name} is no longer available."
    if not unlocked(state, pid):
        return f"It's too soon to play a game with {name}."
    if running(state, pid) is not None:
        return f"You already have a game going with {name}."
    if _pending_invite(state, pid) is not None:
        return f"{name} has already asked you for a game."
    return ""


# -- the effect (rule 3) ------------------------------------------------------------------------------


def _trim(state: GameState) -> None:
    """Bounded state (spec §17.2): finished and abandoned rows past `social.games_kept` leave, oldest first."""
    rows = _games(state)
    done = sorted((r for r in rows.values() if r.get("status") != "active"),
                  key=lambda r: (float(r.get("ended_at") or 0.0), int(str(r["id"])[1:] or 0)))
    keep = int(social.setting("games_kept", 20))
    for row in done[:max(0, len(done) - keep)]:
        del rows[row["id"]]


def _end(state: GameState, row: dict[str, Any], status: str, at: float) -> None:
    """A row's end (inside the handler): its status, time, winner, its module's compaction."""
    row["status"] = status
    row["ended_at"] = at
    module = GAMES[row["game"]]
    if status == "finished":
        row["winner"] = module.winner(row)
    elif status == "resigned":
        row["winner"] = "them"                    # the player resigned: their loss, whatever the score
    module.compact(row)
    events.cancel(state, str(row["pid"]), {"game_move"}, where=lambda e: e.get("game_id") == row["id"])


def _finished_effects(state: GameState, row: dict[str, Any], at: float) -> None:
    """A finished game: familiarity and interest for both, plus the module's `bonus` (This or That's
    agreements, §21.2); a crushing win costs warmth by archetype (§21.1, a game with `crushing_margin`)."""
    module = GAMES[row["game"]]
    effects = module.spec()["effects"]
    pid = str(row["pid"])
    finished = effects["finished"]
    extra = module.bonus(row)
    relationships.add_familiarity(state, pid, int(finished["familiarity"]) + int(extra["familiarity"]), at=at)
    apply_effect(state, {"type": "social_regard", "pid": pid,
                         "interest": int(finished["interest"]) + int(extra["interest"]), "at": at})
    if "crushing_margin" in effects and module.margin(row) > int(effects["crushing_margin"]):
        archetype = population.profile(state, pid).archetype
        cost = effects.get(f"{archetype}_crushing_warmth")
        if cost:
            apply_effect(state, {"type": "social_regard", "pid": pid, "exact": True, "warmth": int(cost), "at": at})


def _their_pace_at(state: GameState, pid: str, at: float, mult: float) -> float:
    person = population.profile(state, pid)
    arch = behaviour.archetype(person.archetype)
    minutes = behaviour.lognormal_minutes(behaviour.person_rng(state, SOCIAL_PACE, pid), *arch.reply_minutes)
    due = at + minutes * float(mult) / 60.0
    if behaviour.status_at(person, due) == "asleep":
        due = behaviour.next_awake(person, due)
    return due


@effect_kind("social_game")
@recorded
def _e_game(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """Engine-only: `op: start | move | abandon` on a game row (spec §21)."""
    if not state.social:
        return {"type": "social_game", "ok": False, "text": "no social slice"}
    op = str(effect.get("op") or "")
    at = float(effect["at"]) if effect.get("at") is not None else state.world_clock_hours
    games = state.social.setdefault("games", {})
    if op == "start":
        game, pid = str(effect.get("game") or ""), str(effect.get("pid") or "")
        if game not in GAMES or not pid:
            return {"type": "social_game", "ok": False, "text": f"cannot start {game!r} with {pid!r}"}
        if running(state, pid) is not None:
            return {"type": "social_game", "ok": False, "text": f"{pid} already has a game going"}
        counters = state.social.setdefault("counters", {})
        counters["game"] = int(counters.get("game", 0)) + 1
        gid = f"g{counters['game']}"
        row = {"id": gid, "game": game, "pid": pid, "status": "active", "started_at": at, "ended_at": None,
               "moves": [], "winner": None, **GAMES[game].new_game(state, gid, pid)}
        games[gid] = row
        relationships.touch(state.social.setdefault("people", {}).setdefault(pid, {}))
        return {"type": "social_game", "ok": True, "text": f"started {gid}", "game_id": gid}
    row = games.get(str(effect.get("game_id") or ""))
    if row is None:
        return {"type": "social_game", "ok": False, "text": f"no game {effect.get('game_id')!r}"}
    gid, pid = str(row["id"]), str(row["pid"])
    if row.get("status") != "active":
        return {"type": "social_game", "ok": False, "text": f"{gid} is {row.get('status')}", "error": "That game is over."}
    if op == "abandon":
        _end(state, row, "abandoned", at)
        _trim(state)
        return {"type": "social_game", "ok": True, "text": f"abandoned {gid}", "game_id": gid}
    if op == RESIGN:
        record = {"by": "player", "kind": RESIGN, "words": [], "score": 0, "at": at}
        row["moves"].append(record)
        del row["moves"][:max(0, len(row["moves"]) - int(social.setting("game_moves_kept", 16)))]
        _end(state, row, "resigned", at)
        relationships.touch(state.social.setdefault("people", {}).setdefault(pid, {}))
        _trim(state)
        return {"type": "social_game", "ok": True, "text": f"the player resigned {gid}", "game_id": gid,
                "status": "resigned", "record": dict(record)}
    if op != "move":
        return {"type": "social_game", "ok": False, "text": f"{op!r} is no game op"}
    by = str(effect.get("by") or "")
    module = GAMES[row["game"]]
    out = module.apply_move(state, row, by, dict(effect.get("args") or {}))
    if not out.get("ok"):
        return {"type": "social_game", "ok": False, "text": str(out.get("error")), "error": str(out.get("error"))}
    record = {**out["record"], "at": at}
    row["moves"].append(record)
    del row["moves"][:max(0, len(row["moves"]) - int(social.setting("game_moves_kept", 16)))]
    relationships.touch(state.social.setdefault("people", {}).setdefault(pid, {}))
    if row.get("status") == "finished":
        _end(state, row, "finished", at)
        _finished_effects(state, row, at)
    elif row.get("turn") == "them":
        events.push(state, _their_pace_at(state, pid, at, float(module.spec()["pace_mult"])), pid, "game_move",
                    game_id=gid)
    result = {"type": "social_game", "ok": True, "text": f"{by} moved in {gid}", "game_id": gid,
              "status": row["status"], "record": {k: v for k, v in record.items() if k != "tiles"}}
    _trim(state)
    return result


def rearm(state: GameState, pid: str, at: float) -> int:
    """
    `pid` came back (a ghost cleared, messaging's reconnect): each active game of theirs on their turn
    with no `game_move` queued gets one again, at their pace from `at` (T22 review I1). The number
    re-armed. Called inside a `social_*` handler (the event that cleared the ghost), rule 3.
    """
    queued = {str(e.get("game_id") or "") for e in state.social.get("queue") or [] if e["kind"] == "game_move"}
    count = 0
    for row in sorted(_games(state).values(), key=lambda r: int(str(r["id"])[1:] or 0)):
        if row.get("pid") != pid or row.get("status") != "active" or row.get("turn") != "them"                 or row["id"] in queued:
            continue
        mult = float(GAMES[row["game"]].spec()["pace_mult"])
        events.push(state, _their_pace_at(state, pid, at, mult), pid, "game_move", game_id=row["id"])
        count += 1
    return count


def _banters(state: GameState, pid: str, module: Any) -> bool:
    """Their move brings a `game_banter` message: `banter_prob`, one draw on their SOCIAL_GAME stream."""
    return behaviour.person_rng(state, SOCIAL_GAME, pid).random() < float(module.spec()["banter_prob"])


# -- the person's side ----------------------------------------------------------------------------------


@events.handles("game_move")
def _on_game_move(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """Their move falls due: found and picked by the engine (rule 1), applied; maybe a banter message due."""
    if event.get("invite"):
        return _their_invite(state, event)
    pid, gid = str(event["pid"]), str(event.get("game_id") or "")
    row = _games(state).get(gid)
    if row is None or row.get("status") != "active" or row.get("turn") != "them":
        return {"ok": False, "why": "no move due"}
    at = float(event["at"])
    person_state = _person(state, pid)
    if apps.gone(state, pid) or person_state.get("stage") in ("ended", "faded"):
        apply_effect(state, {"type": "social_game", "op": "abandon", "game_id": gid, "at": at})
        return {"ok": True, "abandoned": True}
    if person_state.get("ghosted"):
        return {"ok": False, "why": "gone quiet"}             # until they come back: messaging re-arms it (rearm)
    module = GAMES[row["game"]]
    person = population.profile(state, pid)
    skill = float(behaviour.archetype(person.archetype).games.get("skill", 0.5))
    args = module.their_move(state, row, pid, skill, behaviour.person_rng(state, SOCIAL_GAME, pid))
    moved = apply_effect(state, {"type": "social_game", "op": "move", "game_id": gid, "by": "them",
                                 "args": args, "at": at})
    if not moved.get("ok"):
        logger.error("[social] A person's game move was refused by its own judge; they pass "
                     "(operation=game_move, game=%s, pid=%s): %s", gid, pid, moved.get("text"))
        moved = apply_effect(state, {"type": "social_game", "op": "move", "game_id": gid, "by": "them",
                                     "args": {"move": "pass"}, "at": at})
        if not moved.get("ok"):                         # a game with no pass (This or That): never stuck on them
            return _abandon_stuck(state, gid, pid, at, "their pass was refused too", moved)
    tid = messaging.thread_for(state, pid)
    if tid is not None:
        record = moved.get("record") or {}
        if record.get("words"):
            preview = f"{_name(state, pid)} played {str(record['words'][0]).upper()}"
        elif record.get("kind") == "answer":
            preview = f"{_name(state, pid)} answered {module.label()}"
        else:
            preview = f"{_name(state, pid)} moved in {module.label()}"
        messaging.notify(state, APP, "", pid, "game_move", preview, at=at)
    if module.REVEALS and moved.get("ok"):
        revealed = module.reveal(state, gid, at=at)  # the reveal queues their reaction itself (§21.2)
        if not revealed.get("ok"):                   # never left at `reveal` with their picks in state
            return _abandon_stuck(state, gid, pid, at, "the reveal failed", revealed)
    elif tid is not None and _banters(state, pid, module):
        messaging.queue_due(state, pid, tid, Decision(situation="game_banter", max_bubbles=2, game_id=gid), at)
    return {"ok": bool(moved.get("ok")), "game_id": gid}


def _abandon_stuck(state: GameState, gid: str, pid: str, at: float, why: str,
                   out: dict[str, Any]) -> dict[str, Any]:
    """A game the engine could not move on (a bug, logged at ERROR): abandoned through the effect, never
    left waiting on a turn nothing will take (T23 review M1)."""
    logger.error("[social] A game could not continue and is abandoned (operation=game_move, game=%s, pid=%s): "
                 "%s: %s", gid, pid, why, out.get("error") or out.get("text"))
    apply_effect(state, {"type": "social_game", "op": "abandon", "game_id": gid, "at": at})
    return {"ok": False, "abandoned": True, "game_id": gid}


def _abandon_gone(state: GameState) -> None:
    """Each morning (a `daily` step): a game whose person is gone, or whose relationship ended or faded, ends."""
    at = events.daily_at(state)
    for row in list(_games(state).values()):
        if row.get("status") != "active":
            continue
        pid = str(row["pid"])
        if apps.gone(state, pid) or _person(state, pid).get("stage") in ("ended", "faded"):
            apply_effect(state, {"type": "social_game", "op": "abandon", "game_id": row["id"], "at": at})


if _abandon_gone not in events.daily_hooks:
    events.daily_hooks.append(_abandon_gone)


def _invite_prob(state: GameState, pid: str) -> float:
    """Their archetype's behaviours.yaml `games.invite_prob_per_day` (a balance constant, T26's to measure)."""
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    return float(arch.games.get("invite_prob_per_day", 0.0))


def _queue_their_invites(state: GameState) -> None:
    """
    Each morning (a `daily` step, after `_abandon_gone`): everyone the player has a listed thread with,
    in pid order, whose games are open with none running, asked or already on the way, and who is not
    ghosted, draws once on their SOCIAL_GAME stream; under `invite_prob_per_day` an invite is queued as
    a `game_move` event (`invite: true`) at the morning's hour, or when they wake.
    """
    at = events.daily_at(state)
    queued = {e["pid"] for e in state.social.get("queue") or [] if e["kind"] == "game_move" and e.get("invite")}
    pids = {t["pid"] for t in (state.social.get("threads") or {}).values() if matching.listed(t)}
    for pid in sorted(pids - queued):
        if _person(state, pid).get("ghosted") or not proposal_open(state, pid):
            continue
        prob = _invite_prob(state, pid)
        if prob <= 0.0 or behaviour.person_rng(state, SOCIAL_GAME, pid).random() >= prob:
            continue
        person = population.profile(state, pid)
        when = behaviour.next_awake(person, at) if behaviour.status_at(person, at) == "asleep" else at
        events.push(state, when, pid, "game_move", invite=True)


if _queue_their_invites not in events.daily_hooks:
    events.daily_hooks.append(_queue_their_invites)


def _their_invite(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """Their daily invite falls due: the `invite_game` proposal, re-checked now, as a voiced reply's would be."""
    pid, at = str(event["pid"]), float(event["at"])
    if _person(state, pid).get("ghosted") or "invite_game" not in relationships.legal_proposals(state, pid):
        return {"ok": False, "why": "no longer open"}
    made = relationships.apply_proposal(state, pid, "invite_game", at=at)
    if made.get("ok"):
        request = state.social["requests"][made["request_id"]]
        messaging.notify(state, APP, str(request.get("thread_id") or ""), pid, "game_invite",
                         f"{_name(state, pid)} wants to play {label_of(str(request.get('game') or ''))}", at=at)
    return {"ok": bool(made.get("ok")), "request_id": made.get("request_id")}


# -- the player's actions --------------------------------------------------------------------------------


def start(state: GameState, pid: str, game: str) -> dict[str, Any]:
    """A new game with `pid` (the player moves first); refused in the engine's words."""
    if game not in offered():
        return _no(f"You can't play {game} here.")
    made = apply_effect(state, {"type": "social_game", "op": "start", "pid": pid, "game": game})
    if not made.get("ok"):
        return _no(str(made.get("text")))
    return {"ok": True, "game_id": made["game_id"], "game": game, "pid": pid}


def invite(state: GameState, pid: str, game: str) -> dict[str, Any]:
    """The player's `game_invite` (spec §7.1): the game starts at once, then the invite's minutes pass."""
    refusal = invite_refusal(state, pid)
    if refusal:
        return _no(refusal)
    started = start(state, pid, game)
    if started.get("ok"):
        clock.advance_time(state, cost_hours(state, APP, "move"))
    return started


def accept(state: GameState, pid: str, game: str) -> dict[str, Any]:
    """Their invite answered yes (relationships.answer): the game starts, the player first."""
    if running(state, pid) is not None or apps.gone(state, pid):
        return _no("That isn't on the table any more.")
    return start(state, pid, game)


def move(state: GameState, game_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """The player's `game_move`: judged and applied by the engine (rule 1), then its minutes pass."""
    row = _games(state).get(game_id)
    if row is None:
        return _no("There's no such game.")
    kind = str(args.get("move") or "")
    refusal = move_refusal(state, row, kind)
    if refusal:
        return _no(refusal)
    if kind == RESIGN:
        moved = apply_effect(state, {"type": "social_game", "op": RESIGN, "game_id": game_id})
    else:
        moved = apply_effect(state, {"type": "social_game", "op": "move", "game_id": game_id, "by": "player",
                                     "args": dict(args)})
    if not moved.get("ok"):
        return _no(str(moved.get("error") or moved.get("text")))
    clock.advance_time(state, cost_hours(state, APP, "move"))
    record = moved.get("record") or {}
    return {"ok": True, "game_id": game_id, "move": record.get("kind"), "words": list(record.get("words") or []),
            "score": int(record.get("score") or 0), "status": moved.get("status")}


def move_refusal(state: GameState, row: dict[str, Any], kind: str = "") -> str:
    """Why the player cannot make a `kind` move in `row` now; "" when they can. A resign is open on either
    turn, and with someone who has left (it frees the pair)."""
    if row.get("status") != "active":
        return "That game is over."
    if kind == RESIGN:
        return ""
    if apps.gone(state, str(row["pid"])):
        return f"{_name(state, str(row['pid']))} is no longer available."
    if row.get("turn") != "player":
        return NOT_YOUR_TURN
    return ""


def proposal_open(state: GameState, pid: str) -> bool:
    """§10.5 `invite_game`'s gate beyond its data row: games unlocked with them, none running, none asked."""
    return bool(offered()) and unlocked(state, pid) and running(state, pid) is None \
        and _pending_invite(state, pid) is None


def proposed_game(state: GameState, pid: str) -> str:
    """
    Which game their `invite_game` asks for, with no draw (spec §10.5: "none"): the offered game the pair
    has played least among the rows kept (`social.games_kept`), ties to `offered()`'s order (apps.yaml
    `offers`). So a first invite asks for the first game offered, the next for the other.
    """
    games = offered()
    played = {g: 0 for g in games}
    for row in _games(state).values():
        if row.get("pid") == pid and row.get("game") in played:
            played[row["game"]] += 1
    return min(games, key=lambda g: (played[g], games.index(g)))


def banter_note(state: GameState, game_id: str) -> str:
    """The voice's line about a game (engine words), for a `game_banter` due message; "" for none."""
    row = _games(state).get(game_id)
    if row is None or row["game"] not in GAMES:
        return ""
    return GAMES[row["game"]].banter_note(row)


# -- the catalogue (spec §7.1) -------------------------------------------------------------------------------


def _invitable(state: GameState) -> list[str]:
    pids = {t["pid"] for t in (state.social.get("threads") or {}).values() if matching.listed(t)}
    return sorted(p for p in pids if not invite_refusal(state, p))


def _invite_label(state: GameState, intent: dict[str, Any]) -> str:
    game = str((intent.get("args") or {}).get("game") or "")
    return f"Play {label_of(game)} with {_name(state, str(intent.get('target') or ''))}"


def _invite_refuse(state: GameState, intent: dict[str, Any]) -> str:
    pid = str(intent.get("target") or "")
    known = {t["pid"] for t in (state.social.get("threads") or {}).values()}
    return invite_refusal(state, pid) if pid in known else ""


@phone_verb("game_invite", payload={"game": ArgSpec("enum", tuple(GAMES), required=True)},
            skill="social_game_invite", label=_invite_label, refuse=_invite_refuse)
def _invite_verb(state: GameState) -> Optional[IntentVerb]:
    games = offered()
    pids = _invitable(state) if games else []
    if not pids:
        return None
    return IntentVerb("game_invite", options=tuple((p, _name(state, p)) for p in pids), extra={"game": games})


def _game_label(state: GameState, row: dict[str, Any]) -> str:
    return f"{label_of(row['game'])} with {_name(state, str(row['pid']))}"


def _move_label(state: GameState, intent: dict[str, Any]) -> str:
    row = _games(state).get(str(intent.get("target") or ""))
    kind = str((intent.get("args") or {}).get("move") or "")
    if row is None:
        return "Make a move"
    verb = {"pass": "Pass", "swap": "Swap tiles", "answer": "Answer", RESIGN: "Resign"}.get(kind, "Play")
    return f"{verb} in {_game_label(state, row)}"


def _move_refuse(state: GameState, intent: dict[str, Any]) -> str:
    row = _games(state).get(str(intent.get("target") or ""))
    kind = str((intent.get("args") or {}).get("move") or "")
    return move_refusal(state, row, kind) if row is not None else ""


@phone_verb("game_move", payload={"move": ArgSpec("enum", MOVES, required=True),
                                  "tiles": ArgSpec("list", max_len=7),
                                  "letters": ArgSpec("text", max_len=7),
                                  "answers": ArgSpec("list", min_len=this_or_that.ROUNDS,
                                                     max_len=this_or_that.ROUNDS,
                                                     item=ArgSpec("enum", this_or_that.PICKS))},
            skill="social_game_move", label=_move_label, refuse=_move_refuse)
def _move_verb(state: GameState) -> Optional[IntentVerb]:
    # Every active game: a resign is open on either turn; any other move off the player's turn is
    # refused by `move` in words ("It's not your turn").
    rows = [r for r in _games(state).values() if not move_refusal(state, r, RESIGN)]
    if not rows:
        return None
    rows.sort(key=lambda r: int(str(r["id"])[1:] or 0))
    return IntentVerb("game_move", options=tuple((r["id"], _game_label(state, r)) for r in rows))


# -- the payload (spec §17.3) ----------------------------------------------------------------------------------


@section("games", time_varying=True)
def _games_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """Every game kept, newest first: what the player may see (their own rack, the bag's count; never theirs)."""
    out: list[dict[str, Any]] = []
    for row in sorted(_games(state).values(), key=lambda r: -int(str(r["id"])[1:] or 0)):
        if row["game"] not in GAMES:
            continue
        moves = [{k: v for k, v in m.items() if k in ("by", "kind", "words", "score", "at", "swapped")}
                 for m in row.get("moves") or []]
        out.append({"id": row["id"], "game": row["game"], "label": label_of(row["game"]), "pid": row["pid"],
                    "name": _name(state, str(row["pid"])), "status": row["status"], "winner": row.get("winner"),
                    "started_at": row.get("started_at"), "ended_at": row.get("ended_at"), "moves": moves,
                    **GAMES[row["game"]].view(state, row)})
    return out

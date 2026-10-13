"""
This or That (v0.22.0 spec §21.2): a quick preferences game played on the
phone against a match or a contact. Five either/or pairs are dealt from
games.yaml's bank; the player answers all five with one `game_move`
(`{move: answer, answers: [a|b x5]}`); the person answers on their own clock;
then the reveal shows where they agree.

The ENGINE decides everything here (rule 1): which pairs are dealt
(`stable_rng(seed, f"{SOCIAL_GAME}:{game_id}")`), the person's picks
(`their_answers`: derived from their hobbies, traits and personality sliders
through games.yaml `tags`, plus seeded noise, one draw per pair on their
SOCIAL_GAME stream), and what matched. The model only words the reaction:
the reveal queues a due `game_banter` message whose RIGHT NOW line is
`banter_note`.

A game row (`state.social["games"][game_id]`, the `this_or_that` part):

    pairs       [5 x {a: {label, tags}, b: {label, tags}}] (tags dropped
                once the game is over)
    picks       {"player": [a|b x5] | None, "them": [a|b x5] | None}
    turn        "player" -> "them" (the player answered) -> "reveal" (they
                answered; the reveal follows in the same event) -> over
    agreed      the indices both picked alike (set at the reveal)

`picks` never leaves the server: the payload shows the player's own picks
(`mine`) and theirs (`theirs`) only once the game is over, and their picks
are drawn only after the player's are in (the player always answers
first). tests/test_ui_contract.py scans for `picks`.

This module is pure but for `apply_move` (inside the `social_game` effect's
handler only, rule 3) and `reveal`, which writes through `apply_effect`
(the `social_game` move that ends the game, `social_memory` for the canon,
`social_queue` for the reaction).
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional, Sequence

from engine import social
from engine.game.rng import SOCIAL_GAME, stable_rng

#: The game's id in apps.yaml's `games.offers` and games.yaml.
GAME = "this_or_that"
#: Pairs a game deals, and so answers a move carries (spec §21.2: five).
ROUNDS = 5
#: A pick: the pair's `a` or its `b`.
PICKS: tuple[str, str] = ("a", "b")
#: The bank's floor (the plan's T23 row: 60 or more pairs).
MIN_PAIRS = 60
#: This game ends in a reveal the engine runs right after their answer (engine/social/games `_on_game_move`).
REVEALS = True
#: The move kinds: the player's and the person's `answer`; the person's `reveal` (the engine's, after theirs).
ANSWER = "answer"
REVEAL = "reveal"

# -- the engine's refusals (rule 1: each reaches the player) ---------------------------------
NOT_A_MOVE = "That isn't a move in This or That."
PICK_FIVE = f"Pick a or b for each of the {ROUNDS} pairs."
NOT_YOUR_TURN = "It's not your turn"


# -- data ---------------------------------------------------------------------------------------


def spec() -> dict[str, Any]:
    """games.yaml's `this_or_that:` block (checked whole at load, `data_faults`)."""
    block = social.data("games").get(GAME)
    if not isinstance(block, dict):
        raise ValueError("social: games.yaml: this_or_that: required for This or That (spec §21.2)")
    return block


def label() -> str:
    return str(spec().get("label") or "This or That")


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def data_faults(block: Any, population: Optional[dict[str, Any]] = None) -> list[tuple[str, str]]:
    """
    Every fault of games.yaml's `this_or_that:` block, as (key, message): the
    numbers, the tags (each hobby, trait and slider one population.yaml
    knows, when `population` is given) and the bank (60 or more pairs, each
    `{a: {label, tags}, b: {label, tags}}` naming only declared tags). Read by
    the loader (the first fault a ValueError) and by `validation.check_social`.
    """
    if not isinstance(block, dict):
        return [("this_or_that", "must be a mapping")]
    out: list[tuple[str, str]] = []
    if not isinstance(block.get("label"), str) or not block["label"]:
        out.append(("this_or_that.label", "required: what the phone calls the game"))
    if not _num(block.get("pace_mult")) or block["pace_mult"] < 0:
        out.append(("this_or_that.pace_mult", "required: a number, 0 or more"))
    lean = block.get("lean")
    if not isinstance(lean, dict):
        out.append(("this_or_that.lean", "required: {hobby, trait, slider, sharpness, noise}"))
    else:
        for key in ("hobby", "trait", "slider", "sharpness", "noise"):
            if not _num(lean.get(key)) or lean[key] < 0:
                out.append((f"this_or_that.lean.{key}", "required: a number, 0 or more"))
        if _num(lean.get("noise")) and lean["noise"] > 1:
            out.append(("this_or_that.lean.noise", "must be 0 to 1"))
    effects = block.get("effects")
    if not isinstance(effects, dict):
        out.append(("this_or_that.effects", "required: {finished: {familiarity, interest}, agree_familiarity, "
                                            "agree_interest}"))
    else:
        finished = effects.get("finished")
        if not isinstance(finished, dict) or not all(_num(finished.get(k)) for k in ("familiarity", "interest")):
            out.append(("this_or_that.effects.finished", "required: {familiarity, interest}"))
        for key in ("agree_familiarity", "agree_interest"):
            if not _num(effects.get(key)):
                out.append((f"this_or_that.effects.{key}", "required: a number (per agreement)"))
        for key in sorted(set(effects) - {"finished", "agree_familiarity", "agree_interest"}):
            out.append((f"this_or_that.effects.{key}", "is not a key This or That reads"))
    hobbies = traits = sliders = None
    if isinstance(population, dict):
        hobbies = {str(r.get("id")) for r in population.get("hobbies") or () if isinstance(r, dict)}
        traits = {str(r.get("id")) for r in population.get("traits") or () if isinstance(r, dict)}
        sliders = {str(s) for s in population.get("personality") or ()}
    tags = block.get("tags")
    if not isinstance(tags, dict) or not tags:
        out.append(("this_or_that.tags", "required: tag -> {hobbies, traits, sliders}"))
        tags = {}
    for name, row in tags.items():
        key = f"this_or_that.tags.{name}"
        if not isinstance(row, dict) or not _str_list(row.get("hobbies", [])) \
                or not _str_list(row.get("traits", [])) or not isinstance(row.get("sliders", {}), dict):
            out.append((key, "must be {hobbies: [ids], traits: [ids], sliders: {slider: sign}}"))
            continue
        for slider, sign in (row.get("sliders") or {}).items():
            if not _num(sign):
                out.append((key, f"slider {slider!r}: the sign must be a number"))
        if hobbies is not None:
            for hobby in row.get("hobbies") or ():
                if hobby not in hobbies:
                    out.append((key, f"unknown hobby {hobby!r} (population.yaml hobbies)"))
            for trait in row.get("traits") or ():
                if trait not in traits:   # type: ignore[operator]
                    out.append((key, f"unknown trait {trait!r} (population.yaml traits)"))
            for slider in row.get("sliders") or {}:
                if slider not in sliders:   # type: ignore[operator]
                    out.append((key, f"unknown slider {slider!r} (population.yaml personality)"))
    pairs = block.get("pairs")
    if not isinstance(pairs, list) or len(pairs) < MIN_PAIRS:
        out.append(("this_or_that.pairs", f"must list at least {MIN_PAIRS} pairs, not "
                                          f"{len(pairs) if isinstance(pairs, list) else 0}"))
        pairs = pairs if isinstance(pairs, list) else []
    for i, pair in enumerate(pairs):
        key = f"this_or_that.pairs[{i}]"
        if not isinstance(pair, dict) or set(pair) != set(PICKS):
            out.append((key, "must be {a: {label, tags}, b: {label, tags}}"))
            continue
        for side in PICKS:
            option = pair[side]
            if not isinstance(option, dict) or not isinstance(option.get("label"), str) or not option["label"] \
                    or not _str_list(option.get("tags")):
                out.append((f"{key}.{side}", "must be {label: text, tags: [tag, ...]}"))
                continue
            for tag in option["tags"]:
                if tag not in tags:
                    out.append((f"{key}.{side}", f"unknown tag {tag!r} (this_or_that.tags)"))
        if all(isinstance(pair[s], dict) for s in PICKS) and pair["a"].get("label") == pair["b"].get("label"):
            out.append((key, "a and b must differ"))
    return out


def check_data(block: Any, population: Optional[dict[str, Any]] = None) -> None:
    """At load (social._check_loaded): the first fault a ValueError naming the file and key."""
    faults = data_faults(block, population)
    if faults:
        key, message = faults[0]
        raise ValueError(f"social: games.yaml: {key}: {message}")


# -- a new game ----------------------------------------------------------------------------------


def deal(seed: int, game_id: str) -> list[dict[str, Any]]:
    """The game's five pairs, drawn without repeats from its own stream (spec §21.2): another id, another deal."""
    bank = list(spec()["pairs"])
    rng = stable_rng(int(seed), f"{SOCIAL_GAME}:{game_id}")
    return [{side: {"label": str(bank[i][side]["label"]), "tags": [str(t) for t in bank[i][side]["tags"]]}
             for side in PICKS} for i in rng.sample(range(len(bank)), ROUNDS)]


def new_game(state: Any, game_id: str, pid: str) -> dict[str, Any]:
    """The `this_or_that` part of a new row: five pairs dealt, no picks yet, the player first."""
    return {"pairs": deal(state.rng_seed, game_id), "picks": {"player": None, "them": None},
            "turn": "player", "agreed": None}


# -- their picks (rule 1: the engine's, from their profile) ----------------------------------------


def _pull(person: Any, tags: Sequence[str]) -> float:
    """How strongly `person` leans toward an option with these tags (games.yaml `lean`, `tags`)."""
    block = spec()
    lean, table = block["lean"], block["tags"]
    hobbies, traits = set(person.hobbies), set(person.traits)
    sliders = dict(person.personality)
    pull = 0.0
    for tag in tags:
        row = table.get(tag) or {}
        if hobbies & set(row.get("hobbies") or ()):
            pull += float(lean["hobby"])
        if traits & set(row.get("traits") or ()):
            pull += float(lean["trait"])
        for slider, sign in (row.get("sliders") or {}).items():
            pull += float(lean["slider"]) * float(sign) * (float(sliders.get(slider, 3)) - 3.0) / 2.0
    return pull


def chance_of_a(person: Any, pair: dict[str, Any]) -> float:
    """The chance `person` picks the pair's `a`: noise/2 + (1 - noise) x logistic(sharpness x pull difference)."""
    lean = spec()["lean"]
    diff = float(lean["sharpness"]) * (_pull(person, pair["a"]["tags"]) - _pull(person, pair["b"]["tags"]))
    noise = float(lean["noise"])
    return noise / 2.0 + (1.0 - noise) / (1.0 + math.exp(-diff))


def their_answers(person: Any, pairs: Sequence[dict[str, Any]], rng: random.Random) -> list[str]:
    """The person's picks, one draw on `rng` per pair (always one, so the stream's use is fixed)."""
    return ["a" if rng.random() < chance_of_a(person, pair) else "b" for pair in pairs]


def their_move(state: Any, row: dict[str, Any], pid: str, skill: float, rng: random.Random,
               counter: Any = None) -> dict[str, Any]:
    """The person's move args, decided by the engine: their five picks (`skill` plays no part here)."""
    from engine.social import population   # lazily: population imports this package's parent

    return {"move": ANSWER, "answers": their_answers(population.profile(state, pid), row["pairs"], rng)}


# -- applying a move (inside the social_game handler only: rule 3) ------------------------------------


def valid_answers(answers: Any) -> bool:
    return isinstance(answers, list) and len(answers) == ROUNDS and all(a in PICKS for a in answers)


def apply_move(state: Any, row: dict[str, Any], by: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    One move by `by`: `answer` (`answers`, five of a|b) on their turn; or the
    engine's `reveal` (by them, once both have answered), which ends the
    game with the pairs both picked alike. The row changes only when the
    move is legal; the record carries no picks.
    """
    kind = str(args.get("move") or "")
    record: dict[str, Any] = {"by": by, "kind": kind, "words": [], "score": 0}
    if kind == ANSWER:
        if row.get("turn") != by:
            return {"ok": False, "error": NOT_YOUR_TURN}
        answers = args.get("answers")
        if not valid_answers(answers):
            return {"ok": False, "error": PICK_FIVE}
        row["picks"][by] = [str(a) for a in answers]
        row["turn"] = "them" if by == "player" else REVEAL
        return {"ok": True, "record": record}
    if kind == REVEAL:
        picks = row.get("picks") or {}
        if by != "them" or row.get("turn") != REVEAL or not picks.get("player") or not picks.get("them"):
            return {"ok": False, "error": NOT_A_MOVE}
        row["agreed"] = [i for i in range(ROUNDS) if picks["player"][i] == picks["them"][i]]
        row["status"] = "finished"
        record["score"] = len(row["agreed"])
        return {"ok": True, "record": record}
    return {"ok": False, "error": NOT_A_MOVE}


def winner(row: dict[str, Any]) -> Optional[str]:
    """A preferences game has no winner."""
    return None


def margin(row: dict[str, Any]) -> int:
    return 0


def bonus(row: dict[str, Any]) -> dict[str, int]:
    """A finished game's effects beyond `finished`: each agreement's familiarity and interest (spec §21.2)."""
    effects = spec()["effects"]
    agreed = len(row.get("agreed") or ())
    return {"familiarity": agreed * int(effects["agree_familiarity"]),
            "interest": agreed * int(effects["agree_interest"])}


def compact(row: dict[str, Any]) -> None:
    """An ended row keeps its pairs' labels and both picks (the reveal's view and banter); no tags."""
    for pair in row.get("pairs") or ():
        for side in PICKS:
            pair.get(side, {}).pop("tags", None)


def _line(pair: dict[str, Any], pick: str) -> str:
    other = "b" if pick == "a" else "a"
    return f"{pair[pick]['label']} over {pair[other]['label']}"


def agreement_lines(row: dict[str, Any]) -> list[str]:
    """The reveal's canon, engine words: "You both pick mountains over beaches", one per agreement."""
    picks = row["picks"]["player"]
    return [f"You both pick {_line(row['pairs'][i], picks[i])}" for i in row.get("agreed") or ()]


def view(state: Any, row: dict[str, Any]) -> dict[str, Any]:
    """What the player sees: the pairs' labels, their own picks; theirs and the agreements only once it is over."""
    picks = row.get("picks") or {}
    over = row.get("status") == "finished"
    return {
        "pairs": [{side: str(pair[side]["label"]) for side in PICKS} for pair in row.get("pairs") or ()],
        "mine": list(picks.get("player") or []) or None,
        "theirs": list(picks.get("them") or []) if over else None,
        "agreements": len(row.get("agreed") or ()) if over else None,
        "turn": row.get("turn") if row.get("turn") in ("player", "them") else "them",
    }


def banter_note(row: dict[str, Any]) -> str:
    """The voice's line about the game (engine words, "you" the person, "they" the player)."""
    picks = row.get("picks") or {}
    if row.get("status") != "finished" or not picks.get("player") or not picks.get("them"):
        return f"{label()}: you are still answering."
    agreed = list(row.get("agreed") or ())
    both = [_line(row["pairs"][i], picks["player"][i]) for i in agreed]
    split = [f"you picked {row['pairs'][i][picks['them'][i]]['label']}, they picked "
             f"{row['pairs'][i][picks['player'][i]]['label']}" for i in range(ROUNDS) if i not in agreed]
    parts = [f"{label()}: you agree on {len(agreed)} of {ROUNDS}."]
    if both:
        parts.append("You both pick " + "; ".join(both) + ".")
    if split:
        parts.append("Where you differ: " + "; ".join(split) + ".")
    return " ".join(parts)


# -- the reveal ------------------------------------------------------------------------------------


def reveal(state: Any, game_id: str, *, at: Optional[float] = None) -> dict[str, Any]:
    """
    Both have answered: the game ends (the `social_game` move `reveal`, which
    applies the finished-game effects and each agreement's, games.yaml
    `effects`), each agreement is written as canon both ways -- what they
    hold (`canon`) and what they know of the player (`knows`) -- in the
    engine's words, and their reaction is queued as a due `game_banter`
    message. Called by the `game_move` event right after their answer.
    """
    from engine.game.effects import apply_effect
    from engine.social import memory, messaging   # lazily: both import this package's parent
    from engine.social.kinds import Decision

    row = (state.social.get("games") or {}).get(game_id)
    if row is None or row.get("game") != GAME:
        return {"ok": False, "error": "There's no such game."}
    when = float(state.world_clock_hours if at is None else at)
    moved = apply_effect(state, {"type": "social_game", "op": "move", "game_id": game_id, "by": "them",
                                 "args": {"move": REVEAL}, "at": when})
    if not moved.get("ok"):
        return {"ok": False, "error": str(moved.get("error") or moved.get("text"))}
    pid = str(row["pid"])
    lines = agreement_lines(row)
    if lines:
        memory.add_canon(state, pid, lines)
        memory.add_knows(state, pid, lines)
    tid = messaging.thread_for(state, pid)
    if tid is not None:
        messaging.queue_due(state, pid, tid, Decision(situation="game_banter", max_bubbles=2, game_id=game_id), when)
    return {"ok": True, "game_id": game_id, "agreements": len(row.get("agreed") or ()), "agreed": lines}

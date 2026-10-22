"""
Typed world lines, read against the engine's offer (v0.23.0 addendum 4 §3, §3.1, W7; C2, R1).

A line the player types in the world carries NO intent at the route (`default_state.resolve_player_intent`
returns `{}` for it, rule 1). A phone story reads it later, on the server, in `default_scene._run_world_turn`:
the turnstile and the turn lock held, the inbox drained, so the reading sees the state the turn runs on and
nothing can land between the reading and the execution (C2). What it may become, first match wins:

1. ONE activity or room the engine offers now (`match_offered`): a legal `do` target (a scene's shared
   activities included) or a legal core `travel` target, by a conservative, closed matcher;
2. in a scene, a topic move (`ask_about:<t>` / `tell_about:<t>`) whose topic the line names;
3. in a scene, `talk`;
4. otherwise `{}`: the line is narrated only, with no mechanic and no time.

Every result is an intent among `intents.legal_intents(state)` at that moment, re-checked with the same
`find_verb` and targets test `tool_dispatcher.execute_intent` applies, so a typed line never comes back as a
refusal. It never infers a `go` (a venue, a home), a closer, a plan, a promise, an `approach`, a phone action,
or `go_to_work` / `carry_on_working` / `leave_early` (§3): commitments in person come only from closers the
player picks. The line itself is play text: it is never logged here; only the inferred action and target
are (by the caller).

The phrases and cue lists are the story's data (`activities.yaml` `say:` and `typed:`, checked at load by
`world.check_activities`). Stateless: no globals beyond constants.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence

from engine import social
from engine.game import intents
from engine.game.state import GameState
from engine.social import convo

#: Where a line splits into clauses (A4 §3.1 step 3).
_SPLIT = re.compile(r"[,;.!]|\band\b|\bthen\b")
#: Activities the matcher may never run, whatever the line says (A4 §3).
NEVER: frozenset[str] = frozenset({"go_to_work", "carry_on_working", "leave_early"})
#: The cue lists `activities.yaml typed:` carries (beside `rooms`).
CUE_KEYS: tuple[str, ...] = ("modals", "negations", "shifts", "leads", "progressive_leads", "movement")
#: Every key `activities.yaml typed:` may carry.
TYPED_KEYS: tuple[str, ...] = (*CUE_KEYS, "rooms")
#: The phrases that alone name the player's work as a topic (W7): a bare "work" never does.
WORK_PHRASES: tuple[str, ...] = ("my job", "my work")
#: The receipt's line for the narrator (A4 §3, "The receipt says so").
READING = "The player said this; the engine read it as: {label}{band}."


def _block() -> dict[str, Any]:
    block = (social.data("activities") or {}).get("typed") or {}
    return block if isinstance(block, dict) else {}


def _cues() -> dict[str, tuple[str, ...]]:
    block = _block()
    return {k: tuple(str(w).casefold() for w in block.get(k) or ()) for k in CUE_KEYS}


def _normal(text: Any) -> str:
    """Casefolded, whitespace collapsed, a typographic apostrophe read as a plain one."""
    return " ".join(str(text or "").replace("’", "'").replace("‘", "'").casefold().split())


def _forms(verb: str, *, acted: bool, progressive: bool) -> tuple[str, ...]:
    """The verb's allowed forms (§3.1 step 5): the base; `+s`/`+es` only acted; `-ing` acted or progressive."""
    out = [verb]
    if acted:
        out.append(verb + "es" if verb.endswith(("s", "sh", "ch", "x", "o")) else verb + "s")
    if acted or progressive:
        out.append(verb[:-1] + "ing" if verb.endswith("e") and not verb.endswith("ee") else verb + "ing")
    return tuple(out)


def _starts(clause: str, phrase: str, *, acted: bool, progressive: bool) -> bool:
    """The clause STARTS with the phrase (two words or more), its first word in an allowed form."""
    words = phrase.split()
    if len(words) < 2:
        return False
    rest = " ".join(words[1:])
    return any(re.match(rf"{re.escape(f)}\s+{re.escape(rest)}(?!\w)", clause)
               for f in _forms(words[0], acted=acted, progressive=progressive))


def _strip_lead(clause: str, leads: Sequence[str], progressive_leads: Sequence[str]) -> tuple[str, bool]:
    """One leading `leads` entry stripped; then a leading `progressive_leads` entry, marking it progressive.
    A lead never eats the start of a progressive one ("i" of "i am making ...")."""
    progressive = sorted(progressive_leads, key=len, reverse=True)

    def strip_progressive(text: str) -> Optional[str]:
        for lead in progressive:
            if text.startswith(lead + " "):
                return text[len(lead):].strip()
        return None

    first = strip_progressive(clause)
    if first is not None:
        return first, True
    for lead in sorted(leads, key=len, reverse=True):
        if clause == lead or clause.startswith(lead + " "):
            clause = clause[len(lead):].strip()
            break
    after = strip_progressive(clause)
    return (after, True) if after is not None else (clause, False)


def _room_nouns(target: str) -> list[str]:
    """A room's phrases: its `locations.yaml` name and `typed.rooms`' nouns for it."""
    from engine.social import places

    rooms = _block().get("rooms") or {}
    nouns = [str(n).casefold() for n in (rooms.get(target) or ()) if str(n).strip()]
    if target in rooms:
        nouns.append(places.label(target).casefold())
    return nouns


def match_offered(state: GameState, text: str) -> dict[str, Any]:
    """
    One legal `do` or room `travel` the line names, anchored at a clause start, else {} (A4 §3.1).

    Ambiguity is no match, so a clause naming an activity or a room counts toward "exactly one target" whether
    or not it is on offer here ("go to the kitchen and make breakfast" from the hall is two); only the one
    target left is then checked against the offer. A clause that is a room move ("step outside" in the lobby,
    "go to bed" in the hall) is read as the move alone; the room the player is in is never a room move.
    """
    from engine.social import world

    line = _normal(text)
    acted = len(line) > 2 and line.startswith("*") and line.endswith("*")
    line = line.strip("*").strip()
    cues = _cues()
    if not line or line.endswith("?"):
        return {}
    if any(convo.names_label(line, w) for k in ("modals", "negations", "shifts") for w in cues[k]):
        return {}
    phrases: list[tuple[str, str]] = []                           # (activity id, phrase)
    for row in world.activities():
        for p in [row.get("label", ""), *(row.get("say") or ())]:
            phrases.append((str(row.get("id") or ""), _normal(p)))
    rooms = {str(t): _room_nouns(str(t)) for t in (_block().get("rooms") or {}) if str(t) != state.location_id}
    found: set[tuple[str, str]] = set()
    for raw in _SPLIT.split(line):
        clause, progressive = _strip_lead(raw.strip(), cues["leads"], cues["progressive_leads"])
        if not clause:
            continue
        moved: set[str] = set()
        for move in cues["movement"]:
            for form in _forms(move, acted=acted, progressive=progressive):
                m = re.match(rf"{re.escape(form)}\s+(.+)$", clause)
                if not m:
                    continue
                for target, nouns in rooms.items():   # a room's phrase within three words of the verb
                    if any(re.match(rf"(?:\S+\s+){{0,3}}{re.escape(n)}(?!\w)", m.group(1)) for n in nouns):
                        moved.add(target)
        if moved:
            # Every room the clause names counts: "go to the hall or the dining room" is two.
            moved |= {t for t, nouns in rooms.items() if any(convo.names_label(clause, n) for n in nouns)}
            found |= {("travel", t) for t in moved}
            continue
        for rid, phrase in phrases:
            if _starts(clause, phrase, acted=acted, progressive=progressive):
                found.add(("do", rid))
    if len(found) != 1:
        return {}
    action, target = found.pop()
    if action == "do" and target in NEVER:
        return {}
    return _checked(state, {"action": action, "target": target, "typed": True})


def _checked(state: GameState, intent: dict[str, Any]) -> dict[str, Any]:
    """The intent only if the engine offers it NOW (`execute_intent`'s own test), else {}."""
    verb = intents.find_verb(intents.legal_intents(state), str(intent.get("action") or ""))
    if verb is None or (verb.targets and str(intent.get("target") or "") not in verb.targets):
        return {}
    return intent


def _job_label(state: GameState) -> str:
    from engine.social import population

    player = state.social.get("player") or {}
    job = str((player.get("attributes") or {}).get("job") or player.get("job") or "")
    if not job:
        return ""
    for row in population.table("jobs"):
        if isinstance(row, dict) and row.get("id") == job:
            return str(row.get("label") or "")
    return ""


def _yours_named(state: GameState, line: str, targets: Sequence[str]) -> Optional[str]:
    """A legal `tell_about:<t>` whose topic the line names: a hobby's or a running event's label, or the
    work topic by the player's job label, "my job" or "my work" (never a bare "work", W7)."""
    from engine.social import life, population

    hobbies = {str(r.get("id")): str(r.get("label") or "") for r in population.table("hobbies")
               if isinstance(r, dict)}
    news = {str(n["topic"]): str(n.get("label") or "") for n in life.player_news(state)}
    for target in targets:
        name, _, topic = target.partition(":")
        if name != "tell_about" or not topic:
            continue
        if topic == "work":
            words = [*WORK_PHRASES, _job_label(state)]
        elif topic in news:
            words = [news[topic]]
        else:
            words = [hobbies.get(topic, ""), topic.replace("_", " ")]
        if any(w and convo.names_label(line, w) for w in words):
            return target
    return None


def _theirs_named(state: GameState, pid: str, line: str, targets: Sequence[str]) -> Optional[str]:
    """A legal `ask_about:<t>` whose topic the line names (`convo._named_topics`), in the offer's order."""
    named = set(convo._named_topics(state, pid, line))
    return next((t for t in targets if t.partition(":")[0] == "ask_about" and t.partition(":")[2] in named), None)


def intent_for(state: GameState, text: str) -> dict[str, Any]:
    """
    What a typed world line becomes (A4 §3's order): an offered activity or room; in a scene, a topic it names
    (their topics first when the line ends in "?", yours first otherwise) or `talk`; else {}. Every result is a
    legal intent now, marked `typed: True`; nothing here writes.
    """
    hit = match_offered(state, text)
    if hit:
        return hit
    if not social.scene_open(state):
        return {}
    from engine.social import scene

    pid = str(scene.current(state).get("pid") or "")
    verb = intents.find_verb(intents.legal_intents(state), "scene")
    if not pid or verb is None:
        return {}
    line = _normal(text).strip("*").strip()
    if line:
        order = (_theirs_named, _yours_named) if line.endswith("?") else (_yours_named, _theirs_named)
        for finder in order:
            target = (finder(state, pid, line, verb.targets) if finder is _theirs_named
                      else finder(state, line, verb.targets))
            if target:
                return _checked(state, {"action": "scene", "target": target, "typed": True})
    if "talk" in verb.targets:
        return _checked(state, {"action": "scene", "target": "talk", "typed": True})
    return {}


def _reading_label(intent: dict[str, Any], result: dict[str, Any]) -> str:
    """The engine's words for what a typed line was read as (never the line itself)."""
    from engine.social import places, scene, world

    action, target = str(intent.get("action") or ""), str(intent.get("target") or "")
    if action == "do":
        row = next((r for r in world.activities() if r.get("id") == target), None) or {}
        return str(row.get("label") or target)
    if action == "travel":
        return f"go to {places.label(target)}"
    name, _, topic = target.partition(":")
    words = scene.MOVE_WORDS.get(name, name)
    return words.format(topic=scene._topic_label(name, topic) if topic else "something")


def mark(intent: Any, receipts: list[dict[str, Any]]) -> None:
    """A typed intent's receipts say so (A4 §3): `typed: true` on the receipt and its intent, and
    `typed_line`, the narrator's "The player said this; the engine read it as: <label> (<band>)."
    (`prompts.summarise_receipt` leads with it), on the first receipt that ran only, so a reading is never said
    twice. Nothing else on the receipt changes."""
    if not isinstance(intent, dict) or not intent.get("typed"):
        return
    lined = False                                     # the reading is said once, however many receipts
    for receipt in receipts:
        if not isinstance(receipt, dict) or receipt.get("refused"):
            continue
        result = receipt.get("result") if isinstance(receipt.get("result"), dict) else {}
        band = str(result.get("band") or "")
        receipt["typed"] = True
        if isinstance(receipt.get("intent"), dict):
            receipt["intent"]["typed"] = True
        if not lined:
            receipt["typed_line"] = READING.format(label=_reading_label(intent, result),
                                                   band=f" ({band})" if band else "")
            lined = True

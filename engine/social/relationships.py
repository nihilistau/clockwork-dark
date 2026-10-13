"""
Relationships (v0.22.0 spec §10): where the player stands with each person,
kept by the ENGINE. The model may later propose small, capped changes (a
voiced reply's `regard`, a §10.5 proposal); it never moves a stage or a
number directly (rule 1).

Per person (`state.social["people"][pid]`, spec §10.1; hidden from the
player but for the stage's words and a closeness band):

- **Regard** (`social_regard`): `warmth` and `trust` 0-100, moved per reply
  inside `regard.per_reply`, a gain multiplied by the archetype's
  `warmth_mult` and capped per in-game day (`regard.per_day_gain`, counted
  in `regard_day`/`regard_today`); a loss is never capped. An archetype's
  `warmth_cap_band` stops warmth growing past that band (a dry texter never
  passes "warming"). An `exact` move (an arc's `then`, an ask's cost) is the
  engine's own and skips the per-reply and per-day caps.
- **Interest** is the engine's alone (§10.2's last bullet): +`per_exchange`
  at each exchange, +`shared_hobby_mention` when the player names one of
  their hobbies, -`daily_decay` on a day with no contact, the left-on-read
  cost, and drift (a drifter's arc).
- **Mood** is the latest reply's, back to `neutral` after `decay_hours`.
- **Stages** move only through `social_stage` (`_e_social_stage`, the one
  writer: `test_every_stage_write_goes_through_social_stage`). `talking` is
  automatic at its gate's exchanges; `numbers` and `exclusive` come from an
  ask accepted (the player's, decided by `ask_decision`, or the person's
  proposal, answered by the player); `meeting` from a meet-up agreed
  (engine/social/meets.py); dating, friends and fling branch from meeting
  (`branch:`) after two good-or-better meet-ups (`meets_good`); `winding_down` from a turn or
  five cold days; `faded` after 21 days with no contact; `ended` by the
  player's `end` or an arc. Faded and ended re-open when the person writes
  again ("Reconnected"). No stage is an ending: `exclusive` keeps accruing.
- **Familiarity**: `exchanges` (each time the speaker changes, either way)
  and `contact_days` (in-game days on which either side wrote).
- **History** (`social_history`): engine lines only, bounded at
  `social.history_max`, the oldest folded into one "earlier" row.
- **Requests** (`social_request`): an ask by the player, answered by the
  person at their next read; a proposal of theirs, answered by the player
  (`answer`: yes, no or later).

Every number is relationships.yaml's (rule 10, measured at T26); every write
is a `social_*` effect or happens inside a `social_*` handler (rule 3).
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Optional

from engine import social
from engine.game import clock
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.social.kinds import recorded
from engine.game.intents import IntentVerb
from engine.game.rng import SOCIAL_BEHAVIOUR, stable_rng
from engine.game.state import GameState
from engine.social import apps, behaviour, events, population
from engine.social.intents import ArgSpec, phone_verb
from engine.social.kinds import STAGES as _STAGES
from engine.social.kinds import MEDIA_KINDS, Decision, stage_rank
from engine.social.payload import section
from engine.social.turn import cost_hours

#: Every stage, in the engine's order (spec §10.3). relationships.yaml's
#: `stages:` lists exactly these, in this order (check_data).
STAGES: tuple[str, ...] = _STAGES
#: The stages a relationship is still going at (spec §10.3's "any live").
LIVE_STAGES: tuple[str, ...] = (
    "matched", "talking", "numbers", "meeting", "dating", "friends", "fling", "exclusive", "winding_down",
)
#: Stages the person writing again re-opens (spec §10.3).
REOPENABLE: tuple[str, ...] = ("faded", "ended")
#: How a stage row's trigger may read.
TRIGGERS: tuple[str, ...] = ("automatic", "ask", "meet", "branch")
#: A gate's measures -> where each is kept in a person's slice.
GATE_PATHS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("warmth", ("warmth",)), ("trust", ("trust",)),
    ("exchanges", ("familiarity", "exchanges")), ("days", ("familiarity", "contact_days")),
    ("stage_days", ("stage_days",)), ("meets_good", ("meets_good",)),
)
#: What a stage row's `needs:` may ask of both sides.
NEEDS: tuple[str, ...] = ("both",)
#: Why the person said no to the player's ask (`ask_decision`): kept on the answered request as `why`.
ASK_WHYS: tuple[str, ...] = ("stage", "not yet", "draw")
#: The player's asks (spec §10.6) -> the stage an accepted one moves to.
ASK_STAGE: tuple[tuple[str, str], ...] = (("number", "numbers"), ("exclusive", "exclusive"))
#: The proposals this engine applies (spec §10.5): T9's three, T19's
#: offer_photo, offer_voice and offer_video, T22's invite_game and T24's ask_meet.
PROPOSALS: tuple[str, ...] = ("offer_number", "ask_exclusive", "cool_off", "offer_photo", "offer_voice", "offer_video",
                              "invite_game", "ask_meet")
#: A request for a game (`invite_game`, engine/social/games/): answered by the player, it moves no stage.
GAME_REQUEST = "game"
#: A media proposal -> the kind it offers (engine/social/media.py decides it).
PROPOSAL_MEDIA: tuple[tuple[str, str], ...] = (("offer_photo", "photo"), ("offer_voice", "voice"),
                                               ("offer_video", "video"))
#: A proposal that is a request to the player -> what it asks.
PROPOSAL_ASKS: tuple[tuple[str, str], ...] = (("offer_number", "number"), ("ask_exclusive", "exclusive"))
#: An arc's point (`at`) and start (`from`) measures the engine counts (spec §5.3).
ARC_POINTS: tuple[str, ...] = ("exchanges",)
ARC_STARTS: tuple[str, ...] = ("days_since_matched",)
#: What an arc's `then` or `each_day` may move, besides `then.stage`.
ARC_MOVES: tuple[str, ...] = ("warmth", "trust", "interest", "mood")
#: The `cold:` block's keys (spec §10.3 and its recovery ruling).
COLD_KEYS: tuple[str, ...] = ("warmth_below", "days", "recover_above", "recover_days")
#: Why someone is winding down: a cold spell recovers by itself, a turn only by a reconnect.
WOUND_BY_COLD = "cold"
WOUND_BY_TURN = "turn"
#: How the player may answer a request of theirs.
REPLIES: tuple[str, ...] = ("yes", "no", "later")
#: A request's states.
STATUSES: tuple[str, ...] = ("pending", "later", "yes", "no")
#: Every block relationships.yaml must carry.
BLOCKS: tuple[str, ...] = (
    "stages", "branch", "claims", "bands", "regard", "interest", "mood", "asks", "cold", "fade_days", "proposals",
)
#: What an ending drops from the person's queue: their reads, replies, initiations, double texts, a turn.
DROPPED_AT_END: tuple[str, ...] = ("read", "reply", "initiate", "double_text", "arc_beat")
#: The catalogue's refusal of a third ask of one kind in a day (spec §10.6).
GIVE_IT_A_DAY = "Give it a day"
#: The folded history row's kind (spec §10.4).
EARLIER = "earlier"
NEUTRAL = "neutral"


def _no(reason: str) -> dict[str, Any]:
    return {"ok": False, "error": reason}


def _clamp(value: float, low: float, high: float) -> int:
    return int(max(low, min(high, value)))


def _name(state: GameState, pid: str) -> str:
    try:
        return population.profile(state, pid).name
    except (ValueError, KeyError, IndexError):
        return pid


# -- the data (relationships.yaml, rule 10) ---------------------------------------------


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: relationships.yaml: {key}: {message}")


def _data() -> dict[str, Any]:
    return social.data("relationships")


def _block(name: str) -> Any:
    data = _data()
    if name not in data:
        raise _fault(name, "required (spec §10)")
    return data[name]


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _span(value: Any, key: str) -> None:
    if not (isinstance(value, list) and len(value) == 2 and all(_num(v) for v in value) and value[0] <= value[1]):
        raise _fault(key, f"must be [low, high], numbers with low <= high, not {value!r}")


def check_data(data: dict[str, Any]) -> dict[str, Any]:
    """relationships.yaml whole (spec §10); a ValueError naming the file and the key at fault."""
    missing = [name for name in BLOCKS if name not in data]
    if missing:
        raise _fault(missing[0], "required (spec §10)")
    stages = data["stages"]
    if not isinstance(stages, dict) or list(stages) != list(STAGES):
        raise _fault("stages", f"must list exactly {', '.join(STAGES)}, in that order")
    for name, row in stages.items():
        where = f"stages.{name}"
        if not isinstance(row, dict) or not isinstance(row.get("words"), str) or not row["words"]:
            raise _fault(f"{where}.words", "every stage needs the words the player sees")
        for source in row.get("from") or ():
            if source not in STAGES:
                raise _fault(f"{where}.from", f"{source!r} is no stage")
        if "trigger" in row and row["trigger"] not in TRIGGERS:
            raise _fault(f"{where}.trigger", f"must be one of {', '.join(TRIGGERS)}")
        if bool(row.get("from")) != ("trigger" in row):
            raise _fault(where, "a stage reached by a gate needs both from and trigger")
        gate = row.get("gate") or {}
        if not isinstance(gate, dict):
            raise _fault(f"{where}.gate", "must be a mapping of measure to minimum")
        known = dict(GATE_PATHS)
        for measure, value in gate.items():
            if measure not in known:
                raise _fault(f"{where}.gate", f"{measure!r} is not one of {', '.join(known)}")
            if not _num(value) or value < 0:
                raise _fault(f"{where}.gate.{measure}", f"must be a number, 0 or more, not {value!r}")
        for key, value in (row.get("needs") or {}).items():
            if key not in NEEDS or value not in ("long_term", "short_term", "friendship", "unsure"):
                raise _fault(f"{where}.needs", f"{key}: {value!r} is not a need ({', '.join(NEEDS)}: an intent)")
    branch = data["branch"]
    if not isinstance(branch, list) or not branch or "either" in (branch[-1] or {}):
        raise _fault("branch", "must be a list of {either?, stage} ending with a default row (no either)")
    for i, row in enumerate(branch):
        if not isinstance(row, dict) or (stages.get(row.get("stage")) or {}).get("trigger") != "branch":
            raise _fault(f"branch[{i}].stage", "must name a stage whose trigger is branch")
    claims = data["claims"]
    if not isinstance(claims, dict) or any(k not in STAGES or not isinstance(v, list) or not all(
            isinstance(p, str) and p for p in v) for k, v in claims.items()):
        raise _fault("claims", "must map stages to lists of phrases")
    bands = data["bands"]
    if not isinstance(bands, list) or not bands:
        raise _fault("bands", "must be a non-empty list of {name, warmth, contact_days}")
    last = -1.0
    for i, row in enumerate(bands):
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not _num(row.get("warmth")) \
                or not _num(row.get("contact_days")):
            raise _fault(f"bands[{i}]", "must be {name, warmth, contact_days}")
        if row["warmth"] <= last:
            raise _fault(f"bands[{i}].warmth", "must rise band by band")
        last = float(row["warmth"])
    regard = data["regard"]
    for key in ("warmth", "trust"):
        if not _num((regard.get("start") or {}).get(key)):
            raise _fault(f"regard.start.{key}", "required: a number 0-100")
        _span((regard.get("per_reply") or {}).get(key), f"regard.per_reply.{key}")
        if not _num((regard.get("per_day_gain") or {}).get(key)):
            raise _fault(f"regard.per_day_gain.{key}", "required: a number")
    for key in ("fight_warmth", "reconcile_warmth"):
        if not _num(regard.get(key)):
            raise _fault(f"regard.{key}", "required: a number")
    for key in ("warmth", "trust"):
        if not _num((regard.get("fallback") or {}).get(key)):
            raise _fault(f"regard.fallback.{key}", "required: a number (spec §10.2's fallback regard)")
    fallback_day = (regard.get("fallback") or {}).get("per_day")
    if fallback_day is not None:
        for key in ("warmth", "trust"):
            if not _num((fallback_day if isinstance(fallback_day, dict) else {}).get(key)):
                raise _fault(f"regard.fallback.per_day.{key}", "a number: what fallback replies may add a day")
    interest = data["interest"]
    for key in ("start", "per_exchange", "shared_hobby_mention", "daily_decay"):
        if not _num(interest.get(key)):
            raise _fault(f"interest.{key}", "required: a number")
    lor = interest.get("left_on_read") or {}
    if not _num(lor.get("grace_hours")) or not _num(lor.get("max")):
        raise _fault("interest.left_on_read", "required: {grace_hours, max}")
    mood = data["mood"]
    values = mood.get("values")
    if not isinstance(values, list) or NEUTRAL not in values:
        raise _fault("mood.values", f"must be a list holding {NEUTRAL!r}")
    if not _num(mood.get("decay_hours")):
        raise _fault("mood.decay_hours", "required: hours")
    _span(mood.get("media_mult"), "mood.media_mult")
    asks = data["asks"]
    for key in ("per_day", "repeat_mult", "repeat_warmth"):
        if not _num(asks.get(key)):
            raise _fault(f"asks.{key}", "required: a number")
    down = asks.get("turned_down") or {}
    if not _num(down.get("warmth")) or down.get("mood") not in values:
        raise _fault("asks.turned_down", "required: {warmth, mood (a mood value)}")
    cold = data["cold"]
    if not isinstance(cold, dict) or not all(_num(cold.get(k)) for k in COLD_KEYS):
        raise _fault("cold", f"required: {{{', '.join(COLD_KEYS)}}}")
    if cold["recover_above"] <= cold["warmth_below"]:
        raise _fault("cold.recover_above", "must be above warmth_below (else a cold spell recovers while cold)")
    if not _num(data["fade_days"]):
        raise _fault("fade_days", "required: days")
    proposals = data["proposals"]
    if not isinstance(proposals, dict):
        raise _fault("proposals", "must be a mapping of proposal id to {stage, gate}")
    for name, row in proposals.items():
        if name not in PROPOSALS:
            raise _fault(f"proposals.{name}", f"is not a proposal this engine applies ({', '.join(PROPOSALS)})")
        if not isinstance(row, dict) or (row.get("stage") != "live" and row.get("stage") not in STAGES):
            raise _fault(f"proposals.{name}.stage", "must be a stage id or live")
        if row.get("gate") is not None and row["gate"] not in STAGES:
            raise _fault(f"proposals.{name}.gate", f"{row['gate']!r} is no stage")
    return data


def check_cap_bands(behaviours: dict[str, Any], data: dict[str, Any]) -> None:
    """Every archetype's `warmth_cap_band` names a relationships.yaml band (at load, not only in the
    validator: an unknown band would otherwise raise inside `social_regard` mid-advance)."""
    bands = {str(row.get("name")) for row in data.get("bands") or () if isinstance(row, dict)}
    rows = behaviours.get("archetypes") if isinstance(behaviours.get("archetypes"), dict) else {}
    for name, row in rows.items():
        band_name = row.get("warmth_cap_band") if isinstance(row, dict) else None
        if band_name is not None and band_name not in bands:
            raise ValueError(f"social: behaviours.yaml: archetypes.{name}.warmth_cap_band: "
                             f"{band_name!r} is no relationships.yaml band")


# -- stages, gates, bands -----------------------------------------------------------------


def _stage_row(name: str) -> dict[str, Any]:
    rows = _block("stages")
    if name not in rows:
        raise _fault(f"stages.{name}", "no such stage")
    return rows[name]


def stage_index(name: str) -> int:
    return STAGES.index(name)


def stage_words(name: str) -> str:
    """What the player sees for a stage ("Swapped numbers"): never a number, never "ghosted"."""
    return str(_stage_row(name)["words"])


def gate_spec(stage: str) -> dict[str, Any]:
    """The stage's gate row (warmth, trust, exchanges, days, stage_days, meets_good): each a minimum."""
    return dict(_stage_row(stage).get("gate") or {})


def _person(state: GameState, pid: str) -> dict[str, Any]:
    """READ ONLY: a person's dynamic slice, {} when there is none."""
    return (state.social.get("people") or {}).get(pid) or {}


def measure(person_state: dict[str, Any], name: str) -> float:
    """One gate measure from a person's slice (0 when not yet kept)."""
    value: Any = person_state
    for key in dict(GATE_PATHS)[name]:
        value = value.get(key) if isinstance(value, dict) else None
    return float(value or 0)


def gate_holds(state: GameState, pid: str, stage: str) -> bool:
    """Every measure of `stage`'s gate holds for `pid` now (where they are is `can_reach`'s)."""
    person_state = _person(state, pid)
    return all(measure(person_state, name) >= float(minimum) for name, minimum in gate_spec(stage).items())


def needs_hold(state: GameState, pid: str, stage: str) -> bool:
    """The stage row's `needs:` (`both: long_term`): what both sides want."""
    needs = _stage_row(stage).get("needs") or {}
    if not needs:
        return True
    player = str((state.social.get("player") or {}).get("looking_for") or "")
    theirs = population.profile(state, pid).intent
    return all(player == value and theirs == value for key, value in needs.items() if key == "both")


def can_reach(state: GameState, pid: str, stage: str) -> bool:
    """From where `pid` is now: the stage's `from`, its gate and its needs."""
    row = _stage_row(stage)
    return (_person(state, pid).get("stage") in (row.get("from") or ())
            and gate_holds(state, pid, stage) and needs_hold(state, pid, stage))


def _bands() -> list[dict[str, Any]]:
    return list(_block("bands"))


def band(person_state: dict[str, Any]) -> str:
    """The closeness band (`new|warming|close|very close|inseparable`) from warmth and contact days."""
    warmth = float(person_state.get("warmth", 0) or 0)
    days = measure(person_state, "days")
    name = _bands()[0]["name"]
    for row in _bands():
        if warmth >= float(row["warmth"]) and days >= float(row["contact_days"]):
            name = row["name"]
    return str(name)


def _band_cap(name: Optional[str]) -> int:
    """The highest warmth inside band `name` (one below the next band's); 100 for none or the last."""
    if not name:
        return 100
    rows = _bands()
    names = [str(row["name"]) for row in rows]
    if name not in names:
        raise ValueError(f"social: behaviours.yaml: warmth_cap_band: {name!r} is no relationships.yaml band")
    i = names.index(name)
    return 100 if i + 1 >= len(rows) else int(rows[i + 1]["warmth"]) - 1


def live(person_state: dict[str, Any]) -> bool:
    return person_state.get("stage") in LIVE_STAGES


def mood_now(person_state: dict[str, Any], now: float) -> str:
    """Their mood at in-game hour `now`: `neutral` once `mood_until` has passed (spec §10.7), whatever the
    morning step has written yet. The reader for the voice prompt (T13) and the media multiplier (T19)."""
    until = person_state.get("mood_until")
    if until is not None and float(now) >= float(until):
        return NEUTRAL
    return str(person_state.get("mood") or NEUTRAL)


# -- small writers (inside a social_* handler only: rule 3) ------------------------------------


def touch(person_state: dict[str, Any]) -> None:
    """Every write to a person bumps `rev` (spec §10.1; T14's commit logs it)."""
    person_state["rev"] = int(person_state.get("rev", 0)) + 1


def _seed_regard(person_state: dict[str, Any]) -> None:
    """Where regard starts, from data (F20): warmth, trust, interest, mood, familiarity."""
    start = _block("regard")["start"]
    person_state.setdefault("warmth", int(start["warmth"]))
    person_state.setdefault("trust", int(start["trust"]))
    person_state.setdefault("interest", int(_block("interest")["start"]))
    person_state.setdefault("mood", NEUTRAL)
    person_state.setdefault("familiarity", {"exchanges": 0, "contact_days": 0})


def ensure_arc_point(state: GameState, pid: str, person_state: dict[str, Any]) -> None:
    """
    The person's arc point (spec §5.3), drawn once on SOCIAL_BEHAVIOUR (a
    stable key, so no other draw of theirs shifts): a whole number inside
    the arc's `at` or `from` span. None when their archetype has no arc.
    """
    if "arc_point" in person_state:
        return
    arc = behaviour.archetype(population.profile(state, pid).archetype).arc
    if arc is None:
        person_state["arc_point"] = None
        return
    spec = behaviour.arc_spec(arc)
    (_measure, (low, high)), = (spec.get("at") or spec.get("from")).items()
    rng = stable_rng(state.rng_seed, f"{SOCIAL_BEHAVIOUR}:{pid}:arc")
    person_state["arc_point"] = rng.randint(int(low), int(high))


# -- the effects ------------------------------------------------------------------------


@effect_kind("social_regard")
@recorded
def _e_regard(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: warmth, trust, mood and interest (spec §10.2). A model's
    proposal is clamped per reply, multiplied by the archetype and capped per
    in-game day; `exact: true` (the engine's own move) skips those three. A
    gain never passes the archetype's band cap; a loss is never capped.
    `fallback: true` (an engine-authored fallback reply's regard, spec §10.2's
    ruling) is capped again by `regard.fallback.per_day` (v0.22.0 T26), so a
    run with no model progresses, more slowly than one with a working model.
    """
    if not state.social:
        return {"type": "social_regard", "ok": False, "text": "no social slice"}
    pid = str(effect["pid"])
    person_state = state.social.setdefault("people", {}).setdefault(pid, {})
    _seed_regard(person_state)
    person = population.profile(state, pid)
    arch = behaviour.archetype(person.archetype)
    rules = _block("regard")
    day = int(effect.get("day", state.world_day))
    at = float(effect.get("at", state.world_clock_hours))
    if person_state.get("regard_day") != day:
        person_state["regard_day"] = day
        person_state["regard_today"] = {"warmth": 0, "trust": 0, "loss": 0}
    today = person_state["regard_today"]
    warmth = int(effect.get("warmth", 0))
    trust = int(effect.get("trust", 0))
    if not effect.get("exact"):
        w_lo, w_hi = rules["per_reply"]["warmth"]
        t_lo, t_hi = rules["per_reply"]["trust"]
        warmth = _clamp(warmth, w_lo, w_hi)
        trust = _clamp(trust, t_lo, t_hi)
        if warmth > 0:
            warmth = round(warmth * arch.warmth_mult)
            warmth = min(warmth, max(0, int(rules["per_day_gain"]["warmth"]) - today["warmth"]))
        if trust > 0:
            trust = min(trust, max(0, int(rules["per_day_gain"]["trust"]) - today["trust"]))
        fallback_day = (rules.get("fallback") or {}).get("per_day")
        if effect.get("fallback") and isinstance(fallback_day, dict):
            warmth = min(warmth, max(0, int(fallback_day["warmth"]) - int(today.get("fallback_warmth", 0))))
            trust = min(trust, max(0, int(fallback_day["trust"]) - int(today.get("fallback_trust", 0))))
            today["fallback_warmth"] = int(today.get("fallback_warmth", 0)) + max(0, warmth)
            today["fallback_trust"] = int(today.get("fallback_trust", 0)) + max(0, trust)
        today["warmth"] += max(0, warmth)
        today["trust"] += max(0, trust)
    if not effect.get("exact"):                       # a turn's own loss is the turn, not a fight (one event)
        today["loss"] = int(today.get("loss", 0)) + min(0, warmth)
    cap = _band_cap(arch.warmth_cap_band)            # dry texter never passes "warming" (data)
    old = int(person_state["warmth"])
    new = old + warmth
    if warmth > 0:
        new = min(new, max(old, cap))                # a cap stops growth; it never pulls warmth down
    person_state["warmth"] = _clamp(new, 0, 100)
    person_state["trust"] = _clamp(int(person_state["trust"]) + trust, 0, 100)
    if "interest" in effect:                          # the engine's own interest moves (§10.2's last bullet)
        person_state["interest"] = _clamp(int(person_state["interest"]) + int(effect["interest"]), 0, 100)
    mood = effect.get("mood")
    moods = _block("mood")
    if mood in moods["values"]:
        person_state["mood"] = mood
        person_state["mood_until"] = None if mood == NEUTRAL else at + float(moods["decay_hours"])
    touch(person_state)
    _maybe_record_fight(state, pid, person_state, day, at)
    return {"type": "social_regard", "ok": True, "text": "regard", "applied": {"warmth": warmth, "trust": trust}}


def _maybe_record_fight(state: GameState, pid: str, person_state: dict[str, Any], day: int, at: float) -> None:
    """A day's warmth loss at `fight_warmth` or worse is a fight; a day's gain of `reconcile_warmth` after one, making up."""
    rules = _block("regard")
    today = person_state["regard_today"]
    if int(today.get("loss", 0)) <= int(rules["fight_warmth"]) and not today.get("fight"):
        today["fight"] = True
        person_state["fight_day"] = day
        add_history(state, pid, "fight", "A falling-out", at=at)
    elif (person_state.get("fight_day") is not None and day > int(person_state["fight_day"])
          and int(today.get("warmth", 0)) >= int(rules["reconcile_warmth"])):
        person_state["fight_day"] = None
        add_history(state, pid, "reconciled", "Made up", at=at)


@effect_kind("social_stage")
@recorded
def _e_social_stage(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: a stage transition, the ONE writer of a person's `stage`
    (Plan decision 17, pinned by an AST scan). Whether the move is allowed is
    the caller's (`can_reach`, an arc, a threshold); this writes it, its
    `stage_since`, and a history row (`history: false` when the caller wrote
    its own).
    """
    if not state.social:
        return {"type": "social_stage", "ok": False, "text": "no social slice"}
    pid, stage = str(effect.get("pid") or ""), str(effect.get("stage") or "")
    if not pid or stage not in STAGES:
        return {"type": "social_stage", "ok": False, "text": f"{stage!r} is no stage"}
    person_state = state.social.setdefault("people", {}).setdefault(pid, {})
    old = person_state.get("stage")
    if old == stage:
        return {"type": "social_stage", "ok": False, "text": f"{pid} is already {stage}"}
    at = float(effect.get("at", state.world_clock_hours))
    _seed_regard(person_state)
    if stage in REOPENABLE and old in LIVE_STAGES:
        person_state["stage_before"] = old
    if stage == "winding_down" and old in LIVE_STAGES:
        person_state["wound_from"] = old
        person_state["wound_by"] = str(effect.get("by") or "")
    person_state["stage"] = stage
    person_state["stage_since"] = at
    person_state["stage_days"] = 0
    person_state["cold_days"] = 0
    person_state["warm_days"] = 0
    if stage == "ended":
        person_state["ended_by"] = str(effect.get("by") or "")
    if effect.get("drop_queue"):
        events.cancel(state, pid, set(DROPPED_AT_END))
    if stage == "ended":
        from engine.social import meets   # lazily: meets imports this module

        meets.call_off(state, pid, at)              # their plans called off at no cost (T24 review M7)
    touch(person_state)
    if effect.get("history", True):
        add_history(state, pid, str(effect.get("kind") or stage), str(effect.get("line") or stage_words(stage)), at=at)
    # Saved at once (spec §17.2): an ending as `ended`, any other move as `stage`.
    return {"type": "social_stage", "ok": True, "text": f"{pid}: {old} -> {stage}", "from": old, "stage": stage,
            "save_reason": "ended" if stage == "ended" else "stage"}


def set_stage(state: GameState, pid: str, stage: str, *, at: Optional[float] = None, **extra: Any) -> dict[str, Any]:
    """Move `pid` to `stage` through `social_stage` (the caller has decided it may)."""
    effect: dict[str, Any] = {"type": "social_stage", "pid": pid, "stage": stage, **extra}
    if at is not None:
        effect["at"] = float(at)
    return apply_effect(state, effect)


@effect_kind("social_history")
@recorded
def _e_history(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """Engine-only: one history row (spec §10.4), bounded at `social.history_max`, the oldest folded."""
    if not state.social:
        return {"type": "social_history", "ok": False, "text": "no social slice"}
    pid = str(effect["pid"])
    person_state = state.social.setdefault("people", {}).setdefault(pid, {})
    at = float(effect.get("at", state.world_clock_hours))
    rows = person_state.setdefault("history", [])
    rows.append({"at": at, "day": int(at // 24) + 1, "kind": str(effect["kind"]), "text": str(effect["line"])})
    limit = max(2, int(social.setting("history_max", 60)))
    while len(rows) > limit:
        first = rows[0]
        if first["kind"] != EARLIER:
            rows[0] = {"at": first["at"], "day": first["day"], "kind": EARLIER, "count": 1, "text": ""}
        else:
            del rows[1]
            first["count"] = int(first.get("count", 1)) + 1
        n = int(rows[0]["count"])
        rows[0]["text"] = f"{n} earlier moment" + ("" if n == 1 else "s")
    touch(person_state)
    return {"type": "social_history", "ok": True, "text": f"{pid}: {effect['kind']}"}


def add_history(state: GameState, pid: str, kind: str, line: str, *, at: Optional[float] = None) -> None:
    """One engine line on the person's card (through `social_history`)."""
    effect: dict[str, Any] = {"type": "social_history", "pid": pid, "kind": kind, "line": line}
    if at is not None:
        effect["at"] = float(at)
    apply_effect(state, effect)


@effect_kind("social_request")
@recorded
def _e_request(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: a request (spec §10.5, §10.6). `op: create` (`from`: player
    or them, `what`, `thread_id`, `mult`), `op: again` (the player asking
    again while theirs is pending: the odds multiplied), `op: answer`
    (`status`), `op: forget` (an answered request leaves state: `forget_answered`,
    the save's bound). A player's create or again counts one ask of that kind today.
    """
    if not state.social:
        return {"type": "social_request", "ok": False, "text": "no social slice"}
    requests = state.social.setdefault("requests", {})
    op = str(effect.get("op") or "create")
    at = float(effect.get("at", state.world_clock_hours))
    if op == "create":
        counters = state.social.setdefault("counters", {})
        counters["request"] = int(counters.get("request", 0)) + 1
        rid = f"r{counters['request']}"
        row = {"id": rid, "pid": str(effect["pid"]), "from": str(effect["from"]), "what": str(effect["what"]),
               "status": "pending", "at": at, "thread_id": str(effect.get("thread_id") or ""),
               "mult": float(effect.get("mult", 1.0)), "asks": 1}
        if effect.get("game"):
            row["game"] = str(effect["game"])            # an `invite_game` request: which game (T22)
        if effect.get("venue"):                          # an `ask_meet` request: the engine's pick (T24)
            row.update(venue=str(effect["venue"]), day=int(effect["day"]), slot=str(effect["slot"]))
        requests[rid] = row
    else:
        row = requests.get(str(effect.get("request_id") or ""))
        if row is None:
            return {"type": "social_request", "ok": False, "text": f"no request {effect.get('request_id')!r}"}
        if op == "forget":
            if row["status"] in OPEN_STATUSES:
                return {"type": "social_request", "ok": False, "text": f"{row['id']} is still open"}
            del requests[row["id"]]
            return {"type": "social_request", "ok": True, "text": f"{row['id']} forgotten"}
        if op == "again":
            row["mult"] = float(row.get("mult", 1.0)) * float(effect.get("mult", 1.0))
            row["asks"] = int(row.get("asks", 1)) + 1
        elif op == "answer":
            if effect.get("status") not in STATUSES:
                return {"type": "social_request", "ok": False, "text": f"{effect.get('status')!r} is no answer"}
            why = str(effect.get("why") or "")
            if why and why not in ASK_WHYS:
                return {"type": "social_request", "ok": False, "text": f"{why!r} is no reason"}
            row["status"] = str(effect["status"])
            row["answered_at"] = at
            if why:
                row["why"] = why                         # why a no: the voice and the phone say it (owner bug)
        else:
            return {"type": "social_request", "ok": False, "text": f"{op!r} is no request op"}
    person_state = state.social.setdefault("people", {}).setdefault(row["pid"], {})
    if row["from"] == "player" and op in ("create", "again"):
        asked = person_state.get("asks_today")
        if not isinstance(asked, dict) or asked.get("day") != state.world_day:
            asked = person_state["asks_today"] = {"day": state.world_day}
        asked[row["what"]] = int(asked.get(row["what"], 0)) + 1
    touch(person_state)
    return {"type": "social_request", "ok": True, "text": f"{row['id']} {op}", "request": dict(row)}


#: A request still waiting for an answer: never forgotten (`forget_answered`).
OPEN_STATUSES: tuple[str, ...] = ("pending", "later")


def forget_answered(state: GameState) -> int:
    """
    Bounded state (spec §17.2, v0.22.0 T26 fix round 1): answered requests
    past the newest `social.requests_kept` leave state through `social_request`
    `op: forget` (rule 3), oldest first. A request still open, or one a queued
    event or a due message names (its answer is still to be written), stays.
    Nothing reads an answered request again: the asks are counted on the
    person (`asks_today`), and every gate reads the open ones. How many left.
    """
    slice_ = state.social or {}
    requests = slice_.get("requests") or {}
    named = {str(e.get("request_id") or "") for e in slice_.get("queue") or []}
    named |= {str((m.get("decision") or {}).get("request_id") or "")
              for t in (slice_.get("threads") or {}).values() for m in t.get("messages") or []
              if m.get("voiced") is False}
    answered = sorted((r for r in requests.values() if r["status"] not in OPEN_STATUSES and r["id"] not in named),
                      key=lambda r: int(str(r["id"])[1:] or 0))
    keep = max(0, int(social.setting("requests_kept", 30)))
    gone = 0
    for row in answered[:max(0, len(answered) - keep)]:
        gone += bool(apply_effect(state, {"type": "social_request", "op": "forget", "request_id": row["id"]}).get("ok"))
    return gone


# -- familiarity, exchanges and what follows them -----------------------------------------


def _hobby_named(state: GameState, pid: str, text: str) -> bool:
    """The player's words name one of the person's hobbies (its label or its id), whole words."""
    words = text.lower()
    labels = {str(row.get("id")): str(row.get("label") or "") for row in population.table("hobbies")
              if isinstance(row, dict)}
    for hobby in population.profile(state, pid).hobbies:
        for name in (labels.get(hobby, ""), hobby.replace("_", " ")):
            name = name.lower().removeprefix("the ").strip()
            if name and re.search(rf"\b{re.escape(name)}\b", words):
                return True
    return False


def note_message(state: GameState, pid: str, sender: str, at: float, bubbles: Any = ()) -> None:
    """
    A message between the player and `pid` landed (called inside
    `social_message`'s handler): contact days, the first message's history
    row, an exchange when the speaker changed, and a named hobby's interest.
    """
    person_state = state.social.setdefault("people", {}).setdefault(pid, {})
    _seed_regard(person_state)
    familiarity = person_state["familiarity"]
    rules = _block("interest")
    if "last_speaker" not in familiarity:
        add_history(state, pid, "first_message", "First message", at=at)
    day = int(at // 24)
    if familiarity.get("contact_day") != day:
        familiarity["contact_day"] = day
        familiarity["contact_days"] = int(familiarity.get("contact_days", 0)) + 1
    exchanged = familiarity.get("last_speaker") not in (None, sender)
    familiarity["last_speaker"] = sender
    if exchanged:
        familiarity["exchanges"] = int(familiarity.get("exchanges", 0)) + 1
    touch(person_state)
    if sender == "player" and _hobby_named(state, pid, " ".join(str(b) for b in bubbles or ())):
        apply_effect(state, {"type": "social_regard", "pid": pid, "interest": int(rules["shared_hobby_mention"]),
                             "at": at})
    if exchanged:
        apply_effect(state, {"type": "social_regard", "pid": pid, "interest": int(rules["per_exchange"]), "at": at})
        after_exchange(state, pid, sender, at)


def add_familiarity(state: GameState, pid: str, exchanges: int, *, at: float) -> None:
    """
    A shared activity counted as `exchanges` exchanges (a finished game, spec
    §21.1), then the automatic stages. Called only inside a `social_*`
    handler (the `social_game` effect's), so the write is that effect's
    (rule 3).
    """
    person_state = state.social.setdefault("people", {}).setdefault(pid, {})
    _seed_regard(person_state)
    familiarity = person_state["familiarity"]
    familiarity["exchanges"] = int(familiarity.get("exchanges", 0)) + max(0, int(exchanges))
    touch(person_state)
    advance_stage(state, pid, at=at)


def after_exchange(state: GameState, pid: str, sender: str, at: float) -> None:
    """After an exchange: a faded or ended relationship re-opened by THEM, the automatic stages, a turn."""
    person_state = _person(state, pid)
    if sender == pid and person_state.get("stage") in REOPENABLE:
        back = str(person_state.get("stage_before") or "talking")
        if back == "winding_down":                    # a reconnect lifts a winding down, a turn's included
            back = str(person_state.get("wound_from") or "talking")
        set_stage(state, pid, back, at=at, kind="reconnected", line="Reconnected")
    advance_stage(state, pid, at=at)
    _maybe_turn(state, pid, at)


def advance_stage(state: GameState, pid: str, *, at: Optional[float] = None) -> Optional[str]:
    """The automatic transitions from where `pid` is (talking; the meeting branch, after meet-ups): the new stage."""
    stage = _person(state, pid).get("stage")
    rows = _block("stages")
    for name, row in rows.items():
        if row.get("trigger") == "automatic" and stage in (row.get("from") or ()) and can_reach(state, pid, name):
            set_stage(state, pid, name, at=at)
            return name
    if any(row.get("trigger") == "branch" and stage in (row.get("from") or ()) for row in rows.values()):
        chosen = branch_for(state, pid)
        if can_reach(state, pid, chosen):
            set_stage(state, pid, chosen, at=at)
            return chosen
    return None


def branch_for(state: GameState, pid: str) -> str:
    """Dating, friends or fling by both sides' intents (relationships.yaml `branch:`, first match)."""
    intents = {str((state.social.get("player") or {}).get("looking_for") or ""), population.profile(state, pid).intent}
    for row in _block("branch"):
        if "either" not in row or row["either"] in intents:
            return str(row["stage"])
    raise _fault("branch", "has no default row")


def _arc_of(state: GameState, pid: str) -> Optional[str]:
    return behaviour.archetype(population.profile(state, pid).archetype).arc


def _maybe_turn(state: GameState, pid: str, at: float) -> None:
    """A turn (an arc with `at: {exchanges: ...}`) is queued as an `arc_beat` once their exchanges reach its point."""
    person_state = state.social["people"][pid]
    arc = _arc_of(state, pid)
    if arc is None or person_state.get("arc_fired") or not live(person_state):
        return
    ensure_arc_point(state, pid, person_state)
    spec = behaviour.arc_spec(arc)
    point = person_state.get("arc_point")
    if "at" not in spec or point is None:
        return
    (measure_name, _span_), = spec["at"].items()
    if measure(person_state, measure_name) >= float(point):
        person_state["arc_fired"] = True
        events.push(state, at, pid, "arc_beat", arc=arc)


@events.handles("arc_beat")
def _on_arc_beat(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """
    A turn (spec §5.3): its canon row's text (through `social_memory`), a history line, its `then` (a stage
    through `social_stage`, regard through `social_regard`), and a due
    message from them carrying the reveal (`Decision.reveal`), which the
    voice is told to say.
    """
    pid = str(event["pid"])
    person_state = state.social["people"].setdefault(pid, {})
    if apps.gone(state, pid) or not live(person_state):
        return {"ok": False, "why": "no longer live"}
    at = float(event["at"])
    beat = behaviour.arc_spec(str(event["arc"])).get("beat") or {}
    reveal = str(beat.get("reveal") or "")
    if reveal:
        from engine.social import memory   # lazily: memory's view reads messaging, which imports this module

        memory.add_canon(state, pid, [behaviour.canon_text(reveal)])   # the row's prose (spec §12.1)
    touch(person_state)
    add_history(state, pid, "turn", str(beat.get("history") or "Something changed"), at=at)
    then = dict(beat.get("then") or {})
    target = then.pop("stage", None)
    if target and person_state.get("stage") != target:
        set_stage(state, pid, str(target), at=at, history=False, by=WOUND_BY_TURN)
    if person_state.get("stage") == "winding_down":
        person_state["wound_by"] = WOUND_BY_TURN     # a turn on someone already cooling: no recovery by warming
    if then:
        apply_effect(state, {"type": "social_regard", "pid": pid, "exact": True, "at": at, **then})
    instruction = str(beat.get("instruction") or "")
    from engine.social import messaging   # lazily: messaging imports this module

    tid = messaging.thread_for(state, pid)
    if instruction and tid:
        decision = Decision(situation=instruction, reveal=reveal)
        events.push(state, at, pid, "reply", thread_id=tid, decision=dataclasses.asdict(decision))
    return {"ok": True, "turn": str(event["arc"])}


# -- left on read (spec §9.4) ------------------------------------------------------------


def settle_left_on_read(state: GameState, pid: str, at: float, *, clear: bool = False) -> None:
    """
    The interest a long left-on-read costs, up to `at` (inside a handler):
    the archetype's `left_on_read_sensitivity` per hour past the grace, at
    most `interest.left_on_read.max` in all, charged once. `clear` ends it.
    """
    person_state = state.social.setdefault("people", {}).setdefault(pid, {})
    since = person_state.get("left_on_read_since")
    if since is None:
        return
    rules = _block("interest")["left_on_read"]
    sensitivity = behaviour.archetype(population.profile(state, pid).archetype).left_on_read_sensitivity
    hours = max(0.0, float(at) - float(since) - float(rules["grace_hours"]))
    owed = int(round(min(float(rules["max"]), sensitivity * hours)))
    paid = int(person_state.get("left_on_read_paid", 0))
    if owed > paid:
        person_state["left_on_read_paid"] = owed
        apply_effect(state, {"type": "social_regard", "pid": pid, "interest": -(owed - paid), "at": at})
    if clear:
        person_state["left_on_read_since"] = None
        person_state["left_on_read_paid"] = 0
    touch(person_state)


# -- the daily steps (spec §9.1: drift, mood decay; §10.3: cold and faded) -------------------


def _last_contact(person_state: dict[str, Any]) -> Optional[float]:
    marks = [person_state.get(k) for k in ("last_player_at", "last_them_at", "matched_at")]
    return max((float(v) for v in marks if v is not None), default=None)


def _daily(state: GameState) -> None:
    """Each person, once a morning: mood back to neutral, faded, interest decay, drift, the cold count."""
    day_at = events.daily_at(state)
    people = state.social.get("people") or {}
    fade_hours = float(_block("fade_days")) * 24.0
    cold = _block("cold")
    decay = int(_block("interest")["daily_decay"])
    for pid in sorted(people):
        person_state = people[pid]
        if person_state.get("mood_until") is not None and day_at >= float(person_state["mood_until"]):
            person_state["mood"], person_state["mood_until"] = NEUTRAL, None
            touch(person_state)
        if not live(person_state) or apps.gone(state, pid):
            continue
        last = _last_contact(person_state)
        if last is not None and day_at - last >= fade_hours:
            set_stage(state, pid, "faded", at=day_at)
            continue
        person_state["stage_days"] = int(person_state.get("stage_days", 0)) + 1
        touch(person_state)
        if last is None or day_at - last >= 24.0:
            apply_effect(state, {"type": "social_regard", "pid": pid, "interest": -decay, "at": day_at})
        _drift(state, pid, person_state, day_at)
        warmth = float(person_state.get("warmth", 100))
        if warmth < float(cold["warmth_below"]):
            person_state["cold_days"] = int(person_state.get("cold_days", 0)) + 1
            if person_state["cold_days"] >= int(cold["days"]) and person_state.get("stage") != "winding_down":
                set_stage(state, pid, "winding_down", at=day_at, kind="cooled", line="Things cooled off",
                          by=WOUND_BY_COLD)
        else:
            person_state["cold_days"] = 0
        _maybe_recover(state, pid, person_state, warmth, day_at)


def _maybe_recover(state: GameState, pid: str, person_state: dict[str, Any], warmth: float, day_at: float) -> None:
    """
    A cold spell's winding down that warms to `cold.recover_above` for
    `cold.recover_days` mornings goes back to the stage it left (spec
    §10.3's ruling), through `social_stage`. A turn's does not: only a
    reconnect lifts that.
    """
    if person_state.get("stage") != "winding_down" or person_state.get("wound_by") != WOUND_BY_COLD:
        return
    cold = _block("cold")
    if warmth < float(cold["recover_above"]):
        person_state["warm_days"] = 0
        return
    person_state["warm_days"] = int(person_state.get("warm_days", 0)) + 1
    if person_state["warm_days"] >= int(cold["recover_days"]):
        set_stage(state, pid, str(person_state.get("wound_from") or "talking"), at=day_at, kind="recovered",
                  line="Warmed up again")


def _drift(state: GameState, pid: str, person_state: dict[str, Any], day_at: float) -> None:
    """A drift arc (`from: {days_since_matched: ...}`): its `each_day` from its point on (the drifter's fade)."""
    arc = _arc_of(state, pid)
    if arc is None:
        return
    spec = behaviour.arc_spec(arc)
    if "from" not in spec or person_state.get("matched_at") is None:
        return
    ensure_arc_point(state, pid, person_state)
    point = person_state.get("arc_point")
    if point is None or (day_at - float(person_state["matched_at"])) / 24.0 < float(point):
        return
    apply_effect(state, {"type": "social_regard", "pid": pid, "exact": True, "at": day_at,
                         **dict(spec.get("each_day") or {})})


if _daily not in events.daily_hooks:
    events.daily_hooks.append(_daily)


# -- the player's asks (spec §9.5, §10.6) ---------------------------------------------------


def _ask_stage(what: str) -> str:
    return dict(ASK_STAGE)[what]


def ask_kind_for(stage: Any) -> Optional[str]:
    """What the player may ask someone at `stage` (number at talking, exclusive at dating), or None."""
    for what, target in ASK_STAGE:
        if stage in (_stage_row(target).get("from") or ()):
            return what
    return None


def asks_today(state: GameState, pid: str, what: str) -> int:
    asked = _person(state, pid).get("asks_today")
    if not isinstance(asked, dict) or asked.get("day") != state.world_day:
        return 0
    return int(asked.get(what, 0))


def ask_stage_refusal(state: GameState, pid: str, what: str) -> str:
    """Why `pid`'s stage does not offer this ask ("You already have Kai's number."), or ""."""
    name = _name(state, pid)
    stage = _person(state, pid).get("stage")
    target = _ask_stage(what)
    sources = _stage_row(target).get("from") or ()
    if stage_rank(stage) >= stage_rank(target):
        return f"You already have {name}'s number." if what == "number" else "You're already together."
    if stage not in sources:
        early = 0 <= stage_rank(stage) < min(stage_rank(s) for s in sources)
        asking = "for their number" if what == "number" else "to be exclusive"
        return f"It's too soon to ask {name} {asking}." if early else f"It isn't the moment to ask {name} {asking}."
    return ""


def ask_refusal(state: GameState, pid: str, what: str) -> str:
    """
    The catalogue's refusal of an ask past `asks.per_day` of its kind today,
    only while their stage still offers that ask ("" otherwise, so a truer
    refusal -- "You already have their number." -- wins).
    """
    if ask_kind_for(_person(state, pid).get("stage")) != what:
        return ""
    return GIVE_IT_A_DAY if asks_today(state, pid, what) >= int(_block("asks")["per_day"]) else ""


def _pending(state: GameState, pid: str, side: str, what: Optional[str] = None,
             statuses: tuple[str, ...] = ("pending",)) -> list[dict[str, Any]]:
    rows = [r for r in (state.social.get("requests") or {}).values()
            if r["pid"] == pid and r["from"] == side and r["status"] in statuses and (what is None or r["what"] == what)]
    return sorted(rows, key=lambda r: (float(r["at"]), int(str(r["id"])[1:] or 0)))


def pending_asks(state: GameState, pid: str) -> list[dict[str, Any]]:
    """The player's asks of `pid` still waiting for their answer, oldest first."""
    return _pending(state, pid, "player")


def ask(state: GameState, thread_id: str, what: str) -> dict[str, Any]:
    """
    The player asks (spec §10.6): their number at `talking`, to be exclusive
    at `dating`. A request message lands (their read decides it); a second
    ask of a kind the same day lowers its odds by `asks.repeat_mult` and costs
    `asks.repeat_warmth`; a third is refused ("Give it a day").
    """
    from engine.social import messaging   # lazily: messaging imports this module

    from engine.social import meets   # lazily: meets imports this module

    t = messaging.thread(state, thread_id)
    if t is None:
        return _no("There's no such conversation.")
    if what not in dict(ASK_STAGE) and what not in MEDIA_KINDS and what != meets.REQUEST:
        return _no(f"You can't ask for {what} yet.")
    pid = str(t["pid"])
    name = _name(state, pid)
    if t.get("closed"):
        return _no(messaging._closed_reason(state, t))
    if what in MEDIA_KINDS:
        from engine.social import media   # lazily: media imports this module

        refusal = media.ask_refusal(state, pid, thread_id, what)
    elif what == meets.REQUEST:
        refusal = meets.ask_refusal(state, pid)          # its own pacing count (meets._count_ask's)
    else:
        refusal = ask_stage_refusal(state, pid, what) or ask_refusal(state, pid, what)
    if refusal:
        return _no(refusal)
    rules = _block("asks")
    repeat = asks_today(state, pid, what) >= 1
    mult = float(rules["repeat_mult"]) if repeat else 1.0
    waiting = _pending(state, pid, "player", what)
    if waiting:
        made = apply_effect(state, {"type": "social_request", "op": "again", "request_id": waiting[0]["id"],
                                    "mult": mult})
    else:
        made = apply_effect(state, {"type": "social_request", "op": "create", "pid": pid, "from": "player",
                                    "what": what, "thread_id": thread_id, "mult": mult})
    rid = made["request"]["id"]
    if repeat:
        apply_effect(state, {"type": "social_regard", "pid": pid, "exact": True,
                             "warmth": int(rules["repeat_warmth"])})
    result = apply_effect(state, {"type": "social_message", "thread_id": thread_id, "from": "player",
                                  "kind": "request", "bubbles": [], "ask": what, "request_id": rid})
    if not result.get("ok"):
        return _no(str(result.get("text")))
    clock.advance_time(state, cost_hours(state, str(t["app"]), "text"))
    return {"ok": True, "thread_id": thread_id, "pid": pid, "asked": what, "request_id": rid,
            "message_id": result["message"]["id"], "again": repeat}


def accept_draw(state: GameState, pid: str, what: str) -> bool:
    """
    Their yes to the player's ask (spec §9.5): trust/100 x the archetype's
    `media.accept_mult` x the request's repeat multiplier, one draw on
    SOCIAL_BEHAVIOUR (F16: a test pins it through messaging._number_accepted).
    """
    person_state = _person(state, pid)
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    waiting = _pending(state, pid, "player", what)
    mult = float(waiting[0].get("mult", 1.0)) if waiting else 1.0
    p = float(person_state.get("trust", 0)) / 100.0 * float(arch.media.get("accept_mult", 1.0)) * mult
    rng = behaviour.person_rng(state, SOCIAL_BEHAVIOUR, pid)
    return rng.random() < max(0.0, min(1.0, p))


def ask_decision(state: GameState, pid: str, what: str) -> dict[str, Any]:
    """
    The person's answer to the player's ask, decided by the engine: where
    they are (the stage's `from`), the stage's gate and needs ("not yet"),
    then the draw. `{"accept": bool, "why": "" | "stage" | "not yet" | "draw"}`.
    """
    target = _ask_stage(what)
    if _person(state, pid).get("stage") not in (_stage_row(target).get("from") or ()):
        return {"accept": False, "why": "stage"}
    if not (gate_holds(state, pid, target) and needs_hold(state, pid, target)):
        return {"accept": False, "why": "not yet"}
    if what == "number":
        from engine.social import messaging   # its _number_accepted is the pinned draw (T8's tests)

        accepted = messaging._number_accepted(state, pid)
    else:
        accepted = accept_draw(state, pid, what)
    return {"accept": bool(accepted), "why": "" if accepted else "draw"}


def settle_ask(state: GameState, request: dict[str, Any], accepted: bool, at: float, why: str = "") -> None:
    """
    The person's answer recorded (inside their read): the request answered,
    a no with its `why` (`ask_decision`'s: "not yet" is the gate, "draw" the
    odds), and, on yes, the stage moved.
    """
    pid = str(request["pid"])
    effect = {"type": "social_request", "op": "answer", "request_id": request["id"],
              "status": "yes" if accepted else "no", "at": at}
    if why and not accepted:
        effect["why"] = why
    apply_effect(state, effect)
    if accepted:
        set_stage(state, pid, _ask_stage(str(request["what"])), at=at)
        if request["what"] == "number":
            from engine.social import messaging

            messaging.open_numbers(state, pid)


# -- the person's proposals (spec §10.5) ------------------------------------------------------


def legal_proposals(state: GameState, pid: str) -> tuple[str, ...]:
    """The relationships.yaml `proposals:` rows whose stage and gate hold for `pid` NOW."""
    person_state = _person(state, pid)
    if apps.gone(state, pid):
        return ()
    stage = person_state.get("stage")
    out: list[str] = []
    for name, row in (_block("proposals") or {}).items():
        wanted = row.get("stage")
        if (wanted == "live" and stage not in LIVE_STAGES) or (wanted != "live" and stage != wanted):
            continue
        gate = row.get("gate")
        if gate and not (gate_holds(state, pid, gate) and needs_hold(state, pid, gate)):
            continue
        if name in dict(PROPOSAL_ASKS) and _pending(state, pid, "them", dict(PROPOSAL_ASKS)[name],
                                                    ("pending", "later")):
            continue
        if name in dict(PROPOSAL_MEDIA):
            from engine.social import media   # lazily: media imports this module

            if not media.offer_open(state, pid, dict(PROPOSAL_MEDIA)[name]):
                continue
        if name == "invite_game":
            from engine.social import games   # lazily: games imports this module

            if not games.proposal_open(state, pid):
                continue
        from engine.social import meets   # lazily: meets imports this module

        if name == meets.PROPOSAL:
            if not meets.proposal_open(state, pid):
                continue
        out.append(str(name))
    return tuple(out)


def apply_proposal(state: GameState, pid: str, name: str, *, at: Optional[float] = None) -> dict[str, Any]:
    """One proposal, re-checked now: a request to the player, a cool-off or a media offer (T19: the engine
    draws; a medium, if any, is a new due message). Never a stage by itself. `at` dates an `invite_game`
    request made by an event (their daily invite, T23); else the clock's now."""
    if name not in legal_proposals(state, pid):
        return _no(f"{name} is not open now")
    if name == "cool_off":
        step = min(behaviour.COOL_OFF_STEP_MAX,
                   behaviour.archetype(population.profile(state, pid).archetype).cool_off_step)
        return apply_effect(state, {"type": "social_regard", "pid": pid, "interest": -step})
    if name in dict(PROPOSAL_MEDIA):
        from engine.social import media   # lazily: media imports this module

        return media.offer(state, pid, dict(PROPOSAL_MEDIA)[name])
    from engine.social import messaging

    from engine.social import meets   # lazily: meets imports this module

    if name == meets.PROPOSAL:
        return meets.propose_theirs(state, pid, messaging.thread_for(state, pid) or "", at=at)
    if name == "invite_game":
        from engine.social import games   # lazily: games imports this module

        effect = {"type": "social_request", "op": "create", "pid": pid, "from": "them",
                  "what": GAME_REQUEST, "game": games.proposed_game(state, pid),
                  "thread_id": messaging.thread_for(state, pid) or ""}
        if at is not None:
            effect["at"] = float(at)
        made = apply_effect(state, effect)
        return {"ok": bool(made.get("ok")), "request_id": made["request"]["id"]}

    made = apply_effect(state, {"type": "social_request", "op": "create", "pid": pid, "from": "them",
                                "what": dict(PROPOSAL_ASKS)[name], "thread_id": messaging.thread_for(state, pid) or ""})
    return {"ok": bool(made.get("ok")), "request_id": made["request"]["id"]}


def apply_regard(state: GameState, pid: str, proposal: dict[str, Any], *, day: int,
                 fallback: bool = False) -> dict[str, Any]:
    """
    A reply's proposed `regard` (warmth, trust, mood), clamped by `social_regard` against `day`;
    `fallback`: an engine-authored reply's, capped by `regard.fallback.per_day` too.
    """
    effect: dict[str, Any] = {"type": "social_regard", "pid": pid, "day": int(day)}
    if fallback:
        effect["fallback"] = True
    for key in ("warmth", "trust", "mood"):
        if key in proposal:
            effect[key] = proposal[key]
    return apply_effect(state, effect)


# -- the player answers theirs; the player ends it ------------------------------------------------


def answer(state: GameState, request_id: str, reply: str) -> dict[str, Any]:
    """
    The player's answer to a request of theirs: yes (the gate re-checked,
    then the stage), no (`asks.turned_down`), or later (it stays open). The
    answer lands in the thread, so they read it and reply.
    """
    from engine.social import messaging

    request = (state.social.get("requests") or {}).get(request_id)
    if request is None or request["from"] != "them":
        return _no("There's no such request.")
    if request["status"] not in ("pending", "later"):
        return _no("You've already answered that.")
    if reply not in REPLIES:
        return _no(f"Answer yes, no or later, not {reply!r}.")
    pid = str(request["pid"])
    name = _name(state, pid)
    if apps.gone(state, pid):
        return _no(f"{name} is no longer available.")
    tid = request.get("thread_id") or messaging.thread_for(state, pid) or ""
    t = messaging.thread(state, tid)
    if t is None or t.get("closed"):
        return _no(messaging._closed_reason(state, t) if t else f"There's no conversation with {name}.")
    from engine.social import meets   # lazily: meets imports this module

    game = request["what"] == GAME_REQUEST
    meet = request["what"] == meets.REQUEST
    if meet:
        if reply == "yes" and not meets.still_open(state, request):   # the gate, the slot still free
            return _no("That isn't on the table any more.")
    elif game:
        from engine.social import games   # lazily: games imports this module

        if reply == "yes" and (games.running(state, pid) is not None or not games.unlocked(state, pid)
                               or request.get("game") not in games.offered()):
            return _no("That isn't on the table any more.")
    else:
        target = _ask_stage(str(request["what"]))
        if reply == "yes" and not can_reach(state, pid, target):
            return _no("That isn't on the table any more.")
    apply_effect(state, {"type": "social_request", "op": "answer", "request_id": request_id, "status": reply})
    started: dict[str, Any] = {}
    if reply == "yes" and meet:
        started = meets.accept_theirs(state, request)
        if not started.get("ok"):
            return _no(str(started.get("error") or started.get("text")))
    elif reply == "yes" and game:
        started = games.accept(state, pid, str(request.get("game") or ""))
        if not started.get("ok"):
            return started
    elif reply == "yes":
        set_stage(state, pid, target)
        if request["what"] == "number":
            messaging.open_numbers(state, pid)
    elif reply == "no" and not game:              # declining a game costs nothing (T22 review M3)
        down = _block("asks")["turned_down"]
        apply_effect(state, {"type": "social_regard", "pid": pid, "exact": True, "warmth": int(down["warmth"]),
                             "mood": down["mood"]})
    apply_effect(state, {"type": "social_message", "thread_id": tid, "from": "player", "kind": "request",
                         "bubbles": [], "answer": reply, "request_id": request_id})
    clock.advance_time(state, cost_hours(state, str(t["app"]), "text"))
    out = {"ok": True, "request_id": request_id, "pid": pid, "answer": reply}
    if started.get("game_id"):
        out["game_id"] = started["game_id"]
    if started.get("meet_id"):
        out["meet_id"] = started["meet_id"]
    return out


def end(state: GameState, pid: str) -> dict[str, Any]:
    """The player ends it (spec §10.3): stage `ended`, by the player; what they had queued is dropped."""
    name = _name(state, pid)
    if apps.gone(state, pid) or not live(_person(state, pid)):
        return _no(f"There's nothing to end with {name}.")
    set_stage(state, pid, "ended", by="player", line="You ended things", drop_queue=True)
    return {"ok": True, "pid": pid, "name": name, "ended": True}


# -- the catalogue (spec §7.1) ---------------------------------------------------------------


def _open_requests(state: GameState) -> list[dict[str, Any]]:
    """Requests of theirs the player can still answer, oldest first (people still there; a meet request
    only while its slot can still be met)."""
    from engine.social import meets   # lazily: meets imports this module

    rows = [r for r in (state.social.get("requests") or {}).values()
            if r["from"] == "them" and r["status"] in ("pending", "later") and not apps.gone(state, r["pid"])
            and (r["what"] != meets.REQUEST or meets.still_open(state, r))]
    return sorted(rows, key=lambda r: (float(r["at"]), int(str(r["id"])[1:] or 0)))


def _request_label(state: GameState, request: dict[str, Any]) -> str:
    name = _name(state, str(request["pid"]))
    if request["what"] == GAME_REQUEST:
        from engine.social import games   # lazily: games imports this module

        return f"{name}: a game of {games.label_of(str(request.get('game') or ''))}"
    if request.get("venue"):
        from engine.social import meets   # lazily: meets imports this module

        return f"{name}: {meets.place_line(str(request['venue']))}"
    return f"{name}: their number" if request["what"] == "number" else f"{name}: being exclusive"


def _answer_label(state: GameState, intent: dict[str, Any]) -> str:
    request = (state.social.get("requests") or {}).get(str(intent.get("target") or "")) or {}
    return f"Answer {_name(state, str(request.get('pid') or ''))}"


@phone_verb("answer", payload={"reply": ArgSpec("enum", REPLIES, required=True)}, skill="social_answer",
            label=_answer_label)
def _answer_verb(state: GameState) -> Optional[IntentVerb]:
    rows = _open_requests(state)
    if not rows:
        return None
    return IntentVerb("answer", options=tuple((r["id"], _request_label(state, r)) for r in rows))


def _endable(state: GameState) -> list[str]:
    from engine.social import matching

    pids = {t["pid"] for t in (state.social.get("threads") or {}).values() if matching.listed(t)}
    return sorted(pid for pid in pids if live(_person(state, pid)) and not apps.gone(state, pid))


@phone_verb("end", payload={}, skill="social_end",
            label=lambda s, i: f"End things with {_name(s, str(i.get('target') or ''))}")
def _end_verb(state: GameState) -> Optional[IntentVerb]:
    pids = _endable(state)
    return IntentVerb("end", options=tuple((p, _name(state, p)) for p in pids)) if pids else None


# -- the payload (spec §17.3) ---------------------------------------------------------------------


@section("requests", time_varying=True)
def _requests_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """Open requests both ways: theirs to answer, the player's waiting for theirs. No odds, no counts."""
    out: list[dict[str, Any]] = []
    for row in sorted((state.social.get("requests") or {}).values(),
                      key=lambda r: (float(r["at"]), int(str(r["id"])[1:] or 0))):
        if row["status"] not in ("pending", "later") or apps.gone(state, row["pid"]):
            continue
        out.append({"id": row["id"], "pid": row["pid"], "name": _name(state, row["pid"]),
                    "from": row["from"], "what": row["what"], "status": row["status"], "at": row["at"],
                    "thread_id": row.get("thread_id") or "",
                    **({"game": row["game"]} if row.get("game") else {}),
                    **({"venue": row["venue"], "day": row["day"], "slot": row["slot"], **_meet_words(row)}
                       if row.get("venue") else {})})
    return out


def _meet_words(row: dict[str, Any]) -> dict[str, str]:
    """A meet request's place and time as the calendar words them (`venue_label`, `when`: "Fri 19:00")."""
    from engine.social import meets   # lazily: meets imports this module

    try:
        label = str(meets.venue(str(row["venue"])).get("label") or row["venue"])
    except Exception:  # noqa: BLE001 -- an unreadable venue costs its words, not the section (review M3)
        label = str(row.get("venue") or "")
    try:
        when = meets.when_words({"start": meets.slot_start(int(row["day"]), str(row["slot"]))})
    except (KeyError, TypeError, ValueError):
        when = ""
    return {"venue_label": label, "when": when}


#: A contact's profile: the dating card's fields the contact card shows (spec §18.2), nothing else.
CONTACT_PROFILE: tuple[str, ...] = ("name", "age", "job", "neighbourhood", "bio", "hobbies", "prompts", "also_on")


@section("contacts", time_varying=True)
def _contacts_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """
    Everyone the player has a listed thread with, once each, by name (v0.22.0 T29, spec §18.2's
    contact card): the PLAYER's view of them -- their profile as their dating app shows it, the
    stage's words and the closeness band (never a number), "Your story" (the history lines, engine
    words), what they have chosen to tell (`about`: their `canon`, never `knows`, which is what they
    know of the player), and `last_heard_days`, whole in-game days since their last message (None
    before any). That last moves while the player is away, so the section is time-varying (F14).
    """
    from engine.social import matching   # lazily: matching imports this module

    by_pid: dict[str, list[dict[str, Any]]] = {}
    for t in sorted((state.social.get("threads") or {}).values(), key=lambda t: str(t["thread_id"])):
        if matching.listed(t):
            by_pid.setdefault(str(t["pid"]), []).append(t)
    dating = apps.dating_apps()
    live_matches = set(matching.live_matches(state))
    threads = state.social.get("threads") or {}
    now = float(state.world_clock_hours)
    out: list[dict[str, Any]] = []
    for pid, rows in by_pid.items():
        person_state = _person(state, pid)
        stage = person_state.get("stage")
        matched_on = _matched_app(person_state, threads, pid, dating)
        # Their profile as the app you matched on shows it; with no match on record, their first app's.
        app = matched_on or next((a for a in population.apps_of(pid) if a in dating), "")
        card = apps.card(state, app, pid) if app else {"name": _name(state, pid), "photos": [], "avatar_url": ""}
        heard = person_state.get("last_them_at")
        out.append({
            "pid": pid,
            "name": _name(state, pid),
            "avatar_url": str(card.get("avatar_url") or ""),
            "photos": [dict(p) for p in card.get("photos") or ()],
            "profile": {k: card[k] for k in CONTACT_PROFILE if k in card},
            "app": app,
            "app_label": apps.label(app) if app else "",
            "matched_on": apps.label(matched_on) if matched_on else "",
            "thread_ids": [str(t["thread_id"]) for t in rows],
            "open": any(not t.get("closed") for t in rows),
            "matched": pid in live_matches,
            "stage_words": stage_words(str(stage)) if stage else "",
            "band": band(person_state) if stage else "",
            "history": [{"day": int(h.get("day") or 1), "at": h.get("at"), "text": str(h.get("text") or "")}
                        for h in person_state.get("history") or () if str(h.get("text") or "")],
            "about": [str(line) for line in person_state.get("canon") or () if str(line).strip()],
            "last_heard_days": None if heard is None else max(0, int((now - float(heard)) // 24)),
        })
    out.sort(key=lambda r: (r["name"].lower(), r["pid"]))
    return out


def _matched_app(person_state: dict[str, Any], threads: dict[str, Any], pid: str, dating: list[str]) -> str:
    """
    The dating app the player matched `pid` on, from the person's own record (T29 review M9): the
    first `apps.<app>.matched_at`, else a dating thread of theirs whether or not it is still listed
    (an unmatched one keeps its app). "" when neither exists.
    """
    rows = person_state.get("apps") or {}
    marked = sorted((float(r["matched_at"]), name) for name, r in rows.items()
                    if name in dating and isinstance(r, dict) and r.get("matched_at") is not None)
    if marked:
        return str(marked[0][1])
    on = sorted(str(t["app"]) for t in threads.values() if t.get("pid") == pid and t.get("app") in dating)
    return on[0] if on else ""

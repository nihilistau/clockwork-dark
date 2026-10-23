"""
Growth: who people become with you (v0.23.0 spec §6).

Each person keeps a growth record in ``people[pid]["growth"]``: a disclosure
DEPTH (0-4, one of the five fixed rungs), an OPENNESS meter (0-100) that fills
from engine-measured events, their fixed PACE, a ``guarded`` count, the layers
already revealed and the one queued for the next episode.

Depth is self-disclosure and topics only (rule 12, "Rule 12 in this design"):
each rung means only the topic kinds it names, from a closed vocabulary that
lives HERE, in code (``RUNGS``, ``KINDS``). ``check_data`` refuses at load any
data kind outside it, a rung listing another rung's kind, and any key outside
each row's schema (§6.7, §19.6). There is no word list: the guard is the
structure. Only ``number`` and ``meet`` may read depth (§6.5).

Willingness (§6.5, T5): ``willing(state, pid, commitment)`` answers whether a
commitment (``COMMITMENTS``) holds now from growth.yaml ``willing:`` -- a stage,
regard floors, play counts, ``needs``, depth for ``number``/``meet`` only, and
``move_in``'s days since ``exclusive`` (R15) -- with why not (``WILLING_WHYS``).
Reaching ``everyday`` (depth 1) queues their number offer (``offer_number``,
engine/social/convo.py; spec §15.2).

Every write is the ``social_growth`` effect (rule 3). ``pace`` and ``topics``
are fixed per person, drawn from counterless keys on ``SOCIAL_GROWTH`` and
materialised at first match (``attrs``, I14); a layer pick is counterless too.
The model never writes openness: ``gain`` and ``loss`` are called by the
mechanics that measured the event.
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional

from engine import social
from engine.game import detmath
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.rng import SOCIAL_GROWTH
from engine.game.state import GameState
from engine.social import attrs, behaviour, population
from engine.social.kinds import MODES, STAGES, recorded, stage_rank

# -- the closed vocabulary (the rule-12 guard's anchor, spec §6.1, §6.7) --------------------------

RUNGS: tuple[tuple[str, frozenset[str]], ...] = (
    ("small_talk", frozenset({"places", "hobbies", "work_outline", "the_apps"})),
    ("everyday", frozenset({"daily_life", "work", "friends", "plans", "opinions"})),
    ("personal_stories", frozenset({"upbringing", "family_outline", "past", "travel", "proud_of"})),
    ("hopes_and_fears", frozenset({"hopes", "worries", "regrets", "values"})),
    ("family_and_future", frozenset({"family", "future_plans", "home_life", "money"})),
)
RUNG_IDS: tuple[str, ...] = tuple(rung for rung, _ in RUNGS)
KINDS: frozenset[str] = frozenset().union(*(kinds for _, kinds in RUNGS))
COMMITMENTS: tuple[str, ...] = ("number", "meet", "come_over", "go_to_theirs", "stay_over",
                                "exclusive", "meet_family", "move_in", "propose", "stay_or_go")
DEPTH_COMMITMENTS: frozenset[str] = frozenset({"number", "meet"})
#: The commitments a phone reply can state, or a phone proposal or ask act on (v0.23.0 spec §13.2 block 6,
#: §13.4): the voice's YOU AND THEM lists those that hold; `stay_over` is never one (m5).
PHONE_COMMITMENTS: tuple[str, ...] = ("number", "meet", "come_over", "exclusive", "move_in", "propose")
#: Why a commitment does not hold (`willing`'s second value; "" when it does).
WILLING_WHYS: tuple[str, ...] = ("", "not_yet", "stage", "needs", "household")
#: The player's words for each why (the `hints` payload; spec §14.2's "Not there yet").
WHY_WORDS: dict[str, str] = {"": "", "not_yet": "Not there yet", "stage": "Not the moment",
                             "needs": "Not what they're looking for", "household": "Not while you share a home"}

DEPTH_ROW_KEYS = frozenset({"id", "kinds", "floors", "counts"})
FLOOR_KEYS = frozenset({"warmth", "trust"})
COUNT_KEYS = frozenset({"episodes", "scenes"})
TOPIC_KEYS = frozenset({"id", "kind", "label", "when", "follows_up"})
LAYER_KEYS = frozenset({"id", "kind", "text", "when"})
WHEN_KEYS = frozenset({"job", "job_shape", "flag", "hobby", "life"})
WILLING_KEYS = frozenset({"stage_min", "stages", "warmth", "trust", "episodes", "scenes", "needs",
                          "depth", "days_since_exclusive", "no_household"})
TOP_KEYS = frozenset({"kinds", "depths", "pace", "trait_mult", "gain", "loss", "guarded_episodes",
                      "topics_per_kind", "life_lines", "closer_soon_at", "willing"})

#: The events that move openness (spec §6.3): `growth.gain`'s and `growth.loss`'s, and the keys of
#: growth.yaml's `gain:` (plus `mode_mult`) and `loss:`. Any other name is a ValueError, so a
#: misspelt caller fails loudly rather than moving nothing.
GAIN_EVENTS: frozenset[str] = frozenset({"exchange", "good_end", "moment", "promise_kept", "support"})
LOSS_EVENTS: frozenset[str] = frozenset({"broken_promise", "left_on_read", "fight", "too_deep"})

#: Gains that a later task switches on (Plan decision 11; spec §24's stub table). Empty since T17 switched
#: `support` on; kept for T19's assertion.
_STUBBED: set[str] = set()

#: The history row a step up writes (spec §6.4), by the rung reached.
_STEP_LINES: dict[str, str] = {
    "everyday": "Started telling you about their days",
    "personal_stories": "Opened up about their past",
    "hopes_and_fears": "Told you what they hope for and what worries them",
    "family_and_future": "Talked with you about family and the future",
}


# -- load-time checks ------------------------------------------------------------------------------


def _fault(file: str, key: str, message: str) -> ValueError:
    return ValueError(f"social: {file}.yaml: {key}: {message}")


def _unknown(file: str, where: str, row: dict[str, Any], allowed: frozenset[str]) -> None:
    if not isinstance(row, dict):
        raise _fault(file, where, "must be a mapping")
    extra = sorted(set(row) - allowed)
    if extra:
        raise _fault(file, where, f"unknown key(s) {extra} (allowed: {sorted(allowed)})")


def _check_when(file: str, where: str, when: Any) -> None:
    if when is None:
        return
    if not isinstance(when, dict):
        raise _fault(file, f"{where}.when", "must be a mapping")
    _unknown(file, f"{where}.when", when, WHEN_KEYS)
    for key, value in when.items():
        values = value if isinstance(value, list) else [value]
        if not values or not all(isinstance(v, str) and v for v in values):
            raise _fault(file, f"{where}.when.{key}", "must be an id or a non-empty list of ids")


def _num(where: str, value: Any, *, whole: bool = False, above_zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int if whole else (int, float)):
        raise _fault("growth", where, f"must be a {'whole number' if whole else 'number'}, not {value!r}")
    if value < 0 or (above_zero and value == 0):
        raise _fault("growth", where, f"must be {'above' if above_zero else 'at least'} 0, not {value!r}")


def _table(where: str, value: Any, *, keys: Optional[frozenset[str]] = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fault("growth", where, f"must be a mapping, not {value!r}")
    if keys is not None:
        _unknown("growth", where, value, keys)
    return value


def _check_values(growth: dict[str, Any]) -> None:
    """Every number a number, in range, at load (so nothing raises mid-turn: `topics_per_kind` is
    read inside the match's `materialise`)."""
    for i, row in enumerate(growth.get("depths") or []):
        for key, value in (row.get("floors") or {}).items():
            _num(f"depths[{i}].floors.{key}", value)
    pace = _table("pace", growth.get("pace") or {}, keys=frozenset({"jitter"}))
    if "jitter" in pace:
        _num("pace.jitter", pace["jitter"])
    for key, value in _table("trait_mult", growth.get("trait_mult") or {}).items():
        _num(f"trait_mult.{key}", value, above_zero=True)
    gain = _table("gain", growth.get("gain") or {}, keys=GAIN_EVENTS | {"mode_mult"})
    for key, value in gain.items():
        if key == "moment":
            for band, amount in _table("gain.moment", value).items():
                _num(f"gain.moment.{band}", amount)
        elif key == "mode_mult":
            for mode, mult in _table("gain.mode_mult", value, keys=frozenset(MODES)).items():
                _num(f"gain.mode_mult.{mode}", mult)
        else:
            _num(f"gain.{key}", value)
    for key, value in _table("loss", growth.get("loss") or {}, keys=LOSS_EVENTS).items():
        _num(f"loss.{key}", value)
    for key in ("guarded_episodes", "topics_per_kind", "life_lines"):
        if key in growth:
            _num(key, growth[key], whole=True)
    if "closer_soon_at" in growth:
        _num("closer_soon_at", growth["closer_soon_at"])


def _check_willing_values(where: str, gate: dict[str, Any]) -> None:
    """One `willing:` row's values (so `willing` never raises mid-turn on a misspelt stage)."""
    stages = gate.get("stages")
    if stages is not None and (not isinstance(stages, list) or not stages
                               or any(s not in STAGES for s in stages)):
        raise _fault("growth", f"{where}.stages", f"must be a non-empty list of stages ({list(STAGES)})")
    if "stage_min" in gate and stage_rank(gate["stage_min"]) < 0:
        raise _fault("growth", f"{where}.stage_min", f"{gate['stage_min']!r} is not a live stage")
    for key in ("warmth", "trust", "days_since_exclusive"):
        if key in gate:
            _num(f"{where}.{key}", gate[key])
    for key in ("episodes", "scenes", "depth"):
        if key in gate:
            _num(f"{where}.{key}", gate[key], whole=True)
    if "depth" in gate and gate["depth"] >= len(RUNGS):
        raise _fault("growth", f"{where}.depth", f"must be a rung 0-{len(RUNGS) - 1}")
    if "no_household" in gate and not isinstance(gate["no_household"], bool):
        raise _fault("growth", f"{where}.no_household", "must be true or false")
    needs = gate.get("needs")
    if needs is not None and (not isinstance(needs, dict) or set(needs) - {"both"} or any(
            v not in ("long_term", "short_term", "friendship", "unsure") for v in needs.values())):
        raise _fault("growth", f"{where}.needs", "must be {both: <an intent>}")


def check_data(growth: dict[str, Any], topics: dict[str, Any], layers: dict[str, Any], *,
               traits: frozenset[str] = frozenset()) -> None:
    """Refuse at load anything outside the closed disclosure vocabulary (spec §6.7, §19.6; rule 12).
    With ``traits`` (population.yaml's trait ids, passed by ``_check_loaded``), every ``trait_mult``
    key must be a real trait, so no multiplier is dead data (pre-flight F23)."""
    if not growth:
        return
    _unknown("growth", "(top)", growth, TOP_KEYS)
    if traits:
        stray = sorted(set(growth.get("trait_mult") or {}) - set(traits))
        if stray:
            raise _fault("growth", "trait_mult", f"{stray} are not population traits")
    data_kinds = set(growth.get("kinds") or ())
    if data_kinds != set(KINDS):
        raise _fault("growth", "kinds", f"must be exactly the engine's vocabulary; "
                                        f"extra {sorted(data_kinds - KINDS)}, missing {sorted(KINDS - data_kinds)}")
    depths = growth.get("depths") or []
    if not isinstance(depths, list) or [row.get("id") if isinstance(row, dict) else row
                                        for row in depths] != list(RUNG_IDS):
        raise _fault("growth", "depths", f"must list the rungs in order: {list(RUNG_IDS)}")
    for i, row in enumerate(depths):
        where = f"depths[{i}]"
        _unknown("growth", where, row, DEPTH_ROW_KEYS)
        own = RUNGS[i][1]
        listed = set(row.get("kinds") or ())
        if not listed <= own:
            raise _fault("growth", f"{where}.kinds", f"{sorted(listed - own)} are not {row['id']} kinds")
        _unknown("growth", f"{where}.floors", row.get("floors") or {}, FLOOR_KEYS)
        _unknown("growth", f"{where}.counts", row.get("counts") or {}, COUNT_KEYS)
        for key, value in (row.get("counts") or {}).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise _fault("growth", f"{where}.counts.{key}", "a whole number of episodes or scenes, never days")
    _check_values(growth)
    for name, gate in (growth.get("willing") or {}).items():
        where = f"willing.{name}"
        if name not in COMMITMENTS:
            raise _fault("growth", where, f"not a commitment ({list(COMMITMENTS)})")
        _unknown("growth", where, gate or {}, WILLING_KEYS)
        if "depth" in (gate or {}) and name not in DEPTH_COMMITMENTS:
            raise _fault("growth", f"{where}.depth", "only number and meet may read depth (rule 12)")
        if "days_since_exclusive" in (gate or {}) and name != "move_in":
            raise _fault("growth", f"{where}.days_since_exclusive", "only move_in counts days (R15)")
        _check_willing_values(where, gate or {})
    for file, rows, allowed in (("topics", topics.get("topics") or [], TOPIC_KEYS),
                                ("layers", layers.get("layers") or [], LAYER_KEYS)):
        if not isinstance(rows, list):
            raise _fault(file, file, "must be a list of rows")
        seen: set[str] = set()
        for i, row in enumerate(rows):
            where = f"{file}[{i}]"
            _unknown(file, where, row, allowed)
            if row.get("kind") not in KINDS:
                raise _fault(file, f"{where}.kind", f"{row.get('kind')!r} is not in the disclosure vocabulary")
            if row.get("id") in seen:
                raise _fault(file, f"{where}.id", f"{row.get('id')!r} is repeated")
            seen.add(str(row.get("id")))
            _check_when(file, where, row.get("when"))


# -- data and the profile `when` -------------------------------------------------------------------


def _data() -> dict[str, Any]:
    return social.data("growth")


def _ids(value: Any) -> set[str]:
    return {str(v) for v in (value if isinstance(value, list) else [value])}


def _life_ids(person_state: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for entry in person_state.get("life") or ():
        if isinstance(entry, dict):
            out.update(str(entry[k]) for k in ("id", "kind") if entry.get(k))
        elif entry:
            out.add(str(entry))
    return out


def profile_when(person: Any, person_state: dict[str, Any], when: Optional[dict[str, Any]]) -> bool:
    """
    A topic's or layer's ``when`` (keys ``job``, ``job_shape``, ``flag``, ``hobby``, ``life``): every
    key given holds, each when ANY of its ids does. ``life`` reads ``person_state["life"]`` (their
    life events, engine/social/life.py). Not ``messaging.when_holds``, which reads an initiation's
    ``when`` (pre-flight F25).
    """
    if not when:
        return True
    for key, value in when.items():
        wanted = _ids(value)
        if key == "job":
            held = {person.job}
        elif key == "job_shape":
            held = {person.job_shape}
        elif key == "flag":
            held = set(person.flags)
        elif key == "hobby":
            held = set(person.hobbies)
        elif key == "life":
            held = _life_ids(person_state or {})
        else:
            return False
        if not wanted & held:
            return False
    return True


# -- the fixed attributes (I14) --------------------------------------------------------------------


@attrs.drawer("pace", SOCIAL_GROWTH)
def _pace(state: GameState, pid: str, rng: random.Random) -> float:
    person = population.profile(state, pid)
    arch_pace = float(behaviour.archetype(person.archetype).growth.get("pace", 1.0))
    mults = _data().get("trait_mult") or {}
    traits = math.prod(float(mults.get(t, 1.0)) for t in person.traits)
    return round(arch_pace * traits * _jitter(rng), 4)


def _jitter(rng: random.Random) -> float:
    """growth.yaml `pace.jitter`, lognormal (split out so a test can force it: lesson 1)."""
    return detmath.exp(float((_data().get("pace") or {}).get("jitter", 0.2)) * detmath.gauss(rng, 0, 1))


@attrs.drawer("topics", SOCIAL_GROWTH)
def _topics(state: GameState, pid: str, rng: random.Random) -> list[str]:
    person = population.profile(state, pid)
    per = int(_data().get("topics_per_kind", 1))
    rows = [r for r in social.data("topics").get("topics") or [] if profile_when(person, {}, r.get("when"))]
    chosen: list[str] = []
    for kind in sorted(KINDS):
        pool = sorted((r for r in rows if r["kind"] == kind), key=lambda r: r["id"])
        chosen.extend(r["id"] for r in rng.sample(pool, min(per, len(pool))))
    return chosen


# -- the record (read-only) ------------------------------------------------------------------------


def _fresh(state: GameState, pid: str) -> dict[str, Any]:
    return {"depth": 0, "openness": 0.0, "pace": float(attrs.of(state, pid)["pace"]), "guarded": 0,
            "guarded_left": 0, "revealed": [], "peak_depth": 0, "reveal_due": ""}


def record(state: GameState, pid: str) -> dict[str, Any]:
    """Read-only: the stored record, or a fresh one computed and NOT written (I14)."""
    stored = (((state.social or {}).get("people") or {}).get(pid) or {}).get("growth")
    return dict(stored) if stored else _fresh(state, pid)


def depth(state: GameState, pid: str) -> int:
    return int(record(state, pid)["depth"])


def _rung_of(kind: str) -> int:
    return next(i for i, (_, kinds) in enumerate(RUNGS) if kind in kinds)


def topics_of(state: GameState, pid: str, *, up_to: Optional[int] = None) -> list[dict[str, Any]]:
    """The person's drawn topic rows, in rung then id order; with ``up_to``, only rungs 0..up_to."""
    mine = set(attrs.of(state, pid).get("topics") or ())
    rows = [r for r in social.data("topics").get("topics") or [] if r.get("id") in mine]
    if up_to is not None:
        rows = [r for r in rows if _rung_of(str(r["kind"])) <= int(up_to)]
    return sorted(rows, key=lambda r: (_rung_of(str(r["kind"])), str(r["id"])))


def _cap(state: GameState, pid: str, *, in_person: bool) -> int:
    arch = behaviour.archetype(population.profile(state, pid).archetype).growth
    return int(arch.get("cap_in_person" if in_person else "cap", 4))


# -- what moves openness (spec §6.3) ---------------------------------------------------------------


def gain(state: GameState, pid: str, event: str, *, mode: str = "", band: str = "") -> float:
    """Openness from an engine-measured event (spec §6.3). The model never writes openness.
    An event outside `GAIN_EVENTS` is a ValueError (a misspelt caller must not move nothing)."""
    if event not in GAIN_EVENTS:
        raise ValueError(f"social: growth.gain: {event!r} is not one of {sorted(GAIN_EVENTS)}")
    if event in _STUBBED:
        return 0.0
    g = _data().get("gain") or {}
    rec = record(state, pid)
    if event == "exchange":
        amount = float(g.get("exchange", 0)) * rec["pace"] * float((g.get("mode_mult") or {}).get(mode, 1.0))
    elif event == "good_end":
        amount = float(g.get("good_end", 0)) * rec["pace"]
    elif event == "moment":
        amount = float((g.get("moment") or {}).get(band, 0)) * rec["pace"]
    else:                                               # promise_kept, support: flat, not paced
        amount = float(g.get(event, 0))
    if rec["guarded_left"] > 0:
        amount /= 2 ** int(rec["guarded"])          # an int power: exact, no libm pow
    if amount <= 0:
        return 0.0
    apply_effect(state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": amount,
                         "in_person": event == "moment"})
    return amount


def loss(state: GameState, pid: str, event: str) -> float:
    """Openness lost (spec §6.3). An archetype's `growth.decay_mult` scales every loss: a ghoster's
    openness "decays twice as fast" (§6.2) -- the spec names no separate decay, so a loss IS the decay
    (Plan decision 19). An event outside `LOSS_EVENTS` is a ValueError."""
    if event not in LOSS_EVENTS:
        raise ValueError(f"social: growth.loss: {event!r} is not one of {sorted(LOSS_EVENTS)}")
    arch = behaviour.archetype(population.profile(state, pid).archetype).growth
    amount = float((_data().get("loss") or {}).get(event, 0)) * float(arch.get("decay_mult", 1.0))
    if amount > 0:
        apply_effect(state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": -amount})
    return amount


# -- the one writer (rule 3) -----------------------------------------------------------------------


@effect_kind("social_growth")
@recorded
def _e_growth(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: one person's growth record (spec §6.4). Ops: ``gain`` (``amount``, signed, clamped
    0-100; a full meter tries the next rung), ``step`` (try the next rung with the meter as it is,
    after a floor moved), ``guard`` (a betrayal: guarded +1, its episode count restarted), ``tick``
    (one episode closed: the guarded count runs down), ``reveal`` (the queued ``layer`` voiced).
    Depth never goes down.
    """
    if not state.social:
        return {"type": "social_growth", "ok": False, "text": "no social slice"}
    pid = str(effect.get("pid") or "")
    if not pid:
        return {"type": "social_growth", "ok": False, "text": "social_growth needs a pid"}
    op = effect.get("op")
    if op not in ("gain", "step", "guard", "tick", "reveal"):
        return {"type": "social_growth", "ok": False, "text": f"unknown op {op!r}"}
    person = (state.social.get("people") or {}).get(pid)
    if not isinstance(person, dict):             # never matched: no row is made for them here
        return {"type": "social_growth", "ok": False, "text": f"{pid} is not someone the player knows"}
    amount = effect.get("amount")
    if op == "gain" and (isinstance(amount, bool) or not isinstance(amount, (int, float))):
        return {"type": "social_growth", "ok": False, "text": "a gain needs a numeric amount"}
    if op == "reveal" and not str(effect.get("layer") or ""):
        return {"type": "social_growth", "ok": False, "text": "a reveal needs a layer"}
    rec = person.get("growth") or _fresh(state, pid)
    in_person = bool(effect.get("in_person"))
    if op in ("gain", "step"):
        if op == "gain":
            rec["openness"] = max(0.0, min(100.0, float(rec["openness"]) + float(effect["amount"])))
        person["growth"] = rec
        stepped = _maybe_step(state, pid, rec, in_person=in_person)
        return {"type": "social_growth", "ok": True, "pid": pid, "op": op, "stepped": stepped}
    if op == "guard":                                    # a betrayal (§6.4, §12.4): guarded +1
        rec["guarded"] = int(rec["guarded"]) + 1
        rec["guarded_left"] = int(_data().get("guarded_episodes", 6))
    elif op == "tick":                                   # one episode closed: the guarded count runs down
        rec["guarded_left"] = max(0, int(rec["guarded_left"]) - 1)
    else:                                                # the queued layer voiced (`opens_up`)
        rec["revealed"] = [*rec["revealed"], str(effect["layer"])]
        rec["reveal_due"] = ""
    person["growth"] = rec
    return {"type": "social_growth", "ok": True, "pid": pid, "op": op}


def _floors_hold(person: dict[str, Any], row: dict[str, Any]) -> bool:
    floors, counts = row.get("floors") or {}, row.get("counts") or {}
    return (float(person.get("warmth", 0)) >= float(floors.get("warmth", 0))
            and float(person.get("trust", 0)) >= float(floors.get("trust", 0))
            and int(person.get("episodes_done", 0)) >= int(counts.get("episodes", 0))
            and int(person.get("scenes_done", 0)) >= int(counts.get("scenes", 0)))


def _maybe_step(state: GameState, pid: str, rec: dict[str, Any], *, in_person: bool) -> bool:
    """Inside the handler: openness 100, the next rung's floors and counts, the cap -> one rung up (§6.4)."""
    current = int(rec["depth"])
    if rec["openness"] < 100.0 or current >= len(RUNGS) - 1 or current + 1 > _cap(state, pid, in_person=in_person):
        return False
    person = state.social["people"][pid]
    row = (_data().get("depths") or [])[current + 1]
    if not _floors_hold(person, row):
        return False
    rec["depth"], rec["openness"] = current + 1, 0.0
    rec["peak_depth"] = max(int(rec["peak_depth"]), current + 1)
    rec["reveal_due"] = _next_layer(state, pid, current + 1, rec["revealed"])
    from engine.social import relationships   # lazily: relationships imports this module
    relationships.add_history(state, pid, "growth", _STEP_LINES[RUNG_IDS[current + 1]])
    if current + 1 == 1:
        _queue_number_offer(state, pid)
    return True


def _queue_number_offer(state: GameState, pid: str) -> None:
    """Inside the handler (spec §15.2): reaching `everyday` queues their number offer -- at this minute when
    a conversation with them is open, else at their next available minute. Its handler draws
    `offer_number_prob` (convo.py `_on_offer_number`)."""
    from engine.social import convo, events   # lazily: convo imports this module

    now = state.world_clock_hours
    at = now if convo.episode(state, pid) is not None else convo.next_available(state, pid, now)
    events.push(state, at, pid, "offer_number")


def _next_layer(state: GameState, pid: str, rung: int, revealed: list[str]) -> str:
    """The rung's next layer (§6.4): a counterless pick among the rows of its kinds whose `when` holds."""
    person = population.profile(state, pid)
    person_state = ((state.social or {}).get("people") or {}).get(pid) or {}
    kinds = RUNGS[rung][1]
    done = set(revealed)
    pool = sorted((r for r in social.data("layers").get("layers") or []
                   if r.get("kind") in kinds and r.get("id") not in done
                   and profile_when(person, person_state, r.get("when"))), key=lambda r: str(r["id"]))
    if not pool:
        return ""
    return str(attrs.key(state.rng_seed, SOCIAL_GROWTH, pid, f"layer:{rung}").choice(pool)["id"])


# -- willingness (spec §6.5) ------------------------------------------------------------------------


def willing(state: GameState, pid: str, commitment: str) -> tuple[bool, str]:
    """Whether `commitment` holds for `pid` now, and why not (spec §6.5). Read-only."""
    from engine.social import relationships   # lazily: relationships imports this module

    gate = ((_data().get("willing") or {}).get(commitment))
    if gate is None:
        raise ValueError(f"social: growth.yaml: willing.{commitment}: not declared")
    person = (state.social.get("people") or {}).get(pid) or {}
    stage = str(person.get("stage") or "matched")
    if "stages" in gate and stage not in gate["stages"]:
        return False, "stage"
    if "stage_min" in gate and stage_rank(stage) < stage_rank(gate["stage_min"]):
        return False, "stage"
    if "depth" in gate and depth(state, pid) < int(gate["depth"]):
        return False, "not_yet"
    for key, field in (("warmth", "warmth"), ("trust", "trust")):
        if key in gate and float(person.get(field, 0)) < float(gate[key]):
            return False, "not_yet"
    if (int(person.get("episodes_done", 0)) < int(gate.get("episodes", 0))
            or int(person.get("scenes_done", 0)) < int(gate.get("scenes", 0))):
        return False, "not_yet"
    if "days_since_exclusive" in gate:
        since = person.get("exclusive_since")
        if since is None or state.world_clock_hours - float(since) < 24.0 * float(gate["days_since_exclusive"]):
            return False, "not_yet"
    if gate.get("no_household") and state.social.get("household"):
        return False, "household"
    if "needs" in gate and not relationships.needs_hold_spec(state, pid, gate["needs"]):
        return False, "needs"
    return True, ""


def closer_soon(state: GameState, pid: str) -> bool:
    """The client's "Getting closer" hint (§14.2): a boolean, never a number."""
    return record(state, pid)["openness"] >= float(_data().get("closer_soon_at", 70))


# -- who they are now (spec §6.6) ------------------------------------------------------------------


def _home_line(state: GameState, pid: str) -> str:
    """Their home, in a line (spec §10.5)."""
    from engine.social import places   # lazily: places registers a drawer on attrs at import

    label = places.home_label(state, pid)
    return f"You live in {label}." if label else ""


def _since_lines(state: GameState, pid: str) -> list[str]:
    """What has happened in their life since you met (spec §11.3): `life.since_lines`."""
    from engine.social import life   # lazily: life imports this module

    return life.since_lines(state, pid, int(_data().get("life_lines", 3)))


def _bio(person: Any, person_state: dict[str, Any]) -> str:
    bios = dict(person.bio or {})
    for app in person_state.get("seen_on") or ():
        if bios.get(app):
            return bios[app]
    return next(iter(bios.values()), "")


def who_now(state: GameState, pid: str, *, in_episode_mode: str = "") -> str:
    """The voice's who-they-are block, as they are NOW with the player (spec §6.6). Read-only."""
    from engine.social import voicing   # lazily: voicing reads this module (its snapshot, T7)

    from engine.social import life   # lazily: life imports this module

    person = life.person_now(state, pid)             # their job since you met (T17); the seed's otherwise
    person_state = ((state.social or {}).get("people") or {}).get(pid) or {}
    now = depth(state, pid)
    words = population.template_words(social.data("population"), tuple(person.hobbies) or ("",),
                                       person.job, person.neighbourhood)
    lines = [f"You are {person.name}, {person.age}, {words['a_job']} living in {words['neighbourhood']}."]
    home = _home_line(state, pid)
    if home:
        lines.append(home)
    if person.hobbies:
        lines.append(f"You are into {voicing.labels('hobbies', list(person.hobbies))}.")
    if person.traits:
        lines.append(f"People would call you {voicing.labels('traits', list(person.traits))}.")
    # At depth 2 or more, a `short` texter writes medium-length messages in a chatting or deep episode.
    row = next((r for r in population.table("texting_styles")
                if isinstance(r, dict) and r.get("id") == person.texting_style), {})
    opened = now >= 2 and in_episode_mode in ("chatting", "deep") and row.get("length") == "short"
    style = voicing.style_words(person.texting_style, length="medium" if opened else "")
    if style:
        lines.append(style)
    if now == 0:
        bio = _bio(person, person_state)
        if bio:
            lines.append(f"Your profile says: {voicing.one_line(bio)}")
        for question, answer in person.prompts or ():
            if answer:
                lines.append(f"{voicing.one_line(question)} {voicing.one_line(answer)}")
    since = _since_lines(state, pid)[: int(_data().get("life_lines", 3))]
    if since:
        lines.append("Since you met:")
        lines.extend(f"- {voicing.one_line(line)}" for line in since)
    talk = [str(r["label"]) for r in topics_of(state, pid, up_to=now)]
    if talk:
        lines.append("What you talk about with them now: " + ", ".join(talk) + ".")
    if now + 1 < len(RUNGS):
        kept = [str(r["label"]) for r in topics_of(state, pid) if r["kind"] in RUNGS[now + 1][1]]
        if kept:
            lines.append("What you still keep to yourself: " + ", ".join(kept) + ".")
    return "\n".join(lines)

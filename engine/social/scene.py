"""
Scenes: meet-ups played in person (v0.23.0 spec §10.1-§10.4; T13).

A scene is the evening itself. It replaces v0.22.0's single quality draw and recap card
(`meets.py`, deleted by T13: its venues moved to `places.py`, its prior, band words and
`post_meet` here).

**A scene** is `state.social["scene"]` (one at a time, `{}` when none):

    {pid, plan_id, location, kind, started_at, moments: [{move, topic, band, minutes, score}],
     energy, prior, closing, sum, count, misstep_run, stay_asked (only after a "not tonight")}

It opens when the player and the person are both at a plan's place (`plans.arrive` calls
`open_scene`): the plan is `met`, a conversation going on the phone with them closes, and a
conversation episode of kind `scene` opens (`social_episode`), which never lapses and closes only
at the scene's end (m9). While it is open the scene owns the narrated turn
(`intents.scene_owns_turn`, `social.scene_open`): the legal verbs are `scene` (the moves),
`close` (the closers) and, at the flat, `do` for scenes.yaml's shared activities; `go` is offered
only through a closer (§10.1).

**The prior** (§10.2) is v0.22's quality formula, moved to scenes.yaml `prior:`: their chemistry,
their warmth and their mood, plus one SOCIAL_SCENE draw (`_prior_draw`) when it opens. It is the
bias every moment starts from and sets their starting energy.

**A moment** (§10.3) is one move (`move`): ask about one of their topics, tell them about one of
yours, be playful, let a silence sit, or just talk (`talk`, what a typed line becomes when it names no
topic, addendum 4 W7; the phone picked up in company is scored by its own `phone` row). Its score is the prior, the move's fit
(their traits and archetype), the topic's fit, their mood and one SOCIAL_SCENE draw
(`_moment_draw`), banded `lands | fine | flat | misstep`. The band moves warmth and trust exactly
(`relationships.apply_regard_exact`), fills openness (`growth.gain("moment", band=...)`) and spends
the move's minutes (`clock.advance_time`, rule 2). A question above their rung is answered by them
steering elsewhere: the band is `too_deep_band` and openness pays `loss.too_deep`. That is a scored
outcome, never a refusal: **no move has a floor, a stage or a refusal** (spec §19.6, rule 12).

**The end** (§10.4): a closer (`close`), or they close (their energy spent, a run of missteps, or
their schedule's next boundary). The moments' average score bands as `great | good | fine |
awkward | bad`; `scenes_done` counts it; a good-or-better one counts toward the branch from
`meeting` (`meets_good`, v0.22's); the scene episode closes (its recap queued, T6); numbers are
swapped when it went `fine` or better and none were (§15.3); `numbers` moves to `meeting`; and
their `post_meet` text is queued at their next available time. Commitments made in person are the
closers' alone (`call_it_a_night`'s promise and plan, `back_to_*`): the agreement view's
`recorded` reads them.

**The narration** of each scene turn goes to the run's archive as a `scene` row
(`archive_turn`, `run_turn`'s post-turn hook): never into state or memory (§7.1).

**The long term** (§12, T18). The closer `propose` (offered while growth.yaml `willing.propose` holds) makes
them `engaged` and the evening goes on. **The wedding** (`kind: wedding`, at the registry office, opened by its
plan, `plans.make_wedding`) allows only scenes.yaml `wedding.moves`, floors every moment's band at `fine` (it
cannot go badly, §12.2), offers no closer, and ends after `wedding.moments` moments: its end makes an engaged
couple `married`. **At home** (`kind: at_home`): with a household (`relationships.household`), while the
partner is free and the player is in the flat, the `scene` verb opens a scene with them with no plan and no
travel (`at_home_target`); while they are home and no scene is open, the narrator is handed them all the
same (`narrator_lines`, `present_pid`). **Being seen**: every scene's end asks `life.seen_check`.

What two adults do on an evening is the narration's, in the storyteller prompt's and the model's
register: the engine hands the move, the band and the topic in its own words and nothing else
(AGENTS.md rule 12). `back_to_yours`, `back_to_theirs`, staying over, moving in and the wedding are
where the evening and the relationship go, nothing more.

Every write is the `social_scene` effect (rule 3); every draw is on SOCIAL_SCENE inside it (rule 4);
no handler moves the clock (rule 2); every number is scenes.yaml's (rule 10).

A v0.22 save's meet-up recap card (a system message, `kind: recap`) is no longer voiced (v0.23.0 T19):
nothing in the engine reads it, and the migration (engine/social/migrate.py) drops v0.22's `meets` rows and an
unvoiced card at load.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
from typing import Any, Optional, Sequence

from engine import social
from engine.game import clock
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.intents import IntentVerb
from engine.game.rng import SOCIAL_PACE, SOCIAL_SCENE
from engine.game.state import GameState
from engine.social import agreement, attrs, behaviour, convo, growth, matching, memory, messaging, places, population
from engine.social import relationships
from engine.social.kinds import Decision, recorded, stage_rank
from engine.social.payload import section

logger = logging.getLogger(__name__)

#: The conversational moves (scenes.yaml `moves:`, checked equal at load). `phone` is never offered (v0.23.0
#: addendum 4 W7): its row scores the phone picked up in company (`phone_in_company`). `talk` (W7) is what a typed
#: line in a scene becomes when it names no topic (`engine/social/typed.py`), and an offered move like any other.
MOVES: tuple[str, ...] = ("ask_about", "tell_about", "playful", "quiet", "phone", "talk")
#: The moves offered by name after the topics (`_move_options`): `talk` in the place `phone` held (A4 W7).
OFFERED_PLAIN: tuple[str, ...] = ("playful", "quiet", "talk")
#: The closers (§10.4; scenes.yaml `closers:` lists those offered, a subset of these).
CLOSERS: tuple[str, ...] = ("another_round", "go_somewhere_else", "walk_them_home", "back_to_yours",
                            "back_to_theirs", "stay_the_night", "call_it_a_night", "propose")
#: A scene's kinds beyond a plan's (T18): at home with the household partner, and the wedding.
AT_HOME, WEDDING = "at_home", "wedding"
#: A chance meeting (v0.23.0 addendum 4 W9): someone the player knows, at the player's venue by their schedule.
CHANCE = "chance"
#: The `scene` world verb's target that goes over to them (`approach:<pid>`, W9).
APPROACH_TARGET = "approach"
#: scenes.yaml `chance:`'s keys (optional block; W9).
CHANCE_KEYS: frozenset[str] = frozenset({"prob", "block_hours", "max_here", "max_candidates", "prior_bias"})
#: The schedule statuses a chance probability may name (`behaviour.status_at`).
CHANCE_STATUSES: tuple[str, ...] = ("asleep", "work", "free", "out")
#: The `scene` world verb's target that opens an at-home scene (`at_home:<pid>`, Plan decision 5's composite).
AT_HOME_TARGET = "at_home"
#: The `scene` world verb's target that waits for a plan's person to arrive here (`plan:<id>`, A4 W2).
PLAN_TARGET = "plan"
#: The stage a proposal makes and the one the wedding needs; the one the wedding makes (§12.1).
ENGAGED, MARRIED = "engaged", "married"
#: A moment's bands, best first.
BANDS: tuple[str, ...] = ("lands", "fine", "flat", "misstep")
#: A scene's bands, best first (scenes.yaml `end_bands` holds all but the last).
SCENE_BANDS: tuple[str, ...] = ("great", "good", "fine", "awkward", "bad")
#: The scene bands that count toward the branch from `meeting` (`meets_good`, v0.22's §10.3).
GOOD_BANDS: tuple[str, ...] = ("great", "good")
#: The scene bands that swap numbers in person (§15.3).
NUMBER_BANDS: tuple[str, ...] = ("great", "good", "fine")
#: Every key a move row may carry (spec §19.6): no floor, no stage, no refusal.
MOVE_KEYS: frozenset[str] = frozenset({"label", "minutes", "fit", "bands"})
FIT_KEYS: frozenset[str] = frozenset({"traits", "archetypes"})
#: What a band's row may move.
REGARD_KEYS: tuple[str, ...] = ("warmth", "trust")
#: scenes.yaml's top-level keys.
TOP_KEYS: frozenset[str] = frozenset({"prior", "moment", "moves", "closers", "close", "end_bands", "too_deep_band",
                                      "shared_activities", "stay", "wedding", "chance"})
#: The stages a scene moves on (§10.4, §15.3).
NUMBERS, MEETING = "numbers", "meeting"
#: The window `call_it_a_night:promise:<window>` offers ("I'll text you in the morning").
PROMISE_WINDOW = "morning"
#: The player's flat's entry room, where "home" is.
HOME = "apt_lounge"
#: How a `call_it_a_night` may end: home (the default) or staying where you are (N5).
THENS: tuple[str, ...] = ("home", "stay")
#: The commitments a closer records (the agreement view's `recorded`, §13.4).
CLOSER_COMMITMENTS: dict[str, str] = {"back_to_yours": "come_over", "back_to_theirs": "go_to_theirs",
                                      "go_somewhere_else": "meet"}

#: The engine's words for a move, then for a band (§10.3: the narrator is handed these, nothing else).
MOVE_WORDS: dict[str, str] = {"ask_about": "You ask about {topic}", "tell_about": "You tell them about {topic}",
                              "playful": "You are playful", "quiet": "You let a silence sit",
                              "phone": "You check your phone", "talk": "You talk"}
BAND_WORDS: dict[str, str] = {"lands": "It lands.", "fine": "It goes fine.", "flat": "It falls flat.",
                              "misstep": "It is a misstep."}
TOO_DEEP_WORDS = "They steer the talk somewhere else."


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: scenes.yaml: {key}: {message}")


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _data() -> dict[str, Any]:
    return social.data("scenes")


# -- the data, checked at load (spec §19.6; pre-flight F23) ---------------------------------------


def check_data(scenes: dict[str, Any], *, traits: frozenset[str] = frozenset()) -> None:
    """
    scenes.yaml whole, at load: the first fault a ValueError naming the file and key. A move row
    carries exactly `label`, `minutes`, `fit` and `bands` (no floor, stage or refusal: §19.6); a
    `fit.traits` key must be a population.yaml trait (`traits`, when given: pre-flight F23).
    """
    extra = sorted(set(scenes) - TOP_KEYS)
    if extra:
        raise _fault(extra[0], "is not a scenes.yaml key")
    _check_prior(scenes.get("prior"))
    _check_moment(scenes.get("moment"))
    moves = scenes.get("moves")
    if not isinstance(moves, dict) or list(moves) != list(MOVES):
        raise _fault("moves", f"must give exactly {', '.join(MOVES)}, in that order")
    for name, row in moves.items():
        _check_move(name, row, traits)
    closers = scenes.get("closers")
    if not isinstance(closers, list) or not closers or not set(closers) <= set(CLOSERS):
        raise _fault("closers", f"must list closers from {', '.join(CLOSERS)}")
    if "call_it_a_night" not in closers:
        raise _fault("closers", "must offer call_it_a_night (the way home has no gate)")
    close = scenes.get("close")
    if not isinstance(close, dict):
        raise _fault("close", "must be a mapping")
    for key in ("energy_out", "another_round_minutes", "another_round_energy", "walk_extra_minutes"):
        if not _num(close.get(key)) or close[key] < 0:
            raise _fault(f"close.{key}", "must be a number, 0 or more")
    if not _whole(close.get("misstep_run")) or close["misstep_run"] < 1:
        raise _fault("close.misstep_run", "must be a whole number of 1 or more")
    ends = scenes.get("end_bands")
    if (not isinstance(ends, dict) or list(ends) != list(SCENE_BANDS[:-1])
            or not all(_num(v) for v in ends.values())):
        raise _fault("end_bands", f"must give {', '.join(SCENE_BANDS[:-1])} each a least score, in that order")
    values = list(ends.values())
    if any(a <= b for a, b in zip(values, values[1:])):
        raise _fault("end_bands", "must fall band by band, best first")
    if scenes.get("too_deep_band") not in BANDS:
        raise _fault("too_deep_band", f"must be one of {', '.join(BANDS)}")
    shared = scenes.get("shared_activities")
    if not isinstance(shared, dict) or not all(
            isinstance(v, list) and all(isinstance(a, str) and a for a in v) for v in shared.values()):
        raise _fault("shared_activities", "must map a location id to a list of activity ids")
    for key in ("stay", "wedding"):
        if not isinstance(scenes.get(key), dict):
            raise _fault(key, "must be a mapping")
    wedding = scenes["wedding"]
    if not _whole(wedding.get("moments")) or wedding["moments"] < 1:
        raise _fault("wedding.moments", "must be a whole number of 1 or more")
    allowed = wedding.get("moves")
    if not isinstance(allowed, list) or not allowed or not set(allowed) <= set(MOVES):
        raise _fault("wedding.moves", f"must list moves from {', '.join(MOVES)}")
    if "chance" in scenes:
        _check_chance(scenes["chance"])


def _check_chance(chance: Any) -> None:
    """scenes.yaml `chance:` (A4 W9): every key, each in range. Absent, nobody is anywhere by chance."""
    if not isinstance(chance, dict):
        raise _fault("chance", "must be a mapping")
    if set(chance) != CHANCE_KEYS:
        raise _fault("chance", f"must give exactly {', '.join(sorted(CHANCE_KEYS))}")
    prob = chance["prob"]
    if (not isinstance(prob, dict) or not set(prob) <= set(CHANCE_STATUSES)
            or not all(_num(v) and 0 <= v <= 1 for v in prob.values())):
        raise _fault("chance.prob", f"must map statuses ({', '.join(CHANCE_STATUSES)}) to a share, 0 to 1")
    if not _num(chance["block_hours"]) or not 0 < chance["block_hours"] <= 24:
        raise _fault("chance.block_hours", "must be hours, above 0 and at most 24")
    for key in ("max_here", "max_candidates"):
        if not _whole(chance[key]) or chance[key] < 1:
            raise _fault(f"chance.{key}", "must be a whole number of 1 or more")
    if not _num(chance["prior_bias"]):
        raise _fault("chance.prior_bias", "must be a number")


def _check_prior(prior: Any) -> None:
    if not isinstance(prior, dict):
        raise _fault("prior", "must be a mapping")
    for key in ("base", "spread"):
        if not _num(prior.get(key)):
            raise _fault(f"prior.{key}", "must be a number")
    if prior["spread"] < 0:
        raise _fault("prior.spread", "must be 0 or more")
    terms = prior.get("terms")
    if not isinstance(terms, dict):
        raise _fault("prior.terms", "must map chemistry, warmth and mood")
    for key in ("chemistry", "warmth"):
        if not _num(terms.get(key)):
            raise _fault(f"prior.terms.{key}", "must be a number")
    mood = terms.get("mood")
    if not isinstance(mood, dict) or not all(_num(v) for v in mood.values()):
        raise _fault("prior.terms.mood", "must map moods to numbers")


def _check_moment(moment: Any) -> None:
    if not isinstance(moment, dict):
        raise _fault("moment", "must be a mapping")
    if not _num(moment.get("spread")) or moment["spread"] < 0:
        raise _fault("moment.spread", "must be a number, 0 or more")
    cut = moment.get("bands")
    if not isinstance(cut, dict) or list(cut) != list(BANDS[:-1]) or not all(_num(v) for v in cut.values()):
        raise _fault("moment.bands", f"must give {', '.join(BANDS[:-1])} each a least score, in that order")
    values = list(cut.values())
    if any(a <= b for a, b in zip(values, values[1:])):
        raise _fault("moment.bands", "must fall band by band, best first")
    fit = moment.get("topic_fit")
    if not isinstance(fit, dict) or set(fit) != {"theirs", "shared"} or not all(_num(v) for v in fit.values()):
        raise _fault("moment.topic_fit", "must give theirs and shared each a number")
    cost = moment.get("energy_cost")
    if not isinstance(cost, dict) or set(cost) != set(BANDS) or not all(_num(v) and v >= 0 for v in cost.values()):
        raise _fault("moment.energy_cost", f"must give {', '.join(BANDS)} each a number, 0 or more")


def _check_move(name: str, row: Any, traits: frozenset[str]) -> None:
    where = f"moves.{name}"
    if not isinstance(row, dict):
        raise _fault(where, "must be a mapping")
    extra = sorted(set(row) - MOVE_KEYS)
    if extra:
        raise _fault(f"{where}.{extra[0]}", f"is not a move key (a move is exactly {', '.join(sorted(MOVE_KEYS))})")
    if not isinstance(row.get("label"), str) or not row["label"].strip():
        raise _fault(f"{where}.label", "required: the player's words")
    if not _num(row.get("minutes")) or row["minutes"] <= 0:
        raise _fault(f"{where}.minutes", "must be minutes above 0")
    fit = row.get("fit")
    if not isinstance(fit, dict) or not set(fit) <= FIT_KEYS:
        raise _fault(f"{where}.fit", f"must be a mapping of {', '.join(sorted(FIT_KEYS))}")
    for key in FIT_KEYS:
        table = fit.get(key, {})
        if not isinstance(table, dict) or not all(_num(v) for v in table.values()):
            raise _fault(f"{where}.fit.{key}", "must map ids to numbers")
    unknown = sorted(t for t in (fit.get("traits") or {}) if traits and t not in traits)
    if unknown:
        raise _fault(f"{where}.fit.traits", f"{unknown[0]!r} is no population.yaml trait")
    bands = row.get("bands")
    if not isinstance(bands, dict) or set(bands) != set(BANDS):
        raise _fault(f"{where}.bands", f"must give each of {', '.join(BANDS)} a row")
    for band, moves in bands.items():
        if not isinstance(moves, dict) or not set(moves) <= set(REGARD_KEYS) or not all(_whole(v) for v in moves.values()):
            raise _fault(f"{where}.bands.{band}", f"must map {', '.join(REGARD_KEYS)} to whole numbers")


# -- relationships.yaml `meets:` (what is left of v0.22's block: post_meet and the band words) -----------------

def _rules() -> dict[str, Any]:
    rules = social.data("relationships").get("meets")
    if not isinstance(rules, dict):
        raise ValueError("social: relationships.yaml: meets: required beside scenes (spec §10.4)")
    return rules


def meets_faults(relationships_data: dict[str, Any], *, venues_declared: bool = True) -> list[tuple[str, str, str]]:
    """
    Every fault of relationships.yaml's `meets:` block as (file, key, message): `post_meet` (their text after a
    scene: `pace_mult`, `none_after` scene bands, `none_from` archetypes), `recap_lines` (the engine's words for
    each scene band). Required once a story ships
    venues (`venues_declared`); a story with neither has no fault.
    """
    src = "relationships.yaml"
    rules = (relationships_data or {}).get("meets")
    if rules is None:
        return [(src, "meets", "required beside venues.yaml (spec §10.4)")] if venues_declared else []
    if not isinstance(rules, dict):
        return [(src, "meets", "must be a mapping")]
    out: list[tuple[str, str, str]] = []
    post = rules.get("post_meet") or {}
    if not _num(post.get("pace_mult")) or post["pace_mult"] <= 0:
        out.append((src, "meets.post_meet.pace_mult", "required: a number above 0"))
    if not set(post.get("none_after") or ()) <= set(SCENE_BANDS):
        out.append((src, "meets.post_meet.none_after", f"must list bands ({', '.join(SCENE_BANDS)})"))
    if not isinstance(post.get("none_from") or [], list):
        out.append((src, "meets.post_meet.none_from", "must list archetypes"))
    lines = rules.get("recap_lines") or {}
    for name in SCENE_BANDS:
        if not isinstance(lines.get(name), str) or not lines[name].strip():
            out.append((src, f"meets.recap_lines.{name}", "required: the engine's words for how it went"))
    for key in sorted(set(rules) - {"post_meet", "recap_lines"}):
        out.append((src, f"meets.{key}", "is not a meets key (the prior and bands are scenes.yaml's, spec §10.2)"))
    return out


def recap_line(band_name: str) -> str:
    """The engine's words for how a scene went ("It was a little awkward.")."""
    return str((_rules().get("recap_lines") or {}).get(band_name) or "")


# -- reading -------------------------------------------------------------------------------------------


def current(state: GameState) -> dict[str, Any]:
    """The open scene's row, {} when none (read-only)."""
    return ((getattr(state, "social", None) or {}).get("scene") or {})


def _person(state: GameState, pid: str) -> dict[str, Any]:
    return (state.social.get("people") or {}).get(pid) or {}


def _name(state: GameState, pid: str) -> str:
    return matching._name(state, pid)


def _hobby_labels() -> dict[str, str]:
    return {str(r.get("id")): str(r.get("label") or r.get("id")) for r in population.table("hobbies")
            if isinstance(r, dict)}


def _topic_row(topic: str) -> dict[str, Any]:
    return next((r for r in social.data("topics").get("topics") or () if r.get("id") == topic), {})


def _topic_rung(topic: str) -> int:
    """The rung a topic id sits on (by its kind); 0 for a topic the data does not know."""
    kind = str(_topic_row(topic).get("kind") or "")
    return growth._rung_of(kind) if kind in growth.KINDS else 0


def _topic_label(name: str, topic: str) -> str:
    if not topic:
        return "something"
    if name == "tell_about":
        if topic.startswith("life_"):                  # something that is happening in the player's life (T17)
            from engine.social import life   # lazily: life imports this module's peers

            return life.topic_label(topic) or topic.replace("_", " ")
        return "your work" if topic == "work" else _hobby_labels().get(topic, topic.replace("_", " "))
    return str(_topic_row(topic).get("label") or topic.replace("_", " "))


def _mood_term(state: GameState, pid: str) -> float:
    moods = ((_data().get("prior") or {}).get("terms") or {}).get("mood") or {}
    return float(moods.get(relationships.mood_now(_person(state, pid), state.world_clock_hours), 0.0))


def _prior_terms(state: GameState, pid: str) -> float:
    """The prior before its draw (§10.2): base, their chemistry, their warmth (/100) and their mood. Reads only."""
    prior = _data().get("prior") or {}
    terms = prior.get("terms") or {}
    person = population.profile(state, pid)
    warmth = float(_person(state, pid).get("warmth", 0) or 0) / 100.0
    return (float(prior.get("base", 0.5)) + float(terms.get("chemistry", 0)) * float(person.chemistry)
            + float(terms.get("warmth", 0)) * warmth + _mood_term(state, pid))


def _prior_draw(state: GameState, pid: str) -> float:
    """The prior's one SOCIAL_SCENE draw, a centred spread (lesson 1: forceable). Inside a handler (rule 3)."""
    spread = float((_data().get("prior") or {}).get("spread", 0.18))
    return behaviour.person_rng(state, SOCIAL_SCENE, pid).gauss(0.0, spread)


def _moment_draw(state: GameState, pid: str) -> float:
    """The moment's one SOCIAL_SCENE draw, a centred spread (lesson 1: forceable). Inside a handler (rule 3)."""
    spread = float((_data().get("moment") or {}).get("spread", 0.2))
    return behaviour.person_rng(state, SOCIAL_SCENE, pid).gauss(0.0, spread)


def _band_of(score: float) -> str:
    cut = (_data().get("moment") or {}).get("bands") or {}
    for name in ("lands", "fine", "flat"):
        if score >= float(cut.get(name, 1.0)):
            return name
    return "misstep"


def _scene_band(average: float) -> str:
    for name, least in (_data().get("end_bands") or {}).items():
        if average >= float(least):
            return str(name)
    return SCENE_BANDS[-1]


def _fit(state: GameState, pid: str, row: dict[str, Any]) -> float:
    """The move's fit: its `fit.traits` terms for the traits they have, and its archetype's term."""
    person = population.profile(state, pid)
    fit = row.get("fit") or {}
    traits = fit.get("traits") or {}
    total = sum(float(traits[t]) for t in person.traits if t in traits)
    return total + float((fit.get("archetypes") or {}).get(person.archetype, 0.0))


def _topic_fit(state: GameState, pid: str, name: str, topic: str) -> float:
    """A topic of theirs at their own rung (`theirs`), or a hobby of yours they share (`shared`)."""
    if not topic:
        return 0.0
    fit = (_data().get("moment") or {}).get("topic_fit") or {}
    if name == "ask_about":
        mine = {str(r["id"]) for r in growth.topics_of(state, pid)}
        return float(fit.get("theirs", 0.0)) if topic in mine and _topic_rung(topic) == growth.depth(state, pid) else 0.0
    if name == "tell_about":
        shared = set(population.profile(state, pid).hobbies) & set((state.social.get("player") or {}).get("hobbies") or ())
        return float(fit.get("shared", 0.0)) if topic in shared else 0.0
    return 0.0


def _rude(state: GameState, pid: str) -> bool:
    """They find a phone out in company rude (their `in_company` habit, conversation.yaml `habits`)."""
    return attrs.of(state, pid)["habits"]["in_company"] == "rude_not_to"


def _band_words(name: str, band: str, topic: str, *, too_deep: bool) -> str:
    move = MOVE_WORDS.get(name, name).format(topic=topic or "something")
    return f"{move}. {TOO_DEEP_WORDS}" if too_deep else f"{move}. {BAND_WORDS.get(band, '')}".strip()


def _where_words(state: GameState, scn: dict[str, Any]) -> str:
    """Where the scene was, in the engine's words ("Drinks at The Anchor", "At their place", "At yours")."""
    location = str(scn.get("location") or "")
    if scn.get("kind") == CHANCE:
        return f"Ran into each other at {places.label(location)}"
    if location in places.venue_ids():
        return places.place_line(location)
    if places.is_home(location):
        return "At their place"
    if places.is_flat(location):
        return "At home" if scn.get("kind") == AT_HOME else "At yours"
    return places.label(location)


def _where_in_a_line(state: GameState, scn: dict[str, Any]) -> str:
    """`_where_words` after a colon mid-sentence: a run-in reads "you ran into each other at The Anchor" (its card's
    history line keeps the capital); every other kind's words as they are."""
    if scn.get("kind") == CHANCE:
        return f"you ran into each other at {places.label(str(scn.get('location') or ''))}"
    return _where_words(state, scn)


# -- opening (§10.1) ---------------------------------------------------------------------------------


def open_scene(state: GameState, pid: str, location: str, *, plan_id: str = "", kind: str = "date") -> dict[str, Any]:
    """
    The scene opens (from `plans.arrive`): the plan is `met`, a phone conversation with them going on now
    closes, the scene row is written with its prior drawn, and a `scene` episode opens. The result carries
    `met` (the plan) and `scene` (the person).
    """
    if social.scene_open(state):
        return {"ok": False, "quiet": True, "error": "a scene is already going on"}
    at = state.world_clock_hours
    if plan_id:
        apply_effect(state, {"type": "social_plan", "op": "met", "plan_id": plan_id, "at": at})
    if convo.episode(state, pid) is not None:              # the chat that led here ends as you meet (m9)
        apply_effect(state, {"type": "social_episode", "op": "close", "pid": pid, "at": at, "end": "met"})
    opened = apply_effect(state, {"type": "social_scene", "op": "open", "pid": pid, "plan_id": plan_id,
                                  "location": location, "kind": kind, "at": at})
    if not opened.get("ok"):
        return {"ok": False, "quiet": True, "error": str(opened.get("text") or "")}
    apply_effect(state, {"type": "social_episode", "op": "open", "pid": pid, "kind": "scene", "at": at,
                         "thread_id": messaging.thread_for(state, pid) or "", "location": location})
    return {"ok": True, "met": plan_id, "scene": pid, "quiet": False}


# -- the verbs (Plan decision 5) -----------------------------------------------------------------------


def _move_options(state: GameState, pid: str) -> list[tuple[str, str]]:
    """The moves on offer, at most eight, by a fixed rank: three of their topics (their rung first, then the
    rung above), two of yours, then playful, quiet and talk (A4 W7: `talk` took the phone's place; the phone is
    scored by picking it up, `phone_in_company`)."""
    rows = _data().get("moves") or {}
    if current(state).get("kind") == WEDDING:            # only the wedding's moves (§12.2)
        allowed = set((_data().get("wedding") or {}).get("moves") or ())
        rows = {k: v for k, v in rows.items() if k in allowed}
    depth = growth.depth(state, pid)

    def label(name: str, topic: str = "") -> str:
        return str(rows[name]["label"]).replace("{topic}", _topic_label(name, topic))

    out: list[tuple[str, str]] = []
    if "ask_about" in rows:
        theirs = growth.topics_of(state, pid, up_to=min(depth + 1, len(growth.RUNGS) - 1))
        theirs.sort(key=lambda r: (abs(_topic_rung(str(r["id"])) - depth), str(r["id"])))
        out += [(f"ask_about:{r['id']}", label("ask_about", str(r["id"]))) for r in theirs[:3]]
    if "tell_about" in rows:
        from engine.social import life   # lazily: life imports this module's peers

        news = [str(n["topic"]) for n in life.player_news(state)][:1]       # what is happening to you (§11.2)
        mine = news + [str(h) for h in (state.social.get("player") or {}).get("hobbies") or ()][:1] + ["work"]
        out += [(f"tell_about:{t}", label("tell_about", t)) for t in mine[:2]]
    out += [(name, label(name)) for name in OFFERED_PLAIN if name in rows]
    return out[:8]


def _close_options(state: GameState, scn: dict[str, Any]) -> list[tuple[str, str]]:
    """The closers on offer (§10.4), at most eight, in a fixed order; each only where it can be done."""
    pid = str(scn["pid"])
    name = _name(state, pid)
    offered = set(_data().get("closers") or ())
    here = state.location_id
    at_venue = here in places.venue_ids()
    proposing = [("propose", "propose", f"Ask {name} to marry you")] if growth.willing(state, pid, "propose")[0] else []
    if scn.get("kind") == WEDDING:
        return []                                         # the wedding runs its moments; nothing ends it early
    if scn.get("kind") == AT_HOME:                        # at home together: no way home to go, nobody to see off
        rows_home = [("call_it_a_night", "call_it_a_night:stay", "Leave it there, and get on with your evening"),
                     ("another_round", "another_round", "Stay a while longer"), *proposing]
        return [(target, label) for closer, target, label in rows_home if closer in offered][:8]
    lives_here = relationships.household(state) == pid   # they live with the player: their old home is not theirs
    # A chance meeting (W9, C3): the closers that make a plan need `willing(meet)`, since `plans.make(in_person=True)`
    # asks no willingness; a planned scene's plan already passed it.
    plans_ok = scn.get("kind") != CHANCE or growth.willing(state, pid, "meet")[0]
    rows: list[tuple[str, str, str]] = [
        ("call_it_a_night", "call_it_a_night", "Call it a night"),
        ("call_it_a_night", f"call_it_a_night:promise:{PROMISE_WINDOW}",
         "Call it a night, and say you'll text them in the morning"),
    ]
    if plans_ok:
        rows.append(("call_it_a_night", "call_it_a_night:plan:soon", "Call it a night, and say you'll do it again soon"))
    rows.append(("another_round", "another_round", "Stay a while longer"))
    if plans_ok and not places.is_flat(here) and growth.willing(state, pid, "come_over")[0]:
        rows.append(("back_to_yours", "back_to_yours", f"Ask {name} back to yours"))
    if (plans_ok and here != places.home_of(state, pid) and not lives_here
            and growth.willing(state, pid, "go_to_theirs")[0]):
        rows.append(("back_to_theirs", "back_to_theirs", f"Go back to {name}'s"))
    if stay_offered(state) and not lives_here:
        rows.append(("stay_the_night", "stay_the_night", f"Ask {name} to stay the night" if not places.is_home(here)
                     else "Stay the night"))
    if at_venue:
        rows.append(("walk_them_home", "walk_them_home", f"Walk {name} home"))
        elsewhere = next((v for v in _ranked_venues(state) if v != here), "") if plans_ok else ""
        if elsewhere:
            rows.append(("go_somewhere_else", f"go_somewhere_else:{elsewhere}", f"Go on to {places.label(elsewhere)}"))
    rows.append(("call_it_a_night", "call_it_a_night:stay", "Say goodnight, and stay here a while"))
    rows += proposing
    return [(target, label) for closer, target, label in rows if closer in offered][:8]


def _ranked_venues(state: GameState) -> list[str]:
    from engine.social import world   # lazily: world imports this module's peers

    return world._ranked_venues(state)


def _shared_options(state: GameState) -> list[tuple[str, str]]:
    from engine.social import world

    ids = ((_data().get("shared_activities") or {}).get(state.location_id) or ())
    rows = {str(r["id"]): r for r in world.activities()}
    return [(a, str(rows[a].get("label") or a)) for a in ids if a in rows][:8]


def scene_verbs(state: GameState) -> tuple[IntentVerb, ...]:
    """While a scene is open: `scene` (the moves), `close` (the closers) and, at the flat, `do` for the shared
    activities (§10.1). `go` is offered only through a closer."""
    scn = current(state)
    if not scn.get("pid"):
        return ()
    verbs = [IntentVerb("scene", tuple(_move_options(state, str(scn["pid"])))),
             IntentVerb("close", tuple(_close_options(state, scn)))]
    shared = _shared_options(state)
    if shared:
        verbs.append(IntentVerb("do", tuple(shared)))
    return tuple(v for v in verbs if v.options)


def shared_activity(state: GameState, activity_id: str) -> Optional[dict[str, Any]]:
    """A shared activity done together (`do` during a scene): its minutes spent through `clock.advance_time`,
    never cut short by the phone (you are with someone). None when `activity_id` is not one here."""
    if activity_id not in dict(_shared_options(state)):
        return None
    from engine.social import world

    row = next(r for r in world.activities() if r.get("id") == activity_id)
    clock.advance_time(state, float(row.get("minutes", 0) or 0) / 60.0)
    return {"ok": True, "activity": activity_id, "narrate": row.get("narrate", ""), "together": True,
            "pid": str(current(state).get("pid") or "")}


# -- a moment (§10.3) ----------------------------------------------------------------------------------


def move(state: GameState, target: str) -> dict[str, Any]:
    """
    The scene verb (§10.3): one move, scored and banded inside `social_scene` `moment` (its draw there, rule 3),
    then its minutes spent (rule 2) and openness moved. A move above their rung is a `too_deep_band` outcome and
    costs `loss.too_deep`; never a refusal. When they close (energy, missteps, their schedule) the scene ends.
    """
    scn = current(state)
    pid = str(scn.get("pid") or "")
    name, _, topic = str(target).partition(":")
    if not pid and name == AT_HOME_TARGET:
        return open_at_home(state, topic)
    if not pid and name == PLAN_TARGET:
        return wait_for_plan(state, topic)
    if not pid and name == APPROACH_TARGET:
        return approach(state, topic)
    row = (_data().get("moves") or {}).get(name)
    if not pid or row is None:
        return {"ok": False, "error": "there is nobody here to talk to"}
    result = apply_effect(state, {"type": "social_scene", "op": "moment", "move": name, "topic": topic})
    if not result.get("ok"):
        return {"ok": False, "error": str(result.get("text") or "that can't be done now")}
    band = str(result["band"])
    clock.advance_time(state, float(row.get("minutes", 15)) / 60.0)          # the moment's minutes (rule 2)
    if result.get("too_deep"):
        growth.loss(state, pid, "too_deep")
    else:
        growth.gain(state, pid, "moment", band=band)
    from engine.social import life   # lazily: life imports this module's peers

    life.support(state, pid)                                  # a scene while a hard event of theirs runs (§6.3)
    told = life.topic_text(topic) if name == "tell_about" else ""
    if told:
        memory.add_knows(state, pid, [told])                  # they hear it only because you said it (§11.2)
    label = _topic_label(name, topic) if topic else ""
    out: dict[str, Any] = {"ok": True, "pid": pid, "move": name, "topic": topic, "band": band,
                           "words": _band_words(name, band, label, too_deep=bool(result.get("too_deep")))}
    if result.get("closed"):
        ended = end_scene(state, str(result["closed"]), then="stay")
        out.update(closed_by_them=str(result["closed"]), scene_band=ended.get("band", ""),
                   scene_words=recap_line(str(ended.get("band") or "")))
    return out


def phone_in_company(state: GameState) -> None:
    """The phone picked up during a scene (§8.2, MINOR 6): someone who finds it rude minds (`phone`'s misstep
    row, exactly); someone who glances at their own does not."""
    if social.scene_open(state):
        apply_effect(state, {"type": "social_scene", "op": "phone"})


# -- closing (§10.4) ------------------------------------------------------------------------------------


def _go(state: GameState, to: str) -> dict[str, Any]:
    """Travel through a closer: `world.go` with that one target (its travel charged, rule 2; `resume` cleared)."""
    from engine.social import world

    label = world.HOME_LABEL if to == HOME else places.label(to)
    return world.go(state, to, targets=[(to, label)])


def end_scene(state: GameState, reason: str, *, then: str = "home", continues: bool = False) -> dict[str, Any]:
    """
    The scene's end (§10.4), through `social_scene` `end`: its band, the counts, the episode closed and its recap
    queued, numbers swapped, the stage moved, `post_meet` queued, the scene cleared. `then: home` (the default)
    takes the player home to the flat with the travel charged; `then: stay` leaves them where they are.
    `continues` (a closer that moves the evening on) holds the `post_meet` text for the scene that follows.
    """
    if then not in THENS:
        raise ValueError(f"scene.end_scene: then {then!r} is not one of {', '.join(THENS)}")
    if not social.scene_open(state):
        return {"ok": False, "error": "no scene is open"}
    result = apply_effect(state, {"type": "social_scene", "op": "end", "reason": str(reason or ""),
                                      "continues": bool(continues)})
    out = {"ok": bool(result.get("ok")), "band": str(result.get("band") or ""), "pid": str(result.get("pid") or "")}
    if then == "home":
        out["went"] = _go(state, HOME)
    elif not continues:
        # Staying where you are: someone who arrived here for a plan while this scene went on is met now, within
        # their patience (A4 W4, I4). A closer that moves the evening on carries its own person instead (C1).
        from engine.social import plans   # lazily: plans imports this module's peers

        met = plans.meet_if_here(state)
        if met.get("scene") or met.get("stood_up"):
            out["next"] = {k: v for k, v in met.items() if k in ("met", "scene", "stood_up")}
    if not continues:
        from engine.social import messaging   # lazily: messaging imports this module's peers

        messaging.release_held(state)         # their held texts land now they are apart (W5)
    return out


def close(state: GameState, target: str) -> dict[str, Any]:
    """
    A closer (§10.4; Plan decision 5's composite targets): `call_it_a_night[:promise:<window>|:plan:soon|:stay]`,
    `another_round`, `go_somewhere_else:<venue>`, `walk_them_home`, `back_to_yours`, `back_to_theirs`. Only the
    closers on offer now are accepted. A promise or a plan is made only here (I10), and recorded for the
    agreement view (`recorded`).
    """
    scn = current(state)
    pid = str(scn.get("pid") or "")
    if not pid:
        return {"ok": False, "error": "there is nobody here to say goodnight to"}
    if target not in dict(_close_options(state, scn)):
        return {"ok": False, "error": f"{target or 'that'} is not something you can do now"}
    name, _, arg = target.partition(":")
    data = _data().get("close") or {}
    out: dict[str, Any] = {"ok": True, "pid": pid, "closer": name}
    if name == "another_round":
        apply_effect(state, {"type": "social_scene", "op": "round"})
        clock.advance_time(state, float(data.get("another_round_minutes", 30)) / 60.0)
        return out
    made: list[str] = []
    if name == "stay_the_night":
        out.update(stay_the_night(state))
        return out
    if name == "propose":
        out.update(propose(state, pid))
        return out
    if name == "call_it_a_night":
        what, _, value = arg.partition(":")
        if what == "promise":
            from engine.social import promises

            row = promises.make(state, pid, by="player", window=value)
            if row:
                out["promise_id"] = str(row["id"])
        elif what == "plan":
            from engine.social import plans

            kind = str(scn.get("kind") or "")
            if kind == plans.THEIR_PLACE and relationships.household(state) == pid:
                kind = ""                                  # they live with the player now: the engine picks (T18)
            row = plans.make(state, pid, kind=kind if kind in plans.PLAN_KINDS else "", when="soon",
                             venue=str(scn.get("location") or "") if str(scn.get("location") or "") in places.venue_ids() else "")
            if row:
                out["plan_id"] = str(row["id"])
                made.append("meet")
        out.update(end_scene(state, "player", then="stay" if what == "stay" else "home"))
    elif name == "walk_them_home":
        home = places.home_of(state, pid)
        clock.advance_time(state, (places.travel_minutes(home) + float(data.get("walk_extra_minutes", 10))) / 60.0)
        out.update(end_scene(state, "player", then="home"))
    else:                                                  # back_to_yours, back_to_theirs, go_somewhere_else
        from engine.social import plans

        kind, venue = {"back_to_yours": ("your_place", ""), "back_to_theirs": ("their_place", "")}.get(
            name, (str(places.venue(arg).get("kind") or ""), arg))
        out.update(end_scene(state, "player", then="stay", continues=True))
        row = plans.make(state, pid, kind=kind, when="now", venue=venue, in_person=True)
        if row is None:
            out["plan"] = "not tonight"
            _queue_post_meet(state, pid, str(out.get("band") or ""), "", state.world_clock_hours)
        else:
            out["plan_id"] = str(row["id"])
            out["went"] = _go(state, plans.place_of(state, row))
            made.append(CLOSER_COMMITMENTS[name])
    if made:
        apply_effect(state, {"type": "social_scene", "op": "record", "pid": pid, "commitments": made})
        out["recorded"] = made
    return out


# -- staying over (§10.5): logistics only (rule 12) --------------------------------------------------------


def _band_so_far(scn: dict[str, Any]) -> str:
    """The evening's band so far: the moments' average, or the prior before any moment."""
    count = int(scn.get("count", 0))
    return _scene_band(float(scn.get("sum", 0.0)) / count if count else float(scn.get("prior", 0.5)))


def stay_offered(state: GameState) -> bool:
    """Offered at a home (theirs, or the player's flat) when the stage holds `stay_over` AND the evening allows
    it (§10.5): it is going well enough, they have the energy, and they have no early start."""
    scn = current(state)
    pid = str(scn.get("pid") or "")
    where = str(scn.get("location") or "")
    if not pid or not (places.is_home(where) or places.is_flat(where)) or scn.get("stay_asked"):
        return False
    if not growth.willing(state, pid, "stay_over")[0]:
        return False
    stay = _data().get("stay") or {}
    left = convo.boundary_minutes(state, pid, state.world_clock_hours)
    early = (left is not None and left / 60.0 < float(stay.get("early_start_hours", 9))
             and convo._status(state, pid, state.world_clock_hours + left / 60.0 + 0.01) == "work")
    return (_band_so_far(scn) in ("great", "good", "fine")
            and float(scn.get("energy", 0)) > float(stay.get("energy_min", 35)) and not early)


def _stay_drawn(state: GameState, pid: str) -> bool:
    """Whether they say yes: one SOCIAL_SCENE draw against `stay.accept` by archetype alone (F34: no intent
    term; lesson 1: forceable). Inside the `stay` handler (rule 3)."""
    accept = (_data().get("stay") or {}).get("accept") or {}
    chance = float(accept.get(population.profile(state, pid).archetype, accept.get("default", 0.6)))
    return behaviour.person_rng(state, SOCIAL_SCENE, pid).random() < chance


def _not_tonight_reason(state: GameState, pid: str, scn: dict[str, Any]) -> str:
    """Why not tonight, from facts that hold: their energy, or the home's `stay_reasons`. "" when neither."""
    stay = _data().get("stay") or {}
    if float(scn.get("energy", 0)) < float(stay.get("energy_min", 35)) + 10:
        return "they're shattered"
    where = str(scn.get("location") or "")
    if places.is_home(where):
        reasons = ((social.data("homes").get("templates") or {}).get(where) or {}).get("stay_reasons") or ()
        if reasons:
            return str(reasons[0])
    return ""


def _player_morning(state: GameState) -> float:
    """The player's next waking band start, the sleep floor applied (world's `sleep` target)."""
    from engine.social import world

    return float(world._until(state, {"until": "morning"}))


def stay_the_night(state: GameState) -> dict[str, Any]:
    """
    The closer `stay_the_night` (§10.5). Logistics only: they say yes or "not tonight" (one draw in the `stay`
    handler); a yes ends the scene, takes the clock to the player's morning, writes the history row and holds
    the "after the date" text until then. "Not tonight" is a plain answer, never a refusal. T24 (the morning
    scene) is v0.24.0's.
    """
    scn = current(state)
    pid = str(scn.get("pid") or "")
    if not pid:
        return {"ok": False, "error": "there is nobody here to stay with"}
    drawn = apply_effect(state, {"type": "social_scene", "op": "stay"})
    if not drawn.get("accepted"):
        return {"ok": True, "stayed": False, "reason": _not_tonight_reason(state, pid, scn)}
    plan_id = str(scn.get("plan_id") or "")
    ended = end_scene(state, reason="stayed_over", then="stay", continues=True)
    relationships.add_history(state, pid, "stay", "Stayed over")
    clock.advance_time(state, max(0.0, _player_morning(state) - state.world_clock_hours))
    _queue_post_meet(state, pid, str(ended.get("band") or ""), plan_id, state.world_clock_hours)
    return {"ok": True, "stayed": True, "band": str(ended.get("band") or "")}


# -- the long term (§12, T18): proposing, at home -------------------------------------------------------------


def propose(state: GameState, pid: str) -> dict[str, Any]:
    """The closer `propose` (§12.1): offered only while `willing.propose` holds, so they say yes; the stage moves to
    `engaged` (its `engaged_since` written by `social_stage`) and the evening goes on. The step is recorded for the
    fact checks (`recorded`)."""
    ok, why = growth.willing(state, pid, "propose")
    if not ok:
        return {"ok": False, "error": f"not now ({why})"}
    relationships.set_stage(state, pid, ENGAGED, kind="engaged", line="Got engaged")
    apply_effect(state, {"type": "social_scene", "op": "record", "pid": pid, "commitments": ["propose"]})
    return {"ok": True, "engaged": True, "recorded": ["propose"]}


def partner_status(state: GameState, pid: str) -> str:
    """Where the household partner is by their schedule now (`asleep | work | free | out`), or `away` on a holiday
    of theirs (`life.unavailable`). Reads only."""
    from engine.social import life   # lazily: life imports this module's peers

    now = state.world_clock_hours
    return "away" if life.unavailable(state, pid, now) else convo._status(state, pid, now)


def household_present(state: GameState) -> str:
    """The household partner's pid when they are at home with the player and free now (§12.3): someone lives with
    the player, the relationship is still going, the player is in the flat (not at work, no scene open), and their
    schedule says `free`. "" otherwise. Reads only."""
    from engine.social import apps   # lazily: apps reads population, as this module does

    pid = relationships.household(state)
    if not pid or social.scene_open(state) or (state.social or {}).get("at_work"):
        return ""
    if not places.is_flat(state.location_id) or apps.gone(state, pid) or not relationships.live(_person(state, pid)):
        return ""
    return pid if partner_status(state, pid) == "free" else ""


def at_home_options(state: GameState) -> list[tuple[str, str]]:
    """The world verb `scene`'s targets with no scene open (§12.3): spend time with the household partner, when
    they are home and free. Its target opens an at-home scene (`move`)."""
    pid = household_present(state)
    return [(f"{AT_HOME_TARGET}:{pid}", f"Spend time with {_name(state, pid)}")] if pid else []


def plan_wait_options(state: GameState) -> list[tuple[str, str]]:
    """The world verb `scene`'s "Wait for {name}" targets with no scene open (A4 W2): an open `now` / `tonight`
    plan whose place is here and whose person has not arrived yet (`plans.waiting_here`). Reads only."""
    from engine.social import plans   # lazily: plans imports this module's peers

    if social.scene_open(state):
        return []
    out: list[tuple[str, str]] = []
    for row in plans.waiting_here(state):
        target = (f"{PLAN_TARGET}:{row['id']}", f"Wait for {_name(state, str(row['pid']))}")
        if target not in out:
            out.append(target)
    return out


def wait_for_plan(state: GameState, plan_id: str) -> dict[str, Any]:
    """
    "Wait for {name}" (A4 W2): the clock moves (rule 2) to the plan's `arrives_at`, at most plans.yaml
    `arrival.wait_cap_hours` on, then `plans.meet_if_here` opens the scene if they are here. Waiting is never
    refused while it is offered; a flake that lands during the wait leaves the player waiting alone.
    """
    from engine.social import plans   # lazily: plans imports this module's peers

    if f"{PLAN_TARGET}:{plan_id}" not in dict(plan_wait_options(state)):
        return {"ok": False, "error": "there is nobody on their way here to wait for"}
    row = plans.get(state, plan_id) or {}
    pid = str(row.get("pid") or "")
    now = state.world_clock_hours
    until = min(plans.arrives_at(row), now + plans.wait_cap_hours())
    clock.advance_time(state, max(0.0, until - now) + 1e-6)      # a hair past, so the event at `until` runs
    met = plans.meet_if_here(state)
    out: dict[str, Any] = {"ok": True, "pid": pid, "move": PLAN_TARGET, "plan_id": plan_id,
                           "waited_hours": round(state.world_clock_hours - now, 4)}
    if met.get("scene"):
        out.update(met=plan_id, opened=str(met.get("scene")), words=f"{_name(state, pid)} arrives.")
    elif (plans.get(state, plan_id) or {}).get("status") != "open":
        out["words"] = f"{_name(state, pid)} isn't coming."
    else:
        out["words"] = f"You wait. No sign of {_name(state, pid)} yet."
    return out


def approach_options(state: GameState) -> list[tuple[str, str]]:
    """The world verb `scene`'s "Go over to {name}" targets with no scene open (A4 W9): each person the player
    knows who is at this venue by chance (`presence.chance_here`). Reads only; ignoring them costs nothing."""
    if social.scene_open(state):
        return []
    from engine.social import presence   # lazily: presence reads this module

    people = (state.social or {}).get("people") or {}
    now = presence.block_key(state)
    return [(f"{APPROACH_TARGET}:{pid}", f"Go over to {_name(state, pid)}")
            for pid in presence.chance_here(state, str(state.location_id or ""))
            if (people.get(pid) or {}).get("chance_met") != now]      # talked to this block: still here, not again


def approach(state: GameState, pid: str) -> dict[str, Any]:
    """
    "Go over to {name}" (A4 W9): a `chance` scene with someone here by chance, no plan needed. An open `soon` plan
    with them is recorded `met`. Its prior takes scenes.yaml `chance.prior_bias`; its end is gated by `willing`
    (`_end`, C3), and so are its plan-making closers (`_close_options`).
    """
    if f"{APPROACH_TARGET}:{pid}" not in dict(approach_options(state)):
        return {"ok": False, "error": "there is nobody here you know to go over to"}
    from engine.social import plans   # lazily: plans imports this module's peers

    soon = next((r for r in plans.open_for(state, pid) if r.get("when") == "soon" and r.get("kind") != plans.WEDDING),
                None)
    opened = open_scene(state, pid, str(state.location_id), plan_id=str(soon["id"]) if soon else "", kind=CHANCE)
    if not opened.get("ok"):
        return {"ok": False, "error": str(opened.get("error") or "that can't be done now")}
    out: dict[str, Any] = {"ok": True, "pid": pid, "move": APPROACH_TARGET, "opened": CHANCE,
                           "words": f"You go over to {_name(state, pid)}."}
    if soon:
        out["met"] = str(soon["id"])
    return out


def open_at_home(state: GameState, pid: str) -> dict[str, Any]:
    """An at-home scene with the household partner (§12.3): no plan, no travel, here in the flat."""
    if not pid or pid != household_present(state):
        return {"ok": False, "error": "there is nobody at home to spend time with"}
    opened = open_scene(state, pid, state.location_id, kind=AT_HOME)
    if not opened.get("ok"):
        return {"ok": False, "error": str(opened.get("error") or "that can't be done now")}
    return {"ok": True, "pid": pid, "move": AT_HOME_TARGET, "opened": AT_HOME,
            "words": f"You and {_name(state, pid)} spend the evening together at home."}


def present_pid(state: GameState) -> str:
    """Who is with the player in person for the narrator: the open scene's person, else the household partner at
    home and free (`household_present`). "" with neither."""
    return str(current(state).get("pid") or "") or household_present(state)


def household_line(state: GameState) -> str:
    """The narrator's household line (§12.3): who lives with the player, and where they are now by their
    schedule. "" with no household, or while the player is in a scene with them (the scene's lines say it)."""
    pid = relationships.household(state)
    if not pid or str(current(state).get("pid") or "") == pid:
        return ""
    name = _name(state, pid)
    where = {"free": "is home", "asleep": "is asleep", "work": "is at work", "out": "is out",
             "away": "is away"}.get(partner_status(state, pid), "is out")
    if where == "is home" and not places.is_flat(state.location_id):
        where = "is at home"
    return f"{name} lives with you, and {where}."


# -- the narration's archive rows (§7.1) --------------------------------------------------------------


def _scene_pid(state: GameState, session: Any) -> str:
    """The person of the scene this turn played: the one open now, or the one a closer or a move of this turn
    ended (its receipt names them)."""
    pid = str(current(state).get("pid") or "")
    if pid:
        return pid
    receipts = ((getattr(session, "last_turn", None) or {}).get("tool_receipts") or ())
    for receipt in receipts:
        if isinstance(receipt, dict) and receipt.get("skill") in ("social_scene", "social_close"):
            result = receipt.get("result")
            if isinstance(result, dict) and result.get("pid"):
                return str(result["pid"])
    return ""


def archive_turn(session: Any, narration: str) -> None:
    """
    `run_turn`'s post-turn hook (pre-flight F30): a scene turn's narration appended to the run's archive as a
    `scene` row in the person's thread (CALLER HOLDS the turn lock), numbered like a message. Never into state
    or memory (§7.1). Nothing when no scene was played this turn, the narration is empty, or the run has no save
    directory yet. A fault is logged, never raised: a turn that happened is not undone by its archive row.
    """
    from engine.social import archive

    try:
        state = session.engine.state
        pid = _scene_pid(state, session)
        text = str(narration or "").strip()
        if not pid or not text:
            return
        tid = messaging.thread_for(state, pid)
        directory = archive.save_dir(session)
        if not tid or directory is None or not directory.is_dir():
            return
        made = apply_effect(state, {"type": "social_scene", "op": "turn"})
        row = {"id": str(made["id"]), "thread_id": tid, "from": "system", "kind": "scene", "pid": pid,
               "at": round(float(state.world_clock_hours), 4), "bubbles": [text]}
        if not archive.append(directory, [row], kind="scene"):
            logger.warning("[social] A scene turn's archive row was not written (operation=archive_turn, pid=%s)", pid)
    except Exception as exc:  # noqa: BLE001 -- the turn happened; only its archive row is lost
        logger.warning("[social] A scene turn's archive row failed (operation=archive_turn): %s", exc)


# -- the effect (rule 3) ----------------------------------------------------------------------------------


def _kept() -> int:
    return max(1, int(social.setting("scene_moments_kept", 12)))


@effect_kind("social_scene")
@recorded
def _e_scene(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: the open scene (spec §10). Ops: `open` (the row, its prior drawn), `moment` (a move scored,
    its draw, its band's exact regard, energy spent, they may close), `round` (another round: energy back),
    `phone` (the phone out in company), `stay` (their answer to staying the night, one draw), `record` (a closer's commitments on the person), `turn` (a scene
    turn's archive number) and `end` (the band, the counts, the episode closed, numbers, the stage,
    `post_meet`, the scene cleared). No op moves the clock (rule 2).
    """
    if not state.social:
        return {"type": "social_scene", "ok": False, "text": "no social slice"}
    op = str(effect.get("op") or "")
    at = float(effect["at"]) if effect.get("at") is not None else state.world_clock_hours
    if op == "open":
        return _open(state, effect, at)
    if op == "turn":
        counters = state.social.setdefault("counters", {})
        counters["message"] = int(counters.get("message", 0)) + 1
        return {"type": "social_scene", "ok": True, "text": "a scene turn numbered", "id": f"m{counters['message']}"}
    if op == "record":
        pid = str(effect.get("pid") or "")
        person = state.social.setdefault("people", {}).setdefault(pid, {})
        person["recorded"] = sorted({str(c) for c in effect.get("commitments") or ()})
        relationships.touch(person)
        return {"type": "social_scene", "ok": True, "text": f"{pid}: recorded {person['recorded']}"}
    scn = state.social.get("scene") or {}
    if not scn.get("pid"):
        return {"type": "social_scene", "ok": False, "text": "no scene is open"}
    if op == "moment":
        return _moment(state, scn, effect, at)
    if op == "round":
        share = float((_data().get("close") or {}).get("another_round_energy", 0.34))
        scn["energy"] = round(min(100.0, float(scn.get("energy", 0)) + 100.0 * share), 4)
        scn["misstep_run"] = 0
        scn["closing"] = ""
        return {"type": "social_scene", "ok": True, "text": "another round", "pid": scn["pid"]}
    if op == "phone":
        pid = str(scn["pid"])
        if _rude(state, pid):
            row = (((_data().get("moves") or {}).get("phone") or {}).get("bands") or {}).get("misstep") or {}
            if row:
                relationships.apply_regard_exact(state, pid, **{k: int(v) for k, v in row.items() if k in REGARD_KEYS})
        return {"type": "social_scene", "ok": True, "text": "the phone, in company", "pid": pid}
    if op == "end":
        return _end(state, scn, effect, at)
    if op == "stay":
        accepted = bool(_stay_drawn(state, str(scn["pid"])))
        if not accepted:
            scn["stay_asked"] = True                    # a "not tonight" holds for the rest of this scene
        return {"type": "social_scene", "ok": True, "text": "asked to stay", "pid": scn["pid"],
                "accepted": accepted}
    return {"type": "social_scene", "ok": False, "text": f"{op!r} is no scene op"}


def _open(state: GameState, effect: dict[str, Any], at: float) -> dict[str, Any]:
    pid = str(effect.get("pid") or "")
    if (state.social.get("scene") or {}).get("pid"):
        return {"type": "social_scene", "ok": False, "text": "a scene is already open"}
    person = (state.social.get("people") or {}).get(pid)
    if not isinstance(person, dict):
        return {"type": "social_scene", "ok": False, "text": f"{pid!r} is not someone the player knows"}
    prior = _prior_terms(state, pid) + _prior_draw(state, pid)
    if effect.get("kind") == CHANCE:                    # nobody planned the evening (W9)
        prior += float((_data().get("chance") or {}).get("prior_bias", 0.0) or 0.0)
    state.social["scene"] = {
        "pid": pid, "plan_id": str(effect.get("plan_id") or ""), "location": str(effect.get("location") or ""),
        "kind": str(effect.get("kind") or "date"), "started_at": round(at, 4), "moments": [],
        "energy": round(max(0.0, min(100.0, 100.0 * prior)), 4), "prior": round(prior, 6), "closing": "",
        "sum": 0.0, "count": 0, "misstep_run": 0,
    }
    person.pop("recorded", None)                       # what a closer recorded last time is behind them
    relationships.touch(person)
    return {"type": "social_scene", "ok": True, "text": f"a scene with {pid} opened", "pid": pid,
            "save_reason": "stage"}


def _moment(state: GameState, scn: dict[str, Any], effect: dict[str, Any], at: float) -> dict[str, Any]:
    pid = str(scn["pid"])
    name, topic = str(effect.get("move") or ""), str(effect.get("topic") or "")
    row = (_data().get("moves") or {}).get(name)
    if row is None:
        return {"type": "social_scene", "ok": False, "text": f"{name!r} is no move"}
    wedding = scn.get("kind") == WEDDING
    if wedding and name not in ((_data().get("wedding") or {}).get("moves") or ()):
        return {"type": "social_scene", "ok": False, "text": f"{name!r} is not a move at the wedding"}
    too_deep = name == "ask_about" and _topic_rung(topic) > growth.depth(state, pid)
    draw = _moment_draw(state, pid)                     # always drawn, so a replay keeps its counter (rule 4)
    score = (float(scn.get("prior", 0.5)) + _fit(state, pid, row) + _topic_fit(state, pid, name, topic)
             + _mood_term(state, pid) + draw)
    if too_deep:
        band = str(_data().get("too_deep_band") or "flat")
        cut = (_data().get("moment") or {}).get("bands") or {}
        above = BANDS[max(0, BANDS.index(band) - 1)]
        if band != BANDS[0]:
            score = min(score, float(cut.get(above, score)) - 1e-6)   # its average counts it as its band
    elif name == "phone" and _rude(state, pid):
        band = "misstep"                                # their `in_company` habit: they mind (§10.3)
    else:
        band = _band_of(score)
    if wedding and BANDS.index(band) > BANDS.index("fine"):
        band = "fine"                                   # the wedding cannot go badly (§12.2): floored at fine
        score = max(score, float(((_data().get("moment") or {}).get("bands") or {}).get("fine", score)))
    moves = {k: int(v) for k, v in ((row.get("bands") or {}).get(band) or {}).items() if k in REGARD_KEYS}
    if moves:
        relationships.apply_regard_exact(state, pid, **moves)
    minutes = float(row.get("minutes", 15))
    moments = scn.setdefault("moments", [])
    moment = {"move": name, "topic": topic, "band": band, "minutes": minutes, "score": round(score, 6)}
    if too_deep:
        moment["too_deep"] = True                       # its words are "they steer the talk" (`receipt_lines`)
    moments.append(moment)
    del moments[:max(0, len(moments) - _kept())]
    scn["sum"] = round(float(scn.get("sum", 0.0)) + score, 6)
    scn["count"] = int(scn.get("count", 0)) + 1
    cost = float(((_data().get("moment") or {}).get("energy_cost") or {}).get(band, 8))
    scn["energy"] = round(max(0.0, float(scn.get("energy", 0)) - cost), 4)
    scn["misstep_run"] = int(scn.get("misstep_run", 0)) + 1 if band == "misstep" else 0
    closing = _closing(state, scn, pid, at + minutes / 60.0)
    scn["closing"] = closing
    relationships.touch(state.social["people"][pid])
    result: dict[str, Any] = {"type": "social_scene", "ok": True, "text": f"{name}: {band}", "pid": pid,
                              "band": band, "score": round(score, 6), "too_deep": too_deep}
    if closing:
        result["closed"] = closing
    return result


def _closing(state: GameState, scn: dict[str, Any], pid: str, after: float) -> str:
    """Why they close now ("" when they don't): their energy spent, a run of missteps, or their schedule."""
    rules = _data().get("close") or {}
    if scn.get("kind") == WEDDING:                      # its moments, and nothing else, end it (§12.2)
        return WEDDING if int(scn.get("count", 0)) >= int((_data().get("wedding") or {}).get("moments", 3)) else ""
    if float(scn.get("energy", 0)) <= float(rules.get("energy_out", 0)):
        return "energy"
    if int(scn.get("misstep_run", 0)) >= int(rules.get("misstep_run", 2)):
        return "missteps"
    left = convo.boundary_minutes(state, pid, after)
    if left is not None and left <= float((social.data("conversation").get("talk") or {}).get("boundary_minutes", 20)):
        return "schedule"
    return ""


def _post_meet_skipped(state: GameState, pid: str, band_name: str) -> bool:
    post = _rules().get("post_meet") or {}
    return (band_name in (post.get("none_after") or ())
            or population.profile(state, pid).archetype in (post.get("none_from") or ()))


def _post_meet_at(state: GameState, pid: str, at: float) -> float:
    """When their `post_meet` text is due: at their own pace after the scene, at their next available time
    (a draw on SOCIAL_PACE: inside the `end` handler, rule 3)."""
    person = population.profile(state, pid)
    arch = behaviour.archetype(person.archetype)
    minutes = behaviour.lognormal_minutes(behaviour.person_rng(state, SOCIAL_PACE, pid), *arch.reply_minutes)
    pace = float((_rules().get("post_meet") or {}).get("pace_mult", 1.0))
    return convo.next_available(state, pid, at + minutes * pace / 60.0)


def _queue_post_meet(state: GameState, pid: str, band: str, plan_id: str, at: float) -> None:
    """Their "after the date" text, unless the band, their archetype or a ghosting says none."""
    person = state.social["people"][pid]
    tid = messaging.thread_for(state, pid)
    if tid and not _post_meet_skipped(state, pid, band) and not person.get("ghosted"):
        messaging.queue_due(state, pid, tid, Decision(situation="post_meet", plan_id=plan_id),
                            _post_meet_at(state, pid, at))


def _end(state: GameState, scn: dict[str, Any], effect: dict[str, Any], at: float) -> dict[str, Any]:
    pid = str(scn["pid"])
    person = state.social["people"][pid]
    count = int(scn.get("count", 0))
    band = _scene_band(float(scn.get("sum", 0.0)) / count) if count else _scene_band(float(scn.get("prior", 0.5)))
    person["scenes_done"] = int(person.get("scenes_done", 0)) + 1
    relationships.touch(person)
    from engine.social import plans   # lazily: plans imports this module's peers

    plan = plans.get(state, str(scn.get("plan_id") or ""))
    if plan is not None:
        plan["band"] = band                             # how it went, for their post_meet text (voicing)
    ep = convo.episode(state, pid)
    if ep is not None and ep.get("kind") == "scene":
        ep["band"] = band                               # the recap's band words (memory.recap_fallback)
        apply_effect(state, {"type": "social_episode", "op": "close", "pid": pid, "at": at, "end": "scene_end"})
    where = _where_words(state, scn)
    kind = str(scn.get("kind") or "")
    chance = kind == CHANCE                             # read before the row is cleared
    state.social["scene"] = {}
    stage = str(person.get("stage") or "")
    # A chance meeting (W9, C3) moves the number swap and `numbers -> meeting` only as far as `willing` holds NOW;
    # every other kind's plan already passed `meet`. Each gate is asked only where its move could happen.
    if band in NUMBER_BANDS and 0 <= stage_rank(stage) < stage_rank(NUMBERS) and (
            not chance or growth.willing(state, pid, "number")[0]):
        relationships.set_stage(state, pid, NUMBERS, at=at, kind="numbers", line="Swapped numbers in person")
        messaging.open_numbers(state, pid)              # v0.22's number path (§15.3)
    if person.get("stage") == NUMBERS and (not chance or growth.willing(state, pid, "meet")[0]):
        relationships.set_stage(state, pid, MEETING, at=at)
    if chance:                                          # gone over to once: not offered again this block (W9)
        from engine.social import presence   # lazily: presence reads this module

        person["chance_met"] = presence.block_key(state)
    if band in GOOD_BANDS and (not chance or stage_rank(str(person.get("stage") or "")) >= stage_rank(MEETING)):
        person["meets_good"] = int(person.get("meets_good", 0)) + 1    # a pre-meeting run-in pre-pays no branch (C3)
        relationships.touch(person)
    relationships.advance_stage(state, pid, at=at)      # two good-or-better: meeting -> its branch
    married = kind == WEDDING and person.get("stage") == ENGAGED
    if married:                                         # the wedding's end (§12.1): the trigger `event`
        relationships.set_stage(state, pid, MARRIED, at=at, kind="married", line="Got married")
    else:
        relationships.add_history(state, pid, "scene", f"{where}: {recap_line(band)}", at=at)
    # No "after the date" text from home, the wedding or a run-in: texter.md has no chance follow-up row (W9).
    if not effect.get("continues") and kind not in (AT_HOME, WEDDING, CHANCE):
        _queue_post_meet(state, pid, band, str(scn.get("plan_id") or ""), at)
    from engine.social import life   # lazily: life imports this module's peers

    found = life.seen_check(state, pid)                  # seen out with someone else (§12.4)
    out = {"type": "social_scene", "ok": True, "text": f"the scene with {pid} ended {band}", "pid": pid,
           "band": band, "reason": str(effect.get("reason") or ""), "save_reason": "stage"}
    if married:
        out["married"] = True
    if found:
        out["seen_by"] = found
    return out


# -- the payload (pre-flight F18; T23's Companion reads `phone.scene`) ----------------------------------------


@section("scene")
def _scene_section(state: GameState, session: Any) -> dict[str, Any]:
    """Who the player is with, while a scene is open: their name, the stage's words, the closeness band's words
    and their portrait (the helpers v0.22's `contacts` section uses). Words only, never a number; {} otherwise."""
    pid = str(current(state).get("pid") or "")
    if not pid:
        return {}
    from engine.social import media   # lazily: media imports messaging's peers

    person_state = _person(state, pid)
    stage = str(person_state.get("stage") or "")
    return {"pid": pid, "name": _name(state, pid),
            "stage_words": relationships.stage_words(stage) if stage else "",
            "closeness_words": relationships.band(person_state) if stage else "",
            "portrait": media.portrait_url(state, pid)}


def household_card(state: GameState) -> dict[str, Any]:
    """The world view's household card (v0.23.0 T23, spec §12.3): who lives with the player and, in words,
    where they are now by their schedule (`home | asleep | at work | out | away`). Words only, never a number;
    {} with no household."""
    pid = relationships.household(state)
    if not pid:
        return {}
    from engine.social import media   # lazily: media imports messaging's peers

    status = partner_status(state, pid)
    words = {"free": "home", "asleep": "asleep", "work": "at work", "out": "out", "away": "away"}.get(status, "out")
    if words == "home" and not places.is_flat(state.location_id):
        words = "at home"
    return {"pid": pid, "name": _name(state, pid), "where": words, "portrait": media.portrait_url(state, pid)}


def narration_line(state: GameState) -> str:
    """The narrator's scene line (`world.narration_block`): who the player is with, and where. With no scene open,
    the household partner at home and free (§12.3, T18). "" with neither."""
    scn = current(state)
    pid = str(scn.get("pid") or "")
    if not pid:
        home = household_present(state)
        return f"You are with {_name(state, home)}, in person: at home." if home else ""
    return f"You are with {_name(state, pid)}, in person: {_where_in_a_line(state, scn)}."


# -- the companion in the narration (v0.23.0 spec §10.6, T15) -------------------------------------------------

#: The engine's words for a closer, as the scene's receipt lines say it (`receipt_lines`).
CLOSER_WORDS: dict[str, str] = {
    "call_it_a_night": "You call it a night.", "another_round": "You stay a while longer.",
    "walk_them_home": "You walk them home.", "back_to_yours": "You ask them back to yours.",
    "back_to_theirs": "You go back to theirs.", "stay_the_night": "You stay the night.",
    "propose": "You ask them to marry you. They say yes.",
}
#: Why a scene ended by itself, in the engine's words (`receipt_lines`); any other reason is them calling it a night.
CLOSED_WORDS: dict[str, str] = {WEDDING: "You are married."}
#: A scene's receipts: the skills its verbs run (`intents`' `scene`, `close` and, at the flat, `do`).
SCENE_SKILLS: tuple[str, ...] = ("social_scene", "social_close", "social_do")


def _moment_words(state: GameState, pid: str, row: dict[str, Any]) -> str:
    """A kept moment row in the engine's words ("You ask about your work. It lands.")."""
    name, topic = str(row.get("move") or ""), str(row.get("topic") or "")
    return _band_words(name, str(row.get("band") or ""), _topic_label(name, topic) if topic else "",
                       too_deep=bool(row.get("too_deep")))


def _this_moment(state: GameState, scn: dict[str, Any]) -> str:
    """"This moment: {move} — {band words} — {topic label}", from the scene's last moment (engine words)."""
    moments = scn.get("moments") or []
    if not moments and not scn:
        return "This moment: the two of you are at home."      # the household partner, no scene (T18)
    if not moments:
        if scn.get("kind") == CHANCE:
            return "This moment: the two of you have just run into each other."
        return "This moment: the two of you have just met up."
    row = moments[-1]
    name, topic, band = str(row.get("move") or ""), str(row.get("topic") or ""), str(row.get("band") or "")
    label = _topic_label(name, topic) if topic else ""
    move_words = MOVE_WORDS.get(name, name).format(topic=label or "something")
    went = TOO_DEEP_WORDS if row.get("too_deep") else BAND_WORDS.get(band, "")
    return " — ".join(filter(None, [f"This moment: {move_words}", went, label]))


def companion_block(state: GameState, *, tokens: int) -> str:
    """
    The companion block (§10.6): who is with the player, in person, from the texter's own builders --
    `growth.who_now`, where you are, the person's memory parts (`story`, the last 3 recaps, `open`,
    `bridge`: voicing's block builders over a snapshot of them) through `memory.budgeted`, and this moment
    in the engine's words -- budgeted to ``tokens``. Plain titled lines; no register line (rule 12).
    With no scene open, the household partner at home and free (§12.3, T18), where "at home". "" with neither.
    Reads only.
    """
    scn = current(state)
    pid = str(scn.get("pid") or "") or household_present(state)
    if not pid:
        return ""
    from engine.memory.budget import estimate_messages
    from engine.social import memory, voicing

    name = _name(state, pid)
    snap = _snapshot(state, pid)
    titles = {
        "who_now": f"Who {name} is now, in {name}'s own words (\"you\" there means {name}, \"they\" means you):",
        "story": f"Your story together, as {name} tells it (\"you\" there means {name}, \"they\" means you):",
        "open": f"Still open between you, as {name} tells it:",
        "bridge": f"How you left it last time (\"you\" there is {name}):",
    }
    head = f"WITH YOU IN PERSON: {name}"
    frame = (f"In the lines below told in {name}'s own words, \"you\" means {name} and \"they\" means you; "
             f"in every other line, \"you\" is you.")
    overhead = estimate_messages([{"content": "\n".join([head, frame, *titles.values()])}])
    parts = memory.budgeted({
        "who_now": voicing._flat(voicing._who_now(snap)), "story": voicing._story(snap),
        "episodes": "\n".join(voicing._episodes(snap).split("\n")[-3:]),
        "open": voicing._flat(voicing._still_open(snap)), "bridge": voicing._flat(voicing._bridge(snap)),
        "now": f"Where you are: {_where_in_a_line(state, scn) if scn else 'At home'}.\n{_this_moment(state, scn)}",
    }, max(0, int(tokens) - overhead))
    where, moment = parts["now"].split("\n", 1)
    story = "\n".join(filter(None, [parts["story"], parts["episodes"]]))
    lines = [head, frame, titles["who_now"], parts["who_now"], where]
    if story:
        lines += [titles["story"], story]
    lines += [titles["open"], parts["open"]]
    if parts["bridge"]:
        lines += [titles["bridge"], parts["bridge"]]
    lines.append(moment)
    return "\n".join(line for line in lines if line)


def _snapshot(state: GameState, pid: str) -> Any:
    """The voicing builders' view of ``pid`` (deep copies; no due message): their profile, their row, their
    memory, who they are now and the promises open between you."""
    from engine.social import life, memory, promises, voicing

    at = float(state.world_clock_hours)
    row = _person(state, pid)
    return voicing.PersonSnapshot(
        pid=pid, thread_id=messaging.thread_for(state, pid) or "",
        profile=dataclasses.asdict(life.person_now(state, pid)),
        dynamic={k: copy.deepcopy(v) for k, v in row.items() if k != "memory"}, tail=[], summary="", due=[],
        proposals=(), player=copy.deepcopy(state.social.get("player") or {}), now={"at": at}, contacts=(),
        seed=int(state.rng_seed), memory=memory.person(state, pid), who_now=growth.who_now(state, pid),
        open_promises=tuple(voicing._promise_line(r, at) for r in promises.open_by(state, pid)))


def _close_words(state: GameState, receipt: dict[str, Any], result: dict[str, Any]) -> str:
    """A closer in the engine's words, and how the evening went when it ended the scene."""
    target = str((receipt.get("intent") or {}).get("target") or (receipt.get("args") or {}).get("target") or "")
    name, _, arg = target.partition(":")
    what, _, value = arg.partition(":")
    if name == "call_it_a_night" and what == "promise":
        from engine.social import promises

        row = ((state.social.get("promises") or {}).get(str(result.get("promise_id") or "")) or {"window": value})
        words = f"You call it a night, and say you'll message them {promises.window_words(row, speaker='player')}."
    elif name == "call_it_a_night" and what == "plan":
        words = "You call it a night, and say you'll do it again soon."
    elif name == "call_it_a_night" and what == "stay":
        words = "You say goodnight, and stay here a while."
    elif name == "go_somewhere_else":
        words = f"You go on to {places.label(arg)} together."
    elif name == "stay_the_night" and result.get("stayed") is False:
        why = str(result.get("reason") or "")
        words = "You ask them to stay the night. Not tonight" + (f": {why}." if why else ".")
    else:
        words = CLOSER_WORDS.get(name, "")
    band = str(result.get("band") or "")
    return " ".join(filter(None, [words, recap_line(band) if band else ""]))


def narrator_lines(state: GameState) -> str:
    """The narrator's scene lines (`world.narration_block`): the scene line and the companion block,
    budgeted to `social.world.companion_tokens`. With no scene open, the same for the household partner at
    home and free (§12.3, T18). "" with neither."""
    if not social.scene_open(state) and not household_present(state):
        return ""
    return "\n".join(filter(None, [narration_line(state), companion_block(
        state, tokens=int(social.setting("world.companion_tokens", 1200)))]))


#: The correction lines over a scene's NARRATION (review M1): the narrator's frame -- "you" the player, the
#: companion by name -- where voicing's `CORRECTIONS` speak to the texter ("you" the person). Facts only.
SCENE_CORRECTIONS: dict[str, str] = {
    "profile_contradicted": "Your narration got a fact about {name} wrong ({detail}). Rewrite it with the facts "
                            "WITH YOU IN PERSON gives.",
    "another_person": "Your narration had {name} name {detail}, someone {name} does not know. Rewrite it "
                      "without that.",
    "stage_claimed": "Your narration said \"{detail}\", but you and {name} are not there yet. Rewrite it without "
                     "saying so.",
    "promise_claimed": "Your narration said \"{detail}\", a promise to message that was not made that way. "
                       "Rewrite it with only the promises the receipt states, or none.",
    "plan_claimed": "Your narration said \"{detail}\", but you and {name} have no such plan. Rewrite it to agree "
                    "with your plans.",
    "commitment_claimed": "Your narration said \"{detail}\", but that step is not one you and {name} are taking "
                          "now. Rewrite it without it.",
}
SCENE_CORRECTION_DEFAULT = "Your narration did not match what has happened ({check}: {detail}). Rewrite it."
#: The most choices the engine offers with the receipt lines (review M6).
FALLBACK_CHOICES = 4


def engine_choices(state: GameState) -> list[dict[str, Any]]:
    """The engine's own choices (review M6): the legal moves now (`intents.legal_intents`), one per verb in
    turn, at most `FALLBACK_CHOICES`, each carrying its intent. What ships with the receipt lines, never a
    rejected draft's choices."""
    from engine.game.intents import legal_intents

    verbs = [v for v in legal_intents(state) if not v.extra]
    queues = [list(v.options) or [("", v.action)] for v in verbs]
    out: list[dict[str, Any]] = []
    while len(out) < FALLBACK_CHOICES and any(queues):
        for verb, queue in zip(verbs, queues):
            if queue and len(out) < FALLBACK_CHOICES:
                target, label = queue.pop(0)
                intent = {"action": verb.action, "target": target} if target else {"action": verb.action}
                out.append({"id": "abcd"[len(out)], "text": str(label)[:100], "intent": intent})
    return out


def receipt_lines(state: GameState, receipts: Optional[Sequence[dict[str, Any]]] = None) -> str:
    """
    The engine's words for the scene's last moment (§10.6; §21's no-model scene): who you are with and
    where, while the scene is open, then what this turn did -- from ``receipts`` (this turn's scene skills:
    a move, a closer, a shared activity), else from the open scene's last moment. What ships in place of
    narration that failed the fact checks twice, or when no model narrated. Reads only.
    """
    lines = [narration_line(state)]
    done: list[str] = []
    for receipt in receipts or ():
        result = receipt.get("result") if isinstance(receipt, dict) else None
        if not isinstance(result, dict) or receipt.get("skill") not in SCENE_SKILLS or not result.get("ok"):
            continue
        if receipt["skill"] == "social_scene":
            done.append(str(result.get("words") or ""))
            if result.get("closed_by_them"):
                said = CLOSED_WORDS.get(str(result["closed_by_them"]), "They call it a night.")
                done.append(f"{said} {result.get('scene_words') or ''}".strip())
        elif receipt["skill"] == "social_close":
            done.append(_close_words(state, receipt, result))
        elif result.get("together"):
            done.append(f"{result.get('narrate') or ''} You do it together.".strip())
        elif result.get("narrate"):
            done.append(str(result["narrate"]))       # an activity at home, the partner there (T18)
    if receipts is None:
        scn = current(state)
        moments = scn.get("moments") or []
        if moments:
            done.append(_moment_words(state, str(scn["pid"]), moments[-1]))
    return "\n".join(line for line in lines + done if line)


@dataclasses.dataclass
class ProseCheck:
    """
    The storyteller's prose seam for a scene turn (§10.6, I10; `StorytellerAgent.run_turn(prose_check=)`),
    built by `default_state.run_turn` only when a scene was open as the turn began (`prose_check`).
    `check` runs `agreement.check_scene_prose` over a draft; `correction` is the one line the retry
    carries; `fallback` is the receipt lines that ship after a second failure (logged at INFO with the
    check names only, never the prose, and counted through `on_fallback`), or when no model narrated.
    """

    state: GameState
    pid: str
    receipts: tuple[dict[str, Any], ...]
    on_fallback: Any = None
    context: str = ""          # the scene's lines as the turn began (review I1): the prompt's when a closer ended it
    at_home: bool = False      # the household partner at home, no scene open as the turn began (T18 fix I3)

    def moment(self) -> dict[str, Any]:
        """This turn's moment as the checks read it: the closer, and the promise or plan a closer made."""
        out: dict[str, Any] = {}
        for receipt in self.receipts:
            result = receipt.get("result") if isinstance(receipt, dict) else None
            if isinstance(result, dict) and receipt.get("skill") in SCENE_SKILLS and result.get("ok"):
                for key in ("closer", "promise_id", "plan_id"):
                    if result.get(key):
                        out[key] = result[key]
        return out

    def check(self, narration: str) -> list[Any]:
        checks = agreement.HOME_PROSE_CHECKS if self.at_home else agreement.SCENE_PROSE_CHECKS
        return agreement.check_scene_prose(narration, agreement.scene_view(self.state, self.pid), self.moment(),
                                           checks=checks)

    def correction(self, found: Sequence[Any]) -> str:
        """One line: each failed check's correction, in the narrator's frame (`SCENE_CORRECTIONS`, review M1)."""
        firsts: list[Any] = []
        for failure in found:
            if all(f.check != failure.check for f in firsts):
                firsts.append(failure)
        name = _name(self.state, self.pid)
        said = " ".join(SCENE_CORRECTIONS.get(f.check, SCENE_CORRECTION_DEFAULT).format(
            name=name, detail=f.detail, check=f.check) for f in firsts)
        return f"The scene's fact check on {name} failed: {said}"

    def choices(self) -> list[dict[str, Any]]:
        """The engine's choices, shipped with the receipt lines (review M6)."""
        return engine_choices(self.state)

    def receipts_text(self) -> str:
        return receipt_lines(self.state, self.receipts) or narration_line(self.state) or f"You are with {_name(self.state, self.pid)}."

    def fallback(self, found: Sequence[Any]) -> str:
        """The receipt lines, after a second failure: logged (check names only) and counted."""
        names = sorted({f.check for f in found})
        logger.info("[social] Scene narration failed its fact checks twice; the receipt lines ship "
                    "(operation=scene_prose, pid=%s, checks=%s)", self.pid, ",".join(names))
        hook = self.on_fallback
        if hook is not None:
            try:
                hook()
            except Exception:  # noqa: BLE001 -- a metric must never fail a turn
                logger.warning("[social] The scene-prose metric was not recorded (operation=scene_prose)")
        return self.receipts_text()


def prose_check(state: GameState, pid: str, receipts: Sequence[dict[str, Any]], *,
                on_fallback: Any = None, context: str = "", at_home: bool = False) -> Optional[ProseCheck]:
    """The prose seam for a turn that began in a scene with ``pid``, or at home with the household partner and no
    scene open (``at_home``: only `agreement.HOME_PROSE_CHECKS`, T18) -- None without one. ``context``: the
    `narrator_lines` read before the intent ran."""
    if not pid:
        return None
    return ProseCheck(state=state, pid=pid, receipts=tuple(r for r in receipts if isinstance(r, dict)),
                      on_fallback=on_fallback, context=context, at_home=at_home)

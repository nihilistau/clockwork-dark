"""
Agreement checks (v0.22.0 spec §11.5): the phone's third audit question --
does a model-voiced reply agree with what the engine holds?

The checks test agreement with FACTS only: media attached or not, the stage
reached, the person's own age, job and neighbourhood, the player's, the
names they can know, the bubble count, a decline's wording. They never judge
tone, register or explicitness (rule 12): every phrase they look for is the
story's own (`relationships.yaml`'s `claims`, `media_claims`,
`media_denials`, `agree_phrases`, `negations`, `ordinary_names`), and the
engine only matches it, as a whole phrase, case-folded.

A check is PURE over ``(reply, decision, view)`` (Plan decision 24): no
state, no RNG, no write. A failure is a judgement handed back to the voicer
(T13, T14), which retries, drops or falls back; the checks never change the
reply or the world (rule 1). The spec's ``check(reply, decision, state,
pid)`` is ``check(reply, decision, view_from_state(state, pid))``.

Precision first (A2's rule: a check that fires on good prose is worse than
none). So a phrase is matched only in a STATEMENT (a clause not ending in
``?``) for the claim checks, a claim is skipped when one of the story's
negations stands in the three words before it, an age is read only where it
ends the clause (or is followed by years/yo/and/but), and a name is matched
by `engine/agents/cast.py`'s precision rules (a whole word, never a title
or trade) plus the story's `ordinary_names`, two letters at least.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator, Optional, Sequence

from engine import social
from engine.social.kinds import STAGE_RANKS, Decision, decision_from_row, stage_rank
from engine.social.population import Person

if TYPE_CHECKING:
    from engine.social.voicing import PersonSnapshot


@dataclass(frozen=True)
class Failure:
    """One disagreement: the check, where it is (`bubbles|shared|learned`), the item's index, and what hit."""

    check: str
    where: str
    index: int
    detail: str


@dataclass(frozen=True)
class AgreementView:
    """Everything a check may read (Plan decision 24): a frozen copy, never the live state."""

    stage: str
    person: Person
    player: dict[str, Any]
    contacts: tuple[str, ...]                 # display names of everyone else with a thread
    plans: tuple[dict[str, Any], ...] = field(default=())    # their plan rows (plan_claimed, v0.23.0 T12)
    told: tuple[str, ...] = ()                # contacts the player named to this person (their own bubbles)
    stage_before: str = ""                    # off a live stage: the live stage they left (else "")
    now: Optional[float] = None               # the in-game hour judged at
    # v0.23.0 T7 (spec §13.4): what commitment_claimed and promise_claimed read.
    willing: frozenset[str] = frozenset()     # growth.PHONE_COMMITMENTS that hold now (`willing_now`)
    recorded: frozenset[str] = frozenset()    # commitments a scene's closer recorded (`scene.close`, T13)
    promises: tuple[tuple[str, str], ...] = ()    # (id, window) of their promises (`promise_windows_of`)
    makes_promises: bool = True               # their archetype makes promises at all (`promise_prob` > 0)
    promise_windows: tuple[str, ...] = ()     # windows a stated promise may name now (`promise_windows_now`)
    # v0.23.0 T15 (spec §10.6): set only for a scene's NARRATION (`scene_view`), where "you" is the player and
    # the companion is named or "she/he/they". The words that name the companion (their name's forms and
    # pronouns); empty for a texter's own reply, whose every check reads as v0.22/T7 wrote it.
    companion: frozenset[str] = frozenset()
    # Scene prose only (review M3): the windows of the PLAYER's open promises to them (a closer's included);
    # `promise_windows` is then theirs alone, so each side's promise is judged against its own.
    player_windows: tuple[str, ...] = ()


CheckFn = Callable[[dict[str, Any], Decision, AgreementView], list[Failure]]

#: name -> check, in registration order. Filled by @check_fn at import, read after.
CHECKS: dict[str, CheckFn] = {}

#: The checks whose answer can change while a reply waits (the stage moves, a
#: thread opens, a meet is agreed): re-run at commit (spec §16.3 step 3, T14).
STATE_CHECKS: frozenset[str] = frozenset({"stage_claimed", "another_person", "plan_claimed",
                                          "commitment_claimed", "arrival_claimed"})

#: A commitment whose stage is already reached holds whatever its `willing:` row says now: the step
#: was taken (a couple already exclusive may say so).
COMMITMENT_STAGES: tuple[tuple[str, str], ...] = (("number", "numbers"), ("meet", "meeting"),
                                                  ("exclusive", "exclusive"), ("move_in", "living_together"),
                                                  ("propose", "engaged"))

#: relationships.yaml `claims:` keys that are not stages (v0.23.0 T7): `promise` (window -> phrases)
#: and `commitment` (commitment id -> phrases).
CLAIM_TABLES: tuple[str, ...] = ("promise", "commitment")

#: The fact lists a voiced reply carries (spec §11.2).
WHERES: tuple[str, ...] = ("bubbles", "shared", "learned")

#: relationships.yaml `meet_claims:` keys: a plan is open or it is not, so one list (v0.23.0 T12).
MEET_WHENS: tuple[str, ...] = ("any",)

#: relationships.yaml's phrase lists this module reads (each a list of
#: non-empty strings; `check_phrases`).
PHRASE_LISTS: tuple[str, ...] = ("media_claims", "media_denials", "agree_phrases", "negations", "ordinary_names",
                                 "meet_denials")

#: How many words before a claim a negation still cancels it.
NEGATION_WINDOW = 3

#: The ages a number may be read as.
AGE_RANGE: tuple[int, int] = (16, 99)

#: What may follow an age for it still to be read as one ("I'm 29 minutes away" is not an age).
_AGE_TAIL = r"(?:\s+(?:years?\s+old|yrs?(?:\s+old)?|yo)\b)?(?:\s*$|\s+(?:and|but|btw|lol|haha)\b)"


def check_fn(name: str) -> Callable[[CheckFn], CheckFn]:
    """Register a check under ``name``."""
    def register(fn: CheckFn) -> CheckFn:
        if name in CHECKS:
            raise ValueError(f"agreement: check {name!r} registered twice")
        CHECKS[name] = fn
        return fn

    return register


def check(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """Every registered check over one reply (spec §11.5); [] when it agrees. Pure."""
    reply = reply if isinstance(reply, dict) else {}
    out: list[Failure] = []
    for fn in CHECKS.values():
        out.extend(fn(reply, decision, view))
    return out


# -- views ------------------------------------------------------------------------------


def view_from_state(state: Any, pid: str) -> AgreementView:
    """The view of ``pid`` in a live state (T14's commit re-check). Reads only; copies what it keeps."""
    import copy

    from engine.social import life

    slice_ = state.social or {}
    person_state = (slice_.get("people") or {}).get(pid) or {}
    view = _view(person_state, life.person_now(state, pid), copy.deepcopy(slice_.get("player") or {}),
                 tuple(contact_names(state, pid)), plans_of(state, pid), said_to(state, pid),
                 float(state.world_clock_hours))
    return replace(view, willing=willing_now(state, pid), promises=promise_windows_of(state, pid),
                   makes_promises=makes_promises(state, pid), promise_windows=promise_windows_now(state, pid))


def scene_view(state: Any, pid: str) -> AgreementView:
    """
    The view a scene's narration is checked against (v0.23.0 T15, spec §10.6, I10): `view_from_state`, read
    as prose. `recorded` is what a closer recorded (`scene.close`; it lasts until their next chat closes,
    T13). A commitment holds only when a closer recorded it or the stage is already past it -- willingness
    alone makes nothing in person (I10). A promise may be named only as one already held, by the side that
    made it (`promise_windows` theirs, `player_windows` the player's, a closer's included; review M3): the
    narration never makes one, and nothing it states is adopted (the storyteller is not the companion's
    voice). `companion` names them. Reads only.
    """
    from engine.social import life, promises

    view = view_from_state(state, pid)

    def windows(by: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(r["window"]) for r in promises.open_by(state, pid, by=by)))

    return replace(view, willing=_taken_commitments(state, pid, view.stage), makes_promises=True,
                   promise_windows=windows("person"), player_windows=windows("player"),
                   companion=companion_words(life.person_now(state, pid)))


#: Scene prose (T15): a person's pronouns by sex. The "they" forms always name the companion too: the
#: engine's own scene words call them "they" (`scene.MOVE_WORDS`, `TOO_DEEP_WORDS`).
PRONOUNS: dict[str, tuple[str, ...]] = {
    "female": ("she", "her", "hers", "herself", "she's", "she'd", "she'll"),
    "male": ("he", "him", "his", "himself", "he's", "he'd", "he'll"),
}
THEY: tuple[str, ...] = ("they", "them", "their", "theirs", "themselves", "they're", "they'd", "they'll", "they've")
#: Scene prose: every third-person word (a pronoun not the companion's is someone else).
NARRATION_THIRD: frozenset[str] = frozenset(PRONOUNS["female"] + PRONOUNS["male"] + THEY)
#: A possessive before more words makes the subject someone else's ("her brother says ...").
POSSESSIVES: frozenset[str] = frozenset({"his", "her", "their"})


def companion_words(person: Person) -> frozenset[str]:
    """The words that name ``person`` in narration: their name's forms (`name_forms`, and the whole name),
    their pronouns by sex, and the "they" forms."""
    whole = _norm(person.name)
    return frozenset(name_forms(person.name) | ({whole} if whole else set())
                     | set(PRONOUNS.get(person.sex, ())) | set(THEY))


def _stage_commitments(stage: str) -> frozenset[str]:
    """The commitments whose stage is already reached (`COMMITMENT_STAGES`): a step taken."""
    return frozenset(name for name, reached in COMMITMENT_STAGES
                     if stage_rank(stage) >= stage_rank(reached) >= 0)


def _taken_commitments(state: Any, pid: str, stage: str) -> frozenset[str]:
    """The steps already taken with ``pid``: `_stage_commitments`, but moving in is the household (T18, m6: an
    engaged couple may not live together yet, and one living together is), never the stage alone."""
    from engine.social import relationships   # lazily: relationships reads this module's data

    taken = set(_stage_commitments(stage)) - {"move_in"}
    if relationships.household(state) == pid:
        taken.add("move_in")
    return frozenset(taken)


def willing_now(state: Any, pid: str) -> frozenset[str]:
    """The `growth.PHONE_COMMITMENTS` that hold for ``pid`` now (spec §6.5, §13.2): `growth.willing`, or the
    stage already past the step (`COMMITMENT_STAGES`). A commitment the story's growth.yaml does not
    declare never holds. Reads only."""
    from engine.social import growth   # lazily: growth reads population, as this module does

    stage = str((((state.social or {}).get("people") or {}).get(pid) or {}).get("stage") or "matched")
    taken = _taken_commitments(state, pid, stage)
    out: set[str] = set()
    for name in growth.PHONE_COMMITMENTS:
        if name in taken:
            out.add(name)
            continue
        try:
            if growth.willing(state, pid, name)[0]:
                out.add(name)
        except ValueError:                                # not declared in this story's growth.yaml
            continue
    return frozenset(out)


def promise_windows_of(state: Any, pid: str) -> tuple[tuple[str, str], ...]:
    """(id, window) of ``pid``'s own promises a reply may name (any status), each resolved to its own
    window -- a fallback-resolved one ("after work, so tomorrow morning") is left out, since its words
    may truthfully name either (precision first). Reads only."""
    rows = ((state.social or {}).get("promises") or {}).values()
    return tuple((str(r["id"]), str(r["window"])) for r in sorted(rows, key=lambda r: str(r.get("id")))
                 if r.get("pid") == pid and r.get("by") == "person" and not r.get("fallback"))


def promise_windows_now(state: Any, pid: str) -> tuple[str, ...]:
    """The windows ``pid`` could promise to message in now (T7 fix round 1, review I1): relationships.yaml
    `proposals.promise.window`, each that `promises.span_for` resolves within `max_ahead_hours` -- none for
    someone whose archetype makes no promises, who has gone, or whose relationship is not live. Reads only."""
    from engine.social import apps, promises, relationships

    person = (((state.social or {}).get("people") or {}).get(pid) or {})
    if (not makes_promises(state, pid) or apps.gone(state, pid)
            or str(person.get("stage") or "matched") not in relationships.LIVE_STAGES):
        return ()
    row = (social.data("relationships").get("proposals") or {}).get(relationships.PROMISE_PROPOSAL) or {}
    at = float(state.world_clock_hours)
    return tuple(str(w) for w in row.get("window") or ()
                 if promises.span_for(state, pid, by="person", window=str(w), at=at) is not None)


def makes_promises(state: Any, pid: str) -> bool:
    """Their archetype makes promises at all (`promise_prob` above 0; a breadcrumber's is 0, spec §5.2)."""
    from engine.social import behaviour, population

    return float(behaviour.archetype(population.profile(state, pid).archetype).promise_prob) > 0


def plans_of(state: Any, pid: str) -> tuple[dict[str, Any], ...]:
    """Copies of ``pid``'s plan rows, open or closed (the view's `plans`; the voicing snapshot's `plans`)."""
    import copy

    return tuple(copy.deepcopy(row) for row in ((state.social or {}).get("plans") or {}).values()
                 if isinstance(row, dict) and row.get("pid") == pid)


def said_to(state: Any, pid: str) -> set[str]:
    """Every word the player wrote in ``pid``'s threads still in state (`player_said` over each)."""
    said: set[str] = set()
    for thread in ((state.social or {}).get("threads") or {}).values():
        if thread.get("pid") == pid:
            said |= player_said(thread.get("messages") or ())
    return said


def view_from_snapshot(snap: "PersonSnapshot") -> AgreementView:
    """
    The view a voicing snapshot holds (T13; ``voice`` checks against it with
    no lock held). Mirrors `view_from_state` exactly: the person's stage and
    `stage_before` from the snapshot's copy of their slice, `told` from
    their memory (`told`) and from every word the player wrote them that
    the snapshot carries (`player_words`, plus its tail).
    """
    import copy

    from engine.social.voicing import person_of

    said = set(snap.player_words) | player_said(snap.tail)
    at = (snap.now or {}).get("at")
    # Their memory is the snapshot's own copy (`snap.memory`, T6 review M6), not inside `dynamic`.
    row = {**snap.dynamic, "memory": snap.memory} if snap.memory else snap.dynamic
    view = _view(row, person_of(snap), copy.deepcopy(snap.player), tuple(snap.contacts),
                 tuple(copy.deepcopy(m) for m in snap.plans), said, None if at is None else float(at))
    return replace(view, willing=frozenset(snap.willing), promises=tuple(snap.promise_rows),
                   makes_promises=bool(snap.makes_promises), promise_windows=tuple(snap.promise_windows))


def player_said(messages: Iterable[dict[str, Any]]) -> set[str]:
    """Every word of the player's bubbles in ``messages`` (`_tokens`)."""
    said: set[str] = set()
    for message in messages:
        if message.get("from") == "player":
            for bubble in message.get("bubbles") or ():
                said |= _tokens(bubble)
    return said


def _view(person_state: dict[str, Any], person: Person, player: dict[str, Any], contacts: tuple[str, ...],
          plans: tuple[dict[str, Any], ...], said: set[str], now: Optional[float]) -> AgreementView:
    """The view both builders share: `told` is the contacts the player named to them, in their memory
    (`memory.note_told`, for messages gone to the archive) or in the words still at hand."""
    stage = str(person_state.get("stage") or "matched")
    from engine.social import memory   # lazily: memory imports this module

    remembered = {str(n) for n in memory.part(person_state, "told") or ()}
    told = tuple(name for name in contacts if name in remembered or _name_words(name) & said)
    return AgreementView(stage=stage, person=person, player=player, contacts=contacts, plans=plans,
                         told=told, stage_before=_left_from(stage, person_state), now=now,
                         recorded=frozenset(str(c) for c in person_state.get("recorded") or ()))


def contact_names(state: Any, pid: str) -> list[str]:
    """The display names of everyone but ``pid`` the player has a thread with, each once. Reads only."""
    from engine.social import population

    names: list[str] = []
    for thread in ((state.social or {}).get("threads") or {}).values():
        other = str(thread.get("pid") or "")
        if not other or other == pid:
            continue
        name = population.profile(state, other).name
        if name not in names:
            names.append(name)
    return names


def words_of(text: str) -> set[str]:
    """The words of ``text`` as the name checks read them (`_tokens`): for `memory.note_told`."""
    return _tokens(text)


def name_words(name: str) -> set[str]:
    """Every word of a display name the player may have typed (`_name_words`): for `memory.note_told`."""
    return _name_words(name)


def _left_from(stage: str, person_state: dict[str, Any]) -> str:
    """The live stage a person off a live stage left: `wound_from` for cooling off, else `stage_before`."""
    if stage in dict(STAGE_RANKS):
        return ""
    before = str(person_state.get("stage_before") or "") if stage != "winding_down" else "winding_down"
    if before == "winding_down":
        before = str(person_state.get("wound_from") or "")
    return before if before in dict(STAGE_RANKS) else ""


def person_of(row: dict[str, Any]) -> Person:
    """A `Person` from a fixture's `{name, age, job, neighbourhood}` (every other field a blank default)."""
    return Person(
        pid=str(row.get("pid") or "p0000"), index=int(row.get("index") or 0),
        name=str(row.get("name") or ""), sex=str(row.get("sex") or "female"), age=int(row.get("age") or 0),
        neighbourhood=str(row.get("neighbourhood") or ""), job=str(row.get("job") or ""),
        job_shape="", education="", hobbies=tuple(row.get("hobbies") or ()), attributes=(), flags=(),
        appearance="", personality=(), traits=(), intent=str(row.get("intent") or "unsure"),
        archetype=str(row.get("archetype") or ""), texting_style="", preferences=(), chemistry=0.0, voice_id="",
    )


def view_of(case: dict[str, Any]) -> AgreementView:
    """The view a fixture dict describes: `stage`, `person`, `player`, `contacts`, `plans`, `told`,
    `stage_before`, `now` (an in-game hour), `willing`, `recorded`, `promises` ([{id, window}]),
    `makes_promises` (default true) and `promise_windows`."""
    return AgreementView(
        stage=str(case.get("stage") or "matched"), person=person_of(case.get("person") or {}),
        player=dict(case.get("player") or {}), contacts=tuple(str(c) for c in case.get("contacts") or ()),
        plans=tuple(dict(m) for m in case.get("plans") or ()),
        told=tuple(str(c) for c in case.get("told") or ()), stage_before=str(case.get("stage_before") or ""),
        now=None if case.get("now") is None else float(case["now"]),
        willing=frozenset(str(c) for c in case.get("willing") or ()),
        recorded=frozenset(str(c) for c in case.get("recorded") or ()),
        promises=tuple((str(p["id"]), str(p["window"])) for p in case.get("promises") or ()),
        makes_promises=bool(case.get("makes_promises", True)),
        promise_windows=tuple(str(w) for w in case.get("promise_windows") or ()),
    )


def decision_of(case: dict[str, Any]) -> Decision:
    """The `Decision` a fixture dict's `decision:` describes (`situation` defaults to `reply`)."""
    return decision_from_row(case.get("decision"), where="agreement fixture")


# -- the story's words --------------------------------------------------------------------


def _data() -> dict[str, Any]:
    return social.data("relationships")


def _phrases(name: str) -> tuple[str, ...]:
    return tuple(p for p in (_norm(str(x)) for x in (_data().get(name) or ())) if p)


def _table_labels(name: str) -> dict[str, str]:
    """id -> label, lowercased, of a population.yaml table."""
    rows = social.data("population").get(name) or []
    return {str(r["id"]): str(r.get("label") or r["id"]).lower() for r in rows if isinstance(r, dict) and "id" in r}


def check_phrases(data: dict[str, Any]) -> list[tuple[str, str]]:
    """relationships.yaml's agreement lists, as (key, message) faults: each a list of non-empty strings."""
    faults: list[tuple[str, str]] = []
    for name in PHRASE_LISTS:
        value = data.get(name)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(p, str) and _norm(p) for p in value):
            faults.append((name, "must be a list of phrases, each with a word in it"))
    for key in ("meet_claims", "arrival_claims"):
        claims = data.get(key)
        if claims is None:
            continue
        if not isinstance(claims, dict) or any(k not in MEET_WHENS for k in claims):
            faults.append((key, f"must map {', '.join(MEET_WHENS)} to lists of phrases"))
        else:
            for when, value in claims.items():
                if not isinstance(value, list) or not all(isinstance(p, str) and _norm(p) for p in value):
                    faults.append((f"{key}.{when}", "must be a list of phrases, each with a word in it"))
    return faults


# -- matching -----------------------------------------------------------------------------

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})
_CLAUSE = re.compile(r"[^.!?\n]+[.!?\n]*")


def _norm(text: str) -> str:
    """Case-folded, curly apostrophes straightened, every other mark a space, spaces collapsed."""
    text = str(text).translate(_APOSTROPHES).lower()
    return " ".join(re.sub(r"[^\w\s']", " ", text).split())


def _clauses(text: str, *, statements_only: bool) -> Iterator[str]:
    """The normalised clauses of ``text``; a question (ending in ``?``) is skipped when ``statements_only``."""
    for match in _CLAUSE.finditer(str(text).translate(_APOSTROPHES)):
        raw = match.group(0)
        if statements_only and "?" in raw[len(raw.rstrip(".!?\n")):]:
            continue
        clause = _norm(raw)
        if clause:
            yield clause


def _hits(phrase: str, clause: str) -> Iterator[re.Match[str]]:
    return re.finditer(rf"(?<![\w']){re.escape(phrase)}(?![\w'])", clause)


def _negated(clause: str, start: int, negations: tuple[str, ...]) -> bool:
    words = clause[:start].split()
    return any(word in negations for word in words[max(0, len(words) - NEGATION_WINDOW):])


def _claim(text: str, phrases: Iterable[str], *, negatable: bool = True,
           statements_only: bool = True) -> Optional[str]:
    """The first of ``phrases`` stated (not asked -- unless ``statements_only`` is off -- and not negated)
    in ``text``, or None."""
    phrases = tuple(phrases)
    if not phrases:
        return None
    negations = _phrases("negations") if negatable else ()
    for clause in _clauses(text, statements_only=statements_only):
        for phrase in phrases:
            if any(not _negated(clause, m.start(), negations) for m in _hits(phrase, clause)):
                return phrase
    return None


def _said(text: str, phrases: tuple[str, ...], view: AgreementView) -> Optional[str]:
    """`_claim` (stated, not negated) for a texter's reply; over scene prose (`view.companion`) a hit whose
    subject is someone else (`_someone_else`) is skipped too, so only the companion's -- or the player's --
    own claim counts."""
    if not view.companion:
        return _claim(text, phrases)
    if not phrases:
        return None
    negations = _phrases("negations")
    for clause in _clauses(text, statements_only=True):
        for phrase in phrases:
            if any(not _negated(clause, m.start(), negations) and not _someone_else(clause, m.start(), view)
                   for m in _hits(phrase, clause)):
                return phrase
    return None


def stated(text: str, phrases: Iterable[str], *, negatable: bool = True) -> Optional[str]:
    """The first of ``phrases`` (normalised here) stated in ``text`` -- not asked, and (``negatable``) not
    negated by the story's negations -- or None. For a check outside this module (`plans`, `promises`)."""
    return _claim(text, tuple(p for p in (_norm(str(x)) for x in phrases) if p), negatable=negatable)


def _items(reply: dict[str, Any], where: str) -> Iterator[tuple[int, str]]:
    for i, item in enumerate(reply.get(where) or []):
        yield i, str(item.get("text", "") if isinstance(item, dict) else item)


def _start(anchored: bool) -> str:
    """Where a lead may begin: anywhere on a word boundary, or (``anchored``) only at the clause's start."""
    return "^" if anchored else r"(?<![\w'])"


def _ages(text: str, lead: str, *, anchored: bool = False) -> Iterator[int]:
    """Every age stated in ``text`` after ``lead`` (a regex alternation), within AGE_RANGE."""
    for clause in _clauses(text, statements_only=True):
        for m in re.finditer(rf"{_start(anchored)}(?:{lead})\s+(\d{{1,3}}){_AGE_TAIL}", clause):
            age = int(m.group(1))
            if AGE_RANGE[0] <= age <= AGE_RANGE[1]:
                yield age


def _other_label(text: str, lead: str, labels: dict[str, str], own: str, *, anchored: bool = False) -> Optional[str]:
    """A label from ``labels`` other than ``own``'s stated after ``lead``; a label inside one's own is skipped."""
    mine = labels.get(own, own.replace("_", " ")).lower()
    mine_words = set(mine.split())
    for clause in _clauses(text, statements_only=True):
        for key, label in labels.items():
            core = label[4:] if label.startswith("the ") else label
            if key == own or not core or set(label.split()) <= mine_words:
                continue
            if re.search(rf"{_start(anchored)}(?:{lead})\s+(?:the\s+)?{re.escape(core)}(?![\w'])", clause):
                return label
    return None


# -- the checks ------------------------------------------------------------------------------


@check_fn("media_claimed")
def _media_claimed(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """They say media was sent and none is attached (§11.5)."""
    if decision.media_kind:
        return []
    phrases = _phrases("media_claims")
    out = []
    for i, text in _items(reply, "bubbles"):
        hit = _claim(text, phrases)
        if hit:
            out.append(Failure("media_claimed", "bubbles", i, hit))
    return out


@check_fn("media_denied")
def _media_denied(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """Media is attached and the bubbles say they will not send it (§11.5)."""
    if not decision.media_kind:
        return []
    phrases = _phrases("media_denials")
    out = []
    for i, text in _items(reply, "bubbles"):
        hit = _claim(text, phrases, negatable=False)
        if hit:
            out.append(Failure("media_denied", "bubbles", i, hit))
    return out


def _ancestors(stage: str) -> set[str]:
    """Every stage ``stage`` is reached through (relationships.yaml `from`, transitively)."""
    rows = _data().get("stages") or {}
    seen: set[str] = set()
    todo = list((rows.get(stage) or {}).get("from") or ())
    while todo:
        name = str(todo.pop())
        if name not in seen:
            seen.add(name)
            todo.extend((rows.get(name) or {}).get("from") or ())
    return seen


@check_fn("stage_claimed")
def _stage_claimed(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """They name a stage not reached ("my girlfriend" while talking): a STATE check (§11.5).

    A stage is reached when it is the current one or one the current one is reached
    through. Off a live stage (cooling off, ended, faded),
    the live stage they left (`stage_before`) and those it was reached through count as
    reached; with none in the view, nothing is claimed against it (precision first)."""
    ranked = dict(STAGE_RANKS)
    if view.stage in ranked:
        reached = _ancestors(view.stage) | {view.stage}
    elif view.stage_before in ranked:
        reached = _ancestors(view.stage_before) | {view.stage_before, view.stage}
    else:
        return []
    claims = _data().get("claims") or {}
    phrases = tuple(p for stage, words in claims.items() if stage not in reached and stage not in CLAIM_TABLES
                    for p in (_norm(str(w)) for w in words or ()) if p)
    out = []
    for i, text in _items(reply, "bubbles"):
        hit = _said(text, phrases, view)
        if hit:
            out.append(Failure("stage_claimed", "bubbles", i, hit))
    return out


@check_fn("profile_contradicted")
def _profile_contradicted(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """Their age, job or neighbourhood stated otherwise; a `learned` fact contradicting the player's (§11.5)."""
    jobs, places = _table_labels("jobs"), _table_labels("neighbourhoods")
    person, player = view.person, view.player or {}
    out = []
    if view.companion:                                   # scene prose (T15): the companion's facts only
        for i, text in _items(reply, "bubbles"):
            detail = _companion_profile(text, view, jobs, places)
            if detail:
                out.append(Failure("profile_contradicted", "bubbles", i, detail))
        return out
    for where in ("bubbles", "shared"):
        for i, text in _items(reply, where):
            detail = _first_person(text, person, jobs, places)
            if detail:
                out.append(Failure("profile_contradicted", where, i, detail))
    for i, text in _items(reply, "learned"):
        detail = _about_player(text, player, jobs, places)
        if detail:
            out.append(Failure("profile_contradicted", "learned", i, detail))
    return out


_I_AM = r"i'm|im|i am"


def _first_person(text: str, person: Person, jobs: dict[str, str], places: dict[str, str]) -> str:
    if person.age:
        wrong = next((a for a in _ages(text, _I_AM) if a != person.age), None)
        if wrong is not None:
            return f"age {wrong}"
    if person.job:
        label = _other_label(text, r"i work as(?:\s+an?)?|(?:i'm|im|i am)\s+an?", jobs, person.job)
        if label:
            return f"job {label}"
    if person.neighbourhood:
        label = _other_label(text, r"i live in|(?:i'm|im) living in|(?:i'm|im) based in", places,
                             person.neighbourhood)
        if label:
            return f"neighbourhood {label}"
    return ""


def _about_player(text: str, player: dict[str, Any], jobs: dict[str, str], places: dict[str, str]) -> str:
    """A `learned` fact contradicting the player's profile. The fact's SUBJECT must be the player: its
    lead starts the clause, bare ("works as a nurse") or after the player's name or a pronoun ("Sam is
    31", "they live in Northgate") -- so "their sister is 35" is about the sister, never the player."""
    name = _norm(str(player.get("name") or ""))
    subject = "|".join(filter(None, [re.escape(name) if name else "", "they", "you", "she", "he"]))
    be = rf"(?:(?:{subject})\s+)?(?:is|are)|they're|theyre|you're|youre|she's|he's"
    if name:
        be += rf"|{re.escape(name)}'s"
    job = str((player.get("attributes") or {}).get("job") or player.get("job") or "")
    return _about(text, subject, be, player.get("age"), job, str(player.get("neighbourhood") or ""),
                  jobs, places, prefix="player ")


def _about(text: str, subject: str, be: str, age: Any, job: str, place: str, jobs: dict[str, str],
           places: dict[str, str], *, prefix: str) -> str:
    """An age, job or neighbourhood stated otherwise of a SUBJECT whose lead starts the clause (``subject``
    a regex alternation of the words naming them, ``be`` their forms of "is"): `_about_player`'s reading,
    shared with scene prose's companion (T15)."""
    if isinstance(age, int) and not isinstance(age, bool):
        wrong = next((a for a in _ages(text, rf"{be}|aged", anchored=True) if a != age), None)
        if wrong is not None:
            return f"{prefix}age {wrong}"
    if job:
        lead = rf"(?:(?:{subject})\s+)?works?\s+as(?:\s+an?)?|(?:{be})\s+an?"
        label = _other_label(text, lead, jobs, job, anchored=True)
        if label:
            return f"{prefix}job {label}"
    if place:
        lead = rf"(?:(?:{subject})\s+)?lives?\s+in|(?:{be})\s+based\s+in"
        label = _other_label(text, lead, places, place, anchored=True)
        if label:
            return f"{prefix}neighbourhood {label}"
    return ""


# -- scene prose (v0.23.0 T15, spec §10.6): who a sentence's words belong to ---------------------------

#: A quoted line: double quotes (straight or curly), curly single quotes, or straight single quotes that
#: open after a space or the start and close before a space or a mark (an apostrophe inside a word is not one).
_QUOTED = re.compile(r"[\"“”]([^\"“”]+)[\"“”]|‘([^’]+)’|(?:(?<=\s)|^)'(.+?)'(?=[\s,.!?;:]|$)")


def _quoted(text: str) -> tuple[list[str], str]:
    """``text``'s quoted lines, and the rest of it with each quote taken out (its attribution and narration)."""
    quotes = [next(g for g in m.groups() if g is not None) for m in _QUOTED.finditer(str(text))]
    return quotes, _QUOTED.sub(" ", str(text))


def _others(view: AgreementView) -> set[str]:
    """The name forms of everyone else the player has a thread with (never the companion's own)."""
    return {form for name in view.contacts for form in name_forms(name)} - view.companion


def _someone_else(clause: str, start: int, view: AgreementView) -> bool:
    """Scene prose: the words before a hit (`NEGATION_WINDOW` of them) make someone other than the companion
    its subject -- a pronoun not theirs, another contact's name, or a possessive before more words ("her
    brother says", "Maya's sister says"). The companion's name or pronoun, "you" (the player), or nothing,
    leaves the claim theirs, or the player's, and it counts."""
    words = clause[:start].split()[-NEGATION_WINDOW:]
    others = _others(view)
    for i, word in enumerate(words):
        more = i < len(words) - 1
        if word in POSSESSIVES and more:
            return True
        if word in view.companion:
            continue
        if word in NARRATION_THIRD or word in others:
            return True
        if word.endswith("'s") and (word[:-2] in others or (word[:-2] in view.companion and more)):
            return True
    return False


def _speaker(rest: str, view: AgreementView) -> str:
    """Whose a sentence's quote is, by its attribution's first person-word: "companion" ("she says", "Maya
    tells you"), "player" ("you say") or "" (another's name or pronoun, or no attribution: unknown)."""
    others = _others(view)
    for word in _norm(rest).split():
        if word in ("you", "your"):
            return "player"
        if word in view.companion:
            return "companion"
        if word in NARRATION_THIRD or word in others:
            return ""
    return ""


def _theirs(rest: str, view: AgreementView) -> bool:
    """A sentence's quote is the companion's (`_speaker`); unknown is not theirs (precision first)."""
    return _speaker(rest, view) == "companion"


#: Scene prose: the words that make "you" (the player) the subject of a promise ("you'll text them").
_YOU_WORDS: frozenset[str] = frozenset({"you", "you'll", "you'd", "your"})


def _promise_hits(text: str, phrases: tuple[str, ...], view: AgreementView) -> list[tuple[str, str]]:
    """Scene prose: every promise phrase stated in ``text``, with who promised it -- a quote by its speaker
    (`_speaker`); the narration by the words before the hit ("she'll" the companion, "you'll" the player,
    none unknown, someone else's skipped). Negated hits are skipped."""
    negations = _phrases("negations")
    quotes, rest = _quoted(text)
    who_quoted = _speaker(rest, view)
    out: list[tuple[str, str]] = []
    for quote in quotes:
        for clause in _clauses(quote, statements_only=True):
            for phrase in phrases:
                if any(not _negated(clause, m.start(), negations) for m in _hits(phrase, clause)):
                    out.append((phrase, who_quoted))
    for clause in _clauses(rest, statements_only=True):
        for phrase in phrases:
            for m in _hits(phrase, clause):
                if _negated(clause, m.start(), negations) or _someone_else(clause, m.start(), view):
                    continue
                words = clause[:m.start()].split()[-NEGATION_WINDOW:]
                who = ("player" if any(w in _YOU_WORDS for w in words)
                       else "companion" if any(w in view.companion for w in words) else "")
                out.append((phrase, who))
    return out


def _scene_promises(reply: dict[str, Any], table: dict[str, tuple[str, ...]],
                    view: AgreementView) -> list[Failure]:
    """Scene prose's `promise_claimed` (review M3): a promise the companion states is held to THEIR open
    promises (`promise_windows`), one the player states to the player's (`player_windows`, a closer's
    included), one of unknown making to either. Nothing stated is adopted."""
    allowed = {"companion": set(view.promise_windows), "player": set(view.player_windows),
               "": set(view.promise_windows) | set(view.player_windows)}
    out = []
    for i, text in _items(reply, "bubbles"):
        for window, phrases in table.items():
            bad = next((hit for hit, who in _promise_hits(text, phrases, view) if window not in allowed[who]), None)
            if bad:
                out.append(Failure("promise_claimed", "bubbles", i, bad))
                break
    return out


def _companion_profile(text: str, view: AgreementView, jobs: dict[str, str], places: dict[str, str]) -> str:
    """Scene prose's `profile_contradicted`: the companion's own quoted words ("I'm 34," she says) read as
    the first person, and the narration's statements whose subject starts the clause and names them ("Maya
    is 34", "she works as a nurse"). Another's facts ("her sister is 35") and the player's are not read."""
    person = view.person
    quotes, rest = _quoted(text)
    if _theirs(rest, view):
        for quote in quotes:
            detail = _first_person(quote, person, jobs, places)
            if detail:
                return detail
    names = sorted((w for w in view.companion if w not in NARRATION_THIRD), key=len, reverse=True)
    pronouns = [w for w in ("she", "he", "they") if w in view.companion]
    subject = "|".join(re.escape(w) for w in names + pronouns)
    be = rf"(?:(?:{subject})\s+)?(?:is|are)|they're|theyre"
    be += "".join(f"|{w}'s" for w in pronouns if w != "they")
    be += "".join(f"|{re.escape(w)}'s" for w in names)
    return _about(rest, subject, be, person.age or None, person.job, person.neighbourhood, jobs, places, prefix="")


_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")


def _tokens(text: str) -> set[str]:
    """The words of ``text``, case-folded, a possessive 's taken off ("Maya's" -> "maya")."""
    out = set()
    for word in _WORD.findall(str(text).translate(_APOSTROPHES).lower()):
        out.add(word[:-2] if word.endswith("'s") else word)
    return out


#: The shortest name token read as a name: every token is matched as a WHOLE word, so the
#: four-letter floor `cast.surface_forms` keeps for untokenised prose is not needed here;
#: a short name that is also a word (Kit, Max, Rob) is the story's `ordinary_names`.
MIN_NAME_TOKEN = 2


def _name_words(name: str) -> set[str]:
    """Every word of a display name, case-folded (what the player may have typed of it)."""
    return {w.strip(".,'") for w in _norm(name).split() if len(w.strip(".,'")) >= MIN_NAME_TOKEN}


def name_forms(name: str) -> set[str]:
    """The words of a display name read as that name: each token of MIN_NAME_TOKEN letters or more,
    case-folded, never a title or trade (`cast.COMMON_WORDS`) or one of the story's `ordinary_names`;
    a role worn as a name ("The Archivist") gives none."""
    from engine.agents.cast import COMMON_WORDS

    words = [w.strip(".,'") for w in _norm(name).split()]
    if not words or words[0] == "the":
        return set()
    ordinary = set(_phrases("ordinary_names"))
    return {w for w in words if len(w) >= MIN_NAME_TOKEN and w not in COMMON_WORDS and w not in ordinary}


@check_fn("another_person")
def _another_person(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """A name from the player's contacts this person cannot know (§11.5): cast.py's precision rules
    (whole words, never a title or an ordinary word) over `name_forms`. Never their own name or the
    player's, nor a contact the player named to them (`view.told`)."""
    known = name_forms(view.person.name) | name_forms(str((view.player or {}).get("name") or ""))
    for name in view.told:
        known |= name_forms(name)
    forms: dict[str, str] = {}
    for name in view.contacts:
        for form in sorted(name_forms(name) - known):
            forms.setdefault(form, name)
    if not forms:
        return []
    out = []
    for where in WHERES:
        for i, text in _items(reply, where):
            tokens = _tokens(_companion_said(text, view) if view.companion else text)
            hit = next((form for form in forms if form in tokens), None)
            if hit:
                out.append(Failure("another_person", where, i, forms[hit]))
    return out


def _companion_said(text: str, view: AgreementView) -> str:
    """Scene prose's `another_person`: only what the companion says or does -- their quoted words, and the
    narration's clauses that start with their name or pronoun ("She mentions ..."). The narration naming
    someone the player knows ("You think of Sam") is not the companion knowing them."""
    quotes, rest = _quoted(text)
    parts = list(quotes) if _theirs(rest, view) else []
    parts += [c for c in _clauses(rest, statements_only=False)
              if c.split()[0] in view.companion and c.split()[0] not in POSSESSIVES]
    return " ".join(parts)


@check_fn("number")
def _number(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """More bubbles than the decision allows (§11.5); the failure points at the first one too many."""
    bubbles = reply.get("bubbles") or []
    if len(bubbles) > decision.max_bubbles:
        return [Failure("number", "bubbles", decision.max_bubbles,
                        f"{len(bubbles)} bubbles, at most {decision.max_bubbles}")]
    return []


@check_fn("decline_wording")
def _decline_wording(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """A decline decision whose bubbles agree ("ok sending", "here you go") (§11.5)."""
    if decision.kind != "decline":
        return []
    phrases = _phrases("agree_phrases")
    out = []
    for i, text in _items(reply, "bubbles"):
        hit = _claim(text, phrases)
        if hit:
            out.append(Failure("decline_wording", "bubbles", i, hit))
    return out


def _plan_claim(text: str, phrases: tuple[str, ...], view: Optional[AgreementView] = None) -> Optional[str]:
    """The first of ``phrases`` stated in ``text`` -- not asked, not negated, and not with a third-person
    subject in the words before it ("my sister says see you there"; over scene prose, `_someone_else`) --
    or None."""
    negations = _phrases("negations")
    for clause in _clauses(text, statements_only=True):
        for phrase in phrases:
            if any(not _negated(clause, m.start(), negations) and not _third_party(clause, m.start(), view)
                   for m in _hits(phrase, clause)):
                return phrase
    return None


@check_fn("plan_claimed")
def _plan_claimed(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """They state a plan to meet that is not open, or deny one that is (v0.23.0 spec §13.4): a STATE check.

    A `meet_claims` phrase ("it's a date", "see you tonight") needs an open plan of theirs (`view.plans`, status
    `open`); a `meet_denials` phrase fails while one is open. Statements only, in the second person: a hit with
    a third-person subject is skipped, as `commitment_claimed` skips it. Matched only (relationships.yaml): facts, never tone."""
    open_ = any(isinstance(p, dict) and p.get("status") == "open" for p in view.plans)
    claims = tuple(p for p in (_norm(str(w)) for w in (_data().get("meet_claims") or {}).get("any") or ()) if p)
    denials = _phrases("meet_denials") if open_ else ()
    out = []
    for i, text in _items(reply, "bubbles"):
        hit = _plan_claim(text, claims, view) if claims and not open_ else None
        if hit is None and denials:
            hit = _claim(text, denials, negatable=False)
        if hit:
            out.append(Failure("plan_claimed", "bubbles", i, hit))
    return out


def _claim_table(name: str) -> dict[str, tuple[str, ...]]:
    """relationships.yaml `claims.<name>` (a `CLAIM_TABLES` key): key -> its normalised phrases."""
    table = (_data().get("claims") or {}).get(name)
    if not isinstance(table, dict):
        return {}
    return {str(k): tuple(p for p in (_norm(str(w)) for w in v or ()) if p) for k, v in table.items()}


def _reply_promise_window(reply: dict[str, Any]) -> str:
    """The window of the reply's own `promise` proposal (T7's schema: a list of at most one
    `{window, about}`), or ""."""
    value = reply.get("promise")
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value.get("window") or "") if isinstance(value, dict) else ""


def stated_promise(texts: Iterable[str]) -> Optional[str]:
    """The first window a reply's words promise to message in (relationships.yaml `claims.promise`: stated,
    not asked, not negated), or None. The voicer adopts it at commit when it resolves (review I1)."""
    table = _claim_table("promise")
    for text in texts:
        for window, phrases in table.items():
            if _claim(str(text), phrases):
                return window
    return None


@check_fn("promise_claimed")
def _promise_claimed(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """They promise to message in a window the engine cannot hold (v0.23.0 spec §5.2, §13.4): a window other
    than the decision's own promise's (`decision.promise_id`); with none, one that contradicts the reply's
    own `promise` proposal, or one that does not resolve for them now (`view.promise_windows`; none for
    someone whose archetype makes no promises). A stated window that resolves passes: the commit adopts it
    as their promise (T7 fix round 1, review I1). Matched only (relationships.yaml `claims.promise`):
    facts, never tone."""
    table = _claim_table("promise")
    if not table:
        return []
    if view.companion:                                  # scene prose (T15): judged by who made it (review M3)
        return _scene_promises(reply, table, view)
    own = _reply_promise_window(reply)
    if decision.promise_id:
        expected = dict(view.promises).get(decision.promise_id)
        if expected is None:                              # a row the view cannot read: nothing to hold to
            return []
        allowed = {expected}
    elif own:
        allowed = {own}
    else:
        allowed = set(view.promise_windows) if view.makes_promises else set()
    out = []
    for i, text in _items(reply, "bubbles"):
        for window, phrases in table.items():
            hit = _said(text, phrases, view)
            if hit and window not in allowed:
                out.append(Failure("promise_claimed", "bubbles", i, hit))
                break
    return out


#: Words that, among the few before a step's phrase, make someone else its subject ("my brother wants to
#: move in with me", "she said we should get married"): the hit is skipped (T7 fix round 1, review I3).
THIRD_PARTY_WORDS = frozenset({"he", "she", "they", "him", "them", "he'd", "she'd", "they'd", "he's", "she's",
                               "they're", "his", "her", "their"})


def _third_party(clause: str, start: int, view: Optional[AgreementView] = None) -> bool:
    """Someone else is the subject of a hit: a third-person word among the few before it; over scene prose
    (`view.companion`, T15) the companion's own name and pronouns are not someone else (`_someone_else`)."""
    if view is not None and view.companion:
        return _someone_else(clause, start, view)
    words = clause[:start].split()
    return any(word in THIRD_PARTY_WORDS for word in words[max(0, len(words) - NEGATION_WINDOW):])


def _step_claim(text: str, phrases: tuple[str, ...], view: Optional[AgreementView] = None) -> Optional[str]:
    """The first of ``phrases`` said in ``text`` -- asked counts -- neither negated nor with a third-person
    subject in the words before it."""
    negations = _phrases("negations")
    # A comma or semicolon ends the lookback: "honestly my love, will you marry me" is asked of them.
    parts = [_norm(p) for c in _CLAUSE.findall(str(text).translate(_APOSTROPHES)) for p in re.split(r"[,;]", c)]
    for clause in (p for p in parts if p):
        for phrase in phrases:
            if any(not _negated(clause, m.start(), negations) and not _third_party(clause, m.start(), view)
                   for m in _hits(phrase, clause)):
                return phrase
    return None


@check_fn("commitment_claimed")
def _commitment_claimed(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """They state or ask a relationship step (relationships.yaml `claims.commitment`: "let's move in",
    "will you marry me") whose `willing:` row does not hold now and which no closer recorded (v0.23.0
    spec §13.4): a STATE check. Asked counts as stated -- asking IS the step -- but a negated one does
    not, nor one with a third-person subject before it (`_third_party`, review I3). The phrases are the
    second person's ("will you marry me", "you should move in with me"). Matched only: facts, never tone."""
    out = []
    for i, text in _items(reply, "bubbles"):
        for commitment, phrases in _claim_table("commitment").items():
            if commitment in view.willing or commitment in view.recorded:
                continue
            hit = _step_claim(text, phrases, view)
            if hit:
                out.append(Failure("commitment_claimed", "bubbles", i, hit))
                break
    return out


#: A word right after an arrival phrase that makes it about something else ("I'm here for you", "I'm here if you
#: need me", "here to listen"): no arrival is claimed.
NOT_ARRIVAL_AFTER: frozenset[str] = frozenset({"for", "if", "to", "whenever", "when", "anytime", "all"})


def _arrived(view: AgreementView) -> bool:
    """One of their plans is open and they are at its place (A4 W4): marked `arrived`, or its `arrives_at` reached
    by `view.now`. A row written before the arrival fields counts as there, as the engine reads it."""
    for row in view.plans:
        if not isinstance(row, dict) or row.get("status") != "open" or row.get("when") == "soon":
            continue
        if row.get("arrived", "arrives_at" not in row):
            return True
        if view.now is not None and row.get("arrives_at") is not None and float(view.now) >= float(row["arrives_at"]):
            return True
    return False


def _someone_elses_arrival(clause: str, start: int, view: AgreementView) -> bool:
    """A hit whose subject is someone else (fix round 1, I2b): a third-person word (`_third_party`), "my <relation>"
    ("my mum just got here"), or a contact's name ("Priya just got here") among the few words before it."""
    if _third_party(clause, start, view):
        return True
    words = clause[:start].split()[-NEGATION_WINDOW:]
    if "my" in words:
        return True
    names: set[str] = set()
    for name in view.contacts:
        names |= _name_words(name)
    return bool(names & {w.strip(".,'") for w in words})


def _arrival_claim(text: str, phrases: tuple[str, ...], view: AgreementView) -> Optional[str]:
    """The first of ``phrases`` stated in ``text``: not asked, not negated, not someone else's
    (`_someone_elses_arrival`), and not followed by a word that makes it about something else
    (`NOT_ARRIVAL_AFTER`). None when none is."""
    negations = _phrases("negations")
    for clause in _clauses(text, statements_only=True):
        for phrase in phrases:
            for m in _hits(phrase, clause):
                after = clause[m.end():].split()[:1]
                if (not _negated(clause, m.start(), negations) and not _someone_elses_arrival(clause, m.start(), view)
                        and not (after and after[0] in NOT_ARRIVAL_AFTER)):
                    return phrase
    return None


@check_fn("arrival_claimed")
def _arrival_claimed(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """They say they are at the place they planned to meet ("I'm here", "just got here") while they are still on
    their way (v0.23.0 addendum 4 W4, I5): a STATE check, so it is judged on the snapshot in the pass and again on
    the live state at commit. Judged only while they have a plan open with the player (fix round 1, I2a): with
    none, "I'm at the bar" is an ordinary reply. relationships.yaml `arrival_claims.any`; facts, never tone."""
    claims = tuple(p for p in (_norm(str(w)) for w in (_data().get("arrival_claims") or {}).get("any") or ()) if p)
    planned = any(isinstance(p, dict) and p.get("status") == "open" for p in view.plans)
    if not claims or not planned or _arrived(view):
        return []
    out = []
    for i, text in _items(reply, "bubbles"):
        hit = _arrival_claim(text, claims, view)
        if hit:
            out.append(Failure("arrival_claimed", "bubbles", i, hit))
    return out


# -- scene prose (v0.23.0 T15, spec §10.6, I10) ---------------------------------------------------------

#: The checks scene prose is held to: facts only (rule 12) -- the profile, other people, the stage, and
#: the promises, plans and steps a closer did or did not make.
SCENE_PROSE_CHECKS: tuple[str, ...] = ("profile_contradicted", "another_person", "stage_claimed", "promise_claimed",
                                       "plan_claimed", "commitment_claimed")
#: The checks prose at home is held to, with the household partner there and no scene open (T18 fix I3): only
#: the facts that cannot misfire on ordinary home talk. "See you tonight" between two people who live together
#: is no plan, promise or step claimed, so `plan_claimed`, `promise_claimed` and `commitment_claimed` stay out.
HOME_PROSE_CHECKS: tuple[str, ...] = ("profile_contradicted", "another_person", "stage_claimed")


def _sentences(text: str) -> list[str]:
    """``text`` split on sentence ends (the evaluator's `_SENTENCE_END`), each sentence one bubble; a last
    unfinished run of words is a sentence too."""
    from engine.agents.stream_processor import _SENTENCE_END

    text = str(text or "")
    out: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        piece = text[start:match.end()].strip()
        if piece:
            out.append(piece)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def check_scene_prose(narration: str, view: AgreementView, moment: dict[str, Any], *,
                      checks: Sequence[str] = SCENE_PROSE_CHECKS) -> list[Failure]:
    """Every texter fact check (§10.6), run over the narrator's prose as if it were one reply: the
    companion's words and the narration alike. Commitments are judged against what a closer RECORDED
    this turn (`view.recorded`), so a narrated promise, plan or step no closer made fails (I10).
    ``view`` is `scene_view`'s, so each check reads prose: the companion is named or "she/he/they",
    "you" is the player, and a claim whose subject is someone else is not theirs. ``checks``: the checks
    held (`HOME_PROSE_CHECKS` at home with no scene open, T18). Pure."""
    reply = {"bubbles": [{"text": sentence} for sentence in _sentences(narration)]}
    decision = Decision(situation="scene", end="sign_off" if moment.get("closer") else "none",
                        promise_id=str(moment.get("promise_id") or ""), plan_id=str(moment.get("plan_id") or ""))
    names = tuple(checks)
    return [f for f in check(reply, decision, view) if f.check in names]

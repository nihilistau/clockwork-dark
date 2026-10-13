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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator, Optional

from engine import social
from engine.social.kinds import STAGE_RANKS, Decision
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
    agreed_meets: tuple[dict[str, Any], ...] = field(default=())   # their meet rows (meeting_claimed, T24)
    told: tuple[str, ...] = ()                # contacts the player named to this person (their own bubbles)
    stage_before: str = ""                    # off a live stage: the live stage they left (else "")
    now: Optional[float] = None               # the in-game hour judged at (meeting_claimed's today; T24)


CheckFn = Callable[[dict[str, Any], Decision, AgreementView], list[Failure]]

#: name -> check, in registration order. Filled by @check_fn at import, read after.
CHECKS: dict[str, CheckFn] = {}

#: The checks whose answer can change while a reply waits (the stage moves, a
#: thread opens, a meet is agreed): re-run at commit (spec §16.3 step 3, T14).
STATE_CHECKS: frozenset[str] = frozenset({"stage_claimed", "another_person", "meeting_claimed"})

#: The fact lists a voiced reply carries (spec §11.2).
WHERES: tuple[str, ...] = ("bubbles", "shared", "learned")

#: relationships.yaml's phrase lists this module reads (each a list of
#: non-empty strings; `check_phrases`).
PHRASE_LISTS: tuple[str, ...] = ("media_claims", "media_denials", "agree_phrases", "negations", "ordinary_names",
                                 "meet_denials")

#: relationships.yaml `meet_claims:` keys (T24): when the meet-up a phrase states is.
MEET_WHENS: tuple[str, ...] = ("today", "tomorrow", "any")

#: A meet row's statuses that are still a plan (engine/social/meets.py): agreed, or due now.
PLANNED: tuple[str, ...] = ("agreed", "due")

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

    from engine.social import population

    slice_ = state.social or {}
    person_state = (slice_.get("people") or {}).get(pid) or {}
    return _view(person_state, population.profile(state, pid), copy.deepcopy(slice_.get("player") or {}),
                 tuple(contact_names(state, pid)), meets_of(state, pid), said_to(state, pid),
                 float(state.world_clock_hours))


def meets_of(state: Any, pid: str) -> tuple[dict[str, Any], ...]:
    """Copies of ``pid``'s meet rows (the view's `agreed_meets`; the voicing snapshot's `meets`)."""
    import copy

    return tuple(copy.deepcopy(row) for row in ((state.social or {}).get("meets") or {}).values()
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
    return _view(snap.dynamic, person_of(snap), copy.deepcopy(snap.player), tuple(snap.contacts),
                 tuple(copy.deepcopy(m) for m in snap.meets), said, None if at is None else float(at))


def player_said(messages: Iterable[dict[str, Any]]) -> set[str]:
    """Every word of the player's bubbles in ``messages`` (`_tokens`)."""
    said: set[str] = set()
    for message in messages:
        if message.get("from") == "player":
            for bubble in message.get("bubbles") or ():
                said |= _tokens(bubble)
    return said


def _view(person_state: dict[str, Any], person: Person, player: dict[str, Any], contacts: tuple[str, ...],
          meets: tuple[dict[str, Any], ...], said: set[str], now: Optional[float]) -> AgreementView:
    """The view both builders share: `told` is the contacts the player named to them, in their memory
    (`memory.note_told`, for messages gone to the archive) or in the words still at hand."""
    stage = str(person_state.get("stage") or "matched")
    remembered = {str(n) for n in person_state.get("told") or ()}
    told = tuple(name for name in contacts if name in remembered or _name_words(name) & said)
    return AgreementView(stage=stage, person=person, player=player, contacts=contacts, agreed_meets=meets,
                         told=told, stage_before=_left_from(stage, person_state), now=now)


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
    """The view a fixture dict describes: `stage`, `person`, `player`, `contacts`, `agreed_meets`, `told`,
    `stage_before`, `now` (an in-game hour)."""
    return AgreementView(
        stage=str(case.get("stage") or "matched"), person=person_of(case.get("person") or {}),
        player=dict(case.get("player") or {}), contacts=tuple(str(c) for c in case.get("contacts") or ()),
        agreed_meets=tuple(dict(m) for m in case.get("agreed_meets") or ()),
        told=tuple(str(c) for c in case.get("told") or ()), stage_before=str(case.get("stage_before") or ""),
        now=None if case.get("now") is None else float(case["now"]),
    )


def decision_of(case: dict[str, Any]) -> Decision:
    """The `Decision` a fixture dict's `decision:` describes (`situation` defaults to `reply`)."""
    row = dict(case.get("decision") or {})
    row.setdefault("situation", "reply")
    return Decision(**row)


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
    claims = data.get("meet_claims")
    if claims is not None:
        if not isinstance(claims, dict) or any(k not in MEET_WHENS for k in claims):
            faults.append(("meet_claims", f"must map {', '.join(MEET_WHENS)} to lists of phrases"))
        else:
            for when, value in claims.items():
                if not isinstance(value, list) or not all(isinstance(p, str) and _norm(p) for p in value):
                    faults.append((f"meet_claims.{when}", "must be a list of phrases, each with a word in it"))
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


def _claim(text: str, phrases: Iterable[str], *, negatable: bool = True) -> Optional[str]:
    """The first of ``phrases`` stated (not asked, not negated) in ``text``, or None."""
    phrases = tuple(phrases)
    if not phrases:
        return None
    negations = _phrases("negations") if negatable else ()
    for clause in _clauses(text, statements_only=True):
        for phrase in phrases:
            if any(not _negated(clause, m.start(), negations) for m in _hits(phrase, clause)):
                return phrase
    return None


def stated(text: str, phrases: Iterable[str], *, negatable: bool = True) -> Optional[str]:
    """The first of ``phrases`` (normalised here) stated in ``text`` -- not asked, and (``negatable``) not
    negated by the story's negations -- or None. For a check outside this module (meets' recap tone, T24)."""
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
    phrases = tuple(p for stage, words in claims.items() if stage not in reached
                    for p in (_norm(str(w)) for w in words or ()) if p)
    out = []
    for i, text in _items(reply, "bubbles"):
        hit = _claim(text, phrases)
        if hit:
            out.append(Failure("stage_claimed", "bubbles", i, hit))
    return out


@check_fn("profile_contradicted")
def _profile_contradicted(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """Their age, job or neighbourhood stated otherwise; a `learned` fact contradicting the player's (§11.5)."""
    jobs, places = _table_labels("jobs"), _table_labels("neighbourhoods")
    person, player = view.person, view.player or {}
    out = []
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
    age = player.get("age")
    if isinstance(age, int) and not isinstance(age, bool):
        wrong = next((a for a in _ages(text, rf"{be}|aged", anchored=True) if a != age), None)
        if wrong is not None:
            return f"player age {wrong}"
    job = str((player.get("attributes") or {}).get("job") or player.get("job") or "")
    if job:
        lead = rf"(?:(?:{subject})\s+)?works?\s+as(?:\s+an?)?|(?:{be})\s+an?"
        label = _other_label(text, lead, jobs, job, anchored=True)
        if label:
            return f"player job {label}"
    place = str(player.get("neighbourhood") or "")
    if place:
        lead = rf"(?:(?:{subject})\s+)?lives?\s+in|(?:{be})\s+based\s+in"
        label = _other_label(text, lead, places, place, anchored=True)
        if label:
            return f"player neighbourhood {label}"
    return ""


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
            tokens = _tokens(text)
            hit = next((form for form in forms if form in tokens), None)
            if hit:
                out.append(Failure("another_person", where, i, forms[hit]))
    return out


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


def _meet_day(row: dict[str, Any]) -> Optional[int]:
    day = row.get("day")
    return int(day) if isinstance(day, (int, float)) and not isinstance(day, bool) else None


@check_fn("meeting_claimed")
def _meeting_claimed(reply: dict[str, Any], decision: Decision, view: AgreementView) -> list[Failure]:
    """They agree to or state a meet-up `meets` has not agreed, or deny one it has (§11.5): a STATE check.

    A `meet_claims` phrase needs a planned meet-up of theirs (`PLANNED`): `today` one on the day of
    `view.now`, `tomorrow` one the day after, `any` one at all (with no `now`, `today` and `tomorrow`
    ask only for one at all). A `meet_denials` phrase fails while one is planned. Never a recap's: it
    tells of a meet-up that has happened, and is judged by its band instead (engine/social/meets.py)."""
    if decision.kind == "recap":
        return []
    planned = [m for m in view.agreed_meets if isinstance(m, dict) and m.get("status") in PLANNED]
    days = {_meet_day(m) for m in planned}
    today = None if view.now is None else 1 + int(float(view.now) // 24)
    claims = _data().get("meet_claims") or {}

    def holds(when: str) -> bool:
        if when == "any" or today is None:
            return bool(planned)
        return (today if when == "today" else today + 1) in days

    lists = [(when, tuple(p for p in (_norm(str(w)) for w in claims.get(when) or ()) if p))
             for when in MEET_WHENS if not holds(when)]
    denials = _phrases("meet_denials") if planned else ()
    out = []
    for i, text in _items(reply, "bubbles"):
        hit = next((h for _when, phrases in lists for h in [_claim(text, phrases)] if h), None)
        if hit is None and denials:
            hit = _claim(text, denials, negatable=False)
        if hit:
            out.append(Failure("meeting_claimed", "bubbles", i, hit))
    return out

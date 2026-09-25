"""
The Law
=======

Who the watch thinks you are, where, and how badly it wants you.

``paths.law`` names ONE YAML file::

    roles: [watch, sergeant, captain]          # schedule roles that ARE the law
    reporters: {vendor: 0.3, servant: 0.5}      # chance a witness goes straight to the watch
    jurisdictions: {dockside: [tallow_docks, wickmarket]}   # each location in at most one
    deeds: {pickpocket: {severity: 1}, loitering: {severity: 0}}
    notice: {base: 0.6, night: -0.25, per_margin: -0.05}
    wanted:
      bands: [unknown, noticed, sought, wanted, hunted]
      thresholds: [0, 2, 5, 9, 14]              # ascending, first is 0
      cool_per_day: 1.5
    precision: {1: 1.0, 2: 0.6, 3: 0.3}         # by hop
    recognise: {sought: 0.25, wanted: 0.5, hunted: 0.8}
    spread_per_hour: 0.3                         # optional
    guises: {self: {label: "your own face"}, magpie: {label: "...", item: magpie_mask}}
    links: [[self, magpie]]                      # what the watch believes at the start
    arrest: {encounter: watch_stop, gaol: lantern_house,
             fine_per_severity: 6, days_per_severity: 1,
             max_days: 3, max_fine: 30}             # the two caps are optional
    labels: {dockside: "the docks"}                    # optional; else a humanised id
    clarity_words: [nothing, a rumour, a description, a likeness]   # optional; ascending

THIS MODULE, SO FAR, is the data and the arithmetic every later piece reads:
the loader, and the WANTED score per guise per jurisdiction -- the sum of
severity x precision over the reports filed there, less what time has cooled
-- with the band word it falls in -- and ``commit_deed``, which turns a deed
into witness rows and any immediate reports -- and ``propagate``, which
``clock.advance_time`` calls each in-game hour to carry those rows person to
person until one reaches the watch, and to cool the files -- and the
PATROL: ``recognition``, which asks whether a watchman standing here knows
the face the player wears, and ``patrol``, which ``run_turn`` calls once a
turn to open the story's arrest scene on a hit -- and CUSTODY:
``sentence_for``, what an arrest charges, and ``pay_fine`` /
``serve_sentence``, the two engine ways out of it (a story may author a
third: a set-piece gated on the ``in_custody`` predicate, registered here,
whose success pays ``release``).

EVERY WRITE is an effect (AGENTS.md rule 3): ``witness`` records one sighting,
``report`` files one,
``quash_reports`` discharges some (a bribed sergeant's thread), ``law_cool``
lets time wear them down, ``arrest`` and ``release`` hold and free the
player, and ``deed`` lets authored content (a scene's fight with the watch)
commit one through ``commit_deed``. Nothing here assigns to ``state.law``.

The narrator never sees a number from here: the band is a word, and a
report's precision is spoken as ``clarity``. How well the watch knows the face
the player wears -- the wanted poster's sketch -- is ``clarity_word``, one of
the story's ``clarity_words``.

Every content fault is a ValueError naming the file, for the reason
``premises.py`` gives: a guise naming an item the registry lacks, or a gaol
that is not on the map, would load, validate and do nothing.

Version: v0.6.0 [2026-09-25]
"""

from __future__ import annotations

import copy
import logging
import math
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from engine.config import get_config
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
# The parsed, validated file. Registered in engine/games/caches.py: a story swap
# that kept it warm would police one city with another's watch.
_SPEC_CACHE: Optional[dict[str, Any]] = None

#: The guise every story must declare: the player's own face. It is what the
#: player wears when nothing else is on, so a file without it has no answer to
#: "who did the witness see?".
SELF_GUISE = "self"
#: How far rumour spreads per in-game hour when the file does not say. Read by
#: the propagation pass; defaulted here so it has one home.
DEFAULT_SPREAD_PER_HOUR = 0.3
#: How well the watch knows a face, ascending, when the file declares no
#: ``clarity_words``: the first is "no live report at all", the rest split
#: precision (0, 1] evenly -- see ``clarity_word``.
DEFAULT_CLARITY_WORDS = ("nothing", "a rumour", "a description", "a likeness")


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


def _law_path() -> Optional[Path]:
    rel = str(get_config().get("paths.law", "") or "").strip()
    return (_ROOT / rel) if rel else None


def declared() -> bool:
    """Whether the running story declares a Law at all."""
    return _law_path() is not None


def _fail(path: Path, message: str) -> ValueError:
    return ValueError(f"law: {path}: {message}")


def _chance(path: Path, where: str, raw: Any) -> float:
    """A probability in [0, 1]; anything else is a fault naming ``where``."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _fail(path, f"{where} must be a number") from None
    if not 0.0 <= value <= 1.0:
        raise _fail(path, f"{where} must be between 0 and 1")
    return value


def _number(path: Path, where: str, raw: Any, *, minimum: Optional[float] = None) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _fail(path, f"{where} must be a number") from None
    if minimum is not None and value < minimum:
        raise _fail(path, f"{where} must be at least {minimum:g}")
    return value


def _mapping(path: Path, doc: dict[str, Any], key: str) -> dict[str, Any]:
    raw = doc.get(key) or {}
    if not isinstance(raw, dict):
        raise _fail(path, f"`{key}` must be a mapping")
    return raw


def _deed_refs(node: Any) -> list[str]:
    """Every ``deed:`` value anywhere under ``node``.

    The arrest block may name the deed a violent approach commits (fighting
    the watch is itself a crime). Walked rather than read from one key so an
    author who nests it differently still gets the unknown-kind error instead
    of a fight that silently commits nothing.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "deed":
                found.append(str(value))
            else:
                found.extend(_deed_refs(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_deed_refs(value))
    return found


def _load_wanted(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
    raw = _mapping(path, doc, "wanted")
    bands = raw.get("bands")
    thresholds = raw.get("thresholds")
    if not isinstance(bands, list) or not bands:
        raise _fail(path, "`wanted.bands` must be a non-empty list")
    if not isinstance(thresholds, list) or len(thresholds) != len(bands):
        raise _fail(path, "`wanted.thresholds` must list one number per band")
    bands = [str(b) for b in bands]
    if len(set(bands)) != len(bands):
        raise _fail(path, "`wanted.bands` repeats a band")
    values = [_number(path, "`wanted.thresholds`", t) for t in thresholds]
    # The first band is where a score of zero lands -- "never below unknown"
    # is only true if the floor of the score is the floor of the first band.
    if values[0] != 0:
        raise _fail(path, "`wanted.thresholds` must start at 0")
    if any(b <= a for a, b in zip(values, values[1:])):
        raise _fail(path, "`wanted.thresholds` must strictly ascend")
    cool = _number(path, "`wanted.cool_per_day`", raw.get("cool_per_day", 0), minimum=0)
    return {"bands": bands, "thresholds": values, "cool_per_day": cool}


def _load_guises(path: Path, doc: dict[str, Any]) -> dict[str, dict[str, str]]:
    from engine.game.inventory import load_items

    raw = _mapping(path, doc, "guises")
    if SELF_GUISE not in raw:
        raise _fail(path, f"`guises` must declare `{SELF_GUISE}`, the player's own face")
    items = load_items()
    guises: dict[str, dict[str, str]] = {}
    for gid, body in raw.items():
        body = body if isinstance(body, dict) else {}
        label = str(body.get("label") or "").strip()
        # The label is the only thing about a guise the narrator ever says; an
        # empty one would put the id in the prose or nothing at all.
        if not label:
            raise _fail(path, f"guise `{gid}` needs a `label`")
        row = {"label": label}
        item = str(body.get("item") or "").strip()
        if item:
            if item not in items:
                raise _fail(path, f"guise `{gid}`: unknown item `{item}`")
            row["item"] = item
        guises[str(gid)] = row
    return guises


def _load_clarity_words(path: Path, doc: dict[str, Any]) -> list[str]:
    """``clarity_words``: at least two non-empty strings, ascending, or the defaults.

    Two because the first word means "no live report" and a sketch needs at
    least one word for having been seen. Strings only, and no digit inside
    one: a number here would reach the poster and the prose, and the narrator
    never sees one. No word twice (case and edge spaces ignored): two
    thresholds sharing a word are a rise the player cannot hear.
    """
    raw = doc.get("clarity_words")
    if raw is None:
        return list(DEFAULT_CLARITY_WORDS)
    if not isinstance(raw, list) or len(raw) < 2:
        raise _fail(path, "`clarity_words` must be a list of at least two words")
    words: list[str] = []
    seen: set[str] = set()
    for word in raw:
        if not isinstance(word, str) or not word.strip():
            raise _fail(path, f"`clarity_words`: `{word}` is not a word")
        if any(ch.isdigit() for ch in word):
            raise _fail(path, f"`clarity_words`: `{word}` holds a digit -- never a number")
        key = word.strip().casefold()
        if key in seen:
            raise _fail(path, f"`clarity_words`: `{word.strip()}` is listed twice")
        seen.add(key)
        words.append(word.strip())
    return words


def _check_arrest_encounter(path: Path, encounter_id: str) -> None:
    """
    The arrest scene must exist wherever the story ships encounters at all.

    A misspelt ``arrest.encounter`` otherwise loads, validates and stops
    nobody: the patrol finds no scene and warns once. Checked only when
    ``paths.encounters`` is declared -- a story with no encounters directory
    has nothing to check against, and ``patrol``'s one-time warning is the
    honest answer there.
    """
    if not encounter_id:
        return
    if not str(get_config().get("paths.encounters", "") or "").strip():
        return
    from engine.game import encounter  # late: encounter imports effects, which imports this

    if encounter.get_definition(encounter_id) is None:
        raise _fail(path, f"`arrest.encounter` `{encounter_id}` is not an encounter")


def load_spec() -> dict[str, Any]:
    """
    The parsed law file. Empty for a story that declares none.

    Raises:
        ValueError: naming the file, for a declared-but-missing file or any
            fault in the contract above.
    """
    global _SPEC_CACHE
    if _SPEC_CACHE is not None:
        return _SPEC_CACHE
    path = _law_path()
    if path is None:
        _SPEC_CACHE = {}
        return _SPEC_CACHE
    if not path.is_file():
        # Declared and absent is a broken install: the story promised a watch.
        raise ValueError(f"law: declared file {path} does not exist")

    from engine.game.locations import LOCATIONS

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        # A syntax error must name this file like any other fault; PyYAML's own
        # message names a line and a column but reaches the log as "a YAML
        # error somewhere during activation".
        raise _fail(path, f"is not valid YAML: {exc}") from None
    if not isinstance(doc, dict):
        raise _fail(path, "must be a mapping")

    roles = doc.get("roles") or []
    if not isinstance(roles, list):
        raise _fail(path, "`roles` must be a list")
    reporters = {
        str(role): _chance(path, f"reporter `{role}`", p)
        for role, p in _mapping(path, doc, "reporters").items()
    }

    jurisdictions: dict[str, list[str]] = {}
    owner: dict[str, str] = {}
    for name, locs in _mapping(path, doc, "jurisdictions").items():
        if not isinstance(locs, list) or not locs:
            raise _fail(path, f"jurisdiction `{name}` must list locations")
        for loc in map(str, locs):
            if loc not in LOCATIONS:
                raise _fail(path, f"jurisdiction `{name}`: unknown location `{loc}`")
            # Two jurisdictions would each keep a wanted level for one street,
            # and which one a patrol there consults would be dict order.
            if loc in owner:
                raise _fail(path, f"location `{loc}` is in both `{owner[loc]}` and `{name}`")
            owner[loc] = str(name)
        jurisdictions[str(name)] = [str(loc) for loc in locs]

    deeds: dict[str, int] = {}
    for kind, body in _mapping(path, doc, "deeds").items():
        severity = (body or {}).get("severity") if isinstance(body, dict) else None
        try:
            severity = int(severity)
        except (TypeError, ValueError):
            raise _fail(path, f"deed `{kind}` needs an integer `severity`") from None
        if severity < 0:
            raise _fail(path, f"deed `{kind}`: severity must not be negative")
        deeds[str(kind)] = severity

    notice_raw = _mapping(path, doc, "notice")
    # `base` is a probability; the other two are modifiers added to it, so they
    # may be negative and are only required to be numbers.
    notice = {
        "base": _chance(path, "`notice.base`", notice_raw.get("base", 0.6)),
        "night": _number(path, "`notice.night`", notice_raw.get("night", 0.0)),
        "per_margin": _number(path, "`notice.per_margin`", notice_raw.get("per_margin", 0.0)),
    }

    wanted = _load_wanted(path, doc)

    precision: dict[int, float] = {}
    for hop, value in _mapping(path, doc, "precision").items():
        try:
            hop_n = int(hop)
        except (TypeError, ValueError):
            raise _fail(path, f"precision hop `{hop}` must be an integer") from None
        # Hop 1 is the witness themselves; there is no hop before seeing it.
        if hop_n < 1:
            raise _fail(path, f"precision hop `{hop}` must be 1 or more")
        precision[hop_n] = _chance(path, f"precision hop `{hop}`", value)

    recognise: dict[str, float] = {}
    for band, value in _mapping(path, doc, "recognise").items():
        if str(band) not in wanted["bands"]:
            raise _fail(path, f"recognise: `{band}` is not a wanted band")
        recognise[str(band)] = _chance(path, f"recognise `{band}`", value)

    spread = _chance(path, "`spread_per_hour`", doc.get("spread_per_hour", DEFAULT_SPREAD_PER_HOUR))

    guises = _load_guises(path, doc)
    links: list[list[str]] = []
    raw_links = doc.get("links") or []
    if not isinstance(raw_links, list):
        raise _fail(path, "`links` must be a list of pairs")
    for pair in raw_links:
        if not (isinstance(pair, list) and len(pair) == 2):
            raise _fail(path, "each link must be a pair of guises")
        for gid in pair:
            if str(gid) not in guises:
                raise _fail(path, f"link names unknown guise `{gid}`")
        links.append([str(pair[0]), str(pair[1])])

    labels_raw = _mapping(path, doc, "labels")
    labels: dict[str, str] = {}
    for name, label in labels_raw.items():
        if str(name) not in jurisdictions:
            raise _fail(path, f"labels: `{name}` is not a jurisdiction")
        labels[str(name)] = str(label)

    arrest_raw = _mapping(path, doc, "arrest")
    arrest: dict[str, Any] = {}
    if arrest_raw:
        gaol = str(arrest_raw.get("gaol") or "")
        if gaol not in LOCATIONS:
            raise _fail(path, f"`arrest.gaol` `{gaol}` is not a location")
        arrest = {
            "encounter": str(arrest_raw.get("encounter") or ""),
            "gaol": gaol,
            "fine_per_severity": int(_number(
                path, "`arrest.fine_per_severity`", arrest_raw.get("fine_per_severity", 0), minimum=0
            )),
            "days_per_severity": int(_number(
                path, "`arrest.days_per_severity`", arrest_raw.get("days_per_severity", 0), minimum=0
            )),
        }
        # Optional ceilings (Task 7 fix): a charge sheet summed per deed grows
        # without bound, and a sentence longer than the story or a fine no
        # working thief can hold is not a choice between two exits.
        for cap in ("max_days", "max_fine"):
            if arrest_raw.get(cap) is not None:
                arrest[cap] = int(_number(path, f"`arrest.{cap}`", arrest_raw[cap], minimum=1))
        if isinstance(arrest_raw.get("approaches"), dict):
            arrest["approaches"] = arrest_raw["approaches"]
        _check_arrest_encounter(path, arrest["encounter"])
    for kind in _deed_refs(arrest_raw):
        if kind not in deeds:
            raise _fail(path, f"arrest names unknown deed `{kind}`")

    _SPEC_CACHE = {
        "roles": [str(r) for r in roles],
        "reporters": reporters,
        "jurisdictions": jurisdictions,
        "deeds": deeds,
        "notice": notice,
        "wanted": wanted,
        "precision": precision,
        "recognise": recognise,
        "spread_per_hour": spread,
        "guises": guises,
        "links": links,
        "arrest": arrest,
        "labels": labels,
        "clarity_words": _load_clarity_words(path, doc),
    }
    return _SPEC_CACHE


# ---------------------------------------------------------------------------
# Reading the Law
# ---------------------------------------------------------------------------


def jurisdiction_of(location_id: str) -> str:
    """The jurisdiction a location falls in, or "" where no watch reaches."""
    for name, locs in (load_spec().get("jurisdictions") or {}).items():
        if location_id in locs:
            return name
    return ""


def links(state: GameState) -> list[list[str]]:
    """What the watch currently believes: pairs of guises it takes for one person.

    State wins once it holds any belief, including an empty one -- a link the
    player has broken must stay broken. Until then the file's starting belief
    is read through rather than copied in, so a story with a Law writes
    nothing to a new save just by existing.
    """
    if "links" in state.law:
        return [list(pair) for pair in state.law.get("links") or []]
    return [list(pair) for pair in load_spec().get("links") or []]


def same_person(state: GameState, guise: str) -> set[str]:
    """Every guise the watch takes for the same person as ``guise``.

    Transitive: if the watch believes the Magpie is you and the porter is the
    Magpie, a report on the porter is a report on you. Belief in identity does
    not stop at one hop.
    """
    seen = {guise}
    frontier = [guise]
    pairs = links(state)
    while frontier:
        current = frontier.pop()
        for a, b in pairs:
            for here, there in ((a, b), (b, a)):
                if here == current and there not in seen:
                    seen.add(there)
                    frontier.append(there)
    return seen


def filed_score(state: GameState, guise: str, jurisdiction: str) -> float:
    """
    Severity x precision over the DEEDS filed under exactly ``guise`` here --
    one file in the watch-house, before cooling and before links.

    Each deed counts ONCE, at the best precision any report of it reached. A
    lift seen by three watchmen is one lift; counted per report, wanted would
    scale with the size of the crowd, and propagation (a report arriving again
    at hop 2) would multiply it again. A report row with no ``deed_id`` -- none
    exists in any save, but a hand edit could make one -- is its own deed.

    The unit cooling works on, and therefore what ``cap_cooling`` clamps to:
    one raw score, so a quash and a quiet week agree on what exists. Links are
    applied later, in ``wanted_score``: a link is what the watch believes about
    who wears which face, and it can change; which file a report went into
    cannot.
    """
    best: dict[Any, float] = {}
    for index, r in enumerate(state.law.get("reports") or []):
        if r.get("jurisdiction") != jurisdiction or r.get("guise") != guise:
            continue
        try:
            value = float(r.get("severity", 0)) * float(r.get("precision", 0))
        except (TypeError, ValueError):
            continue  # a malformed row is no heat; see `_files`
        key = r.get("deed_id") or ("row", index)
        best[key] = max(best.get(key, 0.0), value)
    return sum(best.values())


def _files(cool: Any, jurisdiction: str) -> dict[str, Any]:
    """One jurisdiction's ``{filed guise: offset}``, or {} for anything else.

    Tolerant on purpose: a malformed entry (a hand-edited save, the flat shape
    that briefly existed on the unreleased branch) reads as no cooling rather
    than raising mid-turn -- too much heat is recoverable, a crash is not.
    """
    files = cool.get(jurisdiction) if isinstance(cool, dict) else None
    return files if isinstance(files, dict) else {}


def cooling_of(state: GameState, guise: str, jurisdiction: str) -> float:
    """How much of one file quiet days have worn away. 0 when none, or malformed."""
    try:
        return float(_files(state.law.get("cool"), jurisdiction).get(guise, 0.0))
    except (TypeError, ValueError):
        return 0.0


def wanted_score(state: GameState, guise: str, jurisdiction: str) -> float:
    """
    How badly the watch here wants the person it takes ``guise`` for: the sum,
    over every guise linked to it (itself included), of that file's score less
    that file's own cooling, each floored at zero. Zero for a story with no Law.

    Per file, not per jurisdiction: quiet days over the Magpie's assaults must
    not pre-forgive a porter's fresh one. An engine number -- it feeds bands and
    rolls, never the narrator.
    """
    if not declared():
        return 0.0
    return sum(
        max(0.0, filed_score(state, g, jurisdiction) - cooling_of(state, g, jurisdiction))
        for g in same_person(state, guise)
    )


def band_for(score: float) -> str:
    """The band word a score falls in: the highest whose threshold it meets."""
    wanted = load_spec().get("wanted") or {}
    band = ""
    for name, floor in zip(wanted.get("bands") or [], wanted.get("thresholds") or []):
        if score >= floor:
            band = name
    return band


def wanted_band(state: GameState, guise: str, jurisdiction: str) -> str:
    """The wanted band word for ``guise`` here, or "" for a story with no Law."""
    if not declared():
        return ""
    return band_for(wanted_score(state, guise, jurisdiction))


def clarity(precision: float) -> str:
    """How well a report saw you, in words -- precision is never narrated."""
    if precision >= 0.9:
        return "seen clearly"
    if precision >= 0.5:
        return "half-seen"
    return "barely glimpsed"


def best_precision(state: GameState, guise: str, jurisdiction: str) -> float:
    """
    The best precision any LIVE report this watch-house holds on ``guise``,
    or on a face the watch links to it, reached. 0.0 when there is none.

    Live means not closed by a paid fine or served sentence (``discharged``)
    and not lost to a bribe here (``quashed``). Both effects already drop
    their rows, so in play this only guards a hand-edited save -- but a
    reader that trusted the rows alone would draw a likeness from a deed the
    player has paid for. An engine number: ``recognition`` rolls on it and
    ``clarity_word`` speaks it; neither lets it reach the prose.
    """
    faces = same_person(state, guise)
    closed = discharged(state) | quashed(state, jurisdiction)
    best = 0.0
    for r in state.law.get("reports") or []:
        if r.get("jurisdiction") != jurisdiction or r.get("guise") not in faces:
            continue
        if str(r.get("deed_id") or "") in closed:
            continue
        try:
            best = max(best, float(r.get("precision", 0)))
        except (TypeError, ValueError):
            continue  # a malformed row is no sighting; see `_files`
    return best


def clarity_word(state: GameState, guise: str, jurisdiction: str) -> str:
    """
    How well the watch in ``jurisdiction`` knows the face ``guise``, in the
    story's words -- the wanted poster's sketch. "" for a story with no Law.

    THE THRESHOLDS. With N ``clarity_words`` (ascending, N >= 2) and P =
    ``best_precision``: P = 0 (no live report, or no watch here at all) is
    the first word; otherwise P's share of (0, 1] picks among the other
    N - 1 evenly -- word ``1 + min(N - 2, floor(P x (N - 1)))``. With the four
    defaults that is below 1/3 "a rumour", below 2/3 "a description", and
    from 2/3 up "a likeness", so the shipped hops (0.3, 0.6, 1.0) land one on
    each: a witness's own account is a likeness, a third-hand one a rumour.

    Best, not newest or summed: one clear sighting is a likeness however many
    rumours follow it, and a hundred rumours are still a rumour. Links are
    followed (``same_person``): the Magpie's likeness is yours while the
    watch takes her for you.
    """
    if not declared():
        return ""
    words = load_spec().get("clarity_words") or list(DEFAULT_CLARITY_WORDS)
    precision = best_precision(state, guise, jurisdiction) if jurisdiction else 0.0
    if precision <= 0:
        return words[0]
    step = min(len(words) - 2, int(math.floor(min(precision, 1.0) * (len(words) - 1))))
    return words[1 + step]


def guise_label(guise: str) -> str:
    """A guise as the narrator may say it."""
    row = (load_spec().get("guises") or {}).get(guise) or {}
    return str(row.get("label") or "someone")


def jurisdiction_label(jurisdiction: str) -> str:
    """
    A jurisdiction as the narrator or the player may say it.

    Authored (``labels:`` in the file) when the story bothered to write one,
    else a humanised id -- never the raw id, which reads as an underscored
    slug rather than a place a watch patrols.
    """
    label = str((load_spec().get("labels") or {}).get(jurisdiction) or "").strip()
    if label:
        return label
    return str(jurisdiction).replace("_", " ").title()


def cap_cooling(
    state: GameState, offsets: dict[str, dict[str, float]]
) -> dict[str, dict[str, float]]:
    """
    Cooling offsets ``{jurisdiction: {filed guise: offset}}``, each clamped to
    its own file's score, with emptied files dropped.

    An offset per file rather than a rewrite of every report row, so the rows
    stay what was filed and a later quash still sees them. Unclamped, an offset
    would keep growing through a quiet week and pre-forgive the next crime in
    that file; clamped, it can erase what exists, never what has not happened
    yet. Returned rather than assigned: the effects that call this are the
    writers.
    """
    capped: dict[str, dict[str, float]] = {}
    for jurisdiction in offsets if isinstance(offsets, dict) else ():
        for guise, offset in _files(offsets, jurisdiction).items():
            try:
                offset = float(offset)
            except (TypeError, ValueError):
                continue  # a malformed offset is no cooling; see `_files`
            value = min(offset, filed_score(state, guise, jurisdiction))
            if value > 0:
                capped.setdefault(jurisdiction, {})[guise] = value
    return capped


# ---------------------------------------------------------------------------
# Deeds and witnesses
# ---------------------------------------------------------------------------

#: The ``time_of_day`` labels (``GameState.time_of_day``) under which
#: ``notice.night`` applies. Dusk counts: 17:00-20:00 is lamp-lighting in a
#: candle-port, the hour a face under a hood stops being a face -- and the data
#: contract names both. Dawn does not: 05:00-08:00 is the market setting up,
#: every stall-holder awake and looking.
DARK_HOURS = frozenset({"dusk", "night"})
#: Witness chance is clamped into this band whatever the modifiers say. Never
#: certain, because a crowded noon still has a moment everyone looks away;
#: never impossible, because a black night still has a window with a face in it.
NOTICE_FLOOR, NOTICE_CEILING = 0.05, 0.95


def notice_chance(state: GameState, margin: Optional[float] = None) -> float:
    """The chance one awake bystander sees a deed, now, at this stealth margin."""
    notice = load_spec().get("notice") or {}
    chance = float(notice.get("base", 0.0))
    if state.time_of_day in DARK_HOURS:
        chance += float(notice.get("night", 0.0))
    if margin is not None:
        chance += float(notice.get("per_margin", 0.0)) * float(margin)
    return min(NOTICE_CEILING, max(NOTICE_FLOOR, chance))


def current_guise(state: GameState) -> str:
    """
    The face the player is EFFECTIVELY wearing: what a witness files. Own
    face by default.

    A stored guise whose item the player no longer carries is not honoured
    -- a mask left behind cannot still be on the player's face, whatever
    ``state.law["guise"]`` still says. Read-only: this never writes the
    stale value away, because a save that later regains the item should read
    as wearing it again, not as having reverted to ``self`` for good. Only
    ``law_guise`` (the effect) writes the field; this is just how everything
    else -- ``commit_deed``, the wanted score, the ``guise`` verb -- must read
    it.
    """
    guise = str(state.law.get("guise") or SELF_GUISE)
    if guise == SELF_GUISE or not declared():
        return guise
    item = str((load_spec().get("guises") or {}).get(guise, {}).get("item") or "")
    if not item:
        return guise
    from engine.game import inventory  # late: inventory imports effects, not law

    return guise if inventory.holds(state, item) else SELF_GUISE


def commit_deed(
    state: GameState,
    kind: str,
    *,
    margin: Optional[float] = None,
    location: Optional[str] = None,
    certain: tuple[str, ...] | list[str] = (),
    exclude: tuple[str, ...] | list[str] = (),
    informants: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """
    The player did ``kind`` here, now: find who saw it and who told the watch.

    CANDIDATES are everyone ``npc_sim`` places at the location this hour and
    who is ``available`` -- a sleeper sees nothing. A street deed never sees
    the households indoors because ``npcs_at`` already keeps them apart
    (an interior id never equals its district's); a deed INSIDE a house is
    seen by that household, for the same reason.

    Each candidate rolls ``notice_chance`` on the LAW stream. ``certain`` ids
    witness without rolling -- the mark who caught the hand. ``exclude`` ids
    neither roll nor witness: the check already answered for them, and a mark
    the receipt says did not notice must not turn up among the witnesses.
    ``informants`` witness AND report without rolling -- the honest vendor the
    player just tried to sell hot goods to, who needs no luck to know what
    was on the counter. Every other witness whose role is in ``roles`` is the
    watch itself and reports at once; one whose role is in ``reporters``
    reports with that chance.

    A deed of severity 0 (loitering) is REMEMBERED -- one witness row each,
    which later tasks read as "someone saw you by that house" -- and never
    reported on its own, per the contract. A kind the story does not list is
    not a crime there and commits nothing. A deed where no jurisdiction
    reaches keeps its witnesses and files no report: there is no watch-house
    for the word to reach.

    Rolls happen HERE and only here -- never while a prompt, the legal
    intents or a payload is being built -- so a replayed seed with the same
    choices sees the same witnesses. Every write is an effect.

    Returns:
        ``{"witnesses": [npc ids], "reported": bool}``. Ids are for the
        engine; the narrator is handed display names, never these.
    """
    from engine.game.effects import apply_effect
    from engine.game.rng import LAW, world_rng
    from engine.world import npc_sim

    result: dict[str, Any] = {"witnesses": [], "reported": False}
    if not declared():
        return result
    spec = load_spec()
    if kind not in spec["deeds"]:
        return result
    where = str(location or state.location_id)
    guise = current_guise(state)
    excluded = {str(n) for n in exclude}
    sure = [str(n) for n in certain if str(n) not in excluded]
    telling = [str(n) for n in informants if str(n) not in excluded]

    # (npc id, role) in a stable order: present people first, in
    # `npcs_at` order, then certain/informant ids who are not otherwise here
    # (a vendor profile need not be a scheduled person). The order is part of
    # the replay: it decides which draw each roll consumes.
    roster: list[tuple[str, str]] = []
    listed: set[str] = set()
    for person in npc_sim.npcs_at(state, where):
        if person.npc_id in excluded or not person.available:
            continue
        roster.append((person.npc_id, person.role))
        listed.add(person.npc_id)
    for npc_id in sure + telling:
        if npc_id not in listed:
            presence = npc_sim.resolve_npc(state, npc_id)
            roster.append((npc_id, presence.role if presence else ""))
            listed.add(npc_id)

    rng = None

    def _roll() -> float:
        # One stream counter per deed, drawn lazily: a deed nobody could see
        # does not advance LAW at all.
        nonlocal rng
        if rng is None:
            rng = world_rng(state, LAW)
        return rng.random()

    chance = notice_chance(state, margin)
    severity = spec["deeds"][kind]
    # The street's watch hears of a deed inside one of its houses: an interior
    # id is in no jurisdiction's list, its district is.
    jurisdiction = jurisdiction_at(where)
    roles = set(spec["roles"])

    # TWO PASSES on the one per-deed stream: every notice roll, in roster
    # order, before any reporter roll. Interleaved, a story that tuned a
    # `reporters` chance would move which draw each later bystander's notice
    # consumed -- tuning who tells the watch would change who SAW.
    seen: list[tuple[str, str]] = [
        (npc_id, role)
        for npc_id, role in roster
        if npc_id in sure or npc_id in telling or _roll() < chance
    ]
    telling_now: list[bool] = []
    for npc_id, role in seen:
        if severity <= 0 or not jurisdiction:
            telling_now.append(False)
        elif npc_id in telling or role in roles:
            telling_now.append(True)
        elif role in spec["reporters"]:
            telling_now.append(_roll() < spec["reporters"][role])
        else:
            telling_now.append(False)

    # One deed, one id: the first witness row allocates it (inside the
    # effect, the only writer), and every later row and report of this deed
    # carries it, so the watch-house counts the deed once however many saw it.
    deed_id = ""
    for (npc_id, _role), tells in zip(seen, telling_now):
        row = apply_effect(state, {"type": "witness", "deed": kind, "guise": guise,
                                   "npc": npc_id, "where": where, "deed_id": deed_id})
        deed_id = deed_id or str(row.get("deed_id") or "")
        result["witnesses"].append(npc_id)
        if tells:
            filed = apply_effect(state, {"type": "report", "deed": kind, "guise": guise,
                                         "jurisdiction": jurisdiction, "precision": 1.0,
                                         "deed_id": deed_id})
            result["reported"] = result["reported"] or bool(filed.get("ok"))
    # Every committed deed is the LAST deed, seen or not: the narrator's "you
    # were seen" reads this stamp, never simply the newest witnessed deed.
    apply_effect(state, {"type": "law_last_deed", "deed_id": deed_id, "where": where})
    return result


# ---------------------------------------------------------------------------
# Reports travel
# ---------------------------------------------------------------------------

#: The most in-game hours of TALK one call steps through. A long sleep carries
#: rumour at most two days: past that, everyone who shares a room with a
#: witness has long since shared it, and a week asleep would otherwise cost a
#: week of presence resolution in the middle of one turn. Cooling is not
#: capped -- it is one cheap effect per hour, and a capped one would forgive a
#: week-long sleeper two days' worth.
#:
#: The cap is PER CALL, so the cut-invariance ``propagate`` promises holds
#: only for calls of 48 hours or less: one 72h call talks for 48 hours, three
#: 24h calls talk for all 72. No shipped caller moves the clock more than 24
#: hours at once (a night's rest, a served day), so none reaches the cap --
#: recorded as deferred in docs/GOVERNANCE.md rather than engineered around.
MAX_PROPAGATION_HOURS = 48
#: Slack on the hour-boundary arithmetic, so a clock that reached 12.0 by
#: adding thirds counts the boundary at 12 exactly once, in whichever call
#: crossed it.
_HOUR_EPSILON = 1e-6


def _max_hop(spec: dict[str, Any]) -> int:
    """How far a sighting may travel: gossip's cap, shortened by the file.

    ``gossip.MAX_HOPS`` is the same three removes the background rumour mill
    keeps, so a deed and a remark die at the same distance. A hop the file
    gives no precision for is a hop the rumour does not make -- there is no
    honest number to file it at.
    """
    from engine.world.gossip import MAX_HOPS

    precision = spec.get("precision") or {}
    hop = 1
    while hop < MAX_HOPS and (hop + 1) in precision:
        hop += 1
    return hop


def jurisdiction_at(location_id: str) -> str:
    """The watch a person standing here answers to. A house answers to its street."""
    from engine.world.npc_sim import INTERIOR_SEPARATOR

    return jurisdiction_of(location_id) or jurisdiction_of(
        str(location_id).split(INTERIOR_SEPARATOR, 1)[0]
    )


def _holdings(
    state: GameState,
) -> tuple[dict[str, dict[str, set[int]]], dict[str, dict[str, dict[str, Any]]], dict[str, int]]:
    """Who holds which deed at which hops, each holder's best row per deed, deed order."""
    hops: dict[str, dict[str, set[int]]] = {}
    best: dict[str, dict[str, dict[str, Any]]] = {}
    order: dict[str, int] = {}
    for row in state.law.get("witnessed") or []:
        npc, deed_id = str(row.get("npc")), str(row.get("deed_id"))
        hop = int(row.get("hop") or 1)
        order.setdefault(deed_id, len(order))
        hops.setdefault(npc, {}).setdefault(deed_id, set()).add(hop)
        held = best.setdefault(npc, {})
        if deed_id not in held or hop < int(held[deed_id].get("hop") or 1):
            held[deed_id] = row
    return hops, best, order


def _presence_scratch(state: GameState) -> GameState:
    """
    A SHALLOW COPY to resolve presence on, its clock free to be set per hour --
    the ``premises._occupancy_text`` pattern. The real clock is never moved:
    only ``advance_time`` may do that, and it is already running. The copy
    shares flags and events, so a quest pin keeps its person where it keeps
    them on the street.

    Its procgen answers ``npc_by_id`` from a dict built once per call rather
    than a scan of the cast per lookup: the pass resolves the cast up to 48
    times, and the scan made that quadratic in the cast. Only the copy's
    procgen is touched.
    """
    scratch = copy.copy(state)
    procgen = copy.copy(state.procgen)
    index = {str(npc.get("id")): npc for npc in reversed(procgen.npcs) if npc.get("id")}
    procgen.npc_by_id = index.get  # type: ignore[method-assign]
    scratch.procgen = procgen
    return scratch


def _propagate_hour(
    state: GameState, scratch: GameState, hour: int, spec: dict[str, Any]
) -> Optional[dict[str, int]]:
    """
    One hour of talk: who stood with whom through ``hour``, and what they told.

    ``hour`` is the hour that just ELAPSED (the boundary crossed, less one):
    people talk during an hour, so a baker who left the ovens at noon has
    spent the noon hour in the square by the time the clock reads 13:00.

    WHAT IS TOLD is read from a snapshot taken before anyone speaks, so a thing
    heard this hour is not passed on until the next: one hour, one remove.
    Each awake person offers every deed they hold at their best hop plus one to
    the others awake in the room who have never heard it. An offer with nobody
    to hear it rolls nothing; the rest roll ``spread_per_hour``, and a telling
    picks its listener from the same generator.

    Tellers are resolved first and everyone else only if one is awake: most
    hours of a long sleep are a night in which every witness is abed.

    Rooms in sorted order, people in sorted order, deeds in the order they
    were first seen: that order is the replay.

    Returns:
        The hour's counts, or None when nobody holds anything left to tell --
        which stays true for the rest of the call, since only telling makes
        new tellers.
    """
    from engine.game.effects import apply_effect
    from engine.game.rng import LAW, world_rng
    from engine.world import npc_sim

    top = _max_hop(spec)
    hops, best, order = _holdings(state)
    tellers = sorted(
        npc for npc, held in best.items()
        if any(int(row.get("hop") or 1) < top for row in held.values())
    )
    if not tellers:
        return None
    result = {"told": 0, "reported": 0}
    scratch.world_clock_hours = float(hour)

    placed: dict[str, Any] = {}
    for npc_id in tellers:
        placed[npc_id] = npc_sim.resolve_npc(scratch, npc_id)
    teller_rooms = {
        p.location_id for p in placed.values()
        if p is not None and p.available and p.location_id
    }
    if not teller_rooms:
        return result
    rooms: dict[str, list[tuple[str, str]]] = {}
    for npc_id in sorted(set(npc_sim.known_npc_ids(scratch))):
        presence = placed[npc_id] if npc_id in placed else npc_sim.resolve_npc(scratch, npc_id)
        if presence is None or not presence.available or presence.location_id not in teller_rooms:
            continue
        rooms.setdefault(presence.location_id, []).append((npc_id, presence.role))

    def _may_hear(listener: str, deed_id: str) -> bool:
        # STRICTER THAN GOSSIP, on purpose. v0.7.2 lets a listener hear a
        # rumour again further from its source, because a heard-note is
        # narrated and "it's going round" is news about how far it travelled.
        # A witness row is never narrated that way: a worse copy would change
        # no score and only steal the roll from someone who has never heard.
        # So whoever holds a deed at any hop is not told it again -- and a
        # watchman who first hears at hop 3 is not upgraded later.
        return deed_id not in hops.get(listener, {})

    spread = float(spec.get("spread_per_hour", DEFAULT_SPREAD_PER_HOUR))
    roles = set(spec.get("roles") or [])
    rng = None
    for room in sorted(rooms):
        people = rooms[room]
        if len(people) < 2:
            continue
        role_of = dict(people)
        for speaker, _role in people:
            held = best.get(speaker) or {}
            for deed_id in sorted(held, key=lambda d: order.get(d, 0)):
                source = held[deed_id]
                hop = int(source.get("hop") or 1) + 1
                if hop > top:
                    continue
                listeners = [
                    npc for npc, _r in people
                    if npc != speaker and _may_hear(npc, deed_id)
                ]
                if not listeners:
                    continue
                # One stream counter per hour, drawn lazily: an hour in which
                # nobody could tell anybody anything does not advance LAW.
                if rng is None:
                    rng = world_rng(state, LAW)
                if rng.random() >= spread:
                    continue
                listener = listeners[rng.randrange(len(listeners))]
                precision = float(spec["precision"][hop])
                # Only who heard, how far out and how clearly change: the deed,
                # its id, severity, guise and place are the sighting's own, or
                # the counted-once score could be fooled by a copy.
                row = apply_effect(state, {
                    "type": "witness", "deed": source.get("deed"), "guise": source.get("guise"),
                    "npc": listener, "where": source.get("where"),
                    "deed_id": deed_id, "hop": hop, "precision": precision,
                })
                if not row.get("ok"):
                    continue
                hops.setdefault(listener, {}).setdefault(deed_id, set()).add(hop)
                result["told"] += 1
                # It reached the watch. Filed where THIS watchman stands, which
                # need not be where the deed was done: that district has heard.
                jurisdiction = jurisdiction_at(room)
                if (
                    role_of[listener] in roles
                    and int(source.get("severity") or 0) > 0
                    and jurisdiction
                ):
                    filed = apply_effect(state, {
                        "type": "report", "deed": source.get("deed"), "guise": source.get("guise"),
                        "jurisdiction": jurisdiction, "precision": precision, "deed_id": deed_id,
                    })
                    result["reported"] += int(bool(filed.get("ok")))
    return result


def propagate(
    state: GameState,
    hours: float,
    *,
    each_hour: Optional[Callable[[int], None]] = None,
) -> dict[str, int]:
    """
    Let ``hours`` pass for the watch: talk carries what witnesses saw, person
    to person, and quiet wears the files down.

    Called from ``clock.advance_time`` once the clock has moved. It walks the
    whole-hour boundaries the clock just crossed -- from ``now - hours`` to
    ``now`` -- and at each one runs an hour of talk (the first
    ``MAX_PROPAGATION_HOURS`` only) and then an hour of cooling (every one).
    Keyed on boundaries rather than on ``hours`` itself, twelve 1h calls,
    forty-eight quarter hours and one 12h call do the same work in the same
    order and leave ``state.law`` bit-identical, and a background tick that
    moves no time does nothing (AGENTS.md, "Time and randomness in new
    systems"). Cooling per hour rather than per call is what stops a report
    filed at hour 47 of a two-day sleep being worn away by the 46 hours before
    it existed -- and what keeps the band from depending on how the wall
    clock happened to cut the background ticks.

    NOT GOSSIP'S BUSINESS. ``engine/world/gossip.py`` moves ledger notes and
    recalled facts between people and never reads or writes ``state.law`` --
    witness rows are not ledger facts -- so nothing a witness saw travels
    twice. This pass owns them; it borrows gossip's hop cap, not its tick.

    ``each_hour``, when given, is called with each boundary AFTER that hour's
    talk and cooling: the agendas pass (``agendas.Walk.hour``) fires its
    moves there, so a report or sighting a move files at 01:00 cools and
    travels through the hours after it in this same call, as it would had
    the call ended at 01:00. A sighting it adds makes a teller, so talk
    resumes. Without it (every story with no agendas) nothing changes.

    Returns:
        ``{"told": n, "reported": n}`` for the log; the rows are the record.
    """
    from engine.game.clock import HOURS_PER_DAY

    result = {"told": 0, "reported": 0}
    if not declared() or hours <= 0:
        return result
    spec = load_spec()
    end = float(state.world_clock_hours)
    first = math.floor(end - float(hours) + _HOUR_EPSILON) + 1
    last = math.floor(end + _HOUR_EPSILON)
    talking = bool(state.law.get("witnessed"))
    scratch: Optional[GameState] = None
    for boundary in range(first, last + 1):
        if talking and boundary - first < MAX_PROPAGATION_HOURS:
            scratch = scratch or _presence_scratch(state)
            step = _propagate_hour(state, scratch, boundary - 1, spec)
            if step is None:
                talking = False
            else:
                result["told"] += step["told"]
                result["reported"] += step["reported"]
        # Nothing filed, nothing to wear down: skipping writes exactly what
        # `law_cool` would have written, which is nothing.
        if state.law.get("reports"):
            cool(state, 1.0 / HOURS_PER_DAY)
        if each_hour is not None:
            heard = len(state.law.get("witnessed") or [])
            each_hour(boundary)
            if len(state.law.get("witnessed") or []) != heard:
                talking = True
    return result


def cool(state: GameState, days: float) -> dict[str, Any]:
    """Let ``days`` of quiet wear the watch's memory down. Through ``law_cool``."""
    from engine.game.effects import apply_effect

    return apply_effect(state, {"type": "law_cool", "days": days})


# ---------------------------------------------------------------------------
# Guises
# ---------------------------------------------------------------------------


def change_guise(state: GameState, guise_id: str) -> dict[str, Any]:
    """
    Put on a different face. Costs no hours -- a change of guise is a choice,
    not an errand, and a hidden hours charge here would be a stealth gate on
    the one system whose whole point is to be always available.

    VALIDATED BEFORE ANY ROLL: the ``law_guise`` effect is applied first, and
    an illegal request (an unknown guise, or one whose item is not carried)
    returns its refusal without ever touching the LAW stream or the roster --
    a refused change is not a sighting, and the stream must stay exactly as
    untouched as if the attempt had never been made.

    Only once the change has actually taken does anyone get a chance to see
    it. Whoever is present and available at the player's own location -- the
    same street-only ``npcs_at`` roster ``commit_deed`` rolls against, so an
    interior household never sees a change made on the street outside it --
    gets one roll of ``notice_chance``'s base rate (no margin: there is no
    stealth check here, just an ordinary look) on the LAW stream. If anyone's
    roll comes up, the watch's belief updates through ``law_link``: from now
    on a report against the old face is a report against the new one too.

    Rolls only run when there IS a change (a new guise differing from the
    one ``current_guise`` reads as worn) and only for a story with a Law --
    a request to become the face already worn is a no-op the watch never
    gets a chance to notice.

    Returns:
        ``{"ok": True, "guise", "label", "seen"}`` on success, or
        ``{"ok": False, "message"}`` for an unknown guise or one whose item
        the player is not carrying (the ``law_guise`` effect's own refusal,
        read through rather than duplicated here).
    """
    from engine.game.effects import apply_effect
    from engine.game.rng import LAW, world_rng
    from engine.world import npc_sim

    guise_id = str(guise_id)
    old = current_guise(state)
    changed = apply_effect(state, {"type": "law_guise", "guise": guise_id})
    if not changed.get("ok"):
        return {"ok": False, "message": changed.get("message") or "you cannot become that"}
    seen = False
    if declared() and old != guise_id:
        chance = notice_chance(state)
        rng = None
        for person in npc_sim.npcs_at(state, state.location_id):
            if not person.available:
                continue
            if rng is None:
                # Lazy, as `commit_deed`'s: nobody present to look means the
                # stream never moves.
                rng = world_rng(state, LAW)
            if rng.random() < chance:
                seen = True
        if seen:
            apply_effect(state, {"type": "law_link", "a": old, "b": guise_id})
    return {"ok": True, "guise": guise_id, "label": guise_label(guise_id), "seen": seen}


# ---------------------------------------------------------------------------
# Patrols, arrest and custody
# ---------------------------------------------------------------------------

# Arrest encounter ids already warned about as missing. A story whose law file
# names a scene its encounters directory lacks would otherwise log the same
# WARNING every turn for the rest of the run. Nulled per activation
# (engine/games/caches.py), the `director._WARNED_FORCED` pattern.
_WARNED_ENCOUNTERS: Optional[set[str]] = None


def custody(state: GameState) -> dict[str, Any]:
    """The player's custody record, or {} when free. A copy; the effects write it."""
    held = state.law.get("custody")
    return dict(held) if isinstance(held, dict) else {}


def in_custody(state: GameState) -> bool:
    """Whether the watch is holding the player. Cheap: a story with no Law reads {}."""
    return bool(custody(state))


def _p_in_custody(state: GameState, value: Any, ctx: Any) -> bool:
    """``{in_custody: true}`` -- whether the watch holds the player right now.

    The condition-grammar face of ``in_custody``: the ``arrest`` effect writes
    the custody record and sets no flag, so without this nothing authored --
    a set-piece's ``requires:``, a card, an ending gate -- could ask "is the
    player in the cells?". False in a story that declares no Law, whatever
    ``state.law`` happens to carry, so ``{in_custody: false}`` is simply true
    there.
    """
    held = declared() and in_custody(state)
    return held is bool(value)


def charged_deeds(state: GameState, guise: str, jurisdiction: str) -> dict[str, int]:
    """
    The charge sheet: ``{deed id: severity}`` for every deed filed in
    ``jurisdiction`` against ``guise`` or a face linked to it, each deed ONCE
    at its highest filed severity.

    Keyed by deed id so the arrest can record EXACTLY what it charged, and
    paying or serving can discharge exactly that and nothing filed later. A
    report row with no ``deed_id`` (none exists in any save; a hand edit
    could make one) is keyed by its row position, charged, and -- having no
    id to discharge by -- left filed.
    """
    faces = same_person(state, guise)
    best: dict[str, int] = {}
    for index, r in enumerate(state.law.get("reports") or []):
        if r.get("jurisdiction") != jurisdiction or r.get("guise") not in faces:
            continue
        try:
            severity = int(r.get("severity", 0))
        except (TypeError, ValueError):
            continue  # a malformed row is no charge; see `_files`
        key = str(r.get("deed_id") or f"#row{index}")
        best[key] = max(best.get(key, 0), severity)
    return best


def charged_severity(state: GameState, guise: str, jurisdiction: str) -> int:
    """
    What the watch here can charge the person it takes ``guise`` for: the sum
    of SEVERITY over ``charged_deeds``.

    Counted once for ``filed_score``'s reason -- a lift three watchmen saw is
    one lift in front of a magistrate too. Severity, not severity x precision:
    precision is how sure the watch is of WHO; once the person is in the cell,
    the charge sheet is what was done. Cooling is not subtracted either: a
    quiet month makes the watch stop looking, it does not unwrite the file.

    Linked faces only: a porter's crimes that nobody has tied to you are not
    on YOUR sheet -- charging them would tell the player the watch knows
    something it does not.
    """
    return sum(charged_deeds(state, guise, jurisdiction).values())


def discharged(state: GameState) -> set[str]:
    """Deed ids a paid fine or a served sentence has closed for good."""
    return {str(d) for d in state.law.get("discharged_deeds") or []}


def quashed(state: GameState, jurisdiction: str) -> set[str]:
    """Deed ids a bribe made ``jurisdiction``'s watch-house lose (``quash_reports``)."""
    return {str(d) for d in (state.law.get("quashed") or {}).get(jurisdiction) or []}


def sentence_for(state: GameState, guise: str, jurisdiction: str) -> dict[str, int]:
    """
    The fine and the days an arrest here costs, as ``{"fine", "days"}``.

    THE FORMULA, with S = ``charged_severity``::

        fine = arrest.fine_per_severity x S
        days = arrest.days_per_severity x S, at least 1 when S > 0

    then each clamped to ``arrest.max_days`` / ``arrest.max_fine`` when the
    file declares them (optional, integers of at least 1).

    The floor is so a story that sets ``days_per_severity: 0`` (fines only)
    still offers a way out to a player with no coin: serving is the exit that
    costs nothing but time, and a zero-day sentence would read as no sentence
    at all. S = 0 (an authored arrest of a clean face) is free and immediate
    either way.
    """
    arrest = load_spec().get("arrest") or {}
    severity = charged_severity(state, guise, jurisdiction)
    days = int(arrest.get("days_per_severity", 0)) * severity
    fine = int(arrest.get("fine_per_severity", 0)) * severity
    days = max(1, days) if severity > 0 else 0
    # The story's ceilings, when it declares them: applied last, so the floor
    # of one day still holds (max_days is at least 1).
    if arrest.get("max_days"):
        days = min(days, int(arrest["max_days"]))
    if arrest.get("max_fine"):
        fine = min(fine, int(arrest["max_fine"]))
    return {"fine": fine, "days": days}


def recognition(state: GameState) -> dict[str, Any]:
    """
    Does a watchman standing here know the face the player is wearing?

    For each law-role person present and AWAKE, in ``npcs_at`` order, one roll
    on the LAW stream against ``recognise[band] x precision``: the band is the
    current guise's wanted band in this jurisdiction, and the precision is the
    best any report the watch holds on that face (or a face linked to it)
    reached here. The first hit wins; later watchmen do not roll.

    NOTHING ROLLS unless the band is one ``recognise`` lists -- ``unknown`` and
    ``noticed`` never are in the shipped contract -- nor while the player is
    held, nor while a scene owns the turn (an encounter, a dealt card or a
    set-piece: ``intents.scene_owns_turn``, the gates ``legal_intents``
    itself uses, so the two cannot disagree about what "open" means): a stream that moved on those turns would
    make every later roll depend on how long a player lingered in a cell or a
    fight. Drawn lazily, like ``commit_deed``'s, so a street with no watchman
    does not advance the stream either.

    Returns:
        ``{"recognised": False}``, or ``{"recognised": True, "npc", "name",
        "guise", "label"}``. The id is for the engine; the name and label are
        what the narrator may say.
    """
    from engine.game import intents
    from engine.game.rng import LAW, world_rng
    from engine.world import npc_sim

    miss: dict[str, Any] = {"recognised": False}
    if not declared() or in_custody(state) or intents.scene_owns_turn(state):
        return miss
    spec = load_spec()
    jurisdiction = jurisdiction_at(state.location_id)
    if not jurisdiction:
        return miss
    guise = current_guise(state)
    band = wanted_band(state, guise, jurisdiction)
    chance = float((spec.get("recognise") or {}).get(band, 0.0))
    if chance <= 0:
        return miss
    precision = best_precision(state, guise, jurisdiction)
    if precision <= 0:
        return miss
    roles = set(spec.get("roles") or [])
    rng = None
    for person in npc_sim.npcs_at(state, state.location_id):
        if not person.available or person.role not in roles:
            continue
        if rng is None:
            rng = world_rng(state, LAW)
        if rng.random() < chance * precision:
            return {
                "recognised": True,
                "npc": person.npc_id,
                "name": npc_sim.display_name(person.npc_id, state),
                "guise": guise,
                "label": guise_label(guise),
            }
    return miss


def patrol(state: GameState) -> Optional[dict[str, Any]]:
    """
    The watch's turn: one recognition check and, on a hit, the arrest scene.

    Called by ``engine/scenes/default_state.py::run_turn`` once a turn, after
    the player's intent has executed and before anything is narrated, so the
    narrator is TOLD of the stop rather than inventing one. On a hit it opens
    ``arrest.encounter`` through ``encounter.begin`` -- the scene's approaches
    (run, talk, bribe, surrender, fight) are the story's -- and returns a
    receipt naming the watchman and the face he knew.

    A law file whose ``arrest.encounter`` names no loaded scene is a content
    fault: it is logged ONCE as a WARNING and nothing rolls, so a broken story
    neither shifts the stream for a stop that cannot happen nor spams the log.

    Returns:
        A receipt in the shape ``execute_tool`` produces (skill
        ``law_recognition``), or None when nobody knew the player.
    """
    global _WARNED_ENCOUNTERS
    if not declared() or in_custody(state):
        return None
    from engine.game import encounter, intents

    if intents.scene_owns_turn(state):
        return None
    encounter_id = str((load_spec().get("arrest") or {}).get("encounter") or "")
    if not encounter_id:
        return None  # a Law with no arrest block keeps files and stops nobody
    if encounter.get_definition(encounter_id) is None:
        if _WARNED_ENCOUNTERS is None:
            _WARNED_ENCOUNTERS = set()
        if encounter_id not in _WARNED_ENCOUNTERS:
            _WARNED_ENCOUNTERS.add(encounter_id)
            logger.warning(
                "[law] arrest.encounter names no loaded encounter "
                "(operation=patrol, id=%s). The watch cannot stop anyone.",
                encounter_id,
            )
        return None
    hit = recognition(state)
    if not hit.get("recognised"):
        return None
    encounter.begin(state, encounter_id)
    return {
        "type": "law",
        "skill": "law_recognition",
        "args": {},
        "result": {"ok": True, "name": hit["name"], "label": hit["label"]},
        "success": True,
    }


def _discharge(state: GameState, held: dict[str, Any]) -> None:
    """
    Close exactly the deeds the arrest charged: the sentence was the debt.

    Without this the watchman at the gaol door would know the face he had just
    let out, and a paid fine would be followed by the same arrest the next
    turn. Through ``law_discharge``, which drops those deeds' reports AND
    witness rows and remembers them, so no witness can carry a served deed to
    a new watchman afterwards. Deeds filed after the arrest were never
    charged and stay filed. A break-out -- a bare ``release`` from a story's
    own scene -- does NOT come through here.
    """
    from engine.game.effects import apply_effect

    charged = [str(d) for d in held.get("charged") or []]
    if charged:
        apply_effect(state, {"type": "law_discharge", "deed_ids": charged})


def _ration_hours() -> float:
    """
    How long a prisoner goes between meals: a day, unless the story's hunger
    would reach ``starving`` inside a day, in which case often enough that it
    never does. The flagship's 2 an hour against 85 is a meal a day.
    """
    from engine.game import clock, survival

    rules = survival.load_rules()
    per_hour = float((rules.get("hunger") or {}).get("per_hour", 2.0))
    starving = float(survival._thresholds(rules).get("starving", 85.0))
    if per_hour <= 0 or per_hour * clock.HOURS_PER_DAY < starving:
        return clock.HOURS_PER_DAY
    return float(max(1, math.floor((starving - 1.0) / per_hour)))


def _feed(state: GameState) -> None:
    """Gaol rations: the prisoner is fed, through the ``hunger`` effect.

    Unconditional on the story's survival rules: the clock's hunger tick runs
    on defaults even in a story that ships none, so a story with no hunger of
    its own would otherwise still starve a prisoner across a long sentence.
    A prisoner already fed costs nothing.
    """
    from engine.game.effects import apply_effect

    if state.hunger > 0:
        apply_effect(state, {"type": "hunger", "delta": -state.hunger})


def _gaol_name(state: GameState) -> str:
    from engine.game.locations import LOCATIONS

    return str((LOCATIONS.get(state.location_id) or {}).get("name") or "the cells")


def pay_fine(state: GameState) -> dict[str, Any]:
    """
    Buy the way out: the fine through the ``gold`` effect, the charge
    discharged, then ``release``.

    Refused -- nothing paid, still held -- when not held or short of the coin.
    The intent is only offered with the gold in hand, so the refusal is for
    every other caller.

    Returns:
        ``{"ok": True, "paid", "gaol"}`` or ``{"ok": False, "message"}``.
    """
    from engine.game.effects import apply_effect
    from engine.game.trade import currency_label

    held = custody(state)
    if not held:
        return {"ok": False, "message": "you are not being held"}
    fine = int(held.get("fine") or 0)
    if state.stats.gold < fine:
        return {"ok": False, "message": f"the fine is {currency_label(fine)} and you do not have it"}
    gaol = _gaol_name(state)
    if fine:
        apply_effect(state, {"type": "gold", "delta": -fine})
    _discharge(state, held)
    apply_effect(state, {"type": "release"})
    return {"ok": True, "paid": fine, "gaol": gaol}


def serve_sentence(state: GameState) -> dict[str, Any]:
    """
    Wait the way out: the charge discharged, then ``days x 24`` hours through
    ``clock.advance_time`` meal by meal, then ``release``.

    Always possible while held -- a sentence always ends (HUE & CRY §2), so a
    player with no coin is never trapped. A SENTENCE NEVER KILLS: the time
    passes in meal-sized steps (``_ration_hours``, a day for the flagship)
    with the prisoner fed before each, because one advance of fifteen days
    starved the prisoner to death in the cells -- measured, hp 20 to -28 and
    a respawn. Everything else -- the doom clock, rumour, cooling -- runs
    through the stretch exactly as through any other.

    Discharged FIRST, so the rumour that runs while the prisoner waits cannot
    carry a served deed anywhere. Should the prisoner leave custody some other
    way mid-sentence (a death's respawn ends custody), the rest is not served
    and the receipt says ``served_out: False`` (the charge is closed either way:
    it was discharged before the first hour).

    Returns:
        ``{"ok": True, "days", "gaol", "served_out"}`` or ``{"ok": False, "message"}``.
    """
    from engine.game import clock
    from engine.game.effects import apply_effect

    held = custody(state)
    if not held:
        return {"ok": False, "message": "you are not being held"}
    days = int(held.get("days") or 0)
    gaol = _gaol_name(state)
    _discharge(state, held)
    remaining = float(days * clock.HOURS_PER_DAY)
    meal = _ration_hours()
    while remaining > 0 and in_custody(state):
        step = min(meal, remaining)
        _feed(state)
        clock.advance_time(state, step)
        remaining -= step
    if not in_custody(state):
        return {"ok": True, "days": days, "gaol": gaol, "served_out": False}
    _feed(state)
    apply_effect(state, {"type": "release"})
    return {"ok": True, "days": days, "gaol": gaol, "served_out": True}


def _register() -> None:
    """Extend the shared condition grammar (listed in ``quests._GRAMMAR_MODULES``)."""
    from engine.game.quests import register_predicate

    register_predicate("in_custody", _p_in_custody)


_register()


__all__ = [
    "DEFAULT_SPREAD_PER_HOUR",
    "MAX_PROPAGATION_HOURS",
    "SELF_GUISE",
    "DEFAULT_CLARITY_WORDS",
    "band_for",
    "best_precision",
    "cap_cooling",
    "charged_deeds",
    "charged_severity",
    "clarity",
    "clarity_word",
    "cooling_of",
    "DARK_HOURS",
    "change_guise",
    "commit_deed",
    "cool",
    "current_guise",
    "custody",
    "declared",
    "discharged",
    "filed_score",
    "guise_label",
    "in_custody",
    "jurisdiction_at",
    "jurisdiction_label",
    "jurisdiction_of",
    "links",
    "load_spec",
    "notice_chance",
    "patrol",
    "pay_fine",
    "propagate",
    "recognition",
    "same_person",
    "sentence_for",
    "serve_sentence",
    "wanted_band",
    "wanted_score",
]

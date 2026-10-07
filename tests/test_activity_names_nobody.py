"""
No activity text a person can be shown with names that person (v0.21.0 T3
fix round 1, Risk 6).

WHY. ``GET /api/people`` shows a STRANGER's activity -- an unmet person's
row carries ``known: false``, no name and no portrait, but their activity
and role. NEON CITY's Frankie, asleep upstairs at Club Noir, read "gone up to
wherever Frankie goes", so the strip named a man the player had never met.

WHAT IS SCANNED. Every story's ``paths.npc_schedules``: each person's own
routine activities and the ``role_defaults`` pool their role draws from,
against that person; the shared texts (``defaults``' activities,
``event_activities`` and the ``default`` role pool) against everyone, since
any person can be shown with them. A person's identifying tokens are their
id (and its bare form, ``npc_`` dropped) and every word of their name -- the
schedule's ``name``, else the story's procgen ``canon_npcs`` name --
matched as whole words, case-insensitive, minus ``STOP_WORDS`` (articles,
abbreviated ranks), honorifics (``TITLES``) and any word their role already
says (the strip shows the role to a stranger). No length floor (fix round 2:
a four-letter one let NEON CITY's "nobody saw Rho leave" through).

GENERATED HOUSEHOLDS (``paths.premises``) have no authored names: each draws
one from ``names.yaml``'s pools, and every member of a type shares the
type's routine, so no routine activity may say any drawable name word.

THE ALLOWLIST is HUE & CRY's shop signs -- a house or a business that bears
a family name is a fact of the street, not an introduction: a stranger can
read the sign over the door -- and one common noun the flagship's tinker is
named for. Each row is ``(slug, npc id, token)`` and says why, and a row that
stops matching fails the test. Spec §4.4's Risk 6 note records the decision.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]

#: Honorifics and ranks: they say what a person is, never who.
TITLES = frozenset({"captain", "sergeant", "lantern", "mother", "sister", "lady", "steward", "the"})

#: (story slug, npc id, token) -> why a stranger may read it.
ALLOWED: dict[tuple[str, str, str], str] = {
    ("hue-and-cry", "npc_pell_hollis", "hollis"):
        "'Hollis's Sundries and Curiosities' is the shop's painted sign; the fence trades behind it under her own name.",
    ("hue-and-cry", "npc_imelda", "vessaline"):
        "'Vessaline House' is the noble house's name, carved over the door and known to every porter in Tallowmere.",
    ("hue-and-cry", "npc_tobiah", "marsh"):
        "'Marsh & Daughters' is the chandlery's sign; a workshop is named for its family by trade custom.",
    ("clockwork-dark", "npc_ilya", "pins"):
        "Not a sign but a common noun: 'Ilya of the Nine Pins' is named for her wares, and 'a tray of ward pins' is the wares, not the name.",
}


def _stories() -> Iterator[tuple[str, dict[str, Any], dict[str, str]]]:
    for manifest in sorted(REPO.glob("games/*/game.yaml")):
        paths = (yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}).get("paths") or {}
        rel = str(paths.get("npc_schedules") or "")
        if not rel:
            continue
        data = yaml.safe_load((REPO / rel).read_text(encoding="utf-8")) or {}
        canon: dict[str, str] = {}
        templates = str(paths.get("procgen_templates") or "")
        if templates and (REPO / templates).is_file():
            for row in (yaml.safe_load((REPO / templates).read_text(encoding="utf-8")) or {}).get("canon_npcs") or []:
                if isinstance(row, dict) and row.get("id"):
                    canon[str(row["id"])] = str(row.get("name") or "")
        yield manifest.parent.name, data, canon


STORIES = list(_stories())


#: Words of a name that say nothing about who: articles, joining words and
#: abbreviated ranks. An explicit list, not a length floor (fix round 2: a
#: four-letter floor let "nobody saw Rho leave" through).
STOP_WORDS = frozenset({"a", "an", "of", "and", "dr", "lt", "cpl", "mr", "mrs", "ms", "st"})


def identifying_tokens(npc_id: str, name: str, role: str) -> set[str]:
    """The words that would identify this person, lower-cased."""
    role_words = {w.lower() for w in re.split(r"[^A-Za-z]+", role) if w}
    tokens = {npc_id.lower(), npc_id.lower().removeprefix("npc_")}
    tokens |= {w.lower() for w in re.split(r"[^A-Za-z]+", name) if w}
    return {t for t in tokens if t and t not in STOP_WORDS and t not in TITLES and t not in role_words}


def names_in(text: str, tokens: set[str]) -> list[str]:
    """
    The tokens ``text`` says, as WHOLE words, case-insensitive ("Hollis's"
    and "Frankie's" count; "Magpie" is not Dock Mag).
    """
    lowered = text.lower()
    return sorted(t for t in tokens if re.search(rf"(?<![a-z0-9_]){re.escape(t)}(?![a-z0-9_])", lowered))


def _texts(data: dict[str, Any], row: dict[str, Any]) -> list[str]:
    defaults = data.get("defaults") or {}
    role_defaults = data.get("role_defaults") or {}
    own = [str(s.get("activity") or "") for s in row.get("routine") or [] if isinstance(s, dict)]
    pool = role_defaults.get(str(row.get("role") or "")) or {}
    shared = [str(v) for k, v in defaults.items() if "activity" in str(k)]
    shared += [str(v) for v in (data.get("event_activities") or {}).values()]
    for chosen in (pool, role_defaults.get("default") or {}):
        own += [str(a) for side in ("day", "night") for a in chosen.get(side) or []]
    return [t for t in own + shared if t]


def test_every_story_with_a_schedule_is_scanned() -> None:
    assert {slug for slug, _d, _c in STORIES} >= {"clockwork-dark", "hue-and-cry", "neon-city"}


@pytest.mark.parametrize("slug,data,canon", STORIES, ids=[s for s, _d, _c in STORIES])
def test_no_activity_names_its_own_person(slug: str, data: dict[str, Any], canon: dict[str, str]) -> None:
    leaks: list[str] = []
    used: set[tuple[str, str, str]] = set()
    for npc_id, row in (data.get("npcs") or {}).items():
        row = row or {}
        name = str(row.get("name") or canon.get(str(npc_id)) or "")
        tokens = identifying_tokens(str(npc_id), name, str(row.get("role") or ""))
        for text in _texts(data, row):
            for token in names_in(text, tokens):
                key = (slug, str(npc_id), token)
                if key in ALLOWED:
                    used.add(key)
                else:
                    leaks.append(f"{npc_id} {token!r}: {text}")
    assert not leaks, f"{slug}: an activity names its own person:\n" + "\n".join(leaks)
    stale = {k for k in ALLOWED if k[0] == slug} - used
    assert not stale, f"allowlist rows that no longer match anything: {sorted(stale)}"


@pytest.mark.parametrize("slug,data,canon", STORIES, ids=[s for s, _d, _c in STORIES])
def test_no_name_word_is_shorter_than_three_letters(slug: str, data: dict[str, Any], canon: dict[str, str]) -> None:
    """
    THE TWO-LETTER DECISION. Every name word of three letters or more is
    scanned ("Rho", "Mag", "Ivo"); a one- or two-letter word ("Jo", "Ed")
    is scanned too, but no shipped story has one -- the only short words in
    any name are abbreviated ranks ("Dr.", "Lt."), which ``STOP_WORDS``
    drops. A new one fails HERE so its author decides it (an allowlist row,
    or a longer name) rather than letting a whole-word match on "ed" or "jo"
    stand unexamined.
    """
    short = []
    for npc_id, row in (data.get("npcs") or {}).items():
        row = row or {}
        name = str(row.get("name") or canon.get(str(npc_id)) or "")
        short += [f"{npc_id}: {t!r}" for t in identifying_tokens(str(npc_id), name, str(row.get("role") or "")) if len(t) < 3]
    assert not short, f"{slug}: a name word under three letters needs a decision: {short}"


def _household_scans() -> Iterator[tuple[str, list[str], set[str]]]:
    for manifest in sorted(REPO.glob("games/*/game.yaml")):
        paths = (yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}).get("paths") or {}
        rel = str(paths.get("premises") or "")
        if not rel:
            continue
        root = REPO / rel
        pools = (yaml.safe_load((root / "names.yaml").read_text(encoding="utf-8")) or {}).get("pools") or {}
        words = {
            w.lower()
            for key in ("given", "surname")
            for drawn in pools.get(key) or []
            for w in re.split(r"[^A-Za-z]+", str(drawn))
            if w and w.lower() not in STOP_WORDS
        }
        texts = []
        for path in sorted(root.rglob("*.yaml")):
            for member in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("household") or []:
                texts += [str(s.get("activity") or "") for s in member.get("routine") or [] if isinstance(s, dict)]
        yield manifest.parent.name, [t for t in texts if t], words


HOUSEHOLDS = list(_household_scans())


@pytest.mark.parametrize("slug,texts,words", HOUSEHOLDS, ids=[s for s, _t, _w in HOUSEHOLDS])
def test_no_household_activity_says_a_drawable_name(slug: str, texts: list[str], words: set[str]) -> None:
    """
    Generated household people (``paths.premises``) are drawn a given name
    and a surname from ``names.yaml``'s pools, and every member of a type
    shares its authored routine. So a routine activity that says ANY word of
    any drawable name could name whoever draws it (a "Sconce" polishing "the
    sconce"): none may.
    """
    assert texts and words, slug
    leaks = [f"{names_in(text, words)}: {text}" for text in texts if names_in(text, words)]
    assert not leaks, f"{slug}: a household activity says a drawable name:\n" + "\n".join(leaks)


def test_the_scan_catches_the_frankie_and_rho_lines() -> None:
    """The guard's own canaries: the lines this file was written for."""
    frankie = identifying_tokens("frankie", "Frankie DeLuca", "vendor")
    assert names_in("gone up to wherever Frankie goes", frankie) == ["frankie"]
    rho = identifying_tokens("rho", "Rho", "vendor")
    assert names_in("not here; nobody saw Rho leave and nobody ever has", rho) == ["rho"]
    # And a title, a stop word or a role word alone is not a name; nor is a
    # name inside another word ("Mag" in "Magpie").
    assert identifying_tokens("npc_ardane", "Captain Ardane", "captain") == {"npc_ardane", "ardane"}
    assert identifying_tokens("ivo_dane", "Cpl. Ivo Dane", "gate corporal") == {"ivo_dane", "ivo", "dane"}
    assert names_in("the Magpie's spree", identifying_tokens("npc_dock_mag", "Dock Mag", "porter_boss")) == []

"""
Clues
=====

A masked role's trail, hidden in the city's houses (HUE & CRY spec §3): the
seed lays it at world generation, and casing and burglary are how a thief
reads it -- so the jobs are also the investigation.

``clues.yaml`` sits inside ``paths.premises`` (found by fixed filename, like
``names.yaml``; a story whose premises directory has none pays nothing)::

    role: magpie          # an agendas role (paths.agendas) with >= 2 candidates
    evidence: evidence    # a veiled, bounded meter the story's state declares
    trail: 4              # clues pointing at the seed's chosen candidate
    herrings: 2           # clues pointing at EACH other candidate
    fresh_flag: clue_fresh  # optional (v0.16 T7): set by every clue carried out
    clues:
      - {id: wick_ends, points_to: npc_wren, text: "a twist of cheap lamp-wick ends ..."}

WHERE IT LIES. ``place`` runs once, inside ``premises.generate``, after every
PREMISES draw and on its own ``CLUES`` stream, so adding a trail moves no
house. The role's candidate is READ (``agendas.role_for_seed`` -- the same
derivation ``agendas.role`` makes on every read), never drawn. It samples
``trail`` of that candidate's rows and ``herrings`` of each other
candidate's, and as many GENERATED premises (an anchor is hand-written, and
may be a candidate's own home: a clue there would be proof, not a trail),
and writes each premise's ``clue`` -- the row id, or "" -- onto the premise.
Every premise of a story with clues carries the key; a story without them
never gains it, so its city is byte-identical.

HOW IT IS FOUND. Casing reveals a house's clue last of everything it has to
give, as ``something here doesn't belong`` (``premises.CLUE_HINT``). The
score takes it cased or not -- the thief is standing in the room -- and the
narrator hears its text then (``in_house``); a job CARRIED OUT keeps it
(``take``): the flag ``clue_found:<id>``, a ``clue`` ledger fact, and the
``evidence`` meter one higher, all through ``apply_effect`` -- and, when the
file names a ``fresh_flag``, that flag set true, so content that clears it
can later ask whether a clue has been found since. Caught, aborted or hurt,
the thief keeps nothing, as with a house's secret.

WHAT IS NEVER SAID. A row's ``points_to`` is read by ``tally`` and the
``clues_favour`` predicate only -- a CONDITION, never rendered into any
prompt (``tests/test_premises_clues.py``). The narrator hears a clue's
``text`` only once it is found, and the loader refuses a text that names any
candidate by name or alias: a clue describes, it never accuses, and a true
clue and a red herring are the same sentence.

Every content fault is a ValueError naming the file.

Version: v0.1.1 [2026-09-27]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine import yamlio
from engine.game.state import GameState
from engine.memory.ledger import MAX_FACT_CHARS

logger = logging.getLogger(__name__)

#: The fixed filename inside ``paths.premises``.
FILENAME = "clues.yaml"
#: The flag a clue carried out of a house sets, ``clue_found:<id>``. Written
#: only by ``take`` (through the ``flag`` effect); read by ``found``.
CLUE_FOUND_PREFIX = "clue_found:"
#: How much one clue raises the evidence meter.
EVIDENCE_PER_CLUE = 1

# The parsed, validated file. Registered in engine/games/caches.py: a story
# swap that kept it warm would lay one city's trail through another's houses.
_SPEC_CACHE: Optional[dict[str, Any]] = None


def _path() -> Optional[Path]:
    from engine.world import premises

    root = premises._premises_dir()  # noqa: SLF001 -- the one definition of the directory
    if root is None:
        return None
    path = root / FILENAME
    return path if path.is_file() else None


def declared() -> bool:
    """Whether the running story lays a trail at all. Read through the cached
    ``spec``: casing asks this of every house on every prompt build."""
    return bool(spec())


def _fail(path: Path, message: str) -> ValueError:
    return ValueError(f"clues: {path.name} ({path}): {message}")


def _count(path: Path, doc: dict[str, Any], key: str, minimum: int) -> int:
    raw = doc.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum:
        raise _fail(path, f"`{key}` must be an integer >= {minimum}")
    return raw


def _check_evidence(path: Path, name: Any) -> str:
    """The meter a found clue raises: declared, a meter, veiled and bounded."""
    from engine.state.active import active_schema

    name = str(name or "").strip()
    spec = active_schema().get(name) if name else None
    if spec is None or spec.kind != "meter":
        raise _fail(path, f"`evidence` `{name}` is not a meter the story's state declares")
    if spec.visibility != "veiled":
        # Public is a count to optimise; hidden is a trail the prose never
        # feels growing. Veiled is the band word the narrator and sheet share.
        raise _fail(path, f"`evidence` meter `{name}` must be `visibility: veiled`")
    if spec.minimum is None or spec.maximum is None:
        # A veiled band needs both bounds to place the number on a scale.
        raise _fail(path, f"`evidence` meter `{name}` needs a `min` and a `max`")
    return name


def _parse(path: Path) -> dict[str, Any]:
    """Read and validate one clues file. Needs the story's agendas and state."""
    from engine.world import agendas, premises

    try:
        doc = yamlio.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _fail(path, f"cannot be read: {exc}") from None
    if not isinstance(doc, dict):
        raise _fail(path, "must be a mapping")

    role = str(doc.get("role") or "").strip()
    # The ROLE is content, read from the agendas file even while a harness
    # switches the agendas' moves off (scripts/simulate_law.py's
    # `agendas_off` patches `agendas.declared`): who the Magpie is does not
    # depend on whether the Magpie is robbing this week. A story with no
    # agendas file has no roles, and is refused here.
    roles = agendas.spec().get("roles") or {}
    if role not in roles:
        raise _fail(path, f"`role` `{role}` is not a role the story's agendas "
                          "(`paths.agendas`) declare")
    candidates = list(roles[role]["from"])
    if len(candidates) < 2:
        raise _fail(path, f"role `{role}` has one candidate: a trail with no red "
                          "herring is a signpost")
    evidence = _check_evidence(path, doc.get("evidence"))
    trail = _count(path, doc, "trail", 1)
    herrings = _count(path, doc, "herrings", 0)

    raw = doc.get("clues")
    if not isinstance(raw, list) or not raw:
        raise _fail(path, "`clues` must be a non-empty list of {id, points_to, text}")
    names = agendas._candidate_names(roles)  # noqa: SLF001 -- the mask's own name list
    rows: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            raise _fail(path, f"clues[{idx}] must be a mapping")
        clue_id = str(row.get("id") or "").strip()
        text = str(row.get("text") or "").strip()
        points_to = str(row.get("points_to") or "").strip()
        if not clue_id or not text:
            raise _fail(path, f"clues[{idx}] needs an `id` and a `text`")
        if clue_id in rows:
            raise _fail(path, f"clue `{clue_id}` is written twice")
        if points_to not in candidates:
            raise _fail(path, f"clue `{clue_id}`: `points_to` `{points_to}` is not one of "
                              f"role `{role}`'s candidates {candidates}")
        for name in names:
            # Matched the way the mask and the trace check match
            # (``agendas._pattern``): the proper noun case-sensitive,
            # word-bounded. A clue that names anyone accuses them.
            if agendas._pattern(name).search(text):  # noqa: SLF001
                raise _fail(path, f"clue `{clue_id}` names a role candidate (`{name}`); "
                                  "a clue describes, it never accuses")
        if len(text) > MAX_FACT_CHARS:
            # `take` remembers the clue as a ledger fact, which the ledger
            # clips at this length: a longer text would be remembered cut off.
            raise _fail(path, f"clue `{clue_id}` is {len(text)} characters; a clue is "
                              f"remembered as a ledger fact, clipped at {MAX_FACT_CHARS}")
        rows[clue_id] = {"id": clue_id, "text": text, "points_to": points_to}

    for npc in candidates:
        # Any candidate may be the chosen one in some seed, and any may be a
        # herring in another, so each needs enough rows for the larger draw.
        have = sum(r["points_to"] == npc for r in rows.values())
        need = max(trail, herrings)
        if have < need:
            raise _fail(path, f"candidate `{npc}` has {have} clues; `trail: {trail}` and "
                              f"`herrings: {herrings}` need {need} for every candidate")
    houses = sum(int(d["count"]) for d in premises._load()["districts"].values())  # noqa: SLF001
    laid = trail + herrings * (len(candidates) - 1)
    if laid > houses:
        raise _fail(path, f"the trail lays {laid} clues but the city generates only "
                          f"{houses} houses to hold them")
    return {"role": role, "candidates": candidates, "evidence": evidence,
            "trail": trail, "herrings": herrings, "clues": rows,
            "fresh_flag": _fresh_flag(path, doc.get("fresh_flag"))}


def _fresh_flag(path: Path, raw: Any) -> str:
    """Optional ``fresh_flag``: a flag every clue carried out sets true, for
    content to clear and later ask "a clue found since then?". "" when absent."""
    if raw is None:
        return ""
    name = raw.strip() if isinstance(raw, str) else ""
    if not name or name.startswith(CLUE_FOUND_PREFIX):
        raise _fail(path, "`fresh_flag` must be a flag name, and not a "
                          f"`{CLUE_FOUND_PREFIX}` one (those are the engine's own)")
    return name


def spec() -> dict[str, Any]:
    """The parsed, validated file; empty for a story that lays no trail."""
    global _SPEC_CACHE
    cached = _SPEC_CACHE  # read once: a reset nulls it without a lock
    if cached is not None:
        return cached
    path = _path()
    loaded = _parse(path) if path is not None else {}
    _SPEC_CACHE = loaded
    return loaded


# ---------------------------------------------------------------------------
# Laying the trail (world generation)
# ---------------------------------------------------------------------------


def place(seed: int, prems: list[dict[str, Any]]) -> None:
    """
    Write every premise's ``clue`` for ``seed``: a row id, or "".

    Called by ``premises.generate`` after its last PREMISES draw. Draws only
    on ``stable_rng(seed, CLUES)``, in a fixed order: the chosen candidate's
    rows, each other candidate's in declared order, then the houses. Rows
    and houses are sorted before sampling, so a reorder in the file or the
    district table cannot move a recorded seed's trail. A no-op for a story
    that lays none.
    """
    if not declared():
        return
    from engine.game.rng import CLUES, stable_rng
    from engine.world import agendas

    sp = spec()
    rng = stable_rng(int(seed), CLUES)
    chosen = agendas.role_for_seed(int(seed), sp["role"])

    def rows_for(npc: str) -> list[str]:
        return sorted(cid for cid, r in sp["clues"].items() if r["points_to"] == npc)

    picked = rng.sample(rows_for(chosen), sp["trail"])
    for npc in sp["candidates"]:
        if npc != chosen:
            picked += rng.sample(rows_for(npc), sp["herrings"])
    houses = sorted(str(p["id"]) for p in prems if not p.get("anchor"))
    where = dict(zip(rng.sample(houses, len(picked)), picked))
    for prem in prems:
        prem["clue"] = where.get(str(prem.get("id")), "")
    logger.info("[clues] Laid (operation=place, seed=%s, clues=%s)", seed, len(picked))


# ---------------------------------------------------------------------------
# Reading and finding
# ---------------------------------------------------------------------------


def found_flag(clue_id: str) -> str:
    """The flag that says the thief carried this clue out of a house."""
    return f"{CLUE_FOUND_PREFIX}{clue_id}"


def row_for(prem: dict[str, Any]) -> dict[str, Any]:
    """
    The authored row behind a premise's ``clue``, or ``{}``.

    ``{}`` for a house with no clue, a save from before the trail (no key),
    a story that lays none, or an id the file no longer writes -- a clue the
    engine cannot word is not a clue the thief can find.
    """
    clue_id = str(prem.get("clue") or "")
    if not clue_id or not declared():
        return {}
    row = spec()["clues"].get(clue_id)
    return dict(row) if row else {}


def found(state: GameState) -> list[str]:
    """The ids of every clue carried out so far, in the file's order."""
    if not declared():
        return []
    return [cid for cid in spec()["clues"] if state.flags.get(found_flag(cid))]


def in_house(state: GameState, prem: dict[str, Any]) -> dict[str, Any]:
    """The clue a thief at this house's strongroom would see, unless already
    carried out; ``{}`` otherwise."""
    row = row_for(prem)
    if not row or state.flags.get(found_flag(row["id"])):
        return {}
    return row


def take(state: GameState, prem: dict[str, Any], ledger: Optional[Any] = None) -> dict[str, Any]:
    """
    The thief carries the house's clue out: called by ``jobs.resolve_stage``
    when a job that reached the score is CARRIED OUT, never at the score.

    Three writes (four with a ``fresh_flag``), all through ``apply_effect``
    (AGENTS.md rule 3): the flag
    ``clue_found:<id>``; a ``clue`` ledger fact in the clue's own words (no
    subject: a clue is about nobody the ledger may name); and the story's
    ``evidence`` meter ``EVIDENCE_PER_CLUE`` higher; and the file's
    ``fresh_flag``, if it names one, set true. A ledger-less caller (tests, a
    simulator) still sets the flags and the meter.

    Returns:
        ``{"text", "evidence"}`` -- the clue's words and the meter's band word
        after it -- or ``{}`` when there was nothing to take.
    """
    from engine.game.effects import apply_effect
    from engine.state.active import store_for

    row = in_house(state, prem)
    if not row:
        return {}
    apply_effect(state, {"type": "flag", "flag": found_flag(row["id"])})
    house = str(prem.get("name") or "a house")
    apply_effect(state, {
        "type": "ledger_fact", "kind": "clue",
        # The clue's words FIRST: the ledger clips a fact at MAX_FACT_CHARS,
        # and the loader holds every text inside that, so a long house name
        # is what a clip would cut -- never the clue.
        "text": f"{row['text'][0].upper()}{row['text'][1:]}, found at {house}.",
    }, ledger=ledger)
    name = spec()["evidence"]
    apply_effect(state, {"type": "value", "name": name, "delta": EVIDENCE_PER_CLUE,
                         "why": "a clue carried out of a house"})
    if spec()["fresh_flag"]:
        apply_effect(state, {"type": "flag", "flag": spec()["fresh_flag"], "value": True})
    store = store_for(state)
    meter = store.schema.get(name)
    band = meter.band(store.get(name)) if meter is not None else ""
    logger.info("[clues] Taken (operation=take, premise=%s, found=%s)",
                prem.get("id"), len(found(state)))
    return {"text": row["text"], "evidence": band}


def tally(state: GameState) -> dict[str, int]:
    """Found clues per candidate, every candidate listed. Never rendered."""
    if not declared():
        return {}
    sp = spec()
    counts = {npc: 0 for npc in sp["candidates"]}
    for cid in found(state):
        counts[sp["clues"][cid]["points_to"]] += 1
    return counts


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------


def _p_clues_favour(state: GameState, value: Any, ctx: Any) -> bool:
    """``{clues_favour: {npc, min?: 1, excluding?: [npc, ...]}}`` -- the found
    clues lean toward ``npc``.

    True iff at least ``min`` found clues point at ``npc`` AND strictly more
    than point at any other candidate: a tie favours nobody. ``excluding``
    (v0.16 T7) sets candidates aside -- the lead is counted among the rest,
    and an excluded ``npc`` never leads -- so a suspect already named wrongly
    stops standing in front of the next one. A CONDITION ONLY, like
    ``agenda_role``: no prompt block renders it, so a card may ask whom the
    evidence favours without the narrator learning where a clue points.
    False with no trail, an ``npc`` who is not a candidate, a ``min`` below 1
    or not an int, or an ``excluding`` that is not a list of names.
    """
    if not isinstance(value, dict) or not declared():
        return False
    npc = str(value.get("npc") or "").strip()
    least = value.get("min", 1)
    if isinstance(least, bool) or not isinstance(least, int) or least < 1:
        return False
    aside = value.get("excluding", [])
    if not isinstance(aside, list) or not all(isinstance(n, str) and n for n in aside):
        return False
    counts = tally(state)
    if npc not in counts or npc in aside:
        return False
    mine = counts[npc]
    return mine >= least and all(mine > n for other, n in counts.items()
                                 if other != npc and other not in aside)


def _register() -> None:
    """Extend the shared condition grammar (listed in ``quests._GRAMMAR_MODULES``)."""
    from engine.game.quests import register_predicate

    register_predicate("clues_favour", _p_clues_favour)


_register()


__all__ = [
    "CLUE_FOUND_PREFIX",
    "EVIDENCE_PER_CLUE",
    "FILENAME",
    "declared",
    "found",
    "found_flag",
    "in_house",
    "place",
    "row_for",
    "spec",
    "take",
    "tally",
]

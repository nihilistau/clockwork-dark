"""
Jobs
====

A burglary as a thing held in state: opened on a premise, walked stage by
stage, closed with an outcome.

``paths.jobs`` names ONE YAML file::

    stages:    {approach: {hours: 1}, entry: {hours: 1}, inside: {hours: 1},
                score: {hours: 1}, getaway: {hours: 1}}     # all five, hours each
    tier_band: {1: easy, 2: standard, 3: hard}              # base band per premise tier
    entries:   {door: {skill: stealth, shift: 0, label: "the door"},
                roof: {skill: survival, shift: 1, label: "over the roof", hurts: true}}
    approach:  {skill: stealth, shift: -1}
    inside:    {awake: {skill: stealth, shift: 0}, asleep: {skill: stealth, shift: -2}}
    score:     {skill: craft, shift: 0, draws: {1: 1, 2: 1, 3: 2}}
    getaway:   {skill: stealth, shift: -1}
    features:  {greasy_step: {stage: entry, entries: [door], shift: 1, known_shift: 0}}
    tools:     {lockpicks: {stage: [entry, score], entries: [door], shift: -1}}
    alarm:     {max: 4, bands: [quiet, uneasy, stirring, roused], on_fail: 1,
                on_crit_fail: 2, watch_delay_hours: 2, deed: burglary}
    prep:      {max: 3, per_case: 1, bands: [none, a little, some, plenty]}
    flashbacks: {knew_the_rota: {label: "...", stage: [approach], cost: {prep: 1},
                 requires: {premise_cased: {min: 1}}, effect: {shift: -1}}}
    anchors:   {margraves_treasury: {after: inside, stages: [{id, label, skill,
                band, hours}]}}

THIS MODULE holds the data and the door -- the loader, ``stages_for`` (the
five stages, with an anchored premise's own stages spliced in), ``begin``
(which opens a job through the ``job_open`` effect), and the three condition
predicates flashbacks and guild contracts are written in (``premise_cased``,
``premise_robbed``, ``job``) -- and the walk: ``approaches`` (what the ``job``
verb offers), ``band_for`` (the band and the reasons that moved it),
``resolve_stage`` (the stage's hours through ``advance_time``, THEN a roll on
the ``JOB`` stream), ``legal_flashbacks``/``flashback`` (calling on prep and
history to move the odds, never the clock), ``abort``, and ``tick``, which
``advance_time`` calls so a raised alarm brings the watch on in-game hours
whatever spends them.

EVERY WRITE is an effect (AGENTS.md rule 3): ``job_open`` starts a job,
``job_stage`` records a stage turn, ``job_alarm`` moves the alarm and
``job_close`` ends it, marking the premise robbed when the score was carried
out. Nothing here assigns to ``state.jobs``.

Every content fault is a ValueError naming the file, for the reason
``premises.py`` gives: a feature no premise has, a tool the registry lacks or
a flashback gated on a predicate nobody registered would load, validate and do
nothing -- the inert shape this repo has shipped before.

Version: v0.4.2 [2026-09-25]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
# The parsed, validated file. Registered in engine/games/caches.py: a story swap
# that kept it warm would burgle one city's houses by another's rules.
_SPEC_CACHE: Optional[dict[str, Any]] = None
# Arrest scenes a raised alarm could not open, warned about once each.
# Registered in engine/games/caches.py beside the spec: it is per story.
_WARNED_ARREST: Optional[set[str]] = None

#: The five derived stages, in the order a job walks them. The file must give
#: hours for each and may not add its own: an extra stage belongs to an anchor.
STAGES = ("approach", "entry", "inside", "score", "getaway")
#: How a job can end. ``clean`` and ``noisy`` carried the score out; the rest
#: did not.
OUTCOMES = ("clean", "noisy", "seen", "hurt", "aborted", "caught")
#: The outcomes that mark the premise robbed, so ``burgle`` never offers it again.
CARRIED_OUT = ("clean", "noisy")
#: The one exposure a flashback may carry: a household member becomes a witness.
EXPOSURES = ("household",)
#: What a flashback's ``effect`` may do.
_FLASHBACK_EFFECTS = ("shift", "remove_obstacle")
#: What a flashback's ``cost`` may spend.
_FLASHBACK_COSTS = ("prep", "gold")


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


def _jobs_path() -> Optional[Path]:
    rel = str(get_config().get("paths.jobs", "") or "").strip()
    return (_ROOT / rel) if rel else None


def declared() -> bool:
    """Whether the running story declares jobs at all."""
    return _jobs_path() is not None


def _fail(path: Path, message: str) -> ValueError:
    return ValueError(f"jobs: {path}: {message}")


def _mapping(path: Path, node: Any, where: str) -> dict[str, Any]:
    if node is None:
        return {}
    if not isinstance(node, dict):
        raise _fail(path, f"`{where}` must be a mapping")
    return node


def _int(path: Path, where: str, raw: Any, *, minimum: Optional[int] = None) -> int:
    if isinstance(raw, bool):
        raise _fail(path, f"{where} must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _fail(path, f"{where} must be an integer") from None
    if value != raw and not isinstance(raw, str):
        raise _fail(path, f"{where} must be an integer")
    if minimum is not None and value < minimum:
        raise _fail(path, f"{where} must be at least {minimum}")
    return value


def _hours(path: Path, where: str, raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _fail(path, f"{where} must be a number of hours") from None
    if value < 0:
        raise _fail(path, f"{where} must not be negative")
    return value


def _names(path: Path, where: str, raw: Any) -> list[str]:
    """A name or a list of names, as a list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, list):
        raise _fail(path, f"{where} must be a name or a list of names")
    return [str(v) for v in raw]


def _check_skill(path: Path, where: str, skill: Any, skills: set[str]) -> str:
    skill = str(skill or "")
    if skill not in skills:
        raise _fail(path, f"{where}: unknown skill `{skill}`")
    return skill


def _check_band(path: Path, where: str, band: Any) -> str:
    from engine.game.intents import DIFFICULTY_BANDS

    band = str(band or "")
    if band not in DIFFICULTY_BANDS:
        raise _fail(path, f"{where}: unknown band `{band}`")
    return band


def _roll(path: Path, where: str, raw: Any, skills: set[str]) -> dict[str, Any]:
    """A ``{skill, shift}`` row: one check a stage asks for."""
    body = _mapping(path, raw, where)
    return {
        "skill": _check_skill(path, where, body.get("skill"), skills),
        "shift": _int(path, f"`{where}.shift`", body.get("shift", 0)),
    }


def _load_stages(path: Path, doc: dict[str, Any]) -> dict[str, dict[str, float]]:
    raw = _mapping(path, doc.get("stages"), "stages")
    for name in raw:
        if str(name) not in STAGES:
            raise _fail(path, f"`stages`: `{name}` is not one of {list(STAGES)}")
    missing = [name for name in STAGES if name not in raw]
    if missing:
        raise _fail(path, f"`stages` is missing {missing}")
    return {
        name: {"hours": _hours(path, f"`stages.{name}.hours`",
                               _mapping(path, raw[name], f"stages.{name}").get("hours", 0))}
        for name in STAGES
    }


def _load_tiers(path: Path, key: str, node: Any, tiers: set[int], value: Any) -> dict[int, Any]:
    """A ``tier -> value`` map that must cover every tier a premise can have."""
    out: dict[int, Any] = {}
    for tier, raw in _mapping(path, node, key).items():
        out[_int(path, f"`{key}` tier `{tier}`", tier, minimum=1)] = value(tier, raw)
    uncovered = sorted(tiers - set(out))
    if uncovered:
        raise _fail(path, f"`{key}` has nothing for premise tier(s) {uncovered}")
    return out


def _premise_catalogue(path: Path) -> tuple[set[str], dict[str, dict[str, Any]], set[int]]:
    """Security ids, anchors and tiers the active story's premises can hold."""
    from engine.world import premises

    if not premises.declared():
        # A job opens ON a premise. A jobs file in a story without premises is
        # a whole system that can never be entered.
        raise _fail(path, "jobs open on premises, and this story declares no `paths.premises`")
    catalogue = premises.definitions()
    security: set[str] = set()
    tiers: set[int] = set()
    for spec in catalogue["types"].values():
        security.update(str(s["id"]) for s in spec.get("security") or [])
        tiers.update(int(t) for t, w in (spec.get("tiers") or {}).items() if int(w) > 0)
    for spec in catalogue["anchors"].values():
        security.update(str(s["id"]) for s in spec.get("security") or [])
        tiers.add(int(spec["tier"]))
    return security, catalogue["anchors"], tiers


def _load_features(path: Path, doc: dict[str, Any], security: set[str],
                   entries: dict[str, Any], stage_ids: set[str],
                   anchor_security: dict[str, set[str]]) -> dict[str, dict[str, Any]]:
    """
    ``anchor_security`` maps each anchor stage id to the security ids its own
    anchor declares: only that anchor's premise ever reaches that stage, and
    ``_plan`` walks only the robbed premise's own ``security``.
    """
    out: dict[str, dict[str, Any]] = {}
    for fid, raw in _mapping(path, doc.get("features"), "features").items():
        fid = str(fid)
        if fid not in security:
            # A row no premise can ever carry would load and change nothing.
            raise _fail(path, f"feature `{fid}` is not a security feature any premise declares")
        body = _mapping(path, raw, f"features.{fid}")
        stage = str(body.get("stage") or "")
        # An anchor stage id is a valid target too (checked against the FULL
        # set the caller builds after `_load_anchors`, five derived stages
        # plus every anchor's own) -- a security row on the vault floor is as
        # real a feature as one on the front door.
        if stage not in stage_ids:
            raise _fail(path, f"feature `{fid}`: unknown stage `{stage}`")
        if stage in anchor_security and fid not in anchor_security[stage]:
            # The union check above passes a townhouse's lock on the vault
            # floor; no premise that reaches that floor carries the lock.
            raise _fail(path, f"feature `{fid}`: stage `{stage}` belongs to an anchor "
                              f"whose own `security` does not declare `{fid}`")
        obstacle = body.get("obstacle", False)
        if not isinstance(obstacle, bool):
            raise _fail(path, f"feature `{fid}`: `obstacle` must be true or false")
        if obstacle and stage != "inside":
            # `_ensure_obstacles` queues every obstacle at `inside` whatever
            # its stage, while `_plan` shifts it only at its own: a blocker
            # with no shift. An obstacle only exists at `inside`.
            raise _fail(path, f"feature `{fid}`: `obstacle` only applies at `inside`")
        on = _names(path, f"feature `{fid}` entries", body.get("entries"))
        if on and stage != "entry":
            # The entries filter binds only at the entry; elsewhere it is ignored.
            raise _fail(path, f"feature `{fid}`: `entries` only applies at `entry`")
        for entry in on:
            if entry not in entries:
                raise _fail(path, f"feature `{fid}`: unknown entry `{entry}`")
        out[fid] = {
            "stage": stage,
            "entries": on,
            "shift": _int(path, f"feature `{fid}` shift", body.get("shift", 0)),
            "known_shift": _int(path, f"feature `{fid}` known_shift", body.get("known_shift", 0)),
            "obstacle": obstacle,
        }
    return out


def _load_tools(path: Path, doc: dict[str, Any],
                entries: dict[str, Any], stage_ids: set[str]) -> dict[str, dict[str, Any]]:
    from engine.game.inventory import load_items

    items = load_items()
    out: dict[str, dict[str, Any]] = {}
    for tid, raw in _mapping(path, doc.get("tools"), "tools").items():
        tid = str(tid)
        if tid not in items:
            raise _fail(path, f"tool `{tid}` is not in the item registry")
        body = _mapping(path, raw, f"tools.{tid}")
        stages = _names(path, f"tool `{tid}` stage", body.get("stage"))
        if not stages:
            raise _fail(path, f"tool `{tid}` names no stage")
        for stage in stages:
            # Same widened set as features: a tool may name an anchor's own
            # stage id, not only the five derived ones.
            if stage not in stage_ids:
                raise _fail(path, f"tool `{tid}`: unknown stage `{stage}`")
        on = _names(path, f"tool `{tid}` entries", body.get("entries"))
        if on and "entry" not in stages:
            # The entries filter binds only at the entry; elsewhere it is ignored.
            raise _fail(path, f"tool `{tid}`: `entries` only applies at `entry`, "
                              "which its `stage` does not name")
        for entry in on:
            if entry not in entries:
                raise _fail(path, f"tool `{tid}`: unknown entry `{entry}`")
        out[tid] = {
            "stage": stages,
            "entries": on,
            "shift": _int(path, f"tool `{tid}` shift", body.get("shift", 0)),
            "consumed": bool(body.get("consumed", False)),
        }
    return out


def _load_meter(path: Path, doc: dict[str, Any], key: str, extra_band: int) -> dict[str, Any]:
    """
    A bounded meter with one band word per level.

    ``alarm`` names the levels BELOW its max (reaching max is "raised", said by
    the engine), so it has ``max`` bands; ``prep`` names every level from 0 to
    max, so it has ``max + 1``.
    """
    body = _mapping(path, doc.get(key), key)
    maximum = _int(path, f"`{key}.max`", body.get("max"), minimum=1)
    bands = body.get("bands")
    want = maximum + extra_band
    if not isinstance(bands, list) or len(bands) != want:
        raise _fail(path, f"`{key}.bands` must list {want} words for max {maximum}")
    return {"max": maximum, "bands": [str(b) for b in bands], "body": body}


def _predicate_names(path: Path, where: str, node: Any) -> list[str]:
    """Every predicate name a condition tree uses, walked the way the grammar walks it."""
    from engine.game import quests

    if node is None:
        return []
    if isinstance(node, list):
        return [name for entry in node for name in _predicate_names(path, where, entry)]
    if not isinstance(node, dict):
        raise _fail(path, f"{where} must be a condition mapping or list")
    groups = [key for key in node if key in quests._GROUP_KEYS]
    siblings = [key for key in node
                if key not in quests._GROUP_KEYS and key not in quests._ANNOTATION_KEYS]
    if groups and siblings:
        # The grammar evaluates a mapping holding a combinator as ONLY its
        # combinators: a sibling predicate beside `all` is silently ignored at
        # runtime, which is a gate that loads, validates and gates nothing.
        raise _fail(path, f"{where} mixes {groups} with sibling predicate(s) {siblings}; "
                          "put them inside the group")
    found: list[str] = []
    for key, value in node.items():
        # The grammar's own keyword lists, read rather than copied, so a
        # combinator added there is understood here the same day.
        if key in quests._GROUP_KEYS:
            found.extend(_predicate_names(path, where, value))
        elif key not in quests._ANNOTATION_KEYS:
            found.append(str(key))
    return found


def _load_flashbacks(path: Path, doc: dict[str, Any],
                     stage_ids: set[str]) -> dict[str, dict[str, Any]]:
    from engine.game.quests import predicate_names

    grammar = set(predicate_names())
    out: dict[str, dict[str, Any]] = {}
    for kind, raw in _mapping(path, doc.get("flashbacks"), "flashbacks").items():
        kind = str(kind)
        body = _mapping(path, raw, f"flashbacks.{kind}")
        label = str(body.get("label") or "").strip()
        # The label is what the narrator says the player did; an empty one puts
        # the id in the prose or nothing at all.
        if not label:
            raise _fail(path, f"flashback `{kind}` needs a `label`")
        stages = _names(path, f"flashback `{kind}` stage", body.get("stage"))
        if not stages:
            raise _fail(path, f"flashback `{kind}` names no stage")
        for stage in stages:
            if stage not in stage_ids:
                raise _fail(path, f"flashback `{kind}`: unknown stage `{stage}`")
        requires = body.get("requires")
        # Placeholders ({district}, {premise}) sit in VALUES and are substituted
        # when the flashback is offered; only the predicate names are checked
        # here, because an unknown one is unmet forever, silently.
        for name in _predicate_names(path, f"flashback `{kind}` requires", requires):
            if name not in grammar:
                raise _fail(path, f"flashback `{kind}`: unknown predicate `{name}` in `requires`")
        cost_raw = _mapping(path, body.get("cost"), f"flashbacks.{kind}.cost")
        for key in cost_raw:
            if key not in _FLASHBACK_COSTS:
                raise _fail(path, f"flashback `{kind}`: unknown cost `{key}`")
        cost = {
            key: _int(path, f"flashback `{kind}` cost {key}", cost_raw.get(key, 0), minimum=0)
            for key in _FLASHBACK_COSTS
        }
        effect_raw = _mapping(path, body.get("effect"), f"flashbacks.{kind}.effect")
        if not effect_raw:
            raise _fail(path, f"flashback `{kind}` has no `effect`")
        effect: dict[str, int] = {}
        for key, value in effect_raw.items():
            if key not in _FLASHBACK_EFFECTS:
                raise _fail(path, f"flashback `{kind}`: unknown effect `{key}`")
            minimum = 1 if key == "remove_obstacle" else None
            effect[str(key)] = _int(path, f"flashback `{kind}` effect {key}", value,
                                    minimum=minimum)
        if "remove_obstacle" in effect and any(s != "inside" for s in stages):
            # An obstacle only exists at `inside`; offered anywhere else it
            # would write `obstacles` off that stage, and a later `inside`
            # would see the key already present and cross with no roll at
            # all -- the whole stage silently skipped.
            raise _fail(path, f"flashback `{kind}`: `remove_obstacle` only applies at `inside`")
        exposure = body.get("exposure")
        if exposure is not None and str(exposure) not in EXPOSURES:
            raise _fail(path, f"flashback `{kind}`: unknown exposure `{exposure}`")
        out[kind] = {
            "label": label,
            "stage": stages,
            "requires": requires,
            "cost": cost,
            "effect": effect,
            "exposure": str(exposure) if exposure is not None else "",
        }
    return out


def _load_anchors(path: Path, doc: dict[str, Any], anchors: dict[str, Any],
                  skills: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    taken = set(STAGES)
    for anchor_id, raw in _mapping(path, doc.get("anchors"), "anchors").items():
        anchor_id = str(anchor_id)
        if anchor_id not in anchors:
            raise _fail(path, f"anchors: `{anchor_id}` is not an anchored premise")
        body = _mapping(path, raw, f"anchors.{anchor_id}")
        after = str(body.get("after") or "")
        if after not in STAGES:
            raise _fail(path, f"anchor `{anchor_id}`: `after` `{after}` is not a stage")
        rows = body.get("stages") or []
        if not isinstance(rows, list):
            raise _fail(path, f"anchor `{anchor_id}`: `stages` must be a list")
        stages: list[dict[str, Any]] = []
        for row in rows:
            row = _mapping(path, row, f"anchors.{anchor_id}.stages")
            sid = str(row.get("id") or "").strip()
            if not sid:
                raise _fail(path, f"anchor `{anchor_id}`: a stage needs an `id`")
            # One namespace for every stage id: a flashback's `stage` list and
            # a job's `stages` would otherwise not know which one is meant.
            if sid in taken:
                raise _fail(path, f"anchor `{anchor_id}`: stage id `{sid}` is already a stage")
            taken.add(sid)
            label = str(row.get("label") or "").strip()
            if not label:
                raise _fail(path, f"anchor `{anchor_id}`: stage `{sid}` needs a `label`")
            where = f"anchor `{anchor_id}` stage `{sid}`"
            stages.append({
                "id": sid,
                "label": label,
                "skill": _check_skill(path, where, row.get("skill"), skills),
                "band": _check_band(path, where, row.get("band")),
                "hours": _hours(path, f"{where} hours", row.get("hours", 0)),
            })
        out[anchor_id] = {"after": after, "stages": stages}
    return out


def _load_alarm(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
    from engine.world import law

    meter = _load_meter(path, doc, "alarm", 0)
    body = meter.pop("body")
    deed = str(body.get("deed") or "")
    if law.declared():
        # With a watch, the deed a raised alarm files must be one it can file.
        # Without one, nothing is filed and the name is never read.
        if deed not in (law.load_spec().get("deeds") or {}):
            raise _fail(path, f"`alarm.deed` `{deed}` is not a deed the Law declares")
    return {
        **meter,
        "on_fail": _int(path, "`alarm.on_fail`", body.get("on_fail", 1), minimum=0),
        "on_crit_fail": _int(path, "`alarm.on_crit_fail`", body.get("on_crit_fail", 2), minimum=0),
        "watch_delay_hours": _hours(path, "`alarm.watch_delay_hours`",
                                    body.get("watch_delay_hours", 0)),
        "deed": deed,
    }


def _load_prep(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
    meter = _load_meter(path, doc, "prep", 1)
    body = meter.pop("body")
    return {
        **meter,
        "per_case": _int(path, "`prep.per_case`", body.get("per_case", 0), minimum=0),
    }


def spec() -> dict[str, Any]:
    """
    The parsed, validated jobs file. Empty for a story that declares none.

    Raises:
        ValueError: naming the file, for a declared-but-missing file or any
            fault in the contract above.
    """
    global _SPEC_CACHE
    if _SPEC_CACHE is not None:
        return _SPEC_CACHE
    path = _jobs_path()
    if path is None:
        _SPEC_CACHE = {}
        return _SPEC_CACHE
    if not path.is_file():
        # Declared and absent is a broken install: the story promised jobs.
        raise ValueError(f"jobs: declared file {path} does not exist")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise _fail(path, f"is not valid YAML: {exc}") from None
    if not isinstance(doc, dict):
        raise _fail(path, "must be a mapping")

    from engine.game.checks import load_skill_rules

    skills = {str(s) for s in ((load_skill_rules() or {}).get("skills") or {})}
    security, anchors_declared, tiers = _premise_catalogue(path)

    stages = _load_stages(path, doc)
    tier_band = _load_tiers(
        path, "tier_band", doc.get("tier_band"), tiers,
        lambda tier, raw: _check_band(path, f"`tier_band` tier `{tier}`", raw),
    )
    entries_raw = _mapping(path, doc.get("entries"), "entries")
    if not entries_raw:
        raise _fail(path, "`entries` must name at least one way in")
    entries: dict[str, dict[str, Any]] = {}
    for eid, raw in entries_raw.items():
        row = _roll(path, f"entries.{eid}", raw, skills)
        label = str((raw or {}).get("label") or "").strip()
        if not label:
            raise _fail(path, f"entry `{eid}` needs a `label`")
        hurts = (raw or {}).get("hurts", False)
        if not isinstance(hurts, bool):
            raise _fail(path, f"entry `{eid}`: `hurts` must be true or false")
        entries[str(eid)] = {**row, "label": label, "hurts": hurts}

    inside_raw = _mapping(path, doc.get("inside"), "inside")
    score_raw = _mapping(path, doc.get("score"), "score")
    draws = _load_tiers(
        path, "score.draws", score_raw.get("draws"), tiers,
        lambda tier, raw: _int(path, f"`score.draws` tier `{tier}`", raw, minimum=0),
    )
    anchors = _load_anchors(path, doc, anchors_declared, skills)
    stage_ids = set(STAGES) | {s["id"] for a in anchors.values() for s in a["stages"]}
    anchor_security = {
        s["id"]: {str(row["id"]) for row in anchors_declared[aid].get("security") or []}
        for aid, a in anchors.items() for s in a["stages"]
    }

    _SPEC_CACHE = {
        "stages": stages,
        "tier_band": tier_band,
        "entries": entries,
        "approach": _roll(path, "approach", doc.get("approach"), skills),
        "inside": {
            "awake": _roll(path, "inside.awake", inside_raw.get("awake"), skills),
            "asleep": _roll(path, "inside.asleep", inside_raw.get("asleep"), skills),
        },
        "score": {**_roll(path, "score", score_raw, skills), "draws": draws},
        "getaway": _roll(path, "getaway", doc.get("getaway"), skills),
        "features": _load_features(path, doc, security, entries, stage_ids, anchor_security),
        "tools": _load_tools(path, doc, entries, stage_ids),
        "alarm": _load_alarm(path, doc),
        "prep": _load_prep(path, doc),
        "flashbacks": _load_flashbacks(path, doc, stage_ids),
        "anchors": anchors,
    }
    return _SPEC_CACHE


# ---------------------------------------------------------------------------
# Reading a job
# ---------------------------------------------------------------------------


def active(state: GameState) -> Optional[dict[str, Any]]:
    """The open job, or None. Cheap: a story with no jobs reads ``{}``."""
    job = state.jobs.get("active") if isinstance(state.jobs, dict) else None
    return job if isinstance(job, dict) and job else None


def robbed(state: GameState) -> list[str]:
    """Premises a finished job took the score from, oldest first."""
    return [str(p) for p in (state.jobs.get("robbed") or [])]


def emptied(state: GameState, premise_id: str) -> bool:
    """
    Whether an agenda already robbed ``premise_id`` (``state.agendas["hits"]``).

    Such a house can still be burgled -- the thief need not know -- but its
    score finds the strongroom bare (``resolve_stage``). Read from state, so a
    story with no agendas answers False for every house.
    """
    hits = state.agendas.get("hits") if isinstance(state.agendas, dict) else None
    return any(str(hit.get("premise")) == premise_id for hit in hits or [])


def stages_for(state: GameState, premise_id: str) -> list[str]:
    """
    The stage ids a job on this premise walks, in order.

    The five derived stages; for an ANCHORED premise with an ``anchors`` row,
    that anchor's own stages spliced in after its ``after`` stage. Empty for an
    unknown premise or a story without jobs.
    """
    from engine.world import premises

    prem = premises.get(state, premise_id)
    if prem is None or not declared():
        return []
    order = list(STAGES)
    row = spec()["anchors"].get(str(prem.get("type") or "")) if prem.get("anchor") else None
    if row:
        cut = order.index(row["after"]) + 1
        order[cut:cut] = [s["id"] for s in row["stages"]]
    return order


def begin(state: GameState, premise_id: str) -> dict[str, Any]:
    """
    Open a job on a premise in the player's district.

    Refuses -- ``ok: False`` with a ``message`` the narrator is handed, and no
    time spent -- where the story has no jobs, the watch holds the player, a
    job is already open, a scene owns the turn, the house does not exist, is
    in another district, or has already been robbed. Opening costs no hours:
    it is deciding to go; the approach stage spends the time.

    Returns:
        ``{"ok", "job_id", "premise", "name", "stages"}`` on an opened job.
        ``premise`` is the id, for the engine; ``name`` is what the narrator
        may say.
    """
    from engine.game import intents
    from engine.game.effects import apply_effect
    from engine.world import law, premises

    if not declared():
        return {"ok": False, "message": "there is no job to be had here"}
    # Read the file at the door, unconditionally: a malformed jobs file must
    # fail HERE, loudly, not halfway through a job the player already opened.
    spec()
    if law.in_custody(state):
        return {"ok": False, "message": "nobody burgles a house from a cell"}
    if active(state) is not None:
        return {"ok": False, "message": "a job is already under way"}
    if intents.scene_owns_turn(state):
        return {"ok": False, "message": "something else has hold of the moment"}
    prem = premises.get(state, premise_id)
    if prem is None:
        return {"ok": False, "message": "there is no such house to burgle"}
    name = str(prem.get("name") or "the house")
    if prem.get("district") != state.location_id:
        return {"ok": False, "name": name, "message": f"{name} is not in this district"}
    if premise_id in robbed(state):
        return {"ok": False, "name": name, "message": f"{name} has already been robbed"}

    stages = stages_for(state, premise_id)
    receipt = apply_effect(state, {"type": "job_open", "premise": premise_id, "stages": stages})
    if not receipt.get("ok"):
        return {"ok": False, "name": name, "message": "the job could not be started"}
    logger.info(
        "[jobs] Opened (operation=begin, job=%s, premise=%s, stages=%s)",
        receipt.get("job_id"),
        premise_id,
        len(stages),
    )
    return {
        "ok": True,
        "job_id": str(receipt.get("job_id") or ""),
        "premise": premise_id,
        "name": name,
        "stages": stages,
    }


# ---------------------------------------------------------------------------
# Walking a job: the stages, the alarm, the watch
# ---------------------------------------------------------------------------

#: The degrees that get through AT A COST (Blades-style): the stage advances,
#: and the alarm rises by ``alarm.on_fail``. On the shipped ladder --
#: crit_success / success / partial / failure -- that is ``partial``. Every
#: other degree below success is a FAILURE: the stage does not advance, the
#: alarm rises by ``alarm.on_crit_fail``, and the thief may be seen or hurt.
_PARTIALS = frozenset({"partial"})
#: The alarm's word once it reaches max: the house is awake and has sent for
#: the watch. Every level below max has the story's own word.
RAISED = "raised"
#: Every stage in the words a player thinks in -- never its id, never a
#: band. ``approaches`` falls back to it for everything but the entry (which
#: always offers named ways in instead, and labels ``inside`` with the
#: obstacle in the way once there is one); ``stage_words`` is the same table
#: for the JOB block and the client payload, where the entry needs its own
#: word too. An anchor stage reads by its own authored ``label`` instead.
_STAGE_LABELS = {
    "approach": "get to the house unseen",
    "entry": "get into the house",
    "inside": "go through the house",
    "score": "go for the strongroom",
    "getaway": "get clear with the take",
}
#: What a banked flashback shift is called in a band's reasons. Task 3's
#: flashbacks bank the shift; the narrator is told something paid off.
_BANKED_REASON = "what you set up beforehand"


def now_hour(state: GameState) -> int:
    """
    The absolute in-game hour: ``world_day * 24 + world_hour``.

    What ``raised_at`` is stamped with and ``tick`` compares against. Built
    from the read-only derived properties, so nothing here writes time.
    """
    return state.world_day * 24 + state.world_hour


def current_stage(state: GameState) -> Optional[str]:
    """The stage id the open job is at, or None with no job open."""
    job = active(state)
    if job is None:
        return None
    stages = list(job.get("stages") or [])
    at = int(job.get("at") or 0)
    return str(stages[at]) if 0 <= at < len(stages) else None


def alarm_band(state: GameState) -> str:
    """The open job's alarm as a word ("" with no job open). Never a number."""
    job = active(state)
    if job is None:
        return ""
    alarm = spec()["alarm"]
    level = int(job.get("alarm") or 0)
    return RAISED if level >= alarm["max"] else alarm["bands"][max(0, level)]


def _premise(state: GameState, job: dict[str, Any]) -> dict[str, Any]:
    from engine.world import premises

    return premises.get(state, str(job.get("premise") or "")) or {}


def _anchor_stage(prem: dict[str, Any], stage: str) -> Optional[dict[str, Any]]:
    """An anchored premise's own stage row, or None for the five."""
    if stage in STAGES or not prem.get("anchor"):
        return None
    row = spec()["anchors"].get(str(prem.get("type") or "")) or {}
    return next((s for s in row.get("stages") or [] if s["id"] == stage), None)


def _stage_hours(prem: dict[str, Any], stage: str) -> float:
    anchor = _anchor_stage(prem, stage)
    if anchor is not None:
        return float(anchor["hours"])
    return float(spec()["stages"].get(stage, {}).get("hours", 0))


def _home(prem: dict[str, Any]) -> str:
    from engine.world.npc_sim import interior_id

    return interior_id(str(prem.get("district") or ""), str(prem.get("id") or ""))


def _at_home(state: GameState, prem: dict[str, Any]) -> list[tuple[str, bool]]:
    """``(npc id, awake)`` for every household member inside the house NOW."""
    from engine.world.npc_sim import resolve_npc

    home = _home(prem)
    found: list[tuple[str, bool]] = []
    for npc_id in prem.get("household") or []:
        here = resolve_npc(state, str(npc_id))
        if here is not None and here.location_id == home:
            found.append((str(npc_id), bool(here.available)))
    return found


def _is_feature(prem: dict[str, Any], obstacle: str) -> bool:
    return obstacle in (prem.get("security") or [])


def _obstacle_label(state: GameState, prem: dict[str, Any], obstacle: str) -> str:
    from engine.world import premises
    from engine.world.npc_sim import display_name

    if _is_feature(prem, obstacle):
        # The premise TYPE'S own authored `text` (test_premises.py's
        # `TOWNHOUSE["security"]`: "a dog in the yard after dark") -- the same
        # source `_plan`'s own reasons read (below), so a feature is named the
        # same way whether it is the obstacle in the way or the reason moving
        # the odds. Never the bare id with underscores swapped for spaces.
        return premises._security_text(prem, obstacle)
    return display_name(obstacle, state)


def stage_words(state: GameState, stage: str) -> str:
    """
    One stage, in the words a player thinks in. "" with no job open.

    An anchored premise's own stage reads by its authored label; the five
    derived stages by ``_STAGE_LABELS``. Never an id, never a band.
    """
    job = active(state)
    if job is None or not stage:
        return ""
    prem = _premise(state, job)
    anchor = _anchor_stage(prem, stage)
    if anchor is not None:
        return anchor["label"]
    return _STAGE_LABELS.get(stage, stage.replace("_", " "))


def stage_labels(state: GameState) -> list[str]:
    """Every stage of the open job, in order, in words. Empty with none open."""
    job = active(state)
    if job is None:
        return []
    return [stage_words(state, s) for s in job.get("stages") or []]


def current_obstacle_label(state: GameState) -> str:
    """
    The obstacle in the way at ``inside`` right now, in words.

    "" outside the ``inside`` stage, with none open, or once the obstacles
    already read are exhausted -- there is nothing left in the way to say.
    """
    job = active(state)
    stage = current_stage(state)
    if job is None or stage != "inside":
        return ""
    obstacles = list(job.get("obstacles") or [])
    if not obstacles:
        return ""
    return _obstacle_label(state, _premise(state, job), obstacles[0])


def flashback_label_this_turn(state: GameState) -> str:
    """
    The label of the flashback called on THIS TURN, at the open job. "" once
    the turn has moved on, or with none called yet.

    Same freshness discipline as the Law's ``last_deed.turn`` (v0.10.0): the
    job keeps its ``last_flashback`` however long the job stays open, and
    only a ``turn`` stamp equal to ``state.turn_number`` says it was called
    just now, not three stages ago.
    """
    job = active(state)
    if job is None:
        return ""
    last = job.get("last_flashback") or {}
    if last.get("turn") != state.turn_number:
        return ""
    return str(last.get("label") or "")


def approaches(state: GameState) -> list[tuple[str, str]]:
    """
    The current stage's approaches, as ``(id, label)``: what ``job`` offers.

    At the entry, the story's ways in, labelled as authored. At every other
    stage its single approach, whose id is the stage's own -- inside, labelled
    with the obstacle in the way once the house has been read; at an anchor
    stage, with the anchor's label. Labels carry names, never ids.
    """
    job = active(state)
    stage = current_stage(state)
    if job is None or stage is None:
        return []
    if stage == "entry":
        return [(eid, row["label"]) for eid, row in spec()["entries"].items()]
    prem = _premise(state, job)
    anchor = _anchor_stage(prem, stage)
    if anchor is not None:
        return [(stage, anchor["label"])]
    if stage == "inside" and job.get("obstacles"):
        return [(stage, f"get past {_obstacle_label(state, prem, job['obstacles'][0])}")]
    return [(stage, _STAGE_LABELS.get(stage, stage.replace("_", " ")))]


def _plan(state: GameState, job: dict[str, Any], stage: str,
          approach: Optional[str]) -> dict[str, Any]:
    """
    The skill, band and reasons for one roll at ``stage``, and the tools used.

    ``approach`` is the entry at the entry and the obstacle inside (default:
    the first one left). The steps are summed and clamped ONCE, so a tool
    that eases a legendary climb is not swallowed by a clamp applied midway.
    """
    from engine.game.checks import shift_band
    from engine.game.inventory import holds, name_of
    from engine.world import premises

    sp = spec()
    prem = _premise(state, job)
    reasons: list[str] = []
    tools: list[str] = []
    steps = 0
    anchor = _anchor_stage(prem, stage)
    obstacle = ""
    if anchor is not None:
        # An authored stage: its own skill and band. Features and tools may
        # still name this stage's own id (below), same as any of the five.
        skill, base = anchor["skill"], anchor["band"]
    else:
        base = sp["tier_band"].get(int(prem.get("tier") or 1), "standard")
        if stage == "entry":
            first = next(iter(sp["entries"].values()))
            row = sp["entries"].get(str(approach or "")) or {"skill": first["skill"], "shift": 0}
        elif stage == "inside":
            left = list(job.get("obstacles") or [])
            obstacle = str(approach if approach and approach != "inside" else (left[0] if left else ""))
            awake = True
            if obstacle and not _is_feature(prem, obstacle):
                awake = dict(_at_home(state, prem)).get(obstacle, False)
            # A feature obstacle (a dog) is awake by nature; a member asleep
            # or out is the easier roll.
            row = sp["inside"]["awake" if awake else "asleep"]
        else:
            row = sp[stage]
        skill = row["skill"]
        steps += int(row["shift"])
    # Features and tools are read for EVERY stage, an anchor's own included --
    # only "entry"/"inside"'s own filters (the entries list, the obstacle
    # gate) ever apply, and an anchor stage id is never either of those, so a
    # row that names it simply shifts the roll like any plain stage shift.
    known = set(premises.known(state, str(prem.get("id") or "")))
    for fid in prem.get("security") or []:
        feature = sp["features"].get(str(fid))
        if feature is None or feature["stage"] != stage:
            continue
        if stage == "entry" and feature["entries"] and approach not in feature["entries"]:
            continue
        # An obstacle feature (a dog) makes only ITS OWN roll harder or
        # easier; the cook asleep upstairs is no easier for knowing it.
        if feature["obstacle"] and obstacle != fid:
            continue
        is_known = f"{premises._SECURITY_PREFIX}{fid}" in known
        delta = feature["known_shift"] if is_known else feature["shift"]
        steps += delta
        # The premise TYPE's own authored `text`, same source as
        # ``_obstacle_label`` -- so a feature reads the same whether the
        # narrator is naming it as the reason moving the odds or as the
        # obstacle in the way. The "cased already"/"not yet cased" suffix
        # keeps the known/unknown framing in words; without it, `text`
        # alone (a full phrase like "a good lock on the street door")
        # would not say which one this reason is.
        text = premises._security_text(prem, fid)
        if is_known and (delta or feature["known_shift"] != feature["shift"]):
            reasons.append(f"{text}, cased already")
        elif not is_known and delta:
            reasons.append(f"{text}, not yet cased")
    for tid, tool in sp["tools"].items():
        if stage not in tool["stage"] or not holds(state, tid):
            continue
        if stage == "entry" and tool["entries"] and approach not in tool["entries"]:
            continue
        steps += tool["shift"]
        tools.append(tid)
        if tool["shift"]:
            reasons.append(name_of(tid))
    banked = int((job.get("shifts") or {}).get(stage, 0) or 0)
    if banked:
        steps += banked
        reasons.append(_BANKED_REASON)
    return {
        "skill": skill,
        "band": shift_band(base, steps),
        "reasons": reasons,
        "consumed": [t for t in tools if sp["tools"][t]["consumed"]],
    }


def band_for(state: GameState, stage: str,
             approach: Optional[str] = None) -> tuple[str, list[str]]:
    """
    The band a roll at ``stage`` would face now, and the human reasons that
    moved it off the stage's own.

    Base: ``tier_band[tier]`` walked by the stage's ``shift`` (an entry's, or
    inside ``awake``/``asleep`` for the obstacle in the way). Then every
    security feature of the premise that applies to this stage and approach
    -- ``known_shift`` if casing found it, else ``shift``; an obstacle
    feature only on its own roll -- then every carried tool that applies (the
    entries filter binds only at the entry), then any flashback shift banked
    for the stage. An anchor stage starts from its authored band. Read-only.

    Returns:
        ``(band, reasons)``; ``("", [])`` with no job open.
    """
    job = active(state)
    if job is None:
        return "", []
    plan = _plan(state, job, stage, approach)
    return plan["band"], plan["reasons"]


def _check(state: GameState, skill: str, band: str) -> Any:
    """One stage roll, on the JOB stream. The seam the tests script."""
    from engine.game.checks import resolve
    from engine.game.rng import JOB, world_rng

    return resolve(state, skill, band, rng=world_rng(state, JOB))


def _draw_loot(state: GameState, prem: dict[str, Any]) -> list[str]:
    """What the score takes: ``draws[tier]`` of the premise's loot, or an anchor's all."""
    from engine.game.rng import JOB, world_rng

    rows = [str(i) for i in prem.get("loot") or []]
    if prem.get("anchor"):
        return rows
    want = min(len(rows), int(spec()["score"]["draws"].get(int(prem.get("tier") or 1), 0)))
    if want <= 0:
        return []
    return world_rng(state, JOB).sample(rows, want)


def _secret_text(state: GameState, prem: dict[str, Any]) -> str:
    """The premise's secret as authored, when casing found that one exists."""
    from engine.world import premises

    secret = str(prem.get("secret") or "")
    if not secret or premises.SECRET_HINT not in premises.known(state, str(prem.get("id"))):
        return ""
    rows = premises.spec(str(prem.get("type") or "")).get("secrets") or []
    return next((str(r.get("text") or "") for r in rows if str(r.get("id")) == secret), "")


def _commit(state: GameState, kind: str, **kwargs: Any) -> list[str]:
    """A Law deed and its witnesses; nothing at all where no Law is declared."""
    from engine.world import law

    if not law.declared() or not kind:
        return []
    return list(law.commit_deed(state, kind, **kwargs).get("witnesses") or [])


def _ensure_obstacles(state: GameState, prem: dict[str, Any],
                      job: dict[str, Any]) -> dict[str, Any]:
    """
    Read the inside stage's obstacles once, lazily, the moment anything at
    ``inside`` needs them -- a roll in ``resolve_stage`` or a
    ``remove_obstacle`` flashback, whichever comes first.

    Whoever is home is in the way (awake or asleep), then every obstacle
    feature. Draws from no stream: the household read is deterministic (the
    world clock, not a die), so calling this from a flashback never shifts a
    later roll beyond what the flashback itself spends. Written through
    ``job_stage``, never assigned directly (rule 3). A no-op once ``obstacles``
    is already on the job.
    """
    from engine.game.effects import apply_effect

    if "obstacles" in job:
        return job
    sp = spec()
    members = [npc for npc, _ in _at_home(state, prem)]
    features = [str(f) for f in prem.get("security") or []
                if sp["features"].get(str(f), {}).get("obstacle")]
    apply_effect(state, {"type": "job_stage", "stage": "inside",
                         "obstacles": members + features})
    return active(state) or job


def _drop_the_absent(state: GameState, prem: dict[str, Any],
                     job: dict[str, Any]) -> dict[str, Any]:
    """
    Take every household member who is no longer at home out of the queue.

    The list is read once (``_ensure_obstacles``), but a stage spends hours
    first, and a guard whose shift ends, or a merchant gone to the counting
    house, is no longer in the way -- nor, gone, can they see the thief.
    Called at each inside roll, after the stage's hours: a member absent NOW
    is dropped (written through ``job_stage``, rule 3); a feature obstacle
    (the dog) never leaves. Draws from no stream. A no-op when nobody left.
    """
    from engine.game.effects import apply_effect

    queue = list(job.get("obstacles") or [])
    home = {npc for npc, _ in _at_home(state, prem)}
    kept = [o for o in queue if _is_feature(prem, o) or o in home]
    if kept == queue:
        return job
    apply_effect(state, {"type": "job_stage", "stage": "inside", "obstacles": kept})
    return active(state) or job


def resolve_stage(state: GameState, approach: str) -> dict[str, Any]:
    """
    Play one turn of the open job's current stage by ``approach``.

    The stage's hours pass FIRST, through ``advance_time`` -- the house moves
    on while the thief works, so the household is read after them, and if the
    watch (``tick``) arrives in those hours the job closes and nothing rolls.
    Then one roll on the JOB stream against ``band_for``; every write is an
    effect.

    Success and ``partial`` ADVANCE: the entry records the way in; inside
    removes the first obstacle and advances once none remain (an empty house
    is crossed without a roll; a household member no longer at home is
    dropped from the queue before the roll, ``_drop_the_absent``, so only
    someone present is rolled against or sees the thief); the score draws
    the loot into the job (not yet the pack) and names the secret if it was
    cased -- or, on a house an agenda already robbed (``emptied``), draws
    nothing and says so (``emptied: True``, on the job and the receipt); the
    getaway carries
    the loot out HOT and closes the job ``clean`` (no alarm) or ``noisy``.
    An anchor stage just advances. A partial pays for it: the alarm rises by
    ``alarm.on_fail`` and the outcome is ``noisy``.

    Any other degree FAILS and does not advance: the alarm rises by
    ``alarm.on_crit_fail``; inside, the member in the way SEES the thief (a
    real witness: ``seen``); at an entry marked ``hurts`` it is a fall (one
    hp: ``hurt``, and the death rules apply); otherwise ``noisy``. The alarm
    reaching max wakes the house: every member at home informs.

    At most ONE Law deed per turn: the alarm's deed when the thief was seen,
    the house shouted, or the take went out onto the street (all of them
    witnesses of that one deed), else ``loitering`` at the approach.

    Returns:
        ``{ok, stage, approach, label, name, band, reasons, degree, outcome,
        alarm_band, witnesses, loot, closed, advanced}`` (+ ``secret`` when
        named, + ``emptied`` at the score and getaway of an emptied house). ``advanced`` says whether the thief got past this stage (or
        this obstacle) -- a ``noisy`` partial did, a ``noisy`` failure did not.
        ``ok`` is "the attempt happened"; ``ok: False`` with a ``message`` is
        the engine declining, and spends nothing.
    """
    from engine.game import encounter
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect
    from engine.game.inventory import name_of, tags_of

    if not declared():
        return {"ok": False, "message": "there is no job under way"}
    sp = spec()
    job = active(state)
    stage = current_stage(state)
    if job is None or stage is None:
        return {"ok": False, "message": "there is no job under way"}
    offered = dict(approaches(state))
    if approach not in offered:
        return {"ok": False, "stage": stage,
                "message": "that is not a way through this part of the job"}
    prem = _premise(state, job)
    job_id = str(job.get("id") or "")
    receipt: dict[str, Any] = {
        "ok": True, "stage": stage, "approach": approach, "label": offered[approach],
        "name": str(prem.get("name") or "the house"), "band": "", "reasons": [],
        "degree": "", "outcome": "clean", "alarm_band": alarm_band(state),
        "witnesses": [], "loot": [], "closed": False, "advanced": False,
    }

    def _closed_meanwhile() -> bool:
        now = active(state)
        return now is None or str(now.get("id") or "") != job_id

    def _finish() -> dict[str, Any]:
        if _closed_meanwhile():
            last = state.jobs.get("last") or {}
            receipt["closed"] = True
            receipt["outcome"] = str(last.get("outcome") or receipt["outcome"])
        else:
            receipt["alarm_band"] = alarm_band(state)
        logger.info(
            "[jobs] Stage (operation=resolve_stage, job=%s, stage=%s, degree=%s, outcome=%s)",
            job_id, stage, receipt["degree"], receipt["outcome"],
        )
        return receipt

    advance_time(state, _stage_hours(prem, stage))
    if _closed_meanwhile():
        # The job ended while the thief worked -- the watch came (``tick``:
        # the alarm was raised, by definition), or the hours took the last
        # hp and the death rules carried the thief off (``hurt``, closed in
        # ``encounter.check_death``). Either way nothing rolls.
        if str((state.jobs.get("last") or {}).get("outcome") or "") != "hurt":
            receipt["alarm_band"] = RAISED
        return _finish()
    job = active(state) or {}

    if stage == "inside":
        job = _ensure_obstacles(state, prem, job)
        job = _drop_the_absent(state, prem, job)
    obstacles = list(job.get("obstacles") or [])
    if stage == "inside" and not obstacles:
        apply_effect(state, {"type": "job_stage", "stage": stage, "approach": approach,
                             "degree": "", "advance": True})
        receipt["advanced"] = True
        return _finish()

    obstacle = obstacles[0] if stage == "inside" else ""
    plan = _plan(state, job, stage, obstacle or approach)
    check = _check(state, plan["skill"], plan["band"])
    receipt.update(band=plan["band"], reasons=plan["reasons"], degree=str(check.degree))
    for tid in plan["consumed"]:
        apply_effect(state, {"type": "remove_item", "item_id": tid})
    degree = str(check.degree)
    # Success advances clean; a partial advances at a cost; anything else
    # fails and the stage waits for another try (or an abort).
    advances = bool(check.success) or degree in _PARTIALS
    failed = not advances
    receipt["advanced"] = advances
    receipt["outcome"] = "clean" if check.success else "noisy"
    step: dict[str, Any] = {"type": "job_stage", "stage": stage, "approach": approach,
                            "degree": degree}
    if advances:
        if stage == "entry":
            step["entry"] = approach
        if stage == "inside":
            step["obstacles"] = obstacles[1:]
            step["advance"] = not obstacles[1:]
        elif stage == "score":
            if emptied(state, str(job.get("premise") or "")):
                # An agenda got here first: nothing to take, and nothing drawn
                # on JOB for it. The score is still DONE -- the take (none)
                # goes out at the getaway and the close records the house
                # robbed, so a contract on it can still be paid.
                taken = []
                step["emptied"] = True
                receipt["emptied"] = True
            else:
                taken = _draw_loot(state, prem)
            step["loot"] = taken
            receipt["loot"] = [name_of(i) for i in taken]
            secret = _secret_text(state, prem)
            if secret:
                receipt["secret"] = secret
            step["advance"] = True
        elif stage != "getaway":
            # The getaway never advances: it closes the job, below.
            step["advance"] = True
    apply_effect(state, step)

    # ONE Law deed per stage turn, however many reasons there are to file:
    # the member who saw the thief (certain) and the house shouting for the
    # watch (informants) are witnesses to the SAME deed, so the watch-house
    # counts it once.
    certain: list[str] = []
    informants: list[str] = []
    if not check.success:
        if (failed and stage == "inside" and obstacle and not _is_feature(prem, obstacle)
                and obstacle in {npc for npc, _ in _at_home(state, prem)}):
            # Only someone actually in the house sees the thief.
            receipt["outcome"] = "seen"
            certain.append(obstacle)
        delta = sp["alarm"]["on_fail" if advances else "on_crit_fail"]
        alarm = apply_effect(state, {"type": "job_alarm", "delta": delta})
        if alarm.get("raised"):
            # The house wakes and shouts for the watch: everyone at home tells.
            informants = [npc for npc, _ in _at_home(state, prem)]

    if advances and stage == "getaway":
        carried = list(job.get("loot") or [])
        for item_id in carried:
            apply_effect(state, {
                "type": "item", "item_id": item_id, "qty": 1,
                "name": name_of(item_id), "tags": tags_of(item_id),
                "stolen_from": {"whom": receipt["name"],
                                "where": str(prem.get("district") or "")},
            })
        receipt["loot"] = [name_of(i) for i in carried]
        if job.get("emptied"):
            receipt["emptied"] = True
        now = active(state) or {}
        receipt["outcome"] = "clean" if int(now.get("alarm") or 0) == 0 else "noisy"

    if certain or informants or (advances and stage == "getaway"):
        # Seen, shouted about, or out on the street with the take.
        kind = sp["alarm"]["deed"]
    elif stage == "approach":
        # A person watching a door at 2am is remembered, never reported on
        # its own -- whether or not the approach went well.
        from engine.world.premises import LOITERING_DEED

        kind = LOITERING_DEED
    else:
        kind = ""
    if kind:
        receipt["witnesses"] += _commit(
            state, kind, margin=check.margin,
            location=_home(prem) if stage == "inside" else None,
            certain=certain, informants=informants,
        )

    if advances and stage == "getaway":
        receipt["alarm_band"] = alarm_band(state)
        apply_effect(state, {"type": "job_close", "outcome": receipt["outcome"]})
    elif failed and stage == "entry" and sp["entries"].get(approach, {}).get("hurts"):
        receipt["outcome"] = "hurt"
        apply_effect(state, {"type": "hp", "delta": -1})
        # The story's death rules, as for an encounter. A death carries the
        # thief off (and spends hours, in which the watch may come first).
        if encounter.check_death(state) is not None and not _closed_meanwhile():
            apply_effect(state, {"type": "job_close", "outcome": "hurt"})
    return _finish()


# ---------------------------------------------------------------------------
# Flashbacks
# ---------------------------------------------------------------------------


def prep_band(state: GameState) -> str:
    """The prep meter as a word ("" with no jobs declared). Never a number."""
    if not declared():
        return ""
    prep = spec()["prep"]
    level = max(0, min(int(prep["max"]), int(state.jobs.get("prep") or 0)))
    return prep["bands"][level]


def _affordable(state: GameState, cost: dict[str, Any]) -> bool:
    prep_have = int(state.jobs.get("prep") or 0)
    if int(cost.get("prep", 0)) > prep_have:
        return False
    if int(cost.get("gold", 0)) > int(state.stats.gold):
        return False
    return True


def _substitute(node: Any, subs: dict[str, str]) -> Any:
    """Fill ``{district}``/``{premise}`` placeholders anywhere in a condition tree."""
    if isinstance(node, str):
        out = node
        for key, value in subs.items():
            out = out.replace("{" + key + "}", value)
        return out
    if isinstance(node, dict):
        return {key: _substitute(value, subs) for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute(value, subs) for value in node]
    return node


def _flashback_subs(job: dict[str, Any]) -> dict[str, str]:
    return {"district": str(job.get("district") or ""), "premise": str(job.get("premise") or "")}


def legal_flashbacks(state: GameState) -> list[str]:
    """
    Flashback kinds offered right now, in the file's own order.

    A kind qualifies when its ``stage`` includes the job's current stage, it
    has not been used already THIS job, its cost is affordable (prep and gold,
    read plainly -- neither is ever spent to find out), and its ``requires``
    -- with ``{district}``/``{premise}`` filled from the open job -- holds
    through the shared condition grammar. Empty with no job open.
    """
    from engine.game.quests import evaluate_condition

    job = active(state)
    stage = current_stage(state)
    if job is None or stage is None:
        return []
    used = set(job.get("used_flashbacks") or [])
    subs = _flashback_subs(job)
    out: list[str] = []
    for kind, row in spec()["flashbacks"].items():
        if kind in used or stage not in row["stage"]:
            continue
        if not _affordable(state, row["cost"]):
            continue
        condition = _substitute(row["requires"], subs)
        if not evaluate_condition(state, condition):
            continue
        out.append(kind)
    return out


def flashback(state: GameState, kind: str) -> dict[str, Any]:
    """
    Call on a flashback at the open job's current stage.

    Spends its ``cost`` through effects (``job_prep``, and ``gold`` where
    named), banks its ``effect`` for THIS stage -- a shift into
    ``active.shifts[stage]``, or the first ``remove_obstacle`` obstacles gone
    from ``inside`` (initialised first, exactly as a roll there would) --
    and marks the kind used for the rest of this job. With
    ``exposure: household`` and the Law declared, one household member of the
    premise is drawn on the JOB stream and becomes a real witness to the
    alarm's deed -- the retroactively bribed servant is a witness now. With no
    Law, exposure writes nothing at all: there is no watch-house for the word
    to reach, and nobody is drawn.

    NEVER calls ``advance_time``: the present stage's odds change and its
    costs are paid now, but no hour passes (rule 2).

    Refuses -- ``ok: False`` with a ``message``, and spends nothing -- for a
    story without jobs, no open job, an unknown kind, or one not currently in
    :func:`legal_flashbacks` (wrong stage, already used, unaffordable, or its
    ``requires`` unmet).

    Returns:
        ``{ok, kind, label, cost, band_before, band_after}``, plus
        ``exposure_witness`` (a display name, never an id) when one was made.
    """
    from engine.game.effects import apply_effect
    from engine.game.rng import JOB, world_rng
    from engine.world import law
    from engine.world.npc_sim import display_name

    if not declared():
        return {"ok": False, "message": "there is nothing to call on here"}
    job = active(state)
    stage = current_stage(state)
    if job is None or stage is None:
        return {"ok": False, "message": "there is no job under way"}
    sp = spec()
    row = sp["flashbacks"].get(kind)
    if row is None:
        return {"ok": False, "message": "that is not something you set up"}
    if kind not in legal_flashbacks(state):
        return {"ok": False, "message": "that is not something you can call on now"}

    prem = _premise(state, job)
    band_before, _ = band_for(state, stage)

    prep_cost = int(row["cost"].get("prep", 0))
    if prep_cost:
        apply_effect(state, {"type": "job_prep", "delta": -prep_cost})
    gold_cost = int(row["cost"].get("gold", 0))
    if gold_cost:
        apply_effect(state, {"type": "gold", "delta": -gold_cost})

    effect = row["effect"]
    if "shift" in effect:
        job = active(state) or job
        shifts = dict(job.get("shifts") or {})
        shifts[stage] = int(shifts.get(stage, 0)) + int(effect["shift"])
        apply_effect(state, {"type": "job_stage", "stage": stage, "shifts": shifts})
    if "remove_obstacle" in effect and stage == "inside":
        # The loader already refuses a `remove_obstacle` flashback offered
        # anywhere but `inside` (and `legal_flashbacks` only offers a kind at
        # a stage it names), so this is a second, cheap belt: `obstacles`
        # NEVER gets written off `inside`, whatever calls this function.
        job = _ensure_obstacles(state, prem, active(state) or job)
        obstacles = list(job.get("obstacles") or [])
        remaining = obstacles[max(0, int(effect["remove_obstacle"])):]
        apply_effect(state, {"type": "job_stage", "stage": stage, "obstacles": remaining})

    job = active(state) or job
    used = list(job.get("used_flashbacks") or [])
    if kind not in used:
        used.append(kind)
    # `last_flashback` is how the narrator says which prep paid off THIS
    # TURN (`flashback_label_this_turn`) -- same stamp-and-compare pattern as
    # the Law's `last_deed.turn`, so it stays truthful past this stage: it is
    # overwritten by the NEXT flashback, never cleared by one that failed to
    # qualify, and read as stale the moment the turn counter moves on.
    apply_effect(state, {
        "type": "job_stage", "stage": stage, "used_flashbacks": used,
        "last_flashback": {"label": row["label"], "turn": state.turn_number},
    })

    exposure_witness = ""
    if row.get("exposure") == "household" and law.declared():
        household = [str(n) for n in prem.get("household") or []]
        if household:
            member = world_rng(state, JOB).choice(household)
            _commit(state, sp["alarm"]["deed"], certain=[member], location=_home(prem))
            exposure_witness = display_name(member, state)

    band_after, _ = band_for(state, stage)
    logger.info(
        "[jobs] Flashback (operation=flashback, job=%s, kind=%s, stage=%s, exposed=%s)",
        job.get("id"), kind, stage, bool(exposure_witness),
    )
    receipt = {
        "ok": True,
        "kind": kind,
        "label": row["label"],
        "cost": dict(row["cost"]),
        "band_before": band_before,
        "band_after": band_after,
    }
    if exposure_witness:
        receipt["exposure_witness"] = exposure_witness
    return receipt


def abort(state: GameState) -> dict[str, Any]:
    """
    Walk away from the open job. No time passes and nothing is carried out:
    loot taken at the score stays in the house.

    Returns:
        ``{ok, outcome: "aborted", closed, name, stage}``, or ``ok: False``
        with a ``message`` when no job is open.
    """
    from engine.game.effects import apply_effect

    job = active(state) if declared() else None
    if job is None:
        return {"ok": False, "message": "there is no job to walk away from"}
    name = str(_premise(state, job).get("name") or "the house")
    stage = current_stage(state)
    apply_effect(state, {"type": "job_close", "outcome": "aborted", "by": "player"})
    logger.info("[jobs] Aborted (operation=abort, job=%s, stage=%s)", job.get("id"), stage)
    return {"ok": True, "outcome": "aborted", "closed": True, "name": name, "stage": stage}


def tick(state: GameState, hours: float) -> None:
    """
    The watch, on in-game hours. Called from ``clock.advance_time``.

    Once the alarm has been raised, and ``alarm.watch_delay_hours`` more
    hours have passed with the job still open, the watch is at the door: the
    job closes ``caught`` and the Law's arrest scene opens through
    ``encounter.begin`` -- the same door the patrol uses. With no Law, or a
    Law with no arrest scene to open, there is nobody to come: the job closes
    ``aborted``, the household awake. An ``arrest.encounter`` naming no
    loaded scene is a content fault, warned about ONCE (the patrol's rule),
    and takes that same path rather than closing ``caught`` with nothing to
    catch the thief. Rolls nothing, so it replays from the hours alone.
    """
    global _WARNED_ARREST
    from engine.game import encounter
    from engine.game.effects import apply_effect
    from engine.world import law

    job = active(state)
    if job is None or job.get("raised_at") is None:
        return
    due = float(job["raised_at"]) + float(spec()["alarm"]["watch_delay_hours"])
    if now_hour(state) < due:
        return
    encounter_id = ""
    if law.declared():
        encounter_id = str((law.load_spec().get("arrest") or {}).get("encounter") or "")
        if encounter_id and encounter.get_definition(encounter_id) is None:
            if _WARNED_ARREST is None:
                _WARNED_ARREST = set()
            if encounter_id not in _WARNED_ARREST:
                _WARNED_ARREST.add(encounter_id)
                logger.warning(
                    "[jobs] arrest.encounter names no loaded encounter "
                    "(operation=tick, id=%s). A raised alarm brings nobody.",
                    encounter_id,
                )
            encounter_id = ""
    if not encounter_id:
        apply_effect(state, {"type": "job_close", "outcome": "aborted"})
        logger.info("[jobs] House roused (operation=tick, job=%s, outcome=aborted)", job.get("id"))
        return
    apply_effect(state, {"type": "job_close", "outcome": "caught"})
    encounter.begin(state, encounter_id)
    logger.info(
        "[jobs] Watch arrived (operation=tick, job=%s, hours=%s, encounter=%s)",
        job.get("id"), hours, encounter_id or "-",
    )


# ---------------------------------------------------------------------------
# Predicates for the shared condition grammar
# ---------------------------------------------------------------------------


def _p_premise_cased(state: GameState, value: Any, ctx: Any) -> bool:
    """``{premise_cased: {min: 2, premise?: id}}`` -- at least that much is known.

    The premise defaults to the open job's, which is what a flashback means by
    "you had watched this house".
    """
    from engine.world import premises

    body = value if isinstance(value, dict) else {"min": value}
    job = active(state)
    premise_id = str(body.get("premise") or (job or {}).get("premise") or "")
    if not premise_id:
        return False
    try:
        minimum = int(body.get("min", 1))
    except (TypeError, ValueError):
        return False
    return len(premises.known(state, premise_id)) >= minimum


def _p_premise_robbed(state: GameState, value: Any, ctx: Any) -> bool:
    """``{premise_robbed: {premise?, type?, district?, owner?}}`` -- a finished job matches.

    Every given filter must hold of the same robbed premise; with none given,
    any robbed premise does. A bare string is a premise id. ``owner`` is
    ``premises.owner`` -- what an agenda's "the player robbed a house the
    guildmaster owns" reaction is written in.
    """
    from engine.world import premises

    body = value if isinstance(value, dict) else {"premise": value}
    for premise_id in robbed(state):
        if body.get("premise") and premise_id != str(body["premise"]):
            continue
        prem = premises.get(state, premise_id) or {}
        if body.get("type") and str(prem.get("type")) != str(body["type"]):
            continue
        if body.get("district") and str(prem.get("district")) != str(body["district"]):
            continue
        if body.get("owner") and premises.owner(state, premise_id) != str(body["owner"]):
            continue
        return True
    return False


def _p_job(state: GameState, value: Any, ctx: Any) -> bool:
    """``{job: {open: true}}`` -- whether a job is under way."""
    want = value.get("open", True) if isinstance(value, dict) else value
    return (active(state) is not None) is bool(want)


def _register() -> None:
    """
    Extend the shared condition grammar.

    At import time, like ``clocks`` and ``threads``, and listed in
    ``quests._GRAMMAR_MODULES`` so a fresh process has these before anything
    evaluates a condition.
    """
    from engine.game.quests import register_predicate

    register_predicate("premise_cased", _p_premise_cased)
    register_predicate("premise_robbed", _p_premise_robbed)
    register_predicate("job", _p_job)


_register()


__all__ = [
    "CARRIED_OUT",
    "OUTCOMES",
    "RAISED",
    "STAGES",
    "abort",
    "active",
    "alarm_band",
    "approaches",
    "band_for",
    "begin",
    "current_obstacle_label",
    "current_stage",
    "declared",
    "flashback",
    "flashback_label_this_turn",
    "legal_flashbacks",
    "now_hour",
    "prep_band",
    "resolve_stage",
    "robbed",
    "spec",
    "stage_labels",
    "stage_words",
    "stages_for",
    "tick",
]

"""
Agendas
=======

What the NPCs are doing while the player is not looking: authored, determin-
istic plans that advance on in-game hours. No model call anywhere -- the
roster's LLM agents are separate and unchanged.

``paths.agendas`` names ONE YAML file::

    roles:                       # hidden identities the SEED chooses
      magpie:
        from: [npc_wren, npc_silas, npc_imelda]   # scheduled NPC ids
        mask:                    # optional; `unmask_when` required when present
          instead: "the Magpie"  # what agenda text calls the chosen NPC until...
          unmask_when: {flag: magpie_unmasked}
          aliases: {npc_wren: ["the lamplighter"]}   # optional, per candidate
    agendas:
      the_magpie:
        owner: {role: magpie}    # or a scheduled npc id
        goal: "steal every shining thing"         # GM-facing only
        clock: magpie_spree      # a clock the story declares, `visibility: hidden`
        moves:
          - id: lift_a_shiny
            every_hours: 24      # cadence, at least 1
            start_hour: 0        # optional: first eligible absolute hour
            at_hours: [1, 2, 3]  # optional: only on these hours of the day
            when: {none: [{flag: magpie_caught}]}    # the shared grammar
            select: {premise: {tier_min: 2, not_robbed: true, loot_tag: shiny}}
            effects: [{type: report, ...}]           # ordinary effects
            advance: 1           # clock delta
            robs: true           # optional: the target premise is robbed
            trace: {text: "...", where: target, public: false}
        reactions:
          - id: the_captain_hears
            on: {reported_to: {npc: npc_ardane, guise: magpie}}   # edge-triggered
            once: true
            effects: []
            advance: 1

Selectors: ``premise {district?, type?, tier_min?, tier_max?, not_robbed?,
loot_tag?, owner?}``, ``fence {district?}`` (a vendor whose profile has
``fence: true``), ``witness {knows: <guise>, jurisdiction?}``.

THIS MODULE holds:

* the loader;
* ``role``: which NPC the seed made the Magpie. It is derived from
  ``stable_rng(state.rng_seed, "agenda:<role>")`` on every read and NEVER
  stored, so it survives a save and cannot be read out of one;
* ``owner_of``;
* the selectors (``candidates``/``select``);
* the three predicates the loader validates gates against: ``wanted``,
  ``reported_to`` and ``agenda_hit``. ``premise_robbed``'s ``owner`` filter
  lives with the rest of that predicate in ``jobs``;
* ``advance``, the per-hour pass that fires moves and then reactions,
  called from ``engine/game/clock.py::advance_time``;
* what the narrator may see: ``signs_here`` (private traces at the player's
  location, rendered by ``prompts.agenda_block`` and recorded seen through
  ``agenda_trace_seen`` after the turn -- ``mark_shown``/``clear_shown``),
  and ``masked_terms``/``mask_text``/``revealed``. THE SECRET IS THE LINK
  between a role and its NPC, not the NPC's name: until ``unmask_when``
  holds, agenda-authored text calls the chosen NPC ``mask.instead``, and
  nothing else in the prompt is touched; once it holds, the GM line says who.
  The loader makes the authored half an invariant: no trace may contain any
  role candidate's display name or declared alias, so only a premise's own
  name in ``{target_name}`` is left for the mask to guard.

REACTIONS are edge-triggered: evaluated at every hour the pass walks, after
that hour's moves, each fires when its ``on`` turns true (``once`` at most
once ever). ``on`` is read with no ledger and no quest progress in scope, so
``disposition``, ``days_in_stage`` and ``days_since_started`` are refused at
load rather than left false forever.

EVERY WRITE is an effect (AGENTS.md rule 3). ``agenda_mark`` is the only
writer of ``state.agendas``'s ``last_hour``, ``moves``, ``fired`` and
``truth``; ``agenda_hit`` of ``hits``; ``agenda_trace`` of ``traces`` and
``trace_seq``; ``agenda_trace_seen`` of a trace's ``seen``. Nothing here
assigns to ``state.agendas``.

Every content fault is a ValueError naming the file, for the reason
``premises.py`` gives: an agenda gated on a predicate nobody registered, or
on a clock the narrator's clock block never reads, would load, validate and
do nothing -- the inert shape this repo has shipped before.

Version: v0.4.1 [2026-09-25]
"""

from __future__ import annotations

import copy
import logging
import math
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
# The parsed, validated file. Registered in engine/games/caches.py: a story swap
# that kept it warm would set one city's thief loose in another's streets.
_SPEC_CACHE: Optional[dict[str, Any]] = None

#: What each selector kind may filter on. A key outside its row is a filter
#: that would be silently ignored at runtime.
SELECTOR_KEYS: dict[str, frozenset[str]] = {
    "premise": frozenset({"district", "type", "tier_min", "tier_max",
                          "not_robbed", "loot_tag", "owner"}),
    "fence": frozenset({"district"}),
    "witness": frozenset({"knows", "jurisdiction"}),
}
#: Where a trace may be left, besides a location id.
TRACE_WHERES = ("target", "owner")
#: Predicates that read the Law, and so need one declared.
LAW_PREDICATES = frozenset({"wanted", "reported_to", "in_custody", "filed"})
#: Predicates that need a StoryLedger in scope. The agendas pass runs inside
#: ``advance_time``, which holds none, so each would be False forever there.
LEDGER_PREDICATES = frozenset({"disposition"})
#: Predicates that need a quest's progress record in scope -- which the pass,
#: evaluating no quest, never has. Each would be False forever there too.
PROGRESS_PREDICATES = frozenset({"days_in_stage", "days_since_started"})
#: Effect kinds only the pass itself may write. An authored move applying one
#: would forge the bookkeeping: stamp a move that never fired, rob a house
#: nobody entered, or leave a sign with no move behind it.
BOOKKEEPING_EFFECTS = frozenset({"agenda_mark", "agenda_hit", "agenda_trace",
                                 "agenda_trace_seen"})
#: Effect kinds that write the Law, and so need one declared. Without it each
#: refuses at runtime -- a move that loads and files nothing.
LAW_EFFECTS = frozenset({
    "witness", "report", "quash_reports", "deed", "law_cool", "law_guise",
    "law_link", "arrest", "release", "law_discharge", "law_last_deed",
})
#: What an authored effect's strings may name, substituted when the move
#: fires. Every ``{target...}`` needs a ``select``; ``{owner}`` is an npc id.
EFFECT_PLACEHOLDERS = frozenset({"target", "target_name", "target_district",
                                 "target_jurisdiction", "owner"})
#: What a trace's text may name. Prose only: an id (``{target}``, ``{owner}``)
#: would print into the narrator's material, and the owner may be a masked role.
TRACE_PLACEHOLDERS = frozenset({"target_name"})
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


def _agendas_path() -> Optional[Path]:
    rel = str(get_config().get("paths.agendas", "") or "").strip()
    return (_ROOT / rel) if rel else None


def declared() -> bool:
    """Whether the running story declares agendas at all."""
    return _agendas_path() is not None


def _fail(path: Path, message: str) -> ValueError:
    return ValueError(f"agendas: {path}: {message}")


def _mapping(path: Path, node: Any, where: str) -> dict[str, Any]:
    if node is None:
        return {}
    if not isinstance(node, dict):
        raise _fail(path, f"`{where}` must be a mapping")
    return node


def _list(path: Path, node: Any, where: str) -> list[Any]:
    if node is None:
        return []
    if not isinstance(node, list):
        raise _fail(path, f"`{where}` must be a list")
    return node


def _int(path: Path, where: str, raw: Any, *, minimum: Optional[int] = None,
         maximum: Optional[int] = None) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise _fail(path, f"{where} must be an integer")
    if minimum is not None and raw < minimum:
        raise _fail(path, f"{where} must be at least {minimum}")
    if maximum is not None and raw > maximum:
        raise _fail(path, f"{where} must be at most {maximum}")
    return raw


def _bool(path: Path, where: str, raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise _fail(path, f"{where} must be true or false")
    return raw


def _scheduled() -> set[str]:
    from engine.world.npc_sim import load_npc_schedules

    return {str(n) for n in (load_npc_schedules().get("npcs") or {})}


def _clauses(path: Path, where: str, node: Any) -> list[tuple[str, Any]]:
    """Every ``(predicate, value)`` a condition tree holds (``quests.condition_clauses``)."""
    from engine.game import quests

    try:
        return quests.condition_clauses(node, where)
    except ValueError as exc:
        raise _fail(path, str(exc)) from None


def _check_condition(path: Path, where: str, node: Any, ctx: dict[str, Any]) -> Any:
    """Validate a gate: known predicates, none needing a ledger or an absent Law."""
    from engine.game.quests import predicate_names

    grammar = set(predicate_names())
    for name, value in _clauses(path, where, node):
        if name not in grammar:
            raise _fail(path, f"{where}: unknown predicate `{name}`")
        if name in LEDGER_PREDICATES:
            raise _fail(path, f"{where}: `{name}` needs a story ledger, and the agendas "
                              "pass has no ledger -- it would never hold")
        if name in PROGRESS_PREDICATES:
            raise _fail(path, f"{where}: `{name}` reads a quest's progress, and the "
                              "agendas pass evaluates no quest -- it would never hold")
        if name in LAW_PREDICATES and not ctx["law"]:
            raise _fail(path, f"{where}: `{name}` reads the Law, and this story "
                              "declares no `paths.law`")
        body = value if isinstance(value, dict) else {}
        if name == "wanted":
            law_spec = ctx["law"]
            if str(body.get("min") or "") not in law_spec["wanted"]["bands"]:
                raise _fail(path, f"{where}: `wanted.min` `{body.get('min')}` is not a "
                                  "wanted band")
            if body.get("guise") and str(body["guise"]) not in law_spec["guises"]:
                raise _fail(path, f"{where}: unknown guise `{body['guise']}`")
            if body.get("jurisdiction") and str(body["jurisdiction"]) not in law_spec[
                "jurisdictions"
            ]:
                raise _fail(path, f"{where}: unknown jurisdiction `{body['jurisdiction']}`")
        elif name == "reported_to":
            npc = str(body.get("npc") or "")
            if npc not in ctx["npcs"]:
                raise _fail(path, f"{where}: `reported_to.npc` `{npc}` is not a scheduled NPC")
            if body.get("guise") and str(body["guise"]) not in ctx["law"]["guises"]:
                raise _fail(path, f"{where}: unknown guise `{body['guise']}`")
        elif name == "filed":
            jurisdiction = str(body.get("jurisdiction") or "")
            if jurisdiction not in ctx["law"]["jurisdictions"]:
                raise _fail(path, f"{where}: `filed.jurisdiction` `{jurisdiction}` is not a "
                                  "jurisdiction")
            if body.get("guise") and str(body["guise"]) not in ctx["law"]["guises"]:
                raise _fail(path, f"{where}: unknown guise `{body['guise']}`")
        elif name == "agenda_hit":
            _check_agenda_hit(path, where, body, ctx)
    return node


def _check_agenda_hit(path: Path, where: str, body: dict[str, Any],
                      ctx: dict[str, Any]) -> None:
    """``agenda_hit {agenda?, premise?, district?}``: each names something real.

    Premises are generated per seed, but their ids are not
    (``premises.possible_ids``), so a premise is checked against every id any
    seed could lay out.
    """
    from engine.game.locations import LOCATIONS
    from engine.world import premises

    if "agenda" in body and str(body["agenda"]) not in ctx["agenda_ids"]:
        raise _fail(path, f"{where}: `agenda_hit.agenda` `{body['agenda']}` is not a "
                          "declared agenda")
    if "premise" in body:
        if not isinstance(body["premise"], str):
            raise _fail(path, f"{where}: `agenda_hit.premise` must be a premise id")
        if body["premise"] not in premises.possible_ids():
            raise _fail(path, f"{where}: `agenda_hit.premise` `{body['premise']}` is no "
                              "premise this story can lay out")
    if "district" in body and str(body["district"]) not in LOCATIONS:
        raise _fail(path, f"{where}: unknown district `{body['district']}`")


def _load_roles(path: Path, doc: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, raw in _mapping(path, doc.get("roles"), "roles").items():
        name = str(name)
        body = _mapping(path, raw, f"roles.{name}")
        members = [str(m) for m in _list(path, body.get("from"), f"roles.{name}.from")]
        if not members:
            raise _fail(path, f"role `{name}` has no candidates in `from`")
        for member in members:
            if member not in ctx["npcs"]:
                raise _fail(path, f"role `{name}`: `{member}` is not a scheduled NPC")
        row: dict[str, Any] = {"from": members, "mask": {}}
        if body.get("mask") is not None:
            mask = _mapping(path, body.get("mask"), f"roles.{name}.mask")
            instead = str(mask.get("instead") or "").strip()
            if not instead:
                # The mask replaces the chosen NPC's name in the narrator's
                # material; an empty one would print nothing where the name was.
                raise _fail(path, f"role `{name}`: `mask.instead` must say something")
            if not mask.get("unmask_when"):
                # A mask with no way to lift would hide the role's NPC from the
                # agenda text forever and never let the GM line say who it is.
                raise _fail(path, f"role `{name}`: `mask` needs an `unmask_when` -- "
                                  "a mask that can never lift")
            row["mask"] = {
                "instead": instead,
                "unmask_when": _check_condition(path, f"role `{name}` unmask_when",
                                                mask.get("unmask_when"), ctx),
                "aliases": _check_aliases(path, name, mask.get("aliases"), members),
            }
        out[name] = row
    return out


def _check_aliases(path: Path, name: str, raw: Any, members: list[str]) -> dict[str, list[str]]:
    """
    ``mask.aliases``: per candidate, the other names agenda text may call them.

    Keyed by candidate, not one flat list: a flat list would mask Silas's
    nickname when the seed chose Wren -- and "Silas the Magpie" points at the
    wrong person as loudly as the right name points at the right one.
    """
    if raw is None:
        return {}
    where = f"role `{name}`: `mask.aliases`"
    if not isinstance(raw, dict):
        raise _fail(path, f"{where} must map candidates to lists of names")
    out: dict[str, list[str]] = {}
    for npc, names in raw.items():
        npc = str(npc)
        if npc not in members:
            raise _fail(path, f"{where}: `{npc}` is not one of the role's candidates")
        if not isinstance(names, list) or not all(
            isinstance(n, str) and n.strip() for n in names
        ):
            raise _fail(path, f"{where} for `{npc}` must be a list of non-empty strings")
        out[npc] = [n.strip() for n in names]
    return out


def _check_owner(path: Path, where: str, raw: Any, roles: dict[str, Any],
                 ctx: dict[str, Any]) -> Any:
    if isinstance(raw, dict):
        role = str(raw.get("role") or "")
        if set(raw) != {"role"} or role not in roles:
            raise _fail(path, f"{where}: `{raw}` names no declared role")
        return {"role": role}
    owner = str(raw or "")
    if owner not in ctx["npcs"]:
        raise _fail(path, f"{where}: `{owner}` is not a scheduled NPC or a role")
    return owner


def _check_clock(path: Path, where: str, clock: Any) -> str:
    from engine.game.clocks import load_clocks
    from engine.state.active import active_schema

    clock = str(clock or "")
    spec = active_schema().get(clock)
    if spec is None or spec.kind != "clock":
        raise _fail(path, f"{where}: `{clock}` is not a clock the story's state declares")
    if clock not in load_clocks():
        # The narrator feels a clock only through its `paths.clocks` row
        # (prompts._clocks_block); a clock missing there fills in silence.
        raise _fail(path, f"{where}: clock `{clock}` has no row in `paths.clocks`")
    if spec.visibility != "hidden":
        # A veiled clock's band crossing is journalled to the prose unwrapped;
        # a public one is a number on the sheet. Either tells the player.
        raise _fail(path, f"{where}: clock `{clock}` must be `visibility: hidden`")
    return clock


def _check_selector(path: Path, where: str, raw: Any, roles: dict[str, Any],
                    ctx: dict[str, Any]) -> dict[str, Any]:
    from engine.game.locations import LOCATIONS

    select = _mapping(path, raw, f"{where}.select")
    if not select:
        return {}
    if len(select) != 1:
        raise _fail(path, f"{where}: `select` names one selector, not {sorted(select)}")
    kind, body_raw = next(iter(select.items()))
    kind = str(kind)
    if kind not in SELECTOR_KEYS:
        raise _fail(path, f"{where}: unknown selector `{kind}`")
    body = _mapping(path, body_raw, f"{where}.select.{kind}")
    for key in body:
        if key not in SELECTOR_KEYS[kind]:
            raise _fail(path, f"{where}: unknown `{kind}` selector key `{key}`")
    if kind == "premise":
        from engine.world import premises

        if not premises.declared():
            raise _fail(path, f"{where}: the `premise` selector needs premises, and this "
                              "story declares no `paths.premises`")
        loaded = premises.definitions()
        if "district" in body and str(body["district"]) not in LOCATIONS:
            raise _fail(path, f"{where}: unknown district `{body['district']}`")
        if "type" in body and str(body["type"]) not in {**loaded["types"], **loaded["anchors"]}:
            raise _fail(path, f"{where}: unknown premise type `{body['type']}`")
        for key in ("tier_min", "tier_max"):
            if key in body:
                _int(path, f"{where}: `{key}`", body[key], minimum=1)
        if "not_robbed" in body:
            _bool(path, f"{where}: `not_robbed`", body["not_robbed"])
        if "loot_tag" in body:
            from engine.game.inventory import load_items, tags_of

            tag = str(body["loot_tag"])
            if not any(tag in tags_of(item) for item in load_items()):
                raise _fail(path, f"{where}: no item carries loot tag `{tag}`")
        if "owner" in body:
            _check_owner(path, f"{where}: `owner`", body["owner"], roles, ctx)
    elif kind == "fence":
        from engine.game import trade

        if not any(bool(v.get("fence")) for v in trade.vendors().values()):
            raise _fail(path, f"{where}: the `fence` selector needs a vendor with "
                              "`fence: true`, and this story has none")
        if "district" in body and str(body["district"]) not in LOCATIONS:
            raise _fail(path, f"{where}: unknown district `{body['district']}`")
    else:  # witness
        law_spec = ctx["law"]
        if not law_spec:
            raise _fail(path, f"{where}: the `witness` selector reads the Law, and this "
                              "story declares no `paths.law`")
        if str(body.get("knows") or "") not in law_spec["guises"]:
            raise _fail(path, f"{where}: `witness.knows` `{body.get('knows')}` is not a guise")
        if "jurisdiction" in body and str(body["jurisdiction"]) not in law_spec[
            "jurisdictions"
        ]:
            raise _fail(path, f"{where}: unknown jurisdiction `{body['jurisdiction']}`")
    return {kind: dict(body)}


def _placeholders(node: Any) -> set[str]:
    """Every ``{name}`` in the string values of a nested effect."""
    if isinstance(node, str):
        return set(_PLACEHOLDER.findall(node))
    if isinstance(node, dict):
        return {name for value in node.values() for name in _placeholders(value)}
    if isinstance(node, list):
        return {name for value in node for name in _placeholders(value)}
    return set()


def _check_placeholders(path: Path, where: str, node: Any, allowed: frozenset[str],
                        has_target: bool) -> None:
    """A placeholder nothing fills would reach the world as literal braces."""
    for name in sorted(_placeholders(node)):
        if name not in allowed:
            raise _fail(path, f"{where}: placeholder `{{{name}}}` is not one of "
                              f"{sorted(allowed)}")
        if name.startswith("target") and not has_target:
            raise _fail(path, f"{where}: placeholder `{{{name}}}` needs a `select` "
                              "to name a target")


def _check_effects(path: Path, where: str, raw: Any, ctx: dict[str, Any],
                   has_target: bool = False) -> list[dict[str, Any]]:
    from engine.game.effects import registered_kinds
    from engine.state.active import active_schema

    kinds = set(registered_kinds())
    out: list[dict[str, Any]] = []
    for effect in _list(path, raw, f"{where}.effects"):
        if not isinstance(effect, dict) or not str(effect.get("type") or "").strip():
            raise _fail(path, f"{where}: every effect is a mapping with a `type`")
        kind = str(effect["type"]).strip().lower()
        if kind in BOOKKEEPING_EFFECTS:
            raise _fail(path, f"{where}: `{kind}` is the agendas pass's own bookkeeping; "
                              "use `robs`, `trace` and the cadence instead")
        if kind in LAW_EFFECTS and not ctx["law"]:
            raise _fail(path, f"{where}: effect `{kind}` writes the Law, and this story "
                              "declares no `paths.law`")
        # An unregistered kind naming a declared value falls through to `value`.
        if kind not in kinds and active_schema().get(kind) is None:
            raise _fail(path, f"{where}: unknown effect type `{effect['type']}`")
        _check_placeholders(path, where, effect, EFFECT_PLACEHOLDERS, has_target)
        out.append(dict(effect))
    return out


def _candidate_names(roles: dict[str, Any]) -> list[str]:
    """
    Every name agenda text could give a role candidate away by: each
    candidate's display name (from the schedule) and every declared alias,
    of every role and every candidate -- not only the seed's chosen one,
    because the file is the same in every seed.
    """
    from engine.world.npc_sim import load_npc_schedules

    table = load_npc_schedules().get("npcs") or {}
    names: set[str] = set()
    for row in roles.values():
        for npc in row["from"]:
            entry = table.get(npc) or {}
            shown = str(entry.get("name") or "").strip() if isinstance(entry, dict) else ""
            if shown:
                names.add(shown)
        for aliases in (row.get("mask") or {}).get("aliases", {}).values():
            names.update(aliases)
    return sorted(names, key=lambda n: (-len(n), n))


def _check_trace(path: Path, where: str, raw: Any, has_target: bool,
                 names: tuple[str, ...] = ()) -> dict[str, Any]:
    from engine.game.locations import LOCATIONS

    if raw is None:
        return {}
    body = _mapping(path, raw, f"{where}.trace")
    text = str(body.get("text") or "").strip()
    if not text:
        raise _fail(path, f"{where}: a trace needs `text`")
    place = str(body.get("where") or "")
    if place not in TRACE_WHERES and place not in LOCATIONS:
        raise _fail(path, f"{where}: trace `where` `{place}` is not {list(TRACE_WHERES)} "
                          "or a location")
    if place == "target" and not has_target:
        raise _fail(path, f"{where}: a trace left at the target needs a `select`")
    _check_placeholders(path, f"{where} trace", text, TRACE_PLACEHOLDERS, has_target)
    for name in names:
        # THE SECRET IS THE LINK, as a schema invariant: a trace naming any
        # candidate either IS the link (the seed chose them) or points at an
        # innocent one the mask does not cover. Matched the way the mask
        # matches (``_pattern``): word-bounded, the proper noun case-sensitive.
        if _pattern(name).search(text):
            raise _fail(path, f"{where}: trace text names a role candidate (`{name}`); "
                              "a sign must be impersonal in every seed")
    return {"text": text, "where": place,
            "public": _bool(path, f"{where}: trace `public`", body.get("public"))}


def _load_move(path: Path, where: str, raw: Any, roles: dict[str, Any],
               ctx: dict[str, Any]) -> dict[str, Any]:
    body = _mapping(path, raw, where)
    select = _check_selector(path, where, body.get("select"), roles, ctx)
    robs = _bool(path, f"{where}: `robs`", body.get("robs"))
    if robs and "premise" not in select:
        raise _fail(path, f"{where}: `robs` needs a `premise` selector to rob")
    at_hours = [_int(path, f"{where}: `at_hours` entry", h, minimum=0, maximum=23)
                for h in _list(path, body.get("at_hours"), f"{where}.at_hours")]
    return {
        "id": str(body.get("id") or ""),
        "every_hours": _int(path, f"{where}: `every_hours`", body.get("every_hours"),
                            minimum=1),
        "start_hour": _int(path, f"{where}: `start_hour`", body.get("start_hour", 0),
                           minimum=0),
        "at_hours": at_hours,
        "when": _check_condition(path, f"{where} when", body.get("when"), ctx),
        "select": select,
        "effects": _check_effects(path, where, body.get("effects"), ctx, bool(select)),
        "advance": _int(path, f"{where}: `advance`", body.get("advance", 0)),
        "robs": robs,
        "trace": _check_trace(path, where, body.get("trace"), bool(select),
                              tuple(ctx.get("candidate_names") or ())),
    }


def _load_reaction(path: Path, where: str, raw: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    body = _mapping(path, raw, where)
    if "on" not in body and True in body:
        # YAML 1.1 reads a bare `on:` key as the boolean true, so the trigger
        # arrives under `True` and the reaction looks as if it has none.
        raise _fail(path, f"{where}: YAML read a bare `on:` key as the boolean true -- "
                          'quote it: `"on":`')
    if body.get("on") in (None, {}, []):
        # An empty trigger is always true: it would fire on the first hour and,
        # being edge-triggered, never again -- a reaction to nothing.
        raise _fail(path, f"{where}: a reaction needs an `on` trigger")
    return {
        "id": str(body.get("id") or ""),
        "on": _check_condition(path, f"{where} on", body.get("on"), ctx),
        "once": _bool(path, f"{where}: `once`", body.get("once")),
        "effects": _check_effects(path, where, body.get("effects"), ctx),
        "advance": _int(path, f"{where}: `advance`", body.get("advance", 0)),
    }


def _load_agendas(path: Path, doc: dict[str, Any], roles: dict[str, Any],
                  ctx: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for agenda_id, raw in _mapping(path, doc.get("agendas"), "agendas").items():
        agenda_id = str(agenda_id)
        body = _mapping(path, raw, f"agendas.{agenda_id}")
        where = f"agenda `{agenda_id}`"
        moves = [_load_move(path, f"{where} move {i}", m, roles, ctx)
                 for i, m in enumerate(_list(path, body.get("moves"), f"{where}.moves"))]
        reactions = [_load_reaction(path, f"{where} reaction {i}", r, ctx)
                     for i, r in enumerate(_list(path, body.get("reactions"),
                                                 f"{where}.reactions"))]
        seen: set[str] = set()
        for row in moves + reactions:
            # One namespace per agenda: `agenda:id` keys the bookkeeping.
            if not row["id"]:
                raise _fail(path, f"{where}: every move and reaction needs an `id`")
            if row["id"] in seen:
                raise _fail(path, f"{where}: id `{row['id']}` is used twice")
            seen.add(row["id"])
        out[agenda_id] = {
            "owner": _check_owner(path, f"{where} owner", body.get("owner"), roles, ctx),
            "goal": str(body.get("goal") or ""),
            "clock": _check_clock(path, where, body.get("clock")),
            "moves": moves,
            "reactions": reactions,
        }
    return out


def spec() -> dict[str, Any]:
    """
    The parsed, validated agendas file. Empty for a story that declares none.

    Raises:
        ValueError: naming the file, for a declared-but-missing file or any
            fault in the contract above.
    """
    global _SPEC_CACHE
    if _SPEC_CACHE is not None:
        return _SPEC_CACHE
    path = _agendas_path()
    if path is None:
        _SPEC_CACHE = {}
        return _SPEC_CACHE
    if not path.is_file():
        raise ValueError(f"agendas: declared file {path} does not exist")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise _fail(path, f"is not valid YAML: {exc}") from None
    if not isinstance(doc, dict):
        raise _fail(path, "must be a mapping")

    from engine.world import law

    ctx = {
        "npcs": _scheduled(),
        "law": law.load_spec() if law.declared() else {},
        # Read before any gate is checked, so `agenda_hit {agenda}` may name an
        # agenda declared further down the file.
        "agenda_ids": {str(k) for k in _mapping(path, doc.get("agendas"), "agendas")},
    }
    roles = _load_roles(path, doc, ctx)
    ctx["candidate_names"] = _candidate_names(roles)
    _SPEC_CACHE = {"roles": roles, "agendas": _load_agendas(path, doc, roles, ctx)}
    return _SPEC_CACHE


def move_keys() -> set[str]:
    """Every ``agenda:move`` key the file declares -- what ``agenda_mark`` may record."""
    return {f"{aid}:{m['id']}" for aid, a in (spec().get("agendas") or {}).items()
            for m in a["moves"]}


def reaction_keys(*, once_only: bool = False) -> set[str]:
    """Every ``agenda:reaction`` key, or only the ``once`` ones."""
    return {f"{aid}:{r['id']}" for aid, a in (spec().get("agendas") or {}).items()
            for r in a["reactions"] if r["once"] or not once_only}


# ---------------------------------------------------------------------------
# Roles and owners
# ---------------------------------------------------------------------------


def role(state: GameState, name: str) -> str:
    """
    The scheduled NPC the seed chose for role ``name``, or "".

    ``stable_rng(state.rng_seed, "agenda:<name>")`` choosing over ``from`` in
    its declared order, derived on EVERY read and never stored: a save cannot
    leak who the Magpie is, and a reload cannot change it. Its own stream, so
    adding a second role never re-deals the first.
    """
    from engine.game.rng import stable_rng

    row = (spec().get("roles") or {}).get(str(name))
    if not row:
        return ""
    return str(stable_rng(int(state.rng_seed), f"agenda:{name}").choice(row["from"]))


def owner_of(state: GameState, agenda_id: str) -> str:
    """Who pursues an agenda: its named NPC, or its role's chosen NPC. "" if unknown."""
    agenda = (spec().get("agendas") or {}).get(str(agenda_id))
    if not agenda:
        return ""
    return _npc_of(state, agenda["owner"])


def _npc_of(state: GameState, owner: Any) -> str:
    """An owner as the loader keeps it -- an npc id or ``{role}`` -- as an npc id."""
    return role(state, owner["role"]) if isinstance(owner, dict) else str(owner or "")


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------


def _live_witness_rows(state: GameState, guise: str) -> list[dict[str, Any]]:
    """
    Every LIVE witness row for a guise the watch takes for the same person as
    ``guise``: its deed not discharged, and not lost to a bribe.

    LOST TO A BRIBE means the deed was quashed (``quash_reports``) somewhere
    and no watch-house still holds a report of it. Not "quashed where it was
    done": the Law files a report where the WATCHMAN heard it
    (``law._propagate_hour``), so a lift up in town told to the captain in the
    village is filed in the village, and the sergeant paid to lose the
    village's file has lost the only one there is. Filed in two houses and
    lost in one, the other still holds it, and the word is live. A sighting
    never filed anywhere has nothing to lose, and is live too.

    One reading shared by ``reported_to`` and the ``witness`` selector, so a
    bribe that lost the file silences the captain's gate and the agenda's
    hunt for the witness alike.
    """
    from engine.world import law

    if not law.declared():
        return []
    faces = law.same_person(state, guise)
    gone = law.discharged(state)
    quashed = {str(d) for ids in (state.law.get("quashed") or {}).values()
               for d in ids or []}
    filed = {str(r.get("deed_id")) for r in state.law.get("reports") or []
             if r.get("deed_id")}
    rows: list[dict[str, Any]] = []
    for row in state.law.get("witnessed") or []:
        if row.get("guise") not in faces:
            continue
        deed_id = str(row.get("deed_id") or "")
        if deed_id in gone:
            continue
        if deed_id in quashed and deed_id not in filed:
            continue
        rows.append(row)
    return rows


def _witnesses(state: GameState, body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{npc: their first live row}`` for a ``witness`` selector's body."""
    from engine.world import law

    wanted_in = str(body.get("jurisdiction") or "")
    held: dict[str, dict[str, Any]] = {}
    for row in _live_witness_rows(state, str(body.get("knows") or "")):
        npc = str(row.get("npc") or "")
        if not npc:
            continue
        if wanted_in and law.jurisdiction_at(str(row.get("where") or "")) != wanted_in:
            continue
        held.setdefault(npc, row)
    return held


def _premise_candidates(state: GameState, body: dict[str, Any]) -> list[str]:
    from engine.game.inventory import tags_of
    from engine.world import jobs, premises

    taken: set[str] = set()
    if body.get("not_robbed"):
        # Robbed by anyone: the player's scores AND every agenda's. The two are
        # separate records (``agenda_hit``'s docstring) and both empty the house.
        taken = set(jobs.robbed(state)) | {
            str(hit.get("premise")) for hit in state.agendas.get("hits") or []
        }
        # And never the house of the player's OPEN job: an agenda robbing it
        # mid-job would empty the strongroom under the thief's hands. The
        # player opens and closes a job between calls to ``advance_time``, so
        # every hour of one call reads the same answer here and the cut does
        # not matter. The one close inside a call is ``jobs.tick`` (the watch
        # arriving), which runs after this walk: the house then stays off
        # limits to the end of that call rather than from the watch's hour --
        # the same seam as any move preceding its call's ``jobs.tick``.
        job = jobs.active(state)
        if job is not None:
            taken.add(str(job.get("premise") or ""))
    owner = _npc_of(state, body["owner"]) if "owner" in body else None
    found: list[str] = []
    for prem in state.procgen.premises:
        premise_id = str(prem.get("id") or "")
        tier = int(prem.get("tier") or 0)
        if not premise_id or premise_id in taken:
            continue
        if "district" in body and str(prem.get("district")) != str(body["district"]):
            continue
        if "type" in body and str(prem.get("type")) != str(body["type"]):
            continue
        if "tier_min" in body and tier < int(body["tier_min"]):
            continue
        if "tier_max" in body and tier > int(body["tier_max"]):
            continue
        if "loot_tag" in body and not any(
            str(body["loot_tag"]) in tags_of(str(item)) for item in prem.get("loot") or []
        ):
            continue
        if owner is not None and premises.owner(state, premise_id) != owner:
            continue
        found.append(premise_id)
    return sorted(found)


def _fence_candidates(body: dict[str, Any]) -> list[str]:
    from engine.game import trade

    return sorted(
        npc for npc, profile in trade.vendors().items()
        if profile.get("fence")
        and ("district" not in body or str(profile.get("location") or "") == str(body["district"]))
    )


def candidates(state: GameState, selector: dict[str, Any]) -> list[str]:
    """
    Every id a selector (``{kind: body}``, as the loader keeps it) matches, sorted.

    Sorted, so a tie is broken by the ``AGENDA`` stream alone and never by
    dict or generation order.
    """
    if not selector:
        return []
    kind, body = next(iter(selector.items()))
    if kind == "premise":
        return _premise_candidates(state, body)
    if kind == "fence":
        return _fence_candidates(body)
    if kind == "witness":
        return sorted(_witnesses(state, body))
    return []


def _pick(state: GameState, pool: list[str]) -> Optional[str]:
    """One of ``pool``: no draw for a single candidate, one ``AGENDA`` draw otherwise."""
    from engine.game.rng import AGENDA, world_rng

    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]
    return world_rng(state, AGENDA).choice(pool)


def select(state: GameState, selector: dict[str, Any]) -> Optional[str]:
    """The target a selector picks, or None when nothing matches."""
    return _pick(state, candidates(state, selector))


def _target_facts(state: GameState, selector: dict[str, Any], target: str) -> dict[str, str]:
    """
    What a move's placeholders say about its target.

    ``target_district`` is WHERE the target is: a premise's district, a
    fence's counter, the place a witness saw the deed. ``target_jurisdiction``
    is the watch there, "" without a Law or outside every jurisdiction -- in
    which case a ``report`` naming it refuses, cleanly, and files nothing.
    """
    from engine.game import trade
    from engine.world import law, npc_sim, premises

    kind, body = next(iter(selector.items()))
    if kind == "premise":
        prem = premises.get(state, target) or {}
        name, where = str(prem.get("name") or ""), str(prem.get("district") or "")
    elif kind == "fence":
        profile = trade.vendors().get(target) or {}
        name = str(profile.get("name") or "") or npc_sim.display_name(target, state)
        where = str(profile.get("location") or "")
    else:
        name = npc_sim.display_name(target, state)
        where = str((_witnesses(state, body).get(target) or {}).get("where") or "")
    return {
        "target": target,
        "target_name": name,
        "target_district": where,
        "target_jurisdiction": law.jurisdiction_at(where) if law.declared() and where else "",
    }


def _substitute(node: Any, subs: dict[str, str]) -> Any:
    """Fill ``{name}`` placeholders in every string value. The loader proved each fillable."""
    if isinstance(node, str):
        return _PLACEHOLDER.sub(lambda m: subs.get(m.group(1), m.group(0)), node)
    if isinstance(node, dict):
        return {key: _substitute(value, subs) for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute(value, subs) for value in node]
    return node


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

#: Slack on the hour-boundary arithmetic -- the Law's, for the Law's reason: a
#: clock that reached 12.0 by adding thirds crosses 12 once, in one call.
_HOUR_EPSILON = 1e-6


def _trace_where(state: GameState, at: GameState, owner: str, place: str,
                 facts: dict[str, str]) -> str:
    """A trace's ``where`` as a location id: the target's, the owner's then, or as written."""
    from engine.world import npc_sim

    if place == "target":
        return facts.get("target_district", "")
    if place == "owner":
        presence = npc_sim.resolve_npc(at, owner) if owner else None
        return str(presence.location_id) if presence is not None else ""
    return place


def _try_move(state: GameState, at: GameState, agenda_id: str, agenda: dict[str, Any],
              move: dict[str, Any], hour: int) -> Optional[dict[str, Any]]:
    """
    Fire one move at absolute ``hour`` if it is due; its receipt, or None.

    ``at`` is the per-hour scratch (``advance``): gates, selectors and the
    owner's whereabouts are READ at that hour. Every write lands on ``state``
    through ``apply_effect``.
    """
    from engine.game.effects import apply_effect, apply_effects
    from engine.game.quests import evaluate_condition

    key = f"{agenda_id}:{move['id']}"
    last = (state.agendas.get("moves") or {}).get(key)
    if last is None:
        if hour < move["start_hour"]:
            return None
    elif hour - int(last) < move["every_hours"]:
        return None
    if move["at_hours"] and hour % 24 not in move["at_hours"]:
        return None
    if not evaluate_condition(at, move["when"]):
        return None
    owner = owner_of(state, agenda_id)
    subs = {"owner": owner}
    target = ""
    if move["select"]:
        # Candidates read at the hour; the draw (if any) on the real counters.
        picked = _pick(state, candidates(at, move["select"]))
        if picked is None:
            return None  # nothing to act on: it does not fire and does not stamp
        target = picked
        subs.update(_target_facts(at, move["select"], target))
    receipts = apply_effects(state, _substitute(move["effects"], subs))
    if move["advance"]:
        receipts.append(apply_effect(state, {"type": "value", "name": agenda["clock"],
                                             "delta": move["advance"], "why": f"agenda:{key}"}))
    if move["robs"]:
        receipts.append(apply_effect(state, {"type": "agenda_hit", "agenda": agenda_id,
                                             "premise": target, "hour": hour}))
    trace = move["trace"]
    if trace:
        receipts.append(apply_effect(state, {
            "type": "agenda_trace", "agenda": agenda_id,
            "text": _substitute(trace["text"], subs),
            "where": _trace_where(state, at, owner, trace["where"], subs),
            "hour": hour, "public": trace["public"],
        }))
    apply_effect(state, {"type": "agenda_mark", "move": key, "hour": hour})
    return {"agenda": agenda_id, "move": move["id"], "hour": hour, "target": target,
            "effects": receipts}


def _scratch(state: GameState, hour: int) -> GameState:
    """A shallow copy whose clock reads ``hour``: where a gate is READ (``Walk``)."""
    at = copy.copy(state)
    at.world_clock_hours = float(hour)
    return at


def _try_reaction(state: GameState, agenda_id: str, agenda: dict[str, Any],
                  reaction: dict[str, Any], hour: int) -> Optional[dict[str, Any]]:
    """
    Evaluate one reaction at absolute ``hour``; its receipt if it fired, or None.

    EDGE-TRIGGERED. It fires when ``on`` holds now and did not at its last
    evaluation. A reaction with no ``truth`` recorded reads as false, so a
    condition already true the first time it is evaluated is an edge -- and
    ``truth`` need only be written when it CHANGES: a reaction that has never
    held leaves nothing in the save. A spent ``once`` reaction is not
    evaluated at all.

    ``on`` is read on a fresh scratch at the hour, after that hour's moves and
    the reactions before this one, so it sees what they wrote -- including an
    attribute an effect reassigned (an arrest's ``location_id``), which the
    moves' once-an-hour scratch would not. No ledger and no quest progress are
    in scope; the loader refuses the predicates that need them.
    """
    from engine.game.effects import apply_effect, apply_effects
    from engine.game.quests import evaluate_condition

    key = f"{agenda_id}:{reaction['id']}"
    if reaction["once"] and key in (state.agendas.get("fired") or []):
        return None
    was = bool((state.agendas.get("truth") or {}).get(key))
    now = bool(evaluate_condition(_scratch(state, hour), reaction["on"]))
    if now is was:
        return None
    if not now:
        apply_effect(state, {"type": "agenda_mark", "truth": {key: False}})
        return None
    receipts = apply_effects(state, _substitute(reaction["effects"],
                                                {"owner": owner_of(state, agenda_id)}))
    if reaction["advance"]:
        receipts.append(apply_effect(state, {"type": "value", "name": agenda["clock"],
                                             "delta": reaction["advance"],
                                             "why": f"agenda:{key}"}))
    mark: dict[str, Any] = {"type": "agenda_mark", "truth": {key: True}}
    if reaction["once"]:
        mark["fired"] = key
    apply_effect(state, mark)
    return {"agenda": agenda_id, "reaction": reaction["id"], "hour": hour,
            "effects": receipts}


class Walk:
    """
    The agendas pass over one ``advance_time`` call, on in-game hours.

    HOW IT IS DRIVEN. ``clock.advance_time`` makes one with ``begin`` and
    passes ``Walk.hour`` to ``law.propagate`` as its per-hour hook. So at each
    boundary the Law's talk and cooling run first, and then that hour's moves.
    The Law then treats a report or witness row a move files at 01:00 as it
    would one filed by a call that ENDED at 01:00: it cools and travels
    through the hours after it, and never through the hours before. After
    ``jobs.tick``, ``finish`` walks whatever the Law did not reach (the Law
    returns early for a story that declares none), stamps ``last_hour`` and
    fires the clock beats. That interleaving is what lets twelve 1h calls and
    one 12h call leave ``state.law`` identical as well as ``state.agendas``.

    Each boundary walked goes from ``state.agendas["last_hour"]`` to now. At
    each one, agendas go in sorted order and each agenda's moves in declared
    order, and a move sees what the moves before it wrote. The walk is capped
    at the Law's ``MAX_PROPAGATION_HOURS`` per call, with the Law's per-call
    caveat: cut-invariance holds for calls of 48 hours or less. The STAMP is
    not capped: ``last_hour`` goes to now, so hours past the cap are skipped,
    never replayed by the next call.

    THE FIRST CALL on a state with no ``last_hour`` starts at the hour the
    clock stood at before the call; that state is a new game, or a save from
    before agendas. The hours the call crosses are walked, and nothing before
    them is. So a new game's first twelve hours fire the same as one call or
    as twelve, and a save loaded on day 21 does not fire twenty days of past.

    READ AT THE HOUR, WRITTEN NOW. Gates, selectors and presence are read on a
    shallow copy whose clock is set to the boundary. This is the Law's
    ``_presence_scratch`` pattern: the real clock is never touched, since only
    ``advance_time`` writes it and it is already running. Effects apply to the
    real state, so a field an effect stamps with the DAY (a ``report``'s
    ``day``) takes the day the call ends on, as the Law's own reports do.

    CLOCK BEATS. ``clocks.resolve`` runs before the Law in ``advance_time``, so
    each hour's step fires, at the end of that hour, any beat its moves'
    ``advance`` crossed -- the same turn as the move, and before the next
    hour's moves, so a ``reset_to`` or a beat's ``set_flags`` reads the same
    whether the hours pass as one call or twelve. Only for the clocks that
    hour moved, and without re-running the clock table's ``advance_when``
    rules: a second ``resolve`` would wind every repeating rule twice.

    JOBS. In a story with a Law, hour h's moves run inside the Law's pass and
    so BEFORE that call's ``jobs.tick``. During an open job, a 1xN call and N
    1h calls can therefore differ if the watch's arrival writes Law state a
    later move reads. (The wall-clock tick is paused during a job; a job's
    own stage hours are the calls that cross it.)

    REACTIONS. After every agenda's moves at a boundary, each agenda (sorted)
    evaluates its reactions (declared order) through ``_try_reaction``: a
    false-to-true edge fires the effects and the clock ``advance``. After the
    moves, so a reaction answers a move of the same hour (a lift's report
    raises ``wanted``, the robbery is an ``agenda_hit``); before the beats,
    so a clock a reaction winds is struck with the moves' crossings at the
    end of that hour. A flag a reaction sets is read by the NEXT hour's moves
    -- the same hour whichever way the calls are cut.

    NO PREDICATE READS ``day``. The Law rows' ``day`` stamp (above) is the one
    field here that is not cut-invariant across midnight; ``wanted`` reads
    reports' deed, guise, jurisdiction, severity and precision and the
    cooling, ``reported_to`` the witness rows' npc, guise and deed id,
    ``agenda_hit`` the hits' agenda and premise, ``premise_robbed`` the
    player's robbed list. Held by ``test_no_agenda_predicate_reads_a_law_rows_day``.
    """

    def __init__(self, state: GameState, hours: float) -> None:
        from engine.world.law import MAX_PROPAGATION_HOURS

        self.state = state
        self.table: dict[str, Any] = spec().get("agendas") or {}
        clock_now = float(state.world_clock_hours)
        self.now = math.floor(clock_now + _HOUR_EPSILON)
        stamped = state.agendas.get("last_hour")
        if isinstance(stamped, bool) or not isinstance(stamped, int):
            stamped = None
        self.stamped = stamped
        self.last = stamped if stamped is not None else math.floor(
            clock_now - float(hours) + _HOUR_EPSILON)
        self.next = self.last + 1
        self.end = min(self.now, self.last + MAX_PROPAGATION_HOURS)
        self.receipts: list[dict[str, Any]] = []

    def hour(self, boundary: int) -> None:
        """Walk every boundary still due up to ``boundary``. Idempotent; the Law's hook."""
        while self.next <= min(int(boundary), self.end):
            self._step(self.next)
            self.next += 1

    def _step(self, hour: int) -> None:
        from engine.game import clocks as clocks_module

        at = _scratch(self.state, hour)
        wound: set[str] = set()
        for agenda_id in sorted(self.table):
            agenda = self.table[agenda_id]
            for move in agenda["moves"]:
                receipt = _try_move(self.state, at, agenda_id, agenda, move, hour)
                if receipt is not None:
                    self.receipts.append(receipt)
                    if move["advance"]:
                        wound.add(agenda["clock"])
        # Reactions AFTER every agenda's moves, so one can answer a move made
        # this same hour; BEFORE the beats, so a clock a reaction winds across
        # a beat is struck with the moves' crossings, once, at the end of the
        # hour.
        for agenda_id in sorted(self.table):
            agenda = self.table[agenda_id]
            for reaction in agenda["reactions"]:
                receipt = _try_reaction(self.state, agenda_id, agenda, reaction, hour)
                if receipt is not None:
                    self.receipts.append(receipt)
                    if reaction["advance"]:
                        wound.add(agenda["clock"])
        # The beats this hour's moves and reactions crossed fire at the END OF
        # THE HOUR, not of the call: a `reset_to` beat resets the clock before
        # the next hour winds it, and a beat's `set_flags` gate the next
        # hour's moves and reactions -- as they would across twelve 1h calls.
        if wound:
            for clock, beat_id in clocks_module.pending_beats(self.state):
                if clock in wound:
                    clocks_module.fire_beat(self.state, clock, beat_id)

    def finish(self) -> list[dict[str, Any]]:
        """
        Walk the rest and stamp ``last_hour``.

        Returns:
            One receipt per move fired, in order: ``{agenda, move, hour,
            target, effects}``. For tests and the harness; the state is the
            record.
        """
        from engine.game.effects import apply_effect

        self.hour(self.end)
        if self.now >= self.last and self.stamped != self.now:
            apply_effect(self.state, {"type": "agenda_mark", "last_hour": self.now})
        return self.receipts


def begin(state: GameState, hours: float) -> Optional[Walk]:
    """The pass over this ``advance_time`` call, or None when there is nothing to walk."""
    if not declared() or hours <= 0:
        return None
    return Walk(state, hours)


def advance(state: GameState, hours: float) -> list[dict[str, Any]]:
    """
    The whole pass in one call, with no Law interleaved -- ``begin`` then
    ``Walk.finish``. For a caller that has already moved the clock and runs
    nothing else per hour (the harness, tests). ``advance_time`` drives a
    ``Walk`` itself, through the Law's per-hour hook.
    """
    walk = begin(state, hours)
    return walk.finish() if walk is not None else []


# ---------------------------------------------------------------------------
# What the narrator may see
# ---------------------------------------------------------------------------

#: The most signs one prompt carries, the latest first to go in. The rest stay
#: unseen and wait for the next prompt built here.
SIGNS_MAX = 5
#: Where prompt assembly records which signs it rendered, until the turn has
#: narrated them (``mark_shown``/``clear_shown``). An attribute on the live
#: state object, NOT a dataclass field: it is never saved, never snapshotted by
#: the turn's transaction, and a story without agendas never gets one.
SHOWN_ATTR = "_agenda_traces_shown"


def signs_here(state: GameState) -> list[dict[str, Any]]:
    """
    The private traces the player could come upon where they stand: unseen,
    left at this location, at most ``SIGNS_MAX`` of the latest.

    A PUBLIC trace is never a sign -- ``agenda_trace`` journalled it at once,
    unlocated, as common talk.
    """
    if not declared():
        return []
    here = str(getattr(state, "location_id", "") or "")
    rows = [t for t in (state.agendas.get("traces") or [])
            if here and not t.get("seen") and not t.get("public") and t.get("where") == here]
    return rows[-SIGNS_MAX:]


def mark_shown(state: GameState) -> None:
    """
    Record which signs the prompt being built renders. Writes no game state.

    Called where the moved journal is marked (``engine/memory/context.py``):
    an evaluator retry rebuilds the prompt and must see the same signs, so they
    are not recorded seen until the narrator has written (``clear_shown``).
    """
    if not declared():
        return
    setattr(state, SHOWN_ATTR, [str(t["id"]) for t in signs_here(state)])


def clear_shown(state: GameState) -> None:
    """
    The signs the last prompt showed have been narrated: record them seen,
    through ``agenda_trace_seen`` (AGENTS.md rule 3). A sign left after that
    prompt was built was not in it, and waits for the next.
    """
    ids = state.__dict__.pop(SHOWN_ATTR, None)
    if not ids:
        return
    from engine.game.effects import apply_effect

    receipt = apply_effect(state, {"type": "agenda_trace_seen", "ids": ids})
    if not receipt.get("ok"):
        logger.warning("[agendas] Signs not recorded seen (operation=clear_shown): %s",
                       receipt.get("message"))


def _unmasked(state: GameState, mask: dict[str, Any]) -> bool:
    from engine.game.quests import evaluate_condition

    return bool(evaluate_condition(state, mask["unmask_when"]))


def masked_terms(state: GameState) -> list[tuple[str, str]]:
    """
    ``(name, instead)`` for every role whose mask has not lifted: the chosen
    NPC's display name and the aliases declared for THAT candidate, longest
    first so a full name goes before a part of it.

    THE SECRET IS THE LINK, NOT THE NAME. These are applied only to text the
    agendas themselves author (``mask_text``), because that is the one place
    the engine could put the role's NPC next to the role's deeds. The cast
    block, the storyteller prompt and the narration are never touched: masking
    one candidate's name everywhere would point at them. Read from state on
    every call, never cached, so an unmask takes effect on the next prompt.
    """
    if not declared():
        return []
    from engine.world import npc_sim

    out: list[tuple[str, str]] = []
    for name, row in sorted((spec().get("roles") or {}).items()):
        mask = row.get("mask") or {}
        if not mask or _unmasked(state, mask):
            continue
        npc = role(state, name)
        shown = npc_sim.display_name(npc, state)
        names = ([] if shown == "somebody" else [shown]) + list(mask["aliases"].get(npc, []))
        out.extend((term, mask["instead"]) for term in names if term)
    return sorted(out, key=lambda row: -len(row[0]))


def mask_text(state: GameState, text: str,
              terms: Optional[list[tuple[str, str]]] = None) -> str:
    """
    Agenda-authored ``text`` with every masked name replaced.

    The spoiler table's matching (``engine/lore/interceptors.py::_compile``),
    word-bounded, with these differences:

    * THE NAME IS CASE-SENSITIVE: these are proper nouns, and "a wren on the
      sill" is a bird, not a lamplighter.
    * AN ARTICLE IS NOT. A leading "the" before a name is swallowed as "the"
      or "The", so the replacement's own article reads ("The Wren" is "The
      Magpie", never "The the Magpie"). An alias that carries its own article
      ("the lamplighter") matches it in either case and NEEDS it -- "a
      lamplighter" is somebody else.
    * AT A SENTENCE START (start of text, or after . ! ? and a space) the
      replacement is capitalised: "The lamplighter was seen" becomes "The
      Magpie was seen".
    """
    for term, instead in (masked_terms(state) if terms is None else terms):
        text = _pattern(term).sub(lambda m, i=instead: _placed(m, i), text)
    return text


_ARTICLE = re.compile(r"(?i)the\s+")
#: Where a replacement starts a sentence: the start of the text, or the end of
#: one sentence (closing quotes and brackets allowed) and whitespace.
_SENTENCE_START = re.compile(r"(?:^|[.!?][\"')\]]*\s+)\s*$")


def _pattern(term: str) -> re.Pattern[str]:
    """``term``'s match: its core case-sensitive, any article in either case."""
    lead = _ARTICLE.match(term)
    if lead:
        return re.compile(rf"\b[Tt]he\s+{re.escape(term[lead.end():])}\b")
    return re.compile(rf"\b(?:[Tt]he\s+)?{re.escape(term)}\b")


def _placed(match: re.Match[str], instead: str) -> str:
    """``instead``, capitalised when the match opens a sentence."""
    if instead and _SENTENCE_START.search(match.string[:match.start()]):
        return instead[0].upper() + instead[1:]
    return instead


def revealed(state: GameState) -> list[tuple[str, str, str]]:
    """
    ``(instead, name, occupation)`` for every masked role whose ``unmask_when``
    now holds -- what the GM line may say, because the player has earned it.
    """
    if not declared():
        return []
    from engine.world import npc_sim

    out: list[tuple[str, str, str]] = []
    for name, row in sorted((spec().get("roles") or {}).items()):
        mask = row.get("mask") or {}
        if not mask or not _unmasked(state, mask):
            continue
        npc = role(state, name)
        sched = (npc_sim.load_npc_schedules().get("npcs", {}) or {}).get(npc) or {}
        occupation = str(sched.get("role") or "").strip() if isinstance(sched, dict) else ""
        out.append((mask["instead"], npc_sim.display_name(npc, state), occupation))
    return out


# ---------------------------------------------------------------------------
# Predicates for the shared condition grammar
# ---------------------------------------------------------------------------


def _p_wanted(state: GameState, value: Any, ctx: Any) -> bool:
    """``{wanted: {guise?: self, jurisdiction?: <here>, min: <band>}}``.

    The wanted band for that face in that jurisdiction is ``min`` or above, in
    the Law's own band order. False with no Law, and for a band it lacks.
    """
    from engine.world import law

    if not law.declared() or not isinstance(value, dict):
        return False
    bands = list(law.load_spec()["wanted"]["bands"])
    floor = str(value.get("min") or "")
    if floor not in bands:
        return False
    guise = str(value.get("guise") or law.SELF_GUISE)
    jurisdiction = str(value.get("jurisdiction") or law.jurisdiction_at(state.location_id))
    band = law.wanted_band(state, guise, jurisdiction)
    return band in bands and bands.index(band) >= bands.index(floor)


def _p_reported_to(state: GameState, value: Any, ctx: Any) -> bool:
    """``{reported_to: {npc, guise?: self}}`` -- that person holds word of it.

    A LIVE witness row held by ``npc`` whose guise the watch takes for the
    same person as ``guise``. A discharged deed's rows are gone already; a
    deed whose every file a bribe lost (``quash_reports``; see
    ``_live_witness_rows`` for why not "where it was done") is not live
    either -- the captain acting on a file the sergeant was paid to
    lose would make the bribe buy nothing.
    """
    from engine.world import law

    if not law.declared() or not isinstance(value, dict):
        return False
    npc = str(value.get("npc") or "")
    if not npc:
        return False
    guise = str(value.get("guise") or law.SELF_GUISE)
    return any(str(row.get("npc")) == npc for row in _live_witness_rows(state, guise))


def _p_agenda_hit(state: GameState, value: Any, ctx: Any) -> bool:
    """``{agenda_hit: {agenda?, premise?, district?}}`` -- an agenda robbed a match."""
    from engine.world import premises

    body = value if isinstance(value, dict) else {}
    for hit in state.agendas.get("hits") or []:
        if body.get("agenda") and str(hit.get("agenda")) != str(body["agenda"]):
            continue
        if body.get("premise") and str(hit.get("premise")) != str(body["premise"]):
            continue
        if body.get("district"):
            prem = premises.get(state, str(hit.get("premise") or "")) or {}
            if str(prem.get("district")) != str(body["district"]):
                continue
        return True
    return False


def _register() -> None:
    """Extend the shared condition grammar (listed in ``quests._GRAMMAR_MODULES``)."""
    from engine.game.quests import register_predicate

    register_predicate("wanted", _p_wanted)
    register_predicate("reported_to", _p_reported_to)
    register_predicate("agenda_hit", _p_agenda_hit)


_register()


__all__ = [
    "BOOKKEEPING_EFFECTS",
    "EFFECT_PLACEHOLDERS",
    "LAW_EFFECTS",
    "LAW_PREDICATES",
    "LEDGER_PREDICATES",
    "PROGRESS_PREDICATES",
    "SELECTOR_KEYS",
    "SHOWN_ATTR",
    "SIGNS_MAX",
    "TRACE_PLACEHOLDERS",
    "TRACE_WHERES",
    "Walk",
    "advance",
    "begin",
    "candidates",
    "clear_shown",
    "declared",
    "mark_shown",
    "mask_text",
    "masked_terms",
    "move_keys",
    "owner_of",
    "reaction_keys",
    "revealed",
    "role",
    "select",
    "signs_here",
    "spec",
]

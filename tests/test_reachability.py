"""
Every engine subsystem is reachable from a running game.

THE GATE THAT WOULD HAVE CAUGHT ALL OF IT. The suite was fully green, the
validator reported zero errors on all five shipped games, and the doctor was
clean -- while three whole subsystems and eleven registered skills had no
production caller at all. Each piece was tested in isolation and none of them
were connected, so nothing failed:

* ``engine/content/deck.py`` -- ``draw``/``resolve_card`` were called only by
  ``scripts/simulate_decks.py`` and by tests. The Wicked Garden's 11 decks,
  136 cards and 386 beats are the largest body of authored prose in the repo,
  and its only ``ending_lock`` sits on a card in a deck nothing dealt: the game
  could not be finished by playing it.
* ``engine/game/clocks.py::forced_scenes`` -- six shipped ``forces_scene:``
  beats raised a world event that nothing ever answered.
* ``engine/challenges/set_pieces.py`` -- the flagship declares ``challenges:``
  and ``docs/GOVERNANCE.md`` documented it as live.
* ``engine/game/threads.py`` -- 1177 lines, three games shipping
  ``threads.yaml``, and nothing that could ever create a thread.

Unit tests cannot see this: a test IS a caller, so a well-tested dead
subsystem looks exactly like a well-tested live one. This walks the call graph
of ``engine/`` alone -- tests and scripts excluded, because those are precisely
the callers that were hiding the problem -- and holds the answer against an
explicit allowlist.

THE ALLOWLIST IS A DESIGN RECORD, NOT A SHAME LIST. Some entries are correct
and deliberate: query skills whose caller is the MCP mechanics phase, verbs
that belong to another table. Each carries its reason. Adding a row is a
decision to be made on purpose and reviewed; it is not a way to make this file
go quiet.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1] / "engine"


#: ``qualified name -> why it has no production caller``.
#:
#: Every entry is a claim that this is INTENDED. Deleting a row is how a
#: subsystem gets wired up; adding one needs a reason that survives review.
ALLOWED_UNREACHABLE: dict[str, str] = {
    # Queries, not verbs. Their caller is the Phase A mechanics loop over MCP
    # (engine/agents/mechanics.py), which resolves skills by NAME at runtime --
    # so they are reached by string, and deliberately have no intent verb.
    "livelihood.query_forage": "MCP query skill; reached by name from Phase A",
    "livelihood.query_work": "MCP query skill; reached by name from Phase A",
    "livelihood.trade_quote": "MCP query skill; reached by name from Phase A",
    "livelihood.trade_browse": "MCP query skill; reached by name from Phase A",
    "mechanics.list_recipes": "MCP query skill; reached by name from Phase A",
    "mechanics.roll_dice": "MCP query skill; checks.resolve is the play path",
    # Covered by another table rather than by an intent verb.
    "mechanics.flee": "an encounter approach, resolved through the approach table",
    "mechanics.sleep_until": "rest covers this; kept for the MCP surface",
    # Inventory handling. Reached from the MCP surface and from item effects
    # rather than from a choice chip; there is no "equip" option on the turn.
    "items.use_item": "item effects and the MCP surface, not a choice chip",
    "items.equip_item": "item effects and the MCP surface, not a choice chip",
    "items.unequip_item": "item effects and the MCP surface, not a choice chip",
    "items.query_inventory": "MCP query skill; the sheet renders inventory",
    "items.query_equipment": "MCP query skill; the sheet renders equipment",
    "items.collections": "MCP query skill; the codex renders collections",
    "livelihood.trade_buy": "the `buy` verb resolves through `trade`",
    "livelihood.trade_haggle": "reached inside a trade, not as its own verb",
    # WIRED IN PHASE 2.6 -- these rows come out with that change.
    "mechanics.craft_item": "Phase 3 -- needs a recipe-selection surface first",
}


def _module_name(path: Path) -> str:
    return path.stem


def _iter_engine_files() -> list[Path]:
    return sorted(p for p in ENGINE.rglob("*.py") if p.name != "__init__.py")


def _qualified_calls(tree: ast.AST) -> set[str]:
    """
    References this module makes to another module's function, as ``mod.func``.

    QUALIFIED, not bare. Matching on the bare attribute name is far too loose
    for this job: ``start``, ``resolve`` and ``available`` appear all over the
    engine on unrelated objects, so ``set_pieces.start`` looked reached by
    ``encounter``'s own ``start`` and the check passed on a subsystem that had
    no caller at all. That false negative is worse than no test.

    All the import shapes in use here are recognised, INCLUDING ALIASES:

        from engine.content.deck import draw          ->  draw(...)
        from engine.game import encounter as encounter_module
                                                      ->  encounter_module.begin(...)
        import engine.game.clocks as clocks           ->  clocks.forced_scenes(...)

    The alias case is not optional: this engine's house style is
    ``from engine.game import encounter as encounter_module``, so a matcher
    that only understood the bare stem would report the single most obviously
    live subsystem in the codebase as dead.
    """
    found: set[str] = set()
    # alias in this file -> the module stem it actually refers to
    aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                stem = alias.name.rsplit(".", 1)[-1]
                aliases[alias.asname or stem] = stem
        elif isinstance(node, ast.ImportFrom) and node.module:
            parent = node.module.rsplit(".", 1)[-1]
            for alias in node.names:
                # `from engine.content.deck import draw` -- a direct function
                # import is itself a reference.
                found.add(f"{parent}.{alias.name}")
                # `from engine.game import encounter as encounter_module`
                aliases[alias.asname or alias.name] = alias.name

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base = node.value.id
            found.add(f"{aliases.get(base, base)}.{node.attr}")

    return found


def _string_literals(tree: ast.AST) -> set[str]:
    """
    Every bare string in the module.

    The skill registry (``SKILL_REGISTRY.invoke(name)``) and the
    condition-predicate table are both keyed by string, so a name that only
    ever appears in quotes is genuinely reachable.
    """
    return {
        node.value.strip()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


@pytest.fixture(scope="module")
def call_graph() -> dict[str, tuple[set[str], set[str]]]:
    """``file -> (qualified calls it makes, string literals it holds)``."""
    graph: dict[str, tuple[set[str], set[str]]] = {}
    for path in _iter_engine_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - a parse error is its own bug
            pytest.fail(f"{path} does not parse: {exc}")
        graph[str(path)] = (_qualified_calls(tree), _string_literals(tree))
    return graph


def _is_reached(
    module: str,
    func: str,
    defining_file: str,
    graph: dict[str, tuple[set[str], set[str]]],
) -> bool:
    """
    Whether anything in engine/ OTHER than the defining module calls this.

    Qualified references only. String literals are NOT consulted here, even
    though they are how skills get dispatched: words like "active", "start" and
    "offer" appear as ordinary strings throughout the engine, and counting them
    reported ``threads.offer`` and ``threads.active`` as reachable in a
    codebase where nothing could create a thread at all. Skill-name dispatch is
    a separate question and is tested separately below.
    """
    target = f"{module}.{func}"
    return any(
        target in calls for path, (calls, _strings) in graph.items()
        if path != defining_file
    )


#: The public surface each subsystem must expose to a running game. Named
#: explicitly rather than derived, because "every public function" would drown
#: the signal in helpers that are legitimately module-local.
LOAD_BEARING: dict[str, tuple[str, ...]] = {
    "deck": ("draw", "resolve_card", "load_deck", "deck_ids"),
    "clocks": ("forced_scenes", "mark_scene_played"),
    "set_pieces": ("start", "resolve", "available"),
    "threads": ("offer", "seal", "discharge", "active"),
    # THE POSITIVE CONTROL. `encounter` is the shape the others are being wired
    # into -- an engine-owned scene that occupies a turn and is resolved by one
    # intent verb -- and it is unquestionably live. It carries no KNOWN_UNWIRED
    # rows, so if the detector ever starts answering "unreachable" to
    # everything, this is the row that fails and says so. A test that can only
    # return one answer is not a test.
    "encounter": ("begin", "check_death"),
}


#: A RATCHET, and it is meant to reach zero.
#:
#: These are the entry points found dead by the audit and being wired up now.
#: Each row is deleted by the change that wires it, and the test below fails if
#: a row is still here after its subsystem became reachable -- so the list
#: cannot quietly outlive the problem it describes. It exists at all because a
#: red suite blocks every other repair; the debt stays machine-checked instead
#: of becoming a paragraph in a document nobody greps.
KNOWN_UNWIRED: dict[str, str] = {
}


@pytest.mark.parametrize("subsystem", sorted(LOAD_BEARING))
def test_a_shipped_subsystem_is_reachable_from_the_engine(
    subsystem: str, call_graph: dict[str, tuple[set[str], set[str]]]
) -> None:
    """
    Each of these has shipped content behind it in at least one game. A
    subsystem nothing in ``engine/`` calls is content the player cannot reach,
    however well its own unit tests pass.
    """
    defining = next(
        (str(p) for p in _iter_engine_files() if _module_name(p) == subsystem), ""
    )
    assert defining, f"engine/**/{subsystem}.py not found"

    dead = [
        name
        for name in LOAD_BEARING[subsystem]
        if not _is_reached(subsystem, name, defining, call_graph)
        and f"{subsystem}.{name}" not in KNOWN_UNWIRED
    ]
    assert not dead, (
        f"{subsystem}: {dead} have no caller anywhere in engine/. "
        "Content authored against them cannot be reached by playing. Wire them "
        "into the turn, or record them in a NOT WIRED table and say so in the "
        "docs that claim otherwise (CLAUDE.md rule 9)."
    )


@pytest.mark.parametrize("subsystem", sorted(LOAD_BEARING))
def test_the_unwired_ratchet_does_not_outlive_the_problem(
    subsystem: str, call_graph: dict[str, tuple[set[str], set[str]]]
) -> None:
    """
    A row that has been wired up must be deleted, not left behind.

    Otherwise the list stops describing the repo and starts excusing it, which
    is the exact failure mode of a NOT WIRED table nobody re-checks.
    """
    defining = next(
        (str(p) for p in _iter_engine_files() if _module_name(p) == subsystem), ""
    )
    stale = [
        name
        for name in LOAD_BEARING[subsystem]
        if f"{subsystem}.{name}" in KNOWN_UNWIRED
        and _is_reached(subsystem, name, defining, call_graph)
    ]
    assert not stale, (
        f"{subsystem}: {stale} are reachable now -- delete their rows from "
        "KNOWN_UNWIRED so the ratchet keeps counting down."
    )


def test_every_registered_skill_is_reachable_or_declared_unreachable() -> None:
    """
    A skill is reachable if an intent verb resolves to it, or if it is an
    allowlisted MCP query. Anything else is implemented, tested and unplayable.
    """
    import engine.agents.tool_dispatcher  # noqa: F401 -- registers the builtins
    from engine.game.intents import SKILL_FOR_ACTION
    from engine.skills.registry import SKILL_REGISTRY

    by_verb = set(SKILL_FOR_ACTION.values())
    allowed = {row.split(".", 1)[1] for row in ALLOWED_UNREACHABLE}

    # Storyteller/GAME skills only. The Assistant's narrative skills and the
    # quest-bookkeeping helpers are called by their own agents, not by a player
    # choosing an option, so an intent verb is not the right reachability test
    # for them.
    playable = [
        s
        for s in SKILL_REGISTRY.all_tools()
        if s.category == "GAME" and "storyteller" in (s.agents or [])
    ]
    unreachable = sorted(
        s.name for s in playable if s.name not in by_verb and s.name not in allowed
    )
    assert not unreachable, (
        "these skills are registered and no intent verb reaches them, so a "
        f"player can never cause them to run: {unreachable}. Give each one a "
        "verb in engine/game/intents.py, or add it to ALLOWED_UNREACHABLE "
        "above WITH ITS REASON."
    )


def test_the_allowlist_does_not_rot() -> None:
    """
    A row for a skill that no longer exists is a lie the next reader inherits.
    """
    import engine.agents.tool_dispatcher  # noqa: F401 -- registers the builtins
    from engine.skills.registry import SKILL_REGISTRY

    known = {s.name for s in SKILL_REGISTRY.all_tools()}
    stale = sorted(
        row for row in ALLOWED_UNREACHABLE if row.split(".", 1)[1] not in known
    )
    assert not stale, f"ALLOWED_UNREACHABLE names skills that do not exist: {stale}"


def test_every_allowlist_entry_gives_a_reason() -> None:
    empty = sorted(k for k, v in ALLOWED_UNREACHABLE.items() if not v.strip())
    assert not empty, f"allowlisted with no reason: {empty}"


def test_the_four_intent_tables_agree() -> None:
    """
    A verb is described in FOUR places and all four must say the same thing.

    ``SKILL_FOR_ACTION`` names the skill, ``REFUSAL_KEY_FOR_ACTION`` says which
    result key means "it did not happen", ``to_tool_call`` maps the target onto
    that skill's arguments, and the registry has to actually hold the skill.
    Nothing checked that they agreed, and the failure is silent in the worst
    way: ``legal_intents`` feeds the JSON grammar, so a verb whose executor
    rejects its own enum produces an unsatisfiable branch and the model returns
    nothing at all -- an empty turn with no error anywhere.
    """
    import engine.agents.tool_dispatcher  # noqa: F401 -- registers the builtins
    from engine.game.intents import (
        REFUSAL_KEY_FOR_ACTION,
        SKILL_FOR_ACTION,
        to_tool_call,
    )
    from engine.game.state import GameState
    from engine.skills.registry import SKILL_REGISTRY

    registered = {s.name for s in SKILL_REGISTRY.all_tools()}

    missing_skill = sorted(
        f"{verb} -> {skill}"
        for verb, skill in SKILL_FOR_ACTION.items()
        if skill not in registered
    )
    assert not missing_skill, f"verbs naming a skill that is not registered: {missing_skill}"

    missing_refusal = sorted(set(SKILL_FOR_ACTION) - set(REFUSAL_KEY_FOR_ACTION))
    assert not missing_refusal, (
        f"verbs with no refusal key: {missing_refusal}. Without one, a refused "
        "action is scored as a success and the narrator is told it happened."
    )

    orphan_refusal = sorted(set(REFUSAL_KEY_FOR_ACTION) - set(SKILL_FOR_ACTION))
    assert not orphan_refusal, f"refusal keys for verbs that do not exist: {orphan_refusal}"

    unmapped = []
    for verb in SKILL_FOR_ACTION:
        try:
            name, args = to_tool_call(GameState(), {"action": verb, "target": "x/y"})
        except KeyError:
            unmapped.append(verb)
            continue
        if name != SKILL_FOR_ACTION[verb] or not isinstance(args, dict):
            unmapped.append(verb)
    assert not unmapped, (
        f"verbs with no to_tool_call branch: {unmapped}. The intent would be "
        "declared, sampled, and then raise on execution."
    )

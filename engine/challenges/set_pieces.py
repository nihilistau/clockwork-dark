"""
Set-Pieces — authored challenges behind world gates
===================================================

A set-piece is a stored challenge plus a flag gate, which is what turns the
doom clock from a counter into a loop:

    doom beat  ->  sets a flag  ->  unlocks a set-piece  ->  terminal flag

``engine/world/world_effects.py`` sets ``scarecrow_awake`` when the Dark
reaches 0.30. That flag is what makes the scarecrow set-piece available. Playing
it sets ``set_piece_scarecrow_done``, which forbids it from ever appearing
again. Every link in that chain is a flag on ``GameState``, so the whole loop
persists through a save and needs no new machinery.

Authored specs run through exactly the same validator as model-composed ones.
That is deliberate: a hand-written YAML file is not more trustworthy than a
model, it is just wrong less often, and having one bounding path means the
ceilings cannot drift apart. The one difference is CAPABILITY, not size:
``start`` validates with ``authored=True``, which admits the structural kinds
(``spec.STRUCTURAL_EFFECT_TYPES``) and ``release``
(``spec.AUTHORED_CHALLENGE_EFFECT_TYPES``) -- so a break-out scene can free a
prisoner -- and changes no magnitude clamp.

GATES. ``location_id``, ``requires_flags`` and ``forbids_flags`` as before,
plus an optional ``requires:`` -- any condition in the shared grammar
(``quests.evaluate_condition``), e.g. ``{in_custody: true}`` for a break-out
offered only in the cell. The custody record sets no flag, so a flag gate
could not ask that. Its predicate names are checked at load
(``quests.condition_problem``); a piece naming one the grammar lacks, or one
this gate cannot answer (``disposition``, ``days_in_stage``,
``days_since_started`` -- no ledger, no quest here), is logged and skipped,
since an unknown predicate is
unmet forever, silently.

ONE TRY A DAY, OPT-IN (v0.17). ``retry: next_day`` keeps a FAILED piece
off offer for the rest of the world day it failed on: ``resolve`` stamps the
day under ``FAILED_ON_PREFIX + id`` through the ``flag`` effect, and
``is_available`` compares it with ``state.world_day``. A piece without the
key is offered again at once, as every piece always was. HUE & CRY's
jailbreak uses it, so a break-out that costs no time is one roll a day and
not a string of free rerolls.

VALIDATED WITH THE STORY (v0.17). Everything else the loader forgives --
a place the graph lacks, a flag gate written as a string, a challenge the spec
rejects, a ``release`` in a failed outcome -- is reported by
``set_piece_problems``, which ``engine/games/validation.py`` (so doctor and
``validate_content``) runs over ``paths.challenges``.

Version: v0.4.0 [2026-09-27]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.challenges import runner
from engine.config import get_config
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_CACHE: Optional[dict[str, dict[str, Any]]] = None

#: Key under which the owning set-piece id is stashed on the active challenge,
#: so resolution knows which terminal flag to grant.
SET_PIECE_KEY = "set_piece"

#: ``retry:`` values a piece may declare. Absent: a failed piece is offered
#: again at once (every piece before v0.17). ``next_day``: not again on the
#: day it failed -- HUE & CRY's jailbreak, one try a day.
RETRY_VALUES = ("next_day",)

#: Flag ``<prefix><piece id>`` holds the world day a ``retry: next_day``
#: piece last FAILED on (an int, through the ``flag`` effect). Engine-owned.
FAILED_ON_PREFIX = "set_piece_failed_on_"


def _catalogue_dir() -> Optional[Path]:
    """The challenge directory, or None when the story declares none."""
    rel = str(get_config().get("paths.challenges", "") or "").strip()
    return (_ROOT / rel) if rel else None


def load_set_pieces() -> dict[str, dict[str, Any]]:
    """
    Read every ``*.yaml`` in the challenge directory, keyed by set-piece id.

    A malformed file is logged and skipped rather than raised: one bad content
    file must not remove every set-piece from the game.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    catalogue: dict[str, dict[str, Any]] = {}
    directory = _catalogue_dir()
    if directory is None:
        logger.debug(
            "[set_pieces] Story declares no challenges (operation=load_set_pieces)"
        )
        _CACHE = catalogue
        return _CACHE
    if not directory.is_dir():
        logger.info(
            "[set_pieces] No challenge directory (operation=load_set_pieces, path=%s)",
            directory,
        )
        _CACHE = catalogue
        return _CACHE

    for path in sorted(directory.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.error(
                "[set_pieces] Unreadable set-piece file, skipping "
                "(operation=load_set_pieces, path=%s): %s",
                path,
                exc,
            )
            continue

        for raw in (data or {}).get("set_pieces", []) or []:
            if not isinstance(raw, dict):
                continue
            piece_id = str(raw.get("id", "")).strip()
            if not piece_id:
                logger.error(
                    "[set_pieces] Set-piece with no id, skipping "
                    "(operation=load_set_pieces, path=%s)",
                    path,
                )
                continue
            if piece_id in catalogue:
                logger.error(
                    "[set_pieces] Duplicate set-piece id, keeping the first "
                    "(operation=load_set_pieces, id=%s, path=%s)",
                    piece_id,
                    path,
                )
                continue
            problem = _requires_problem(raw.get("requires"))
            if problem:
                logger.error(
                    "[set_pieces] Bad `requires`, skipping (operation=load_set_pieces, "
                    "id=%s, path=%s): %s",
                    piece_id,
                    path,
                    problem,
                )
                continue
            catalogue[piece_id] = raw

    logger.info(
        "[set_pieces] Catalogue loaded (operation=load_set_pieces, pieces=%d)",
        len(catalogue),
    )
    _CACHE = catalogue
    return _CACHE


def _requires_problem(node: Any) -> Optional[str]:
    """
    What is wrong with a set-piece's ``requires:`` condition, or None.

    The shared check (``quests.condition_problem``): an unknown predicate is
    unmet forever; a mapping holding a group combinator is evaluated as ONLY
    its combinators, so a sibling predicate beside ``all`` would gate nothing;
    and ``is_available`` evaluates with no ledger and no quest record, so
    ``disposition``, ``days_in_stage`` and ``days_since_started`` would never
    hold. All load, validate and do nothing unless refused here.
    """
    from engine.game import quests

    return quests.condition_problem(
        node, where="`requires`", forbid=quests.CONTEXT_FREE_FORBIDS
    )


def _flag_name_ok(value: Any) -> bool:
    """One flag name: a non-empty string with no whitespace in it."""
    return isinstance(value, str) and bool(value) and not any(ch.isspace() for ch in value)


def _outcome_blocks(challenge: dict[str, Any]) -> list[tuple[str, bool, Any]]:
    """
    Every effect list a challenge can apply, as ``(where, succeeded, effects)``.

    ``succeeded`` is whether the runner applies that list on a SUCCESS
    (``engine/challenges/runner.py``): a gauntlet's or puzzle's ``reward``, a
    decision tree's success node's ``reward``, and every dice-table row (a
    roll always succeeds). A ``fail`` block, and a failure node's ``reward``
    -- which the runner never reads -- are not.
    """
    blocks: list[tuple[str, bool, Any]] = []
    kind = str(challenge.get("kind", "")).strip().lower()
    if kind == "decision_tree":
        for node_id, node in (challenge.get("nodes") or {}).items():
            if not isinstance(node, dict) or not node.get("terminal"):
                continue
            won = str(node.get("outcome", "success")).strip().lower() != "failure"
            for key in ("reward", "fail"):
                block = node.get(key)
                if isinstance(block, dict):
                    blocks.append(
                        (f"node '{node_id}' {key}", won and key == "reward", block.get("effects"))
                    )
    elif kind == "dice_table":
        for index, row in enumerate(challenge.get("outcomes") or []):
            if isinstance(row, dict):
                blocks.append((f"outcomes[{index}]", True, row.get("effects")))
    else:
        for key in ("reward", "fail"):
            block = challenge.get(key)
            if isinstance(block, dict):
                blocks.append((key, key == "reward", block.get("effects")))
    return blocks


def _count_releases(node: Any) -> int:
    if isinstance(node, dict):
        own = 1 if str(node.get("type", "")).strip().lower() == "release" else 0
        return own + sum(_count_releases(v) for v in node.values())
    if isinstance(node, list):
        return sum(_count_releases(v) for v in node)
    return 0


def set_piece_problems(
    raw: Any,
    *,
    locations: Optional[set[str]] = None,
    effect_types: Optional[frozenset[str]] = None,
) -> list[str]:
    """
    Everything wrong with one authored set-piece, for the load-time checks.

    THE LOADER'S FORGIVENESS IS WHY THIS EXISTS. ``load_set_pieces`` keeps
    any mapping with an id and a readable ``requires:``, and every other
    mistake loads and does nothing -- or the wrong thing -- with nothing said:
    a ``requires_flags: gate_open`` gates on the letters g, a, t, e; a piece
    at a place the graph lacks is never offered; a challenge the spec rejects
    fails on the turn the player starts it; a ``release`` in a ``fail`` block
    frees the prisoner who FAILED the break-out. ``engine/games/validation.py``
    (and so doctor and validate_content) calls this, the way it calls
    ``encounter.death_terminal_problem``: one home for the rule.

    Args:
        raw: The set-piece as written.
        locations: The story's place ids, or None to skip that check (a story
            with no graph).
        effect_types: Every effect type a set-piece's outcome may apply in
            this story, or None to skip that check. ``{type: value, name: x}``
            is checked under ``x``.

    Returns:
        Human-readable problems; ``[]`` for a clean piece.
    """
    from engine.challenges import spec as spec_module

    if not isinstance(raw, dict):
        return ["set-piece entry is not a mapping"]
    problems: list[str] = []

    location = raw.get("location_id")
    if location is not None:
        if not isinstance(location, str) or not location.strip():
            problems.append("`location_id` is not a place id")
        elif locations is not None and location.strip() not in locations:
            problems.append(f"`location_id` {location!r} is not a place in the story's graph")

    for key in ("requires_flags", "forbids_flags"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            problems.append(f"`{key}` must be a list of flag names, not {type(value).__name__}")
            continue
        for flag in value:
            if not _flag_name_ok(flag):
                problems.append(f"`{key}` holds {flag!r}, which is not a flag name")

    if "grants_flag" in raw and not _flag_name_ok(raw.get("grants_flag")):
        problems.append(f"`grants_flag` {raw.get('grants_flag')!r} is not one flag name")

    if "retry" in raw and raw.get("retry") not in RETRY_VALUES:
        problems.append(
            f"`retry` {raw.get('retry')!r} is not one of {', '.join(RETRY_VALUES)}; "
            "leave it out to offer a failed piece again at once"
        )

    requires_problem = _requires_problem(raw.get("requires"))
    if requires_problem:
        problems.append(requires_problem)

    challenge = raw.get("challenge")
    checked = spec_module.validate(challenge, authored=True)
    if not checked.ok:
        problems.append(f"`challenge` will not start: {checked.error}")
    challenge = challenge if isinstance(challenge, dict) else {}

    allowed_releases = 0
    for where, succeeded, effects in _outcome_blocks(challenge):
        for effect in effects if isinstance(effects, list) else []:
            if not isinstance(effect, dict):
                problems.append(f"`challenge` {where}: effect {effect!r} is not a mapping")
                continue
            kind = str(effect.get("type", "")).strip().lower()
            name = kind
            if kind == "value":
                name = str(effect.get("name") or effect.get("id") or "").strip().lower()
            if kind == "release":
                if succeeded:
                    allowed_releases += 1
                else:
                    problems.append(
                        f"`challenge` {where}: `release` frees the player only from a "
                        "challenge's success outcome, never a failed one"
                    )
                    allowed_releases += 1  # reported here, not again below
                continue
            if effect_types is not None and name not in effect_types:
                problems.append(
                    f"`challenge` {where}: effect type {name!r} is not one a set-piece "
                    "may apply; the runner drops it"
                )
    if _count_releases(raw) > allowed_releases:
        problems.append(
            "`release` appears outside the challenge's outcomes; only a challenge's "
            "success outcome can free the player"
        )
    return problems


def set_piece_effect_types(declared_values: set[str]) -> frozenset[str]:
    """
    What a set-piece's outcome may apply in a story declaring these values:
    the model-composed set, the structural kinds, ``release``, and the
    story's own values. The same union ``spec.validate(authored=True)`` admits
    at runtime, built without activating the story.
    """
    from engine.challenges import spec as spec_module

    return frozenset(
        spec_module.ALLOWED_EFFECT_TYPES
        | spec_module.STRUCTURAL_EFFECT_TYPES
        | spec_module.AUTHORED_CHALLENGE_EFFECT_TYPES
        | {str(v).lower() for v in declared_values}
    )


def reset_set_piece_cache() -> None:
    """Drop the cached catalogue. Game swap and tests."""
    global _CACHE
    _CACHE = None


def is_available(state: GameState, piece: dict[str, Any]) -> bool:
    """
    True if every gate on this set-piece is satisfied right now.

    Gates are AND-ed. ``forbids_flags`` is what makes a set-piece one-shot:
    its own terminal flag is listed there. ``requires:``, when present, is a
    condition in the shared grammar -- evaluated last, and only for a piece
    that declares one, so a piece without it costs exactly what it did.
    """
    location = str(piece.get("location_id", "")).strip()
    if location and state.location_id != location:
        return False
    for flag in piece.get("requires_flags", []) or []:
        if not state.flags.get(str(flag)):
            return False
    for flag in piece.get("forbids_flags", []) or []:
        if state.flags.get(str(flag)):
            return False
    grants = str(piece.get("grants_flag", "")).strip()
    # A piece that already granted its terminal flag is done, even if the
    # author forgot to list it under forbids_flags.
    if grants and state.flags.get(grants):
        return False
    if piece.get("retry") == "next_day" and _failed_today(state, piece):
        return False
    requires = piece.get("requires")
    if requires is not None:
        from engine.game.quests import evaluate_condition

        return evaluate_condition(state, requires)
    return True


def _failed_today(state: GameState, piece: dict[str, Any]) -> bool:
    """Whether this piece's last failure was on the current world day."""
    stamp = state.flags.get(FAILED_ON_PREFIX + str(piece.get("id", "")))
    return isinstance(stamp, int) and not isinstance(stamp, bool) and stamp == state.world_day


def available(state: GameState) -> list[dict[str, Any]]:
    """Every set-piece whose gates are open, in id order for determinism."""
    return [
        piece
        for _, piece in sorted(load_set_pieces().items())
        if is_available(state, piece)
    ]


def start(
    state: GameState,
    piece_id: str,
    *,
    replace: bool = False,
) -> runner.ChallengeResult:
    """
    Begin a set-piece, if its gates are open.

    Args:
        state: Mutable game state.
        piece_id: Catalogue id.
        replace: Passed to the runner; abandons a running challenge.

    Returns:
        The challenge's first step, or an error result when the piece is
        unknown or gated shut.
    """
    piece = load_set_pieces().get(piece_id)
    if piece is None:
        return runner._error(f"unknown set-piece {piece_id!r}")
    if not is_available(state, piece):
        return runner._error(f"set-piece {piece_id!r} is not available here")

    # `authored=True`: the spec came out of the story's own file, so its
    # rewards may use the structural kinds and `release` (a break-out).
    result = runner.start(
        state, piece.get("challenge") or {}, replace=replace, authored=True
    )
    if state.challenge:
        # Stashed on the stored challenge, not held in a module global: the
        # player can save mid-set-piece and reload tomorrow, and the terminal
        # flag still has to be granted when they finish.
        state.challenge[SET_PIECE_KEY] = piece_id
    if result.status != runner.STATUS_ERROR:
        logger.info(
            "[set_pieces] Set-piece started (operation=start, id=%s)", piece_id
        )
    return result


def resolve(state: GameState, **kwargs: Any) -> runner.ChallengeResult:
    """
    Advance the active challenge, granting a set-piece's terminal flag on success.

    Accepts and forwards the runner's keyword arguments (``choice``, ``answer``,
    ``rng``, ``ledger``).
    """
    # Captured BEFORE resolution: a resolved challenge is cleared off the state,
    # taking the set-piece id with it.
    piece_id = str((state.challenge or {}).get(SET_PIECE_KEY, ""))
    # The day the attempt was MADE: a lethal failure's respawn can carry the
    # clock past midnight inside `runner.resolve`.
    day = state.world_day
    result = runner.resolve(state, **kwargs)

    if not piece_id or not result.ended:
        return result
    piece = load_set_pieces().get(piece_id) or {}
    if not result.success:
        if piece.get("retry") == "next_day":
            # `retry: next_day` (v0.17 T4 fix round 1, opt-in): a failed piece
            # waits for tomorrow. Stamped with the day, through the one writer.
            from engine.game import effects as effects_module

            effects_module.apply_effect(
                state, {"type": "flag", "flag": FAILED_ON_PREFIX + piece_id, "value": day}
            )
        return result

    grants = str(piece.get("grants_flag", "")).strip()
    if grants:
        from engine.game import effects as effects_module

        effects_module.apply_effect(
            state, {"type": "flag", "flag": grants, "value": True}
        )
        logger.info(
            "[set_pieces] Set-piece completed (operation=resolve, id=%s, flag=%s)",
            piece_id,
            grants,
        )
    return result


__all__ = [
    "FAILED_ON_PREFIX",
    "RETRY_VALUES",
    "SET_PIECE_KEY",
    "available",
    "is_available",
    "load_set_pieces",
    "reset_set_piece_cache",
    "resolve",
    "set_piece_effect_types",
    "set_piece_problems",
    "start",
]

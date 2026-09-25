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

Version: v0.2.0 [2026-09-25]
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
    requires = piece.get("requires")
    if requires is not None:
        from engine.game.quests import evaluate_condition

        return evaluate_condition(state, requires)
    return True


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
    result = runner.resolve(state, **kwargs)

    if not piece_id or not result.ended or not result.success:
        return result

    piece = load_set_pieces().get(piece_id) or {}
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
    "SET_PIECE_KEY",
    "available",
    "is_available",
    "load_set_pieces",
    "reset_set_piece_cache",
    "resolve",
    "start",
]

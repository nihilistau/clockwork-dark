"""
State Transactions
==================

Snapshot and rollback for a turn.

The retry loop executed tool calls BEFORE the evaluator ran and never undid
them. A draft rejected for hallucinated mechanics had already spent stamina,
moved the player four hours down the road and burned a skill check -- the
player was teleported and drained by a narration they never saw. The receipts
were then reassigned on retry, so the audit trail did not even record it.

Rollback restores in place rather than rebinding, so ``GameEngine.state`` and
every session reference stay valid.

A side benefit worth keeping: every turn now round-trips the save serializer,
so a regression in to_save_dict/from_dict surfaces immediately in normal play
rather than the first time someone loads a save.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import fields
from typing import Any, Iterator

from engine.game.state import GameState

logger = logging.getLogger(__name__)


def restore_in_place(target: GameState, source: GameState) -> None:
    """
    Copy every field from source onto target, keeping target's identity.

    Iterates ``type(target)``, NOT ``GameState``. The literal base class was the
    sharpest edge in the engine: any field a story added beyond the base
    dataclass was silently reverted here on every evaluator retry and every tool
    savepoint -- both of which run on ordinary turns. There was no log line and
    no exception; it would have presented as "the new meters occasionally do not
    move", visible only on turns the model happened to get rejected.
    """
    for spec in fields(type(target)):
        setattr(target, spec.name, getattr(source, spec.name))


class StateTransaction:
    """Snapshot of a GameState that can be rolled back."""

    def __init__(self, state: GameState) -> None:
        self.state = state
        self._snapshot: dict[str, Any] = state.to_save_dict()
        self.committed = False

    def rollback(self) -> None:
        """
        Undo every mutation since the snapshot.

        Rehydrates through ``type(self.state)`` for the same reason
        ``restore_in_place`` walks ``type(target)``: rebuilding through the base
        class would hand back an object missing every extended field, so the
        restore would have nothing to copy even after the loop was fixed. Both
        halves have to know the real class or neither works.
        """
        restore_in_place(self.state, type(self.state).from_dict(self._snapshot))
        logger.debug(
            "[transaction] Rolled back (operation=rollback, turn=%s)",
            self.state.turn_number,
        )

    def commit(self) -> None:
        self.committed = True

    @contextmanager
    def savepoint(self) -> Iterator["StateTransaction"]:
        """
        Nested snapshot for a single tool call.

        Rolls back only that call's effects if it raises, leaving earlier tool
        results in the turn intact.
        """
        inner = StateTransaction(self.state)
        try:
            yield inner
        except Exception:
            inner.rollback()
            raise
        else:
            inner.commit()


@contextmanager
def transaction(state: GameState) -> Iterator[StateTransaction]:
    """
    Scope a turn. Rolls back automatically if the block raises.

    Explicit rollback is still available for the non-exceptional case where the
    evaluator rejects a draft.
    """
    tx = StateTransaction(state)
    try:
        yield tx
    except Exception:
        tx.rollback()
        raise

"""
State Store
===========

One API over a story's declared state, whatever it is physically made of.

``StateStore`` is the layer that lets an engine module, a skill, or an agent say
"raise favor by eight" without knowing whether ``favor`` is a typed attribute
inherited from the flagship or an entry in a generic bag the story invented.
The schema knows; nothing else has to.

ATTRIBUTION LIVES ON THE RECEIPT, NOT HERE. This class used to keep a write
journal -- every write appended a record with who, why, before and after. It was
recorded and discarded: ``store_for()`` builds a fresh store per call, so every
record died the moment its caller returned, and ``clear_journal()`` ("called per
turn, after it has been read") was called by nothing. The two fields that made
it worth having, ``by`` and ``why``, ride out on the effect receipt instead
(``engine/game/effects.py::_e_value``), which is the artifact that actually
survives a turn. What stays here is the enforcement: a value declares its
``owners``, a write by anyone else is refused, and the refusal is logged at
WARNING -- a model repeatedly trying to grant itself favor is a prompt defect,
and it must be visible somewhere durable rather than silently dropped.

WHY WRITES CLAMP RATHER THAN RAISE. A meter is a number with bounds, and a model
proposing 140 on a 0-100 scale means "as high as it goes", not "crash the turn".
The receipt carries ``before``/``after``, so the overshoot is still visible.

Version: v0.2.0 [2026-08-13]
"""

from __future__ import annotations

import logging
from typing import Any

from engine.state.schema import (
    BACKING_FIELD,
    KIND_CLOCK,
    KIND_METER,
    VISIBILITY_PUBLIC,
    VISIBILITY_VEILED,
    StateSchema,
    ValueSpec,
)

logger = logging.getLogger(__name__)

#: The engine itself, for writes that are not any agent's doing (the clock
#: ticking a value, a migration, a test). Always permitted.
WRITER_ENGINE = "engine"


def _resolve_owner(target: Any, path: str) -> tuple[Any, str]:
    """
    Walk a dotted path to the object holding the final attribute.

    ``stats.hp`` returns ``(state.stats, "hp")``. Raises AttributeError on a bad
    path, which surfaces as a schema problem at first use rather than a silent
    zero.
    """
    parts = path.split(".")
    owner = target
    for part in parts[:-1]:
        owner = getattr(owner, part)
    return owner, parts[-1]


class StateStore:
    """
    Read and write a story's declared values.

    Args:
        state: The live GameState. Held by reference -- the store is a view, not
            a copy, so it must never be cached across a rollback.
        schema: The story's declared state.
    """

    def __init__(self, state: Any, schema: StateSchema) -> None:
        self.state = state
        self.schema = schema

    # -- reading ---------------------------------------------------------

    def has(self, name: str) -> bool:
        return name in self.schema

    def get(self, name: str) -> float:
        """
        Current value, or the declared default when unset.

        An undeclared name is a programming error and raises: reading a value no
        story declared should never quietly return zero, because zero is a
        legitimate value for almost every meter in the game.
        """
        spec = self.schema.get(name)
        if spec is None:
            raise KeyError(f"'{name}' is not declared in this story's state schema")

        if spec.backing == BACKING_FIELD:
            owner, attr = _resolve_owner(self.state, spec.path)
            return float(getattr(owner, attr, spec.default))

        return float(self._bag(spec).get(name, spec.default))

    def snapshot(self) -> dict[str, float]:
        """Every declared value, for prompts, telemetry and tests."""
        return {name: self.get(name) for name in self.schema.values}

    # -- writing ---------------------------------------------------------

    def set(
        self,
        name: str,
        value: float,
        *,
        by: str = WRITER_ENGINE,
        why: str = "",
        turn: int = 0,
    ) -> float:
        """
        Write a declared value, clamped to its bounds.

        Args:
            name: Declared value name.
            value: Desired value, before clamping.
            by: Who is writing. ``WRITER_ENGINE`` is always permitted; anyone
                else must appear in the value's declared ``owners``.
            why: Reason. Carried into the refusal log line here; a permitted
                write's reason reaches the player through the effect receipt
                (``effects.py::_e_value``), the artifact that survives a turn.
            turn: Turn number, for the log.

        Returns:
            The value actually stored -- which may differ from ``value`` after
            clamping, and equals the previous value if the write was refused.
        """
        spec = self.schema.get(name)
        if spec is None:
            raise KeyError(f"'{name}' is not declared in this story's state schema")

        before = self.get(name)

        if by != WRITER_ENGINE and not spec.writable_by(by):
            # Refused, and LOGGED. Silently dropping this would hide exactly
            # the behaviour worth seeing: a model repeatedly trying to move a
            # value it does not own is a prompt defect.
            logger.warning(
                "[state] Write refused, agent does not own this value "
                "(operation=set, name=%s, by=%s, why=%s, turn=%s, owners=%s)",
                name,
                by,
                why,
                turn,
                list(spec.owners),
            )
            return before

        wanted = float(value)
        after = spec.clamp(wanted)

        if spec.backing == BACKING_FIELD:
            owner, attr = _resolve_owner(self.state, spec.path)
            current = getattr(owner, attr, spec.default)
            # Preserve the attribute's existing type: hp is an int and the rest
            # of the engine indexes and formats it as one.
            setattr(owner, attr, int(after) if isinstance(current, int) else after)
        else:
            self._bag(spec)[name] = after

        return after

    def adjust(
        self,
        name: str,
        delta: float,
        *,
        by: str = WRITER_ENGINE,
        why: str = "",
        turn: int = 0,
    ) -> float:
        """Move a value by a delta. The common case; everything else is set."""
        return self.set(name, self.get(name) + float(delta), by=by, why=why, turn=turn)

    # -- projection ------------------------------------------------------

    def to_client(self) -> dict[str, Any]:
        """
        What the browser is allowed to know, projected from the schema.

        Replaces guessing. The client contract used to be three independent
        hardcoded lists, so a story could not show the player a value the engine
        had not been taught about; here a story declares visibility once and
        this follows.

        A veiled value ships its band and NEVER its number -- that is the
        difference between a meter the player reads as a rose opening and one
        they read as 63/100.
        """
        out: dict[str, Any] = {}
        for spec in self.schema.client_visible():
            value = self.get(spec.name)
            row: dict[str, Any] = {
                "name": spec.name,
                "label": spec.display_label,
                "kind": spec.kind,
            }
            if spec.visibility == VISIBILITY_PUBLIC:
                row["value"] = value
                if spec.minimum is not None:
                    row["min"] = spec.minimum
                if spec.maximum is not None:
                    row["max"] = spec.maximum
            elif spec.visibility == VISIBILITY_VEILED:
                row["band"] = spec.band(value)
            out[spec.name] = row
        return out

    # -- internals -------------------------------------------------------

    def _bag(self, spec: ValueSpec) -> dict[str, float]:
        """
        The generic container a bag-backed value lives in.

        Kept per kind rather than one flat dict so a save is readable and a
        clock cannot silently collide with a meter of the same name.
        """
        if spec.kind == KIND_CLOCK:
            return self.state.clocks
        if spec.kind == KIND_METER:
            return self.state.meters
        return self.state.tracks


__all__ = ["WRITER_ENGINE", "StateStore"]

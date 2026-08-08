"""
State Store
===========

One API over a story's declared state, whatever it is physically made of.

``StateStore`` is the layer that lets an engine module, a skill, or an agent say
"raise favor by eight" without knowing whether ``favor`` is a typed attribute
inherited from the flagship or an entry in a generic bag the story invented.
The schema knows; nothing else has to.

WHY A WRITE JOURNAL. Today nothing records WHICH agent changed a value or why.
The receipts carry the skill, the args and the result -- not the caller -- so
"the companion moved a stat it should not be able to touch" is not a question
the engine can answer. The journal makes every write attributable, and it is the
enforcement point for per-agent field ACLs: a value declares its ``owners``, and
a write by anyone else is refused AND recorded. Recording the refusal matters
more than the refusal: a model repeatedly trying to grant itself favor is a
prompt defect, and it is invisible if you only ever drop the attempt.

WHY WRITES CLAMP RATHER THAN RAISE. A meter is a number with bounds, and a model
proposing 140 on a 0-100 scale means "as high as it goes", not "crash the turn".
The clamp is recorded in the journal so the overshoot is still visible.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

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


@dataclass
class WriteRecord:
    """One attempted write, permitted or not."""

    name: str
    before: float
    after: float
    by: str
    why: str = ""
    turn: int = 0
    clamped: bool = False
    refused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "before": self.before,
            "after": self.after,
            "by": self.by,
            "why": self.why,
            "turn": self.turn,
            "clamped": self.clamped,
            "refused": self.refused,
        }


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
        self.journal: list[WriteRecord] = []

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
        Write a declared value, clamped to its bounds and recorded.

        Args:
            name: Declared value name.
            value: Desired value, before clamping.
            by: Who is writing. ``WRITER_ENGINE`` is always permitted; anyone
                else must appear in the value's declared ``owners``.
            why: Reason, recorded. Cheap to pass and the only thing that makes
                the journal readable after the fact.
            turn: Turn number, for the journal.

        Returns:
            The value actually stored -- which may differ from ``value`` after
            clamping, and equals the previous value if the write was refused.
        """
        spec = self.schema.get(name)
        if spec is None:
            raise KeyError(f"'{name}' is not declared in this story's state schema")

        before = self.get(name)

        if by != WRITER_ENGINE and not spec.writable_by(by):
            # Refused, and RECORDED. Silently dropping this would hide exactly
            # the behaviour worth seeing.
            self.journal.append(
                WriteRecord(
                    name=name, before=before, after=before, by=by,
                    why=why, turn=turn, refused=True,
                )
            )
            logger.warning(
                "[state] Write refused, agent does not own this value "
                "(operation=set, name=%s, by=%s, owners=%s)",
                name,
                by,
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

        self.journal.append(
            WriteRecord(
                name=name, before=before, after=after, by=by, why=why,
                turn=turn, clamped=after != wanted,
            )
        )
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

    def refusals(self) -> list[WriteRecord]:
        """Writes that were turned away. The interesting half of the journal."""
        return [record for record in self.journal if record.refused]

    def clear_journal(self) -> None:
        """Drop the journal. Called per turn, after it has been read."""
        self.journal.clear()

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


__all__ = ["WRITER_ENGINE", "StateStore", "WriteRecord"]

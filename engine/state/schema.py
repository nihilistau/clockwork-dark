"""
Story State Schema
==================

What a story's state IS, declared as data instead of as a Python dataclass.

THE PROBLEM THIS SOLVES. ``GameState`` is a fixed dataclass carrying ``hp``,
``stamina``, ``hunger``, ``wounds``, ``evil_phase``, ``awareness`` and a procgen
result. That is one story's answer, welded into the engine. A story with eight
0-100 meters, four 0-5 progress clocks and nine per-NPC relationship records has
nowhere to put any of it -- ``flags`` is booleans only -- and simultaneously
inherits a dozen fields it will never read. The multi-game layer could repoint
content files and nothing else, so a second story could only ever be the first
one with different nouns.

BACKING IS THE MIGRATION STRATEGY, and it is the only reason this is safe to
land at all. Every value declares where it physically lives:

    backing: field   an existing typed attribute, addressed by a dotted path
                     (``stats.hp``). Nothing moves, nothing breaks, and the
                     ~10 modules that say ``state.stats.hp`` today keep saying
                     it. This is how The Clockwork Dark is described rather
                     than rewritten.

    backing: bag     a schema-declared entry in the generic ``meters`` /
                     ``clocks`` / ``tracks`` containers on the spine. A story
                     the engine has never heard of uses these exclusively.

Both are reached through one ``StateStore`` API, so callers cannot tell the
difference. A Clockwork field can be flipped from ``field`` to ``bag`` later,
one at a time, each flip a small change with its own proof -- instead of one
big-bang rewrite of the state model with 949 tests hanging off it.

VISIBILITY is declared here because the client contract was three independent
hardcoded lists (``to_client_dict``'s 21-key allowlist, the ``turn_update`` dict
literal, and the reducer's own shape). A story could not show the player a
number the engine did not already know about. Now the schema says what is
player-facing and the payload is projected from it.

    public   sent to the browser as a number
    veiled   sent as a coarse band, never as an integer -- the Garden's rule
             that meters are read as bloom and vine, not as 63/100
    hidden   never leaves the server; the player meets it as fiction

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

BACKING_FIELD = "field"
BACKING_BAG = "bag"
BACKINGS = (BACKING_FIELD, BACKING_BAG)

VISIBILITY_PUBLIC = "public"
VISIBILITY_VEILED = "veiled"
VISIBILITY_HIDDEN = "hidden"
VISIBILITIES = (VISIBILITY_PUBLIC, VISIBILITY_VEILED, VISIBILITY_HIDDEN)

KIND_METER = "meter"
KIND_CLOCK = "clock"
KIND_TRACK = "track"
KINDS = (KIND_METER, KIND_CLOCK, KIND_TRACK)

#: Bands a veiled meter collapses to, low to high. Deliberately five: enough to
#: feel movement, few enough that a player cannot reverse-engineer the integer.
VEILED_BANDS: tuple[str, ...] = ("none", "faint", "some", "strong", "utmost")


class SchemaError(ValueError):
    """A story's state declaration is unusable. Raised at load, never mid-turn."""


@dataclass(frozen=True)
class ValueSpec:
    """
    One declared piece of story state.

    Attributes:
        name: Key the rest of the engine addresses this by.
        kind: meter | clock | track.
        backing: Where the value physically lives -- see the module docstring.
        path: Dotted attribute path, ``backing: field`` only.
        minimum / maximum: Clamp bounds. ``None`` means unbounded on that side.
        default: Starting value.
        visibility: public | veiled | hidden.
        label: Player-facing name. Falls back to a de-underscored ``name``.
        owners: Agent ids permitted to write this. Empty means engine-only,
            which is the safe default -- a story must say a value is
            agent-writable, rather than forgetting to say it is not.
    """

    name: str
    kind: str = KIND_METER
    backing: str = BACKING_BAG
    path: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    default: float = 0.0
    visibility: str = VISIBILITY_PUBLIC
    label: str = ""
    owners: tuple[str, ...] = ()

    @property
    def display_label(self) -> str:
        return self.label or self.name.replace("_", " ").title()

    def clamp(self, value: float) -> float:
        """Bring a value inside its declared bounds."""
        if self.minimum is not None:
            value = max(self.minimum, value)
        if self.maximum is not None:
            value = min(self.maximum, value)
        return value

    def band(self, value: float) -> str:
        """
        Coarse label for a veiled value.

        Needs both bounds: without them there is no scale to place the number
        on, and inventing one would make the band lie. An unbounded veiled value
        reports "some" rather than guessing.
        """
        if self.minimum is None or self.maximum is None:
            return VEILED_BANDS[len(VEILED_BANDS) // 2]
        span = float(self.maximum) - float(self.minimum)
        if span <= 0:
            return VEILED_BANDS[0]
        ratio = (float(value) - float(self.minimum)) / span
        index = int(ratio * len(VEILED_BANDS))
        return VEILED_BANDS[min(max(index, 0), len(VEILED_BANDS) - 1)]

    def writable_by(self, agent: str) -> bool:
        return agent in self.owners


@dataclass
class StateSchema:
    """Every declared value for one story, plus the story's own identity."""

    slug: str = ""
    version: int = 1
    values: dict[str, ValueSpec] = field(default_factory=dict)
    #: Declared value names the load menu shows on a save row, in order.
    #: Declared HERE rather than in the manifest because it names values that
    #: are defined here -- a column list living in a different file from the
    #: values it references is a rename waiting to break silently.
    summary: tuple[str, ...] = ()

    def __contains__(self, name: str) -> bool:
        return name in self.values

    def get(self, name: str) -> Optional[ValueSpec]:
        return self.values.get(name)

    def of_kind(self, kind: str) -> list[ValueSpec]:
        return [v for v in self.values.values() if v.kind == kind]

    @property
    def bag_backed(self) -> list[ValueSpec]:
        return [v for v in self.values.values() if v.backing == BACKING_BAG]

    @property
    def field_backed(self) -> list[ValueSpec]:
        return [v for v in self.values.values() if v.backing == BACKING_FIELD]

    def client_visible(self) -> list[ValueSpec]:
        """Everything the browser is allowed to know about, in declared order."""
        return [
            v for v in self.values.values() if v.visibility != VISIBILITY_HIDDEN
        ]


def _spec_from_raw(name: str, raw: Any, kind: str) -> ValueSpec:
    """Build one spec, failing loudly rather than guessing."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SchemaError(f"{kind} '{name}' must be a mapping, got {type(raw).__name__}")

    backing = str(raw.get("backing", BACKING_BAG))
    if backing not in BACKINGS:
        raise SchemaError(
            f"{kind} '{name}' declares backing '{backing}'; expected one of {BACKINGS}"
        )

    path = str(raw.get("path", "") or "")
    if backing == BACKING_FIELD and not path:
        # The whole point of `field` backing is the address. Without it the
        # store would silently fall through to the bag and the story would read
        # zeros where it expected the engine's real value.
        raise SchemaError(f"{kind} '{name}' has backing 'field' but no 'path'")

    visibility = str(raw.get("visibility", VISIBILITY_PUBLIC))
    if visibility not in VISIBILITIES:
        raise SchemaError(
            f"{kind} '{name}' declares visibility '{visibility}'; "
            f"expected one of {VISIBILITIES}"
        )

    minimum = raw.get("min")
    maximum = raw.get("max")
    if minimum is not None and maximum is not None and float(minimum) > float(maximum):
        raise SchemaError(f"{kind} '{name}' has min {minimum} above max {maximum}")

    owners = raw.get("owners") or ()
    if isinstance(owners, str):
        owners = (owners,)

    return ValueSpec(
        name=name,
        kind=kind,
        backing=backing,
        path=path,
        minimum=None if minimum is None else float(minimum),
        maximum=None if maximum is None else float(maximum),
        default=float(raw.get("default", 0.0)),
        visibility=visibility,
        label=str(raw.get("label", "") or ""),
        owners=tuple(str(o) for o in owners),
    )


def parse_schema(data: dict[str, Any], *, slug: str = "") -> StateSchema:
    """
    Build a schema from an already-loaded mapping.

    Args:
        data: The parsed ``state.yaml`` body.
        slug: Story slug, for error messages.

    Returns:
        A validated StateSchema.

    Raises:
        SchemaError: On any malformed declaration. This is deliberately fatal
            and deliberately at load time -- a story whose state does not parse
            must refuse to start, not discover it three turns in.
    """
    if not isinstance(data, dict):
        raise SchemaError(f"state schema for '{slug}' is not a mapping")

    schema = StateSchema(slug=slug or str(data.get("slug", "")), version=int(data.get("version", 1)))

    for kind, block_key in ((KIND_METER, "meters"), (KIND_CLOCK, "clocks"), (KIND_TRACK, "tracks")):
        block = data.get(block_key) or {}
        if not isinstance(block, dict):
            raise SchemaError(f"'{block_key}' for '{slug}' must be a mapping")
        for name, raw in block.items():
            key = str(name)
            if key in schema.values:
                raise SchemaError(
                    f"'{key}' is declared twice in the state schema for '{slug}'"
                )
            schema.values[key] = _spec_from_raw(key, raw, kind)

    # Load-menu columns. Validated here, at load, because the failure is
    # otherwise invisible until someone opens the save browser -- and a column
    # naming a hidden value is a leak, not a typo.
    raw_summary = data.get("summary") or ()
    if isinstance(raw_summary, str):
        raw_summary = (raw_summary,)
    summary: list[str] = []
    for name in raw_summary:
        key = str(name)
        spec = schema.values.get(key)
        if spec is None:
            raise SchemaError(
                f"summary column '{key}' for '{slug}' is not a declared value"
            )
        if spec.visibility == VISIBILITY_HIDDEN:
            raise SchemaError(
                f"summary column '{key}' for '{slug}' is hidden; the load menu "
                f"is a screen the player reads"
            )
        summary.append(key)
    schema.summary = tuple(summary)

    logger.info(
        "[state] Schema parsed (operation=parse_schema, slug=%s, values=%d, "
        "field_backed=%d, bag_backed=%d)",
        schema.slug or "?",
        len(schema.values),
        len(schema.field_backed),
        len(schema.bag_backed),
    )
    return schema


def load_schema(path: Path | str, *, slug: str = "") -> StateSchema:
    """
    Read and validate a story's ``state.yaml``.

    A missing file is NOT an error: it means the story declares no state of its
    own and runs on the engine spine alone. That is the correct behaviour for
    the flagship before it has been described, and it keeps this layer additive.
    """
    source = Path(path)
    if not source.is_file():
        logger.debug(
            "[state] No state schema, running on the spine "
            "(operation=load_schema, path=%s)",
            source,
        )
        return StateSchema(slug=slug)

    try:
        with source.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SchemaError(f"could not read state schema at {source}: {exc}") from exc

    return parse_schema(data, slug=slug)


__all__ = [
    "BACKINGS",
    "BACKING_BAG",
    "BACKING_FIELD",
    "KINDS",
    "KIND_CLOCK",
    "KIND_METER",
    "KIND_TRACK",
    "VEILED_BANDS",
    "VISIBILITIES",
    "VISIBILITY_HIDDEN",
    "VISIBILITY_PUBLIC",
    "VISIBILITY_VEILED",
    "SchemaError",
    "StateSchema",
    "ValueSpec",
    "load_schema",
    "parse_schema",
]

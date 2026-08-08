"""
Boundary Sheet
==============

The data a player and a story fill in, and the only thing in this engine that
sits ABOVE both agents.

    hard nos      never write this. No motivation reaches past it.
    soft nos      the player would rather not. Fade it, or rename it.
    green lights  explicitly welcome. Lifts a soft no. Never lifts a hard one.

THE STRUCTURAL CLAIM. ``docs/design/agents/STATE-BOARD.md`` states the rule as
"Sophia character desire NEVER overrides product layer", and the tempting way
to implement that is a sentence in a system prompt. A sentence in a prompt is a
suggestion to a sampler. This module makes it a property of the type instead:

  * ``BoundarySheet`` is frozen. Nothing removes a limit from one.
  * ``merged_with`` is MONOTONE on hard nos -- merging two sheets can only ever
    produce a superset. There is no subtract, no ``without``, no ``clear``.
  * ``green_lights`` are filtered against the merged limit topics on the way
    in, so a story (or anything downstream of a model) cannot green-light a
    topic the player has said no to. It is not that we decline to honour it --
    the value does not survive construction.

A character can therefore want anything it likes. The want has no API to reach.

WHY ``substitute`` IS SOFT-ONLY. ``docs/design/scenes/DAY-01-GUEST.md:152``
wants an item to rename itself when its noun lands on a player limit -- "same
mechanics, cosmetic rename from boundaries". That is right for a soft no, which
is about a word the player does not want to read. It is exactly wrong for a
hard no, which is about a thing that must not happen: honouring a substitute
there would generate the content and launder the label. So a ``substitute``
declared on a hard no is dropped, and said so in the log.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Optional

from engine.safety.tiers import LOWEST, TIER_ORDER, IntensityTier

logger = logging.getLogger(__name__)

#: Severity names as they appear in YAML.
HARD = "hard"
SOFT = "soft"


@lru_cache(maxsize=512)
def _pattern(nouns: tuple[str, ...]) -> Optional[re.Pattern[str]]:
    """
    Compile one limit's nouns into a single alternation.

    Lookarounds rather than ``\\b`` because a noun may legally start or end on
    a non-word character ("age-play", "self-harm"), and ``\\b`` next to a
    hyphen matches in the wrong place. Longest first so "blood magic" wins over
    "blood" when both are listed and the report should name the specific one.

    Cached because the same sheet is matched against every beat of every turn,
    and recompiling per call would put a regex build inside the narration path.
    """
    cleaned = sorted(
        {n.strip().lower() for n in nouns if str(n).strip()},
        key=len,
        reverse=True,
    )
    if not cleaned:
        return None
    body = "|".join(re.escape(n) for n in cleaned)
    try:
        return re.compile(rf"(?<!\w)({body})(?!\w)", re.IGNORECASE)
    except re.error as exc:  # pragma: no cover -- escape() makes this unreachable
        logger.warning(
            "[safety] Limit nouns would not compile, limit is inert "
            "(operation=_pattern, nouns=%s): %s",
            cleaned,
            exc,
        )
        return None


def _match_case(sample: str, replacement: str) -> str:
    """
    Give a replacement the case shape of the text it replaces.

    "Collar" -> "Throat-garland", "COLLAR" -> "THROAT-GARLAND". Without this a
    cosmetic rename produces "a Collar of Soft Thorns" becoming "a
    throat-garland of Soft Thorns" mid-title, and the seam shows -- which is
    the one thing a COSMETIC substitution must not do.
    """
    if sample.isupper() and len(sample) > 1:
        return replacement.upper()
    if sample[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


@dataclass(frozen=True)
class Limit:
    """
    One boundary entry.

    Attributes:
        topic: Stable id. This is what appears in logs, telemetry and a
            verdict's reasons -- never in player-facing prose, because the
            player already knows what they wrote and the character must not
            recite it back (SOPHIA-VOICE-BIBLE.md:98).
        nouns: Surface forms that indicate the topic. Matched with word
            boundaries, case-insensitively. A limit with no nouns is inert and
            matches nothing; that is legal, and is how a topic is declared for
            an agent directive without also becoming a text filter.
        substitute: Cosmetic replacement noun. Honoured on soft nos only.
        note: Why, in the author's words. For the log, never for the player.
    """

    topic: str
    nouns: tuple[str, ...] = ()
    substitute: str = ""
    note: str = ""

    @classmethod
    def parse(cls, raw: Any, *, source: str = "") -> Optional["Limit"]:
        """
        Build a limit from YAML, never raising.

        Two shapes are legal, because both are things an author reasonably
        writes:

            - "self-harm"                     a bare string; topic and noun
            - {topic: collars, nouns: [...]}  the full form

        Returns:
            A Limit, or None when the entry carries no topic at all -- an
            unnamed limit cannot be reported on, and silently keeping it would
            produce log lines nobody can act on.
        """
        if isinstance(raw, Limit):
            return raw
        if isinstance(raw, str):
            topic = raw.strip()
            if not topic:
                return None
            return cls(topic=topic.lower(), nouns=(topic,))
        if not isinstance(raw, dict):
            logger.warning(
                "[safety] Limit is neither a string nor a mapping, dropping "
                "(operation=Limit.parse, value=%r, source=%s)",
                raw,
                source or "unknown",
            )
            return None

        topic = str(raw.get("topic") or raw.get("id") or "").strip().lower()
        if not topic:
            logger.warning(
                "[safety] Limit has no topic, dropping "
                "(operation=Limit.parse, source=%s)",
                source or "unknown",
            )
            return None

        raw_nouns = raw.get("nouns") or raw.get("words") or ()
        if isinstance(raw_nouns, str):
            raw_nouns = (raw_nouns,)
        nouns = tuple(
            str(n).strip() for n in raw_nouns if str(n).strip()
        ) if isinstance(raw_nouns, (list, tuple)) else ()

        return cls(
            topic=topic,
            nouns=nouns,
            substitute=str(raw.get("substitute") or "").strip(),
            note=str(raw.get("note") or "").strip(),
        )

    # -- matching ---------------------------------------------------------

    def hits(self, text: str) -> tuple[str, ...]:
        """Surface forms of this limit found in ``text``, in order of appearance."""
        pattern = _pattern(self.nouns)
        if pattern is None or not text:
            return ()
        seen: list[str] = []
        for match in pattern.finditer(text):
            found = match.group(1)
            if found not in seen:
                seen.append(found)
        return tuple(seen)

    def matches(self, text: str) -> bool:
        """True when any of this limit's nouns appears in ``text``."""
        return bool(self.hits(text))


@dataclass(frozen=True)
class BoundarySheet:
    """
    One session's limits. Frozen, and only ever grows.

    Attributes:
        hard_nos: Never generated. No tier, no motivation and no green light
            reaches past these.
        soft_nos: Faded or cosmetically substituted rather than written.
        green_lights: Topics the player has explicitly welcomed. Suppress a
            soft no of the same topic. Filtered against hard nos on
            construction, so the pairing cannot exist in a built sheet.
    """

    hard_nos: tuple[Limit, ...] = ()
    soft_nos: tuple[Limit, ...] = ()
    green_lights: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Construction-time filter, not a check at read time. A green light
        # that survives into the object is a green light some later reader can
        # honour by accident; one that never survives cannot be.
        #
        # Only HARD nos cancel a green light here. A sheet that names a topic
        # in both `soft_nos` and `green_lights` is one author saying "usually
        # not, but yes for me", and the green light wins -- that is the whole
        # job of a green light. The cross-LAYER case, where a story green-lit
        # what a player later said no to, is resolved in ``merged_with``.
        blocked = {limit.topic for limit in self.hard_nos}
        kept = tuple(
            g for g in self.green_lights if g.strip().lower() not in blocked
        )
        if len(kept) != len(self.green_lights):
            dropped = sorted(set(self.green_lights) - set(kept))
            logger.info(
                "[safety] Green light dropped, topic is a hard no "
                "(operation=BoundarySheet, topics=%s)",
                dropped,
            )
        object.__setattr__(self, "green_lights", kept)

    # -- construction -----------------------------------------------------

    @classmethod
    def from_mapping(cls, raw: Any, *, source: str = "") -> "BoundarySheet":
        """
        Read a sheet from a config or manifest block, never raising.

            boundaries:
              hard_nos: [...]
              soft_nos: [...]
              green_lights: [...]

        Anything unreadable produces an EMPTY sheet rather than a partial one
        the author would not recognise -- with a warning, because a boundary
        block that silently did nothing is the worst failure this file has.
        """
        if not isinstance(raw, dict):
            if raw:
                logger.warning(
                    "[safety] boundaries block is not a mapping, ignoring "
                    "(operation=from_mapping, source=%s)",
                    source or "unknown",
                )
            return EMPTY_SHEET

        def _limits(key: str, *, allow_substitute: bool) -> tuple[Limit, ...]:
            rows = raw.get(key) or ()
            if isinstance(rows, str):
                rows = (rows,)
            if not isinstance(rows, (list, tuple)):
                logger.warning(
                    "[safety] boundaries.%s is not a list, ignoring "
                    "(operation=from_mapping, source=%s)",
                    key,
                    source or "unknown",
                )
                return ()
            out: list[Limit] = []
            for row in rows:
                limit = Limit.parse(row, source=f"{source}.{key}" if source else key)
                if limit is None:
                    continue
                if limit.substitute and not allow_substitute:
                    # See the module docstring: renaming a hard no generates it
                    # under another word.
                    logger.warning(
                        "[safety] substitute ignored on a hard no "
                        "(operation=from_mapping, topic=%s, source=%s)",
                        limit.topic,
                        source or "unknown",
                    )
                    limit = Limit(
                        topic=limit.topic, nouns=limit.nouns, note=limit.note
                    )
                out.append(limit)
            return tuple(out)

        greens_raw = raw.get("green_lights") or ()
        if isinstance(greens_raw, str):
            greens_raw = (greens_raw,)
        greens = tuple(
            str(g).strip().lower()
            for g in (greens_raw if isinstance(greens_raw, (list, tuple)) else ())
            if str(g).strip()
        )

        return cls(
            hard_nos=_limits("hard_nos", allow_substitute=False),
            soft_nos=_limits("soft_nos", allow_substitute=True),
            green_lights=greens,
        )

    def merged_with(self, other: Optional["BoundarySheet"]) -> "BoundarySheet":
        """
        Union with another sheet. Monotone on limits, by construction.

        There is no operation on this class that produces FEWER hard nos than
        it was given. That is the whole enforcement of "meta-consent is
        absolute" -- a config layer, a story manifest and a player's own sheet
        stack, and stacking is the only verb.

        ``other`` is the HIGHER-authority layer -- the same "later wins"
        ordering ``engine/config.py`` uses for its YAML layers, and the reason
        ``policy.resolve`` merges config, then the story, then the player. So a
        green light in ``other`` lifts a soft no from ``self`` (a player may
        welcome what a story is cautious about), and a soft no in ``other``
        cancels a green light from ``self`` (a story may not welcome what a
        player has said no to).

        A green light never touches a hard no from either side. That rule has
        no layer ordering, because "meta-consent is absolute" does not have one.
        """
        if other is None:
            return self

        def _union(left: tuple[Limit, ...], right: tuple[Limit, ...]) -> tuple[Limit, ...]:
            by_topic: dict[str, Limit] = {}
            for limit in (*left, *right):
                existing = by_topic.get(limit.topic)
                if existing is None:
                    by_topic[limit.topic] = limit
                    continue
                # Same topic declared twice: keep every noun from both, and
                # keep a substitute if either side offered one. Union again --
                # the merge must not be able to narrow a limit.
                by_topic[limit.topic] = Limit(
                    topic=limit.topic,
                    nouns=tuple(dict.fromkeys((*existing.nouns, *limit.nouns))),
                    substitute=existing.substitute or limit.substitute,
                    note=existing.note or limit.note,
                )
            return tuple(by_topic.values())

        hard = _union(self.hard_nos, other.hard_nos)
        soft = _union(self.soft_nos, other.soft_nos)
        # The later layer's limits cancel the earlier layer's green lights; the
        # later layer's own green lights survive. BoundarySheet.__post_init__
        # then drops anything a hard no named, from either side.
        later_topics = {l.topic for l in other.hard_nos} | {
            l.topic for l in other.soft_nos
        }
        greens = tuple(
            dict.fromkeys(
                (
                    *(g for g in self.green_lights if g not in later_topics),
                    *other.green_lights,
                )
            )
        )
        return BoundarySheet(hard_nos=hard, soft_nos=soft, green_lights=greens)

    # -- queries ----------------------------------------------------------

    @property
    def empty(self) -> bool:
        """True when this sheet has nothing to enforce."""
        return not (self.hard_nos or self.soft_nos or self.green_lights)

    @property
    def topics(self) -> tuple[str, ...]:
        """Every limit topic, hard first. For a directive block and for logs."""
        return tuple(l.topic for l in self.hard_nos) + tuple(
            l.topic for l in self.soft_nos
        )

    def hard_hits(self, text: str) -> tuple[Limit, ...]:
        """Hard limits present in ``text``. Green lights are not consulted."""
        if not text:
            return ()
        return tuple(l for l in self.hard_nos if l.matches(text))

    def soft_hits(self, text: str) -> tuple[Limit, ...]:
        """
        Soft limits present in ``text``, minus anything green-lit.

        A green light lifts a soft no of the same topic and nothing else. The
        hard list is not reachable from here at all -- there is no parameter
        that would make it so.
        """
        if not text:
            return ()
        greens = set(self.green_lights)
        return tuple(
            l for l in self.soft_nos if l.topic not in greens and l.matches(text)
        )

    def substitutions(self, text: str) -> dict[str, str]:
        """
        Cosmetic renames this sheet asks for in ``text``.

        Keys are the surface forms actually found, values the replacement in
        the same case shape. Only soft limits contribute, and only those that
        declared a substitute -- a soft no with no substitute wants a fade, not
        a euphemism.
        """
        out: dict[str, str] = {}
        greens = set(self.green_lights)
        for limit in self.soft_nos:
            if not limit.substitute or limit.topic in greens:
                continue
            for found in limit.hits(text):
                out[found] = _match_case(found, limit.substitute)
        return out

    def rename(self, text: str) -> str:
        """
        Apply this sheet's cosmetic substitutions to a DISPLAY string.

        Takes and returns display text only. There is deliberately no overload
        that accepts an item id, a location id or an effect payload: the
        mechanics of a renamed thing must be bit-identical to the mechanics of
        the thing, and the simplest way to guarantee that is for the renaming
        function to be incapable of seeing an id.
        """
        result = text
        for found, replacement in self.substitutions(text).items():
            result = re.sub(
                rf"(?<!\w){re.escape(found)}(?!\w)", replacement, result
            )
        return result


#: The sheet a session with no configured boundaries gets. Shared because it is
#: immutable and because identity makes the "nothing configured" test cheap.
EMPTY_SHEET = BoundarySheet()


@dataclass(frozen=True)
class TierMarkers:
    """
    Surface forms that say "this text is at least this intense".

    The ceiling check needs to know what tier a piece of content IS. Two things
    can tell it: the caller declares one (a scene's rating, an agent's brief),
    or the text itself carries markers. This is the second, and it exists so a
    caller that declares nothing -- or an agent that understates -- is still
    measured against something.

    SHIPPED EMPTY, ON PURPOSE. Filling this in means writing down the words
    that indicate explicit content, and those words are the story owner's to
    write, not the engine's. What ships is the mechanism and the data shape;
    ``config/default.yaml`` declares the key with empty lists so the seam is
    visible and so turning it on is a config edit rather than a code change.

    An empty markers set is not a hole in the ceiling: an unmarked policy still
    enforces the tier the CALLER declares, and still enforces every hard no.
    """

    by_tier: tuple[tuple[IntensityTier, Limit], ...] = ()

    @property
    def empty(self) -> bool:
        return not any(limit.nouns for _, limit in self.by_tier)

    @classmethod
    def from_mapping(cls, raw: Any, *, source: str = "") -> "TierMarkers":
        """
        Read ``{explicit: [...], extreme: [...]}``, never raising.

        Unknown tier names are dropped with a warning rather than guessed at --
        a marker list filed under a tier that does not exist would silently
        never fire, which is the failure mode this package is written against.
        """
        if not isinstance(raw, dict):
            if raw:
                logger.warning(
                    "[safety] tier_markers block is not a mapping, ignoring "
                    "(operation=TierMarkers.from_mapping, source=%s)",
                    source or "unknown",
                )
            return NO_MARKERS

        rows: list[tuple[IntensityTier, Limit]] = []
        for key, value in raw.items():
            name = str(key).strip().lower()
            tier = next((t for t in TIER_ORDER if t.value == name), None)
            if tier is None:
                logger.warning(
                    "[safety] tier_markers names an unknown tier, dropping "
                    "(operation=TierMarkers.from_mapping, tier=%r, source=%s)",
                    key,
                    source or "unknown",
                )
                continue
            nouns = (value,) if isinstance(value, str) else value
            if not isinstance(nouns, (list, tuple)):
                continue
            cleaned = tuple(str(n).strip() for n in nouns if str(n).strip())
            if cleaned:
                rows.append((tier, Limit(topic=f"tier:{tier.value}", nouns=cleaned)))
        # Highest first, so tier_of stops at the strongest signal.
        rows.sort(key=lambda row: row[0].rank, reverse=True)
        return cls(by_tier=tuple(rows)) if rows else NO_MARKERS

    def tier_of(self, text: str, *, floor: IntensityTier = LOWEST) -> IntensityTier:
        """
        The highest tier whose markers appear in ``text``, or ``floor``.

        Args:
            text: What is about to be written, or was written.
            floor: The tier the caller already declared. The answer is never
                below it -- markers may only ever raise the estimate, so a
                caller's own declaration cannot be talked down by the absence
                of a word.
        """
        if not text:
            return floor
        for tier, limit in self.by_tier:
            if tier > floor and limit.matches(text):
                return tier
        return floor


#: Markers for a session that configured none. Shared and immutable.
NO_MARKERS = TierMarkers()


def sheet_from_limits(
    *,
    hard: Iterable[Any] = (),
    soft: Iterable[Any] = (),
    green: Iterable[str] = (),
) -> BoundarySheet:
    """Convenience builder for tests and for code holding loose values."""
    return BoundarySheet.from_mapping(
        {
            "hard_nos": list(hard),
            "soft_nos": list(soft),
            "green_lights": list(green),
        },
        source="sheet_from_limits",
    )


__all__ = [
    "EMPTY_SHEET",
    "HARD",
    "NO_MARKERS",
    "SOFT",
    "BoundarySheet",
    "Limit",
    "TierMarkers",
    "sheet_from_limits",
]

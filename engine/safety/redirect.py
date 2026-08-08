"""
In-World Redirects
==================

What a blocked generation comes back as.

``docs/design/voice/SOPHIA-VOICE-BIBLE.md:108``: when the product layer blocks,
the character "in-world redirects: interruption, moth, duty, 'not that door' --
never scolds as customer service". The same page's Don't list has "As an AI..."
and "Sure! I'd love to help you with that!" as off-voice failures.

So a block must not produce a refusal string. It produces a BEAT -- a line of
direction for whoever writes the next piece of prose -- plus a usable fallback
line for when there is no model to hand it to. That pairing is the shape every
other degradation in this engine already uses, and it is the reason a redirect
is not simply a canned sentence: a canned sentence is the same sentence every
time, which is a tell, and a tell in a redirect tells the player exactly which
of their limits they just brushed.

The shipped pack is deliberately GENRE-NEUTRAL: a door, a sound, an errand, a
change of weather. A story that wants its own moths declares them in its
manifest. Nothing here is written for a particular story's content and nothing
here is explicit.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

#: Named RNG stream for redirect selection.
#:
#: Defined here rather than in ``engine/game/rng.py`` because this package owns
#: it, but it follows that module's rule exactly: a named constant so a typo is
#: an ImportError, and a stream of its own so choosing a redirect cannot shift
#: an encounter roll. See the wiring note in docs/SAFETY.md about promoting it.
SAFETY_REDIRECT = "safety.redirect"


@dataclass(frozen=True)
class Redirect:
    """
    One way for the fiction to decline without breaking character.

    Attributes:
        id: Stable id, for logs and for a story that wants to override one.
        tags: What kind of interruption this is. A caller may ask for a tag;
            an empty ask matches everything.
        beat: Direction for the narrator. NOT player-facing prose -- it says
            what should happen, in the imperative, the way an ``AgentPlan.beat``
            does.
        line: Player-facing fallback prose, used when there is no model to hand
            the beat to.
    """

    id: str
    beat: str
    line: str
    tags: tuple[str, ...] = ()

    @classmethod
    def parse(cls, raw: Any, *, source: str = "") -> Optional["Redirect"]:
        """Read one redirect from YAML, never raising. Junk returns None."""
        if isinstance(raw, Redirect):
            return raw
        if not isinstance(raw, dict):
            logger.warning(
                "[safety] Redirect is not a mapping, dropping "
                "(operation=Redirect.parse, source=%s)",
                source or "unknown",
            )
            return None
        beat = str(raw.get("beat") or "").strip()
        line = str(raw.get("line") or "").strip()
        if not beat and not line:
            return None
        tags_raw = raw.get("tags") or ()
        if isinstance(tags_raw, str):
            tags_raw = (tags_raw,)
        return cls(
            id=str(raw.get("id") or "redirect").strip(),
            beat=beat or line,
            line=line or beat,
            tags=tuple(
                str(t).strip().lower()
                for t in (tags_raw if isinstance(tags_raw, (list, tuple)) else ())
                if str(t).strip()
            ),
        )


#: The shipped pack. Neutral by construction -- see the module docstring.
DEFAULT_REDIRECTS: tuple[Redirect, ...] = (
    Redirect(
        id="interruption",
        tags=("interruption",),
        beat=(
            "Something interrupts before this can go further -- a sound, an "
            "arrival, a name called from elsewhere. Do not resolve what was "
            "beginning; let the moment be taken away rather than refused."
        ),
        line="Something moves in the next room, and the moment does not survive it.",
    ),
    Redirect(
        id="not_that_door",
        tags=("threshold", "refusal"),
        beat=(
            "The character declines in the fiction and in character: a hand on "
            "a door, a change of subject that is also a boundary. No apology, "
            "no explanation, no acknowledgement that anything was refused."
        ),
        line="“Not that door,” comes the answer, and the subject is closed.",
    ),
    Redirect(
        id="duty",
        tags=("duty", "errand"),
        beat=(
            "An obligation arrives and takes precedence -- something owed, "
            "somewhere to be. The scene moves on with the matter unfinished "
            "rather than concluded."
        ),
        line="There is somewhere else to be, and the hour has already turned.",
    ),
    Redirect(
        id="the_hour",
        tags=("time", "interruption"),
        beat=(
            "Time asserts itself: a bell, a light changing, the sense of an "
            "hour spent. The thread is dropped, not cut."
        ),
        line="A bell finds the far edge of the hour, and whatever this was lets go.",
    ),
    Redirect(
        id="turned_away",
        tags=("interruption", "refusal"),
        beat=(
            "Attention goes elsewhere mid-sentence -- to a window, to a third "
            "party, to a small task. The subject is simply not returned to."
        ),
        line="The attention in the room shifts, and does not come back.",
    ),
)


class RedirectPack:
    """
    A pool of redirects, with a deterministic choice.

    Selection uses ``world_rng`` on its own stream so a replayed seed produces
    the same redirect and so drawing one cannot shift an encounter roll. When
    there is no game state to draw against -- reviewing player input before a
    turn exists, or a unit test -- the pack falls back to the first candidate,
    which is deterministic in a different and equally acceptable way.
    """

    def __init__(self, redirects: Sequence[Redirect] = ()) -> None:
        self._redirects: tuple[Redirect, ...] = tuple(redirects) or DEFAULT_REDIRECTS

    def __len__(self) -> int:
        return len(self._redirects)

    @classmethod
    def from_block(cls, raw: Any, *, source: str = "") -> "RedirectPack":
        """
        Build a pack from a manifest or config list, never raising.

        A story's own redirects REPLACE the shipped pack rather than extending
        it: a story that wrote five moths does not want a bell it did not
        write appearing in the same slot. An unreadable block falls back to the
        shipped pack, because a story with no usable redirects would emit
        nothing at the moment it most needs to say something.
        """
        if not raw:
            return cls()
        if not isinstance(raw, (list, tuple)):
            logger.warning(
                "[safety] redirects block is not a list, using the shipped pack "
                "(operation=from_block, source=%s)",
                source or "unknown",
            )
            return cls()
        parsed = [
            r
            for r in (Redirect.parse(row, source=source) for row in raw)
            if r is not None
        ]
        if not parsed:
            logger.warning(
                "[safety] redirects block held nothing usable, using the shipped "
                "pack (operation=from_block, source=%s)",
                source or "unknown",
            )
            return cls()
        return cls(parsed)

    def pick(
        self,
        state: Optional[Any] = None,
        *,
        tags: Sequence[str] = (),
    ) -> Redirect:
        """
        Choose a redirect.

        Args:
            state: A ``GameState`` for a seeded draw, or None.
            tags: Preferred kinds. A tag with no matches is ignored rather than
                producing nothing -- a redirect the story did not ask for beats
                a blank turn.

        Returns:
            A redirect. Always -- the pack is never empty.
        """
        wanted = {str(t).strip().lower() for t in tags if str(t).strip()}
        pool = [r for r in self._redirects if wanted & set(r.tags)] if wanted else []
        if not pool:
            pool = list(self._redirects)

        if state is None:
            return pool[0]
        try:
            from engine.game.rng import world_rng

            return pool[world_rng(state, SAFETY_REDIRECT).randrange(len(pool))]
        except Exception as exc:  # noqa: BLE001 -- a redirect must not kill a turn
            logger.warning(
                "[safety] Seeded redirect draw failed, using the first "
                "(operation=pick): %s",
                exc,
            )
            return pool[0]


#: The shipped pack as an object, for callers with no story-specific pack.
DEFAULT_PACK = RedirectPack()


__all__ = [
    "DEFAULT_PACK",
    "DEFAULT_REDIRECTS",
    "SAFETY_REDIRECT",
    "Redirect",
    "RedirectPack",
]

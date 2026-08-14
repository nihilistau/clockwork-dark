"""
Who Is In The Scene
===================

The cast the narrator is allowed to name, and the cast it is not.

THE LEAK THIS CLOSES. The Storyteller persona has carried this line for months:

    Never introduce a named character who is not present in WORLD STATE.

Nothing enforced it. Measured on a fresh run (seed 7, ``forest_clearing``, turn
0, empty ledger) the model wrote:

    "You turn your back on Ilya's lantern and begin walking, keeping low where
     the shadows of the salt-sheds stretch long across the mud..."

Ilya is a real NPC -- the tinker -- and he was nowhere near that clearing. He
came out of the few-shot examples, along with salt-sheds the story does not
have. The turn passed the evaluator and reached the player.

The engine already knows who is present: ``storyteller_turn_schema(npc_ids=...)``
is built from it, which is why ``npc_voices`` cannot name an absent character.
This module hands the same fact to the prose check -- the SAME
``present_npc_ids`` call, not a second notion of presence.

PRECISION OVER RECALL
---------------------
A gate that fails good turns is worse than the leak it plugs, so a name is only
scored as an intrusion when every one of these holds:

* the story has a roster at all (a story with no NPCs contributes nothing, and
  an AGENT companion -- The Wicked Garden's Sophia -- is not an NPC and is
  never in this set);
* the character is not at the player's location this turn;
* the player has never met them, per the ledger. A callback to someone the
  player knows ("the tinker had warned you") is legitimate narration; only an
  INTRODUCTION out of nowhere is the bug;
* the surface form is distinctive -- four characters or more, not an ordinary
  English word, not a crowd id like ``court_generic``, not shared with someone
  who IS present;
* the player did not name them in their own action;
* it appears capitalised, as a whole word, in the prose.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover -- typing only
    from engine.game.state import GameState
    from engine.memory.ledger import StoryLedger

logger = logging.getLogger(__name__)

#: Shortest surface form worth matching. Below this, initials and short names
#: ("Ada", "Bo") collide with ordinary prose more often than they catch a leak.
MIN_NAME_CHARS = 4

#: Ids that name a crowd rather than a character. Their tokens ("bloomkin",
#: "court") are species and place words that legitimately appear in prose.
_CROWD_MARKERS = ("generic", "crowd", "chorus", "villagers", "commoners")

#: Ordinary words that also serve as name parts -- titles, trades and plain
#: nouns. A name whose only distinctive token is one of these contributes
#: nothing on its own: "Mother Briar" is matched whole, but "Mother" alone is
#: not a name sighting, and "Sergeant Sera Venn" is matched on "Sera" rather
#: than on every scene that mentions a sergeant.
_COMMON_WORDS = frozenset(
    {
        "aunt",
        "baker",
        "briar",
        "brother",
        "captain",
        "cook",
        "corporal",
        "court",
        "dame",
        "dark",
        "doctor",
        "elder",
        "father",
        "gate",
        "goodwife",
        "guard",
        "hearth",
        "hunter",
        "keeper",
        "lady",
        "lord",
        "madam",
        "market",
        "mason",
        "master",
        "miller",
        "mistress",
        "mother",
        "priest",
        "sergeant",
        "sister",
        "smith",
        "stranger",
        "tinker",
        "trader",
        "uncle",
        "visitor",
        "warden",
        "watch",
        "widow",
    }
)


def _surface_forms(npc_id: str, display_name: str) -> tuple[str, ...]:
    """
    The written forms a narrator would use for one character.

    The full name, and the first token that is a NAME rather than a title.
    "Sergeant Sera Venn" gives "Sera", not "Sergeant" -- a rank is worn by
    anyone, and matching it would fail a scene about the militia. A name whose
    every token is an ordinary word ("Mother Briar") keeps only its full form.

    Ids are a fallback source because a story may declare a schedule with no
    ``name``: The Wicked Garden's are bare ids (``ashen_vale``), and the engine
    then uses the id as the name.
    """
    raw = display_name.strip() or npc_id
    if raw == npc_id:
        raw = npc_id[4:] if npc_id.startswith("npc_") else npc_id
        raw = raw.replace("_", " ").replace("-", " ").title()

    forms: list[str] = []
    full = " ".join(raw.split())
    if len(full) >= MIN_NAME_CHARS:
        forms.append(full)

    tokens = full.split()
    # "The Archivist", "The Lunch Lady": a role worn as a name. Only the whole
    # form is a sighting -- the remainder is an ordinary noun, and NEON CITY and
    # the dev bench between them field seven of these.
    if tokens and tokens[0].lower() == "the":
        return tuple(forms)

    if len(tokens) > 1:
        # Walk past ranks and honorifics to the given name. Stop at the first
        # token that is distinctive enough to stand alone.
        for token in tokens:
            stripped = token.strip(".,'")
            if len(stripped) >= MIN_NAME_CHARS and stripped.lower() not in _COMMON_WORDS:
                forms.append(stripped)
                break

    # A single-token name that is an ordinary word is not usable at all.
    if len(tokens) == 1 and full.lower() in _COMMON_WORDS:
        return ()
    return tuple(dict.fromkeys(forms))


def _is_crowd(npc_id: str) -> bool:
    lowered = npc_id.lower()
    return any(marker in lowered for marker in _CROWD_MARKERS)


def absent_cast(
    state: "GameState",
    ledger: Optional["StoryLedger"] = None,
) -> dict[str, tuple[str, ...]]:
    """
    Characters the story knows, who are not here, and whom the player has never met.

    Args:
        state: Current game state. Never mutated.
        ledger: Narrative memory, for "have they met". Omitted means nobody has.

    Returns:
        ``{npc_id: (surface forms...)}``. Empty for a story with no NPC roster,
        which is the whole of the story-agnostic contract: no roster, no
        criterion.
    """
    try:
        from engine.memory.context import present_npc_ids
        from engine.world.npc_sim import known_npc_ids, resolve_npc
    except Exception as exc:  # noqa: BLE001 -- a broken import must not cost a turn
        logger.debug("[cast] Roster unavailable (operation=absent_cast): %s", exc)
        return {}

    roster = [npc_id for npc_id in known_npc_ids(state) if not _is_crowd(npc_id)]
    if not roster:
        return {}

    # THE SAME call the turn schema is built from. Two notions of "present"
    # would be worse than none: the prose gate would disagree with the enum.
    present = set(present_npc_ids(state))

    relations = getattr(ledger, "relations", {}) if ledger is not None else {}
    known_names = {n.lower() for n in (getattr(ledger, "names", {}) or {})}

    present_forms: set[str] = set()
    for npc_id in present:
        presence = resolve_npc(state, npc_id)
        present_forms.update(
            form.lower() for form in _surface_forms(npc_id, getattr(presence, "name", ""))
        )

    cast: dict[str, tuple[str, ...]] = {}
    for npc_id in roster:
        if npc_id in present:
            continue
        relation = relations.get(npc_id)
        if relation is not None and getattr(relation, "met", False):
            # Already introduced. Referring back to them is not an intrusion.
            continue
        presence = resolve_npc(state, npc_id)
        forms = tuple(
            form
            for form in _surface_forms(npc_id, getattr(presence, "name", ""))
            # A form shared with someone standing in the room, or already
            # entered in the ledger's name list, cannot be attributed.
            if form.lower() not in present_forms and form.lower() not in known_names
        )
        if forms:
            cast[npc_id] = forms
    return cast


def find_intrusion(
    narration: str,
    cast: dict[str, tuple[str, ...]],
    *,
    player_action: str = "",
) -> Optional[str]:
    """
    The first absent character named in the prose, or None.

    Args:
        narration: What the model wrote.
        cast: ``absent_cast`` output.
        player_action: The player's own words. A character the PLAYER named is
            not an intrusion -- answering "ask about Ilya" by writing Ilya's
            name is the correct behaviour.

    Returns:
        The surface form as it was matched, so the retry can be told which name
        to remove.
    """
    if not narration or not cast:
        return None

    action = player_action.lower()
    for _npc_id, forms in cast.items():
        for form in forms:
            if form.lower() in action:
                continue
            # Case-sensitive on purpose: a name in prose is capitalised, and
            # requiring that keeps ordinary lowercase words out of the gate.
            # \b before an apostrophe still matches "Ilya's lantern".
            if re.search(rf"\b{re.escape(form)}\b", narration):
                return form
    return None


def cast_note(name: str) -> str:
    """The retry's instruction. It has to NAME the character to be actionable."""
    return (
        f"You named {name}, who is not in this scene. WORLD STATE lists everyone "
        f"present; {name} is not among them. Rewrite the narration without "
        f"{name} -- do not move them into the scene, and do not swap in another "
        "name. Use only the people WORLD STATE gives you."
    )

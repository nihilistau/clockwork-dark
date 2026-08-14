"""
Continuity
==========

Narration that contradicts what the world remembers.

WHAT THIS CAN AND CANNOT DO. General contradiction detection needs a model and
would cost a second inference per turn to catch something the first inference
should not have written. This catches the one contradiction the ledger can
PROVE, which is also the one the memory layer exists to prevent:

    **treating somebody as a stranger when the ledger says you have met.**

``SubjectMemory.met`` is a fact, not an opinion. It was set by the engine when
the meeting happened, and the dossier for every present character is in the
prompt (``engine/agents/prompts.py::_dossier``). So a narration that has a met
character introduce themselves, or calls them a stranger, is not a judgement
call about tone -- it is the narrator disagreeing with the save file.

This is deliberately the ONLY continuity rule here. Every other candidate --
"the shutter was broken and is now whole", "she was warm and is now cold" --
requires understanding the prose rather than matching it, and a guard that
guesses would fail correct writing. The cast check next door earns its keep
because absence is provable; this earns its keep for the same reason.

WHY IT IS WORTH A GATE AT ALL. Before the memory work, the narrator was handed
one sentence per present character ("maris has met you and is neutral toward
you") and everything else sat unread in the ledger, so re-introduction was the
DEFAULT failure -- a character could greet you as a stranger on your fourth
visit. Now the dossier is in the prompt, this is the check that the prompt
was believed.

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

#: Phrases that assert first contact WITH A PERSON. Each is matched only near a
#: known character's name (see ``_WINDOW``).
#:
#: THIS LIST IS SHORT ON PURPOSE, and three earlier entries were cut by the
#: tests that were supposed to prove them:
#:
#:   "a stranger"        -- "Maris looks at you the way you look at a stranger"
#:                          is a simile about somebody she knows perfectly well.
#:   "for the first time" -- "you see the sky clearly for the first time" says
#:                          nothing about anyone.
#:   "you have never seen" (bare) -- "you have never seen the sky this colour",
#:                          two sentences from her name, is correct prose.
#:
#: Each survivor has to be about MEETING SOMEBODY: a pronoun, a name, or a
#: question only a stranger asks. A guard that fires on correct writing is
#: worse than no guard, and precision matters more than recall here because
#: the cost of a miss is one imperfect turn while the cost of a false positive
#: is a retry that rewrites a good one.
_FIRST_CONTACT = (
    r"introduces? (?:her|him|them)sel(?:f|ves)",
    r"gives? (?:her|his|their) name as",
    r"you have never (?:seen|met) (?:her|him|them|this)",
    r"you had never (?:seen|met) (?:her|him|them|this)",
    # Bound to a PERSON noun, which is what separates "a woman you have never
    # seen" (a contradiction) from "you have never seen the sky this colour"
    # (a sentence about the sky that happens to sit near her name).
    r"(?:a|an|some|another) (?:wom|m)an you (?:do not know|have never (?:seen|met))",
    r"nobody you recognise",
    r"nobody you recognize",
    r"who are you\?",
)

#: Characters either side of the name that count as "near it". A paragraph is
#: roughly this, and requiring proximity is what keeps "a stranger" three
#: paragraphs later -- about somebody else entirely -- out of the gate.
_WINDOW = 160


def known_cast(state: Any, ledger: Any) -> dict[str, tuple[str, ...]]:
    """
    Present characters the ledger says the player has already met.

    Mirrors ``engine.agents.cast.absent_cast``, and deliberately reuses the
    same ``present_npc_ids`` the turn schema's ``npc_id`` enum is built from,
    so "present" has exactly one meaning in this codebase.

    Returns:
        ``{npc_id: (surface forms...)}``. Empty when nothing is remembered,
        which makes the criterion inert rather than failing -- a story with no
        roster, or turn zero, must not be penalised for having no history.
    """
    if state is None or ledger is None:
        return {}
    try:
        from engine.agents.cast import _surface_forms
        from engine.memory.context import present_npc_ids
    except Exception as exc:  # noqa: BLE001 -- never block a turn on this
        logger.debug("[continuity] No cast source: %s", exc)
        return {}

    out: dict[str, tuple[str, ...]] = {}
    for npc_id in present_npc_ids(state):
        record = (getattr(ledger, "relations", {}) or {}).get(npc_id)
        if record is None or not getattr(record, "met", False):
            continue
        display = str((getattr(ledger, "names", {}) or {}).get(npc_id) or "")
        forms = tuple(f for f in _surface_forms(npc_id, display) if f)
        if forms:
            out[npc_id] = forms
    return out


def find_reintroduction(
    narration: str,
    cast: Mapping[str, Sequence[str]],
) -> Optional[str]:
    """
    The first known character the prose treats as a stranger, or None.

    Returns:
        The surface form as matched, so the retry can be told WHO it forgot --
        "do not introduce strangers" is unactionable in the same way "do not
        invent people" was for the cast check.
    """
    if not narration or not cast:
        return None

    for _npc_id, forms in cast.items():
        for form in forms:
            for hit in re.finditer(rf"\b{re.escape(form)}\b", narration):
                start = max(0, hit.start() - _WINDOW)
                window = narration[start : hit.end() + _WINDOW].lower()
                for phrase in _FIRST_CONTACT:
                    if re.search(phrase, window):
                        return form
    return None


def continuity_note(name: str) -> str:
    """The retry's instruction. It names the character and says what is known."""
    return (
        f"You wrote {name} as though the player were meeting them for the "
        f"first time. The player has already met {name} -- WHO IS HERE, AND "
        f"WHAT THEY REMEMBER says so, and lists what passed between them. "
        f"Rewrite the narration so {name} knows the player: no introduction, "
        "no 'stranger', no asking who they are."
    )

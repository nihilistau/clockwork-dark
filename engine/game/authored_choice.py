"""
Authored choices: what an option the AUTHOR wrote may do beyond its intent.

An intent (``engine/game/intents.py``) is the one mechanic a choice declares,
and it is the same grammar whether the narrator sampled the choice or an
author typed it -- deliberately, so a model can never declare anything an
author could not. Some authored moments need more than one verb, though.
HUE & CRY's opening is the case that asked: a stranger who BOLTS from a
Lantern has rolled stealth AND done something the Watch can file, and one
who holds out their wrists is not walking to the Lantern House, they are
being arrested on the quay.

So an authored choice -- today, only a manifest's ``entry.opening`` choices
-- may carry three more keys beside its ``intent``::

    deed: resisting_watch            # committed when the choice is taken
    on_pass: {text, effects, encounter}
    on_fail: {text, effects, encounter}

``deed`` is committed through ``law.commit_deed``, witnesses rolled on the
LAW stream exactly as for a lift, with the check's margin when the intent was
a check. ``on_pass`` applies when the choice passed -- its check succeeded,
or it declared no check and its intent (if any) went through -- and
``on_fail`` otherwise. ``effects`` are bounded like a card's
(``spec.clamp_outcome(authored=True)``) plus ``AUTHORED_CHOICE_EFFECT_TYPES``
(``arrest``), which no card, thread or model-composed spec may use.
``encounter`` begins that scene through ``encounter.begin``, the door the
patrol and a job's alarm use, unless a scene already owns the turn.

A REFUSED intent applies nothing at all: the player did not do it, so there
is no deed to witness and no branch to take.

WHY THE MODEL CANNOT CARRY ONE. None of this is read off the choice the
client sent back or the choice in ``session.last_turn`` -- a narrated choice
is a dict whose extra keys ride through (``storyteller._positional_ids``),
and a model that wrote ``deed:`` there must get nothing. It is read from the
MANIFEST, by choice id, and only when the frame the player chose from is the
opening frame (``default_state.opening`` marks it; no turn payload does).
A story whose opening carries none of the keys resolves to ``{}`` and its
turns are byte-identical.

Version: v0.1.0 [2026-09-26]
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.game.state import GameState

logger = logging.getLogger(__name__)

#: The keys an authored choice may carry beyond ``id``, ``text`` and ``intent``.
AUTHORED_KEYS: tuple[str, ...] = ("deed", "on_pass", "on_fail")

#: What ``default_state.opening`` stamps on the opening frame, and the only
#: frame this module reads authored consequences for.
OPENING_FRAME = "opening"

#: Effects whose receipt ``text`` is written for a reader and so reaches the
#: narrator beside the branch's own line: the Law's, whose texts are a place
#: name, a guise's label and a clarity word by contract (``effects.py``). A
#: ``flag`` receipt's text is its id and value, and a meter's is a number, so
#: neither is passed on -- the author's line says what they mean.
NARRATED_EFFECT_TYPES: frozenset[str] = frozenset(
    {"arrest", "report", "release", "quash_reports"}
)


def bound(row: Any) -> dict[str, Any]:
    """
    One authored choice's consequences, bounded; ``{}`` when it carries none.

    Args:
        row: The choice exactly as the manifest declares it.

    Returns:
        ``{"deed"?: str, "on_pass"?: branch, "on_fail"?: branch, "adjustments"?:
        [...]}`` where a branch is ``{"text", "effects", "encounter"}``. The
        adjustments are every clamp applied, for the validator and the log.
    """
    from engine.challenges import spec as spec_module

    if not isinstance(row, dict) or not any(k in row for k in AUTHORED_KEYS):
        return {}
    adjustments: list[str] = []
    out: dict[str, Any] = {}
    deed = str(row.get("deed") or "").strip()
    if deed:
        out["deed"] = deed
    for branch in ("on_pass", "on_fail"):
        raw = row.get(branch)
        if not isinstance(raw, dict):
            continue
        clamped = spec_module.clamp_outcome(
            raw, adjustments, authored=True,
            extra_types=spec_module.AUTHORED_CHOICE_EFFECT_TYPES,
        )
        encounter_id = str(raw.get("encounter") or "").strip()
        if encounter_id:
            clamped["encounter"] = encounter_id
        out[branch] = clamped
    if adjustments:
        out["adjustments"] = adjustments
    return out


def problems(
    row: Any, *, deeds: Any, encounters: Any, values: Any = (),
) -> list[str]:
    """
    Why one authored choice would not do what it says, or ``[]``.

    Read straight off the manifest row, activating nothing, so the validator
    (``engine/games/validation.py``) can ask it of a story that is not the
    running one. A misspelt deed commits nothing, a misspelt encounter opens
    nothing and a disallowed effect type is dropped by ``bound`` -- each
    silently at play time, the "loads and does nothing" shape.

    Args:
        deeds: The story's law file's deed kinds (empty for a story with none).
        encounters: The story's declared encounter ids.
        values: The story's declared value names, which effects may also move.
    """
    from engine.challenges import spec as spec_module

    found: list[str] = []
    if not isinstance(row, dict) or not any(k in row for k in AUTHORED_KEYS):
        return found
    deed = str(row.get("deed") or "").strip()
    if "deed" in row and deed not in set(deeds or ()):
        found.append(f"deed `{deed}` is not a deed the story's law file lists")
    allowed = (spec_module.ALLOWED_EFFECT_TYPES | spec_module.STRUCTURAL_EFFECT_TYPES
               | spec_module.AUTHORED_CHOICE_EFFECT_TYPES | {str(v) for v in values or ()})
    for branch in ("on_pass", "on_fail"):
        raw = row.get(branch)
        if branch in row and not isinstance(raw, dict):
            found.append(f"{branch} must be a mapping of text, effects and encounter")
            continue
        raw = raw or {}
        encounter_id = str(raw.get("encounter") or "").strip()
        if encounter_id and encounter_id not in set(encounters or ()):
            found.append(f"{branch}.encounter `{encounter_id}` names no declared encounter")
        for effect in raw.get("effects") or []:
            kind = str((effect or {}).get("type") or "").strip() if isinstance(effect, dict) else ""
            name = str((effect or {}).get("name") or "") if kind == "value" else kind
            if name not in allowed:
                found.append(f"{branch}: effect type `{kind or effect!r}` is not one an "
                             "authored choice may use")
    return found


def opening_consequences(choice_id: str) -> dict[str, Any]:
    """The active manifest's opening choice ``choice_id``, bounded, or ``{}``."""
    from engine.scenes.default_state import _declared_entry_opening

    for row in _declared_entry_opening().get("choices") or []:
        if isinstance(row, dict) and str(row.get("id") or "") == str(choice_id):
            return bound(row)
    return {}


def _passed(intent: dict[str, Any], receipts: list[dict[str, Any]]) -> tuple[bool, Optional[float]]:
    """Whether the choice passed, and the check's margin when it was a check."""
    if str((intent or {}).get("action") or "") == "check":
        for receipt in receipts:
            result = receipt.get("result")
            if receipt.get("skill") == "resolve_skill_check" and isinstance(result, dict):
                margin = result.get("margin")
                margin = float(margin) if isinstance(margin, (int, float)) else None
                return bool(result.get("success")), margin
        return False, None
    return all(r.get("success") for r in receipts), None


def resolve(
    state: GameState,
    consequences: dict[str, Any],
    intent: Optional[dict[str, Any]],
    receipts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Apply an authored choice's consequences after its intent has run.

    Called by ``run_turn`` between the intent and the patrol, so the deed is
    witnessed in the street the choice left the player in, the patrol sees a
    scene this opened (and stands down), and the narrator is handed one
    receipt saying what happened.

    Args:
        state: Live state.
        consequences: ``bound``'s output for the chosen choice.
        intent: The intent that ran, or None/{} for a choice that declared none.
        receipts: What the intent produced.

    Returns:
        ``[]`` when there is nothing to apply (no consequences, or the intent
        was refused), else one receipt, skill ``authored_choice``.
    """
    if not consequences:
        return []
    if any(r.get("refused") for r in receipts):
        return []
    passed, margin = _passed(intent or {}, receipts)
    lines: list[str] = []
    committed = False
    witnessed = False
    reported = False

    deed = str(consequences.get("deed") or "")
    if deed:
        from engine.world import law

        if law.declared() and deed in law.load_spec()["deeds"]:
            seen = law.commit_deed(state, deed, margin=margin)
            committed = True
            witnessed = bool(seen.get("witnesses"))
            reported = bool(seen.get("reported"))
        else:
            logger.warning(
                "[authored_choice] Deed not committed: the story's law lists no "
                "such deed (operation=resolve, deed=%s)", deed,
            )

    branch = consequences.get("on_pass" if passed else "on_fail") or {}
    text = str(branch.get("text") or "").strip()
    if text:
        lines.append(text)

    from engine.game.effects import apply_effect

    applied: list[dict[str, Any]] = []
    for effect in branch.get("effects") or []:
        row = apply_effect(state, effect)
        applied.append(row)
        if not row.get("ok", True):
            logger.warning(
                "[authored_choice] Effect refused (operation=resolve, type=%s, why=%s)",
                effect.get("type"), row.get("message") or row.get("text"),
            )

    begun = ""
    encounter_id = str(branch.get("encounter") or "")
    if encounter_id:
        from engine.game import encounter, intents

        if not intents.scene_owns_turn(state) and encounter.begin(state, encounter_id):
            begun = encounter_id

    return [{
        "type": "authored",
        "skill": "authored_choice",
        "args": {},
        "result": {
            "ok": True,
            "passed": passed,
            "text": " ".join(lines),
            # Whether a deed was committed, seen, and filed -- booleans only:
            # witness ids are the engine's, and the narrator is told in words.
            "deed": committed,
            "witnessed": witnessed,
            "reported": reported,
            "effects": [str(r.get("text")) for r in applied
                        if r.get("type") in NARRATED_EFFECT_TYPES and r.get("ok")
                        and not r.get("hidden") and r.get("text")],
            "scene": bool(begun),
        },
        "success": True,
    }]


__all__ = [
    "AUTHORED_KEYS",
    "NARRATED_EFFECT_TYPES",
    "OPENING_FRAME",
    "bound",
    "opening_consequences",
    "problems",
    "resolve",
]

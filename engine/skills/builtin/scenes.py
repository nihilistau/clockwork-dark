"""
Scene Skills
============

Answering a dealt card -- the one entry point the ``card`` intent verb resolves
through.

WHY THIS IS A SKILL AND NOT PROSE. A card's beats move meters, set flags, lock
endings and run the ending module; The Wicked Garden's whole finale is beats on
a card. CLAUDE.md's first rule is that the engine resolves mechanics and the
model narrates them, so the card is resolved BEFORE a word is written and the
receipt is handed to the narrator to render.

Thin by design, exactly like its siblings in this package: bind the active
engine, call the module that owns the work (``engine/content/director.py``), and
return its receipt verbatim so a test can assert the engine did not quietly add
a number it did not show.

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import json

from engine.game.engine import get_active_engine
from engine.skills.registry import AGENT_STORYTELLER, skill


@skill(
    pack="core",
    description=(
        "Answer the authored card currently in front of the player: apply the "
        "beat they chose and move to the next card in the hand. A menu card "
        "takes the id of ONE beat -- its beats are branches of a single "
        "question, and resolving them all would take every branch at once. A "
        "sequence card takes no choice. MUST call before narrating what the "
        "card's outcome was."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def resolve_scene_card(chosen: str = "") -> str:
    """
    Apply the chosen beat of the open scene's current card.

    Args:
        chosen: The beat id the player picked on a menu card. Empty, or the
            sentinel ``"resolve"``, for a sequence card.

    Returns:
        The director's receipt as JSON. ``ok: false`` for a beat the card does
        not carry or a resolve against a closed scene -- a refusal that reaches
        the prose through the intent machinery rather than a silent no-op.
    """
    from engine.content import director

    engine = get_active_engine()
    return json.dumps(
        director.resolve(engine.state, chosen=chosen, ledger=None)
    )


@skill(
    pack="core",
    description=(
        "Begin an authored set-piece at this location: a skill gauntlet, a "
        "decision tree, a puzzle or a dice table. Only pieces whose gates are "
        "open here and now can be started. MUST call before narrating the "
        "player entering one."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def start_set_piece(piece_id: str = "") -> str:
    """
    Open a set-piece as the current challenge.

    Args:
        piece_id: Catalogue id, from ``set_pieces.available``.

    Returns:
        The challenge's first step as JSON, or an error result for an unknown
        or gated-shut piece.
    """
    from engine.challenges import set_pieces

    engine = get_active_engine()
    result = set_pieces.start(engine.state, piece_id)
    payload = result.to_dict()
    # `ok` is what REFUSAL_KEY_FOR_ACTION reads. ChallengeResult reports its own
    # failure as a status, and the intent layer must not have to know that.
    payload["ok"] = result.status != "error"
    if not payload["ok"]:
        payload["error"] = result.message or "the set-piece could not be started"
    return json.dumps(payload)


@skill(
    pack="core",
    description=(
        "Advance the running challenge by one step: pick an option on a "
        "gauntlet or decision tree, or answer a puzzle. MUST call before "
        "narrating the outcome of a step."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def resolve_challenge(choice: str = "", answer: str = "") -> str:
    """
    Advance the active challenge.

    Args:
        choice: The option id, for a gauntlet or decision tree.
        answer: Free text, for a puzzle. A puzzle is the one challenge whose
            input cannot be an enum, which is why the ``challenge`` intent verb
            carries no target list for it.

    Returns:
        The next step as JSON, with ``ok`` for the intent layer's refusal check.

    Routed through ``set_pieces.resolve`` rather than ``runner.resolve``: only
    the former grants the set-piece's terminal flag on success, and a gauntlet
    won without its flag is a gauntlet the player gets to win again.
    """
    from engine.challenges import set_pieces

    engine = get_active_engine()
    result = set_pieces.resolve(engine.state, choice=choice, answer=answer)
    payload = result.to_dict()
    payload["ok"] = result.status != "error"
    if not payload["ok"]:
        payload["error"] = result.message or "that is not a step this challenge has"
    return json.dumps(payload)


@skill(
    pack="core",
    description=(
        "Strike a bargain: offer a declared contract and seal it, making it a "
        "thread the world remembers. MUST call before narrating a deal being "
        "struck -- a promise the engine does not hold is a promise the story "
        "can quietly stop honouring three turns later."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def strike_bargain(template_id: str = "", sealed_by: str = "word") -> str:
    """
    Offer and seal a thread template in one call.

    Offer and seal are separate in ``engine/game/threads.py`` because
    renegotiation happens between them -- and renegotiation belongs to the
    agent pipeline, where two parties can actually argue, rather than to a
    choice chip. The player-facing verb is the simple case: this contract, as
    offered, agreed.

    Args:
        template_id: Key in the story's ``threads.yaml`` templates.
        sealed_by: The act that bound it -- word, kiss, blood, gift.

    Returns:
        The seal receipt as JSON, or ``ok: false`` for an undeclared template.
    """
    from engine.game import threads

    engine = get_active_engine()
    proposal = threads.offer(engine.state, template_id)
    if proposal is None:
        return json.dumps(
            {"ok": False, "error": f"no thread template named {template_id!r}"}
        )
    receipt = threads.seal(engine.state, proposal, sealed_by=sealed_by)
    receipt.setdefault("ok", True)
    return json.dumps(receipt)


@skill(
    pack="core",
    description=(
        "Discharge a live thread: the contract is satisfied and stops being "
        "owed. MUST call before narrating a debt being settled."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def discharge_thread(thread_id: str = "", why: str = "paid") -> str:
    """
    Settle an active thread.

    The verb the player actually needs: a debt that cannot be paid is not a
    bargain, it is a trap.

    Args:
        thread_id: Id from ``threads.active``.
        why: Short reason, recorded on the thread.
    """
    from engine.game import threads

    engine = get_active_engine()
    receipt = threads.discharge(engine.state, thread_id, why=why)
    if isinstance(receipt, dict):
        receipt.setdefault("ok", True)
        return json.dumps(receipt)
    return json.dumps({"ok": bool(receipt)})

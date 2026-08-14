"""
Memory Skills
=============

What the narrator may ASK the world to remember for it.

There is one tool here and it only reads. The prompt already carries the
essentials unprompted -- a dossier for everyone in the room and the state of
the room itself (``engine/agents/prompts.py::memory_blocks``) -- because memory
the model has to remember to ask for is memory it will forget to ask for. This
exists for the rest: the person two rooms away who is about to be mentioned,
the place the player is describing from memory, the topic a story declared.

WHY THERE IS NO ``remember_this`` TOOL. The model already proposes ledger
deltas as part of its structured turn output, and those are validated and
applied by the engine (``engine/memory/ledger.py``). A second write path
reached by a different mechanism would be two implementations of the same
authority, and the one thing this codebase has learned repeatedly is that the
second one is the one nobody validates. Reading is safe; writing has an owner.

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import json

from engine.game.engine import get_active_engine
from engine.skills.registry import (
    AGENT_STORYTELLER,
    TRIGGER_OPTIONAL,
    skill,
)

#: Facts returned per call. Small: a tool answer is spent from the same context
#: the narration has to fit in, and a model that asks for four subjects should
#: not be able to spend the whole window on the answer.
MAX_RECALL = 4


@skill(
    pack="core",
    description=(
        "Recall what the world remembers about one subject -- a character, a "
        "place, or a topic. Use before writing about someone or somewhere the "
        "prompt has not already described, so what you write agrees with what "
        "happened. Read-only: it never changes anything."
    ),
    category="NARRATIVE",
    trigger=TRIGGER_OPTIONAL,
    agents=[AGENT_STORYTELLER],
)
def recall_subject(subject_id: str = "") -> str:
    """
    Everything remembered about one subject, as JSON.

    Args:
        subject_id: An NPC id, a location id, or a declared topic key.

    Returns:
        JSON: ``{ok, subject_id, kind, met, disposition, facts, notes, owed,
        tags}``. ``ok: false`` with a ``reason`` when the subject is unknown --
        which is a real answer, not an error: "nothing is remembered about this
        person" is exactly what the narrator needs to know before inventing a
        history for them.
    """
    subject_id = str(subject_id or "").strip()
    if not subject_id:
        return json.dumps({"ok": False, "reason": "no subject_id given"})

    engine = get_active_engine()
    ledger = getattr(engine, "ledger", None)
    if ledger is None:
        # The session owns the ledger; a bare engine (tests, the simulator) has
        # none. Saying so beats inventing an empty memory that reads as "this
        # person is a stranger".
        return json.dumps(
            {"ok": False, "subject_id": subject_id, "reason": "no ledger in this session"}
        )

    record = ledger.relations.get(subject_id)
    facts = [f.text for f in ledger.recall(subject_id, limit=MAX_RECALL)]
    if record is None and not facts:
        return json.dumps(
            {
                "ok": True,
                "subject_id": subject_id,
                "known": False,
                "reason": "nothing is remembered about this subject yet",
            }
        )

    return json.dumps(
        {
            "ok": True,
            "subject_id": subject_id,
            "known": True,
            "kind": getattr(record, "kind", "npc") if record else "unknown",
            "met": bool(getattr(record, "met", False)) if record else False,
            "disposition": int(getattr(record, "disposition", 0)) if record else 0,
            "facts": facts,
            "notes": list(getattr(record, "notes", []) or [])[-3:] if record else [],
            "owed": list(getattr(record, "owed", []) or [])[-2:] if record else [],
            "tags": list(getattr(record, "tags", []) or [])[-3:] if record else [],
        }
    )

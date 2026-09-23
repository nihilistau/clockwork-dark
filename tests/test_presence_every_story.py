"""
Everyone the schedules put in a room is in the room -- in every story.

THE BUG. ``present_npc_ids`` and ``_npcs_present_block`` returned early when
``state.procgen.npcs`` was empty, and only the flagship runs procgen. So in four
of five stories the narrator read "PEOPLE HERE: (world not yet generated)"
while the buy intent offered a present vendor's stock; the cast gate rejected
prose naming her; nobody was ever met; and every model-proposed NPC fact was
dropped, because ``known_npc_ids`` was built from the same empty list.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

import pytest

from engine.agents import prompts
from engine.games import registry
from engine.memory.context import present_npc_ids
from engine.scenes.default_state import SessionStore
from engine.world import npc_sim

STORIES = ["wicked-garden", "neon-city", "the-long-con", "dev-story", "hue-and-cry"]


def _session(slug: str):
    registry.activate(slug)
    return SessionStore().create(seed=7, llm_fn=lambda messages, **kw: "{}")


def _someone_scheduled_somewhere(state):
    """A (location, npc) pair the story's own schedule places together now."""
    for npc_id in npc_sim.known_npc_ids(state):
        presence = npc_sim.resolve_npc(state, npc_id)
        if presence and presence.location_id:
            return presence.location_id, npc_id
    return None, None


@pytest.mark.parametrize("slug", STORIES)
def test_a_scheduled_npc_is_present(slug: str) -> None:
    session = _session(slug)
    state = session.engine.state
    where, who = _someone_scheduled_somewhere(state)
    assert who, f"{slug} schedules nobody -- the fixture's assumption is broken"
    state.location_id = where

    assert who in present_npc_ids(state)
    block = prompts._npcs_present_block(state)
    assert "world not yet generated" not in block
    assert npc_sim.display_name(who, state) in block


@pytest.mark.parametrize("slug", STORIES)
def test_the_dossier_prints_a_name_not_an_id(slug: str) -> None:
    """It printed ``npc_maris (npc_maris)``: ledger.names is keyed by proper noun."""
    session = _session(slug)
    state, ledger = session.engine.state, session.ledger
    where, who = _someone_scheduled_somewhere(state)
    state.location_id = where
    ledger.meet(who, day=1, location_id=where)

    lines = prompts._dossier(ledger, who, state=state)
    assert lines, "a met NPC has no dossier"
    assert who not in lines[0], lines[0]
    assert npc_sim.display_name(who, state) in lines[0]


@pytest.mark.parametrize("slug", STORIES)
def test_a_fact_about_a_scheduled_npc_is_admitted(slug: str) -> None:
    """
    The turn's memory step dropped every subject not in procgen.npcs.

    Driven through ``_record_memory`` -- the real caller -- because
    ``apply_ledger_delta`` itself was always right; it was handed an empty
    list of who exists.
    """
    from types import SimpleNamespace

    from engine.scenes.default_state import _record_memory

    session = _session(slug)
    state, ledger = session.engine.state, session.ledger
    where, who = _someone_scheduled_somewhere(state)
    state.location_id = where
    result = SimpleNamespace(
        narration="You ask after the east road.",
        parsed={
            "ledger_delta": {
                "facts": [{"text": "you asked after the east road", "subject_id": who}]
            }
        },
    )
    _record_memory(session, "ask about the road", result)

    assert any(f.subject_id == who for f in ledger.facts), [
        (f.text, f.subject_id) for f in ledger.facts
    ]
    assert ledger.relations.get(who) is not None and ledger.relations[who].met


def test_display_name_never_returns_an_id() -> None:
    registry.activate("neon-city")
    assert npc_sim.display_name("npc_nobody_at_all") == "somebody"


@pytest.mark.parametrize("slug", STORIES + ["clockwork-dark"])
def test_every_scheduled_person_has_a_name(slug: str) -> None:
    """
    A schedule row with no ``name:`` reached the narrator as its id.

    The Wicked Garden's eight rows carried neither ``name`` nor ``role``, so
    presence rendered "ashen_vale: ashen_vale (visitor)" -- and its own
    ``role_defaults`` for ``bloomkin`` and ``court`` could never match a row,
    because every row's role fell back to "visitor". The flagship's names come
    from procgen's canon villagers, which ``display_name`` asks second.
    """
    session = _session(slug)
    state = session.engine.state
    nameless = [
        npc_id
        for npc_id in npc_sim.known_npc_ids(state)
        if npc_sim.display_name(npc_id, state) == "somebody"
    ]
    assert not nameless, f"{slug}: no name for {nameless}"

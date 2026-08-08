"""
Session Machinery
=================

One player's live run: engine, agents, ledger, save id, turn lock.

Lived in ``content/scenes/clockwork/clockwork_state.py`` until v0.3.0, which
made it story-owned code that every story had to inherit. Nothing in it is
Clockwork's -- see the module docstring in ``store.py`` for the two seams that
are.

Version: v0.1.0 [2026-08-08]
"""

from engine.session.store import GameSession, SessionStore, default_archetype

__all__ = ["GameSession", "SessionStore", "default_archetype"]

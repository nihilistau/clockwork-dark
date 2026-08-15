"""
Session Store
=============

In-memory registry of live runs, backed by on-disk saves.

    store = SessionStore(opening=..., resume_opening=..., save_store=...)
    session = store.create(player_name="Alden", seed=42)
    session = store.resume(save_id)
    session = store.require(session_id)      # KeyError if it is gone

WHAT IS THE ENGINE'S AND WHAT IS THE STORY'S. A session is engine machinery:
a GameEngine over a GameState, a Storyteller, an Assistant, a narrative ledger,
the save id it autosaves into, and a lock so two turns cannot interleave. None
of that is Clockwork's, and it sat in ``content/scenes/clockwork/`` until
v0.3.0 -- so a second story could not have a session without importing the
flagship.

Exactly two things ARE the story's, and both are injected rather than inherited:

    opening(state) -> dict           the frame a brand-new run opens on
    resume_opening(state, ledger)    the frame a reloaded run lands in

``last_turn`` is what the client renders and what ``resolve_player_action``
matches a choice id against, so a story that does not supply these gets an
empty frame -- correct-but-blank, never Edgewood's birch trees.

WHY ``save_store`` IS INJECTED TOO. It is not for testing seams; it is because
the caller decides WHEN the store is resolved. ``get_save_store()`` caches a
process-wide SaveStore built from ``paths.saves`` and the active game's slug,
so a store captured at construction time would outlive a game activation.
Passing the *accessor* keeps the lookup late.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from engine.agents.assistant import AssistantAgent
from engine.agents.storyteller import StorytellerAgent
from engine.game.engine import GameEngine
from engine.game.procgen import new_game_state
from engine.game.state import GameState
from engine.memory import StoryLedger
from engine.persistence import get_save_store

logger = logging.getLogger(__name__)

# (state) -> the payload a fresh run's first frame renders from.
OpeningBuilder = Callable[[GameState], dict[str, Any]]
# (state, ledger) -> the payload a reloaded run's first frame renders from.
ResumeBuilder = Callable[[GameState, StoryLedger], dict[str, Any]]

LLMFn = Callable[[list[dict[str, Any]]], str]

# What a run starts as when no manifest is readable at all: nobody in
# particular. This was the flagship's "wayfarer" -- one story's noun stamped on
# any build that could not answer -- and it is unreachable in practice, because
# ``entry.archetypes`` is validated at activation and all four shipped games
# answer long before this is asked (wayfarer, human, runner, human).
FALLBACK_ARCHETYPE = ""


def default_archetype(fallback: str = FALLBACK_ARCHETYPE) -> str:
    """
    The archetype a new run starts as, per the active story's manifest.

    Answers WITHOUT activating anything -- ``entry_archetypes`` reads the
    resolved manifest off disk when none is active, so asking this question
    cannot repoint config or reset caches.

    A story that declares ``archetypes: []`` gets an EMPTY archetype, not the
    flagship's. Character classes are one story's idea: a story where the player
    is simply a person who walked in has nothing to pick from, and inheriting
    "wayfarer" would stamp every run of it with another game's noun -- silently,
    since nothing downstream requires an archetype to resolve.

    The distinction is between "declared nothing" and "declared an empty list".
    A manifest with no ``entry`` block at all still falls back, because that is
    an author who has not said, rather than one who has said no.

    Args:
        fallback: Returned when no manifest is readable, or when the manifest
            does not mention archetypes at all.
    """
    try:
        from engine.games.registry import entry_manifest

        manifest = entry_manifest()
        if manifest is not None and "archetypes" in (manifest.entry or {}):
            offered = manifest.archetypes
            # Declared and empty: this story has no classes. Honour it.
            return str(offered[0]) if offered else ""
    except Exception as exc:  # noqa: BLE001 — never block a new game on this
        logger.debug("[session] No manifest archetype: %s", exc)
    return fallback


def _declared_opening(state: GameState) -> dict[str, Any]:
    """
    The frame a new run opens on, from the active story's manifest.

    A story declares it as data:

        entry:
          opening:
            narration: "You wake beneath birch trees..."
            choices:
              - {id: a, text: "Follow the smoke"}

    WHY DATA AND NOT CODE. The opening used to be two module constants in the
    flagship's scene package, injected into this store by the flagship's
    subclass -- so a second story running on the same scene inherited Edgewood's
    birch trees as the first thing its player ever read. That is the same shape
    as the archetype default, which had three homes and was missed in one of
    them: one story's answer, reachable from a place a second story cannot
    override without writing code.

    Deliberately empty when a story declares nothing. A blank frame is
    correct-but-blank; another story's forest is wrong and looks deliberate.
    """
    frame: dict[str, Any] = {"narration": "", "choices": [], "state": state.to_client_dict()}
    try:
        from engine.games.registry import entry_manifest

        manifest = entry_manifest()
        declared = (manifest.entry or {}).get("opening") if manifest else None
        if isinstance(declared, dict):
            frame["narration"] = str(declared.get("narration") or "")
            choices = declared.get("choices") or []
            frame["choices"] = [
                {"id": str(c.get("id") or ""), "text": str(c.get("text") or "")}
                for c in choices
                if isinstance(c, dict) and c.get("text")
            ]
    except Exception as exc:  # noqa: BLE001 -- a missing opening is not fatal
        logger.debug("[session] No declared opening: %s", exc)
    return frame


#: Kept as the documented name for "render nothing".
_blank_opening = _declared_opening


def _blank_resume(state: GameState, _ledger: StoryLedger) -> dict[str, Any]:
    """As ``_blank_opening``, for a run reloaded from disk."""
    return {"narration": "", "choices": [], "state": state.to_client_dict(), "resumed": True}


@dataclass
class GameSession:
    """One player session bound to engine and agents."""

    engine: GameEngine
    storyteller: StorytellerAgent
    assistant: AssistantAgent
    last_turn: dict[str, Any] = field(default_factory=dict)
    save_id: str = ""
    # Narrative memory. Persisted beside the save rather than inside it, so
    # save.json stays small and diffable.
    ledger: StoryLedger = field(default_factory=StoryLedger)
    # Held for the duration of a turn. A second choice arriving mid-turn is
    # rejected rather than interleaved -- two turns mutating one GameState
    # concurrently corrupts it in ways no test would reproduce.
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def session_id(self) -> str:
        return self.engine.state.session_id


def _is_busy(session: GameSession) -> bool:
    """
    Whether a turn is currently running for this session.

    Probed by acquiring the turn lock and immediately releasing it, which is
    the only reliable signal available: a turn against a local model can take
    minutes, so elapsed time says nothing about whether anyone is still there.
    """
    if not session.lock.acquire(blocking=False):
        return True
    session.lock.release()
    return False


class SessionStore:
    """
    In-memory session registry backed by on-disk saves.

    Args:
        opening: Builds the first frame of a new run. See the module docstring.
        resume_opening: Builds the first frame of a reloaded run.
        save_store: Zero-arg accessor returning the SaveStore to use. Called
            per operation, never cached, so a game activation between two calls
            lands on the right save namespace.
    """

    def __init__(
        self,
        *,
        opening: Optional[OpeningBuilder] = None,
        resume_opening: Optional[ResumeBuilder] = None,
        save_store: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._sessions: dict[str, GameSession] = {}
        #: ``session_id -> monotonic timestamp of last access``. Feeds
        #: ``sweep_idle`` and nothing else.
        self._seen: dict[str, float] = {}
        self._guard = threading.RLock()
        self._opening: OpeningBuilder = opening or _blank_opening
        self._resume_opening: ResumeBuilder = resume_opening or _blank_resume
        self._save_store: Callable[[], Any] = save_store or get_save_store

    def _build(
        self,
        state: GameState,
        *,
        llm_fn: Optional[LLMFn] = None,
        save_id: str = "",
        ledger: Optional[StoryLedger] = None,
    ) -> GameSession:
        engine = GameEngine(state)
        resolved_ledger = ledger or StoryLedger()
        session = GameSession(
            engine=engine,
            # One ledger object shared with the agent, not a copy: what the
            # session records after a turn is what the agent reads before the
            # next one.
            storyteller=StorytellerAgent(engine, llm_fn=llm_fn, ledger=resolved_ledger),
            assistant=AssistantAgent(engine, llm_fn=llm_fn),
            save_id=save_id,
            ledger=resolved_ledger,
        )
        with self._guard:
            self._sessions[state.session_id] = session
            self._seen[state.session_id] = time.monotonic()

        # Swept here rather than per turn, and rather than on a timer thread:
        # sessions only accumulate by being created, so this is the exact rate
        # the problem appears at, it stays off the turn's hot path, and there
        # is no background thread to reason about. A no-op unless
        # `session.idle_sweep_enabled` is on.
        try:
            self.sweep_idle()
        except Exception as exc:  # noqa: BLE001 -- housekeeping must not fail a run
            logger.warning("[session] Idle sweep failed (operation=_build): %s", exc)

        return session

    def create(
        self,
        *,
        player_name: str = "Traveler",
        archetype: Optional[str] = None,
        seed: Optional[int] = None,
        llm_fn: Optional[LLMFn] = None,
    ) -> GameSession:
        """
        Create a new procgen-backed session and write its first save.

        ``archetype`` defaults from the active story's manifest rather than
        from the string "wayfarer". ``entry.archetypes`` has been validated and
        published over ``/api/games`` since the multi-game layer landed and
        consumed by nothing -- three places each held their own copy of the
        flagship's answer, so a second story offered its own archetypes in the
        picker and then started every run as a Clockwork wayfarer.
        """
        state = new_game_state(
            player_name=player_name,
            archetype=archetype or default_archetype(),
            seed=seed,
        )
        session = self._build(state, llm_fn=llm_fn)
        session.last_turn = self._opening(state)
        try:
            session.save_id = self._save_store().save(state)
        except OSError as exc:
            logger.warning(
                "[session] Initial save failed (operation=create): %s", exc
            )
        logger.info(
            "[session] Session created (operation=create, id=%s, save=%s)",
            state.session_id,
            session.save_id,
        )
        return session

    def resume(
        self,
        save_id: str,
        *,
        llm_fn: Optional[LLMFn] = None,
    ) -> GameSession:
        """
        Rehydrate a run from disk.

        This is what makes a dropped socket survivable. The client previously
        called /api/game/new on every reconnect, silently discarding the run.
        """
        state, memory = self._save_store().load(save_id)
        session = self._build(
            state,
            llm_fn=llm_fn,
            save_id=save_id,
            ledger=StoryLedger.from_dict(memory),
        )
        session.last_turn = self._resume_opening(state, session.ledger)
        logger.info(
            "[session] Session resumed (operation=resume, save=%s, day=%s)",
            save_id,
            state.world_day,
        )
        return session

    def get(self, session_id: str) -> Optional[GameSession]:
        with self._guard:
            session = self._sessions.get(session_id)
            if session is not None:
                self._seen[session_id] = time.monotonic()
            return session

    def sweep_idle(self, ttl_minutes: Optional[float] = None) -> list[str]:
        """
        Release sessions nobody has touched for a while.

        OFF BY DEFAULT (``session.idle_sweep_enabled``). Evicting a live run
        loses a player's game, and the cost of NOT sweeping is memory in a
        long-lived process -- so the failure modes are not symmetric and the
        conservative default is the right one until this has miles on it.

        A session whose turn lock is held is never evicted, whatever its age: a
        turn can legitimately take minutes against a local model, and the lock
        is the only reliable signal that someone is still in there.

        Returns:
            The session ids released.
        """
        from engine.config import get_config

        cfg = get_config()
        if not bool(cfg.get("session.idle_sweep_enabled", False)):
            return []
        if ttl_minutes is None:
            ttl_minutes = float(cfg.get("session.idle_ttl_minutes", 60))
        # Floored at one minute on purpose: a misconfigured `idle_ttl_minutes: 0`
        # would otherwise evict every session on the next `create`, including
        # the one the player is sitting in.
        cutoff = time.monotonic() - max(1.0, float(ttl_minutes)) * 60.0

        with self._guard:
            stale = [
                sid
                for sid, session in self._sessions.items()
                if self._seen.get(sid, 0.0) < cutoff and not _is_busy(session)
            ]

        for session_id in stale:
            logger.info(
                "[session] Releasing idle session (operation=sweep_idle, id=%s)",
                session_id,
            )
            self.delete(session_id)
        return stale

    def require(self, session_id: str) -> GameSession:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"Unknown session: {session_id}")
        return session

    def delete(self, session_id: str) -> None:
        """
        Forget a run, and everything else that was holding onto it.

        THE SINGLE TEARDOWN DOOR. Three registries kept a reference to a live
        run and none of their release functions had a production caller:
        ``mechanics.register_engine`` is called at the top of EVERY mechanics
        phase and ``release_engine`` was called only from a test, so every
        ``GameEngine`` -- and through it every ``GameState``, inventory, roster
        and world-event list -- was retained for the life of the process. The
        skills server's per-session registration had the same shape, and
        additionally writes a row into ``mcp.json`` per session.

        Never raises: releasing an auxiliary registry that is not installed, or
        that has already forgotten this id, is not a reason to fail the caller
        that is trying to clean up.
        """
        with self._guard:
            self._sessions.pop(session_id, None)
            self._seen.pop(session_id, None)

        try:
            from engine.agents.mechanics import release_engine

            release_engine(session_id)
        except Exception as exc:  # noqa: BLE001 -- see docstring
            logger.debug("[session] Engine release skipped (id=%s): %s", session_id, exc)

        try:
            from engine.mcp.skills_server import active_server

            server = active_server()
            if server is not None:
                server.release(session_id)
        except Exception as exc:  # noqa: BLE001 -- see docstring
            logger.debug("[session] Skills release skipped (id=%s): %s", session_id, exc)


__all__ = [
    "FALLBACK_ARCHETYPE",
    "GameSession",
    "OpeningBuilder",
    "ResumeBuilder",
    "SessionStore",
    "default_archetype",
]

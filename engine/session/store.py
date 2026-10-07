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
the caller decides WHEN the store is resolved. ``get_save_store()`` answers the
cached SaveStore for the local player and the active game's slug, under the
storage root (``engine/persistence/storage.py``), so a store captured when the
SessionStore is constructed would outlive a game activation. Passing the
*accessor* keeps the lookup late: it is resolved when each SESSION is built,
and the session keeps it (``GameSession.saves``, v0.20.0), so a run autosaves
into the store it was created or resumed from. A session of another owner
(hosted mode) resolves ``save_store_for(owner, active slug)`` instead.

OWNERSHIP (v0.20.0, spec §6.4). ``current_owner`` is the account a request or
a socket event acts for, set by hosted mode's HTTP gate and socket guard and
reset after each (``engine/hosting``); it lives HERE, in the session package,
so the store reads it in both modes without importing ``engine.hosting``.
``require``, ``create`` and ``resume`` read it when no ``owner`` is passed
(``request_owner``):

- local mode (``hosting.enabled`` false): never set, never read; ``require``
  checks nothing and a run is the local player's (owner ``""``);
- hosted mode: a session owned by anyone else is MISSING -- the same
  ``KeyError``, so the same 404 or "session not found" a nonexistent id gets
  -- and an UNSET owner is a refusal (``KeyError``), so a code path that
  escaped both gates fails closed. A story blueprint that calls
  ``store.require(session_id)`` is covered without being edited.

THE ADMIN PANEL'S VIEW (v0.20.0 T15, hosted): ``describe`` lists the live
sessions as metadata only (``DESCRIBE_KEYS``: never the state's name, place
or text), read under the guard and no turn lock; ``end`` and ``end_owner``
release a session (or an account's) as the idle sweep does, refusing one
whose turn lock is held. The save cap's count and write are one step:
``SaveStore.save(max_rows=save_room_limit())``.

SESSION METRICS (v0.20.0 T17, hosted under the supervisor): ``on_event`` is a
hook ``engine.hosting.install`` sets, None by default (never an import of
``engine.hosting``), told each ``created``, ``resumed``, ``released``,
``swept`` and ``ended_by_admin`` with the account id and nothing else.

Version: v0.3.0 [2026-10-06]
"""

from __future__ import annotations

import contextvars
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
from engine.persistence import SaveStore, get_save_store, save_store_for
from engine.persistence.saves import SaveRoomFull

logger = logging.getLogger(__name__)

# (state) -> the payload a fresh run's first frame renders from.
OpeningBuilder = Callable[[GameState], dict[str, Any]]
# (state, ledger) -> the payload a reloaded run's first frame renders from.
ResumeBuilder = Callable[[GameState, StoryLedger], dict[str, Any]]

LLMFn = Callable[[list[dict[str, Any]]], str]

#: The account a hosted request or socket event acts for (spec §6.4); None
#: outside one, and always None in local mode.
current_owner: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "engine_session_current_owner", default=None
)


class OwnerUnset(KeyError):
    """Hosted mode, and no owner is set: the request escaped both gates."""


#: What a hosted player starting or resuming a run is told while their other
#: run's turn is still running (spec §5.4); answered 409.
OTHER_WINDOW_BUSY = "A turn is still running in your other window."

#: What an admin ending a session whose turn is running is told (spec §14.8).
TURN_RUNNING = "a turn is running; try again in a moment"

#: Why a live run was released (v0.21.0, spec §6.5), passed to ``on_release``
#: and, in hosted mode, to the run's room as ``session_ended``'s ``reason``.
RELEASED_ELSEWHERE = "elsewhere"  # one live run per account: opened elsewhere
RELEASED_ENDED = "ended"  # an admin's end, or ``delete``
RELEASED_IDLE = "idle"  # the idle sweep

#: A ``describe`` row's keys, exactly (v0.20.0 T15): metadata, never play text.
DESCRIBE_KEYS = ("owner", "session_id", "save_id", "created", "last_activity", "turns", "turn_running")

#: How often, at most, a hosted ``require`` runs the idle sweep (spec §5.4).
SWEEP_INTERVAL_SECONDS = 60.0


class SessionBusy(RuntimeError):
    """
    Hosted mode: this account's other live run has a turn running, so it
    cannot be released for a new one (spec §5.4). A ``RuntimeError``, never a
    ``ValueError``: the doors answer it 409 with ``OTHER_WINDOW_BUSY``, not as
    a save that will not load.
    """

    def __init__(self, message: str = OTHER_WINDOW_BUSY) -> None:
        super().__init__(message)


#: What a request that would write for an account an admin has disabled or
#: deleted (or is ending) is told (v0.20.0 T15 fix round 2, N3); answered 409.
ACCOUNT_CLOSED = "This account was closed by the server's operator, so nothing was saved."


class AccountClosed(SessionBusy):
    """
    Hosted: the write (a new run's first save, a manual save) is for an
    account that is disabled, gone, or whose sessions an admin is ending
    (T15 fix round 2, N3). A ``SessionBusy``, so every door answers it 409
    with these words.
    """

    def __init__(self, message: str = ACCOUNT_CLOSED) -> None:
        super().__init__(message)


def saves_full_message(limit: int) -> str:
    """What a hosted player told they have no room for another save is told."""
    return (
        f"This story already keeps {int(limit)} of your runs and saves on this "
        "server, the most it allows. Delete one to make room."
    )


class SavesFull(RuntimeError):
    """
    Hosted mode: a new run or save would take an account past
    ``hosting.max_saves_per_story`` in this story (T9 fix round 1). A
    ``RuntimeError``: the doors answer it 409 with its own words.
    """


def save_room_limit() -> Optional[int]:
    """
    Hosted mode's ``hosting.max_saves_per_story``, for ``SaveStore.save``'s
    ``max_rows`` (the count and the write one step under the folder's index
    lock, v0.20.0 T15); None in local mode, which is never limited. Read
    here, before the save takes its leaf lock.
    """
    if not _hosted():
        return None
    from engine.config import get_config

    return int(get_config().get("hosting.max_saves_per_story", 50))


def check_save_room(saves: Any, save_id: Optional[str] = None) -> None:
    """
    Hosted only: refuse a write that would ADD a row to ``saves``' index once
    it holds ``hosting.max_saves_per_story`` (a new run's first save, or a
    manual save under a new id). Overwriting a save that is there is always
    allowed; local mode is never limited.

    AN EARLY ANSWER, NOT THE GUARD: two saves at once can both pass it. The
    guard is the write's own count under the folder's index lock
    (``SaveStore.save(max_rows=save_room_limit())``, v0.20.0 T15); this
    refuses before a run is built.

    Raises:
        SavesFull: no room.
    """
    if not _hosted():
        return
    from engine.config import get_config

    limit = int(get_config().get("hosting.max_saves_per_story", 50))
    rows = {row.save_id for row in saves.list_saves()}
    if save_id and save_id in rows:
        return
    if len(rows) >= limit:
        logger.info(
            "[session] Refused: the account's saves in this story are at the cap "
            "(operation=check_save_room, rows=%d, limit=%d)",
            len(rows),
            limit,
        )
        raise SavesFull(saves_full_message(limit))


class SessionConflict(ValueError):
    """
    A run being built carries a session id that is live under ANOTHER owner
    (a save copied between accounts). Refused, never replaced: a
    ``ValueError``, so the resume doors answer it as a save that will not
    load (and log it), never as the other owner's run.
    """


def request_owner(owner: Optional[str] = None) -> Optional[str]:
    """
    Whose runs this call may reach: ``owner`` when given; else None in local
    mode (nothing is checked) and ``current_owner`` in hosted mode.

    Hosted mode never answers ``""`` (the local player): an explicit
    ``owner=""`` is refused like an unset one (fix round 1), so no hosted path
    reaches the local player's store or sessions.

    Raises:
        OwnerUnset: hosted mode and no owner (unset, or ``""``): fail closed.
    """
    from engine.config import hosting_enabled

    if not hosting_enabled():
        return owner
    value = owner if owner is not None else current_owner.get()
    if not value:
        logger.error(
            "[session] Refused: hosted mode with no owner set (operation=request_owner)"
        )
        raise OwnerUnset("no owner")
    return value

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
    # Whose run this is: "" for the local player; an account id in hosted mode
    # (v0.20.0, spec §4.4). Set when the session is built.
    owner: str = ""
    # The SaveStore this run autosaves into, resolved ONCE when the session is
    # built (`save_store_for(owner, active slug)`, or the store's injected
    # accessor for owner ""), so a turn never asks the process which store is
    # current. None only for a session built by hand outside `SessionStore`.
    saves: Optional[SaveStore] = None
    # When the session was built (wall time, seconds since the epoch): the
    # admin panel's Sessions page shows it (v0.20.0 T15, ``describe``).
    created: float = field(default_factory=time.time)
    # Hosted (v0.20.0 T15 fix round 1): an admin ended this session's account
    # while a turn was running in it. That turn finishes (it is never cut),
    # but writes NO save and no transcript (``_autosave``), so a purge of the
    # account's folder is never undone; and ``end_after_turn``, called once
    # its turn lock is released (``run_guarded``), releases the session.
    ending: bool = False
    end_after_turn: Optional[Callable[[], None]] = None

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
        #: Called with a session id and the reason (``RELEASED_*``) each time
        #: a live run is released (``delete``, an admin's ``end``, the sweep,
        #: one-session-per-account), after it is gone from the store. Hosted
        #: mode sets it to tell the run's Socket.IO room why
        #: (``session_ended``, v0.21.0) and close it
        #: (``engine.hosting.install``), so an old tab stops hearing it;
        #: None in local mode.
        self.on_release: Optional[Callable[[str, str], None]] = None
        #: When the idle sweep last ran (monotonic), for the hosted sweep on
        #: ``require`` at most once per ``SWEEP_INTERVAL_SECONDS``.
        self._last_sweep = time.monotonic()
        #: Hosted (T15 fix round 2, N3): ``owner_open(owner)`` answers whether
        #: that account may still write -- set by ``engine.hosting.install``
        #: to read the account store (re-read, so a re-enable counts at
        #: once); None in local mode, where nothing is checked.
        self.owner_open: Optional[Callable[[str], bool]] = None
        #: Hosted under the supervisor (v0.20.0 T17, spec §14.10):
        #: ``on_event(event, owner)`` hears ``created``, ``resumed``,
        #: ``released`` (one session per account), ``swept`` and
        #: ``ended_by_admin`` -- an enum and an account id, nothing of the run.
        #: A HOOK ``engine.hosting.install`` sets; None in local mode, and
        #: this module never imports ``engine.hosting`` for it.
        self.on_event: Optional[Callable[[str, str], None]] = None

    def _event(self, event: str, owner: str) -> None:
        """Hand one session event to ``on_event``, if set (no lock held). Never raises."""
        hook = self.on_event
        if hook is None:
            return
        try:
            hook(event, owner)
        except Exception:  # noqa: BLE001 -- a metric must never fail a run
            logger.warning("[session] A session metric was not recorded (operation=on_event, event=%s)", event)

    def _store_for(self, owner: str) -> Any:
        """
        The save store a session of ``owner``'s writes to.

        Owner ``""`` (the local player) goes through the injected accessor,
        which is ``get_save_store`` -- ``save_store_for("", active slug)`` --
        unless a caller passed its own (a balance harness's keeps-nothing
        store, a test's temp store). Any other owner is an account:
        ``save_store_for(owner, active slug)``.
        """
        if owner:
            return save_store_for(owner, None)
        return self._save_store()

    def _take_owned(self, owner: str) -> list[GameSession]:
        """
        Take every live run of ``owner``'s out of the store, holding its turn
        lock (CALLER HOLDS ``_guard``; the locks are tried non-blocking, the
        one kind of acquisition a leaf allows).

        Raises:
            SessionBusy: one of them has a turn running; nothing is taken.
        """
        taken: list[GameSession] = []
        for other in [s for s in self._sessions.values() if s.owner == owner]:
            if not other.lock.acquire(blocking=False):
                for done in taken:
                    done.lock.release()
                logger.info(
                    "[session] Refused: the account's other run has a turn running "
                    "(operation=_take_owned, id=%s)",
                    other.session_id,
                )
                raise SessionBusy()
            taken.append(other)
        for other in taken:
            self._sessions.pop(other.session_id, None)
            self._seen.pop(other.session_id, None)
        return taken

    def _refuse_if_owner_busy(self, owner: str) -> None:
        """
        Hosted: refuse at once, before a run is built, when ``owner``'s other
        run has a turn running (``_build`` decides it again, atomically).

        Raises:
            SessionBusy: it does.
        """
        if not owner or not _hosted():
            return
        with self._guard:
            if any(s.owner == owner and _is_busy(s) for s in self._sessions.values()):
                raise SessionBusy()

    def _build(
        self,
        state: GameState,
        *,
        llm_fn: Optional[LLMFn] = None,
        save_id: str = "",
        ledger: Optional[StoryLedger] = None,
        owner: str = "",
        saves: Any = None,
    ) -> GameSession:
        engine = GameEngine(state)
        resolved_ledger = ledger or StoryLedger()
        # The skills that need the session's memory read it off the engine
        # (``getattr(engine, "ledger", None)``: ``recall_subject``, ``job_stage``).
        # Nothing set it until v0.15, so ``recall_subject`` answered "no ledger
        # in this session" in every live session.
        engine.ledger = resolved_ledger
        session = GameSession(
            engine=engine,
            # One ledger object shared with the agent, not a copy: what the
            # session records after a turn is what the agent reads before the
            # next one.
            storyteller=StorytellerAgent(engine, llm_fn=llm_fn, ledger=resolved_ledger),
            assistant=AssistantAgent(engine, llm_fn=llm_fn),
            save_id=save_id,
            ledger=resolved_ledger,
            owner=owner,
            saves=saves if saves is not None else self._store_for(owner),
        )
        one_per_owner = bool(owner) and _hosted()  # read before the leaf lock
        released: list[GameSession] = []
        with self._guard:
            live = self._sessions.get(state.session_id)
            if live is not None and live.owner != session.owner:
                # A save carrying ANOTHER owner's live session id (a copied
                # save): building it would replace their session and put this
                # owner in their room (rooms are named by the bare id).
                raise SessionConflict(
                    f"session {state.session_id} is live under another owner"
                )
            if one_per_owner:
                # ONE LIVE SESSION PER ACCOUNT (spec §5.4), decided here,
                # atomically with the insert, so two starts at once cannot
                # leave two runs live. The owner's other runs are taken
                # (their turn locks, non-blocking) and released; one with a
                # turn running refuses this build instead.
                released = self._take_owned(owner)
            self._sessions[state.session_id] = session
            self._seen[state.session_id] = time.monotonic()
        for other in released:
            # Outside the leaf: the registries and the release hook take
            # their own locks. Each released run's turn lock stays HELD for
            # good, so a request that found it before the release is refused
            # as busy and the old engine never autosaves over this one (a
            # resume of the same save rebuilds the same id: finding 7).
            self._release(other.session_id, RELEASED_ELSEWHERE)
            self._event("released", other.owner)

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
        owner: Optional[str] = None,
    ) -> GameSession:
        """
        Create a new procgen-backed session and write its first save, into
        ``owner``'s store (``""``: the local player's; None: ``request_owner``,
        the logged-in account in hosted mode).

        ``archetype`` defaults from the active story's manifest rather than
        from the string "wayfarer". ``entry.archetypes`` has been validated and
        published over ``/api/games`` since the multi-game layer landed and
        consumed by nothing -- three places each held their own copy of the
        flagship's answer, so a second story offered its own archetypes in the
        picker and then started every run as a Clockwork wayfarer.

        Hosted mode: the account's other live run is released first (spec
        §5.4).

        Raises:
            OwnerUnset: hosted mode with no owner (``request_owner``).
            SessionBusy: hosted, and the account's other run has a turn
                running.
            SavesFull: hosted, and the account's saves in this story are at
                ``hosting.max_saves_per_story``.
        """
        owner = request_owner(owner) or ""
        self._refuse_if_owner_busy(owner)
        if owner:
            check_save_room(self._store_for(owner))
        state = new_game_state(
            player_name=player_name,
            archetype=archetype or default_archetype(),
            seed=seed,
        )
        saves = self._store_for(owner)
        session = self._build(state, llm_fn=llm_fn, owner=owner, saves=saves)
        session.last_turn = self._opening(state)
        try:
            room = save_room_limit() if owner else None
            # Under the run's turn lock, refused for a closed account (T15
            # fix round 2, N3): a request admitted before an admin disabled
            # the account cannot write its folder back after a purge.
            session.save_id = self.owner_write(session, lambda: saves.save(state, max_rows=room))
        except SaveRoomFull as exc:
            # Another save took the last row since the early check: this run
            # is not kept (v0.20.0 T15, the count and the write one step).
            self.delete(state.session_id)
            raise SavesFull(saves_full_message(exc.limit)) from None
        except AccountClosed:
            self.delete(state.session_id)
            raise
        except OSError as exc:
            logger.warning(
                "[session] Initial save failed (operation=create): %s", exc
            )
        logger.info(
            "[session] Session created (operation=create, id=%s, save=%s)",
            state.session_id,
            session.save_id,
        )
        self._event("created", owner)
        return session

    def resume(
        self,
        save_id: str,
        *,
        llm_fn: Optional[LLMFn] = None,
        owner: Optional[str] = None,
    ) -> GameSession:
        """
        Rehydrate a run from ``owner``'s store (``""``: the local player's;
        None: ``request_owner``, so in hosted mode the logged-in account's,
        where another account's save id is simply not there).

        This is what makes a dropped socket survivable. The client previously
        called /api/game/new on every reconnect, silently discarding the run.

        Hosted mode: the account's other live run is released first (spec
        §5.4); a resume of the save that run came from rebuilds it under the
        same id, and the old engine can no longer save.

        Raises:
            OwnerUnset: hosted mode with no owner (``request_owner``).
            SessionBusy: hosted, and the account's other run has a turn
                running.
        """
        owner = request_owner(owner) or ""
        self._refuse_if_owner_busy(owner)
        saves = self._store_for(owner)
        state, memory = saves.load(save_id)
        session = self._build(
            state,
            llm_fn=llm_fn,
            save_id=save_id,
            ledger=StoryLedger.from_dict(memory),
            owner=owner,
            saves=saves,
        )
        session.last_turn = self._resume_opening(state, session.ledger)
        logger.info(
            "[session] Session resumed (operation=resume, save=%s, day=%s)",
            save_id,
            state.world_day,
        )
        self._event("resumed", owner)
        return session

    def get(self, session_id: str, owner: Optional[str] = None) -> Optional[GameSession]:
        """
        ``require``, answering None where it raises ``KeyError``: owner-checked
        the same way (fix round 1), so no door can skip §6.4 by asking
        ``get``. Hosted with no owner still raises ``OwnerUnset``.
        """
        try:
            return self.require(session_id, owner)
        except OwnerUnset:
            raise
        except KeyError:
            return None

    def describe(self, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        """
        Hosted mode's Sessions page (v0.20.0 T15, spec §14.8): one row per
        live session, a page at a time (``limit`` rows after ``offset``,
        ordered by when each was built, then its id), and how many there are
        in all. A row is EXACTLY ``DESCRIBE_KEYS``: the owner (an account id),
        the session id, the save id, when it was built, its last activity
        (both wall time), the turn count and whether a turn is running.
        Nothing else from the state: no player name, place, day or text.

        Read under the store's guard (a leaf) and NO turn lock: whether a turn
        runs is a non-blocking try of its lock, so a listing never waits on a
        turn; ``turn_number`` is one attribute read.
        """
        limit = max(0, int(limit))
        offset = max(0, int(offset))
        wall, mono = time.time(), time.monotonic()
        with self._guard:
            sessions = sorted(self._sessions.values(), key=lambda s: (s.created, s.session_id))
            total = len(sessions)
            page = sessions[offset : offset + limit]
            rows = [
                {
                    "owner": session.owner,
                    "session_id": session.session_id,
                    "save_id": session.save_id,
                    "created": round(float(session.created), 3),
                    "last_activity": round(wall - (mono - self._seen.get(session.session_id, mono)), 3),
                    "turns": int(getattr(session.engine.state, "turn_number", 0) or 0),
                    "turn_running": _is_busy(session),
                }
                for session in page
            ]
        return rows, total

    def end(self, session_id: str) -> None:
        """
        An admin ends a live session (v0.20.0 T15, spec §14.8): released
        through ``delete`` and the release hook, exactly as the idle sweep
        releases one. REFUSED while its turn lock is held: a turn is never
        cut mid-flight. The check and the take are one step under the guard
        (the turn lock tried non-blocking and then KEPT, as the sweep keeps
        it), so no turn can start between them, and a request that found the
        session before it was ended is refused as busy.

        Raises:
            KeyError: no such live session.
            SessionBusy: a turn is running in it.
        """
        with self._guard:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"Unknown session: {session_id}")
            if not session.lock.acquire(blocking=False):
                raise SessionBusy(TURN_RUNNING)
            # Taken out in the same step as the check (fix round 1, M1): a
            # second end, or a request racing this one, finds it missing,
            # never "busy" behind a lock nobody will release.
            self._sessions.pop(session_id, None)
            self._seen.pop(session_id, None)
        logger.info("[session] Ended by an admin (operation=end, id=%s)", session_id)
        self._release(session_id, RELEASED_ENDED)
        self._event("ended_by_admin", session.owner)

    def end_owner(self, owner: str) -> tuple[int, int]:
        """
        ``end`` every live session of ``owner`` (an account disabled or
        deleted, v0.20.0 T15). A session with a turn running is not cut: it
        is marked ENDING (fix round 1, I1) -- its turn finishes but saves
        nothing, so a purge of the account's folder is never undone by it --
        and it is released as soon as that turn gives its lock back
        (``end_after_turn``). Returns ``(ended, busy)``: ``busy`` counts the
        ones still finishing a turn.
        """
        if not owner:
            return 0, 0
        with self._guard:
            ids = [s.session_id for s in self._sessions.values() if s.owner == owner]
        ended = busy = 0
        for session_id in ids:
            try:
                self.end(session_id)
                ended += 1
            except SessionBusy:
                busy += 1
                self._end_when_done(session_id)
            except KeyError:
                continue  # released meanwhile
        return ended, busy

    def owner_write(self, session: GameSession, write: Callable[[], Any]) -> Any:
        """
        Run ``write`` -- a save outside a turn (a new run's first save, a
        manual save) -- as a turn runs: under the session's turn lock, taken
        non-blocking (T15 fix round 2, N3). So an admin's ``end_owner`` that
        comes meanwhile finds the session BUSY and marks it ending (and a
        purge then waits), never ends it under the write. Refused, nothing
        written, when the lock is taken (a turn, or an end that already took
        it), the session is ending, or its account may no longer write
        (``owner_open``). Local mode (owner ""): ``write()`` as before.

        Raises:
            SessionBusy: a turn holds the lock.
            AccountClosed: the account is closed, or its sessions ending.
        """
        if not session.owner or self.owner_open is None:
            return write()
        if not session.lock.acquire(blocking=False):
            with self._guard:
                gone = self._sessions.get(session.session_id) is not session
            if gone:
                raise AccountClosed()
            raise SessionBusy("A turn is already in progress.")
        try:
            # Read outside the guard (a file read): the turn lock is what
            # orders this write against an admin's end.
            if session.ending or not self.owner_open(session.owner):
                logger.info(
                    "[session] Write refused: the account is closed (operation=owner_write, id=%s)",
                    session.session_id,
                )
                raise AccountClosed()
            return write()
        finally:
            session.lock.release()
            after = session.end_after_turn
            if after is not None:
                after()

    def _end_when_done(self, session_id: str) -> None:
        """Mark a session whose turn is running ENDING: no save from that turn; released after it."""
        with self._guard:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.ending = True

            def after_turn() -> None:
                try:
                    self.end(session_id)
                except SessionBusy:
                    pass  # another turn took it first: its own end releases it
                except KeyError:
                    pass  # gone already

            session.end_after_turn = after_turn
        logger.info("[session] Ending after its turn (operation=end_owner, id=%s)", session_id)

    def turns_running(self) -> int:
        """
        How many sessions hold their turn lock now (each tried non-blocking,
        under the leaf ``_guard``). A hosted worker's ``drain`` waits for 0
        (v0.20.0 T10, spec §14.3).
        """
        with self._guard:
            return sum(1 for session in self._sessions.values() if _is_busy(session))

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

        HOSTED MODE TURNS IT ON (spec §5.4): ``hosting.enabled`` counts as
        ``idle_sweep_enabled: true``, with the same ``idle_ttl_minutes``. A
        released run is on disk, autosaved every turn, and the client's
        reconnect ``resume`` rebuilds it.

        The check and the release are one step: an idle session is taken out
        of the store holding its turn lock (tried non-blocking, under the
        store's guard), so a turn cannot start on it between the two, and the
        lock is kept, so a request that found it earlier is refused as busy.

        Returns:
            The session ids released.
        """
        from engine.config import get_config

        cfg = get_config()
        if not (bool(cfg.get("session.idle_sweep_enabled", False)) or _hosted()):
            return []
        if ttl_minutes is None:
            ttl_minutes = float(cfg.get("session.idle_ttl_minutes", 60))
        # Floored at one minute on purpose: a misconfigured `idle_ttl_minutes: 0`
        # would otherwise evict every session on the next `create`, including
        # the one the player is sitting in.
        now = time.monotonic()
        cutoff = now - max(1.0, float(ttl_minutes)) * 60.0

        stale: list[str] = []
        owners: list[str] = []
        with self._guard:
            self._last_sweep = now
            for sid, session in list(self._sessions.items()):
                if self._seen.get(sid, 0.0) >= cutoff:
                    continue
                if not session.lock.acquire(blocking=False):
                    continue  # a turn is running: never evicted, whatever its age
                self._sessions.pop(sid, None)
                self._seen.pop(sid, None)
                stale.append(sid)
                owners.append(session.owner)

        for session_id, owner in zip(stale, owners):
            logger.info(
                "[session] Releasing idle session (operation=sweep_idle, id=%s)",
                session_id,
            )
            self._release(session_id, RELEASED_IDLE)
            self._event("swept", owner)
        return stale

    def _sweep_if_due(self) -> None:
        """Hosted: the idle sweep, at most once per ``SWEEP_INTERVAL_SECONDS``."""
        with self._guard:
            if time.monotonic() - self._last_sweep < SWEEP_INTERVAL_SECONDS:
                return
            self._last_sweep = time.monotonic()
        try:
            self.sweep_idle()
        except Exception as exc:  # noqa: BLE001 -- housekeeping must not fail a request
            logger.warning("[session] Idle sweep failed (operation=require): %s", exc)

    def require(self, session_id: str, owner: Optional[str] = None) -> GameSession:
        """
        The live session ``session_id``, if ``owner`` may see it.

        ``owner`` None reads ``request_owner``: no check in local mode, the
        logged-in account in hosted mode. A session owned by anyone else is
        answered EXACTLY as a missing one (the same ``KeyError``), so another
        player's ids cannot even be probed for existence; nor is its idle
        clock touched.

        Raises:
            KeyError: no such session, or not ``owner``'s (``OwnerUnset`` when
                hosted mode has no owner set).
        """
        wanted = request_owner(owner)
        with self._guard:
            session = self._sessions.get(session_id)
            if session is None or (wanted is not None and session.owner != wanted):
                raise KeyError(f"Unknown session: {session_id}")
            self._seen[session_id] = time.monotonic()
        # Hosted (spec §5.4): a quiet server would otherwise never sweep, as
        # the sweep ran only when a run was built. This request's own session
        # was touched above, so it is not idle.
        if _hosted():
            self._sweep_if_due()
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

        Then the release hook (``on_release``, reason ``ended``), which
        hosted mode sets to tell the run's room and close it.
        """
        with self._guard:
            self._sessions.pop(session_id, None)
            self._seen.pop(session_id, None)
        self._release(session_id, RELEASED_ENDED)

    def _release(self, session_id: str, reason: str) -> None:
        """
        Everything ``delete`` does after the store has forgotten the run: the
        engine and skills registries, then the release hook, given ``reason``
        (one of the ``RELEASED_*`` constants). Never raises.
        """
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

        hook = self.on_release
        if hook is not None:
            try:
                hook(session_id, reason)
            except Exception as exc:  # noqa: BLE001 -- see docstring
                logger.warning(
                    "[session] Release hook failed (operation=_release, id=%s): %s",
                    session_id,
                    exc,
                )


def _hosted() -> bool:
    """``hosting.enabled``, read from config (never an ``engine.hosting`` import)."""
    from engine.config import hosting_enabled

    return hosting_enabled()


__all__ = [
    "FALLBACK_ARCHETYPE",
    "GameSession",
    "OTHER_WINDOW_BUSY",
    "OpeningBuilder",
    "OwnerUnset",
    "ResumeBuilder",
    "SWEEP_INTERVAL_SECONDS",
    "SavesFull",
    "SessionBusy",
    "ACCOUNT_CLOSED",
    "AccountClosed",
    "DESCRIBE_KEYS",
    "TURN_RUNNING",
    "check_save_room",
    "save_room_limit",
    "saves_full_message",
    "SessionConflict",
    "SessionStore",
    "current_owner",
    "default_archetype",
    "request_owner",
]

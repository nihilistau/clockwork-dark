"""
Save Store
==========

Reading and writing runs to disk.

There was no persistence at all before this: sessions lived in a process dict
and died with the process -- or, worse, with any socket reconnect, since the
client called /api/game/new on every connect event.

Layout::

    data/saves/
      <game_slug>/                   one namespace per game (see saves_root)
        index.json                   summaries for the load menu
        <save_id>/
          save.json                  envelope: metadata + full GameState
          save.json.bak              previous good write
          memory.json                StoryLedger (P2), split to keep saves diffable
          transcript.jsonl           append-only narration log, never read back

THE GAME SLUG IN THE PATH: saves were flat under ``data/saves/`` while there
was only ever one story. With four, a flat namespace means one load menu
listing runs from all of them, and ``index.json`` written by whichever was
launched last -- and a Wicked Garden save restored into The Clockwork Dark is a
state object full of location ids that do not exist in the graph, with meters
the flagship has never declared. Namespacing is the cheap fix, and the legacy
flat layout is migrated on first use.

THE LOAD-MENU ROW IS STORY-DECLARED. ``SaveSummary`` had twelve required fields
including ``evil_phase`` and ``archetype``, so indexing a run of a story with no
doom clock and no archetypes meant filling in two columns that mean nothing --
or crashing on a dataclass that will not construct. The twelve are still there,
now all defaulted, and a story adds its OWN columns by naming declared state
values in ``save_summary:`` in its ``game.yaml``. Those are projected through the
state schema, which already knows what is player-facing; a hidden value is
refused, because the load menu is a screen the player reads.

A story that declares none gets the row it always got, byte for byte -- the
``values`` key is emitted only when it is non-empty.

Version: v0.4.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from engine.config import get_config
from engine.game.state import CURRENT_SAVE_VERSION, GameState

# ONE home for the engine's version: engine/games/__init__.py is authoritative
# (it is what manifests' ``engine_requires`` gates against), and the save
# envelope imports it rather than repeating the string. tests/test_games.py
# asserts the two agree, which this import makes true by construction.
from engine.games import ENGINE_VERSION  # noqa: F401  (re-exported)
from engine.locks import renew_after_fork
from engine.names import is_portable_name
from engine.persistence.atomic import append_jsonl, read_json, write_json_atomic
from engine.persistence.migrations import MigrationError, migrate
from engine.persistence import storage

logger = logging.getLogger(__name__)

AUTOSAVE_SLOT = "auto"

#: What a save id -- and a loaded save's ``session_id`` -- may be: a NAME,
#: never a path (v0.20.0, spec §4.3). ``_dir`` used to be ``root / save_id``
#: with every door passing its id straight through, so ``..``, ``.``, an
#: absolute path and, on Windows, ``..\\..\\x`` and ``C:\\x`` (which Flask's
#: router hands over from ``..%5c..%5cx`` and ``C:%5cx``) all reached outside
#: the store: a ``DELETE`` unlinked every plain file in the directory it named.
#: Every minted id (``uuid4().hex[:12]``) matches.
SAVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def missing_save_message(save_id: str) -> str:
    """The words for a save that is not there, or whose id is not ours."""
    return f"No readable save: {save_id}"


class InvalidSaveId(ValueError):
    """
    A save id (or a loaded save's session id) that is not a name we allow.

    ITS OWN CLASS so the doors can answer exactly this as a missing save and
    nothing else: a save that is there and will not load (a corrupt envelope,
    a bad enum in its state) raises some other ``ValueError``, which is an
    error the owner's log must name, never a silent "not found".
    """


class SaveRoomFull(RuntimeError):
    """
    A save that would add a row to an index already at its ``max_rows``
    (hosted mode's ``hosting.max_saves_per_story``, v0.20.0 T15): refused,
    nothing written. The session package answers it as ``SavesFull``.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(f"the index holds {int(limit)} rows")
        self.limit = int(limit)


def check_save_id(save_id: Any, *, what: str = "save id") -> str:
    """
    ``save_id``, if it is a name ``SAVE_ID_RE`` allows and a portable one
    (``engine.names``: no Windows device name such as ``NUL`` or ``con``, on
    every OS, so a save tree means the same thing everywhere).

    Raises:
        InvalidSaveId: Anything else. The doors answer it as a missing save,
            so an id that is not ours looks exactly like one that does not
            exist.
    """
    if (
        not isinstance(save_id, str)
        or not SAVE_ID_RE.fullmatch(save_id)
        or not is_portable_name(save_id)
    ):
        raise InvalidSaveId(f"not a {what}: {save_id!r}")
    return save_id


@dataclass
class SaveSummary:
    """
    One row in the load menu.

    Every field is defaulted. They were all required, which meant a story with
    no ``archetype`` and no ``evil_phase`` could not build a row at all -- the
    load menu was as Clockwork-shaped as the state model underneath it.
    ``archetype`` and ``evil_phase`` default to empty rather than being removed,
    because The Clockwork Dark's rows must stay exactly what they were.

    Attributes:
        values: Story-declared columns, ``{name: {"label": ..., "value": ...}}``
            or ``{"label": ..., "band": ...}`` for a veiled value. Empty for a
            story that declares no ``save_summary``, and omitted from
            ``to_dict`` when empty so the shipped stories' rows do not change.
    """

    save_id: str = ""
    slot: str = AUTOSAVE_SLOT
    player_name: str = ""
    archetype: str = ""
    world_day: int = 1
    world_hour: int = 0
    location_id: str = ""
    evil_phase: str = ""
    turn_number: int = 0
    updated_at: float = 0.0
    save_version: int = CURRENT_SAVE_VERSION
    thumbnail: str = ""
    values: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "save_id": self.save_id,
            "slot": self.slot,
            "player_name": self.player_name,
            "archetype": self.archetype,
            "world_day": self.world_day,
            "world_hour": self.world_hour,
            "location_id": self.location_id,
            "evil_phase": self.evil_phase,
            "turn_number": self.turn_number,
            "updated_at": self.updated_at,
            "save_version": self.save_version,
            "thumbnail": self.thumbnail,
        }
        if self.values:
            row["values"] = dict(self.values)
        return row


def summary_values(state: GameState) -> dict[str, Any]:
    """
    The story-declared columns for one run, projected through its state schema.

    Reads ``save_summary:`` off the active manifest and resolves each name
    against the story's declared state. Visibility is honoured exactly as it is
    on the wire to the browser: a public value ships its number, a veiled value
    ships only its band, and a hidden value is REFUSED with a warning -- the
    load menu is a screen the player reads, so leaking a hidden meter there
    would be the same defect as leaking it into a turn payload.

    Args:
        state: The run being indexed.

    Returns:
        ``{name: row}``, empty when the story declares nothing or when the
        schema cannot be read. Never raises: an unindexable column must not be
        the reason a save fails to write.
    """
    try:
        from engine.state.active import active_schema, store_for
        from engine.state.schema import VISIBILITY_HIDDEN, VISIBILITY_VEILED

        schema = active_schema()

        # The schema is the source: a column list naming values declared in a
        # DIFFERENT file is a rename waiting to break silently, and state.yaml
        # can validate its own columns at load -- which it does, refusing a
        # hidden one outright rather than discovering it here per save.
        #
        # The manifest stays as the fallback so a story can still name columns
        # without declaring a schema, and so the shipped games are unaffected.
        declared = schema.summary
        if not declared:
            from engine.games.registry import entry_manifest

            manifest = entry_manifest()
            declared = manifest.save_summary if manifest is not None else ()
        if not declared:
            return {}

        store = store_for(state)

        out: dict[str, Any] = {}
        for name in declared:
            spec = schema.get(name)
            if spec is None:
                logger.warning(
                    "[persistence] save_summary names an undeclared value "
                    "(operation=summary_values, name=%s)",
                    name,
                )
                continue
            if spec.visibility == VISIBILITY_HIDDEN:
                logger.warning(
                    "[persistence] save_summary names a hidden value, refusing "
                    "(operation=summary_values, name=%s)",
                    name,
                )
                continue
            row: dict[str, Any] = {"label": spec.display_label, "kind": spec.kind}
            value = store.get(name)
            if spec.visibility == VISIBILITY_VEILED:
                row["band"] = spec.band(value)
            else:
                row["value"] = value
            out[name] = row
        return out
    except Exception as exc:  # noqa: BLE001 -- a save must always be writable
        logger.warning(
            "[persistence] Could not project save summary values "
            "(operation=summary_values): %s",
            exc,
        )
        return {}


# Legacy migration runs at most once per process. The check is two stat calls,
# but saves_root() is called on every store construction and a filesystem walk
# per call would be absurd.
#
# Checked, migrated and then recorded under ``_migrated_lock`` (v0.20.0): it was
# added BEFORE the migration ran, so a second thread's first store for the
# same story went on while the first was still moving the files.
_migrated: set[str] = set()
_migrated_lock = threading.Lock()
renew_after_fork(globals(), _migrated_lock=threading.Lock)


def saves_base() -> Path:
    """
    The local player's un-namespaced save directory: ``<storage root>/saves``
    (``engine/persistence/storage.py``; v0.20.0), anchored at the repository,
    never the working directory. THE one seam every owner-``""`` save root is
    built from, and the one ``tests/conftest.py`` redirects.
    """
    return storage.saves_dir("", None)


def _migrate_legacy(base: Path, slug: str) -> None:
    """
    Move a pre-namespacing ``data/saves/`` tree into ``data/saves/<slug>/``.

    Detected by an ``index.json`` sitting directly in the base directory --
    the namespaced layout never has one there. Every save directory beside it
    moves with it; a name that already exists in the destination is left alone
    rather than overwritten, because losing somebody's run to a migration is
    the one outcome worse than an untidy directory.

    Args:
        base: The un-namespaced save directory.
        slug: Game to migrate the legacy runs into.
    """
    legacy_index = base / "index.json"
    if not legacy_index.is_file():
        return

    destination = base / slug
    destination.mkdir(parents=True, exist_ok=True)
    moved = 0
    for child in list(base.iterdir()):
        if child.name == slug:
            continue
        if child.is_dir() and not (child / "save.json").is_file():
            # Some other game's namespace, or a stray directory. Not ours.
            continue
        target = destination / child.name
        if target.exists():
            logger.warning(
                "[persistence] Legacy save already migrated, leaving in place "
                "(operation=_migrate_legacy, name=%s)",
                child.name,
            )
            continue
        try:
            child.rename(target)
            moved += 1
        except OSError as exc:
            logger.warning(
                "[persistence] Could not migrate legacy save "
                "(operation=_migrate_legacy, name=%s): %s",
                child.name,
                exc,
            )

    logger.info(
        "[persistence] Migrated legacy saves into a game namespace "
        "(operation=_migrate_legacy, slug=%s, entries=%d)",
        slug,
        moved,
    )


def saves_root(slug: Optional[str] = None) -> Path:
    """
    Save directory for a game.

    Args:
        slug: Game slug, or None for the active game.

    Returns:
        ``<saves_base()>/<slug>``. The legacy flat layout is folded into the
        active game's namespace the first time this is called for it.
    """
    base = saves_base()

    if slug is None:
        # Imported lazily: engine.games.registry resets this module's cached
        # store, so a module-level import would be a cycle.
        from engine.games.registry import active_slug

        slug = active_slug()

    if slug not in _migrated:
        with _migrated_lock:
            if slug not in _migrated:
                try:
                    _migrate_legacy(base, slug)
                except OSError as exc:  # noqa: PERF203 -- diagnostics beat a crash here
                    logger.warning(
                        "[persistence] Legacy save migration failed "
                        "(operation=saves_root, slug=%s): %s",
                        slug,
                        exc,
                    )
                finally:
                    # Recorded whatever happened: a failure is not retried.
                    _migrated.add(slug)

    return base / slug


#: Every save folder's index lock, keyed by the folder's resolved path, case
#: folded (v0.20.0 T8). Every ``SaveStore`` for one folder shares its lock,
#: whichever cache built it and whenever: a store a config reset dropped and
#: its replacement included, and two owner ids differing only in case on a
#: case-insensitive file system. Weak values: a lock lives exactly as long as
#: some store holds it, so the registry holds only live folders. Read and
#: filled under ``_index_locks_lock`` (engine/locks.py's order).
#:
#: AFTER A FORK the registry is emptied along with its lock, and the cached
#: stores (``_stores``) are dropped with it (fix round 1): a folder's RLock
#: that another thread of the parent held at fork would be held forever in
#: the child, so the child builds its stores, and their locks, afresh.
_index_locks: "weakref.WeakValueDictionary[str, Any]" = weakref.WeakValueDictionary()
_index_locks_lock = threading.Lock()
renew_after_fork(
    globals(),
    _index_locks_lock=threading.Lock,
    _index_locks=weakref.WeakValueDictionary,
    _stores=lambda: None,
)


def _folder_key(root: Path) -> str:
    """``root`` as the registry keys it: absolute, resolved, case folded."""
    try:
        resolved = Path(root).resolve()
    except OSError:
        resolved = Path(os.path.abspath(root))
    return os.path.normcase(str(resolved)).casefold()


def index_lock_for(root: Path) -> Any:
    """
    The one index lock of the save folder ``root`` (an ``RLock``), made on
    first use. Folding case can only make two folders SHARE a lock on a
    case-sensitive file system, which costs a wait, never a lost write.
    """
    key = _folder_key(root)
    with _index_locks_lock:
        lock = _index_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _index_locks[key] = lock
        return lock


class SaveStore:
    """
    File-backed save storage for ONE story.

    Args:
        root: Save directory, or None for the active game's namespace.
        slug: Story these saves belong to. Defaults to the active game when
            ``root`` is None, else to the directory name -- which is right,
            because ``saves_root`` builds the directory from the slug. The slug
            is what selects the story's migration chain, so guessing it wrong
            must be impossible rather than merely unlikely.
    """

    def __init__(self, root: Optional[Path] = None, slug: Optional[str] = None) -> None:
        if root is None:
            self.root = saves_root(slug)
            if not slug:
                from engine.games.registry import active_slug

                slug = active_slug()
        else:
            self.root = Path(root)
            slug = slug or self.root.name
        self.slug = str(slug)
        # The index is read-modify-written on every autosave, and this store is
        # shared, one per (owner, slug) (`save_store_for`), by every session
        # under threading-mode Socket.IO. Two sessions autosaving in the same
        # window both loaded the index before either wrote it, so the second
        # write dropped the first's entry: the `save.json` survived on disk and
        # the run vanished from the load menu forever. Reentrant because
        # `compact()` calls the same guarded helpers.
        #
        # ONE LOCK PER FOLDER, not per store (v0.20.0 T8): a config reset
        # drops the cached stores while a turn may still be saving through
        # the old one, and its replacement for the same folder must take the
        # SAME lock, or two writers race one `index.json` (on Windows the
        # second `os.replace` fails and that autosave is lost).
        self._lock = index_lock_for(self.root)

    # -- paths -----------------------------------------------------------

    def _dir(self, save_id: str) -> Path:
        """
        The run's directory. THE ONE DOOR every method that names a save goes
        through (``save``, ``load``, ``exists``, ``delete``,
        ``append_transcript``), so an id outside ``SAVE_ID_RE`` is refused
        here, with ``InvalidSaveId``, before any path is built from it.
        """
        directory = self.root / check_save_id(save_id)
        # Case (review finding 5): on Windows `abc` and `ABC` are ONE
        # directory, so a second id differing only in case would read, share
        # and delete the first run's files. `resolve()` returns the name as it
        # is on disk there, so a directory found under another case is the
        # other run's, and the id is refused -- on every OS, so a save tree
        # means the same thing wherever it is copied.
        if directory.exists() and directory.resolve().name != save_id:
            raise InvalidSaveId(f"differs only in case from an existing save: {save_id!r}")
        return directory

    def _case_twin(self, save_id: str, index: dict[str, Any]) -> Optional[str]:
        """
        An existing save id that differs from ``save_id`` only in case, for a
        NEW id on a case-sensitive filesystem (where ``_dir`` sees nothing):
        from the index, then the directories on disk.
        """
        folded = save_id.casefold()
        names = set(index)
        try:
            with os.scandir(self.root) as entries:
                names.update(e.name for e in entries if e.is_dir())
        except OSError:
            pass
        for name in names:
            if name != save_id and name.casefold() == folded:
                return name
        return None

    def _index_path(self) -> Path:
        return self.root / "index.json"

    # -- index -----------------------------------------------------------

    def _load_index(self) -> dict[str, dict[str, Any]]:
        raw = read_json(self._index_path()) or {}
        entries = raw.get("saves", []) if isinstance(raw, dict) else []
        return {e["save_id"]: e for e in entries if isinstance(e, dict) and "save_id" in e}

    def _index_limit(self) -> int:
        try:
            return max(1, int(get_config().get("saves.index_max_entries", 200)))
        except Exception:  # noqa: BLE001 -- a config miss must not block a save
            return 200

    def _write_index(
        self, entries: dict[str, dict[str, Any]], *, limit: int, keep_backup: bool = False
    ) -> None:
        """
        Persist the index, newest first, bounded.

        THE BOUND IS NOT COSMETIC. This file is parsed, re-serialised and
        fsynced on every autosave -- i.e. every turn -- and it grows by one
        entry per run ever started, forever, with nothing anywhere that ever
        removed one. A working checkout measured 537 KB across 1302 entries,
        which is a megabyte of JSON I/O per turn to record a single change.

        MANUAL SLOTS ARE NEVER DROPPED. Only autosaves are, oldest first: the
        index IS the load menu (`list_saves`), so pruning a save the player
        deliberately named would delete their run from the only place they can
        see it. An autosave is by definition the one the engine will replace
        anyway.

        ``limit`` is ``_index_limit()``, read by the caller BEFORE it takes
        ``self._lock``: the index lock is a leaf (engine/locks.py), and its
        holder takes no other lock, the config's included.
        """
        ordered = sorted(
            entries.values(), key=lambda e: e.get("updated_at", 0.0), reverse=True
        )
        if len(ordered) > limit:
            keep: list[dict[str, Any]] = []
            autos: list[dict[str, Any]] = []
            for entry in ordered:
                if str(entry.get("slot", "")) == AUTOSAVE_SLOT:
                    autos.append(entry)
                else:
                    keep.append(entry)
            room = max(0, limit - len(keep))
            dropped = len(autos) - room
            if dropped > 0:
                logger.info(
                    "[persistence] Index pruned (operation=_write_index, "
                    "dropped=%d, kept=%d, limit=%d)",
                    dropped,
                    len(keep) + room,
                    limit,
                )
            ordered = sorted(
                keep + autos[:room],
                key=lambda e: e.get("updated_at", 0.0),
                reverse=True,
            )
        write_json_atomic(
            self._index_path(), {"saves": ordered}, keep_backup=keep_backup
        )

    def reindex(self) -> int:
        """
        Rebuild the index from the save files actually on disk.

        THE INVERSE OF PRUNING, and the reason pruning is safe. The index is a
        derived listing, not the data: every run's real content is its own
        `save.json`, and dropping a row hides a run from the load menu without
        touching it. This walks the directories and puts every readable save
        back, newest first.

        Also the repair for an index that was corrupted, truncated, or written
        by a build that disagreed about the summary shape -- all of which used
        to mean the run was simply gone as far as the player could tell.

        Bounded by the same `saves.index_max_entries` afterwards, so calling
        this on a directory with thousands of runs does not undo the bound; it
        restores the NEWEST that fit. Raise the config key first if you want
        more of them back.

        Returns:
            How many entries the index holds afterwards.
        """
        limit = self._index_limit()
        with self._lock:
            rebuilt: dict[str, dict[str, Any]] = {}
            for directory in sorted(p for p in self.root.iterdir() if p.is_dir()):
                # A directory no door could name (`foo.bak`, a copy made by
                # hand) would be a load-menu row that answers "not found".
                save_id = ""
                try:
                    check_save_id(directory.name)
                    envelope = read_json(directory / "save.json")
                    if not isinstance(envelope, dict):
                        continue
                    save_id = check_save_id(str(envelope.get("save_id") or directory.name))
                except InvalidSaveId:
                    logger.warning(
                        "[persistence] Reindex skipped a directory whose name is "
                        "not a save id (operation=reindex, name=%.80r, id=%.80r)",
                        directory.name,
                        save_id,
                    )
                    continue
                raw_state = envelope.get("state")
                if not isinstance(raw_state, dict):
                    continue
                known = SaveSummary.__dataclass_fields__.keys()
                row = {
                    "save_id": save_id,
                    "slot": str(envelope.get("slot") or AUTOSAVE_SLOT),
                    "updated_at": float(envelope.get("updated_at") or 0.0),
                    "player_name": str(raw_state.get("player_name") or ""),
                    "archetype": str(raw_state.get("archetype") or ""),
                    "world_day": int(raw_state.get("world_day") or 0),
                    "world_hour": int(raw_state.get("world_hour") or 0),
                    "location_id": str(raw_state.get("location_id") or ""),
                    "evil_phase": str(raw_state.get("evil_phase") or ""),
                    "turn_number": int(raw_state.get("turn_number") or 0),
                }
                rebuilt[save_id] = {k: v for k, v in row.items() if k in known}
                rebuilt[save_id]["created_at"] = float(
                    envelope.get("created_at") or row["updated_at"]
                )
            self._write_index(rebuilt, limit=limit, keep_backup=True)
            total = len(self._load_index())
        logger.info(
            "[persistence] Reindexed (operation=reindex, found=%d, indexed=%d)",
            len(rebuilt),
            total,
        )
        return total

    def compact(self) -> int:
        """
        Re-write the index down to its configured bound, once.

        For a checkout that accumulated entries before the bound existed --
        pruning otherwise only happens on the next save, and a story nobody is
        currently playing never gets one. Keeps a backup, because this is the
        only operation here that removes rows the player did not ask to remove.

        Returns:
            How many entries were dropped.
        """
        limit = self._index_limit()
        with self._lock:
            index = self._load_index()
            before = len(index)
            self._write_index(index, limit=limit, keep_backup=True)
            after = len(self._load_index())
        logger.info(
            "[persistence] Compacted (operation=compact, before=%d, after=%d)",
            before,
            after,
        )
        return before - after

    def list_saves(self) -> list[SaveSummary]:
        """Return all known saves, newest first."""
        summaries: list[SaveSummary] = []
        for entry in self._load_index().values():
            known = SaveSummary.__dataclass_fields__.keys()
            summaries.append(
                SaveSummary(**{k: v for k, v in entry.items() if k in known})
            )
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    # -- write -----------------------------------------------------------

    def save(
        self,
        state: GameState,
        *,
        save_id: Optional[str] = None,
        slot: str = AUTOSAVE_SLOT,
        memory: Optional[dict[str, Any]] = None,
        max_rows: Optional[int] = None,
    ) -> str:
        """
        Persist a run. Returns the save_id.

        Args:
            state: Game state to write.
            save_id: Reuse an existing save, or None to mint one.
            slot: "auto" or a manual slot label.
            memory: Optional StoryLedger payload, written alongside.
            max_rows: Hosted mode's ``hosting.max_saves_per_story`` (v0.20.0
                T15, from T9's review): a save that would ADD a row to an
                index already holding this many is refused. The count and
                the write are ONE step under the folder's index lock, so two
                saves at once cannot both pass the count at the cap less one
                and both write. None (local mode): never limited.

        Raises:
            SaveRoomFull: ``max_rows`` given, and no room for a new row
                (nothing is written).
        """
        chosen = bool(save_id)
        save_id = save_id or uuid.uuid4().hex[:12]
        directory = self._dir(save_id)
        if chosen and not directory.exists():
            # A new run under an id the CALLER chose: it must not be another's
            # in another case (see `_dir`, which covers an id whose directory
            # already exists). A minted id is lowercase hex and never is.
            with self._lock:
                twin = self._case_twin(save_id, self._load_index())
            if twin is not None:
                raise InvalidSaveId(
                    f"differs only in case from an existing save: {save_id!r}"
                )
        now = time.time()

        envelope = {
            "save_version": CURRENT_SAVE_VERSION,
            "engine_version": ENGINE_VERSION,
            # Which story wrote this. Saves are already namespaced by directory,
            # but the directory can be moved, copied or restored from a backup,
            # and the migration chain that runs over a document must be chosen
            # by what the document IS, not by where it was found.
            "game": self.slug,
            "save_id": save_id,
            "slot": slot,
            "updated_at": now,
            "state": state.to_save_dict(),
        }

        # Built before the lock: summary_values and the index bound read the
        # story's schema and config, and the index lock is a leaf.
        summary = SaveSummary(
            save_id=save_id,
            slot=slot,
            player_name=state.player_name,
            archetype=getattr(state, "archetype", "") or "",
            world_day=state.world_day,
            world_hour=state.world_hour,
            location_id=state.location_id,
            evil_phase=(
                getattr(getattr(state, "evil_phase", None), "value", "") or ""
            ),
            turn_number=state.turn_number,
            updated_at=now,
            values=summary_values(state),
        ).to_dict()
        limit = self._index_limit()

        def write_files() -> None:
            write_json_atomic(directory / "save.json", envelope)
            if memory is not None:
                write_json_atomic(directory / "memory.json", memory)

        if max_rows is None:
            write_files()
        # Read-modify-write under the lock: see SaveStore.__init__. With a
        # cap, the count and every write are under it too (the files are
        # written only once the count has room), so no second save can count
        # between this one's count and its row.
        with self._lock:
            index = self._load_index()
            if max_rows is not None:
                if save_id not in index and len(index) >= int(max_rows):
                    raise SaveRoomFull(int(max_rows))
                write_files()
            created = index.get(save_id, {}).get("created_at", now)
            index[save_id] = summary
            index[save_id]["created_at"] = created
            self._write_index(index, limit=limit)

        logger.info(
            "[persistence] Saved (operation=save, id=%s, slot=%s, day=%s, turn=%s)",
            save_id,
            slot,
            state.world_day,
            state.turn_number,
        )
        return save_id

    def append_transcript(self, save_id: str, record: dict[str, Any]) -> None:
        """Append one turn to the run's narration log."""
        append_jsonl(self._dir(save_id) / "transcript.jsonl", record)

    # -- read ------------------------------------------------------------

    def load(self, save_id: str) -> tuple[GameState, dict[str, Any]]:
        """
        Load a run, migrating it forward if needed.

        Returns:
            (state, memory) -- memory is {} when the run predates the ledger.

        Raises:
            FileNotFoundError: No such save.
            InvalidSaveId: ``save_id`` is not a name ``SAVE_ID_RE`` allows, or
                the save's own ``session_id`` is not (below).
            MigrationError: Save is from a newer build or unmigratable.
        """
        envelope = read_json(self._dir(save_id) / "save.json")
        if not isinstance(envelope, dict) or "state" not in envelope:
            raise FileNotFoundError(missing_save_message(save_id))

        raw_state = dict(envelope["state"])
        # The session id is persisted in the save and becomes the socket's
        # room when the run is resumed, so a hand-edited save must not smuggle
        # a path or another run's room in: held to the save id's own pattern.
        # A save written before session ids existed has none, and gets a fresh
        # one from GameState's default.
        if "session_id" in raw_state:
            try:
                check_save_id(raw_state["session_id"], what="session id")
            except InvalidSaveId:
                # Logged: a save that IS there is being refused, and the
                # player is told only that it is missing. The id is repr'd
                # and bounded -- it came out of a file anyone could edit.
                logger.warning(
                    "[persistence] Save refused: its session id is not a name "
                    "(operation=load, id=%s, session id=%.80r)",
                    save_id,
                    raw_state["session_id"],
                )
                raise
        raw_state.setdefault("save_version", envelope.get("save_version", 1))
        # The save says which story it is; a save written before the envelope
        # carried that falls back to the namespace it was found in, which is
        # the directory the store was built for and therefore always right.
        migrated = migrate(raw_state, slug=str(envelope.get("game") or self.slug))
        state = GameState.from_dict(migrated)

        memory = read_json(self._dir(save_id) / "memory.json") or {}
        if not isinstance(memory, dict):
            memory = {}

        logger.info(
            "[persistence] Loaded (operation=load, id=%s, day=%s, turn=%s)",
            save_id,
            state.world_day,
            state.turn_number,
        )
        return state, memory

    def exists(self, save_id: str) -> bool:
        return (self._dir(save_id) / "save.json").exists()

    def delete(self, save_id: str) -> bool:
        """Remove a save and drop it from the index."""
        directory = self._dir(save_id)
        removed = False
        if directory.exists():
            for child in directory.iterdir():
                child.unlink(missing_ok=True)
            directory.rmdir()
            removed = True

        limit = self._index_limit()
        with self._lock:
            index = self._load_index()
            if index.pop(save_id, None) is not None:
                self._write_index(index, limit=limit)
                removed = True

        if removed:
            logger.info("[persistence] Deleted (operation=delete, id=%s)", save_id)
        return removed


#: One store per ``(owner, slug)``, built on first use (v0.20.0, spec §4.4).
#: Each save FOLDER has its own index lock (``index_lock_for``), so two
#: owners' autosaves never wait on each other and never share an
#: ``index.json``, and two stores over one folder share one lock. Nulled with every config
#: reset (``engine/games/caches.py``): a store's root embeds the storage root
#: and the slug. A store is built under ``_stores_lock`` (double-checked: a
#: built one is a dict read), so two first callers share one index lock.
_stores: Optional[dict[tuple[str, str], SaveStore]] = None
_stores_lock = threading.Lock()
renew_after_fork(globals(), _stores_lock=threading.Lock)


def save_store_for(owner: str = "", slug: Optional[str] = None) -> SaveStore:
    """
    The save store for ``owner``'s runs of ``slug`` (None: the active story).

    Owner ``""`` is the local player: ``saves_root(slug)``, whose first use
    folds a pre-namespacing flat ``data/saves/`` into the story's namespace.
    Any other owner is an account, under ``storage.saves_dir(owner, slug)``,
    and NEVER runs that migration: it exists only for the owner's old flat
    directory, and an account's directory never had one.

    Raises:
        InvalidSaveId: ``owner`` is not a name (``check_save_id``'s rule).
        ValueError: ``slug`` is not a valid story slug.
    """
    global _stores
    from engine.games.manifest import is_valid_slug
    from engine.games.registry import active_slug

    if owner:
        # Case-normalised BEFORE it reaches a path or the cache key (v0.20.0
        # T8): on a case-insensitive file system `u_ABC...` and `u_abc...`
        # are one folder, and two stores over it would hold two index locks.
        # Account ids are lower case (`engine/hosting/accounts.ID_RE`).
        owner = check_save_id(owner, what="owner").lower()
    chosen = str(slug) if slug else active_slug()
    if not is_valid_slug(chosen):
        raise ValueError(f"not a story slug: {chosen!r}")
    key = (owner, chosen)
    stores = _stores
    store = stores.get(key) if stores is not None else None
    if store is not None:
        return store
    with _stores_lock:
        # One dict, read once: a config reset nulls ``_stores`` without this
        # lock (engine/games/caches.py), so re-reading the global after the
        # build could find None. A store built across a reset lands in the
        # dropped dict and is still returned; the next call builds afresh.
        stores = _stores
        if stores is None:
            stores = _stores = {}
        store = stores.get(key)
        if store is None:
            if owner:
                store = SaveStore(root=storage.saves_dir(owner, chosen), slug=chosen)
            else:
                store = SaveStore(slug=chosen)
            stores[key] = store
        return store


def get_save_store() -> SaveStore:
    """The store for owner ``""`` and the active story: the local player's."""
    return save_store_for("", None)


def cached_save_stores() -> list[SaveStore]:
    """Every store built since the last reset (the conftest's teardown check)."""
    stores = _stores
    return list((stores or {}).values())


def reset_save_store() -> None:
    """Drop every cached store. Config resets and tests."""
    global _stores
    _stores = None


__all__ = [
    "AUTOSAVE_SLOT",
    "ENGINE_VERSION",
    "InvalidSaveId",
    "MigrationError",
    "SAVE_ID_RE",
    "SaveRoomFull",
    "SaveStore",
    "SaveSummary",
    "cached_save_stores",
    "check_save_id",
    "get_save_store",
    "index_lock_for",
    "missing_save_message",
    "reset_save_store",
    "save_store_for",
    "saves_base",
    "saves_root",
    "summary_values",
]

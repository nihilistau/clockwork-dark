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
was only ever one story. With two, a flat namespace means one load menu listing
runs from both games, and ``index.json`` written by whichever was launched last
-- and a Drowned Carillon save restored into The Clockwork Dark is a state
object full of location ids that do not exist in the graph. Namespacing is the
cheap fix, and the legacy flat layout is migrated on first use.

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
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from engine.config import get_config
from engine.game.state import CURRENT_SAVE_VERSION, GameState
from engine.persistence.atomic import append_jsonl, read_json, write_json_atomic
from engine.persistence.migrations import MigrationError, migrate

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.2.0"
AUTOSAVE_SLOT = "auto"


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
_migrated: set[str] = set()


def saves_base() -> Path:
    """The un-namespaced save directory, straight from ``paths.saves``."""
    return Path(get_config().get("paths.saves", "data/saves"))


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
        ``<paths.saves>/<slug>``. The legacy flat layout is folded into the
        active game's namespace the first time this is called for it.
    """
    base = saves_base()

    if slug is None:
        # Imported lazily: engine.games.registry resets this module's cached
        # store, so a module-level import would be a cycle.
        from engine.games.registry import active_slug

        slug = active_slug()

    if slug not in _migrated:
        _migrated.add(slug)
        try:
            _migrate_legacy(base, slug)
        except OSError as exc:  # noqa: PERF203 -- diagnostics beat a crash here
            logger.warning(
                "[persistence] Legacy save migration failed "
                "(operation=saves_root, slug=%s): %s",
                slug,
                exc,
            )

    return base / slug


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

    # -- paths -----------------------------------------------------------

    def _dir(self, save_id: str) -> Path:
        return self.root / save_id

    def _index_path(self) -> Path:
        return self.root / "index.json"

    # -- index -----------------------------------------------------------

    def _load_index(self) -> dict[str, dict[str, Any]]:
        raw = read_json(self._index_path()) or {}
        entries = raw.get("saves", []) if isinstance(raw, dict) else []
        return {e["save_id"]: e for e in entries if isinstance(e, dict) and "save_id" in e}

    def _write_index(self, entries: dict[str, dict[str, Any]]) -> None:
        ordered = sorted(
            entries.values(), key=lambda e: e.get("updated_at", 0.0), reverse=True
        )
        write_json_atomic(self._index_path(), {"saves": ordered}, keep_backup=False)

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
    ) -> str:
        """
        Persist a run. Returns the save_id.

        Args:
            state: Game state to write.
            save_id: Reuse an existing save, or None to mint one.
            slot: "auto" or a manual slot label.
            memory: Optional StoryLedger payload, written alongside.
        """
        save_id = save_id or uuid.uuid4().hex[:12]
        directory = self._dir(save_id)
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
        write_json_atomic(directory / "save.json", envelope)

        if memory is not None:
            write_json_atomic(directory / "memory.json", memory)

        index = self._load_index()
        created = index.get(save_id, {}).get("created_at", now)
        index[save_id] = SaveSummary(
            save_id=save_id,
            slot=slot,
            player_name=state.player_name,
            archetype=getattr(state, "archetype", "") or "",
            world_day=state.world_day,
            world_hour=state.world_hour,
            location_id=state.location_id,
            evil_phase=getattr(getattr(state, "evil_phase", None), "value", "") or "",
            turn_number=state.turn_number,
            updated_at=now,
            values=summary_values(state),
        ).to_dict()
        index[save_id]["created_at"] = created
        self._write_index(index)

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
            MigrationError: Save is from a newer build or unmigratable.
        """
        envelope = read_json(self._dir(save_id) / "save.json")
        if not isinstance(envelope, dict) or "state" not in envelope:
            raise FileNotFoundError(f"No readable save: {save_id}")

        raw_state = dict(envelope["state"])
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

        index = self._load_index()
        if index.pop(save_id, None) is not None:
            self._write_index(index)
            removed = True

        if removed:
            logger.info("[persistence] Deleted (operation=delete, id=%s)", save_id)
        return removed


_store: Optional[SaveStore] = None


def get_save_store() -> SaveStore:
    """Process-wide save store."""
    global _store
    if _store is None:
        _store = SaveStore()
    return _store


def reset_save_store() -> None:
    """Drop the cached store. Tests only."""
    global _store
    _store = None


__all__ = [
    "AUTOSAVE_SLOT",
    "ENGINE_VERSION",
    "MigrationError",
    "SaveStore",
    "SaveSummary",
    "get_save_store",
    "reset_save_store",
    "saves_base",
    "saves_root",
    "summary_values",
]

"""
Save Store
==========

Reading and writing runs to disk.

There was no persistence at all before this: sessions lived in a process dict
and died with the process -- or, worse, with any socket reconnect, since the
client called /api/game/new on every connect event.

Layout::

    data/saves/
      index.json                     summaries for the load menu
      <save_id>/
        save.json                    envelope: metadata + full GameState
        save.json.bak                previous good write
        memory.json                  StoryLedger (P2), split to keep saves diffable
        transcript.jsonl             append-only narration log, never read back

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
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
    """One row in the load menu."""

    save_id: str
    slot: str
    player_name: str
    archetype: str
    world_day: int
    world_hour: int
    location_id: str
    evil_phase: str
    turn_number: int
    updated_at: float
    save_version: int = CURRENT_SAVE_VERSION
    thumbnail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
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


def saves_root() -> Path:
    """Configured save directory."""
    return Path(get_config().get("paths.saves", "data/saves"))


class SaveStore:
    """File-backed save storage."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else saves_root()

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
            archetype=state.archetype,
            world_day=state.world_day,
            world_hour=state.world_hour,
            location_id=state.location_id,
            evil_phase=state.evil_phase.value,
            turn_number=state.turn_number,
            updated_at=now,
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
        migrated = migrate(raw_state)
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
    "MigrationError",
    "SaveStore",
    "SaveSummary",
    "get_save_store",
    "reset_save_store",
    "saves_root",
]

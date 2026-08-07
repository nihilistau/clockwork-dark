"""Save persistence — atomic JSON writes with forward migrations."""

from engine.persistence.atomic import append_jsonl, read_json, write_json_atomic
from engine.persistence.migrations import MigrationError, migrate
from engine.persistence.saves import (
    AUTOSAVE_SLOT,
    SaveStore,
    SaveSummary,
    get_save_store,
    reset_save_store,
    saves_root,
)

__all__ = [
    "AUTOSAVE_SLOT",
    "MigrationError",
    "SaveStore",
    "SaveSummary",
    "append_jsonl",
    "get_save_store",
    "migrate",
    "read_json",
    "reset_save_store",
    "saves_root",
    "write_json_atomic",
]

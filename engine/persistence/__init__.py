"""Save persistence — atomic JSON writes with forward migrations."""

from engine.persistence.atomic import append_jsonl, read_json, write_json_atomic
from engine.persistence.migrations import (
    MigrationError,
    migrate,
    register_story_migration,
    story_migrations,
)
from engine.persistence.saves import (
    AUTOSAVE_SLOT,
    SaveStore,
    SaveSummary,
    get_save_store,
    reset_save_store,
    saves_root,
    summary_values,
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
    "register_story_migration",
    "reset_save_store",
    "saves_root",
    "story_migrations",
    "summary_values",
    "write_json_atomic",
]

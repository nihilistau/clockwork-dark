"""
Seed Lore Database
==================

Ingest ``data/lore/*.md`` into SQLite FTS for RAG retrieval.

Version: v0.1.0 [2026-06-20]

Usage:
    python scripts/seed_lore.py
    python scripts/seed_lore.py --clear
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.config import get_config
from engine.lore.manager import LoreManager, reset_lore_manager


def main(argv: list[str] | None = None) -> int:
    """Ingest lore markdown into the RAG database."""
    parser = argparse.ArgumentParser(description="Seed lore RAG database from markdown")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing lore before ingest",
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Override lore source directory",
    )
    args = parser.parse_args(argv)

    lore_dir = _ROOT / (args.dir or get_config().get("paths.lore", "data/lore"))
    manager = reset_lore_manager()

    if args.clear:
        manager.clear()
        print("[seed_lore] Cleared existing lore database.")

    count = manager.ingest_directory(lore_dir)
    print(f"[seed_lore] Ingested {count} chunks from {lore_dir}")
    print(f"[seed_lore] Database: {manager.db_path}")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
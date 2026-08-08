"""
Lore Manager
============

Markdown → SQLite FTS5 ingest and retrieval.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_manager: Optional["LoreManager"] = None

_SECTION_SPLIT = re.compile(r"(?=^##\s+)", re.MULTILINE)


@dataclass
class LoreChunk:
    """Single retrievable lore passage."""

    chunk_id: str
    source: str
    title: str
    text: str
    tags: list[str]

    def to_dict(self) -> dict[str, str | list[str]]:
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "title": self.title,
            "text": self.text,
            "tags": self.tags,
        }


def _default_db_path() -> Path:
    rel = get_config().get("paths.lore_db", "data/lore/lore.db")
    return _ROOT / rel


def _default_lore_dir() -> Path:
    rel = get_config().get("paths.lore", "data/lore")
    return _ROOT / rel


def chunk_markdown(text: str, source: str) -> list[tuple[str, str, list[str]]]:
    """
    Split markdown into (title, body, tags) tuples.

    Args:
        text: Raw markdown file contents.
        source: Source filename for metadata.

    Returns:
        List of chunk tuples.
    """
    sections = _SECTION_SPLIT.split(text.strip())
    chunks: list[tuple[str, str, list[str]]] = []
    file_title = source.replace(".md", "").replace("_", " ").title()

    if not sections or (len(sections) == 1 and not sections[0].startswith("##")):
        body = text.strip()
        if len(body) >= 40:
            chunks.append((file_title, body, [file_title.lower()]))
        return chunks

    for section in sections:
        section = section.strip()
        if not section:
            continue
        lines = section.splitlines()
        title = file_title
        body_lines = lines
        if lines and lines[0].startswith("##"):
            title = lines[0].lstrip("#").strip()
            body_lines = lines[1:]
        body = "\n".join(body_lines).strip()
        if len(body) < 40:
            continue
        tags = [t.strip().lower() for t in re.findall(r"#(\w+)", section)]
        tags.append(file_title.lower())
        chunks.append((title, body, tags))

    return chunks


class LoreManager:
    """SQLite FTS-backed lore store."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per thread. This is a process-wide singleton reached
        # from Socket.IO worker threads; a single shared sqlite3 connection
        # raises ProgrammingError as soon as a second thread touches it.
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._count_cache: Optional[int] = None
        self._init_schema()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Thread-local connection, opened on first use in each thread."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def close(self) -> None:
        """Close this thread's connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _init_schema(self) -> None:
        with self._write_lock:
            self._conn.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS lore_fts USING fts5(
                    chunk_id UNINDEXED,
                    source UNINDEXED,
                    title,
                    body,
                    tags
                );
                """
            )
            self._conn.commit()

    def clear(self) -> None:
        """Remove all lore chunks."""
        with self._write_lock:
            self._conn.execute("DELETE FROM lore_fts")
            self._conn.commit()
        self._count_cache = None

    def count(self) -> int:
        """
        Number of stored chunks, cached.

        This ran a full COUNT(*) scan on every search, and search runs up to
        three times per turn between the interceptor and the evaluator.
        """
        if self._count_cache is None:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM lore_fts").fetchone()
            self._count_cache = int(row["c"]) if row else 0
        return self._count_cache

    def ingest_text(
        self,
        text: str,
        *,
        source: str = "inline.md",
    ) -> int:
        """Ingest markdown text; returns number of chunks added."""
        added = 0
        with self._write_lock:
            for title, body, tags in chunk_markdown(text, source):
                chunk_id = uuid.uuid4().hex[:12]
                tag_str = ",".join(tags)
                self._conn.execute(
                    """
                    INSERT INTO lore_fts (chunk_id, source, title, body, tags)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (chunk_id, source, title, body, tag_str),
                )
                added += 1
            self._conn.commit()
        self._count_cache = None
        return added

    def ingest_file(self, path: Path) -> int:
        """Ingest a single markdown file."""
        text = path.read_text(encoding="utf-8")
        return self.ingest_text(text, source=path.name)

    def ingest_directory(self, directory: Optional[Path] = None) -> int:
        """
        Ingest all ``*.md`` files in directory.

        Returns:
            Total chunks ingested.
        """
        lore_dir = directory or _default_lore_dir()
        if not lore_dir.exists():
            logger.warning(
                "[lore] Directory missing (operation=ingest_directory, path=%s)",
                lore_dir,
            )
            return 0

        total = 0
        for path in sorted(lore_dir.glob("*.md")):
            total += self.ingest_file(path)
        logger.info(
            "[lore] Ingest complete (operation=ingest_directory, chunks=%s)",
            total,
        )
        return total

    def search(
        self,
        query: str,
        *,
        limit: int = 3,
        scopes: Optional[tuple[str, ...]] = None,
    ) -> list[LoreChunk]:
        """
        FTS search for lore chunks.

        Args:
            query: Free-text query (location, action, keywords).
            limit: Max results.
            scopes: Knowledge scopes the CALLER may read. A chunk tagged with a
                scope outside this set is withheld. ``None`` means no scoping,
                which is the behaviour every existing caller gets.

        Returns:
            Matching LoreChunk list (empty if DB empty or no hits).

        Note on scoping: ``tags`` has been stored on every chunk since this
        index was written and read by nothing -- the column was selected,
        returned, and never filtered on. It is the scope key now, so a chunk
        tagged ``gm_secrets`` is simply not retrievable by an agent without
        that grant. Filtering happens in Python rather than SQL because tags
        are a comma-joined string in an FTS table, and a LIKE over it would
        match ``gm_secrets`` inside an unrelated tag.
        """
        if self.count() == 0 or not query.strip():
            return []

        terms = [t for t in re.findall(r"\w+", query) if len(t) > 2]
        if not terms:
            terms = query.split()[:5]
        fts_query = " OR ".join(f'"{t}"' for t in terms[:8])

        try:
            rows = self._conn.execute(
                """
                SELECT chunk_id, source, title, body, tags
                FROM lore_fts
                WHERE lore_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.debug("[lore] FTS query failed (operation=search): %s", exc)
            rows = self._conn.execute(
                """
                SELECT chunk_id, source, title, body, tags
                FROM lore_fts
                WHERE body LIKE ?
                LIMIT ?
                """,
                (f"%{terms[0]}%", limit),
            ).fetchall()

        from engine.agents.knowledge import SCOPES

        allowed = None if scopes is None else set(scopes)
        withheld = 0

        results: list[LoreChunk] = []
        for row in rows:
            tags = [t for t in str(row["tags"]).split(",") if t]

            if allowed is not None:
                # Only tags that NAME a scope gate the chunk. Every other tag is
                # ordinary content metadata, so an untagged or topically tagged
                # chunk stays public -- the alternative would make every
                # existing lore file invisible the moment scoping was turned on.
                claimed = {t for t in tags if t in SCOPES}
                if claimed and not (claimed & allowed):
                    withheld += 1
                    continue

            results.append(
                LoreChunk(
                    chunk_id=str(row["chunk_id"]),
                    source=str(row["source"]),
                    title=str(row["title"]),
                    text=str(row["body"]),
                    tags=tags,
                )
            )

        if withheld:
            logger.debug(
                "[lore] Chunks withheld by scope (operation=search, withheld=%d)",
                withheld,
            )
        return results


def get_lore_manager(*, db_path: Optional[Path] = None) -> LoreManager:
    """Return singleton LoreManager."""
    global _manager
    if _manager is None or (db_path and _manager.db_path != db_path):
        _manager = LoreManager(db_path=db_path)
    return _manager


def reset_lore_manager(db_path: Optional[Path] = None) -> LoreManager:
    """Reset singleton — for tests."""
    global _manager
    if _manager is not None:
        _manager.close()
    _manager = LoreManager(db_path=db_path)
    return _manager
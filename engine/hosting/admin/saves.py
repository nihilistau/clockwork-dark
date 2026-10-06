"""
The Admin Panel: Saves
======================

``GET /admin/saves`` shows each account's saves, per story (v0.20.0 T15,
spec §14.8), ``ACCOUNTS_PER_PAGE`` accounts a page (``?page=``), read by the
front door STRAIGHT FROM STORAGE -- each store's ``index.json`` under
``<root>/users/<id>/saves/<slug>/``, read-only, no bus -- through ONE
allowlisted projection (``project``), whose keys are exactly ``SAVE_KEYS``:

- ``save_ref``: a stable hash of the save id, never the id itself (fix round
  1, M2: ``POST /api/saves`` takes an id the player chose, which is player
  text like a label); the Sessions page shows the same reference;
- ``kind``: ``auto`` or ``manual`` -- NEVER a manual slot's label, which the
  player typed;
- ``turn_number``, ``updated_at``, ``save_version``;
- ``size``: the bytes on disk of the save's folder, from each file's ``stat``
  (``os.scandir``): no file in it is opened.

Never ``player_name``, ``archetype``, ``location_id``, ``evil_phase``,
``values``, ``thumbnail``, a ``save.json`` or a transcript: nothing here opens
any file but an ``index.json`` (AGENTS.md rule 12: the panel observes the
service; a save's contents are the player's). A missing, oversized or
malformed index shows as no rows, never an error page.

Downloading, restoring or deleting one save from the panel is NOT WIRED
(docs/GOVERNANCE.md); removing an account's saves is a delete with purge
(the Users page).

Version: v0.1.0 [2026-10-05]
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from flask import request

from engine.hosting.admin.guard import admin_account
from engine.hosting.admin.pages import render
from engine.hosting.auth import form_token, hosting_state

logger = logging.getLogger(__name__)

#: Accounts per page.
ACCOUNTS_PER_PAGE = 20

#: A projected save's keys, exactly (spec §14.8). The id leaves only as
#: ``save_ref``, a stable hash (fix round 1, M2): ``POST /api/saves`` takes a
#: save id the player chose, which is player text like a label.
SAVE_KEYS = ("save_ref", "kind", "turn_number", "updated_at", "save_version", "size")

#: The largest ``index.json`` the page reads; a bigger one is shown as no rows
#: (the index is bounded by ``saves.index_max_entries``, some 200 rows).
MAX_INDEX_BYTES = 4 * 1024 * 1024

#: An index file's name.
INDEX_FILE = "index.json"

#: The slot an autosave is written under (``engine.persistence.saves.AUTOSAVE_SLOT``).
AUTO = "auto"


def _number(value: Any, kind: type, default: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return kind(value)


def folder_size(folder: Path) -> int:
    """The bytes of the files directly in ``folder``, by ``stat`` alone (no file is opened); 0 when gone."""
    total = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += int(entry.stat(follow_symlinks=False).st_size)
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def project(entry: Any, store_dir: Path) -> Optional[dict[str, Any]]:
    """
    One index row through the allowlist (``SAVE_KEYS``), or None when it is
    not a row (no valid ``save_id``). Nothing but these keys leaves.
    """
    from engine.hosting.admin.sessions import save_ref
    from engine.persistence.saves import InvalidSaveId, check_save_id

    if not isinstance(entry, dict):
        return None
    try:
        save_id = check_save_id(entry.get("save_id"))
    except InvalidSaveId:
        return None
    return {
        "save_ref": save_ref(save_id),
        "kind": AUTO if str(entry.get("slot", AUTO)) == AUTO else "manual",
        "turn_number": _number(entry.get("turn_number"), int, 0),
        "updated_at": _number(entry.get("updated_at"), float, 0.0),
        "save_version": _number(entry.get("save_version"), int, 0),
        "size": folder_size(store_dir / save_id),
    }


def read_index(store_dir: Path) -> list[dict[str, Any]]:
    """
    ``store_dir``'s ``index.json``, projected, newest first; ``[]`` when it is
    missing, too big or not an index. Opens no other file.
    """
    path = store_dir / INDEX_FILE
    try:
        if not path.is_file() or path.stat().st_size > MAX_INDEX_BYTES:
            return []
        raw = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        logger.warning("[admin] A save index could not be read (operation=saves, store=%s)", store_dir.name)
        return []
    entries = raw.get("saves") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    rows = [row for row in (project(e, store_dir) for e in entries) if row is not None]
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows


def saves_data(number: int) -> dict[str, Any]:
    """One page of accounts, each with its saves per story."""
    from engine.hosting.admin.users import when
    from engine.persistence.storage import saves_dir

    state = hosting_state()
    accounts = sorted(state.accounts.all(), key=lambda a: a.name)
    start = (number - 1) * ACCOUNTS_PER_PAGE
    shown = []
    for account in accounts[start : start + ACCOUNTS_PER_PAGE]:
        stories = []
        for slug in state.settings.stories:
            rows = read_index(saves_dir(account.id, slug))
            for row in rows:
                row["updated_text"] = when(row["updated_at"], seconds=True) if row["updated_at"] else ""
            stories.append({"slug": slug, "rows": rows})
        shown.append({"id": account.id, "name": account.name, "stories": stories})
    return {"accounts": shown, "more": start + ACCOUNTS_PER_PAGE < len(accounts)}


def register(blueprint: Any) -> None:
    """The Saves page, on the admin blueprint."""

    @blueprint.get("/saves")
    def saves() -> Any:
        try:
            number = max(1, min(100000, int(request.args.get("page", "1") or "1")))
        except ValueError:
            number = 1
        admin = admin_account()
        return render(
            "saves.html",
            admin=admin,
            csrf=form_token(admin),
            page="saves",
            data=saves_data(number),
            number=number,
        )


__all__ = ["ACCOUNTS_PER_PAGE", "MAX_INDEX_BYTES", "SAVE_KEYS", "folder_size", "project", "read_index", "register", "saves_data"]

"""
Phone Media Storage
===================

Where the phone's generated media live (v0.22.0 spec §13.4):
``storage.media_dir()/phone/<owner>/<save_id>/<mid>-<digest>.<ext>``, ``<owner>``
being ``local`` in local mode and the account id when hosted. An account id
is ``u_<hex>`` (``engine/hosting/accounts.ID_RE``), so no account can be
named ``local``. Every name that reaches a path is checked as a save id is
(``engine.persistence.saves.check_save_id``): a ``..`` or a separator is a
``ValueError``, never a path outside the owner's folder.

A file is typed by its MAGIC BYTES (:func:`sniff`), never by the name or the
``Content-Type`` a server sent: PNG, JPEG, WEBP, MP4 and WEBM from ComfyUI,
and a voice note's WAV from the speech worker (T21, by
``engine.media.tts.is_wav``); nothing else is stored. Nothing here reads or judges what an image shows (AGENTS.md
rule 12).

The route that serves these files is T19's (``GET
/api/phone/media/<save_id>/<name>``, :func:`url_for`).

Version: v0.1.0 [2026-10-12]
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from engine.persistence import storage as _storage
from engine.persistence.saves import check_save_id

#: The owner folder of local mode's media (no account).
LOCAL_OWNER = "local"

#: A stored file's name: ``<mid>-<digest>.<ext>`` or ``<mid>-<digest>_poster.<ext>`` (the digest: the request's, ``JobSpec.digest``).
#: ``wav`` is a voice note's (v0.22.0 T21), written by the speech worker's
#: hand-off and typed by ``engine.media.tts.is_wav``; ComfyUI's outputs are
#: still only what :func:`sniff` names.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\.(png|jpg|webp|mp4|webm|wav)$")


def media_dir() -> Path:
    """The storage root's media folder (``engine.persistence.storage.media_dir``)."""
    return _storage.media_dir()


def _owner_folder(owner: str) -> str:
    if not owner:
        return LOCAL_OWNER
    return check_save_id(owner, what="owner").lower()


def phone_media_dir(owner: str, save_id: str) -> Path:
    """
    ``media_dir()/phone/<owner or "local">/<save_id>``. Raises ``ValueError``
    (``InvalidSaveId``) for an owner or save id that is not a plain name.
    """
    return media_dir() / "phone" / _owner_folder(owner) / check_save_id(save_id)


def phone_owner_dir(owner: str) -> Path:
    """``media_dir()/phone/<owner or "local">``: every save's media of one owner."""
    return media_dir() / "phone" / _owner_folder(owner)


def check_name(name: str) -> str:
    """``name`` if it is a stored file's name (``<mid>-<digest>.<ext>``); ``ValueError`` otherwise."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ValueError(f"not a phone media file name: {name!r}")
    return name


def url_for(save_id: str, name: str) -> str:
    """The URL T19's route serves a stored file at: ``/api/phone/media/<save_id>/<name>``."""
    return f"/api/phone/media/{check_save_id(save_id)}/{check_name(name)}"


def sniff(data: bytes) -> Optional[tuple[str, str]]:
    """
    ``(ext, mime)`` from the magic bytes -- PNG, JPEG, WEBP, MP4 or WEBM --
    or None for anything else.
    """
    head = bytes(data[:64])
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ("png", "image/png")
    if head.startswith(b"\xff\xd8\xff"):
        return ("jpg", "image/jpeg")
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ("webp", "image/webp")
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return ("mp4", "video/mp4")
    # EBML; a Matroska file whose DocType is "webm" (a bare .mkv is not stored).
    if head.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in head:
        return ("webm", "video/webm")
    return None


__all__ = [
    "LOCAL_OWNER",
    "check_name",
    "media_dir",
    "phone_media_dir",
    "phone_owner_dir",
    "sniff",
    "url_for",
]

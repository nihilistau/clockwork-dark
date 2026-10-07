"""
Storage Root
============

Where the engine writes what it makes at run time: saves, generated media
and (hosted, from v0.20.0) accounts. ONE root, engine-owned (spec §4.1):

    CLOCKWORK_DATA_DIR       the environment, if set and non-empty
    storage.root             else the config (``config/default.yaml``: "data")

A relative value is taken against ``project_root()``, NEVER the working
directory. Until v0.20.0 saves (``paths.saves``, used as-is), images
(``MEDIA_DIR``, ``IMAGE_DIR``) and audio (``AUDIO_DIR``) were all paths
under ``data/`` taken relative to the cwd, so ``python /path/to/launcher.py``
run from anywhere else wrote saves into that directory and served media that
did not exist there (survey finding 2). From the root:

    saves           <root>/saves/<slug>/                  owner ""  (local)
                    <root>/users/<owner>/saves/<slug>/    any other owner
    images          <root>/media/images/
    audio           <root>/media/tts/
    hosting         <root>/hosting/

With the default, every local path is byte-for-byte v0.19.0's (the local-mode
golden's ``save_base.json`` pins it).

EACH FUNCTION READS ON CALL, never at import. The module constants these
replace were bound at import, and ``from ... import IMAGE_DIR`` copied the
value into the importer, so a ``CLOCKWORK_DATA_DIR`` set later (a test's
``monkeypatch.setenv``, a hosted deployment's environment) never reached them.
They are deleted, not aliased; ``tests/test_storage_root.py`` scans for them.

A ``paths.saves`` in an operator layer was read as the save base, with a
WARNING, through v0.20.x; since v0.21.0 it is refused at config load
(``engine.config.LegacyConfigError``).

Version: v0.20.0 [2026-09-30]
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from engine.config import get_config, project_root

logger = logging.getLogger(__name__)

#: The environment variable that beats ``storage.root``.
DATA_DIR_ENV = "CLOCKWORK_DATA_DIR"

#: What ``storage.root`` answers when no layer sets it: the layout every
#: release has used.
DEFAULT_ROOT = "data"


def _anchored(raw: str) -> Path:
    """``raw`` as a path, a relative one taken against ``project_root()``."""
    candidate = Path(os.path.expanduser(raw))
    return candidate if candidate.is_absolute() else project_root() / candidate


def data_root() -> Path:
    """
    The storage root: ``CLOCKWORK_DATA_DIR``, else ``storage.root``, anchored
    at ``project_root()`` when relative. Read on every call.
    """
    env = os.environ.get(DATA_DIR_ENV, "").strip()
    if env:
        return _anchored(env)
    raw = str(get_config().get("storage.root", DEFAULT_ROOT) or "").strip()
    return _anchored(raw or DEFAULT_ROOT)


def local_saves_base() -> Path:
    """The owner-``""`` save base: ``<root>/saves``."""
    return data_root() / "saves"


def saves_dir(owner: str = "", slug: Optional[str] = None) -> Path:
    """
    Where ``owner``'s saves for ``slug`` live; the owner's save base when
    ``slug`` is None.

    Owner ``""`` is the local player: ``<root>/saves``.
    Any other owner is an account: ``<root>/users/<owner>/saves``. The caller
    checks the owner and the slug are names (``save_store_for`` does).
    """
    base = local_saves_base() if not owner else data_root() / "users" / owner / "saves"
    return base if slug is None else base / slug


def media_dir() -> Path:
    """Generated media: ``<root>/media``. Served by ``/api/media/<path>``."""
    return data_root() / "media"


def image_dir() -> Path:
    """Generated images, the disposable cache: ``<root>/media/images``."""
    return media_dir() / "images"


def audio_dir() -> Path:
    """Synthesized narration: ``<root>/media/tts``. Served by ``/api/audio/<path>``."""
    return media_dir() / "tts"


def hosting_dir() -> Path:
    """Hosted mode's accounts and cookie key: ``<root>/hosting``."""
    return data_root() / "hosting"


__all__ = [
    "DATA_DIR_ENV",
    "DEFAULT_ROOT",
    "audio_dir",
    "data_root",
    "hosting_dir",
    "image_dir",
    "local_saves_base",
    "media_dir",
    "saves_dir",
]

"""
Portable names
==============

A name a client or an author picks that becomes a directory -- a save id, a
story slug -- must mean the same file on every platform a save tree or a
story may be copied to. Each such name is already held to an allowlist
(``saves.SAVE_ID_RE``, ``manifest.SLUG_RE``); this module holds the two rules
an allowlist of ordinary characters does not express, applied on EVERY
operating system (v0.20.0 T2, review finding 3):

- **Windows device names.** ``CON``, ``PRN``, ``AUX``, ``NUL``, ``COM0``-``COM9``
  and ``LPT0``-``LPT9`` (and the superscript-digit forms), in any case, with or
  without an extension: ``NUL`` as a save id answered a 500 on Windows, and
  ``con`` saved into a directory no other checkout could hold.
- **A trailing dot or space**, which Windows strips, so ``x.`` and ``x`` are
  one directory there and two elsewhere.

Every match here uses ``fullmatch``, never a ``$`` that also matches before a
trailing newline.
"""

from __future__ import annotations

import re
from typing import Any

#: A Windows device name, as the part before the first dot, any case.
_DEVICE_RE = re.compile(r"(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])", re.IGNORECASE)


def is_device_name(name: str) -> bool:
    """Whether ``name`` (or its stem before the first dot) is a Windows device."""
    return bool(_DEVICE_RE.fullmatch(name.split(".", 1)[0].strip()))


def is_portable_name(name: Any) -> bool:
    """
    A non-empty string that is no device name and ends in no dot or space.

    Only the two platform rules: the caller's own allowlist still decides the
    characters.
    """
    return (
        isinstance(name, str)
        and bool(name)
        and not name.endswith((".", " "))
        and not is_device_name(name)
    )


__all__ = ["is_device_name", "is_portable_name"]

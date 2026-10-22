"""
The phone slice, packed for its save (v0.23.0 T9 fix round 2; spec §17.2's size bound, §7.1, R8).

A save leaves out what loading can put back exactly, nothing else:

- a message's `decision` of the exact shape the engine writes (`Decision`'s fields, in their order)
  keeps only the fields that differ from `Decision`'s defaults, marked ``"_p": 1``;
- a message whose `thread_id` is its own thread's key, as its second key (`social_message` writes it
  so), drops it and is marked ``"_t": 1`` (loading restores `thread_id` only on a marked message, so
  a message that never had one is never given one);
- a media row whose keys begin with the engine's own (`MEDIA_KEYS`, `media._e_media`'s ``attach``)
  keeps only the defaultable ones that differ from `MEDIA_DEFAULTS`, marked ``"_p": 1``.

`unpack` puts each back in its place, so save -> load -> save gives the same bytes and the loaded slice
is the slice that was saved, key order and all (tests/test_social_packing.py). A row of any other
shape -- a decision with a missing or extra key, a message filed under another thread -- is saved as it
is. Called only for a story whose state carries a `social` slice (`GameState.to_save_dict`,
`GameState.from_dict`): every other story's save is byte-identical.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from engine.social.kinds import Decision

#: The marker a packed row carries.
PACKED = "_p"

#: The marker a message carries when its `thread_id` was dropped.
DROPPED = "_t"

#: `Decision`'s fields and defaults, in the order `dataclasses.asdict` writes them.
DECISION_FIELDS: tuple[tuple[str, Any], ...] = tuple((f.name, f.default) for f in dataclasses.fields(Decision))

#: A media row's own keys, in the order `media._e_media` writes them, and those with a default to leave out.
MEDIA_KEYS: tuple[str, ...] = ("mid", "kind", "pid", "thread_id", "message_id", "subject", "caption", "seed",
                               "priority", "account", "status", "provider", "prompt_id", "attempts", "url",
                               "poster_url", "error", "created_at", "finished_at")
MEDIA_DEFAULTS: tuple[tuple[str, Any], ...] = (("caption", ""), ("priority", 0), ("account", ""),
                                               ("provider", ""), ("prompt_id", ""), ("attempts", 0), ("url", ""),
                                               ("poster_url", ""), ("error", ""), ("finished_at", None))


def _same(a: Any, b: Any) -> bool:
    """Equal and of the same type (a 0 is not a False, a 1.0 not a 1: loading must give back the same)."""
    return type(a) is type(b) and a == b


def _pack_defaults(row: dict[str, Any], order: tuple[str, ...], defaults: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    drop = {k for k, v in defaults if k in row and _same(row[k], v)}
    out = {k: v for k, v in row.items() if k not in drop}
    out[PACKED] = 1
    return out


def _unpack_defaults(row: dict[str, Any], order: tuple[str, ...], defaults: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    fill = dict(defaults)
    out = {k: (row[k] if k in row else fill[k]) for k in order if k in row or k in fill}
    out.update((k, v) for k, v in row.items() if k not in out and k != PACKED)
    return out


def _decision_packable(d: Any) -> bool:
    return isinstance(d, dict) and PACKED not in d and tuple(d) == tuple(k for k, _ in DECISION_FIELDS)


def _media_packable(row: Any) -> bool:
    return (isinstance(row, dict) and PACKED not in row and tuple(row)[:len(MEDIA_KEYS)] == MEDIA_KEYS)


def pack(slice_: dict[str, Any]) -> dict[str, Any]:
    """The slice as its save writes it (``slice_`` is the save's own copy: changed in place, returned)."""
    order = tuple(k for k, _ in DECISION_FIELDS)
    for tid, t in (slice_.get("threads") or {}).items():
        messages = t.get("messages") if isinstance(t, dict) else None
        if not isinstance(messages, list):
            continue
        for i, m in enumerate(messages):
            if not isinstance(m, dict):
                continue
            if _decision_packable(m.get("decision")):
                m["decision"] = _pack_defaults(m["decision"], order, DECISION_FIELDS)
            keys = tuple(m)
            if len(keys) > 1 and keys[1] == "thread_id" and m["thread_id"] == tid and DROPPED not in m:
                messages[i] = {**{k: v for k, v in m.items() if k != "thread_id"}, DROPPED: 1}
    media = slice_.get("media")
    if isinstance(media, dict):
        for mid, row in media.items():
            if _media_packable(row):
                media[mid] = _pack_defaults(row, MEDIA_KEYS, MEDIA_DEFAULTS)
    return slice_


def unpack(slice_: dict[str, Any]) -> dict[str, Any]:
    """The slice as it was before `pack` (changed in place, returned)."""
    order = tuple(k for k, _ in DECISION_FIELDS)
    for tid, t in (slice_.get("threads") or {}).items():
        messages = t.get("messages") if isinstance(t, dict) else None
        if not isinstance(messages, list):
            continue
        for i, m in enumerate(messages):
            if not isinstance(m, dict):
                continue
            if m.get(DROPPED) == 1 and "thread_id" not in m:
                first, *rest = ((k, v) for k, v in m.items() if k != DROPPED)
                m = dict([first, ("thread_id", tid), *rest])
                messages[i] = m
            elif DROPPED in m:
                m.pop(DROPPED)
            d = m.get("decision")
            if isinstance(d, dict) and d.get(PACKED) == 1:
                m["decision"] = _unpack_defaults(d, order, DECISION_FIELDS)
    media = slice_.get("media")
    if isinstance(media, dict):
        for mid, row in media.items():
            if isinstance(row, dict) and row.get(PACKED) == 1:
                media[mid] = _unpack_defaults(row, MEDIA_KEYS, MEDIA_DEFAULTS)
    return slice_

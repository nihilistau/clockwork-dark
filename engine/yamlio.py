"""
One YAML loader for the engine (v0.21.1).

libyaml's CSafeLoader is ~10x faster than PyYAML's pure-Python parser
(measured 2026-10-07: HUE & CRY's 69 files, 0.73 s -> 0.07 s), and every
story activation re-parses its tree. On valid input both build through
SafeConstructor with the same resolver, so the values are equal -- types,
key order and shared anchors (tests/test_yamlio.py checks every tracked
file). On invalid input the pure parser runs again so the error, and its
marks, read exactly as before: validation messages and several tests quote
them.

libyaml is MORE LENIENT than the pure parser in places, and there a
fallback on error never fires, so those documents go to the pure parser
from the start (``_pure_only``):

- a TAB anywhere: libyaml accepts one after a token (``a: 1	``,
  ``a:	1``, ``- a	``, ``a: [1,	2]``, ``a: "x"	``), which the pure
  parser refuses with a ScannerError. No tracked file holds a tab, so this
  costs shipped content nothing;
- a byte-order mark past the first character: libyaml drops a doubled
  leading BOM (``\ufeff\ufeffa: 1`` -> key ``a``, pure ``\ufeffa``) and
  refuses one at a line start that the pure parser reads as text.

One divergence is left, measured and pathological: flow collections nested
some 600 deep make the pure parser raise RecursionError (not a YAMLError),
where libyaml parses them. No authored file nests like that.

A stream is read whole first, so the fast parser can be tried. If the read
itself fails (a file that is not UTF-8), a seekable stream is rewound and
handed to the pure parser, which then fails as it always did, chunk by
chunk; a non-seekable stream that cannot be read raises the read's own
error (the pure parser might have hit a syntax error first; no engine site
passes one). A document the pure parser takes -- a YAML error, or one of
the cases above -- is replayed from a stream that carries the original
one's ``name``, because the pure parser marks a stream's errors with that
name and no snippet, and a string's with ``"<unicode string>"`` and the
offending line.

Stateless: no cache, nothing to classify in tests/fixtures/module_state.yaml.
"""

from __future__ import annotations

import io
from typing import Any

import yaml

#: libyaml's safe loader; None when PyYAML was built without libyaml.
_FAST = getattr(yaml, "CSafeLoader", None)


def safe_load(stream_or_text: Any) -> Any:
    """``yaml.safe_load``, through libyaml when it is installed: the same
    values, and on a malformed document the same exception and message."""
    if _FAST is None:
        return yaml.safe_load(stream_or_text)
    if not hasattr(stream_or_text, "read"):
        if _pure_only(stream_or_text):
            return yaml.safe_load(stream_or_text)
        try:
            return yaml.load(stream_or_text, Loader=_FAST)  # noqa: S506 -- CSafeLoader is the safe loader
        except yaml.YAMLError:
            return yaml.safe_load(stream_or_text)
    stream = stream_or_text
    start = _tell(stream)
    try:
        text = stream.read()
    except Exception:
        if start is None:
            raise
        stream.seek(start)
        return yaml.safe_load(stream)
    if not _pure_only(text):
        try:
            return yaml.load(text, Loader=_FAST)  # noqa: S506 -- CSafeLoader is the safe loader
        except yaml.YAMLError:
            pass
    replay = io.BytesIO(text) if isinstance(text, bytes) else io.StringIO(text)
    if hasattr(stream, "name"):
        replay.name = stream.name
    return yaml.safe_load(replay)


def _pure_only(text: Any) -> bool:
    """A document libyaml would read more leniently than the pure parser:
    one with a tab, or a byte-order mark past its first character."""
    if isinstance(text, bytes):
        return b"\t" in text or text.find(b"\xef\xbb\xbf", 1) != -1
    if isinstance(text, str):
        return "\t" in text or text.find("\ufeff", 1) != -1
    return False


def _tell(stream: Any) -> Any:
    """Where a seekable stream stands now, or None."""
    try:
        return stream.tell() if stream.seekable() else None
    except (AttributeError, OSError, ValueError):
        return None

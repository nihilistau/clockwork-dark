"""
Tag Buffer
==========

Holds back text that might still turn out to be a ``[TAG:...]``.

Tags arrive split across SSE chunks. ``[IMAGE:forest_dawn]`` can land as
``"[IMA"`` + ``"GE:forest"`` + ``"_dawn]"``, and a scanner that inspects each
delta independently matches none of them -- so the tag text goes straight into
the player's log while the image never renders.

The existing StreamProcessor scans per-delta and only appears to work because
nothing streamed yet; it would have broken the moment streaming was wired up.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import re

# Longest plausible tag. Beyond this a lone '[' is just a bracket, and holding
# text hostage forever would stall the narration on screen.
MAX_TAG_LENGTH = 64

TAG_PATTERN = re.compile(r"\[([A-Z_]+):([^\]\[]*)\]")


class TagBuffer:
    """Incremental, split-safe tag extraction over a text stream."""

    def __init__(self, *, max_tag_length: int = MAX_TAG_LENGTH) -> None:
        self._pending = ""
        self._max_tag_length = max_tag_length
        self.tags: list[tuple[str, str]] = []

    def push(self, delta: str) -> str:
        """
        Feed a chunk. Returns the text that is safe to display now.

        Complete tags are consumed into ``self.tags`` and never emitted. A
        trailing partial tag is retained until it completes or grows too long
        to be one.
        """
        if not delta:
            return ""

        self._pending += delta
        emitted, self._pending = self._split(self._pending)
        return emitted

    def flush(self) -> str:
        """Release anything still held. Call at end of stream."""
        text = self._pending
        self._pending = ""
        cleaned, _ = self._consume_tags(text)
        return cleaned

    def _split(self, text: str) -> tuple[str, str]:
        """Return (safe_to_emit, still_pending)."""
        text, _ = self._consume_tags(text)

        # A '[' with no closing ']' yet might be the start of a tag.
        open_index = text.rfind("[")
        if open_index == -1:
            return text, ""

        candidate = text[open_index:]
        if "]" in candidate:
            # Closed but not a tag we recognise -- ordinary text.
            return text, ""
        if len(candidate) > self._max_tag_length:
            # Too long to be a tag; stop holding it.
            return text, ""

        return text[:open_index], candidate

    def _consume_tags(self, text: str) -> tuple[str, int]:
        """Strip complete tags out of text, recording them."""
        count = 0

        def _take(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            self.tags.append((match.group(1), match.group(2)))
            return ""

        return TAG_PATTERN.sub(_take, text), count

    def tags_of(self, kind: str) -> list[str]:
        """All values captured for one tag kind, e.g. ``IMAGE``."""
        return [value for name, value in self.tags if name == kind]

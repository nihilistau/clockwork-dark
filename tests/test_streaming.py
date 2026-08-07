"""
Streaming primitive tests.

Both of these fail in ways that are invisible until real streaming is wired up,
so they are tested against every possible chunk boundary rather than one
convenient split.
"""

from __future__ import annotations

import json

import pytest

from engine.agents.json_stream import (
    NarrationStreamer,
    extract_json,
    find_json_object,
)
from engine.agents.tag_buffer import TagBuffer


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


# -- TagBuffer -----------------------------------------------------------


def test_plain_text_passes_through():
    buf = TagBuffer()
    assert buf.push("You wake beneath birch trees.") == "You wake beneath birch trees."
    assert buf.flush() == ""


@pytest.mark.parametrize("size", range(1, 12))
def test_tag_never_leaks_at_any_chunk_size(size):
    """
    The bug this exists to prevent.

    A per-delta scanner sees '[IMA' then 'GE:forest' and matches neither, so
    the tag text lands in the player's log and the image never renders.
    """
    source = "Mist clings [IMAGE:forest_clearing_dawn] to the ferns."
    buf = TagBuffer()
    emitted = "".join(buf.push(c) for c in _chunks(source, size)) + buf.flush()

    assert "[IMAGE" not in emitted
    assert "IMAGE:" not in emitted
    assert emitted == "Mist clings  to the ferns."
    assert buf.tags_of("IMAGE") == ["forest_clearing_dawn"]


@pytest.mark.parametrize("size", range(1, 8))
def test_multiple_tags_at_any_chunk_size(size):
    source = "[VOICE:whisper]The wheat [IMAGE:field_night] remembers.[CUTSCENE:phase_shift]"
    buf = TagBuffer()
    emitted = "".join(buf.push(c) for c in _chunks(source, size)) + buf.flush()

    assert emitted == "The wheat  remembers."
    assert buf.tags_of("VOICE") == ["whisper"]
    assert buf.tags_of("IMAGE") == ["field_night"]
    assert buf.tags_of("CUTSCENE") == ["phase_shift"]


def test_tag_at_very_end_is_held_then_flushed():
    buf = TagBuffer()
    out = buf.push("Done.[IMAGE:x")
    assert "[IMAGE" not in out
    assert buf.push("]") == ""
    assert buf.tags_of("IMAGE") == ["x"]


def test_lone_bracket_is_released_not_held_forever():
    """A bracket that cannot be a tag must not stall the narration on screen."""
    buf = TagBuffer()
    long_tail = "[" + "x" * 100
    emitted = buf.push("Text " + long_tail)
    assert long_tail in emitted


def test_ordinary_brackets_survive():
    buf = TagBuffer()
    out = buf.push("He wrote [see the ledger] in the margin.") + buf.flush()
    assert out == "He wrote [see the ledger] in the margin."
    assert buf.tags == []


# -- NarrationStreamer ---------------------------------------------------

PAYLOAD = {
    "narration": 'She said "no" once, then\nturned back to the oven — quietly.',
    "choices": [{"id": "a", "text": "Wait"}, {"id": "b", "text": "Leave"}],
    "mood": "uneasy",
}


@pytest.mark.parametrize("size", range(1, 15))
def test_narration_reassembles_exactly_at_any_chunk_size(size):
    raw = json.dumps(PAYLOAD)
    streamer = NarrationStreamer()
    streamed = "".join(streamer.push(c) for c in _chunks(raw, size))

    assert streamed == PAYLOAD["narration"]
    assert streamer.text == PAYLOAD["narration"]
    assert streamer.done is True


def test_narration_stops_at_the_closing_quote():
    """Later fields must not bleed into the narration shown on screen."""
    streamer = NarrationStreamer()
    streamer.push(json.dumps(PAYLOAD))
    assert "choices" not in streamer.text
    assert "uneasy" not in streamer.text


def test_narration_decodes_unicode_escapes():
    payload = json.dumps({"narration": "café — warm"}, ensure_ascii=True)
    streamer = NarrationStreamer()
    out = "".join(streamer.push(c) for c in _chunks(payload, 1))
    assert out == "café — warm"


def test_narration_streams_before_the_object_closes():
    """The point of the exercise: text on screen while generation continues."""
    streamer = NarrationStreamer()
    partial = '{"narration": "You wake beneath birch'
    assert streamer.push(partial) == "You wake beneath birch"
    assert streamer.done is False


# -- find_json_object ----------------------------------------------------


def test_finds_object_with_nested_braces():
    """
    The regression that made the old fallback dead code.

    _JSON_LOOSE used [^{}]* so it could never match a payload containing
    choices: [{...}] -- which the mandated schema always did. The fallback
    never fired once, and raw JSON reached players as narration.
    """
    text = 'Here you go:\n{"narration": "x", "choices": [{"id": "a"}]}\nthanks'
    found = find_json_object(text)
    assert found is not None
    assert json.loads(found)["choices"][0]["id"] == "a"


def test_braces_inside_strings_do_not_confuse_the_scanner():
    text = '{"narration": "he drew a { on the wall", "choices": []}'
    assert json.loads(find_json_object(text))["choices"] == []


def test_escaped_quote_inside_string():
    text = '{"narration": "she said \\"no\\"", "choices": []}'
    assert json.loads(find_json_object(text))["narration"] == 'she said "no"'


def test_returns_none_when_unbalanced():
    assert find_json_object('{"narration": "unterminated') is None


def test_extract_json_prefers_fenced_block():
    text = 'prose here\n```json\n{"narration": "fenced", "choices": []}\n```'
    assert extract_json(text)["narration"] == "fenced"


def test_extract_json_without_fence():
    text = 'prose\n{"narration": "bare", "choices": [{"id": "a"}]}'
    assert extract_json(text)["narration"] == "bare"


def test_extract_json_returns_none_on_prose():
    assert extract_json("Just narration, no JSON at all.") is None

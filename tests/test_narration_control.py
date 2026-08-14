"""
Streamed narration must never stop mid sentence.

Every case here was observed against the live model (nemotron-3-nano-4b on LM
Studio) across 24 measured turns, or proved by driving the real code path with
a forced ``max_tokens``. They are regression guards for four distinct causes
that all surfaced as the same symptom -- a sentence that stops dead:

  1. ``finish_reason: "length"`` with content already written. Only the EMPTY
     case had a failure class (``starved_by_reasoning``); the partial cut, which
     is the one players actually see, was undetected.
  2. A JSON envelope cut mid-object. ``parse_storyteller_response`` returned
     ``narration: ""`` after the player had already watched half of that
     narration stream onto the screen.
  3. The evaluator retry does not stream, so the accepted narration only ever
     arrived inside ``turn_update`` -- which the client ignored, leaving the
     rejected half-streamed draft on screen for good.
  4. The model writing the whole turn envelope, escaped, INSIDE the narration
     string. Grammar-legal, so structured output does not prevent it, and the
     player is shown raw JSON as prose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine.agents.storyteller import (
    Generation,
    parse_storyteller_response,
    salvage_narration,
    strip_embedded_envelope,
)
from engine.agents.stream_processor import (
    SentenceGate,
    ends_mid_sentence,
    strip_trailing_debris,
    trim_to_sentence,
)
from engine.lmstudio.events import LMSResponse

UI_SRC = Path(__file__).resolve().parent.parent / "ui" / "src"


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


PROSE = (
    "You wake beneath birch trees, and the cold finds the gap at your collar. "
    "Mist clings to the ferns. Somewhere behind you a door closes, once, "
    "without hurry."
)


# -- SentenceGate --------------------------------------------------------


@pytest.mark.parametrize("size", [1, 2, 3, 5, 11, 40, 500])
def test_a_finished_stream_is_delivered_verbatim(size):
    """Pacing must not lose or reorder a single character."""
    gate = SentenceGate()
    out = "".join(gate.push(c) for c in _chunks(PROSE, size))
    out += gate.flush(complete=True)
    assert out == PROSE


@pytest.mark.parametrize("size", [1, 3, 7, 40])
def test_a_cut_stream_never_ends_mid_sentence(size):
    """
    The whole point. A generation that stopped mid-clause releases only whole
    sentences, and the severed remainder is withheld rather than shown.
    """
    cut = PROSE[: PROSE.index("Somewhere") + 20]
    gate = SentenceGate()
    out = "".join(gate.push(c) for c in _chunks(cut, size))
    out += gate.flush(complete=False)

    assert out  # something survived
    assert cut.startswith(out)  # only a prefix, never invented text
    assert not ends_mid_sentence(out)
    assert gate.dropped  # and the tail was consciously withheld


def test_a_half_written_word_is_never_released():
    gate = SentenceGate()
    emitted = gate.push("The watchman's lamp swings rou")
    assert not emitted.endswith("rou")


def test_a_long_unpunctuated_run_still_moves():
    """A model writing one endless line must not freeze the screen."""
    source = "word " * 40
    gate = SentenceGate(soft_limit=40)
    emitted = gate.push(source)
    assert emitted
    assert source.startswith(emitted)
    # Released up to a whole word; the separating space is held back with the
    # rest, which is why this does not end in one.
    assert emitted.endswith("word")


def test_nothing_complete_means_nothing_shown():
    gate = SentenceGate()
    gate.push("a fragment with no ending")
    assert gate.flush(complete=False) == ""
    assert gate.dropped == "a fragment with no ending"


# -- trimming ------------------------------------------------------------


def test_markdown_fence_debris_is_dropped():
    """Observed live: the model closing a fence it never opened, inside JSON."""
    assert trim_to_sentence("It holds its breath.\n\n```") == "It holds its breath."


def test_a_severed_clause_is_dropped_not_shown():
    text = 'He says, "Bit late for the road." And waits, and the waiting goes'
    assert trim_to_sentence(text) == 'He says, "Bit late for the road."'


def test_text_with_no_complete_sentence_is_left_alone():
    """Something imperfect beats an empty log entry."""
    assert trim_to_sentence("no sentence here at all") == "no sentence here at all"


def test_a_clean_ending_is_untouched():
    assert trim_to_sentence(PROSE) == PROSE
    assert not ends_mid_sentence(PROSE)


@pytest.mark.parametrize(
    "tail",
    [
        "`",
        "\n\n```",
        "}`",
        " ``}`",
        ' `"``,',
        "\n\n*",
        "   ",
    ],
)
def test_every_observed_debris_shape_is_stripped(tail):
    """
    All of these were measured live, after a perfectly finished sentence. They
    survive every truncation check by construction -- the sentence before them
    is complete, so `ends_mid_sentence` is False and nothing else was looking.
    """
    assert strip_trailing_debris("It holds its breath." + tail) == "It holds its breath."


def test_debris_stripping_does_not_eat_dialogue():
    """
    The reason this is a "wordless tail" rule and not a character class: a
    class wide enough for ``` `"``, ``` has to include `"` and `,`, and would
    then strip the closing quote off every line of speech.
    """
    speech = 'He waits, and then: "Bit late for the road."'
    assert strip_trailing_debris(speech) == speech
    assert strip_trailing_debris("They are gone (all of them.)") == "They are gone (all of them.)"
    assert strip_trailing_debris(PROSE) == PROSE


def test_the_schema_ceiling_degeneration_is_recovered():
    """
    The worst shape measured: the model wrote two good sentences, degenerated
    into a run of backticks, and the grammar's `maxLength: 1400` guillotined
    the string mid-run. `finish_reason` was a clean "stop", so no token-level
    check could ever have seen it.
    """
    prose = (
        "The firelight dances on the rough-hewn logs. "
        "A rabbit watches from the ferns, unmoving."
    )
    degenerate = (prose + " " + "`` " * 320)[:1400]
    assert strip_trailing_debris(degenerate) == prose


def test_debris_stripping_never_empties_the_narration():
    """No complete sentence to fall back on means leave it alone."""
    assert strip_trailing_debris("```") == "```"
    assert strip_trailing_debris("a fragment with no ending") == "a fragment with no ending"


def test_debris_is_never_shown_even_for_an_instant():
    """
    `\\n` is a clause boundary, so a fence arriving after a finished sentence
    used to be released mid-stream and sat on screen until `turn_update`
    replaced the text. The gate holds a trailing debris run instead.
    """
    gate = SentenceGate()
    source = "It holds its breath.\n\n```"
    shown = []
    acc = ""
    for i in range(0, len(source), 3):
        acc += gate.push(source[i : i + 3])
        shown.append(acc)
    assert all("`" not in state for state in shown), shown
    assert acc + gate.flush(complete=True) == "It holds its breath."


def test_a_finished_stream_still_loses_its_debris():
    gate = SentenceGate()
    out = gate.push("It holds its breath.") + gate.flush(complete=True)
    assert out == "It holds its breath."


# -- truncation detection ------------------------------------------------


def test_partial_truncation_is_its_own_condition():
    """
    The cut that used to be invisible: content present, finish_reason length.

    ``starved_by_reasoning`` is False here, which is exactly why nothing
    downstream noticed.
    """
    cut = LMSResponse(content="Mist clings to the fer", finish_reason="length")
    assert cut.truncated
    assert cut.truncated_mid_content
    assert not cut.starved_by_reasoning


def test_starvation_and_partial_truncation_are_not_the_same_thing():
    starved = LMSResponse(content="", reasoning_content="x" * 200, finish_reason="length")
    assert starved.starved_by_reasoning
    assert not starved.truncated_mid_content


def test_a_clean_stop_is_neither():
    done = LMSResponse(content=PROSE, finish_reason="stop")
    assert not done.truncated
    assert not done.truncated_mid_content


def test_generation_reports_whether_the_model_finished():
    assert Generation(raw="{}", complete=True, finish_reason="stop").truncated is False
    assert Generation(raw="{", complete=False, finish_reason="length").truncated is True


# -- the JSON envelope ---------------------------------------------------


def test_a_cut_envelope_no_longer_blanks_the_narration():
    """
    Cause 2. The player had already watched this text arrive; returning "" then
    reported it as "the model wrote no narration", which is not what happened.
    """
    raw = '{"narration": "You step into the clearing and the cold finds the gap at your'
    parsed = parse_storyteller_response(raw)

    assert parsed["narration"].startswith("You step into the clearing")
    assert parsed["salvaged"] is True
    # Never zero choices: a cut-short generation is exactly when a soft-lock
    # would happen.
    assert len(parsed["choices"]) >= 2


def test_a_cut_envelope_after_the_narration_closed_still_salvages():
    raw = '{"narration": "A full sentence here.", "choices": [{"id":"a","text":"Go"'
    parsed = parse_storyteller_response(raw)
    assert parsed["narration"] == "A full sentence here."


def test_salvage_is_silent_when_there_is_nothing_to_salvage():
    assert salvage_narration("total gibberish, no key here") == ""


def test_a_whole_envelope_still_parses_normally():
    raw = json.dumps(
        {
            "narration": PROSE,
            "choices": [{"id": "a", "text": "Look"}, {"id": "b", "text": "Wait"}],
        }
    )
    parsed = parse_storyteller_response(raw)
    assert parsed["narration"] == PROSE
    assert not parsed.get("salvaged")
    assert not parsed.get("parse_failed")


# -- the envelope written inside the prose -------------------------------


def test_an_embedded_envelope_is_cut_out_of_the_narration():
    """
    Cause 4, observed live once in 21 turns: the model wrote the entire turn
    object, escaped, inside its own narration string, and the player was shown
    `..., "choices": [{"id": "a", "text": ...` as prose.
    """
    derailed = (
        "A slow trickle glides through the hollow of the stone basin, steady "
        'and sure.", "choices": [{"id": "a", "text": "It sounds like the '
        'river."}], "mood": "quietly concerned" }'
    )
    cleaned = strip_embedded_envelope(derailed)
    assert '"choices"' not in cleaned
    assert cleaned.endswith("steady and sure.")


def test_ordinary_prose_with_quotes_and_commas_survives():
    """The guard must not eat dialogue."""
    speech = 'She tips her chin at the flue. "Odran says it\'s the wind," she says, "and Odran says a lot of things."'
    assert strip_embedded_envelope(speech) == speech
    assert strip_embedded_envelope(PROSE) == PROSE


# -- the client contract -------------------------------------------------


def test_turn_update_replaces_the_streamed_text():
    """
    Cause 3. The reducer must take `payload.narration` as authoritative rather
    than trusting whatever its delta buffer happened to contain -- the retry
    does not stream, so the buffer holds a REJECTED draft.
    """
    store = (UI_SRC / "core" / "store.js").read_text(encoding="utf-8")
    turn_update = store.split('case "turn_update"')[1].split('case "dice_result"')[0]
    assert "payload.narration" in turn_update
    assert "text: finalText" in turn_update, (
        "turn_update must overwrite the streamed entry's text, not just clear "
        "its streaming flag"
    )


def test_every_way_a_turn_can_end_early_closes_the_streaming_entry():
    """
    Cause 3's other half, and the shape a playtest found again.

    Three actions end a turn WITHOUT a ``turn_update``: a dropped socket, a
    client-side ERROR (the watchdog fires at 330s, on turns that are still
    running) and a server ``turn_error``. Each used to null ``streamingId`` on
    its own and leave the half-streamed paragraph orphaned in the log -- so when
    the authoritative narration arrived, ``turn_update`` saw no ``streamingId``,
    took its append branch, and printed the same prose a second time underneath
    it. They must all funnel through the one helper that takes the orphan with
    it.

    ``ui/tests/store.test.js`` drives the sequence; this only guards that a
    fourth exit cannot be added without one.
    """
    store = (UI_SRC / "core" / "store.js").read_text(encoding="utf-8")
    for case, until in (
        ('case "DISCONNECTED"', 'case "ERROR"'),
        ('case "ERROR"', 'case "SUBMIT"'),
        ('case "turn_error"', 'case "resume_failed"'),
    ):
        body = store.split(case)[1].split(until)[0]
        assert "closeStream(" in body, f"{case} clears streamingId without closing the entry"


def test_the_narration_is_never_left_in_the_page_twice():
    """
    Measured live on the flagship, two consecutive turns: the log held one
    ``.entry--narration`` and one ``.visually-hidden`` announcement carrying the
    same 602 characters, which reads as the turn having been rendered twice.

    Two things made that true and both are asserted here: ``role="log"`` carries
    an implicit ``aria-live="polite"``, so the container announced every entry
    itself on top of the dedicated region, and the region never cleared, so the
    paragraph stayed in the log as a second readable copy.
    """
    log = (UI_SRC / "core" / "parts" / "NarrativeLog.jsx").read_text(encoding="utf-8")
    assert 'role="log" aria-live="off"' in log, (
        'role="log" is implicitly a live region; leaving it implicit announces '
        "every entry a second time"
    )
    assert "ANNOUNCE_LINGER_MS" in log, "the announcement must be withdrawn, not left in the page"
    assert 'setTimeout(() => setAnnouncement("")' in log


def test_the_server_sends_the_completion_signal():
    state = (
        Path(__file__).resolve().parent.parent
        / "engine" / "scenes" / "default_state.py"
    ).read_text(encoding="utf-8")
    assert '"narration_complete"' in state


def test_the_delta_queue_is_paced_and_always_fully_flushed():
    """
    A paced drain must never be able to strand the tail: `flushNow` empties the
    queue outright, and every non-streamed event calls it before dispatching.
    """
    socket = (UI_SRC / "core" / "socket.js").read_text(encoding="utf-8")
    assert "requestAnimationFrame" in socket
    assert "DRAIN_DIVISOR" in socket, "the reveal is no longer paced"

    flush_now = socket.split("function flushNow()")[1].split("function clearQueues")[0]
    assert 'queue[event] = ""' in flush_now
    assert "cancelAnimationFrame" in flush_now

    # Every non-streamed listener drains first.
    assert re.search(r"flushNow\(\);\s*\n\s*dispatch\(", socket)


def test_the_reveal_holds_back_a_half_written_word():
    """
    Measured live before this guard: 262 of 319 rendered states ended mid-word
    ("You’re per"). The pacer must return 0 -- release nothing -- when the
    queue ends inside a word, rather than showing the fragment.
    """
    socket = (UI_SRC / "core" / "socket.js").read_text(encoding="utf-8")
    fn = socket.split("function wordBoundary(")[1].split("function step(")[0]
    assert "return 0" in fn or "return text.length > MAX_WORD ? text.length : 0" in fn
    assert "MAX_WORD" in socket, "a spaceless run must still have an escape hatch"


def test_a_dropped_socket_discards_the_queue_rather_than_flushing_it():
    """
    The reducer clears `streamingId` on disconnect, so a flush would land in a
    closed entry -- and a held word fragment would spin the frame loop forever
    waiting on a socket that is gone.
    """
    socket = (UI_SRC / "core" / "socket.js").read_text(encoding="utf-8")
    disconnect = socket.split('socket.on("disconnect"')[1].split('socket.on("connect_error"')[0]
    assert "clearQueues()" in disconnect
    assert "flushNow()" not in disconnect


def test_no_socket_event_was_added_without_registering_it():
    """The narration fix rides on turn_update; it must not invent a channel."""
    socket = (UI_SRC / "core" / "socket.js").read_text(encoding="utf-8")
    inbound = set(re.findall(r'"([a-z_]+)"', socket.split("export const INBOUND")[1].split("]")[0]))
    assert "turn_update" in inbound
    assert "narration_delta" in inbound

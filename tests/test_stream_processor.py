"""StreamProcessor tag extraction tests."""

from __future__ import annotations

from engine.agents.stream_processor import StreamProcessor


def test_extract_image_cutscene_stat_voice():
    text = (
        "You enter the square. [IMAGE:edgewood_square_dawn] "
        "Something stirs. [CUTSCENE:cutscene_stirring_phase] "
        "[STAT:stamina-5] [VOICE:whisper] The oven glows."
    )
    result = StreamProcessor.extract_tags(text)
    assert "edgewood_square_dawn" in result.image_requests
    assert "cutscene_stirring_phase" in result.cutscene_requests
    assert result.stat_deltas[0].stat == "stamina"
    assert result.stat_deltas[0].delta == -5
    assert result.voice_style == "whisper"
    assert "[IMAGE:" not in result.clean_text
    assert "[CUTSCENE:" not in result.clean_text


def test_stream_processor_events():
    proc = StreamProcessor()
    proc.on_event(type("E", (), {"event_type": "chat.start", "model_instance_id": "test-model"})())
    proc.on_event(
        type("E", (), {"event_type": "message.delta", "content": "[MOOD:uneasy] Hello."})()
    )
    proc.on_event(
        type("E", (), {"event_type": "chat.end", "response_id": "resp_abc", "stats": {}})()
    )
    result = proc.result()
    assert result.clean_text == "Hello."
    assert result.mood_tags == ["uneasy"]
    assert result.model == "test-model"
    assert result.response_id == "resp_abc"
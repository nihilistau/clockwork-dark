"""Media pipeline tests — ComfyUI queue, TTS fallback, cutscene budget."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from engine.game.engine import GameEngine
from engine.game.procgen import new_game_state
from engine.game.state import EvilPhase
from engine.media.comfyui import ComfyUIClient, build_image_prompt, load_comfyui_templates
from engine.media.cutscene import CutsceneBudget, CutsceneRunner
from engine.media.interceptors import run_media_interceptors
from engine.media.pipeline import MediaPipeline
from engine.media.queue import make_cache_key, parse_image_tag, reset_media_queue
from engine.media.tts import TTSClient


def _engine() -> GameEngine:
    return GameEngine(new_game_state(seed=42))


def test_parse_image_tag():
    assert parse_image_tag("forest_clearing_dawn") == ("forest_clearing", "dawn")
    assert parse_image_tag("edgewood_square") == ("edgewood_square", "dawn")


def test_cache_key_stable():
    a = make_cache_key("forest_clearing", "dawn", "dormant")
    b = make_cache_key("forest_clearing", "dawn", "dormant")
    assert a == b
    assert a != make_cache_key("forest_clearing", "noon", "dormant")


def test_build_image_prompt():
    prompt = build_image_prompt("forest_clearing_dawn", evil_phase="dormant")
    assert "birch" in prompt.lower()
    assert "oil-painted" in prompt


def test_comfyui_enqueue_placeholder():
    reset_media_queue()
    engine = _engine()
    client = ComfyUIClient()
    job = client.enqueue_image("forest_clearing_dawn", engine.state)
    assert job.kind == "image"
    assert job.status == "placeholder"
    assert "forest_clearing_dawn" in job.url
    from engine.media.queue import get_media_queue

    assert len(get_media_queue().all_jobs()) == 1
    assert job.cache_key in engine.state.media_cache


def test_comfyui_cache_hit():
    reset_media_queue()
    engine = _engine()
    client = ComfyUIClient()
    first = client.enqueue_image("edgewood_square_dawn", engine.state)
    reset_media_queue()
    second = client.enqueue_image("edgewood_square_dawn", engine.state)
    assert second.status == "cached"
    assert second.url == first.url


def test_tts_fallback():
    client = TTSClient(base_url="http://127.0.0.1:1")
    result = client.synthesize("The mist lingers.")
    assert result["success"] is False
    assert result["source"] == "text"
    assert result["text"] == "The mist lingers."


def test_cutscene_budget_blocks_second_in_phase():
    engine = _engine()
    engine.state.evil_phase = EvilPhase.STIRRING
    runner = CutsceneRunner()
    first = runner.enqueue_cutscene("cutscene_stirring_phase", engine.state)
    second = runner.enqueue_cutscene("cutscene_assistant_reveal", engine.state)
    assert first is not None
    assert second is None


def test_cutscene_budget_resets_on_phase_shift():
    engine = _engine()
    engine.state.evil_phase = EvilPhase.STIRRING
    runner = CutsceneRunner()
    runner.enqueue_cutscene("cutscene_stirring_phase", engine.state)
    engine.state.evil_phase = EvilPhase.SPREADING
    allowed = runner.enqueue_cutscene("cutscene_consuming_horizon", engine.state)
    assert allowed is not None


def test_media_pipeline_process_tags():
    reset_media_queue()
    engine = _engine()
    pipe = MediaPipeline()
    result = pipe.process_tags(
        engine.state,
        image_tags=["forest_clearing_dawn"],
        cutscene_tags=["cutscene_stirring_phase"],
        narration="Smoke rises from Edgewood.",
        force_cutscenes=True,
    )
    assert len(result.images) == 1
    assert len(result.cutscenes) == 1


def test_narration_tts_is_off_by_default(monkeypatch):
    """
    Speaking narration costs minutes on this hardware (21x realtime measured),
    so it must not happen unless explicitly asked for.
    """
    reset_media_queue()
    engine = _engine()
    result = MediaPipeline().process_tags(
        engine.state,
        narration="Smoke rises from Edgewood.",
    )
    assert result.tts_jobs == []


def test_narration_tts_queues_when_enabled(monkeypatch):
    reset_media_queue()
    monkeypatch.setattr("engine.media.pipeline.tts_enabled", lambda: True)
    submitted: list[str] = []
    monkeypatch.setattr(
        "engine.media.pipeline.get_speech_worker",
        lambda: type("W", (), {"submit": lambda _s, text, **kw: submitted.append(text)})(),
    )

    engine = _engine()
    result = MediaPipeline().process_tags(
        engine.state,
        narration="Smoke rises from Edgewood.",
    )
    assert len(result.tts_jobs) == 1
    # Queued for the background worker, not synthesized inline.
    assert result.tts_jobs[0].status == "queued"
    assert submitted == ["Smoke rises from Edgewood."]


def test_run_media_interceptors():
    reset_media_queue()
    engine = _engine()
    data = run_media_interceptors(
        engine.state,
        narration="A cold morning.",
        processed_tags={"image": ["forest_clearing_dawn"]},
    )
    assert len(data["images"]) == 1


def test_comfyui_submit_when_enabled():
    reset_media_queue()
    engine = _engine()
    client = ComfyUIClient()
    client.enabled = True

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"prompt_id": "abc123"}

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        job = client.enqueue_image("edgewood_square_noon", engine.state)
        assert job.status == "submitted"
        assert job.payload["comfyui"]["prompt_id"] == "abc123"
        mock_client.post.assert_called_once()


def test_comfyui_templates_load():
    tpl = load_comfyui_templates()
    assert "forest_clearing" in tpl.get("locations", {})
    assert "cutscene_stirring_phase" in tpl.get("cutscenes", {})

# -- Voxtral utterance splitting -----------------------------------------
#
# The server hard-rejects anything over 400 chars with HTTP 400 and says so:
# long input on this build does not degrade, it blows up. Splitting is a
# correctness requirement, not an optimization.

def test_short_text_is_one_utterance():
    from engine.media.tts import split_utterances

    assert split_utterances("The smoke is bread, not burning.") == [
        "The smoke is bread, not burning."
    ]


def test_long_narration_splits_on_sentence_boundaries():
    from engine.media.tts import split_utterances

    sentence = "Maris does not stop working while she answers her visitor. "
    text = sentence * 12  # ~700 chars
    chunks = split_utterances(text, max_chars=400)

    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks)
    # Nothing is lost in the split.
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_single_overlong_sentence_falls_back_to_words():
    from engine.media.tts import split_utterances

    text = "word " * 200  # one 1000-char run with no sentence boundary
    chunks = split_utterances(text, max_chars=120)
    assert all(len(c) <= 120 for c in chunks)
    assert len(chunks) > 1


def test_empty_text_yields_nothing():
    from engine.media.tts import split_utterances

    assert split_utterances("   ") == []


def test_synthesize_refuses_overlong_text_without_calling_the_server():
    from engine.media.tts import TTSClient

    client = TTSClient(base_url="http://127.0.0.1:1")
    result = client.synthesize("x" * 500)
    assert result["success"] is False
    assert result["source"] == "too_long"


def test_synthesize_never_returns_bytes():
    """
    The result is embedded in the turn payload and jsonify'd; raw bytes there
    raise TypeError and take down the whole turn.
    """
    import json

    from engine.media.tts import TTSClient

    result = TTSClient(base_url="http://127.0.0.1:1").synthesize("A line.")
    json.dumps(result)  # must not raise

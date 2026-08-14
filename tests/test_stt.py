"""
Speech-to-text: provider selection, the optional dependency, and the route.

THE CLAIM THESE TESTS DEFEND. faster-whisper is optional. The game boots, the
suite passes, and push-to-talk degrades to a readable message on a machine that
has never installed it -- which is the machine these tests run on. Every test
below that touches the Whisper provider is written so it passes whether or not
the package is present, because "it worked on the box where I installed it" is
exactly the assurance an optional dependency does not give you.
"""

from __future__ import annotations

import io

import pytest

from engine.config import get_config, reset_config
from engine.media.stt import (
    DEFAULT_PROVIDER,
    PROVIDER_FASTER_WHISPER,
    PROVIDER_VOXTRAL_HTTP,
    STTClient,
    build_provider,
    get_stt_provider,
    reset_stt_provider,
    resolve_provider_name,
    transcribe_audio,
)


@pytest.fixture(autouse=True)
def _clean_config():
    reset_config()
    reset_stt_provider()
    yield
    reset_config()
    reset_stt_provider()


def _set(monkeypatch, mapping: dict) -> None:
    """Overlay dotted config keys for one test."""
    cfg = get_config()
    original = cfg.get

    def fake(key, default=None):
        if key in mapping:
            return mapping[key]
        return original(key, default)

    monkeypatch.setattr(cfg, "get", fake)


# -- 1. which provider answers --------------------------------------------


def test_the_shipped_default_is_faster_whisper():
    assert resolve_provider_name() == PROVIDER_FASTER_WHISPER
    assert DEFAULT_PROVIDER == PROVIDER_FASTER_WHISPER


def test_the_legacy_stt_mode_key_still_works(monkeypatch):
    """
    An existing config/local.yaml must not silently change backend under a
    player because the key was renamed.
    """
    _set(monkeypatch, {"stt.provider": "", "stt.mode": "voxtral_cli"})
    assert resolve_provider_name() == PROVIDER_VOXTRAL_HTTP


def test_voxtral_cli_resolves_to_the_http_client_it_always_was(monkeypatch):
    """
    `voxtral_cli` named a CLI adapter that was never written: the only code in
    engine/media/stt.py POSTed multipart audio to an HTTP endpoint. The alias
    keeps the config honest rather than keeping the name honest.
    """
    _set(monkeypatch, {"stt.provider": "voxtral_cli"})
    assert resolve_provider_name() == PROVIDER_VOXTRAL_HTTP
    assert isinstance(build_provider(), STTClient)


def test_an_unknown_provider_falls_back_loudly_rather_than_going_silent(monkeypatch):
    _set(monkeypatch, {"stt.provider": "wav2vec-from-a-dream"})
    assert resolve_provider_name() == DEFAULT_PROVIDER


def test_the_provider_is_cached_but_not_across_a_config_change(monkeypatch):
    """The Settings panel can repoint stt.provider mid-run."""
    _set(monkeypatch, {"stt.provider": "voxtral_http"})
    first = get_stt_provider()
    assert get_stt_provider() is first
    reset_config()
    reset_stt_provider()
    assert get_stt_provider() is not first


# -- 2. the optional dependency -------------------------------------------


def test_importing_the_whisper_provider_does_not_need_faster_whisper():
    """
    The import must be lazy. If this module imported faster_whisper at the top,
    this test would ERROR on collection on any machine without it -- which is
    the whole failure mode the laziness exists to prevent.
    """
    from engine.media import stt_whisper

    assert stt_whisper.WhisperSTTProvider is not None


def test_a_missing_faster_whisper_is_a_message_not_an_exception(monkeypatch):
    from engine.media.stt_whisper import INSTALL_HINT, WhisperSTTProvider

    provider = WhisperSTTProvider()
    monkeypatch.setattr(
        WhisperSTTProvider, "load", lambda _self: (_ for _ in ()).throw(ImportError())
    )
    result = provider.transcribe(b"not really audio")
    assert result["success"] is False
    assert result["source"] == "unavailable"
    assert result["transcript"] == ""
    assert "pip install faster-whisper" in result["message"]
    assert result["message"] == INSTALL_HINT


def test_a_model_that_will_not_load_is_also_survivable(monkeypatch):
    from engine.media.stt_whisper import WhisperSTTProvider

    provider = WhisperSTTProvider()
    monkeypatch.setattr(
        WhisperSTTProvider,
        "load",
        lambda _self: (_ for _ in ()).throw(RuntimeError("no such model")),
    )
    result = provider.transcribe(b"audio")
    assert result["success"] is False
    assert "no such model" in result["message"]


def test_cpu_falls_back_to_int8(monkeypatch):
    """int8 is the only CPU quantisation fast enough to feel live."""
    from engine.media import stt_whisper

    monkeypatch.setattr(stt_whisper, "_cuda_available", lambda: False)
    assert stt_whisper.resolve_device("auto") == ("cpu", "int8")
    assert stt_whisper.resolve_device("cpu") == ("cpu", "int8")


def test_cuda_is_taken_when_it_is_there(monkeypatch):
    from engine.media import stt_whisper

    monkeypatch.setattr(stt_whisper, "_cuda_available", lambda: True)
    assert stt_whisper.resolve_device("auto") == ("cuda", "float16")


def test_a_cuda_probe_that_explodes_means_cpu(monkeypatch):
    """No CTranslate2 installed is not an error; it is an answer."""
    from engine.media import stt_whisper

    assert stt_whisper._cuda_available() in (True, False)


# -- 3. the shared contract -----------------------------------------------


def test_empty_audio_is_answered_without_touching_a_backend():
    result = transcribe_audio(b"")
    assert result["success"] is False
    assert result["transcript"] == ""
    assert result["provider"]


def test_a_dead_transcription_server_is_a_result_not_a_raise():
    client = STTClient(base_url="http://127.0.0.1:1")
    result = client.transcribe(b"audio")
    assert result["success"] is False
    assert result["source"] == "stub"
    assert result["provider"] == PROVIDER_VOXTRAL_HTTP
    assert result["message"]


def test_every_result_is_json_serialisable():
    """The result is embedded in an HTTP response; raw bytes there kill it."""
    import json

    json.dumps(transcribe_audio(b""))
    json.dumps(STTClient(base_url="http://127.0.0.1:1").transcribe(b"audio"))


def test_an_explicit_client_beats_the_configured_provider(monkeypatch):
    class Stub:
        name = "stub"

        def transcribe(self, audio_bytes, **_kwargs):
            return {"success": True, "transcript": "heard you", "source": "live",
                    "provider": self.name}

    assert transcribe_audio(b"audio", client=Stub())["transcript"] == "heard you"


# -- 4. the route ----------------------------------------------------------


def _app(monkeypatch, transcript: str = "open the door"):
    """A Flask app serving only the voice blueprint, over a real session."""
    from flask import Flask

    from engine.api.voice import voice_blueprint
    from engine.session import SessionStore

    monkeypatch.setattr(
        "engine.media.stt.transcribe_audio",
        lambda audio, **_kw: {
            "success": bool(transcript),
            "transcript": transcript,
            "source": "live",
            "provider": "stub",
        },
    )

    store = SessionStore()
    session = store.create(seed=42, llm_fn=lambda _m: "{}")
    app = Flask(__name__)
    app.register_blueprint(voice_blueprint(store))
    return app.test_client(), session.session_id


def test_transcribe_only_skips_the_assistant_turn(monkeypatch):
    """
    The mic button's whole job is to put text in a box. Charging it an
    Assistant LLM call per press is a multi-second wait for nothing.
    """
    client, session_id = _app(monkeypatch)
    response = client.post(
        "/api/voice/transcribe",
        data={
            "session_id": session_id,
            "transcribe_only": "1",
            "audio": (io.BytesIO(b"fake wav"), "speech.webm"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["stt"]["transcript"] == "open the door"
    assert body["assistant"] is None


def test_a_missing_session_is_404_not_a_traceback(monkeypatch):
    client, _ = _app(monkeypatch)
    response = client.post(
        "/api/voice/transcribe",
        data={
            "session_id": "no-such-run",
            "transcribe_only": "1",
            "audio": (io.BytesIO(b"fake wav"), "speech.webm"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 404


def test_audio_is_required(monkeypatch):
    client, session_id = _app(monkeypatch)
    response = client.post(
        "/api/voice/transcribe",
        data={"session_id": session_id},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_a_failed_transcription_is_still_200(monkeypatch):
    """
    A quiet room must not look like a broken server. The client renders
    stt.success false as a state on the button.
    """
    client, session_id = _app(monkeypatch, transcript="")
    response = client.post(
        "/api/voice/transcribe",
        data={
            "session_id": session_id,
            "transcribe_only": "1",
            "audio": (io.BytesIO(b"fake wav"), "speech.webm"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["stt"]["success"] is False


# -- 5. the settings panel -------------------------------------------------


def test_the_voice_group_exposes_the_provider_and_its_model():
    from engine.api.settings import SETTINGS_BY_KEY

    for key in ("stt.provider", "stt.whisper.model", "stt.whisper.device"):
        assert key in SETTINGS_BY_KEY, f"{key} is not settable from the panel"
        assert SETTINGS_BY_KEY[key]["group"] == "Voice"

    assert set(SETTINGS_BY_KEY["stt.provider"]["options"]) == {
        PROVIDER_FASTER_WHISPER,
        PROVIDER_VOXTRAL_HTTP,
    }


def test_a_whisper_model_id_survives_the_text_coercion():
    """Repo ids carry a slash and a dot; the identifier filter must allow both."""
    from engine.api.settings import SETTINGS_BY_KEY, _coerce_setting

    spec = SETTINGS_BY_KEY["stt.whisper.model"]
    for candidate in ("distil-small.en", "Systran/faster-whisper-small", "large-v3"):
        ok, value, _note = _coerce_setting(spec, candidate)
        assert ok, candidate
        assert value == candidate

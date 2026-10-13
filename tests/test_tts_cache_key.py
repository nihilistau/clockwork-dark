"""F7 (v0.22.0 T21): two speakers saying the same words must not share one audio file.

`tts.cache_key(text, voice)` always took the voice, but `write_audio` and
`cached_url` keyed the file by the text alone, so the first voice to say a
line answered for every voice after it.
"""

from __future__ import annotations

import httpx
import pytest


def _patch_tts_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """`httpx.Client(...)` inside `synthesize` speaks to ``transport`` (in process, no socket)."""
    from engine.media import tts

    real = httpx.Client

    def handler_client(*args, **kwargs):
        kwargs.pop("verify", None)
        return real(*args, transport=transport, **kwargs)

    monkeypatch.setattr(tts.httpx, "Client", handler_client)


def test_two_voices_saying_the_same_text_get_two_files(tmp_path, monkeypatch) -> None:
    from engine.media import tts
    from engine.persistence import storage

    monkeypatch.setattr(storage, "audio_dir", lambda: tmp_path)
    a = tts.write_audio(b"RIFF-a", "see you tonight", voice="warm_female")
    b = tts.write_audio(b"RIFF-b", "see you tonight", voice="old_male")
    assert a != b
    assert tts.cached_url("see you tonight", "warm_female") == a
    assert tts.cached_url("see you tonight", "old_male") == b
    assert (tmp_path / a.rsplit("/", 1)[1]).read_bytes() == b"RIFF-a"
    assert (tmp_path / b.rsplit("/", 1)[1]).read_bytes() == b"RIFF-b"


def test_a_line_with_no_voice_keeps_its_old_name(tmp_path, monkeypatch) -> None:
    """Audio already on disk (written with no voice) is still found under the same name."""
    from engine.media import tts
    from engine.persistence import storage

    monkeypatch.setattr(storage, "audio_dir", lambda: tmp_path)
    url = tts.write_audio(b"RIFF", "a sentence")
    assert url == f"/api/audio/{tts.cache_key('a sentence')}.wav"
    assert tts.cached_url("a sentence") == url
    narrator = str(__import__("engine.config", fromlist=["get_config"]).get_config().get("tts.voice"))
    other = next(v for v in ("warm_female", "old_male") if v != narrator)
    assert tts.cached_url("a sentence", other) is None


def test_the_narrators_cache_from_before_the_fix_is_still_read(tmp_path, monkeypatch) -> None:
    """M3: narration cached before v0.22.0 (named by the text alone) answers for the configured
    `tts.voice` -- the only voice it can have been spoken in -- and for no other voice."""
    from engine.config import get_config
    from engine.media import tts
    from engine.persistence import storage

    monkeypatch.setattr(storage, "audio_dir", lambda: tmp_path)
    narrator = str(get_config().get("tts.voice"))
    other = next(v for v in ("warm_female", "old_male") if v != narrator)
    legacy = tts.write_audio(b"RIFF-old", "the lamps gutter")          # how v0.21 named it
    assert tts.cached_url("the lamps gutter", narrator) == legacy
    assert tts.cached_url("the lamps gutter", other) is None

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a cached line was synthesized again")

    _patch_tts_transport(monkeypatch, httpx.MockTransport(refuse))
    hit = tts.TTSClient().synthesize("the lamps gutter")                 # the default voice: the narrator's
    assert hit["source"] == "cache" and hit["audio_url"] == legacy


def test_synthesize_writes_under_its_own_voice(tmp_path, monkeypatch) -> None:
    from engine.media import tts
    from engine.persistence import storage
    from tests.tts_stub import wav_bytes

    monkeypatch.setattr(storage, "audio_dir", lambda: tmp_path)
    bodies = {"warm_female": wav_bytes(0.5), "old_male": wav_bytes(0.75)}

    def answer(request: httpx.Request) -> httpx.Response:
        import json

        voice = json.loads(request.content)["voice"]
        return httpx.Response(200, content=bodies[voice], headers={"content-type": "audio/wav"})

    _patch_tts_transport(monkeypatch, httpx.MockTransport(answer))
    first = tts.TTSClient().synthesize("hey", voice="warm_female")
    second = tts.TTSClient().synthesize("hey", voice="old_male")
    assert first["source"] == "live" and second["source"] == "live"
    assert first["audio_url"] != second["audio_url"]
    assert (tmp_path / second["audio_url"].rsplit("/", 1)[1]).read_bytes() == bodies["old_male"]
    again = tts.TTSClient().synthesize("hey", voice="warm_female")
    assert again["source"] == "cache" and again["audio_url"] == first["audio_url"]


@pytest.mark.parametrize("behaviour", ["not_wav", "oversize", "down"])
def test_synthesize_keeps_nothing_that_is_not_a_bounded_wav(tmp_path, monkeypatch, behaviour) -> None:
    """Size and type are checked (by magic bytes, at most `tts.max_bytes`): the text fallback, no file."""
    from engine.media import tts
    from engine.persistence import storage
    from tests.tts_stub import StubTTS

    monkeypatch.setattr(storage, "audio_dir", lambda: tmp_path)
    result = tts.TTSClient(transport=StubTTS(behaviour).transport).synthesize("hey", voice="old_male")
    assert result["success"] is False and result["source"] == "text"
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(tts.TTSError):
        tts.TTSClient(transport=StubTTS(behaviour).transport).speak("hey", voice="old_male")

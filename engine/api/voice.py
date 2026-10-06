"""
Voice HTTP API
==============

    POST /api/voice/transcribe    push-to-talk: audio in, transcript + reply out

Shared. Speech-to-text and the companion's voice channel are engine services
configured per machine, not per story -- see the ``stt``/``tts`` refusals in
``engine/games/manifest.SETTING_REFUSALS``.

Wire it into a scene with one line in its ``register()``::

    from engine.api.voice import voice_blueprint
    app.register_blueprint(voice_blueprint(self.store))

HOSTED MODE (v0.20.0, spec §6.4, §6.6): the session is the logged-in
account's own (``store.require`` reads the request's owner), the STT result's
``raw`` is dropped, and a failure's words become a generic sentence with a
reference, logged with the original. Local mode answers byte for byte as it
always has (the local-mode golden records the voice error body).

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from engine.config import hosting_enabled
from engine.session import SessionStore

logger = logging.getLogger(__name__)

BLUEPRINT_NAME = "voice"


def _public_stt(stt: dict[str, Any]) -> dict[str, Any]:
    """
    An STT result as hosted mode shows it (spec §6.6): ``raw`` (the STT
    server's own JSON) dropped, and a failure's ``message`` (an exception's
    words, which name the STT server's URL) replaced by "Transcription
    failed (ref ...)", logged under the reference with the original.
    """
    from engine.hosting.errors import TRANSCRIPTION_FAILED, public_message

    public = {key: value for key, value in stt.items() if key != "raw"}
    if "message" in public:
        public["message"], _ref = public_message(
            TRANSCRIPTION_FAILED,
            provider=stt.get("provider", ""),
            message=stt.get("message", ""),
        )
    return public


def voice_blueprint(store: SessionStore, name: str = BLUEPRINT_NAME) -> Blueprint:
    """
    Build the voice blueprint.

    Args:
        store: The scene's live session registry -- a transcription is spoken
            INTO a run, so it needs the session's Assistant and its last scene.
        name: Blueprint name, in case a host app already has one called
            "voice".
    """
    blueprint = Blueprint(name, __name__)

    @blueprint.post("/api/voice/transcribe")
    def api_transcribe() -> Any:
        """
        Audio in, transcript out -- and optionally the companion's reply.

        ``transcribe_only=1`` stops after the transcript. That is what the
        compose row's mic button sends, and it matters: the alternative costs
        an Assistant LLM call on every press of a button whose entire job is to
        put editable text in a box the player has not sent yet.

        A failed transcription is still HTTP 200 with ``stt.success: false`` and
        a message. The client renders that as a state on the button; a 500 would
        make a quiet room look like a broken server.
        """
        from engine.game.engine import active_engine
        from engine.media.stt import transcribe_audio

        session_id = request.form.get("session_id", "")
        audio = request.files.get("audio")
        if audio is None:
            return jsonify({"error": "audio file required"}), 400
        try:
            session = store.require(session_id)
        except KeyError:
            return jsonify({"error": "session not found"}), 404

        transcribe_only = str(request.form.get("transcribe_only", "")).lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        audio_bytes = audio.read()
        hosted = hosting_enabled()
        with active_engine(session.engine):
            # Transcribe once. This used to call transcribe_audio here AND
            # again inside process_voice_input -- two full ASR round trips
            # per push-to-talk, which could disagree with each other.
            stt = transcribe_audio(audio_bytes)
            if hosted:
                stt = _public_stt(stt)
            if transcribe_only:
                return jsonify({"stt": stt, "assistant": None})
            if hosted:
                # Hosted (spec §6.5, T9 fix round 1): a transcript longer than
                # `hosting.max_input_chars` gets no reply. The same text typed
                # would be refused as an action, so the companion is not asked
                # either; the player keeps the transcript, and is told why.
                from engine.config import get_config
                from engine.hosting.limits import too_long

                cap = int(get_config().get("hosting.max_input_chars", 1000))
                if len(str(stt.get("transcript") or "")) > cap:
                    return jsonify({"stt": stt, "assistant": None, "error": too_long(cap)})
            try:
                assistant = session.assistant.process_voice_input(
                    audio_bytes,
                    scene_context=session.last_turn.get("narration", ""),
                    # A string, even "": transcribed once, here, and never
                    # again inside the Assistant (fix round 1).
                    transcript=str(stt.get("transcript") or ""),
                )
            except Exception as exc:  # noqa: BLE001 -- hosted: a reference, not the words
                if not hosted:
                    raise
                from engine.hosting.errors import REPLY_FAILED, public_error

                text, _ref = public_error(exc, REPLY_FAILED, where="voice", id=session_id)
                return jsonify({"stt": stt, "assistant": None, "error": text}), 500
        return jsonify({"stt": stt, "assistant": assistant.to_dict()})

    return blueprint


__all__ = ["BLUEPRINT_NAME", "voice_blueprint"]

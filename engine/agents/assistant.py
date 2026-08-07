"""
Assistant Agent
===============

Player-facing companion — agency rolls, forms, optional hint skills.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from engine.agents.prompts import assistant_system_prompt
from engine.agents.stream_processor import StreamProcessor
from engine.agents.tool_dispatcher import execute_tool_calls
from engine.game.rng import ASSISTANT as RNG_ASSISTANT
from engine.game.rng import world_rng
from engine.skills.registry import AGENT_ASSISTANT
from engine.config import get_config
from engine.game.engine import GameEngine
from engine.media.stt import STTClient, transcribe_audio
from engine.skills.builtin.assistant import ASSISTANT_FORMS, compute_hint_tier

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_LOOSE = re.compile(r"(\{[^{}]*\"text\"[^{}]*\})", re.DOTALL)

FORM_VOICE_STYLES: dict[str, str] = {
    "cat": "chime",
    "wanderer": "whisper",
    "child": "bright",
    "tinker": "dry",
    "reflection": "echo",
}


@dataclass
class AssistantTurnResult:
    """Result of one Assistant turn (may be silent)."""

    text: str
    form: str
    voice_style: str
    spoke: bool
    hint_tier: int
    tool_receipts: list[dict[str, Any]] = field(default_factory=list)
    raw_llm: str = ""
    transcript: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "form": self.form,
            "voice_style": self.voice_style,
            "spoke": self.spoke,
            "hint_tier": self.hint_tier,
            "tool_receipts": self.tool_receipts,
            "transcript": self.transcript,
        }


def parse_assistant_response(raw: str) -> dict[str, Any]:
    """
    Parse Assistant LLM output — plain prose or optional JSON epilogue.

    Args:
        raw: Full LLM response.

    Returns:
        Dict with text, tool_calls, voice_style.
    """
    match = _JSON_BLOCK.search(raw)
    if not match:
        match = _JSON_LOOSE.search(raw)

    if match:
        try:
            data = json.loads(match.group(1))
            prose = raw.split("```")[0].strip()
            text = str(data.get("text") or prose or raw).strip()
            return {
                "text": text,
                "tool_calls": data.get("tool_calls", []),
                "voice_style": str(data.get("voice_style", "")),
            }
        except json.JSONDecodeError:
            pass

    return {
        "text": raw.strip(),
        "tool_calls": [],
        "voice_style": "",
    }


def should_assistant_speak(
    help_probability: float,
    rng: random.Random,
) -> bool:
    """
    Agency roll — Assistant may stay silent.

    Args:
        help_probability: 0–1 willingness to help this turn.
        rng: Injectable RNG for tests.

    Returns:
        True if Assistant should speak.
    """
    return rng.random() <= help_probability


class AssistantAgent:
    """
    In-world companion agent with separate fresh context each turn.

    Args:
        engine: Game engine bound to session state.
        llm_fn: Optional mock LLM callable(messages) -> str.
        stt_client: Optional STT client for voice input.
        rng: Injectable random for agency tests.
    """

    AGENT_ID = "clockwork_assistant"

    def __init__(
        self,
        engine: GameEngine,
        *,
        llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
        lms_client: Any = None,
        stt_client: Optional[STTClient] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.engine = engine
        self.llm_fn = llm_fn
        self._client = lms_client
        self._stt = stt_client or STTClient()
        # None means "draw from the state's deterministic assistant stream".
        # An unseeded Random() here made whether the companion spoke at all
        # unreproducible, so the same seed replayed differently every run.
        self._rng = rng

    def _infer(self, messages: list[dict[str, Any]]) -> str:
        """Call small-profile LLM via injectable fn or LMSClient."""
        if self.llm_fn is not None:
            return self.llm_fn(messages)

        from engine.lmstudio.client import get_lms_client
        from engine.lmstudio.profiles import resolve_profile

        client = self._client or get_lms_client()
        mp = resolve_profile("small")
        max_tokens = int(
            get_config().get("assistant.max_tokens", mp.max_tokens)
        )
        return client.chat(
            messages,
            model=mp.model,
            temperature=mp.temperature,
            max_tokens=max_tokens,
        ).content

    def _build_messages(self, context: str) -> list[dict[str, Any]]:
        """Fresh conversation each turn — store=False semantics."""
        state = self.engine.state
        hint_tier = compute_hint_tier(
            state.assistant_mind.trust_level,
            state.plot_involvement,
        )
        system = assistant_system_prompt(state, hint_tier=hint_tier)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": context},
        ]

    def run_turn(
        self,
        context: str,
        *,
        force_speak: bool = False,
    ) -> AssistantTurnResult:
        """
        Maybe speak after agency roll; execute optional tool_calls.

        Args:
            context: Scene beat or player message for this turn.
            force_speak: Skip agency roll (tests / voice push-to-talk).

        Returns:
            AssistantTurnResult; text empty when silent.
        """
        state = self.engine.state
        mind = state.assistant_mind
        hint_tier = compute_hint_tier(mind.trust_level, state.plot_involvement)
        form = mind.current_form
        voice_style = FORM_VOICE_STYLES.get(form, "whisper")

        if not force_speak and not should_assistant_speak(
            mind.help_probability,
            self._rng or world_rng(state, RNG_ASSISTANT),
        ):
            logger.debug(
                "[assistant] Silent turn (operation=run_turn, form=%s)", form
            )
            return AssistantTurnResult(
                text="",
                form=form,
                voice_style=voice_style,
                spoke=False,
                hint_tier=hint_tier,
            )

        messages = self._build_messages(context)
        try:
            raw = self._infer(messages)
        except Exception as exc:
            logger.warning(
                "[assistant] LLM unavailable (operation=run_turn): %s", exc
            )
            raw = ""

        if not raw.strip():
            return AssistantTurnResult(
                text="",
                form=form,
                voice_style=voice_style,
                spoke=False,
                hint_tier=hint_tier,
            )

        parsed = parse_assistant_response(raw)
        tool_receipts = execute_tool_calls(
            parsed.get("tool_calls", []),
            self.engine,
            agent=AGENT_ASSISTANT,
        )
        form = state.assistant_mind.current_form
        text = parsed.get("text", "")
        tags = StreamProcessor.extract_tags(text)
        voice_style = (
            parsed.get("voice_style")
            or tags.voice_style
            or FORM_VOICE_STYLES.get(form, "whisper")
        )
        clean_text = tags.clean_text or text

        return AssistantTurnResult(
            text=clean_text,
            form=form,
            voice_style=voice_style,
            spoke=bool(clean_text),
            hint_tier=hint_tier,
            tool_receipts=tool_receipts,
            raw_llm=raw,
        )

    def process_voice_input(
        self,
        audio_bytes: bytes,
        *,
        scene_context: str = "",
        transcript: str = "",
    ) -> AssistantTurnResult:
        """
        STT → Assistant (not Storyteller).

        Args:
            audio_bytes: Push-to-talk audio payload.
            scene_context: Optional scene summary prepended to transcript.
            transcript: Pre-computed transcript. Pass this when the caller has
                already transcribed the audio -- the route used to transcribe
                and then call in here, which transcribed the same bytes a
                second time.

        Returns:
            AssistantTurnResult after forced agency speak attempt.
        """
        if transcript.strip():
            transcript = transcript.strip()
        else:
            stt = transcribe_audio(audio_bytes, client=self._stt)
            transcript = str(stt.get("transcript") or "").strip()
        if not transcript:
            state = self.engine.state
            hint_tier = compute_hint_tier(
                state.assistant_mind.trust_level,
                state.plot_involvement,
            )
            return AssistantTurnResult(
                text="",
                form=state.assistant_mind.current_form,
                voice_style=FORM_VOICE_STYLES.get(
                    state.assistant_mind.current_form,
                    "whisper",
                ),
                spoke=False,
                hint_tier=hint_tier,
                transcript="",
            )

        context = transcript
        if scene_context:
            context = f"{scene_context}\n\nPlayer (voice): {transcript}"

        result = self.run_turn(context, force_speak=True)
        result.transcript = transcript
        return result
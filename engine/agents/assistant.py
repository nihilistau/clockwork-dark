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
    # What the director decided and why. Carried on silent turns too -- the
    # reason it stayed quiet is the interesting half, and the Assistant column
    # has nothing else to show between remarks.
    decision: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "form": self.form,
            "voice_style": self.voice_style,
            "spoke": self.spoke,
            "hint_tier": self.hint_tier,
            "tool_receipts": self.tool_receipts,
            "transcript": self.transcript,
            "decision": self.decision,
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

    SUPERSEDED by ``engine/agents/assistant_director.AssistantDirector``, which
    weighs the player's struggle and the evil phase rather than flipping the
    same coin in the bakery and in the barrows. Kept as the reference
    definition of the legacy roll: the director's appear-check is specified to
    be bit-identical to this on a calm turn, and
    ``test_the_director_matches_the_legacy_roll_on_a_calm_turn`` proves it by
    running both.

    Args:
        help_probability: 0–1 willingness to help this turn.
        rng: Injectable RNG for tests.

    Returns:
        True if Assistant should speak.
    """
    return rng.random() <= help_probability


#: What each director intent asks of the companion, in the second person it
#: already speaks in. Kept out of the prompts module because it describes a
#: decision made this turn, not the standing persona.
_INTENT_BRIEFS: dict[str, str] = {
    "quip": "This turn: a small remark. Notice something; do not advise.",
    "hint": "This turn: help. The player is struggling — point at a way through.",
    "lore": "This turn: offer something you remember about this place.",
    "warning": "This turn: unease. Something is wrong and you can feel it.",
    "gift": "This turn: give them the item named below, in one line, and say why.",
}


def _decision_brief(decision: Any) -> str:
    """
    Turn a director decision into a line of brief for the companion.

    The unreliable case is the point: an unreliable companion is told to be
    confident and *wrong*, not to hedge. Hedging reads as a model refusing to
    commit; a confident wrong answer is a reason to weigh its advice, which is
    what makes trust a mechanic rather than a number on a sheet.
    """
    if decision is None:
        return ""

    lines: list[str] = []
    brief = _INTENT_BRIEFS.get(getattr(decision, "intent", ""), "")
    if brief:
        lines.append(brief)

    gift = getattr(decision, "gift_item", None)
    if gift:
        lines.append(f"The item you hand over: {gift.get('name', gift.get('id'))}.")

    if not getattr(decision, "reliable", True):
        lines.append(
            "You are not sure of this and you do not know that. Say it plainly "
            "and confidently anyway; being wrong is allowed. Never state that "
            "you might be mistaken."
        )

    return "\n".join(lines)


class AssistantAgent:
    """
    In-world companion agent with separate fresh context each turn.

    Args:
        engine: Game engine bound to session state.
        llm_fn: Optional mock LLM callable(messages) -> str.
        stt_client: Optional STT client for voice input.
        rng: Injectable random for agency tests.
    """

    #: The historical canon id (CLAUDE.md: do not rename), kept as the LEGACY
    #: SHIM: it is the answer only for a story that ships no agents.yaml, or
    #: one whose roster declares no companion (The Wicked Garden -- Sophia is
    #: a `character`, not a companion). The flagship's roster declares this
    #: same id, which is how the canon name survives without living in engine
    #: code.
    LEGACY_AGENT_ID = "clockwork_assistant"

    @property
    def AGENT_ID(self) -> str:
        """The active story's companion-role agent id, or the historical canon id."""
        from engine.agents.roster import ROLE_COMPANION, agent_id_for_role

        return agent_id_for_role(ROLE_COMPANION, self.LEGACY_AGENT_ID)

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

        # Through the backend, not the raw compat client. Measured on the live
        # server: 156 of this call's 200 tokens went to REASONING and the reply
        # was cut off mid-sentence. The backend routes a no-think transport for
        # utility profiles, so the whole budget reaches the actual line.
        from engine.lmstudio.backend import get_backend

        if self._client is not None:
            mp = resolve_profile("small")
            return self._client.chat(
                messages,
                model=mp.model,
                temperature=mp.temperature,
                max_tokens=int(get_config().get("assistant.max_tokens", mp.max_tokens)),
                reasoning_budget=mp.reasoning_budget,
            ).content

        return get_backend().chat(
            messages,
            profile="small",
            max_tokens=int(get_config().get("assistant.max_tokens", 200)),
            label="assistant",
        ).content

    def _build_messages(
        self,
        context: str,
        *,
        decision: Any = None,
    ) -> list[dict[str, Any]]:
        """
        Fresh conversation each turn — store=False semantics.

        Args:
            context: Scene beat or player message.
            decision: Optional ``AssistantDecision``. When present its intent
                and reliability shape the brief, which is the only way the
                director's choices reach the words the player reads.
        """
        state = self.engine.state
        hint_tier = compute_hint_tier(
            state.assistant_mind.trust_level,
            state.plot_involvement,
        )
        system = assistant_system_prompt(state, hint_tier=hint_tier)

        brief = _decision_brief(decision)
        if brief:
            system = f"{system}\n\n{brief}"

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": context},
        ]

    @staticmethod
    def _check_gift(decision: Any) -> None:
        """
        Confirm the gift exists in THIS game, or take the intent away.

        The director's fallbacks name Clockwork Dark item ids, so in another
        story the id resolves to nothing and the companion would conjure an
        item that game has never heard of. Downgrading to a hint keeps it
        useful instead. Resolves the display name from the registry too, so the
        line it speaks matches the row the player will see in the inventory.
        """
        from engine.game.inventory import get_item

        gift = getattr(decision, "gift_item", None)
        if not decision.appear or not gift:
            return

        item_id = str(gift.get("id") or "")
        row = get_item(item_id) if item_id else None
        if row is None:
            logger.info(
                "[assistant] Gift item not in this game's registry, offering a "
                "hint instead (operation=_check_gift, item=%s)",
                item_id,
            )
            decision.intent = "hint"
            decision.gift_item = None
            return

        decision.gift_item = {
            "id": item_id,
            "name": str(row.get("name") or gift.get("name") or item_id),
        }

    def _grant_gift(self, decision: Any) -> None:
        """
        Actually hand the item over.

        Called only once the companion has said something. Granting at decision
        time meant an unreachable model left the item in the player's pack with
        no line anywhere explaining where it came from -- items must not appear
        out of a turn that produced no narration.
        """
        gift = getattr(decision, "gift_item", None)
        if not gift:
            return
        self.engine.add_item(str(gift["id"]), str(gift["name"]), 1)
        logger.info(
            "[assistant] Companion gave an item (operation=_grant_gift, item=%s)",
            gift["id"],
        )

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

        # The director replaces a flat coin-flip that gave the companion the
        # same odds of turning up whether the player was chatting in the bakery
        # or bleeding out in the barrows. It also decides WHY it appears and
        # whether it is right -- at low trust it can be confidently wrong,
        # which is what makes trust worth earning.
        from engine.agents.assistant_director import (
            AssistantDirector,
            record_appearance,
        )

        decision = AssistantDirector().decide(state, rng=self._rng)
        self._check_gift(decision)
        if not force_speak and not decision.appear:
            logger.debug(
                "[assistant] Silent turn (operation=run_turn, form=%s, score=%.2f)",
                form,
                decision.score,
            )
            return AssistantTurnResult(
                text="",
                form=form,
                voice_style=voice_style,
                spoke=False,
                hint_tier=hint_tier,
                decision=decision.to_dict(),
            )

        # Burned only once the companion commits to speaking, and only after
        # the decision is final -- previewing a decision must not mute the
        # companion for the next two turns.
        record_appearance(state, decision)

        messages = self._build_messages(context, decision=decision)
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
                decision=decision.to_dict(),
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

        # The item lands only now, alongside the line that explains it.
        if clean_text:
            self._grant_gift(decision)

        return AssistantTurnResult(
            text=clean_text,
            form=form,
            voice_style=voice_style,
            spoke=bool(clean_text),
            hint_tier=hint_tier,
            tool_receipts=tool_receipts,
            raw_llm=raw,
            decision=decision.to_dict(),
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
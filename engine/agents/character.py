"""
Character Agent
===============

A second voice that wants something, as opposed to a hint system.

WHAT THIS IS NOT. ``engine/agents/assistant.py`` is a companion: it decides
whether to speak, offers a hint at a tier, and is deliberately stateless and
short. That is the right shape for a guide standing at the edge of the scene.
It is the wrong shape for a character who is the *subject* of the story, who has
private motives, who is permitted to be wrong, and whose regard is a mechanic.

WHAT MAKES IT DIFFERENT, CONCRETELY:

  * **Its persona is the story's.** Loaded from the roster's ``prompt`` file,
    not from a constant in the engine.
  * **It is scope-blind by construction.** The knowledge policy filters what
    reaches its prompt, so a character barred from ``gm_secrets`` is not
    trusted to ignore them -- it never receives them. Trusting a model not to
    use what you handed it is not a partition.
  * **It may write state, within its declared permissions.** The roster says
    which values, and which need a reason; the store refuses and journals the
    rest. The companion writes nothing.
  * **It is not asked to narrate.** The world has a narrator. This agent
    produces speech and intent, and the prompt says so in the hardest terms
    available, because the single most common failure of a second agent is that
    it starts describing the room.

WHEN THIS RUNS, NOW THAT THE PIPELINE DOES. A story declaring two or more
agents goes through ``engine/agents/pipeline.py`` instead: every agent PLANS
against pre-commit state, the plans are negotiated, the accepted effects land in
one commit, and the narrator writes once knowing the answer. A character who
planned has already spoken -- her words came out of her plan and went to the
narrator verbatim -- so this module is not called on those turns.

It remains the path for a story that declares exactly ONE agent with
``role: character``: there is nobody to negotiate with, so she reacts to
finished prose, which is the right shape for that story and the wrong one for
two. Both shipped games declare no roster at all and reach neither.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: Hard ceiling on a character's turn. She is an interruption in someone else's
#: paragraph; a model given room will write a paragraph of its own.
MAX_TOKENS = 220


@dataclass
class CharacterTurn:
    """What the character did this turn."""

    agent: str = ""
    text: str = ""
    spoke: bool = False
    #: Values it moved, as receipts from the one writer.
    receipts: list[dict[str, Any]] = field(default_factory=list)
    #: Recorded refusals -- writes it attempted outside its permissions.
    refused: list[dict[str, Any]] = field(default_factory=list)
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "text": self.text,
            "spoke": self.spoke,
            "receipts": self.receipts,
            "refused": self.refused,
        }


class CharacterAgent:
    """
    One declared character, speaking for itself.

    Args:
        spec: The roster entry -- id, voices, reads, writes, profile, prompt.
        engine: Game engine bound to the session state.
        policy: Knowledge policy, for scope filtering.
        llm_fn: Optional injected LLM for tests.
    """

    def __init__(
        self,
        spec: Any,
        engine: Any,
        *,
        policy: Any = None,
        llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
    ) -> None:
        self.spec = spec
        self.engine = engine
        self.policy = policy
        self.llm_fn = llm_fn

    # -- prompt ----------------------------------------------------------

    def _persona(self) -> str:
        """
        The character's own voice file, from the story's prompt directory.

        Returns empty when the story declares a character but ships no prompt
        for it -- and an empty persona means this agent does not speak at all.
        A character with no voice should be silent, not improvised from the
        engine's idea of one.
        """
        from engine.config import get_config, project_root

        name = str(getattr(self.spec, "prompt", "") or "")
        if not name:
            return ""
        base = str(get_config().get("paths.prompts", "") or "")
        if not base:
            return ""
        root = Path(base)
        if not root.is_absolute():
            root = project_root() / root
        # `prompt: prompts/sophia.md` is written relative to the story root, and
        # `paths.prompts` already points at that directory -- so take the leaf.
        target = root / Path(name).name
        try:
            return target.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning(
                "[character] No voice file, staying silent "
                "(operation=_persona, agent=%s, path=%s): %s",
                self.spec.id,
                target,
                exc,
            )
            return ""

    def _scene_block(self, narration: str) -> str:
        """
        What just happened, filtered by what this character may know.

        Every line is tagged with a scope and run through the policy, so a
        character barred from the world's secrets never receives them. The
        filtering happens HERE rather than in the prompt text, because "do not
        use the following" is an instruction and this is a wall.
        """
        from engine.agents.knowledge import SCOPE_CHARACTER, SCOPE_PUBLIC

        state = self.engine.state
        blocks: list[tuple[str, str]] = [
            (SCOPE_PUBLIC, f"Where you are: {state.location_id}."),
            (SCOPE_PUBLIC, f"What just happened:\n{narration.strip()}"),
        ]

        # The character's own standing with the player, which is hers to know.
        try:
            from engine.state.active import store_for
            from engine.state.schema import VISIBILITY_HIDDEN

            store = store_for(state)
            mine = [
                f"{spec.display_label}: {spec.band(store.get(name))}"
                for name, spec in store.schema.values.items()
                if self.spec.id in spec.owners and spec.visibility != VISIBILITY_HIDDEN
            ]
            if mine:
                blocks.append(
                    (SCOPE_CHARACTER, "How you feel about them: " + "; ".join(mine))
                )
        except Exception as exc:  # noqa: BLE001 -- a missing meter is not a turn
            logger.debug("[character] No declared meters: %s", exc)

        if self.policy is None:
            return "\n\n".join(text for _scope, text in blocks)
        return "\n\n".join(self.policy.filter_blocks(self.spec.id, blocks))

    # -- the turn --------------------------------------------------------

    def run_turn(self, narration: str) -> CharacterTurn:
        """
        Speak, or decide not to.

        Silence is a real outcome and is returned as one. The prompt says as
        much: a model that must produce something will produce filler, and
        filler from a character who is meant to be dangerous is worse than a
        turn where she simply watches.
        """
        result = CharacterTurn(agent=self.spec.id)

        persona = self._persona()
        if not persona:
            return result

        messages = [
            {"role": "system", "content": persona},
            {"role": "user", "content": self._scene_block(narration)},
        ]

        try:
            raw = self._infer(messages)
        except Exception as exc:  # noqa: BLE001 -- her silence is not an outage
            logger.warning(
                "[character] Model unavailable, staying silent "
                "(operation=run_turn, agent=%s): %s",
                self.spec.id,
                exc,
            )
            return result

        text = _clean(raw)
        result.raw = raw
        result.text = text
        result.spoke = bool(text)
        if text:
            logger.info(
                "[character] Spoke (operation=run_turn, agent=%s, chars=%d)",
                self.spec.id,
                len(text),
            )
        return result

    def _infer(self, messages: list[dict[str, Any]]) -> str:
        if self.llm_fn is not None:
            return self.llm_fn(messages)

        from engine.lmstudio.backend import get_backend

        return get_backend().chat(
            messages,
            profile=str(getattr(self.spec, "profile", "small") or "small"),
            max_tokens=MAX_TOKENS,
            label=f"character:{self.spec.id}",
        ).content


def _clean(raw: str) -> str:
    """
    Strip the wrappers a chat model reaches for when asked to be a person.

    Quotes around the whole line, a name prefix, a stage direction in
    asterisks. None of these are her; they are the model narrating that it is
    about to speak, which is the failure this agent exists to avoid.
    """
    text = (raw or "").strip()
    if not text:
        return ""

    for prefix in ("Sophia:", "SOPHIA:", "sophia:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    if len(text) > 1 and text[0] in "\"'“" and text[-1] in "\"'”":
        inner = text[1:-1]
        # Only unwrap when the quotes actually enclose the WHOLE line -- a line
        # that opens and closes with dialogue quotes around separate clauses is
        # her speaking twice, not one quoted block.
        if inner.count('"') == 0:
            text = inner.strip()

    return text.strip()


def character_for(engine: Any, *, llm_fn: Any = None) -> Optional[CharacterAgent]:
    """
    The active story's character agent, or None.

    None is the answer for both shipped games and for any story that declares
    no ``role: character``. The caller falls back to the companion, so nothing
    changes for a story that never asked for one.
    """
    try:
        from engine.agents.roster import ROLE_CHARACTER
        from engine.state.active import active_roster

        roster = active_roster()
        characters = roster.of_role(ROLE_CHARACTER) if roster else []
        if not characters:
            return None
        return CharacterAgent(
            characters[0],
            engine,
            policy=roster.knowledge(),
            llm_fn=llm_fn,
        )
    except Exception as exc:  # noqa: BLE001 -- never block a turn on the roster
        logger.debug("[character] No character agent available: %s", exc)
        return None


__all__ = ["MAX_TOKENS", "CharacterAgent", "CharacterTurn", "character_for"]

"""
Comms Interceptors (PRE)
========================

Lore injection and awareness gating for agent prompts.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import functools
import logging
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.state import GameState
from engine.lore.manager import LoreManager, get_lore_manager

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

#: Filename a story puts in its own ``paths.rules`` directory to declare what
#: its narration must not name before the player has earned it.
SPOILER_FILE = "spoilers.yaml"


@functools.lru_cache(maxsize=8)
def _compile_terms(rules_dir: str, _mtime: float) -> tuple[tuple[re.Pattern[str], str], ...]:
    """Parse and compile one story's spoiler table, memoized on (dir, mtime)."""
    path = Path(rules_dir) / SPOILER_FILE
    try:
        with path.open(encoding="utf-8") as handle:
            rows = (yaml.safe_load(handle) or {}).get("spoilers") or []
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[lore] Unreadable spoiler table at %s: %s", path, exc)
        return ()

    out: list[tuple[re.Pattern[str], str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        term = str(row.get("term") or "").strip()
        instead = str(row.get("instead") or "").strip()
        if not term or not instead:
            continue
        # The leading article is swallowed so the replacement reads as English.
        # Matching the bare term produced "names the something wrong in the
        # wheat", which is the sort of thing a player screenshots.
        flags = 0 if row.get("case_sensitive") else re.IGNORECASE
        try:
            out.append((re.compile(rf"\b(?:the\s+)?{re.escape(term)}\b", flags), instead))
        except re.error as exc:
            logger.warning("[lore] Bad spoiler term %r: %s", term, exc)
    return tuple(out)


def spoiler_terms() -> tuple[tuple[re.Pattern[str], str], ...]:
    """
    What the RUNNING story will not have named yet, and what to say instead.

    THIS WAS A LIST OF ONE STORY'S NOUNS IN THE ENGINE. It masked "Clockwork
    Dark" as "something wrong in the wheat" and ``evil_progress`` as "the
    village's unease" -- for every story, forever. A fae court below the
    awareness threshold had its narration rewritten to talk about wheat, and a
    story with no ``evil_progress`` still paid the regex.

    A story declares its own in ``<paths.rules>/spoilers.yaml``::

        spoilers:
          - term: "Clockwork Dark"
            instead: "something wrong in the wheat"

    A story that declares none gets an empty table, which means no redaction --
    the correct nothing, and the same shape as clocks, threads and endings. The
    awareness GATE still runs; there is simply no vocabulary for it to mask.
    """
    rel = str(get_config().get("paths.rules", "") or "").strip()
    if not rel:
        return ()
    root = Path(rel)
    if not root.is_absolute():
        root = _ROOT / root
    path = root / SPOILER_FILE
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return ()
    return _compile_terms(str(root), mtime)


class LoreInjectInterceptor:
    """PRE: inject RAG lore chunks into system context."""

    priority = 6
    name = "LoreInjectInterceptor"

    def __init__(self, manager: Optional[LoreManager] = None) -> None:
        self._manager = manager

    @property
    def manager(self) -> LoreManager:
        return self._manager or get_lore_manager()

    def run_pre(
        self,
        state: GameState,
        system_prompt: str,
        *,
        player_action: str = "",
        limit: int = 3,
    ) -> str:
        """
        Append lore context block when DB has chunks.

        No-op if lore store is empty.
        """
        if self.manager.count() == 0:
            return system_prompt

        query = f"{state.location_id} {player_action} {state.archetype}"
        chunks = self.manager.search(query, limit=limit)
        if not chunks:
            return system_prompt

        lines = [f"- [{c.title}] {c.text}" for c in chunks]
        block = "LORE CONTEXT (canonical — do not contradict):\n" + "\n".join(lines)
        logger.debug(
            "[lore] Injected chunks (operation=run_pre, count=%s)", len(chunks)
        )
        return f"{system_prompt}\n\n{block}"


SPOILER_OPEN = "<<<SPOILER"
SPOILER_CLOSE = "SPOILER>>>"
_SPOILER_REGION = re.compile(
    re.escape(SPOILER_OPEN) + r"(.*?)" + re.escape(SPOILER_CLOSE),
    re.DOTALL,
)


def mark_spoiler(text: str) -> str:
    """Wrap text in gate markers so the awareness gate may redact it."""
    return f"{SPOILER_OPEN}{text}{SPOILER_CLOSE}"


class AwarenessGateInterceptor:
    """PRE: strip spoiler phrases below awareness threshold."""

    priority = 40
    name = "AwarenessGateInterceptor"

    def _below_threshold(self, awareness: float) -> bool:
        threshold = float(get_config().get("awareness.spoiler_gate_threshold", 15))
        return awareness < threshold

    def gate(self, text: str, awareness: float) -> str:
        """
        Replace spoiler terms in free text.

        Used for model OUTPUT, where any occurrence is a genuine leak.
        """
        if not self._below_threshold(awareness):
            return text
        result = text
        for pattern, replacement in spoiler_terms():
            result = pattern.sub(replacement, result)
        return result

    def gate_prompt(self, system_prompt: str, awareness: float) -> str:
        """
        Redact only explicitly marked regions of a system prompt.

        This used to run over the WHOLE prompt, so at awareness 0 -- every new
        game -- the Storyteller was told:

            You are the STORYTELLER (Game Master) of "something wrong in the wheat".

        The game's own title was being substituted out of its own instructions.
        Only text wrapped in ``mark_spoiler`` is eligible now; everything else
        is instruction, not narration, and must survive intact.
        """
        below = self._below_threshold(awareness)

        def _replace(match: re.Match[str]) -> str:
            inner = match.group(1)
            return self.gate(inner, awareness) if below else inner

        return _SPOILER_REGION.sub(_replace, system_prompt)

    def run_pre(self, state: GameState, system_prompt: str, **_: Any) -> str:
        return self.gate_prompt(system_prompt, state.awareness)

    def run_post(self, state: GameState, narration: str, **_: Any) -> str:
        """POST: redact spoilers the model produced on its own."""
        return self.gate(narration, state.awareness)


def run_pre_interceptors(
    state: GameState,
    system_prompt: str,
    *,
    player_action: str = "",
    interceptors: Optional[list[Any]] = None,
) -> str:
    """
    Run configured PRE interceptors in priority order.

    Args:
        state: Current game state.
        system_prompt: Storyteller system prompt.
        player_action: Current player action for lore query.
        interceptors: Optional override list (tests).

    Returns:
        Modified system prompt.

    Note:
        Dispatch lives in ``engine/agents/governance.py`` -- this function is
        the historical entry point and delegates. It used to carry its own copy
        of "build a chain from config, sort by priority, thread a prompt
        through", which the media package then grew a second, subtly different
        copy of. Neither copy could host a rule check, which is why
        ``SceneRulesEngine`` sat uncalled. One chain now, with one ordering and
        one failure policy.
    """
    # Imported here, not at module scope: governance imports this module to
    # register these two interceptors by name, so a top-level import would be
    # circular.
    from engine.agents.governance import get_governance

    return get_governance().run_pre(
        state,
        system_prompt,
        player_action=player_action,
        interceptors=interceptors,
    )
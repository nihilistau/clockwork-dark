"""
Context Budget
==============

Keeping the prompt inside the model's window.

Deliberately does NOT use tiktoken: it is the wrong tokenizer for a llama or
qwen GGUF, and it is a heavyweight dependency in a local-first project. Prose
in English runs close to 3.6 characters per token; that plus a safety margin is
accurate enough to decide what to evict, and eviction is the only decision this
module makes. The budget is asserted in tests, not defended at runtime.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

CHARS_PER_TOKEN = 3.6
SAFETY_MARGIN = 0.15

# Blocks 0 and 1 are never evicted: without the persona the model is not the
# Storyteller, and without world state it is narrating a void.
EVICTION_ORDER = ("turns", "lore", "threads", "summary")


def estimate_tokens(text: str) -> int:
    """Approximate token count for English prose."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_messages(messages: Iterable[dict[str, str]]) -> int:
    """Approximate token count for a chat message array, including overhead."""
    total = 0
    for message in messages:
        # ~4 tokens of role/delimiter framing per message.
        total += estimate_tokens(str(message.get("content", ""))) + 4
    return total


@dataclass
class Budget:
    """Token allowance for one prompt."""

    context_tokens: int = 8192
    reserve_output: int = 900

    @property
    def available(self) -> int:
        usable = self.context_tokens - self.reserve_output
        return max(512, int(usable * (1.0 - SAFETY_MARGIN)))

    def fits(self, messages: Iterable[dict[str, str]]) -> bool:
        return estimate_messages(messages) <= self.available

    @classmethod
    def for_profile(cls, profile: str = "big") -> "Budget":
        """
        Derive the budget from the model that will actually serve the request.

        WHY THIS IS NOT A CONSTANT ANY MORE
        -----------------------------------
        The shipped numbers were ``context_tokens: 8192`` and
        ``reserve_output: 900``, giving ``(8192 - 900) * 0.85 = 6198`` tokens of
        prompt. Two things were wrong with that.

        First, ``reserve_output`` has to cover the whole generation, and on a
        reasoning model that is content PLUS thinking -- ``ModelProfile.wire_cap()``,
        not ``max_tokens`` alone. Reserving less than that would put the
        difference into a window the prompt had already claimed, and LM Studio
        truncates the prompt silently from the front -- taking the system
        persona with it.

        Second, 8192 was a guess about a model nobody had identified. The bound
        model reports what it was actually loaded with (nemotron here: loaded at
        20,224 despite advertising 1,048,576), so the real number is available
        and the guess is unnecessary.
        """
        from engine.config import get_config
        from engine.lmstudio.profiles import resolve_profile

        cfg = get_config()
        try:
            mp = resolve_profile(profile)
            context = int(mp.context_tokens)
            # Reserve the full generation ceiling -- content and reasoning
            # both -- plus a floor so a profile with a small cap still leaves
            # room for a reply.
            reserve = max(int(mp.wire_cap()), int(cfg.get("lmstudio.reserve_output", 900)))
        except Exception:  # noqa: BLE001 -- offline dev falls back to config
            context = int(cfg.get("lmstudio.context_tokens", 8192))
            reserve = int(cfg.get("lmstudio.reserve_output", 900))

        # Never let the reserve eat the whole window: a huge max_tokens against
        # a small context must still leave a usable prompt.
        reserve = min(reserve, max(512, context // 2))
        return cls(context_tokens=context, reserve_output=reserve)


@dataclass
class Block:
    """One labelled section of the prompt."""

    name: str
    role: str
    content: str
    evictable: bool = True

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.content)


@dataclass
class BlockSet:
    """Prompt blocks with budget-aware assembly."""

    blocks: list[Block] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    def add(self, name: str, role: str, content: str, *, evictable: bool = True) -> None:
        if content and content.strip():
            self.blocks.append(Block(name, role, content, evictable))

    def fit(self, budget: Budget, *, reserved: int = 0) -> list[dict[str, str]]:
        """
        Drop blocks in EVICTION_ORDER until the prompt fits.

        Turn history goes first because the running summary already covers the
        same ground in compressed form; the summary goes last because losing it
        costs the model every memory it has.

        Args:
            budget: The window this prompt has to fit inside.
            reserved: Tokens already spoken for by messages the CALLER will
                append after this returns -- few-shot examples, the turn
                buffer, receipts, the agreed block, the player's own line.
                Without it this method fitted the blocks against the whole
                window and the caller then appended an unbounded amount on top,
                so the prompt that was measured and the prompt that went on the
                wire were different objects. LM Studio truncates from the
                front, which takes the persona first.
        """
        allowance = max(0, budget.available - max(0, reserved))
        working = list(self.blocks)
        self.dropped = []

        for name in EVICTION_ORDER:
            if estimate_messages(self._render(working)) <= allowance:
                break
            remaining = [b for b in working if not (b.name == name and b.evictable)]
            if len(remaining) != len(working):
                self.dropped.append(name)
                working = remaining

        # Last resort: trim the oldest turn entries one at a time.
        while (
            estimate_messages(self._render(working)) > allowance
            and any(b.evictable for b in working)
        ):
            for index, block in enumerate(working):
                if block.evictable:
                    self.dropped.append(block.name)
                    working.pop(index)
                    break
            else:
                break

        return self._render(working)

    @staticmethod
    def _render(blocks: list[Block]) -> list[dict[str, str]]:
        return [{"role": b.role, "content": b.content} for b in blocks]

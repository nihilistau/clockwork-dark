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

    def fit(self, budget: Budget) -> list[dict[str, str]]:
        """
        Drop blocks in EVICTION_ORDER until the prompt fits.

        Turn history goes first because the running summary already covers the
        same ground in compressed form; the summary goes last because losing it
        costs the model every memory it has.
        """
        working = list(self.blocks)
        self.dropped = []

        for name in EVICTION_ORDER:
            if estimate_messages(self._render(working)) <= budget.available:
                break
            remaining = [b for b in working if not (b.name == name and b.evictable)]
            if len(remaining) != len(working):
                self.dropped.append(name)
                working = remaining

        # Last resort: trim the oldest turn entries one at a time.
        while (
            estimate_messages(self._render(working)) > budget.available
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

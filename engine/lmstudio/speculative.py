"""
Speculative Decoding
====================

Draft model skeleton pass → refine model full stream (Anubis pattern).

Falls back to single-model stream when speculative disabled or draft fails.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from engine.config import get_config
from engine.lmstudio.client import LMSClient
from engine.lmstudio.events import LMSResponse

logger = logging.getLogger(__name__)


def speculative_enabled() -> bool:
    """Return True if speculative decoding is configured."""
    return bool(get_config().get("lmstudio.speculative.enabled", True))


def speculative_stream(
    client: LMSClient,
    messages: list[dict[str, Any]],
    *,
    refine_profile: str = "big",
    draft_profile: str = "draft",
    on_delta: Optional[Callable[[str], None]] = None,
) -> LMSResponse:
    """
    Two-pass inference: fast draft outline, then refine stream to UI.

    The draft skeleton is injected as a system hint for the refine pass.
    If draft fails, falls back to refine-only stream.

    Args:
        client: LMS client instance.
        messages: Conversation messages.
        refine_profile: Profile for final narration.
        draft_profile: Profile for fast skeleton.
        on_delta: Optional per-token callback (refine pass only).

    Returns:
        LMSResponse from refine pass.
    """
    if not speculative_enabled():
        gen = client.infer_stream(messages, profile=refine_profile)
        parts: list[str] = []
        for chunk in gen:
            if on_delta:
                on_delta(chunk)
            parts.append(chunk)
        return LMSResponse(content="".join(parts))

    draft_messages = list(messages) + [
        {
            "role": "user",
            "content": (
                "In 1-2 sentences, outline the narrative skeleton only. "
                "No tags, no JSON."
            ),
        }
    ]
    skeleton = ""
    try:
        from engine.lmstudio.profiles import resolve_profile

        dmp = resolve_profile(draft_profile)
        draft_resp = client.chat(
            draft_messages,
            model=dmp.model,
            temperature=dmp.temperature,
            max_tokens=dmp.max_tokens,
        )
    except Exception as exc:
        logger.warning(
            "[speculative] Draft failed (operation=speculative_draft): %s", exc
        )
        draft_resp = LMSResponse(content="")

    skeleton = (draft_resp.content or "").strip()
    refine_messages = list(messages)
    if skeleton:
        refine_messages.insert(
            1,
            {
                "role": "system",
                "content": f"Narrative skeleton (expand with atmosphere):\n{skeleton}",
            },
        )

    gen = client.infer_stream(refine_messages, profile=refine_profile)
    parts = []
    for chunk in gen:
        if on_delta:
            on_delta(chunk)
        parts.append(chunk)
    return LMSResponse(content="".join(parts))
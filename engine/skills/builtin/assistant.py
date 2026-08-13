"""
Assistant Skills
================

Optional narrative tools for the companion agent (the ``assistant`` role in
the skill registry's allowlist; historically ``clockwork_assistant``, an id
that now lives in the flagship's agents.yaml rather than in engine code).

THE GAP THIS MODULE CLOSES (P9): the Assistant's entire vocabulary used to be
six hint strings and three lore snippets written as Python literals right here.
Six lines, for an agent that may speak on any turn of any session. The content
now lives in ``data/assistant/hints.yaml`` where a writer can reach it, and
this module does what a skills module should: gate it and hand it over.

Every public name is unchanged -- ``ASSISTANT_FORMS``, ``HINTS_BY_TIER``,
``LORE_SNIPPETS``, ``compute_hint_tier``, ``grant_hint``, ``reveal_lore``,
``change_form``. ``HINTS_BY_TIER`` and ``LORE_SNIPPETS`` are now populated from
the YAML at import rather than typed out, so anything that read them still can.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.engine import get_active_engine
from engine.skills.registry import AGENT_ASSISTANT, TRIGGER_OPTIONAL, skill

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[3]

ASSISTANT_FORMS: tuple[str, ...] = (
    "cat",
    "wanderer",
    "child",
    "tinker",
    "reflection",
)

# Spoken only if the YAML is missing entirely. Kept deliberately in voice --
# a content-loading failure must not make the Assistant sound like a stub.
_FALLBACK_HINT = "Nothing worth saying. That is not the same as nothing worth noticing."


def _hints_path() -> Optional[Path]:
    """
    Path to the hint corpus, declared by the story as ``paths.assistant_hints``.

    None when the story ships none, in which case the Assistant speaks from
    ``_FALLBACK_HINT`` and whatever the turn itself gives it. Another story's
    hints would have it noticing things this world does not contain.
    """
    rel = str(get_config().get("paths.assistant_hints", "") or "").strip()
    return (_ROOT / rel) if rel else None


def _load_hint_data() -> dict[str, Any]:
    """
    Read data/assistant/hints.yaml.

    Returns:
        The parsed document, or an empty dict if it is missing or malformed.
        A broken hint file must degrade the Assistant's vocabulary, never
        abort a turn.
    """
    path = _hints_path()
    if path is None:
        logger.debug("[assistant] Story declares no hints (operation=_load_hint_data)")
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error(
            "[assistant] Unreadable hint corpus "
            "(operation=_load_hint_data, path=%s): %s",
            path,
            exc,
        )
        return {}
    return data if isinstance(data, dict) else {}


def _build_hints_by_tier(data: dict[str, Any]) -> dict[int, list[str]]:
    """
    Group hint texts by tier.

    Tier 1 absorbs tier 0. ``compute_hint_tier`` floors at 1, so a tier-0 line
    would otherwise be data nothing can ever reach -- and the ambient register
    is exactly right for a player who has not yet earned anything else.
    Tiers 2 and 3 stay pure, or a trusted player would keep drawing weather
    out of the much larger tier-0 pool.
    """
    by_tier: dict[int, list[str]] = {0: [], 1: [], 2: [], 3: []}
    for row in data.get("hints") or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            tier = int(row.get("tier", 1))
        except (TypeError, ValueError):
            tier = 1
        by_tier.setdefault(max(0, min(3, tier)), []).append(text)

    merged: dict[int, list[str]] = {
        1: by_tier[0] + by_tier[1],
        2: by_tier[2],
        3: by_tier[3],
    }
    for tier, pool in merged.items():
        if pool:
            continue
        # A story that ships NO hint corpus has no pools by definition, and
        # saying so three times at WARNING on every boot is noise about a
        # decision the story made. A corpus that exists and leaves a tier empty
        # is still worth flagging: that one is an authoring gap.
        if data.get("hints"):
            logger.warning(
                "[assistant] Empty hint pool (operation=_build_hints_by_tier, tier=%s)",
                tier,
            )
        else:
            logger.debug(
                "[assistant] Story declares no hints "
                "(operation=_build_hints_by_tier, tier=%s)",
                tier,
            )
    return merged


def _build_lore_snippets(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalise the ``lore_snippets`` block into the historical shape."""
    out: dict[str, dict[str, Any]] = {}
    for topic, row in (data.get("lore_snippets") or {}).items():
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            min_tier = int(row.get("min_tier", 1))
        except (TypeError, ValueError):
            min_tier = 1
        out[str(topic).lower()] = {"min_tier": min_tier, "text": text}
    return out


_HINT_DATA = _load_hint_data()

HINTS_BY_TIER: dict[int, list[str]] = _build_hints_by_tier(_HINT_DATA)
LORE_SNIPPETS: dict[str, dict[str, Any]] = _build_lore_snippets(_HINT_DATA)
_FALLBACK_HINT = str(_HINT_DATA.get("fallback") or _FALLBACK_HINT)

logger.info(
    "[assistant] Loaded hint corpus (operation=import, hints=%d, snippets=%d)",
    sum(len(pool) for pool in HINTS_BY_TIER.values()),
    len(LORE_SNIPPETS),
)


def reload_hints() -> None:
    """Re-read the hint corpus in place, keeping the module-level mappings."""
    global _FALLBACK_HINT
    data = _load_hint_data()
    HINTS_BY_TIER.clear()
    HINTS_BY_TIER.update(_build_hints_by_tier(data))
    LORE_SNIPPETS.clear()
    LORE_SNIPPETS.update(_build_lore_snippets(data))
    _FALLBACK_HINT = str(data.get("fallback") or _FALLBACK_HINT)


def compute_hint_tier(trust_level: float, plot_involvement: float) -> int:
    """
    Derive hint tier from trust and plot involvement (no evil_progress).

    Args:
        trust_level: Assistant trust 0–100.
        plot_involvement: Player plot involvement 0–100.

    Returns:
        Hint tier 1–3.
    """
    tier = 1
    if trust_level >= 30.0:
        tier = 2
    if trust_level >= 60.0 or plot_involvement >= 20.0:
        tier = 3
    return max(1, min(3, tier))


def _reflection_min_awareness() -> float:
    return float(
        get_config().get(
            "assistant.reflection_awareness_min",
            get_config().get("awareness.reflection_form_min", 40),
        )
    )


@skill(
    pack="core",
    description="Assistant: return a lore hint appropriate to trust tier.",
    category="NARRATIVE",
    trigger=TRIGGER_OPTIONAL,
    agents=[AGENT_ASSISTANT],
)
def grant_hint(tier: int = 0) -> str:
    """Return hint text capped by computed hint tier."""
    engine = get_active_engine()
    state = engine.state
    max_tier = compute_hint_tier(
        state.assistant_mind.trust_level,
        state.plot_involvement,
    )
    effective = tier if tier > 0 else max_tier
    effective = max(1, min(effective, max_tier))
    # Walk down rather than trusting one pool: an empty band in the corpus
    # must cost the player specificity, not silence the Assistant.
    pool: list[str] = []
    for candidate in range(effective, 0, -1):
        pool = HINTS_BY_TIER.get(candidate) or []
        if pool:
            break
    hint = pool[state.turn_number % len(pool)] if pool else _FALLBACK_HINT
    return json.dumps(
        {
            "tier": effective,
            "max_tier": max_tier,
            "hint": hint,
        }
    )


@skill(
    pack="core",
    description="Assistant: reveal a lore snippet by topic id.",
    category="NARRATIVE",
    trigger=TRIGGER_OPTIONAL,
    agents=[AGENT_ASSISTANT],
)
def reveal_lore(topic: str = "") -> str:
    """Return lore snippet if hint tier permits."""
    engine = get_active_engine()
    state = engine.state
    max_tier = compute_hint_tier(
        state.assistant_mind.trust_level,
        state.plot_involvement,
    )
    entry = LORE_SNIPPETS.get(topic.lower())
    if entry is None:
        return json.dumps(
            {
                "success": False,
                "topic": topic,
                "message": f"Unknown lore topic: {topic}",
            }
        )
    min_tier = int(entry.get("min_tier", 1))
    if max_tier < min_tier:
        return json.dumps(
            {
                "success": False,
                "topic": topic,
                "required_tier": min_tier,
                "max_tier": max_tier,
                "message": "Trust is not deep enough for that truth.",
            }
        )
    return json.dumps(
        {
            "success": True,
            "topic": topic,
            "tier": max_tier,
            "lore": entry["text"],
        }
    )


@skill(
    pack="core",
    description="Assistant: shift visible form (cat, wanderer, child, tinker, reflection).",
    category="NARRATIVE",
    trigger=TRIGGER_OPTIONAL,
    agents=[AGENT_ASSISTANT],
)
def change_form(form: str) -> str:
    """Change assistant_mind.current_form with awareness gate on reflection."""
    engine = get_active_engine()
    state = engine.state
    target = form.lower().strip()
    if target not in ASSISTANT_FORMS:
        return json.dumps(
            {
                "success": False,
                "form": target,
                "message": f"Unknown form: {target}",
                "valid_forms": list(ASSISTANT_FORMS),
            }
        )
    if target == "reflection" and state.awareness < _reflection_min_awareness():
        return json.dumps(
            {
                "success": False,
                "form": target,
                "required_awareness": _reflection_min_awareness(),
                "awareness": state.awareness,
                "message": "The reflection will not hold yet.",
            }
        )
    previous = state.assistant_mind.current_form
    state.assistant_mind.current_form = target
    return json.dumps(
        {
            "success": True,
            "previous_form": previous,
            "form": target,
        }
    )
"""
Art Prompt Renderer
===================

One source of art direction, two prompt dialects.

Grok Imagine wants natural prose, 2-5 sentences, positive description only,
and explicitly no negative prompts. ComfyUI SDXL wants comma-separated keyword
tags with a separate negative prompt and LoRA hints. Maintaining both by hand
guarantees they drift apart; both are rendered here from the structured
subjects in data/art/subjects.yaml.

v0.3.0 adds ``kind="item"``. The chain has been able to SERVE item art since
P6 -- engine/media/providers/shipped.py resolves ``kind == "item"`` against the
manifest -- but no prompt could ever be rendered for one, because ``_fields``
only knew about locations and portraits and fell through to the "degrade to the
id" branch. Asking either backend for a picture of ``bent_nail`` produced a
prompt that read "bent nail" and nothing else, which is why the 52 items with
no packed plate had no realistic route to one.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config, project_root

logger = logging.getLogger(__name__)

# Corruption motifs only appear once the world has visibly turned.
CORRUPT_PHASES = ("spreading", "consuming")


@functools.lru_cache(maxsize=1)
def load_subjects() -> dict[str, Any]:
    """Load the art spec. Cached; the file is small and static."""
    path = get_config().resolve_path("paths.art_subjects")
    if path is None:
        # No art spec is a story shipping no generated art, not a fault. DEBUG,
        # or it warns on every boot of a story that legitimately has none.
        logger.debug("[art] Story declares no art subjects (operation=load_subjects)")
        return {}
    if not path.exists():
        logger.warning("[art] Subjects file missing (operation=load_subjects, path=%s)", path)
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[art] Unreadable subjects (operation=load_subjects): %s", exc)
        return {}


def reset_subjects_cache() -> None:
    """Tests only."""
    load_subjects.cache_clear()


def format_for(kind: str) -> dict[str, Any]:
    """Aspect ratio and pixel size for a workflow kind."""
    formats = load_subjects().get("formats", {})
    return formats.get(kind, formats.get("location", {"aspect": "16:9", "width": 1344, "height": 768}))


def style_for(variant: str, key: str) -> str:
    """
    One clause of the shared art direction, or a named variant's replacement.

    A story's ``style:`` block is appended to every prompt it renders, which is
    the point -- it is what makes a pack look like one pack. But a story with a
    strong house style has subjects that are deliberately OUTSIDE it, and for
    those the block argues against the thing being drawn. The Wicked Garden's
    style says "lush organic forms everywhere -- vines, petals, pollen" and
    "botanical art nouveau"; two of its fourteen locations are a drab mortal
    flat and a formless void, and reading as the opposite of the Garden is the
    entire job of both.

    So a subject may name a variant (``style: mortal``) and the story declares
    it under ``style.variants.mortal``. Only the keys the variant declares are
    replaced, so a variant that changes the prose keeps the shared negative.

    An unknown variant name falls back to the shared block and logs -- a typo
    should cost a prompt its exception, not produce no art direction at all.
    """
    block = load_subjects().get("style", {}) or {}
    if variant:
        override = (block.get("variants") or {}).get(variant)
        if not isinstance(override, dict):
            logger.warning(
                "[art] Unknown style variant (operation=style_for, variant=%s)", variant
            )
        elif key in override:
            return str(override.get(key) or "").strip()
    return str(block.get(key) or "").strip()


def _location_fields(location_id: str, time_of_day: str) -> Optional[dict[str, str]]:
    entry = load_subjects().get("locations", {}).get(location_id)
    if not entry:
        return None
    times = entry.get("times", {})
    # Fall back to dawn rather than failing: coverage is deliberately partial
    # for the less-visited hours.
    slot = times.get(time_of_day) or times.get("dawn") or {}
    return {
        "subject": entry.get("subject", location_id.replace("_", " ")),
        "details": entry.get("details", ""),
        "setting": slot.get("setting", ""),
        "light": slot.get("light", ""),
        "style": entry.get("style", ""),
    }


def _portrait_fields(npc_id: str) -> Optional[dict[str, str]]:
    entry = load_subjects().get("portraits", {}).get(npc_id)
    if not entry:
        return None
    return {
        "subject": entry.get("subject", npc_id.replace("_", " ")),
        "details": entry.get("details", ""),
        "setting": entry.get("setting", ""),
        "light": entry.get("mood", ""),
        "style": entry.get("style", ""),
    }


def _item_fields(item_id: str) -> Optional[dict[str, str]]:
    """
    Prompt fields for one registry item.

    Framing and lighting come from ``items.defaults`` unless the entry
    overrides them, because eighty-one repetitions of "laid flat on a dark aged
    ground" is eighty-one chances for one of them to say something else. An
    item that needs its own light -- anything with a flame in it -- says so.
    """
    block = load_subjects().get("items", {}) or {}
    entry = block.get(item_id)
    if not entry:
        return None
    defaults = block.get("defaults", {}) or {}
    return {
        "subject": entry.get("subject", item_id.replace("_", " ")),
        "details": entry.get("details", ""),
        "setting": entry.get("setting", defaults.get("setting", "")),
        "light": entry.get("light", defaults.get("light", "")),
        "style": entry.get("style", defaults.get("style", "")),
    }


def _fields(kind: str, subject_id: str, time_of_day: str) -> dict[str, str]:
    if kind == "item":
        fields = _item_fields(subject_id)
    elif kind == "portrait":
        fields = _portrait_fields(subject_id)
    else:
        fields = _location_fields(subject_id, time_of_day)
    if fields is None:
        # Unknown subject: degrade to the id itself rather than producing
        # nothing. The old ComfyUI client did exactly this and it is fine.
        logger.debug("[art] No spec for subject (operation=_fields, id=%s)", subject_id)
        fields = {
            "subject": subject_id.replace("_", " "),
            "details": "",
            "setting": time_of_day,
            "light": "",
            "style": "",
        }
    return fields


def render_prose(
    subject_id: str,
    *,
    kind: str = "location",
    time_of_day: str = "dawn",
    evil_phase: str = "dormant",
) -> str:
    """
    Natural-prose prompt for Grok Imagine.

    Subject first, then setting, light, style -- the order the imagine skill
    asks for. Positive description only; no negative prompt.
    """
    spec = load_subjects()
    fields = _fields(kind, subject_id, time_of_day)

    sentences = [f"{fields['subject']}."]
    if fields["details"]:
        sentences.append(f"Visible detail: {fields['details']}.")
    if fields["setting"] or fields["light"]:
        joined = ", ".join(p for p in (fields["setting"], fields["light"]) if p)
        sentences.append(f"{joined.capitalize()}.")

    style = style_for(fields.get("style", ""), "prose")
    if style:
        sentences.append(style)

    if evil_phase in CORRUPT_PHASES:
        corrupt = (spec.get("corruption", {}).get("prose") or "").strip()
        if corrupt:
            sentences.append(corrupt)

    return " ".join(s.strip() for s in sentences if s.strip())


def render_tags(
    subject_id: str,
    *,
    kind: str = "location",
    time_of_day: str = "dawn",
    evil_phase: str = "dormant",
) -> tuple[str, str]:
    """
    Keyword-tag prompt and negative prompt for ComfyUI SDXL.

    Returns:
        (positive, negative)
    """
    spec = load_subjects()
    fields = _fields(kind, subject_id, time_of_day)

    parts = [fields["subject"], fields["details"], fields["setting"], fields["light"]]
    style = style_for(fields.get("style", ""), "tags")
    if style:
        parts.append(style)
    if evil_phase in CORRUPT_PHASES:
        corrupt = (spec.get("corruption", {}).get("tags") or "").strip()
        if corrupt:
            parts.append(corrupt)

    positive = ", ".join(p.strip() for p in parts if p and p.strip())
    negative = style_for(fields.get("style", ""), "negative")
    return positive, negative


def lora_hints() -> list[dict[str, Any]]:
    """LoRA suggestions for the ComfyUI workflow."""
    return list(load_subjects().get("style", {}).get("loras", []))

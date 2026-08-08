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
    path = get_config().resolve_path("paths.art_subjects", "data/art/subjects.yaml")
    if path is None or not path.exists():
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

    style = (spec.get("style", {}).get("prose") or "").strip()
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
    style = (spec.get("style", {}).get("tags") or "").strip()
    if style:
        parts.append(style)
    if evil_phase in CORRUPT_PHASES:
        corrupt = (spec.get("corruption", {}).get("tags") or "").strip()
        if corrupt:
            parts.append(corrupt)

    positive = ", ".join(p.strip() for p in parts if p and p.strip())
    negative = (spec.get("style", {}).get("negative") or "").strip()
    return positive, negative


def lora_hints() -> list[dict[str, Any]]:
    """LoRA suggestions for the ComfyUI workflow."""
    return list(load_subjects().get("style", {}).get("loras", []))

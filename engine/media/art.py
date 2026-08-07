"""
Art Prompt Renderer
===================

One source of art direction, two prompt dialects.

Grok Imagine wants natural prose, 2-5 sentences, positive description only,
and explicitly no negative prompts. ComfyUI SDXL wants comma-separated keyword
tags with a separate negative prompt and LoRA hints. Maintaining both by hand
guarantees they drift apart; both are rendered here from the structured
subjects in data/art/subjects.yaml.

Version: v0.2.0 [2026-08-07]
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


def _fields(kind: str, subject_id: str, time_of_day: str) -> dict[str, str]:
    fields = (
        _portrait_fields(subject_id)
        if kind == "portrait"
        else _location_fields(subject_id, time_of_day)
    )
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

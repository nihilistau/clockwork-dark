"""
No gate reads days (spec §19.3, I9, R15, m7). Walks growth.yaml, relationships.yaml and media.yaml and fails on
any key naming days, hours or a per-day cap -- but for the named exemptions, each with its reason.
"""

from __future__ import annotations

import re

from tests.social_fixtures import receipts_active  # noqa: F401

#: (file, dotted path with list indexes written `[*]`) -> its reason. Nothing else may count days
#: (pre-flight F5: every row below was found by walking the shipped data at a2ed481).
EXEMPT: dict[tuple[str, str], str] = {
    ("growth", "willing.move_in.days_since_exclusive"): "R15: move_in's 14 days since exclusive",
    ("relationships", "wedding_after_days"): "R15: the wedding follows the engagement by days",
    ("relationships", "fade_days"): "m7: an absence measure, days of no contact",
    ("relationships", "cold.days"): "m7: an absence measure, days of a cold spell",
    ("relationships", "cold.recover_days"): "m7: an absence measure, days of warming back",
    ("relationships", "bands[*].contact_days"): "m7: an absence measure, like fade_days (spec clarification, F5)",
    ("relationships", "interest.left_on_read.grace_hours"): "a decay or grace window, not a gate",
    ("relationships", "mood.decay_hours"): "a decay or grace window, not a gate",
}
DAYISH = re.compile(r"(^|_)(days?|per_day|hours?|stage_days)($|_)")


def _walk(node, path=""):
    """Yield (path, key) with every list index written `[*]`, so one EXEMPT row covers a list."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            yield here, str(key)
            yield from _walk(value, here)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, f"{path}[*]")


def test_no_gate_reads_days(receipts_active) -> None:
    from engine import social

    offenders = []
    for name in ("growth", "relationships", "media"):
        for path, key in _walk(social.data(name)):
            if DAYISH.search(key) and (name, path) not in EXEMPT:
                offenders.append(f"{name}.yaml: {path}")
    assert not offenders, offenders


def test_every_exemption_still_exists(receipts_active) -> None:
    """An exemption whose key was removed is stale and is deleted from EXEMPT (no silent drift)."""
    from engine import social

    present = {(name, path) for name in ("growth", "relationships", "media") for path, _ in _walk(social.data(name))}
    assert set(EXEMPT) <= present, sorted(set(EXEMPT) - present)

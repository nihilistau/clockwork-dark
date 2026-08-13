"""
Content Integrity Validator — CLI
=================================

Cross-check every id reference in a STORY's data tree against the thing it
names. Any story, chosen by slug; the active/default story when none is named.

THE GAP THIS SCRIPT CLOSES: at several hundred ids spread across locations,
items, recipes, quests, encounters, decks, clocks and endings, the dominant
failure is not a bug in a function, it is ``wild_mushroom`` versus
``wild_mushrooms``: a reference that resolves to nothing, raises nothing, and
produces a shop entry that cannot be bought or a gate that can never open.
Unit tests do not catch that. Only a referential-integrity pass does.

THE LOGIC LIVES IN ``engine/games/validation.py`` — one home, three faces:
this CLI, ``scripts/doctor.py``'s Games section, and the per-game test in
``tests/test_story_content_integrity.py``. v0.1.0 of this script WAS the
logic, hardcoded to the flagship's paths and vocabularies; generalising it
meant moving it behind the manifest, where every story's paths already are.

Every finding names the file and the offending id, because the only useful
form of this failure is one a content author can act on without reading
Python.

Version: v0.2.0 [2026-08-13]

Usage:
    python scripts/validate_content.py                        # active story
    python scripts/validate_content.py --game wicked-garden
    python scripts/validate_content.py --game all             # every story
    python scripts/validate_content.py --warnings             # show advisories
    python scripts/validate_content.py --strict               # advisories fail
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.games import registry  # noqa: E402
from engine.games.validation import (  # noqa: E402
    Issue,
    errors_only,
    validate_story,
    warnings_only,
)

logger = logging.getLogger(__name__)


def _report(slug: str, issues: list[Issue], *, show_warnings: bool, strict: bool) -> int:
    """Print one story's findings. Returns the number of failing findings."""
    errors = errors_only(issues)
    warnings = warnings_only(issues)

    for issue in errors:
        print(issue)
    if show_warnings or strict:
        for issue in warnings:
            print(issue)

    failing = len(errors) + (len(warnings) if strict else 0)
    print(
        f"[validate_content] {slug}: {len(errors)} error(s), "
        f"{len(warnings)} advisory(ies)"
        + (" [strict: advisories fail]" if strict and warnings else "")
    )
    return failing


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Exit 0 when nothing fails."""
    parser = argparse.ArgumentParser(
        description="Validate cross-file content integrity for a story"
    )
    parser.add_argument(
        "--game",
        default=None,
        help="Story slug to validate (default: the active/resolved story). "
        "'all' validates every discovered story.",
    )
    parser.add_argument(
        "--warnings",
        action="store_true",
        help="Print advisory findings as well as errors",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Advisories become failures",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    if args.game == "all":
        slugs = sorted(registry.discover())
        if not slugs:
            print("[validate_content] no games found under games/")
            return 1
    else:
        slugs = [args.game or registry.resolve_slug()]

    failing = 0
    for slug in slugs:
        issues = validate_story(slug)
        failing += _report(slug, issues, show_warnings=args.warnings, strict=args.strict)

    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
The single-writer rule, held by a scanner.

CLAUDE.md rule 3: ``effects.apply_effect`` is the only writer of game state.
The rule was true of the big writers and quietly false at the edges -- travel
decremented stamina inline, survival clamped hunger and stamina by assignment,
four modules appended daily markers straight onto ``active_effects``, and five
modules set flags by subscript. Each was found by reading, which does not
scale; this test finds the next one by grep.

WHAT IS SCANNED. Every ``.py`` under ``engine/`` (and the flagship's scene
runner package under ``content/``), for the exact mutation shapes that were
eliminated. The patterns are deliberately narrow: they match the assignment
forms the leaks actually took, so a false positive means a new line LOOKS like
a leak, which is worth a human glance anyway.

WHAT IS WHITELISTED, AND WHY:

    engine/game/effects.py    the writer itself -- every pattern lives here on
                              purpose
    engine/game/procgen.py    initialization-time construction: it builds a
                              new character's starting state before any turn
                              exists (see the comment at its write sites)

A file earning a new exemption belongs in the table with a reason, not in a
loosened pattern.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCAN_DIRS = (_ROOT / "engine", _ROOT / "content")

#: pattern name -> regex matching a direct-write shape. `(?!=)` keeps `==`
#: comparisons out; the patterns target assignment and augmented assignment.
PATTERNS: dict[str, re.Pattern[str]] = {
    "stats.stamina assignment": re.compile(r"\.stats\.stamina\s*[-+*/]?=(?!=)"),
    "awareness assignment": re.compile(r"\.awareness\s*[-+*/]?=(?!=)"),
    "hunger assignment": re.compile(r"\.hunger\s*[-+*/]?=(?!=)"),
    "flags subscript assignment": re.compile(r"\.flags\[[^\]]+\]\s*=(?!=)"),
    "active_effects.append": re.compile(r"\.active_effects\.append\("),
    "inventory.append": re.compile(r"\.inventory\.append\("),
}

#: file (relative, forward slashes) -> pattern names it may contain.
WHITELIST: dict[str, set[str]] = {
    # The one writer. Every pattern is its job.
    "engine/game/effects.py": set(PATTERNS),
    # Initialization-time construction of a brand-new state; documented at the
    # write sites. Only the shapes character creation actually uses.
    "engine/game/procgen.py": {"inventory.append"},
}


def _matches(path: Path) -> list[tuple[str, int, str]]:
    """(pattern, line number, line) for every hit in one file."""
    hits: list[tuple[str, int, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(line):
                hits.append((name, number, stripped))
    return hits


def test_no_direct_state_writes_outside_the_one_writer() -> None:
    offences: list[str] = []
    for base in _SCAN_DIRS:
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(_ROOT).as_posix()
            allowed = WHITELIST.get(rel, set())
            for name, number, line in _matches(path):
                if name in allowed:
                    continue
                offences.append(f"{rel}:{number} [{name}] {line}")

    assert not offences, (
        "Direct game-state writes found outside effects.apply_effect. Route "
        "them through the one writer (add an effect kind if none fits), or "
        "add a whitelist entry WITH A REASON:\n  " + "\n  ".join(offences)
    )


def test_the_whitelist_names_only_real_files() -> None:
    """A renamed file must not leave a ghost exemption behind."""
    for rel in WHITELIST:
        assert (_ROOT / rel).is_file(), f"whitelisted file does not exist: {rel}"

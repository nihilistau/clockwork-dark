"""
No engine source names repo-root content again.

THE REGRESSION THIS BLOCKS. The flagship's content lived at the repo root's
``data/`` for the project's whole life, so ``data/...`` literals grew all over
the engine as "the" defaults -- and every one of them was one story's answer,
silently inherited by any story that omitted a key. The content now lives at
``games/clockwork-dark/data/`` like every other story's, engine loaders resolve
through ``paths.*`` on the active manifest, and the ONLY repo-root ``data/``
paths the engine may name are its own runtime outputs, which never moved:

    data/saves    the save store        (``paths.saves``, engine-owned output)
    data/media    the generated-media disk cache

A new quoted ``data/...`` literal anywhere else in ``engine/`` is this bug
being reintroduced. It belongs in a manifest, not in Python.

Comment lines are exempt (history may name the old layout); string literals
are not, docstrings included -- a docstring telling the next reader that the
flagship is the fallback is how the last round of these survived.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ENGINE = _ROOT / "engine"

# A quoted repo-root data path: "data/..." or 'data/...'.
_QUOTED_DATA_PATH = re.compile(r"""["'](data/[^"']*)["']""")
# A bare "data" path component being pathlib-joined: ... / "data" / ...
# (The trailing slash is what makes it a PATH; a bare ``.get("data")`` is a
# perfectly good dict key and none of this test's business.)
_DATA_COMPONENT_JOIN = re.compile(r"""["']data["']\s*/""")

# The engine's own runtime outputs -- the two trees that deliberately stayed at
# the repo root when the flagship's content moved. Everything else is a story's
# job to declare. Keep this list SMALL; a new entry needs the same argument
# these have (an engine-owned OUTPUT, not story content).
_ALLOWED: dict[str, frozenset[str]] = {
    "engine/persistence/saves.py": frozenset({"data/saves"}),
    "engine/api/media.py": frozenset({"data/media"}),
    "engine/media/tts.py": frozenset({"data/media/tts"}),
    "engine/media/providers/base.py": frozenset({"data/media"}),
}
_ALLOWED_PREFIXES = ("data/saves", "data/media", "data/cache", "data/telemetry")


def _engine_sources() -> list[Path]:
    files = sorted(_ENGINE.rglob("*.py"))
    assert files, "engine/ has no Python sources -- wrong repo root?"
    return files


def test_engine_names_no_repo_root_content() -> None:
    offenders: list[str] = []
    for path in _engine_sources():
        rel = path.relative_to(_ROOT).as_posix()
        allowed = _ALLOWED.get(rel, frozenset())
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("#"):
                continue  # comments may narrate the old layout
            for match in _QUOTED_DATA_PATH.finditer(line):
                literal = match.group(1)
                if literal in allowed:
                    continue
                offenders.append(f"{rel}:{lineno}: {literal!r}")
            if _DATA_COMPONENT_JOIN.search(line):
                offenders.append(f'{rel}:{lineno}: "data" used as a path component')

    assert not offenders, (
        "Engine code names repo-root data/ paths that are story content now "
        "(a story's files belong in its games/<slug>/game.yaml manifest, "
        "resolved through get_config().get('paths.*')):\n  "
        + "\n  ".join(offenders)
    )


def test_the_allowlist_is_only_runtime_outputs() -> None:
    """The allowlist itself cannot quietly grow a content path."""
    for rel, literals in _ALLOWED.items():
        assert (_ROOT / rel).is_file(), f"allowlist names a missing file: {rel}"
        for literal in literals:
            assert literal.startswith(_ALLOWED_PREFIXES), (
                f"{rel} allows {literal!r}, which is not an engine runtime "
                "output -- data/saves, data/media, data/cache, data/telemetry "
                "are the only trees that stayed at the repo root"
            )

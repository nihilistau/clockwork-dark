"""
Hosted mode's runtime files, and the agent workspace, stay out of git (v0.20.0
final review, finding 1): this repository is public, and a `git add -A` must
not be able to commit a cookie key, password hashes or a player's save.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

PATHS = (
    "data/hosting/users.json",
    "data/hosting/secret_key",
    "data/users/u_0123456789ab/saves/x/save.json",
    ".superpowers/sdd/x/progress.md",
    "data/saves/x",
)


@pytest.mark.parametrize("path", PATHS)
def test_runtime_secrets_and_the_workspace_are_gitignored(path: str) -> None:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("git or the repository's history is not available")
    done = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path],
        cwd=REPO,
        capture_output=True,
        timeout=60,
    )
    assert done.returncode == 0, f"{path} is not ignored"

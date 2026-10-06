"""
The two start scripts, held together (v0.20.0 T4; spec §3.2).

``scripts/start.ps1`` (Windows) and ``scripts/start.sh`` (POSIX ``sh``) do the
same thing line for line. So they cannot drift:

* their "Next steps" blocks list the same commands, once the interpreter path
  (``.\\.venv\\Scripts\\python.exe`` / ``.venv/bin/python``) and the path
  separator are set aside;
* both install ``requirements.txt`` under ``constraints.txt``;
* ``start.sh`` is committed executable (``100755`` in the git index -- this
  checkout has ``core.fileMode=false``, so the bit is set with ``git
  update-index --chmod=+x``) and with LF endings.

The index check skips cleanly where git history cannot be read (no ``.git``,
no ``git`` on PATH), as ``test_ui_contract.py``'s build check does.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PS1 = REPO / "scripts" / "start.ps1"
SH = REPO / "scripts" / "start.sh"

_PS1_LINE = re.compile(r'^\s*Write-Host "(?P<text>.*)"\s*$')
_SH_LINE = re.compile(r'^\s*echo "(?P<text>.*)"\s*$')
_INTERPRETERS = (".\\.venv\\Scripts\\python.exe", ".venv/bin/python")


def _next_steps(path: Path, line: re.Pattern[str]) -> list[str]:
    """The printed lines after "Next steps:", in order."""
    printed = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = line.match(raw)
        if match:
            printed.append(match["text"])
    start = next(i for i, text in enumerate(printed) if text.endswith("Next steps:"))
    return printed[start + 1 :]


def _commands(lines: list[str]) -> list[tuple[str, str]]:
    """(label, command) for each "  Label:   <interpreter> args" line, with the
    interpreter replaced by PY and backslashes by slashes."""
    out = []
    for text in lines:
        label, sep, rest = text.partition(":")
        rest = rest.strip()
        if not sep or not any(rest.startswith(i) for i in _INTERPRETERS):
            continue
        for interpreter in _INTERPRETERS:
            if rest.startswith(interpreter):
                rest = "PY" + rest[len(interpreter) :]
        out.append((label.strip(), rest.replace("\\", "/")))
    return out


def test_both_list_the_same_next_steps() -> None:
    ps1 = _commands(_next_steps(PS1, _PS1_LINE))
    sh = _commands(_next_steps(SH, _SH_LINE))
    assert len(ps1) >= 7, ps1
    assert ps1 == sh


def test_the_prose_around_the_commands_matches_too() -> None:
    def prose(lines: list[str]) -> list[str]:
        return [
            text.replace("$ModelServer", "<model>")
            for text in lines
            if not any(i in text for i in _INTERPRETERS)
        ]

    assert prose(_next_steps(PS1, _PS1_LINE)) == prose(_next_steps(SH, _SH_LINE))


@pytest.mark.parametrize("path", [PS1, SH], ids=["start.ps1", "start.sh"])
def test_both_install_under_the_constraints(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.search(r"pip install -q -r requirements\.txt -c constraints\.txt", text)


def test_start_sh_is_posix_sh_with_lf_endings() -> None:
    raw = SH.read_bytes()
    assert raw.startswith(b"#!/bin/sh\n")
    assert b"\r" not in raw


def _git(*args: str) -> str:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH -- the index cannot be read")
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git could not be run: {exc}")
    if done.returncode != 0:
        pytest.skip(f"`git {' '.join(args)}` failed: {done.stderr.strip()}")
    return done.stdout.strip()


# -- start.sh's venv checks, run for real under a POSIX shell (fix round 1) --------
#
# Review finding 2: on Debian/Ubuntu without python3.X-venv, `python3 -m venv`
# fails at ensurepip AFTER creating .venv/bin/python, and the next run reused
# that pip-less venv; an existing venv's Python version was never checked.
# These run start.sh itself -- a copy in tmp_path, beside a fake interpreter --
# under dash (or sh), which Git for Windows ships too. Each case stops before
# the script's pip install, so nothing is installed and no network is used.
# What cannot be run here (a real Debian without the venv package) is the same
# code path as the fake: `venv` fails, or leaves a venv whose pip does not run.

_SHELL = shutil.which("dash") or shutil.which("sh")
needs_sh = pytest.mark.skipif(_SHELL is None, reason="no POSIX sh on PATH")


def _fake(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("#!/bin/sh\n" + body + "\n").encode("utf-8"))
    path.chmod(0o755)


#: An interpreter stand-in: answers "is this 3.11+?" with `newer`, prints
#: `version` when asked for it, and answers `-m pip --version` with `pip`.
def _interpreter(version: str, newer: bool, pip: bool) -> str:
    return (
        'case "$*" in\n'
        f'  *"version_info >= (3, 11)"*) exit {0 if newer else 1};;\n'
        f'  *"%d.%d"*) echo {version}; exit 0;;\n'
        f'  "-m pip --version") exit {0 if pip else 1};;\n'
        "  *) exit 0;;\n"
        "esac"
    )


def _run(repo: Path, fakebin: Path | None = None) -> subprocess.CompletedProcess[str]:
    script = repo / "scripts" / "start.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_bytes(SH.read_bytes())
    env = dict(os.environ)
    if fakebin is not None:
        env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [str(_SHELL), str(script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


@needs_sh
def test_dash_parses_start_sh() -> None:
    done = subprocess.run(
        [str(_SHELL), "-n", str(SH)], capture_output=True, text=True, timeout=30
    )
    assert done.returncode == 0, done.stderr


@needs_sh
def test_an_existing_venv_older_than_311_is_refused_and_kept(tmp_path: Path) -> None:
    _fake(tmp_path / ".venv" / "bin" / "python", _interpreter("3.9", newer=False, pip=True))
    done = _run(tmp_path)
    assert done.returncode == 1
    assert "runs Python 3.9" in done.stderr and "requires 3.11" in done.stderr
    assert (tmp_path / ".venv" / "bin" / "python").exists(), "the owner's venv is kept"
    assert "Running tests" not in done.stdout


@needs_sh
def test_an_existing_venv_without_pip_names_the_package_and_is_kept(tmp_path: Path) -> None:
    _fake(tmp_path / ".venv" / "bin" / "python", _interpreter("3.11", newer=True, pip=False))
    done = _run(tmp_path)
    assert done.returncode == 1
    assert "no pip" in done.stderr and "python3.11-venv" in done.stderr
    assert (tmp_path / ".venv").exists()


@needs_sh
def test_an_existing_venv_whose_python_does_not_run_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    done = _run(tmp_path)
    assert done.returncode == 1
    assert "does not run" in done.stderr
    assert (tmp_path / ".venv").exists()


def _base_that_fails_at_ensurepip(fakebin: Path, venv_exit: int) -> None:
    """A python3.11 that, like Debian's without python3.11-venv, makes
    .venv/bin/python (one whose pip does not run) and then exits `venv_exit`."""
    template = fakebin / "venv-python.template"
    _fake(template, _interpreter("3.11", newer=True, pip=False))
    _fake(
        fakebin / "python3.11",
        'case "$*" in\n'
        '  *"-venv"*) echo python3.11-venv; exit 0;;\n'
        '  "-m venv .venv")\n'
        "    mkdir -p .venv/bin\n"
        f'    cp "{template.as_posix()}" .venv/bin/python\n'
        "    chmod +x .venv/bin/python\n"
        f"    exit {venv_exit};;\n"
        "  *) exit 0;;\n"
        "esac",
    )


@needs_sh
@pytest.mark.parametrize("venv_exit", [1, 0], ids=["venv-fails", "venv-leaves-no-pip"])
def test_a_failed_venv_creation_is_removed_and_names_the_package(
    tmp_path: Path, venv_exit: int
) -> None:
    repo = tmp_path / "repo"
    fakebin = tmp_path / "bin"
    _base_that_fails_at_ensurepip(fakebin, venv_exit)
    done = _run(repo, fakebin)
    assert done.returncode == 1, done.stderr
    assert "sudo apt install python3.11-venv" in done.stderr
    assert not (repo / ".venv").exists(), "the half-made venv is removed"
    assert "Running tests" not in done.stdout


@needs_sh
def test_a_dangling_venv_symlink_is_refused_and_left_alone(tmp_path: Path) -> None:
    """
    v0.20.0 T5 (T4 re-review): ``[ -e .venv ]`` is false for a symlink whose
    target is gone, so the script took the creation branch -- and, when that
    failed, ``rm -rf .venv`` removed the owner's link. It is refused now, and
    neither the link nor its (absent) target is touched.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    fakebin = tmp_path / "bin"
    _base_that_fails_at_ensurepip(fakebin, venv_exit=1)
    link = repo / ".venv"
    target = tmp_path / "gone-venv"
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this machine cannot make a symlink here: {exc}")
    probe = subprocess.run(
        [str(_SHELL), "-c", '[ -L .venv ] && [ ! -e .venv ]'], cwd=repo, timeout=30
    )
    if probe.returncode != 0:
        pytest.skip("this POSIX shell does not see the link as a dangling symlink")
    done = _run(repo, fakebin)
    assert done.returncode == 1, done.stderr
    assert "symbolic link to something that does not exist" in done.stderr
    assert os.path.islink(link), "the owner's link is kept"
    assert not target.exists(), "nothing is built through the link"
    assert "Creating venv" not in done.stdout


def test_start_sh_is_executable_in_the_index() -> None:
    entry = _git("ls-files", "-s", "--", "scripts/start.sh")
    if not entry:
        pytest.skip("scripts/start.sh is not in the git index yet")
    assert entry.split()[0] == "100755", entry

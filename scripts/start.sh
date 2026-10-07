#!/bin/sh
# The Clockwork Dark -- bootstrap + verify script (Linux; other POSIX systems,
# macOS included, should work but are untested)
#
# Creates the venv if it is missing, installs requirements under
# constraints.txt (the versions the suite was proven green on), and gates on
# the test suite. It does NOT start the game: six stories ship, and picking
# one is the player's call -- the "next steps" below are the accurate ways in.
#
# scripts/start.ps1 is the Windows twin, line for line. Their "Next steps"
# blocks list the same commands, modulo the interpreter path, and
# tests/test_start_scripts.py holds them to it: change one, change both.
#
# Version: v0.20.0 [2026-09-30]

set -eu

Root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$Root"

VenvPython="$Root/.venv/bin/python"
# The project requires Python 3.11 or newer (pyproject.toml, requires-python).
AtLeast311='import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'

# `-e` follows a link, so a .venv symlink whose target is gone reads as
# absent, and the creation branch below would build a venv through it (or
# remove it on failure). A link is the owner's: refused, never touched.
if [ -L .venv ] && [ ! -e .venv ]; then
    echo "The .venv here is a symbolic link to something that does not exist." >&2
    echo "It is left as it is: repoint the link, or remove it (the link, not" >&2
    echo "its target) and run this script again to build a fresh .venv." >&2
    exit 1
fi

if [ -e .venv ]; then
    # An existing venv is the owner's: checked, never deleted or rebuilt here.
    if [ ! -x "$VenvPython" ] || ! "$VenvPython" -c 'import sys' >/dev/null 2>&1; then
        echo "A .venv exists but its python ($VenvPython) does not run." >&2
        echo "Remove .venv and run this script again to rebuild it." >&2
        exit 1
    fi
    if ! "$VenvPython" -c "$AtLeast311" >/dev/null 2>&1; then
        Found=$("$VenvPython" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "unknown")
        echo "The existing .venv runs Python $Found; this project requires 3.11 or newer." >&2
        echo "It is not replaced for you: remove .venv and run this script again" >&2
        echo "with python3.11 (or a python3 that is 3.11+) on PATH." >&2
        exit 1
    fi
    if ! "$VenvPython" -m pip --version >/dev/null 2>&1; then
        echo "The existing .venv has no pip: it was probably left half-made by a" >&2
        echo "venv creation that failed at ensurepip. Remove .venv and run this" >&2
        echo "script again; on Debian or Ubuntu, install the python3.11-venv" >&2
        echo "package first (sudo apt install python3.11-venv)." >&2
        exit 1
    fi
else
    # python3.11 by name, else python3 if it is 3.11 or newer.
    if command -v python3.11 >/dev/null 2>&1; then
        Base=python3.11
    elif command -v python3 >/dev/null 2>&1 && python3 -c "$AtLeast311"; then
        Base=python3
    else
        echo "Python 3.11 or newer is required (python3.11, or a python3 that is 3.11+)." >&2
        exit 1
    fi
    VenvPackage=$("$Base" -c 'import sys; print("python%d.%d-venv" % sys.version_info[:2])')
    echo "Creating venv..."
    # On Debian and Ubuntu, `python3 -m venv` without the distro's venv
    # package fails at ensurepip AFTER creating .venv/bin/python, and a
    # second run would then find a venv with no pip. So a failed creation
    # removes the half-made .venv (it was made just now, by this script).
    if ! "$Base" -m venv .venv || ! "$VenvPython" -m pip --version >/dev/null 2>&1; then
        rm -rf .venv
        echo "Creating the venv failed, and the half-made .venv was removed." >&2
        echo "On Debian or Ubuntu, install the venv package and run this script again:" >&2
        echo "    sudo apt install $VenvPackage" >&2
        exit 1
    fi
fi

"$VenvPython" -m pip install -q -r requirements.txt -c constraints.txt
echo "Running tests..."
"$VenvPython" -m pytest tests/ --full -q --tb=short

# The configured model server, read from the config the engine itself reads
# (config/default.yaml under config/local.yaml), never written here.
ModelServer=$("$VenvPython" -c 'from engine.config import get_config; c = get_config(); print(c.get("llm.provider"), "expected at", c.get("llm.base_url"))' 2>/dev/null) || ModelServer=""
if [ -z "$ModelServer" ]; then ModelServer="(could not read llm.provider from the config)"; fi

echo ""
echo "All green. Next steps:"
echo ""
echo "  Check the environment:   .venv/bin/python scripts/doctor.py"
echo "  Check local services:    .venv/bin/python launcher.py --check"
echo "                           (model server: $ModelServer)"
echo "  Seed lore (first run):   .venv/bin/python scripts/seed_lore.py"
echo ""
echo "  List installed games:    .venv/bin/python launcher.py --list-games"
echo "  Play the flagship:       .venv/bin/python launcher.py --game clockwork-dark"
echo "  Play another story:      .venv/bin/python launcher.py --game hue-and-cry"
echo "  With managed services:   .venv/bin/python launcher.py --game <slug> --stack"
echo ""
echo "  The launcher prints its URL on start. The port comes from"
echo "  scene.<name>.port in config/default.yaml (5573 by default);"
echo "  override per run with --port."

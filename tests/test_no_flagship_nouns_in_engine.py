"""
No Flagship Noun Is a Code Literal in the Engine
================================================

THE REGRESSION THIS BLOCKS. The Clockwork Dark grew up inside this engine, so
its nouns -- Edgewood, the forest clearing, Maris, the wayfarer -- kept ending
up as Python literals that every other story silently inherited: the canned
outage line breathed the flagship's forest, procgen placed every story's
villagers in Edgewood Square, `apply_archetype` reinstated "wayfarer" at the
end of a chain two other layers had correctly left empty. Each one was fixed
individually; this test is what keeps the class of bug from coming back.

HOW IT READS THE CODE. Like Python does: as an AST, with docstrings removed.
Comments and docstrings may (and do, in house style) narrate the old bugs by
name -- explaining a defect requires naming it. What must never come back is a
flagship noun the engine can actually EXECUTE: a string literal that reaches a
prompt, an id lookup, a path or a default.

THE ALLOWLIST is per-file and exact-literal, each entry with the reason it
remains and whose job removing it is. It must only ever shrink.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ENGINE = _ROOT / "engine"

# Single-word nouns, matched as whole identifier tokens ("npc_maris" splits to
# "npc" + "maris" and is caught; "summarised" contains m-a-r-i-s and is not).
_WORD_NOUNS = frozenset(
    {
        "edgewood",
        "millhaven",
        "maris",
        "odran",
        "brindle",
        "ilya",
        "wayfarer",
        "hearthkeeper",
    }
)

# Multi-token nouns, matched with separators.
_PHRASE_NOUNS = (
    re.compile(r"forest[_\- ]clearing"),
    re.compile(r"tinker[_\- ]apprentice"),
    re.compile(r"tinker[_\- ]caravan"),
    re.compile(r"clockwork[_\- ]dark"),
)

_TOKEN_RE = re.compile(r"[a-z]+")

# Literals that legitimately remain, per engine file, each with the reason and
# the owner of its removal. Matched EXACTLY against the literal's full text.
_ALLOWED: dict[str, frozenset[str]] = {
    # The shipped default game, named once as the last resort when
    # config/default.yaml (game.default) is itself unreadable. A launcher-level
    # choice, not content inheritance -- nothing of the flagship's is read
    # through it unless the flagship is actually the story being launched.
    "engine/games/registry.py": frozenset({"clockwork-dark"}),
}


def _live_strings(source: str) -> list[tuple[int, str]]:
    """Every string constant in the module that is not a docstring."""
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            docstrings.add(id(node.body[0].value))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _offending_nouns(text: str) -> list[str]:
    lowered = text.lower()
    found = [word for word in _TOKEN_RE.findall(lowered) if word in _WORD_NOUNS]
    found += [rx.pattern for rx in _PHRASE_NOUNS if rx.search(lowered)]
    return found


def test_no_flagship_noun_is_a_code_literal_in_engine() -> None:
    offenders: list[str] = []
    for path in sorted(_ENGINE.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        allowed = _ALLOWED.get(rel, frozenset())
        for lineno, literal in _live_strings(path.read_text(encoding="utf-8")):
            if literal in allowed:
                continue
            nouns = _offending_nouns(literal)
            if nouns:
                offenders.append(f"{rel}:{lineno}: {nouns} in {literal!r:.80}")

    assert not offenders, (
        "Flagship nouns are live string literals in the engine again. A story's "
        "nouns belong in its games/<slug>/ tree, declared through its manifest; "
        "the engine's defaults are neutral:\n  " + "\n  ".join(offenders)
    )


def test_the_allowlist_only_names_real_files() -> None:
    """A removed literal must take its allowlist row with it."""
    for rel, literals in _ALLOWED.items():
        path = _ROOT / rel
        assert path.is_file(), f"allowlist names a missing file: {rel}"
        live = {text for _lineno, text in _live_strings(path.read_text(encoding="utf-8"))}
        for literal in literals:
            assert literal in live, (
                f"{rel} no longer contains {literal!r}; delete its allowlist row "
                "so the gate tightens behind it"
            )


def test_agent_ids_are_the_only_clockwork_identifiers_left() -> None:
    """
    The agent ids (`clockwork_storyteller`, `clockwork_assistant`), the skill
    pack (`pack="clockwork"`), the scene defaults in engine/scenes/spec.py and
    the active-engine context var still carry the word "clockwork". They are
    IDENTITY, owned by parallel workstreams (S4: agents/skills, S2: the scene
    package), so this test pins today's inventory rather than banning the word:
    a NEW "clockwork" literal in a file not listed here is the old bug, not
    more identity.
    """
    expected = {
        "engine/agents/assistant.py",  # AGENT_ID -- S4 removes
        "engine/agents/storyteller.py",  # AGENT_ID -- S4 removes
        "engine/config.py",  # CLOCKWORK_ENV -- the project's env-var prefix
        "engine/persistence/storage.py",  # CLOCKWORK_DATA_DIR -- the same prefix (v0.20.0)
        "engine/game/engine.py",  # ContextVar name -- S4 renames
        "engine/games/registry.py",  # DEFAULT_SLUG + CLOCKWORK_GAME env var
        "engine/media/providers/comfy.py",  # ComfyUI output prefix -- S4
        "engine/media/providers/shipped.py",  # flagship art tree for its own script
        "engine/scenes/spec.py",  # default scene NAME keys scene.clockwork.* config
        # The extracted default scene serves the flagship-pinned asset home
        # (content/scenes/clockwork/static + templates/clockwork.html, held by
        # ui/vite.config.js outDir) and reads scene.clockwork.* for port/host.
        # Both are deliberate compat identities documented in the module; the
        # day the asset home and config key are renamed, this row goes too.
        "engine/scenes/default_scene.py",
        # Hosted mode (v0.20.0 T7): CLOCKWORK_STUDIO, the project's env-var
        # prefix, and the login cookie's name, clockwork_session, which spec
        # §6.2 fixes (one name at every door of an instance).
        "engine/hosting/__init__.py",
        "engine/hosting/auth.py",
        # The bus and the supervisor (v0.20.0 T10): CLOCKWORK_BUS_ADDR,
        # CLOCKWORK_BUS_TOKEN, CLOCKWORK_BUS_ROLE, CLOCKWORK_PROXY_TOKEN and
        # CLOCKWORK_GAME, the project's env-var prefix (spec §14.2).
        "engine/hosting/boot.py",
        "engine/hosting/bus.py",
        "engine/hosting/supervisor/process.py",
        # The front door's proxy token header (v0.20.0 T12, spec §14.5):
        # X-Clockwork-Proxy, the project's header prefix.
        "engine/hosting/gate.py",
        # ...and the front door names the bus variables it refuses without
        # (CLOCKWORK_BUS_ADDR, CLOCKWORK_BUS_TOKEN), as boot.py does.
        "engine/hosting/frontdoor/__init__.py",
        # The builtin skill pack was renamed to "core"; the five skills/builtin
        # rows that stood here are gone and must not return.
    }
    actual: set[str] = set()
    for path in sorted(_ENGINE.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        for _lineno, literal in _live_strings(path.read_text(encoding="utf-8")):
            if "clockwork" in literal.lower():
                actual.add(rel)
                break

    new_files = actual - expected
    assert not new_files, (
        f"new files carry 'clockwork' string literals: {sorted(new_files)} -- "
        "story identity belongs to the story, not the engine"
    )
    gone = expected - actual
    assert not gone, (
        f"these files no longer carry 'clockwork' literals: {sorted(gone)} -- "
        "remove them from this inventory so the gate tightens behind them"
    )

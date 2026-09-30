"""
``engine/lmstudio/`` became ``engine/llm/`` in v0.19.0 (spec §1.1).

The package serves five model servers now, so it is named for what it does.
``engine/lmstudio/__init__.py`` stays behind as an IDENTITY shim until v0.21.0
(removed with the legacy ``lmstudio:`` config alias): every old dotted path
resolves to the very same module object as the new one, by import and by
attribute. ``native`` is the one module whose name changed as well as its
package: it is ``engine.llm.lmstudio_native`` now, since four other servers
have their own "native" routes.

Why both halves of the shim. A ``sys.modules`` entry makes ``import
engine.lmstudio.backend`` work, but it does not set the attribute on the parent
package, and a dotted STRING patch target
(``monkeypatch.setattr("engine.lmstudio.backend.resolve_profile", ...)``)
resolves by attribute walk. Without the ``setattr`` half such a patch fails to
resolve, or patches nothing the engine reads.

And why a scan. The shim makes an old path keep working, which is exactly what
lets one survive unnoticed: nothing in ``engine/``, ``scripts/``,
``content/``, ``launcher.py`` or ``tests/`` may name ``engine.lmstudio`` in an
import (absolute or relative) or in any string literal, apart from the shim
itself and this file.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: old submodule name -> new submodule name, for every module of the package.
SUBMODULES: dict[str, str] = {
    "backend": "backend",
    "client": "client",
    "discovery": "discovery",
    "events": "events",
    "gate": "gate",
    "native": "lmstudio_native",
    "ollama": "ollama",
    "profiles": "profiles",
    "providers": "providers",
    "registry": "registry",
    "routes": "routes",
    "schemas": "schemas",
    "tools": "tools",
}

#: The only files allowed to name the old package.
_SHIM = ROOT / "engine" / "lmstudio" / "__init__.py"
_THIS = Path(__file__).resolve()

_OLD = "engine.lmstudio"


def test_every_module_of_the_new_package_is_listed_here():
    """A module added to engine/llm/ must be aliased by the shim too."""
    on_disk = {
        p.stem for p in (ROOT / "engine" / "llm").glob("*.py") if p.name != "__init__.py"
    }
    assert on_disk == set(SUBMODULES.values())


@pytest.mark.parametrize("old,new", sorted(SUBMODULES.items()))
def test_the_old_path_imports_the_same_module_object(old, new):
    legacy = importlib.import_module(f"{_OLD}.{old}")
    current = importlib.import_module(f"engine.llm.{new}")
    assert legacy is current


@pytest.mark.parametrize("old,new", sorted(SUBMODULES.items()))
def test_the_old_path_is_the_same_module_as_an_attribute(old, new):
    import engine.llm
    import engine.lmstudio

    assert getattr(engine.lmstudio, old) is getattr(engine.llm, new)


def test_the_old_package_re_exports_the_new_packages_names():
    import engine.llm
    import engine.lmstudio

    assert engine.lmstudio.__all__ == engine.llm.__all__
    for name in engine.llm.__all__:
        assert getattr(engine.lmstudio, name) is getattr(engine.llm, name)


def test_a_dotted_string_patch_on_the_old_path_is_seen_by_the_new_module(monkeypatch):
    """
    The ``setattr`` half. ``monkeypatch.setattr`` with a string target walks
    attributes from ``engine``; without the shim setting ``backend`` on
    ``engine.lmstudio`` this cannot resolve.
    """
    import engine.llm.backend

    def sentinel(*_args, **_kwargs):
        return "patched"

    monkeypatch.setattr(_OLD + ".backend.resolve_profile", sentinel)
    assert engine.llm.backend.resolve_profile is sentinel


def test_the_shim_defines_no_functions_of_its_own():
    tree = ast.parse(_SHIM.read_text(encoding="utf-8"))
    defined = [
        getattr(node, "name", "<lambda>")
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))
    ]
    assert defined == []


#: The dotted name, and the same package as a path (a docstring citing
#: ``engine/lmstudio/backend.py`` is as stale as an import of it).
_OLD_SPELLINGS = (_OLD, "engine/lmstudio", "engine\\lmstudio")


def _names_old_package(text: str) -> bool:
    return any(
        text == old or (old + ".") in text or (old + "/") in text or (old + "\\") in text
        for old in _OLD_SPELLINGS
    )


def _package_of(path: Path, root: Path) -> list[str]:
    """The dotted package ``path`` belongs to, as parts, relative to ``root``."""
    try:
        parts = list(path.resolve().relative_to(root.resolve()).with_suffix("").parts)
    except ValueError:
        return []
    return parts[:-1]  # a module's package; an __init__'s own package is its dir


def _absolute(node: ast.ImportFrom, package: list[str]) -> str:
    """``from <.x> import ...``'s module as an absolute dotted name ("" if unknowable)."""
    if node.level == 0:
        return node.module or ""
    if node.level - 1 > len(package):
        return ""
    base = package[: len(package) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def old_package_references(path: Path, root: Path = ROOT) -> list[str]:
    """
    Every import of, and string literal naming, ``engine.lmstudio`` in ``path``.

    A relative import (``from .lmstudio import x`` in ``engine/``, ``from ..
    import lmstudio`` below it) is resolved against the file's own package
    under ``root`` first, so it is caught as surely as the absolute spelling.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _package_of(path, root)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _names_old_package(alias.name):
                    found.append(f"{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = _absolute(node, package)
            spelled = "." * node.level + (node.module or "")
            if module and _names_old_package(module):
                found.append(f"{node.lineno}: from {spelled} import ...")
            if module == "engine":
                for alias in node.names:
                    if alias.name == "lmstudio":
                        found.append(f"{node.lineno}: from {spelled} import lmstudio")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _names_old_package(node.value):
                found.append(f"{node.lineno}: string {node.value.splitlines()[0][:80]!r}")
    return found


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for top in ("engine", "scripts", "tests", "content"):
        files.extend((ROOT / top).rglob("*.py"))
    files.append(ROOT / "launcher.py")
    return sorted(
        p for p in files if p.resolve() not in {_SHIM.resolve(), _THIS} and "__pycache__" not in p.parts
    )


def test_nothing_but_the_shim_names_the_old_package():
    offenders = {
        str(path.relative_to(ROOT)): refs
        for path in _scanned_files()
        if (refs := old_package_references(path))
    }
    assert not offenders, (
        "these files still name engine.lmstudio in an import or a string "
        f"literal; name engine.llm instead (the shim goes in v0.21.0): {offenders}"
    )


def test_the_scan_catches_an_import_and_a_string_patch_target(tmp_path):
    """Canary: the scan is not vacuous for either shape."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import engine.lmstudio.backend\n"
        "from engine.lmstudio.registry import ModelInfo\n"
        "from engine import lmstudio\n"
        "TARGET = 'engine.lmstudio.backend.resolve_profile'\n"
        "DOC = 'see engine/lmstudio/backend.py'\n",
        encoding="utf-8",
    )
    refs = old_package_references(probe)
    assert len(refs) == 5, refs
    clean = tmp_path / "clean.py"
    clean.write_text(
        "import engine.llm.backend\n"
        "KEY = 'lmstudio.native_url'\n"
        "NAME = 'lmstudio'\n",
        encoding="utf-8",
    )
    assert old_package_references(clean) == []


def test_the_scan_catches_relative_imports_of_the_old_package(tmp_path):
    """
    Canary, carried from T7's review: ``from .lmstudio import x`` inside
    ``engine/`` names the old package as surely as the absolute spelling, and
    the first version of the scan read only ``level == 0``.
    """
    engine = tmp_path / "engine"
    (engine / "agents").mkdir(parents=True)
    top = engine / "mod.py"
    top.write_text(
        "from .lmstudio import backend\n"
        "from .lmstudio.registry import ModelInfo\n"
        "from . import lmstudio\n"
        "from .llm import backend as fine\n",
        encoding="utf-8",
    )
    assert len(old_package_references(top, tmp_path)) == 3
    deep = engine / "agents" / "mod.py"
    deep.write_text(
        "from ..lmstudio.client import LMSClient\n"
        "from .. import lmstudio\n"
        "from ..llm import client\n"
        "from . import lmstudio as sibling\n",  # engine.agents.lmstudio: not the package
        encoding="utf-8",
    )
    assert len(old_package_references(deep, tmp_path)) == 2


def test_content_is_scanned_too():
    assert any(p.parts[len(ROOT.parts)] == "content" for p in _scanned_files())

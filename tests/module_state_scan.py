"""
The module-state scan (v0.20.0, spec §5.2): every piece of process-wide
state the engine keeps, found mechanically so a new one cannot arrive
unclassified.

Five kinds of site, each given a stable id:

* ``engine.pkg.mod.NAME`` -- a module-level name that is rebound through a
  ``global`` statement anywhere in its module, or bound at module level to a
  container (a dict, list or set literal or comprehension, or a call to
  ``dict``/``list``/``set``/``defaultdict``/``OrderedDict``/``deque``/
  ``Counter`` or a weak container), to ``None``, to a ``threading`` or
  ``contextvars`` object, or to an INSTANCE of a class (a capitalised callee:
  ``SkillRegistry()``, ``random.Random()``, ``queue.Queue()``; bar the few in
  ``_IMMUTABLE_CALLS``: ``Path``, ``TypeVar`` ...). ``__all__`` is left out:
  it is the import convention, never written after the module runs.
* ``engine.pkg.mod.Class.ATTR`` -- a container bound in a class body: one
  object every instance and every thread shares.
* ``engine.pkg.mod.func()`` -- a function decorated ``@lru_cache`` /
  ``@functools.lru_cache`` / ``@cache`` (a method is named ``Class.method()``).
* ``engine.pkg.mod.qualname#Thread`` -- a ``threading.Thread(``,
  ``threading.Timer(``, ``ThreadPoolExecutor(`` or ``ProcessPoolExecutor(``
  call site (``#Timer``, ``#ThreadPoolExecutor`` ...), named by the function
  or class that makes it (``<module>`` at module scope; ``#Thread2`` and on
  for a second of a kind in one scope).
* ``engine.pkg.mod.Class#ThreadSubclass`` -- a subclass of ``threading.Thread``.

Read by ``tests/test_module_state_inventory.py`` (the pin) and
``tests/test_cache_warming.py`` (the ``warmed`` rows). Pure AST: nothing is
imported, so the scan sees modules the suite never loads.

Version: v0.1.0 [2026-10-01]
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Iterator, Optional

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
INVENTORY = ROOT / "tests" / "fixtures" / "module_state.yaml"

#: The verdicts a row may carry (spec §5.2).
VERDICTS = frozenset(
    {
        "per_context",
        "locked",
        "warmed",
        "log_once",
        "registration",
        "constant",
        "shared_by_design",
        "not_served_hosted",
    }
)

_CONTAINER_CALLS = frozenset(
    {
        "dict",
        "list",
        "set",
        "defaultdict",
        "OrderedDict",
        "deque",
        "Counter",
        "WeakValueDictionary",
        "WeakKeyDictionary",
        "WeakSet",
    }
)
_THREADING_NAMES = frozenset(
    {
        "Lock",
        "RLock",
        "local",
        "Event",
        "Condition",
        "Semaphore",
        "BoundedSemaphore",
        "Barrier",
        "ContextVar",
    }
)
_THREADING_MODULES = frozenset({"threading", "contextvars"})
_POOL_CALLS = frozenset({"ThreadPoolExecutor", "ProcessPoolExecutor"})
#: Capitalised callees that build something immutable, or a typing construct:
#: a module name bound to one is a constant, not state, and is not a site.
_IMMUTABLE_CALLS = frozenset(
    {
        "Path",
        "PurePath",
        "PurePosixPath",
        "PureWindowsPath",
        "TypeVar",
        "ParamSpec",
        "NewType",
        "NamedTuple",
        "Decimal",
        "Fraction",
    }
)
_LRU_NAMES = frozenset({"lru_cache", "cache"})


def module_name(path: Path, root: Path = ROOT) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _call_name(node: ast.AST) -> Optional[tuple[Optional[str], str]]:
    """``(module, name)`` of a call's callee: ``threading.Lock`` -> ("threading", "Lock")."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return None, func.id
    if isinstance(func, ast.Attribute):
        base = func.value
        return (base.id if isinstance(base, ast.Name) else None), func.attr
    return None


def _is_container(value: Optional[ast.AST]) -> bool:
    """A dict, list or set literal or comprehension, or a container call."""
    if value is None:
        return False
    if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    called = _call_name(value)
    return (
        called is not None
        and called[1] in _CONTAINER_CALLS
        and called[0] in (None, "collections", "weakref")
    )


def _is_instance(value: Optional[ast.AST]) -> bool:
    """
    A call that builds an instance of a class (a capitalised callee:
    ``SkillRegistry()``, ``random.Random()``, ``queue.Queue()``), bar the few
    that build something immutable or purely typing (``_IMMUTABLE_CALLS``).
    """
    called = _call_name(value) if value is not None else None
    if called is None:
        return False
    mod, name = called
    if name in _IMMUTABLE_CALLS:
        return False
    return name[:1].isupper() and mod not in ("typing",)


def _is_tracked_value(value: Optional[ast.AST]) -> bool:
    if value is None:
        return False
    if isinstance(value, ast.Constant) and value.value is None:
        return True
    if _is_container(value) or _is_instance(value):
        return True
    called = _call_name(value)
    if called is None:
        return False
    mod, name = called
    if mod in _THREADING_MODULES:
        return True
    return mod is None and name in _THREADING_NAMES


def _thread_kind(node: ast.AST) -> Optional[str]:
    """``Thread``, ``Timer``, ``ThreadPoolExecutor`` or ``ProcessPoolExecutor``
    for a call that starts (or can start) threads or processes."""
    called = _call_name(node)
    if called is None:
        return None
    mod, name = called
    if name in ("Thread", "Timer") and mod in ("threading", None):
        return name
    if name in _POOL_CALLS and mod in ("concurrent", "futures", None):
        return name
    return None


def _top_level(body: Iterable[ast.stmt]) -> Iterator[ast.stmt]:
    """Module-level statements, descending into if/try/with but not defs."""
    for stmt in body:
        yield stmt
        if isinstance(stmt, ast.If):
            yield from _top_level(stmt.body)
            yield from _top_level(stmt.orelse)
        elif isinstance(stmt, ast.Try):
            yield from _top_level(stmt.body)
            for handler in stmt.handlers:
                yield from _top_level(handler.body)
            yield from _top_level(stmt.orelse)
            yield from _top_level(stmt.finalbody)
        elif isinstance(stmt, ast.With):
            yield from _top_level(stmt.body)


def _targets(stmt: ast.stmt) -> list[tuple[str, Optional[ast.AST]]]:
    out: list[tuple[str, Optional[ast.AST]]] = []
    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                out.append((target.id, stmt.value))
    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        out.append((stmt.target.id, stmt.value))
    return out


def _is_lru(decorator: ast.AST) -> bool:
    node = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(node, ast.Name):
        return node.id in _LRU_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in _LRU_NAMES and isinstance(node.value, ast.Name) and node.value.id == "functools"
    return False


def _is_thread_base(base: ast.AST) -> bool:
    """``threading.Thread`` or ``Thread`` as a class's base."""
    if isinstance(base, ast.Name):
        return base.id == "Thread"
    return (
        isinstance(base, ast.Attribute)
        and base.attr == "Thread"
        and isinstance(base.value, ast.Name)
        and base.value.id == "threading"
    )


class _Walker(ast.NodeVisitor):
    """Collects lru_cache functions, class-level containers, thread and pool
    sites and Thread subclasses, each with its qualname."""

    def __init__(self, mod: str) -> None:
        self.mod = mod
        self.stack: list[str] = []
        self.found: list[str] = []
        self._threads: dict[tuple[str, str], int] = {}

    def _qual(self, name: str) -> str:
        return f"{self.mod}.{'.'.join([*self.stack, name])}"

    def _def(self, node: ast.AST) -> None:
        name = node.name  # type: ignore[attr-defined]
        if any(_is_lru(d) for d in node.decorator_list):  # type: ignore[attr-defined]
            self.found.append(f"{self._qual(name)}()")
        self.stack.append(name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _def
    visit_AsyncFunctionDef = _def

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if any(_is_thread_base(base) for base in node.bases):
            self.found.append(f"{self._qual(node.name)}#ThreadSubclass")
        # A container in a class body is one object shared by every instance
        # (and every thread): a class-level cache is module state by another name.
        for stmt in node.body:
            for attr, value in _targets(stmt):
                if _is_container(value):
                    self.found.append(f"{self._qual(node.name)}.{attr}")
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        kind = _thread_kind(node)
        if kind is not None:
            where = ".".join(self.stack) or "<module>"
            n = self._threads.get((where, kind), 0) + 1
            self._threads[(where, kind)] = n
            self.found.append(f"{self.mod}.{where}#{kind}{'' if n == 1 else n}")
        self.generic_visit(node)


def scan_source(source: str, mod: str) -> set[str]:
    """Every tracked site in one module's source."""
    tree = ast.parse(source)
    globals_rebound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            globals_rebound.update(node.names)
    names: set[str] = set()
    for stmt in _top_level(tree.body):
        for name, value in _targets(stmt):
            if name == "__all__":
                continue
            if name in globals_rebound or _is_tracked_value(value):
                names.add(f"{mod}.{name}")
    names.update(f"{mod}.{name}" for name in globals_rebound)
    walker = _Walker(mod)
    walker.visit(tree)
    names.update(walker.found)
    return names


def scan(engine: Path = ENGINE, root: Path = ROOT) -> set[str]:
    """Every tracked site under ``engine/``."""
    found: set[str] = set()
    for path in sorted(engine.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        found |= scan_source(path.read_text(encoding="utf-8"), module_name(path, root))
    return found


def load_inventory(path: Path = INVENTORY) -> dict[str, dict]:
    """``module_state.yaml``'s rows, keyed by site id."""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(data.get("sites") or {})


__all__ = ["INVENTORY", "VERDICTS", "load_inventory", "module_name", "scan", "scan_source"]

"""
Deprecated: the package is ``engine.llm`` since v0.19.0. Removed in v0.21.0.

An IDENTITY shim, not a copy. Every ``engine.lmstudio.<m>`` is the very module
object ``engine.llm.<m>`` -- in ``sys.modules`` (so ``import
engine.lmstudio.backend`` works) AND as an attribute of this package (so a
dotted string patch such as
``monkeypatch.setattr("engine.lmstudio.backend.resolve_profile", ...)``
resolves, and patches what the engine reads). A ``sys.modules`` entry alone
does not set the parent's attribute, which is why both halves are here.
``native`` is the one module renamed as well as moved: it is
``engine.llm.lmstudio_native``.

Nothing in the repo imports this path any more
(``tests/test_llm_package_shim.py`` scans for it); it exists for code outside
the repo. It defines nothing of its own.
"""

import importlib
import pkgutil
import sys

import engine.llm
from engine.llm import *  # noqa: F401,F403 -- the re-export IS the shim

__all__ = engine.llm.__all__

#: new submodule name -> the name it had under ``engine.lmstudio``.
_OLD_NAMES = {"lmstudio_native": "native"}

for _info in pkgutil.iter_modules(engine.llm.__path__):
    _module = importlib.import_module(f"engine.llm.{_info.name}")
    _old = _OLD_NAMES.get(_info.name, _info.name)
    sys.modules[f"{__name__}.{_old}"] = _module
    setattr(sys.modules[__name__], _old, _module)

del _info, _module, _old

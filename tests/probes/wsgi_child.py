"""
Imports one of hosted mode's gunicorn entry points in a fresh process, as
gunicorn's worker would (v0.20.0 T13, ``tests/test_hosting_wsgi.py``), so a
story activated by the import never outlives the test's own process.

    python -m tests.probes.wsgi_child engine.hosting.wsgi
    python -m tests.probes.wsgi_child engine.hosting.frontdoor.wsgi

Prints ONE JSON line: whether the import built an ``app`` (``ok``), the
refusal's key and text if it raised ``HostingConfigError``, whether the
engine's scene module was ever imported (``built``: ``create_app`` lives
there), the active story (``active``), the app's name, whether it holds a
bus, and whether the warmed governance chain exists. Then it leaves at once
(``os._exit``), so a bus reader or pool thread cannot hold it open.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main(argv: list[str]) -> None:
    from engine.hosting.config import HostingConfigError

    out: dict[str, Any] = {"ok": False, "key": "", "error": ""}
    app: Any = None
    try:
        app = importlib.import_module(argv[0]).app
        out["ok"] = True
    except HostingConfigError as exc:
        out["key"] = exc.key
        out["error"] = str(exc)
    from engine.games import registry

    active = registry.peek()
    out["active"] = getattr(active, "slug", None) if active is not None else None
    out["built"] = "engine.scenes.default_scene" in sys.modules
    if app is not None:
        from engine.hosting import BUS_EXTENSION
        from engine.hosting.frontdoor import FRONTDOOR_EXTENSION

        out["app"] = app.name
        out["bus"] = app.extensions.get(BUS_EXTENSION) is not None or app.extensions.get(FRONTDOOR_EXTENSION) is not None
        governance = sys.modules.get("engine.agents.governance")
        out["warmed"] = governance is not None and getattr(governance, "_GOVERNANCE", None) is not None
    print("WSGI_CHILD " + json.dumps(out), flush=True)
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])

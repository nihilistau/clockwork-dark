"""
The child of ``tests/test_subprocess_sandbox.py`` (v0.20.0 T5; spec §3.5).

Run in a FRESH interpreter -- through ``subprocess``, ``os.system``, a
``multiprocessing`` spawn or asyncio -- so it has none of the conftest's
in-process guards: only what it inherited (the ``CLOCKWORK_TEST_SANDBOX``
marker, and from the ``Popen`` wrapper a ``CLOCKWORK_CONFIG`` ending in the
sandbox layer). It imports the engine, registers one session into
``mcp_json_path()`` -- the write a child could aim at the owner's LM Studio
``mcp.json`` -- and reports, as JSON:

- ``base_url``: ``get_config().get("llm.base_url")``;
- ``hosting``: ``get_config().get("hosting.enabled")``;
- ``marker``: ``get_config().get("sandbox_probe.marker")``, a key only a
  stand-in ``local.yaml`` sets;
- ``written``: the path the registration wrote (``None`` if none);
- ``sandbox``: ``CLOCKWORK_TEST_SANDBOX`` as the child saw it;
- ``sandboxed``: whether the engine counts this process as a child of the
  suite (``engine.config.child_sandbox``);
- ``pid``: this process's pid;
- ``api_key_set``: whether ``llm.api_key`` resolves to anything, and
  ``api_key_kind`` its source kind (``secret_source``) -- never the key
  (v0.20.0 T16 fix round 1: a child has none unless the sandbox layer names
  one);
- ``probed``: with ``--probe-model``, whether the configured provider's
  health probe passed against ``llm.base_url`` (a test's registered stub).

It registers UNCONDITIONALLY (T5 fix round 1): what keeps it off the owner's
file is the engine's sandbox, not a special case here. A test that runs it
with a guard in doubt redirects the home directory and ``_CONFIG_DIR`` to
its temp directory first (AGENTS.md "Tests").

Usage: ``python tests/probes/sandbox_child.py [--config-dir <dir>] [--out <file>] [--probe-model]``.
``--config-dir`` points ``engine.config._CONFIG_DIR`` at a stand-in whose
``local.yaml`` sets the marker -- an ARGUMENT, never the environment.
``--out`` writes the JSON to a file (for ``os.system``, whose output is not
captured); otherwise it is the last line printed. No socket is opened, but
by ``--probe-model`` (to a test's registered stub).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def report(argv: list[str]) -> dict[str, Any]:
    """Configure from ``argv``, register one session, and answer what was seen."""
    import engine.config as config

    if "--config-dir" in argv:
        config._CONFIG_DIR = Path(argv[argv.index("--config-dir") + 1])
        config._instance = None

    from engine.mcp import skills_server

    cfg = config.get_config()
    target = skills_server.mcp_json_path()
    entry = skills_server.register_session(
        "http://127.0.0.1:9/mcp", "sandbox-probe", settle_seconds=0
    )
    written = str(target) if entry is not None and target is not None and target.exists() else None
    sandbox = getattr(config, "child_sandbox", None)
    probed = None
    if "--probe-model" in argv:
        from engine.llm.providers import get_provider

        probed = bool(get_provider().health_probe(timeout=5)[0])
    return {
        "api_key_set": bool(cfg.get("llm.api_key")),
        "api_key_kind": cfg.secret_source("llm.api_key")[0],
        "probed": probed,
        "base_url": cfg.get("llm.base_url"),
        "hosting": cfg.get("hosting.enabled"),
        "marker": cfg.get("sandbox_probe.marker"),
        "written": written,
        "sandbox": os.environ.get("CLOCKWORK_TEST_SANDBOX"),
        "sandboxed": bool(sandbox is not None and sandbox() is not None),
        "pid": os.getpid(),
    }


def report_to_file(argv: list[str], out: str) -> None:
    """``report``, written to ``out``: the target of a ``multiprocessing`` spawn."""
    Path(out).write_text(json.dumps(report(argv)), encoding="utf-8")


def main(argv: list[str]) -> int:
    if "--out" in argv:
        report_to_file(argv, argv[argv.index("--out") + 1])
    else:
        print(json.dumps(report(argv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

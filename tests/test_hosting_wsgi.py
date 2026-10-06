"""
Hosted mode's gunicorn entry points (v0.20.0 T13, spec §7.1, §14.5):
``engine/hosting/wsgi.py`` (a story's worker) and
``engine/hosting/frontdoor/wsgi.py`` (the front door).

Each is imported in a CHILD (``tests/probes/wsgi_child.py``), as gunicorn's
worker imports it, so the story an import activates never outlives the test.
Every child is sandboxed (the suite's ``Popen`` wrapper), reads the test's
own ``CLOCKWORK_CONFIG`` and keeps its data under ``tmp_path``. The bus is a
real ``BusServer`` in this process, on loopback, closed in a ``finally``.

- the worker's refuses local mode before it activates or builds anything,
  and refuses to boot without the supervisor's bus (spec §7.1 step 4);
- with hosting on and a bus, it builds, activates its story, warms and
  connects;
- the front door's likewise refuses local mode and a missing bus, and builds
  with one -- activating NO story.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
STORY = "clockwork-dark"

#: Inherited variables a child must not see.
_CLEARED = (
    "CLOCKWORK_STUDIO",
    "CLOCKWORK_GAME",
    "CLOCKWORK_SECRET_KEY",
    "CLOCKWORK_ENV",
    "CLOCKWORK_CONFIG",
    "CLOCKWORK_BUS_ADDR",
    "CLOCKWORK_BUS_TOKEN",
    "CLOCKWORK_BUS_ROLE",
    "CLOCKWORK_PROXY_TOKEN",
)


def _config(tmp_path: Path, *, hosting: bool) -> Path:
    path = tmp_path / "wsgi-config.yaml"
    tree = {
        "scene": {"clockwork": {"host": "127.0.0.1", "port": 0}},
        "hosting": {"enabled": hosting, "stories": [STORY], "cookie_secure": False},
    }
    path.write_text(yaml.safe_dump(tree, sort_keys=True), encoding="utf-8")
    return path


def _run(module: str, tmp_path: Path, *, hosting: bool, bus: Optional[dict[str, str]] = None) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if k not in _CLEARED}
    env["CLOCKWORK_CONFIG"] = str(_config(tmp_path, hosting=hosting))
    env["CLOCKWORK_DATA_DIR"] = str(tmp_path / "data")
    env["CLOCKWORK_GAME"] = STORY
    env.update(bus or {})
    done = subprocess.run(
        [sys.executable, "-u", "-m", "tests.probes.wsgi_child", module],
        cwd=str(REPO),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=240,
    )
    text = done.stdout.decode("utf-8", "replace")
    line = next((x for x in text.splitlines() if x.startswith("WSGI_CHILD ")), None)
    assert line, f"no result from the child (exit {done.returncode}):\n{text[-2000:]}\n{done.stderr.decode('utf-8', 'replace')[-2000:]}"
    return json.loads(line[len("WSGI_CHILD "):])


@pytest.fixture
def bus() -> Any:
    from engine.hosting.bus import BusServer

    server = BusServer().start()
    server.handle("stories.list", lambda _conn, _args: {"stories": [], "seq": 0})
    server.handle("ready", lambda _conn, _args: {})
    try:
        yield server
    finally:
        server.close()


def _bus_env(server: Any, role: str) -> dict[str, str]:
    import secrets

    if role == "worker":
        record = server.mint("worker", story=STORY, process=f"worker-{STORY}")
    else:
        record = server.mint("frontdoor", process="frontdoor")
    return {
        "CLOCKWORK_BUS_ADDR": server.addr,
        "CLOCKWORK_BUS_TOKEN": record.token,
        "CLOCKWORK_BUS_ROLE": role,
        "CLOCKWORK_PROXY_TOKEN": secrets.token_hex(32),
    }


@pytest.mark.parametrize("module", ["engine.hosting.wsgi", "engine.hosting.frontdoor.wsgi"])
def test_local_mode_is_refused_before_anything_is_built(tmp_path: Path, module: str) -> None:
    found = _run(module, tmp_path, hosting=False)
    assert not found["ok"]
    assert found["key"] == "hosting.enabled"
    assert "launcher.py" in found["error"] and "gunicorn serves hosted mode only" in found["error"]
    assert found["active"] is None, "a story was activated before the refusal"
    assert not found["built"]


@pytest.mark.parametrize("module", ["engine.hosting.wsgi", "engine.hosting.frontdoor.wsgi"])
def test_no_bus_is_refused(tmp_path: Path, module: str) -> None:
    found = _run(module, tmp_path, hosting=True)
    assert not found["ok"]
    assert found["key"] == "CLOCKWORK_BUS_ADDR"
    assert "python -m engine.hosting.supervisor" in found["error"]
    assert not found["built"]


def test_the_worker_builds_activates_warms_and_connects(tmp_path: Path, bus: Any) -> None:
    found = _run("engine.hosting.wsgi", tmp_path, hosting=True, bus=_bus_env(bus, "worker"))
    assert found["ok"], found
    assert found["active"] == STORY
    assert found["built"] and found["bus"] and found["warmed"]


def test_the_front_door_builds_and_activates_no_story(tmp_path: Path, bus: Any) -> None:
    found = _run("engine.hosting.frontdoor.wsgi", tmp_path, hosting=True, bus=_bus_env(bus, "frontdoor"))
    assert found["ok"], found
    assert found["app"] == "hosting_frontdoor"
    assert found["active"] is None, "the front door activated a story"
    assert found["bus"]

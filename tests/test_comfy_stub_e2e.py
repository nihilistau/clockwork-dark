"""The one end-to-end ComfyUI test over loopback (spec §13.5): a restart mid-job resubmits, one file."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.process_identity import alive, identify, terminate
from tests.social_fixtures import _lines, _spec, _wait_until, media_root  # noqa: F401  (fixture)

pytestmark = [pytest.mark.process, pytest.mark.loopback]

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def comfy_stub(tmp_path):
    port = _free_port()
    control = tmp_path / "control.json"                  # the stub reads its script from here per request
    control.write_text(json.dumps({"script": "hold"}), encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "comfy_stub.py"), "--port", str(port),
         "--control", str(control), "--log", str(tmp_path / "requests.jsonl"), "--exit-with-parent"],
        cwd=str(ROOT),
    )
    identity = identify(proc.pid)                        # pid AND creation time, read at once
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        terminate(identity)
        pytest.fail("comfy stub did not start")
    try:
        yield f"http://127.0.0.1:{port}", control, tmp_path / "requests.jsonl"
    finally:
        if alive(identity):
            terminate(identity)
        proc.wait(timeout=10)


def test_a_restart_mid_job_resubmits_and_keeps_one_file(comfy_stub, media_root) -> None:
    from engine.media.comfy.client import ComfyClient
    from engine.media.comfy.jobs import MediaJobWorker

    base, control, log = comfy_stub
    done: list = []

    def worker() -> MediaJobWorker:
        return MediaJobWorker(client_factory=lambda: ComfyClient(base, timeout=5),
                              on_done=lambda spec, result: done.append(result))

    first = worker()
    first.submit(_spec("x7", "photo"))
    _wait_until(lambda: _lines(log, "/history/"), timeout=10)       # submitted and polling, held by "hold"
    first.stop()                                                     # the "restart"
    assert first.join(timeout=10)                                    # its thread ENDED: nothing leaks past the test (F13)
    assert done == []                                                # the abandoned job was not handed on
    control.write_text(json.dumps({"script": "ready"}), encoding="utf-8")
    second = worker()
    second.submit(_spec("x7", "photo"))                              # resume resubmits the same spec
    _wait_until(lambda: done, timeout=15)
    second.stop()
    assert second.join(timeout=10)
    assert [r.status for r in done] == ["ready"]                     # exactly one result: the second worker's
    files = list(Path(done[-1].path).parent.glob("x7-*"))
    assert len(files) == 1
    client_ids = [json.loads(line)["client_id"] for line in log.read_text(encoding="utf-8").splitlines()
                  if json.loads(line)["path"] == "/prompt"]
    assert client_ids == ["x7", "x7"]

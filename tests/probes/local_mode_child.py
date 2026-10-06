"""
The child of ``tests/test_local_mode_golden.py::test_local_mode_never_imports_hosting``.

Run in a FRESH interpreter, so ``sys.modules`` holds only what a local-mode
process imports: the launcher's path (``launcher.main([])``, with the scene's
``run_scene`` and the service stack stubbed), then ``create_app(testing=True,
llm_fn=<scripted>)`` -- the real ``FlaskScene.__init__`` and ``DefaultScene``,
where hosting's branch and the CORS choice live -- one scripted turn over HTTP
and one ``join_session`` over the Socket.IO test client. The last line it
prints is JSON: the turn's status, the first event the join answered, and every
loaded ``engine.hosting`` module (there must be none).

Usage: ``python tests/probes/local_mode_child.py <temp dir>``. Everything it
writes goes under that directory: config, saves, the storage root and the
working directory are pinned as the golden pins them (``tests/local_golden.py``), plus the
conftest's model pins, which a child process does not inherit. No socket may
be opened at all: a connect raises.
"""

from __future__ import annotations

import contextlib
import io
import json
import socket
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _no_network() -> None:
    """Refuse every connection: nothing in this child may reach a server."""

    def refuse(self: Any, address: Any) -> None:
        raise AssertionError(f"local_mode_child opened a connection to {address!r}")

    socket.socket.connect = refuse  # type: ignore[method-assign]


def main(argv: list[str]) -> int:
    import pytest

    from tests.local_golden import pinned, scripted_model

    temp = Path(argv[1])
    workdir = temp / "cwd"
    workdir.mkdir(parents=True, exist_ok=True)
    _no_network()

    patch = pytest.MonkeyPatch()
    patch.chdir(workdir)

    # The conftest's model pins (tests/conftest.py::_no_live_model_calls).
    from engine.llm.lmstudio_native import NativeClient
    from engine.llm.ollama import OllamaClient
    from engine.llm.providers import get_provider
    from engine.llm.registry import ModelRegistry
    from engine.persistence import saves
    from engine.scenes import default_state

    patch.setattr(
        ModelRegistry, "_fetch", lambda self, path, body=None: get_provider().empty_model_list()
    )
    patch.setattr(NativeClient, "is_available", lambda self: False)
    patch.setattr(OllamaClient, "is_available", lambda self: False)
    patch.setattr(default_state, "_summarizer_fn", lambda: None)
    # And its saves redirect (tests/conftest.py::_no_test_writes_real_saves).
    patch.setattr(saves, "saves_base", lambda: temp / "saves")
    saves.reset_save_store()

    try:
        with pinned(patch, temp / "config", temp / "data"):
            import launcher
            from engine.scenes import default_scene

            calls: list[dict[str, Any]] = []
            with patch.context() as local:
                local.setattr(default_scene, "run_scene", lambda **kw: calls.append(dict(kw)))
                with contextlib.redirect_stdout(io.StringIO()):
                    code = launcher.main([])
            assert code == 0 and len(calls) == 1, (code, calls)

            default_scene.reset_store()
            scene, app = default_scene.create_app(testing=True, llm_fn=scripted_model)
            client = app.test_client()
            started = client.post("/api/game/new", json={"seed": 7}).get_json()
            session_id = started["session_id"]
            turn = client.post(
                "/api/game/choice", json={"session_id": session_id, "choice_id": "a"}
            )
            sio = scene.socketio.test_client(app)
            sio.emit("join_session", {"session_id": session_id})
            received = sio.get_received()
            sio.disconnect()
    finally:
        patch.undo()
        saves.reset_save_store()

    print(
        json.dumps(
            {
                "turn_status": turn.status_code,
                "joined": received[0]["name"] if received else None,
                "hosting_modules": sorted(m for m in sys.modules if m.startswith("engine.hosting")),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

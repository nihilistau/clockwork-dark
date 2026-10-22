"""
A real hosted worker for the front door's tests (v0.20.0 T12): the engine's
own worker -- ``build_worker_app(llm_fn=<scripted>)`` with hosting on, its bus
connected, served by the boot runner (``engine.hosting.boot.serve_worker``) --
with the model scripted (one fixed reply, never a model server) and a probe
WSGI layer outside everything that the test drives through files in
``CLOCKWORK_FAKE_WORKER_DIR`` (the control directory, as
``tests/probes/fake_worker.py``'s):

- ``<process>-<pid>.json``: written at start (its pid), so the instance's
  orphan check covers this process;
- ``<process>-<pid>.requests``: one line ``METHOD path`` per request that
  carried the front door's ``X-Clockwork-Proxy`` header (any value): what was
  PROXIED to it, the supervisor's health checks left out;
- ``<process>.slow`` holding a path: a request for it writes
  ``<process>.entered`` and then waits until ``<process>.release`` exists
  (at most a minute) before the worker answers it -- the cookie races;
- ``<process>.evil``: while it exists, every response carries ``Set-Cookie:
  clockwork_session=evil``, a worker trying to write the cookie;
- ``GET /probe/redirect`` is answered ``302`` to ``/probe/elsewhere`` (a
  worker's redirect, which the front door must not follow);
- ``<process>.hold``: while it exists, each model call waits (writing
  ``<process>.held``) until it is removed: a turn in flight, its turn lock
  and ticket held (T15);
- ``<process>.crash``: while it exists, the process exits code 3 at its
  start, before it builds anything: a crash loop (T15);
- ``<process>.bloat``: while it exists, the worker's answer to the
  supervisor's ``worker.sessions.list`` is padded past one bus frame (the
  bus answers it ``too_large``; v0.20.0 T15);
- ``<process>-<pid>.llm`` (v0.20.0 T16): JSON, written once the worker is
  built, the ``llm.*`` values it booted with (``LLM_KEYS``), so a test sees
  which admin layer a (re)started worker read (not ``.json``: the instance
  reads every ``*.json`` here as a process report);
- ``<process>.refuse-provider`` holding a provider name (v0.20.0 T16): a
  worker whose config names that provider exits code 4 at its start, before
  it builds anything -- a provider that fails validation at load, injected,
  for the model apply's rollback;
- ``scripted.reply`` (v0.20.0 T17): while it exists, its text is every
  worker's scripted reply (the sentinel test's narration and stat claim);
- ``scripted.voice`` (v0.22.0 T14): in a story declaring ``paths.social``,
  the voicing pass's model is scripted too (``voicer.set_llm_fn``, never a
  model server): each reply is one bubble, this file's text while it exists
  (else "sure"), valid against the call's schema;
- ``<process>.fail`` (v0.20.0 T17): while it exists, a turn raises inside
  ``run_turn`` with the file's text as its message;
- with ``CLOCKWORK_PROBE_BUS_TRACE`` set (v0.20.0 T17), every frame the
  worker sends the supervisor once built, ``hello`` excepted, is appended to
  ``<process>-<pid>.bustrace``;
- with ``CLOCKWORK_PROBE_FORBID_RESET`` set in its environment (v0.20.0
  T16), ``engine.config.reset_config`` and
  ``engine.games.caches.reset_all_caches`` are replaced, once the worker is
  built (its boot may reset), by functions that write
  ``<process>-<pid>.reset`` and raise: a serving process must never reset on
  the model apply's path.

Run as ``python -u -m tests.probes.scripted_worker --role worker`` by the
supervisor (``tests/hosting_instance.py``, ``worker_module=SCRIPTED_WORKER``),
or, where gunicorn runs (v0.20.0 T13), served by gunicorn as
``tests.probes.scripted_worker:app`` (the supervisor's ``--worker-wsgi``):
the module's ``app`` is built on first access, in gunicorn's worker.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

CONTROL_ENV = "CLOCKWORK_FAKE_WORKER_DIR"

#: The scripted model's one reply (tests/hosted_app.py's, copied: this child
#: does not import pytest).
SCRIPTED_REPLY = """```json
{"narration": "Mist clings to the birch trunks.",
 "choices": [{"id": "a", "text": "Walk on"}, {"id": "b", "text": "Wait"}]}
```"""


def scripted_model(_messages: Any, *_args: Any, **_kwargs: Any) -> str:
    _hold_if_asked()
    return _reply()


def _hold_if_asked() -> None:
    """
    While ``<process>.hold`` exists, a model call writes ``<process>.held``
    and waits (at most a minute) until the hold file is gone: a turn in
    flight, holding its turn lock and its narration ticket (v0.20.0 T15).
    Every call waiting is let through at once when the test removes it (a
    turn's agents may call the model in parallel).
    """
    control = os.environ.get(CONTROL_ENV, "")
    name = f"worker-{os.environ.get('CLOCKWORK_GAME', '')}"
    if not control:
        return
    hold = Path(control) / f"{name}.hold"
    if not hold.exists():
        return
    (Path(control) / f"{name}.held").write_text("1", encoding="utf-8")
    deadline = time.monotonic() + 60
    pause = threading.Event()
    while hold.exists() and time.monotonic() < deadline:
        pause.wait(0.02)


class Probe:
    """The probe's WSGI layer, outside the worker's own (see the module docstring)."""

    def __init__(self, app: Callable[..., Iterable[bytes]], name: str, control: Path) -> None:
        self.app = app
        self.name = name
        self.control = control
        self.requests = control / f"{name}-{os.getpid()}.requests"
        self._lock = threading.Lock()

    def _file(self, suffix: str) -> Path:
        return self.control / f"{self.name}.{suffix}"

    def _plant_if_asked(self) -> None:
        """``<process>.plant`` (v0.23.0 T28): JSON of play-text sentinels, planted once through the engine's own
        writers into every live phone run (`plant_play_text`), then removed. Never raises into a request."""
        flag = self._file("plant")
        if not flag.exists():
            return
        with self._lock:
            try:
                words = json.loads(flag.read_text(encoding="utf-8"))
                flag.unlink()
            except (OSError, ValueError):
                return
        try:
            plant_play_text(words)
        except Exception:  # noqa: BLE001 -- the probe never fails a request; the test sees the sentinel missing
            import logging

            logging.getLogger("tests.probes.scripted_worker").exception("plant failed")

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        path = str(environ.get("PATH_INFO", ""))
        if "HTTP_X_CLOCKWORK_PROXY" in environ:
            with self._lock:
                with self.requests.open("a", encoding="utf-8") as handle:
                    handle.write(f"{environ.get('REQUEST_METHOD', '')} {path}\n")
        self._plant_if_asked()
        if path == "/probe/redirect":
            start_response("302 Found", [("Location", "/probe/elsewhere"), ("Content-Length", "0")])
            return [b""]
        slow = self._file("slow")
        try:
            slow_path = slow.read_text(encoding="utf-8").strip()
        except OSError:
            slow_path = ""
        if slow_path and slow_path == path:
            self._file("entered").write_text("1", encoding="utf-8")
            release = self._file("release")
            deadline = time.monotonic() + 60
            pause = threading.Event()
            while not release.exists() and time.monotonic() < deadline:
                pause.wait(0.02)
        if self._file("evil").exists():
            real_start = start_response

            def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> Any:  # type: ignore[no-redef]
                headers = list(headers) + [("Set-Cookie", "clockwork_session=evil; Path=/; HttpOnly")]
                return real_start(status, headers, exc_info)

        return self.app(environ, start_response)


def _bloat_listing(app: Any, name: str, control: Path) -> None:
    """
    While ``<process>.bloat`` exists, this worker's ``worker.sessions.list``
    answer carries rows past one bus frame (v0.20.0 T15), so the bus itself
    must answer it ``too_large``: the panel's error row, the front door up.
    """
    from engine.hosting import BUS_EXTENSION

    client = app.extensions.get(BUS_EXTENSION)
    if client is None:
        return
    real = client._handlers.get("worker.sessions.list")
    if real is None:
        return

    def listing(args: dict[str, Any]) -> Any:
        answer = dict(real(args))
        if (control / f"{name}.bloat").exists():
            answer["rows"] = [{"owner": "u_" + "0" * 12, "session_id": "x" * 64, "save_id": "y" * 64}] * 600
        return answer

    client.handle("worker.sessions.list", listing)


#: The ``llm.*`` values written to ``<process>-<pid>.llm`` (v0.20.0 T16).
LLM_KEYS = ("llm.provider", "llm.profiles.big.temperature", "llm.lanes.narration", "llm.lanes.utility")

#: The environment variable that forbids this process a reset once built.
FORBID_RESET_ENV = "CLOCKWORK_PROBE_FORBID_RESET"


def forbid_resets(control: Path, name: str) -> None:
    """
    Replace ``reset_config`` and ``reset_all_caches`` with functions that
    write ``<name>-<pid>.reset`` and raise (v0.20.0 T16), when
    ``FORBID_RESET_ENV`` is set. Also used by ``frontdoor_relay``.
    """
    if not os.environ.get(FORBID_RESET_ENV):
        return
    import engine.config as config_module
    import engine.games.caches as caches_module

    marker = control / f"{name}-{os.getpid()}.reset"

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        marker.write_text("a serving process reset its config", encoding="utf-8")
        raise RuntimeError("a serving process must not reset its config (v0.20.0 T16)")

    config_module.reset_config = forbidden  # type: ignore[assignment]
    caches_module.reset_all_caches = forbidden  # type: ignore[assignment]


#: The environment variable that records this process's bus frames (v0.20.0 T17).
BUS_TRACE_ENV = "CLOCKWORK_PROBE_BUS_TRACE"


def trace_bus(control: Path, name: str) -> None:
    """
    With ``BUS_TRACE_ENV`` set (v0.20.0 T17), every frame this process sends
    the supervisor from now on -- requests, notifications (``metric``) and
    replies -- is appended to ``<name>-<pid>.bustrace`` as well: what the
    supervisor RECEIVED, read by the sentinel test. A ``hello`` (its token)
    is never written. Also used by ``frontdoor_relay``.
    """
    if not os.environ.get(BUS_TRACE_ENV):
        return
    import engine.hosting.bus as bus_module

    path = control / f"{name}-{os.getpid()}.bustrace"
    lock = threading.Lock()
    real = bus_module.encode

    def encode(message: Any) -> bytes:
        data = real(message)
        if isinstance(message, dict) and message.get("op") == "hello":
            return data
        with lock:
            with path.open("ab") as handle:
                handle.write(data)
        return data

    bus_module.encode = encode  # type: ignore[assignment]


#: A control file whose text, while it exists, is the scripted model's reply
#: (v0.20.0 T17), for every worker: the sentinel test's narration and claim.
REPLY_FILE = "scripted.reply"

#: ``<process>.fail``: while it exists, a turn raises inside ``run_turn``
#: with the file's text as its message (v0.20.0 T17): a turn's failure, which
#: the player sees only by reference.
FAIL_SUFFIX = "fail"


def _reply() -> str:
    control = os.environ.get(CONTROL_ENV, "")
    if control:
        try:
            return (Path(control) / REPLY_FILE).read_text(encoding="utf-8")
        except OSError:
            pass
    return SCRIPTED_REPLY


#: A control file whose text, while it exists, is every scripted phone reply's one bubble (v0.22.0 T14).
VOICE_FILE = "scripted.voice"


def scripted_voice(_messages: Any, fmt: Any) -> str:
    """The voicing pass's scripted model: one bubble (``scripted.voice``'s text), nothing else moved."""
    text = "sure"
    control = os.environ.get(CONTROL_ENV, "")
    if control:
        try:
            text = (Path(control) / VOICE_FILE).read_text(encoding="utf-8").strip() or text
        except OSError:
            pass
    schema = ((fmt or {}).get("json_schema") or {}).get("schema") or {}
    props = schema.get("properties") or {}
    reply: dict[str, Any] = {"bubbles": [{"text": text}], "regard": {"warmth": 0, "trust": 0, "mood": "neutral"},
                             "learned": [], "shared": []}
    if "proposals" in props:
        reply["proposals"] = []
    if "media" in props:
        reply["media"] = {"caption": text}
    return json.dumps(reply)


#: A control file: while it exists, every person of a phone story always reads and replies -- never
#: ghosts, never leaves the player on read (pre-flight F16: a test FORCES the draws it needs instead of
#: hunting for a seed whose course a content change can move; tests/test_admin_no_play_text.py).
ALWAYS_REPLIES = "scripted.always_replies"
#: A control file (v0.22.0 T21 review M7): while it exists, a phone story's people say yes to every media
#: ask the app can carry -- the kind unlocked at any stage, a budget always held, the accept odds 1 -- so
#: a person's voice note (its transcript the scripted voice's line) lands in the save the admin scan reads.
MEDIA_YES = "scripted.media_yes"


def script_the_phone(control: Optional[Path] = None) -> None:
    """
    A phone story's voicing pass voiced by ``scripted_voice`` (absent in any
    other story). With ``control``, while ``<control>/scripted.always_replies``
    exists every archetype's ghost chance is 0 and its reply odds 1 (its
    interest and burst terms pinned to 1), read per decision; and while
    ``scripted.media_yes`` exists every media ask the app can carry is
    accepted (``_media_yes``).
    """
    from engine import social

    if social.declared():
        from engine.social import voicer

        voicer.set_llm_fn(scripted_voice)
        voicer.set_summary_fn(lambda messages: "")   # "" takes the deterministic fallback, no server asked
        if control is not None:
            _always_replies(control / ALWAYS_REPLIES)
            _media_yes(control / MEDIA_YES)


def _always_replies(flag: Path) -> None:
    import dataclasses

    from engine.social import behaviour, convo

    real_archetype = behaviour.archetype
    real_ghost, real_reply = convo._ghost_factor, convo._reply_factor

    def archetype(name: str) -> Any:
        arch = real_archetype(name)
        return dataclasses.replace(arch, ghost_per_episode=0.0, reply_prob=1.0) if flag.exists() else arch

    behaviour.archetype = archetype  # type: ignore[assignment]
    # v0.23.0: the per-episode-start draws (convo, spec §4.6) forced while the flag exists.
    convo._ghost_factor = lambda state, pid: 0.0 if flag.exists() else real_ghost(state, pid)  # type: ignore[assignment]
    convo._reply_factor = lambda state, pid: 100.0 if flag.exists() else real_reply(state, pid)  # type: ignore[assignment]
    # T28: availability and the boundary are the other draws a person's reply (a voice note's too) can fall
    # to ("their voice note never fell due" in a batch run, a person asleep or at work): forced while the flag exists.
    real_available, real_boundary = convo.available, convo.boundary_minutes
    convo.available = lambda state, pid, at: convo.Availability(True) if flag.exists() else real_available(state, pid, at)  # type: ignore[assignment]
    convo.boundary_minutes = lambda state, pid, at: None if flag.exists() else real_boundary(state, pid, at)  # type: ignore[assignment]


def _media_yes(flag: Path) -> None:
    from engine.social import media

    real_unlocked, real_budget, real_accept = media.unlocked, media.budget_of, media.accept_p
    media.unlocked = lambda *a, **k: True if flag.exists() else real_unlocked(*a, **k)  # type: ignore[assignment]
    media.budget_of = lambda *a, **k: 2.0 if flag.exists() else real_budget(*a, **k)  # type: ignore[assignment]
    media.accept_p = lambda *a, **k: 1.0 if flag.exists() else real_accept(*a, **k)  # type: ignore[assignment]


def plant_play_text(words: dict[str, str]) -> None:
    """
    Play text only the engine's own paths write, put into the live READ RECEIPTS run(s) of this worker the way
    play puts it (v0.23.0 T28): a RECAP and a STORY in a person's memory (`memory.add_recap`, `commit_fold`), a
    scene's narration and a CHANCE scene's as `scene` rows in the run's archive (`archive.append`), and a HELD
    text as a landed message that waited while they were together (`messaging.new_message`, the decision's
    `after_together`). Keys: ``recap``, ``story``, ``scene``, ``chance``, ``held``. Each run is saved after.
    """
    from engine import social

    if not social.declared():
        return
    from engine.scenes.default_scene import get_store
    from engine.session.store import release_turn
    from engine.social import archive, memory, messaging, saves

    pause = threading.Event()
    for session in get_store().live_sessions():
        state = session.engine.state
        if not (state.social or {}).get("threads"):
            continue
        for _ in range(200):
            if session.lock.acquire(blocking=False):
                break
            pause.wait(0.05)
        else:
            continue
        try:
            tid = next(iter(state.social["threads"]))
            pid = str(state.social["threads"][tid]["pid"])
            row = {"kind": "chat", "where": "", "topics": [], "end_reason": "", "from_at": 0.0, "to_at": 0.1}
            memory.add_recap(state, pid, {**row, "id": "plant-0", "recap": "an earlier evening"})
            memory.add_recap(state, pid, {**row, "id": "plant-1", "recap": words["recap"]})
            oldest = memory.person(state, pid)["episodes"][0]
            memory.commit_fold(state, {"pid": pid, "episode": {"id": oldest["id"]},
                                       "story": str(memory.person(state, pid)["story"] or "")}, words["story"])
            messaging.new_message(state, tid, pid, "text", at=float(state.world_clock_hours),
                                  bubbles=[words["held"]], voiced=True, decision={"after_together": True})
            directory = archive.save_dir(session)
            number = 9000
            for kind, text in (("scene", words["scene"]), ("chance", words["chance"])):
                number += 1
                archive.append(directory, [{"id": f"m{number}", "thread_id": tid, "from": "system", "kind": "scene",
                                            "pid": pid, "at": round(float(state.world_clock_hours), 4),
                                            "bubbles": [text], "scene": kind}], kind="scene")
            saves.mark_dirty(session, "action")
            saves.save_now(session)
        finally:
            release_turn(session)


def fail_when_asked(control: Path, name: str) -> None:
    """``default_scene.run_turn`` wrapped: it raises while ``<name>.fail`` exists."""
    from engine.scenes import default_scene

    real = default_scene.run_turn

    def run_turn(*args: Any, **kwargs: Any) -> Any:
        try:
            words = (control / f"{name}.{FAIL_SUFFIX}").read_text(encoding="utf-8")
        except OSError:
            return real(*args, **kwargs)
        failure = RuntimeError(words)
        # Also an ERROR record of its own whose MESSAGE carries the words
        # (T17 fix round 1, M7): the child's ERROR handler, not only
        # public_error, sees play text and must keep none of it.
        import logging

        logging.getLogger("tests.probes.scripted_worker").error(
            "a scripted failure: %s", words, exc_info=(RuntimeError, failure, None)
        )
        raise failure

    default_scene.run_turn = run_turn  # type: ignore[assignment]


def _llm_report(control: Path, name: str) -> None:
    from engine.config import get_config

    cfg = get_config()
    values = {key: cfg.get(key) for key in LLM_KEYS}
    (control / f"{name}-{os.getpid()}.llm").write_text(json.dumps(values), encoding="utf-8")


def _refused_provider(control: Path, name: str) -> None:
    """Exit 4 at the start when ``<name>.refuse-provider`` names the configured provider."""
    try:
        refused = (control / f"{name}.refuse-provider").read_text(encoding="utf-8").strip()
    except OSError:
        return
    if not refused:
        return
    from engine.config import get_config

    if str(get_config().get("llm.provider") or "") == refused:
        print(f"probe: refusing to start under llm.provider {refused}", flush=True)
        os._exit(4)


def _builder() -> Callable[[], tuple[Any, Any]]:
    """Write this process's report and return the build (the worker, scripted, under the probe)."""
    from engine.hosting.boot import build_worker_app, configure_logging

    configure_logging()
    slug = os.environ.get("CLOCKWORK_GAME", "")
    name = f"worker-{slug}"
    control = Path(os.environ[CONTROL_ENV])
    report = control / f"{name}-{os.getpid()}.json"
    from tests.process_identity import report as identity_report

    report.write_text(json.dumps(identity_report()), encoding="utf-8")
    if (control / f"{name}.crash").exists():
        os._exit(3)  # a crash loop, on request (v0.20.0 T15)
    _refused_provider(control, name)  # v0.20.0 T16

    def build() -> tuple[Any, Any]:
        scene, app = build_worker_app(llm_fn=scripted_model)
        app.wsgi_app = Probe(app.wsgi_app, name, control)
        _bloat_listing(app, name, control)
        _llm_report(control, name)
        forbid_resets(control, name)
        fail_when_asked(control, name)  # v0.20.0 T17
        script_the_phone(control)  # v0.22.0 T14; the draws pinned on request (T19)
        trace_bus(control, name)  # v0.20.0 T17
        return scene, app

    return build


def main(argv: list[str]) -> int:
    from engine.hosting.boot import prepare_child, serve_worker

    prepare_child()
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["worker"], required=True)
    parser.parse_args(argv)
    return serve_worker(_builder())


#: The app gunicorn serves (``tests.probes.scripted_worker:app``, the
#: supervisor's ``--worker-wsgi``; v0.20.0 T13), built on first access in
#: gunicorn's worker, the same steps as ``main`` bar the server.
_APP: list[Any] = []


def __getattr__(name: str) -> Any:
    if name != "app":
        raise AttributeError(name)
    if not _APP:
        from engine.hosting.boot import prepare_child

        prepare_child()
        _scene, app = _builder()()
        _APP.append(app)
    return _APP[0]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

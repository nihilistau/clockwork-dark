"""
The local-mode golden: the whole surface a local player's process shows.

WHY IT EXISTS. v0.20.0 adds Linux and a hosted, multi-user mode, and its first
invariant is that neither changes the game a local, single-player owner gets.
"Unchanged" has to be a thing a test can check, so this module captures, from
the untouched v0.19.0 code (e7fdd26), everything local mode shows -- the app's
shape, the page, two stories played at a fixed seed over HTTP and Socket.IO,
the saves those runs wrote, the catalogue and settings routes and the
launcher -- and ``tests/test_local_mode_golden.py`` replays it and compares it
with ``tests/fixtures/local_mode/``. The fixtures are recorded ONCE; a later
change that needs one re-recorded has found a regression, or a spec decision
to take back to the owner (the plan's Global Constraints, spec §1). The runner
may follow a seam a later task renames; the fixtures may not move.

WHAT IS PINNED, so the capture is the same on every machine:

  * CONFIG, through the real layers: ``engine.config._instance`` reset,
    ``_CONFIG_DIR`` a temp directory holding no file, ``_DEFAULT_PATH`` the
    repository's real ``config/default.yaml``, and ``ENV_KEYS`` deleted from
    the environment. The Settings panel's own read of ``config/local.yaml``
    (``engine.api.settings._read_local``, which reads past ``_CONFIG_DIR``)
    runs for real, with ``project_root`` moved for that call only to the temp
    directory whose ``config/`` is the pinned ``_CONFIG_DIR``: the owner's
    own file never reaches a row's ``overridden``.
  * THE MODEL: ``create_app(llm_fn=scripted_model)``, one fixed reply. The
    conftest guards stay up: nothing reaches a model server.
  * SAVES, under the conftest's redirect of ``saves.saves_base`` (a per-test
    temp directory), never ``data/saves``. The save BASE is captured apart,
    from the real resolver (kept here at import, before any redirect).
  * THE STREAMED TURNS (``stream_turn``, both stories): no ``llm_fn``; every
    request answered by ``tests/llm_wire.py`` from ``STREAMED_STORIES``, with
    discovery through the wire (warmed first for HUE & CRY, whose planners
    run concurrently) and ``time.perf_counter`` frozen.
  * THE WORLD TICK: ``WorldSim.realtime_tick_hours`` sees zero real seconds
    elapsed after the forced first tick, so wall-clock time between turns
    moves nothing.
  * THE STORAGE ROOT: ``CLOCKWORK_DATA_DIR`` is a temp directory for the
    capture (unset for ``save_base``, which pins the default), because
    generated media is written under, and its cache read from, the root's
    ``media/`` (``capture``). THE WORKING DIRECTORY is an empty temp directory
    too: on e7fdd26 that media directory was cwd-relative.
  * THE LORE INDEX: empty (``engine.lore.manager._default_db_path`` answers
    ``MEMORY_DB``); the gitignored ``lore.db`` one machine has is not the
    golden's.
  * SPEECH: ``engine.media.stt.get_stt_provider`` answers a stub, so
    faster-whisper is never loaded (it can download a model).
  * THE STACK: ``engine.stack.probe_service`` answers ``STACK_PROBES`` and
    ``ServiceSpec.resolved_command`` answers None; ``StackManager.start`` and
    ``stop_all`` are stubbed and recorded. Nothing is probed, nothing started.
  * VALUES THAT CANNOT REPEAT: every ``session_id``, ``save_id`` and media
    ``job_id`` becomes ``<session-N>`` / ``<save-N>`` / ``<job-N>`` wherever
    it recurs (inside other strings and file names included), and every
    timestamp ``<time>`` (``Normaliser``).

RECORDING (on e7fdd26 code only)::

    .venv\\Scripts\\python.exe -m tests.local_golden record

It runs the golden test under pytest with ``RECORD_ENV`` set, so every
conftest guard is up while the fixtures are written, and refuses to overwrite
a recording unless given ``--overwrite``.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest

from engine.llm.registry import ModelRegistry
from engine.persistence import saves as _saves
from engine.world.world_sim import WorldSim
from tests import llm_golden as _llm_golden
from tests.llm_wire import wire

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "local_mode"

#: Set (to "1") to make the golden test WRITE the fixtures instead of
#: comparing them. Only ``record()`` sets it.
RECORD_ENV = "CLOCKWORK_LOCAL_GOLDEN_RECORD"
#: Set with ``RECORD_ENV`` to let a recording replace an existing one.
OVERWRITE_ENV = "CLOCKWORK_LOCAL_GOLDEN_OVERWRITE"

#: Removed from the environment for the whole capture (spec §1): the LM Studio
#: golden's own list (shared, so a key added there reaches both harnesses),
#: plus the operator config file and the data directory. Those two do not
#: exist on e7fdd26; stripping them from the start means the owner's shell can
#: never leak into a later run.
ENV_KEYS = _llm_golden.ENV_KEYS + ("CLOCKWORK_CONFIG", "CLOCKWORK_DATA_DIR")
#: Also removed: per-invocation choices the launcher or the owner's shell can
#: set, each of which would change what is served (the story, the studio).
INVOCATION_KEYS = ("CLOCKWORK_GAME", "CLOCKWORK_STUDIO")
#: Also removed: the supervisor's bus variables (v0.20.0 T10, spec §14.1),
#: which only a child of a hosted supervisor is given. Local mode reads none
#: of them; stripped so a shell that has one can never reach the capture.
BUS_KEYS = (
    "CLOCKWORK_BUS_ADDR",
    "CLOCKWORK_BUS_TOKEN",
    "CLOCKWORK_BUS_ROLE",
    "CLOCKWORK_PROXY_TOKEN",
)

#: The two stories played: the flagship, and the one v0.20.0's hosting targets.
STORIES = ("clockwork-dark", "hue-and-cry")
SEED = 20260930

#: The one plate served through ``/story-art/<path>`` (the flagship's tree).
PLATE = "scenes/bakery.jpg"

#: The scripted model's only reply.
SCRIPTED_REPLY = json.dumps(
    {
        "narration": "The lamps gutter and steady. Nothing in the street moves "
        "that was not moving before.",
        "choices": [
            {"id": "a", "text": "Wait and watch the street"},
            {"id": "b", "text": "Look about you"},
        ],
    }
)

#: What the stubbed stack probe answers, per service. Anything not named is
#: down. The model server is up, so ``--check`` exits 0.
STACK_PROBES = {
    "lmstudio": (True, "golden: up"),
    "llm": (True, "golden: up"),
    "voxtral_tts": (False, "golden: down"),
    "comfyui": (False, "golden: down"),
}

#: The stubbed speech provider's answers.
STT_TRANSCRIPT = "look about you"
STT_FAILURE = RuntimeError("the transcription service answered 503")
STT_FAILURE_RAW = {"error": {"code": 503, "message": "model is loading"}}

#: The real save-base resolver, kept before any fixture can redirect it
#: (``tests/conftest.py::_no_test_writes_real_saves`` replaces the module
#: attribute for every test). Fails if this module is first imported inside a
#: test body: import it at module level.
_REAL_SAVES_BASE = _saves.saves_base
assert _REAL_SAVES_BASE.__name__ == "saves_base", "imported under the saves redirect"

#: Model discovery's real request, kept before the conftest pins it to an
#: empty list: the streamed turn (``stream_turn``) discovers through the wire.
_REAL_FETCH = ModelRegistry.__dict__["_fetch"]
assert _REAL_FETCH.__name__ == "_fetch", "imported under the discovery pin"

#: The stories whose socket turn is also played through the real model path,
#: and how.
#:
#: The flagship's turn asks the server three things, one after the other:
#: discovery, the structured-output probe, the storyteller's stream. It runs
#: cold, exactly as a player's first turn does.
#:
#: HUE & CRY's turn first runs its agents' plans CONCURRENTLY
#: (`engine/agents/pipeline.py::_gather`, a thread pool). Cold, each planner
#: thread can run discovery itself (`ModelRegistry.models` checks `_models`
#: outside its lock, so one or two discovery GETs, by timing), and the plans
#: reach an in-order answer list in no fixed order. `tests/llm_wire.py` is not
#: changed; instead (the reviewer's recipe): discovery and the probe are
#: WARMED by the harness before the turn (`warm: True`), so they are one
#: ordered pair up front; every planner POST gets the SAME canned plan -- they
#: share a URL, so arrival order no longer matters to an answer or to the
#: recorded request lines -- and the storyteller's stream comes after the pool
#: joins, so it is always last. The outcome was already order-independent:
#: `_gather` collects in spec order.
_STREAM = _llm_golden._compat_sse(_llm_golden.ENVELOPE, reasoning=_llm_golden.REASONING)
_PLAN = _llm_golden._compat_json(_llm_golden.PLAN, model=_llm_golden.UTILITY, reasoning_tokens=0)

#: What the model server answers, in order (v0.19.0's LM Studio golden's own
#: canned answers, `tests/llm_golden.py`: scenario 01's stream -- reasoning
#: deltas, then the envelope in content deltas -- and its plan).
STREAMED_STORIES: dict[str, dict[str, Any]] = {
    "clockwork-dark": {
        "warm": False,
        "answers": (_llm_golden._models(), _llm_golden.PROBE_YES, _STREAM),
    },
    "hue-and-cry": {
        "warm": True,
        # discovery and the probe (warmed), one plan per planning agent, the stream
        "answers": (_llm_golden._models(), _llm_golden.PROBE_YES, _PLAN, _PLAN, _STREAM),
    },
}


def scripted_model(messages: Any, *args: Any, **kwargs: Any) -> str:
    """Every agent call gets the same reply; nothing reaches a model server."""
    return SCRIPTED_REPLY


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------

#: Keys whose value is an id minted afresh each run (uuid-derived), and the
#: placeholder kind each becomes. `job_id` is the media queue's.
_ID_KINDS = {"session_id": "session", "save_id": "save", "job_id": "job"}

#: ISO-8601 date-times, with or without a zone or fraction.
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
#: Keys whose value is a wall-clock time: the ones the recording actually
#: holds, plus the save index's `saved_at`. Deliberately not a generic list
#: (`ts`, `timestamp`, ...): a new wall-clock key must fail loudly, and a
#: deterministic value a later change files under a generic name must not be
#: blanked.
_TIME_KEYS = frozenset({"saved_at", "created_at", "updated_at", "last_sim_tick_at"})


class Normaliser:
    """
    Stable placeholders for values that cannot repeat between runs.

    One instance for a whole capture, so the same id gets the same placeholder
    in every fixture it reaches. Ids are learned from ``session_id`` and
    ``save_id`` keys wherever they appear, in the order the capture meets
    them, then replaced wherever they recur, inside any string or key.
    """

    def __init__(self) -> None:
        self.ids: dict[str, str] = {}
        self._counts = {kind: 0 for kind in _ID_KINDS.values()}

    def learn(self, value: Any) -> None:
        """Register every ``session_id`` / ``save_id`` value under ``value``."""
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _ID_KINDS and isinstance(item, str) and item:
                    self.register(item, _ID_KINDS[key])
                self.learn(item)
        elif isinstance(value, list):
            for item in value:
                self.learn(item)

    def register(self, raw: str, kind: str) -> str:
        if raw not in self.ids:
            self._counts[kind] += 1
            self.ids[raw] = f"<{kind}-{self._counts[kind]}>"
        return self.ids[raw]

    def text(self, value: str) -> str:
        for raw in sorted(self.ids, key=len, reverse=True):
            if raw in value:
                value = value.replace(raw, self.ids[raw])
        return _ISO.sub("<time>", value)

    def __call__(self, value: Any, key: str = "") -> Any:
        """``value`` with every learned id and every timestamp replaced."""
        if key in _TIME_KEYS and isinstance(value, (int, float, str)) and value:
            return "<time>"
        if isinstance(value, dict):
            return {self.text(str(k)): self(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, str):
            return self.text(value)
        return value


def dump_json(value: Any) -> str:
    """How every JSON fixture is written: sorted, indented, LF, one newline."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Pinning
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def pinned(
    patch: pytest.MonkeyPatch, config_dir: Path, data_dir: Optional[Path] = None
) -> Iterator[list[Any]]:
    """
    The config, speech and stack pins of the module docstring, on ``patch``.

    ``data_dir``, when given, is the storage root for everything run inside
    (``CLOCKWORK_DATA_DIR``, the production seam since v0.20.0 T3): generated
    media lands there, never under the repository's ``data/``.

    Yields the list the stubbed stack records its start and stop calls in.
    The caller owns ``patch`` and undoes it; the config singleton is reset on
    the way in and out, so no cache outlives the capture.
    """
    import engine.config as config
    from engine.api import settings
    from engine.lore import manager as lore_manager
    from engine.media import stt
    from engine.stack import ServiceSpec, StackManager
    import engine.stack as stack

    config_dir.mkdir(parents=True, exist_ok=True)
    for name in ENV_KEYS + INVOCATION_KEYS + BUS_KEYS:
        patch.delenv(name, raising=False)
    if data_dir is not None:
        patch.setenv("CLOCKWORK_DATA_DIR", str(data_dir))
    patch.setattr(config, "_CONFIG_DIR", config_dir)
    patch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    patch.setattr(config, "_overlay", {})
    patch.setattr(config, "_instance", None)
    # The Settings panel reads `project_root()/config/local.yaml` itself,
    # past `_CONFIG_DIR`. The REAL reader runs, with `project_root` answering
    # the temp directory whose `config/` IS the pinned `_CONFIG_DIR` -- so it
    # reads the same (absent) local.yaml the config layers read, and
    # `config_path` in the payload is untouched. Only `_read_local` sees the
    # moved root; a change to where Settings reads (§2.1) runs for real here.
    real_read_local = settings._read_local
    assert config_dir.name == "config", config_dir

    def read_local_beside_the_pinned_config() -> Any:
        with pytest.MonkeyPatch.context() as moved:
            moved.setattr(config, "project_root", lambda: config_dir.parent)
            return real_read_local()

    patch.setattr(settings, "_read_local", read_local_beside_the_pinned_config)
    # The wall-clock world tick (`default_state._background_tick`): on e7fdd26
    # it grants in-game hours for REAL seconds elapsed since the last turn
    # (`world.tick_interval_seconds`), so a slow machine, a loaded CI runner
    # or a breakpoint would move every turn fixture. Pinned to zero elapsed;
    # the forced first tick (`last_tick_at <= 0`) still runs as it does.
    real_tick = WorldSim.__dict__["realtime_tick_hours"].__func__

    def no_real_time_passes(last_tick_at: float, *, now: Optional[float] = None) -> float:
        if last_tick_at > 0:
            return real_tick(last_tick_at, now=last_tick_at)
        return real_tick(last_tick_at, now=now)

    patch.setattr(WorldSim, "realtime_tick_hours", staticmethod(no_real_time_passes))
    # The lore index is a gitignored build product (scripts/seed_lore.py) that
    # one machine has and another does not, and its chunks reach the prompts
    # and the evaluator. Pinned empty, as a machine that never seeded it.
    patch.setattr(lore_manager, "_default_db_path", lambda: lore_manager.MEMORY_DB)
    patch.setattr(stt, "get_stt_provider", lambda: _SttStub(fail=False))

    stack_calls: list[Any] = []
    patch.setattr(
        stack,
        "probe_service",
        lambda spec, **_kw: STACK_PROBES.get(spec.name, (False, "golden: down")),
    )
    patch.setattr(ServiceSpec, "resolved_command", lambda self: None)

    def start(self: Any, spec: Any) -> Any:
        stack_calls.append(["start", spec.name])
        return stack.ServiceStatus(spec.name, stack.STATUS_DISABLED, "golden: not started")

    def stop_all(self: Any) -> None:
        stack_calls.append(["stop_all"])

    patch.setattr(StackManager, "start", start)
    patch.setattr(StackManager, "stop_all", stop_all)
    config.reset_config()
    try:
        yield stack_calls
    finally:
        config.reset_config()


class _SttStub:
    """A speech provider that answers a fixed transcript, or a fixed failure."""

    name = "golden_stub"

    def __init__(self, *, fail: bool) -> None:
        self.fail = fail

    def transcribe(self, audio_bytes: bytes, **_kw: Any) -> dict[str, Any]:
        if not self.fail:
            return {
                "success": True,
                "transcript": STT_TRANSCRIPT,
                "source": "live",
                "provider": self.name,
            }
        try:
            raise STT_FAILURE
        except RuntimeError as exc:
            return {
                "success": False,
                "transcript": "",
                "source": "stub",
                "provider": self.name,
                "message": str(exc),
                "raw": STT_FAILURE_RAW,
            }


def wav_bytes() -> bytes:
    """A tenth of a second of 8 kHz mono silence: the same bytes everywhere."""
    out = io.BytesIO()
    with wave.open(out, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(8000)
        clip.writeframes(struct.pack("<800h", *([0] * 800)))
    return out.getvalue()


# ---------------------------------------------------------------------------
# Capturing
# ---------------------------------------------------------------------------


def _fn_names(funcs: dict[Any, list[Callable[..., Any]]]) -> dict[str, list[str]]:
    return {
        str(scope): [f"{f.__module__}.{f.__qualname__}" for f in fs]
        for scope, fs in sorted(funcs.items(), key=lambda kv: str(kv[0]))
    }


def app_shape(scene: Any, patch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The URL map, the request hooks, the Socket.IO door and ``run``'s kwargs."""
    import flask_socketio

    from engine.scenes import default_scene

    app = scene.app
    rules = sorted(
        [rule.rule, sorted(rule.methods or ()), rule.endpoint] for rule in app.url_map.iter_rules()
    )
    handlers = {
        str(namespace): sorted(events)
        for namespace, events in sorted(scene.socketio.server.handlers.items())
    }
    runs: list[dict[str, Any]] = []

    def fake_run(self: Any, app_: Any, **kwargs: Any) -> None:
        runs.append(dict(kwargs))

    with patch.context() as local:
        local.setattr(flask_socketio.SocketIO, "run", fake_run)
        default_scene.run_scene()
    assert len(runs) == 1, runs
    # The config surface is read off the app `run_scene()` itself built -- the
    # one a local owner's process serves (testing off) -- not the test app.
    served = default_scene._scene
    assert served is not None and served is not scene
    eio = served.socketio.server.eio
    # Its headers too: a header added only outside testing must show.
    client = served.app.test_client()
    return {
        "url_map": rules,
        "before_request": _fn_names(app.before_request_funcs),
        "after_request": _fn_names(app.after_request_funcs),
        "socketio": {
            "cors_allowed_origins": scene.socketio.server_options.get("cors_allowed_origins"),
            "async_mode": scene.socketio.server_options.get("async_mode"),
            # Everything the SocketIO constructor was given, and the limits
            # the Engine.IO server actually runs with: hosted mode's input
            # caps and pings (§6.5) must not reach local mode unseen.
            "server_options": {
                str(k): _json_safe(v) for k, v in sorted(served.socketio.server_options.items())
            },
            "engineio": {
                name: _json_safe(getattr(eio, name, "<absent>"))
                for name in ENGINEIO_ATTRIBUTES
            },
        },
        # The Flask config a hosted login and its limits would set (§6.2,
        # §6.5). SECRET_KEY as whether it is set, never its value.
        "app_config": {
            **{key: _json_safe(served.app.config.get(key)) for key in APP_CONFIG_KEYS},
            "SECRET_KEY is set": served.app.config.get("SECRET_KEY") is not None,
        },
        # A stray Set-Cookie or CORS header on a local answer shows here.
        # Date moves; GET /'s Content-Length follows the checkout's line
        # endings (the body is compared CRLF-folded, see `capture`).
        "response_headers": {
            "/": _headers(client.get("/"), drop=("Date", "Content-Length")),
            "/api/health": _headers(client.get("/api/health"), drop=("Date",)),
        },
        "socketio_handlers": handlers,
        "run_kwargs": runs[0],
    }


#: The Engine.IO server attributes recorded in `app_shape.json`.
ENGINEIO_ATTRIBUTES = (
    "max_http_buffer_size",
    "ping_interval",
    "ping_interval_grace_period",
    "ping_timeout",
    "cors_allowed_origins",
    "cors_credentials",
    "allow_upgrades",
    "http_compression",
    "compression_threshold",
    "cookie",
    "transports",
    "async_mode",
)

#: The Flask config keys recorded in `app_shape.json`.
APP_CONFIG_KEYS = (
    "MAX_CONTENT_LENGTH",
    "MAX_FORM_MEMORY_SIZE",
    "MAX_FORM_PARTS",
    "PERMANENT_SESSION_LIFETIME",
    "SESSION_COOKIE_NAME",
    "SESSION_COOKIE_DOMAIN",
    "SESSION_COOKIE_PATH",
    "SESSION_COOKIE_HTTPONLY",
    "SESSION_COOKIE_SECURE",
    "SESSION_COOKIE_PARTITIONED",
    "SESSION_COOKIE_SAMESITE",
    "SESSION_REFRESH_EACH_REQUEST",
    "SERVER_NAME",
    "PREFERRED_URL_SCHEME",
    "TRUSTED_HOSTS",
    "TESTING",
    "DEBUG",
    "PROPAGATE_EXCEPTIONS",
)


def _json_safe(value: Any) -> Any:
    """A value as JSON can hold it: itself, or a stable description."""
    import datetime

    if isinstance(value, datetime.timedelta):
        return {"timedelta_seconds": value.total_seconds()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        kind = value if isinstance(value, type) else type(value)
        return f"<{kind.__module__}.{kind.__qualname__}>"


def _headers(response: Any, *, drop: tuple[str, ...]) -> list[list[str]]:
    """A response's headers, in order, less the ones named."""
    lowered = {d.lower() for d in drop}
    out = [[k, v] for k, v in response.headers.items() if k.lower() not in lowered]
    response.close()
    return out


def _http(response: Any) -> dict[str, Any]:
    """An HTTP answer as a fixture records it: status, and its JSON body."""
    return {"status": response.status_code, "json": response.get_json(silent=True)}


def _first_choice(turn: Optional[dict[str, Any]]) -> str:
    choices = (turn or {}).get("choices") or []
    return str(choices[0].get("id", "")) if choices else ""


def _socket_events(received: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": item.get("name"), "args": item.get("args"), "namespace": item.get("namespace")}
        for item in received
    ]


def play_story(slug: str, norm: Normaliser, patch: pytest.MonkeyPatch) -> dict[str, Any]:
    """
    One story, at ``SEED``, with the scripted model: everything spec §1 lists
    under "for the flagship and HUE & CRY", as ``{fixture name: value}``
    (values not yet normalised; ids are learned as they appear).
    """
    from engine.games import registry
    from engine.media import stt
    from engine.scenes.default_scene import create_app, reset_store

    registry.activate(slug)
    _saves.reset_save_store()
    reset_store()
    scene, app = create_app(testing=True, llm_fn=scripted_model)
    client = app.test_client()
    out: dict[str, Any] = {}

    def keep(name: str, value: Any) -> Any:
        norm.learn(value)
        out[name] = value
        return value

    new = keep("new_game", _http(client.post("/api/game/new", json={"seed": SEED})))
    session_id = new["json"]["session_id"]
    last = (new["json"] or {}).get("opening")

    turns = []
    for _ in range(2):
        answer = _http(
            client.post(
                "/api/game/choice",
                json={"session_id": session_id, "choice_id": _first_choice(last)},
            )
        )
        turns.append(answer)
        last = answer["json"]
    keep("http_turns", turns)

    sio = scene.socketio.test_client(app)
    keep(
        "socket_connect",
        {"connected": sio.is_connected(), "events": _socket_events(sio.get_received())},
    )
    sio.emit("join_session", {"session_id": session_id})
    keep("join_live", _socket_events(sio.get_received()))
    sio.emit("join_session", {"session_id": "no-such-session"})
    keep("join_unknown", _socket_events(sio.get_received()))

    socket_turns = []
    for _ in range(2):
        sio.emit("player_choice", {"session_id": session_id, "choice_id": _first_choice(last)})
        events = _socket_events(sio.get_received())
        socket_turns.append(events)
        finals = [e["args"][0] for e in events if e["name"] == "turn_update" and e["args"]]
        if finals:
            last = finals[-1]
    keep("socket_turns", socket_turns)

    keep("state", _http(client.get("/api/game/state", query_string={"session_id": session_id})))

    written = keep("save_write", _http(client.post("/api/saves", json={"session_id": session_id})))
    save_id = (written["json"] or {}).get("save_id", "")
    keep("save_list", _http(client.get("/api/saves")))
    keep("save_load", _http(client.post(f"/api/saves/{save_id}/load")))
    sio.emit("resume", {"save_id": save_id})
    keep("socket_resume", _socket_events(sio.get_received()))

    routes: dict[str, Any] = {}
    for rule in STORY_ROUTES:
        routes[f"{rule}?session_id"] = _http(
            client.get(rule, query_string={"session_id": session_id})
        )
        if rule in OPTIONAL_SESSION_ROUTES:
            routes[rule] = _http(client.get(rule))
    keep("story_routes", routes)

    voice = {}
    for label, fail in (("transcript", False), ("failure", True)):
        with patch.context() as local:
            local.setattr(stt, "get_stt_provider", lambda fail=fail: _SttStub(fail=fail))
            voice[label] = _http(
                client.post(
                    "/api/voice/transcribe",
                    data={
                        "session_id": session_id,
                        "transcribe_only": "1",
                        "audio": (io.BytesIO(wav_bytes()), "clip.wav"),
                    },
                    content_type="multipart/form-data",
                )
            )
    keep("voice", voice)

    keep("save_delete", _http(client.delete(f"/api/saves/{save_id}")))
    sio.disconnect()
    return out


def stream_turn(slug: str, patch: pytest.MonkeyPatch) -> dict[str, Any]:
    """
    One socket turn through the REAL model path, as a local player gets it.

    The scripted ``llm_fn`` hands the storyteller its whole reply at once, so
    the turns in ``play_story`` each emit a single ``narration_delta``. Here
    the app is built with no ``llm_fn``: the storyteller streams through
    ``backend.chat_stream`` (reasoning channel, tag buffer, many deltas), and
    ``tests/llm_wire.py`` answers every request from the story's
    ``STREAMED_STORIES`` answers, all of which must be asked for. Discovery
    goes through the wire too (``_REAL_FETCH``), warmed first where the story
    says so; the native route stays the conftest's "unavailable", so the
    stream is the compatible one. ``time.perf_counter`` is frozen, as the LM
    Studio golden freezes it, so no latency moves a fixture.
    """
    import time

    from engine.games import registry
    from engine.llm.client import reset_lms_client
    from engine.config import reset_config
    from engine.scenes.default_scene import create_app, reset_store

    plan = STREAMED_STORIES[slug]
    registry.activate(slug)
    _saves.reset_save_store()
    reset_store()
    scene, app = create_app(testing=True)
    out: dict[str, Any] = {}
    with patch.context() as local:
        local.setattr(ModelRegistry, "_fetch", _REAL_FETCH)
        local.setattr(time, "perf_counter", lambda: 1000.0)
        reset_config()
        reset_lms_client()
        try:
            with wire([dict(a) for a in plan["answers"]], exhaust=True) as seam:
                client = app.test_client()
                new = _http(client.post("/api/game/new", json={"seed": SEED}))
                session_id = new["json"]["session_id"]
                sio = scene.socketio.test_client(app)
                sio.emit("join_session", {"session_id": session_id})
                sio.get_received()
                if plan["warm"]:
                    _warm_discovery_and_probe()
                sio.emit(
                    "player_choice",
                    {"session_id": session_id, "choice_id": _first_choice(new["json"]["opening"])},
                )
                out["events"] = _socket_events(sio.get_received())
                sio.disconnect()
            out["requests"] = [f"{r['method']} {r['url']}" for r in seam.requests]
        finally:
            reset_config()
            reset_lms_client()
    out["new_game"] = new
    return out


def _warm_discovery_and_probe() -> None:
    """
    Model discovery, then the structured-output probe, asked by the harness
    before a turn whose planners would otherwise race to ask them
    (``STREAMED_STORIES``). Both are cached for the process, as the first
    turn of a long-running local server leaves them.
    """
    from engine.llm.backend import get_backend
    from engine.llm.registry import get_registry

    assert get_registry().models(), "discovery found no models"
    assert get_backend().structured_output(
        {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    ), "the structured-output probe did not answer yes"


#: The story blueprint's nine routes (engine/scenes/default_api.py).
STORY_ROUTES = (
    "/api/quests",
    "/api/codex/places",
    "/api/codex/souls",
    "/api/codex/things",
    "/api/items",
    "/api/recipes",
    "/api/trade",
    "/api/notices",
    "/api/clues",
)
#: The five that take an optional session (``_optional_session``).
OPTIONAL_SESSION_ROUTES = frozenset(
    {"/api/codex/places", "/api/codex/souls", "/api/codex/things", "/api/items", "/api/recipes"}
)


def save_tree(slug: str, norm: Normaliser) -> dict[str, Any]:
    """Every file under the story's save namespace: relative path -> content."""
    root = _saves.saves_root(slug)
    files: dict[str, Any] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        if path.suffix == ".jsonl":
            content: Any = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
        else:
            # `.json`, and a `.json.bak` (the previous save, kept beside it):
            # parsed, so its timestamps and ids normalise like the save's.
            try:
                content = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                content = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        norm.learn(content)
        files[rel] = content
    return {rel: norm(value) for rel, value in norm({"_": files})["_"].items()}


def save_base(patch: pytest.MonkeyPatch) -> dict[str, str]:
    """
    Where each story's saves would go, relative to ``project_root()``: the real
    resolver, from the repository root, with no migration run and nothing
    written -- and with no ``CLOCKWORK_DATA_DIR``, so it is the DEFAULT
    storage root's layout that is pinned (v0.20.0 T3: the resolver is
    ``saves.saves_base`` -> ``storage.saves_dir("", None)``).
    """
    from engine.config import project_root

    root = project_root()
    out = {}
    with patch.context() as local:
        local.delenv("CLOCKWORK_DATA_DIR", raising=False)
        local.chdir(root)
        local.setattr(_saves, "saves_base", _REAL_SAVES_BASE)
        local.setattr(_saves, "_migrated", set(_saves._migrated) | set(STORIES))
        base = Path(os.path.abspath(_saves.saves_base()))
        out["saves_base"] = base.relative_to(root).as_posix()
        for slug in STORIES:
            where = Path(os.path.abspath(_saves.saves_root(slug)))
            out[slug] = where.relative_to(root).as_posix()
    return out


def launcher_runs(patch: pytest.MonkeyPatch, stack_calls: list[Any]) -> dict[str, str]:
    """
    ``launcher.main(["--check"])`` and ``launcher.main([])``, under ``pinned``'s
    stack stubs (``stack_calls`` is the list they record into).
    """
    import launcher
    from engine.scenes import default_scene

    out: dict[str, str] = {}

    stack_calls.clear()
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        code = launcher.main(["--check"])
    out["launcher_check.txt"] = (
        text.getvalue()
        + f"--- exit {code}\n"
        + f"--- stack calls {json.dumps(stack_calls)}\n"
    )

    stack_calls.clear()
    calls: list[dict[str, Any]] = []
    text = io.StringIO()
    with patch.context() as local:
        local.setattr(default_scene, "run_scene", lambda **kw: calls.append(dict(kw)))
        with contextlib.redirect_stdout(text):
            code = launcher.main([])
    out["launcher_main.json"] = dump_json(
        {
            "exit": code,
            "lines": text.getvalue().splitlines(),
            "run_scene_calls": calls,
            "stack_calls": list(stack_calls),
        }
    )
    return out


def capture(tmp_path: Path, patch: pytest.MonkeyPatch) -> dict[str, str]:
    """
    Everything spec §1 lists, as ``{fixture path relative to FIXTURES: text}``.

    Runs inside a test: the conftest's saves redirect and model guards must be
    in force. ``patch`` is the test's MonkeyPatch.
    """
    from engine.games import registry
    from engine.scenes.default_scene import create_app, reset_store

    norm = Normaliser()
    files: dict[str, str] = {}
    # Generated media is written under, and the image cache read from, the
    # storage root (engine/persistence/storage.py; on e7fdd26 a cwd-relative
    # data/media), and the cache is consulted before the procedural provider
    # -- so the owner's data/media would both receive the capture's pictures
    # and change its answers. The root is a temp directory for the whole
    # capture (`pinned`'s `data_dir`), unset only where `save_base` pins the
    # default. The working directory is an empty temp directory as well, as it
    # was on e7fdd26, so nothing still relative to it can reach the repo.
    workdir = tmp_path / "cwd"
    workdir.mkdir(parents=True, exist_ok=True)
    patch.chdir(workdir)
    with pinned(patch, tmp_path / "config", tmp_path / "data") as stack_calls:
        if registry.peek() is not None:
            registry.deactivate()

        # -- the app, as a local owner starts it (the default story) --------
        reset_store()
        scene, app = create_app(testing=True, llm_fn=scripted_model)
        client = app.test_client()
        files["app_shape.json"] = dump_json(app_shape(scene, patch))
        # Rebuilt: run_scene() made an app of its own; the routes below are
        # asked of the one created for this capture.
        reset_store()
        scene, app = create_app(testing=True, llm_fn=scripted_model)
        client = app.test_client()

        index = client.get("/")
        assert index.status_code == 200, index.status_code
        # A CRLF checkout of the template (autocrlf) serves CRLF; the golden
        # pins the content, not the checkout's line endings.
        files["index.html"] = index.get_data(as_text=True).replace("\r\n", "\n")
        files["health.json"] = dump_json(_http(client.get("/api/health")))
        for name, url in (
            ("settings.json", "/api/settings"),
            ("games.json", "/api/games"),
            ("games_active.json", "/api/games/active"),
            ("games_clockwork-dark.json", "/api/games/clockwork-dark"),
            ("games_hue-and-cry.json", "/api/games/hue-and-cry"),
            ("archetypes.json", "/api/archetypes"),
        ):
            files[name] = dump_json(norm(_http(client.get(url))))
        files["art.json"] = dump_json(
            {
                "bare": _http(client.get("/api/art")),
                "edgewood_bakery": _http(
                    client.get("/api/art", query_string={"id": "edgewood_bakery", "kind": "location"})
                ),
            }
        )
        plate = client.get(f"/story-art/{PLATE}")
        body = plate.get_data()
        files["story_art.json"] = dump_json(
            {
                "path": PLATE,
                "status": plate.status_code,
                "content_type": plate.headers.get("Content-Type"),
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
            }
        )
        plate.close()
        files["media_refused.json"] = dump_json(_http(client.get("/api/media/../x")))
        files["audio_refused.json"] = dump_json(_http(client.get("/api/audio/../x")))

        # -- two stories, played ----------------------------------------------
        for slug in STORIES:
            played = play_story(slug, norm, patch)
            for name, value in played.items():
                files[f"{slug}/{name}.json"] = dump_json(norm(value))
            files[f"save_tree_{slug}.json"] = dump_json(save_tree(slug, norm))
            if slug in STREAMED_STORIES:
                streamed = stream_turn(slug, patch)
                norm.learn(streamed)
                files[f"{slug}/socket_stream_turn.json"] = dump_json(norm(streamed))
        files["save_base.json"] = dump_json(save_base(patch))

        # -- the launcher -----------------------------------------------------
        files.update(launcher_runs(patch, stack_calls))
    return files


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def write(files: dict[str, str], *, overwrite: bool = False) -> list[Path]:
    """Write a capture as the recording. Refuses to replace one without leave."""
    if FIXTURES.exists() and any(FIXTURES.rglob("*")) and not overwrite:
        raise RuntimeError(
            f"{FIXTURES} already holds a recording. The golden is recorded once, "
            "on e7fdd26 code; pass --overwrite only if that is what you are doing."
        )
    written = []
    for name, text in sorted(files.items()):
        path = FIXTURES / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def record(*, overwrite: bool = False, pytest_args: Optional[list[str]] = None) -> int:
    """
    Record the fixtures by running the golden test under pytest with
    ``RECORD_ENV`` set, so every conftest guard is up while they are written.
    ``pytest_args`` are passed through (this workstation needs ``--basetemp``).
    """
    env = dict(os.environ)
    env[RECORD_ENV] = "1"
    if overwrite:
        env[OVERWRITE_ENV] = "1"
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_local_mode_golden.py::test_local_mode_is_unchanged",
        "-q",
        "-p",
        "no:cacheprovider",
        *(pytest_args or []),
    ]
    return subprocess.call(argv, cwd=str(REPO), env=env)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    parser.add_argument("command", choices=["record"])
    parser.add_argument("--overwrite", action="store_true")
    args, extra = parser.parse_known_args(argv)
    # Anything else goes to pytest (this workstation needs --basetemp=...).
    return record(overwrite=args.overwrite, pytest_args=extra)


if __name__ == "__main__":
    raise SystemExit(main())

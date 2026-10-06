"""
A hosted game app, built in this process, for the hosting tests (v0.20.0 T7).

Hosted mode is turned on the way an operator turns it on: a ``local.yaml``
layer holding ``hosting.enabled: true``, in a temp ``config/`` directory that
``engine.config._CONFIG_DIR`` is pointed at (so the owner's real
``config/local.yaml`` is never read, let alone written), and
``CLOCKWORK_DATA_DIR`` set to the test's ``tmp_path`` so ``users.json``, its
lock and the cookie key are made there and nowhere else.

``install()``'s warming (``engine.hosting.warm_process``) is replaced with a
recorder unless a test asks for it: it builds every cache in the engine, and
``tests/test_cache_warming.py`` already proves what it builds. The test that
asserts install warms spies on the real one's parts.

Passwords are generated per test (``secrets``), never written down.

Version: v0.1.0 [2026-10-01]
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pytest
import yaml

#: Environment a hosted test must not inherit from the shell that ran pytest.
CLEARED_ENV = (
    "CLOCKWORK_ENV",
    "CLOCKWORK_CONFIG",
    "CLOCKWORK_STUDIO",
    "CLOCKWORK_SECRET_KEY",
    "CLOCKWORK_GAME",
    # The supervisor's bus (v0.20.0 T10): an in-process app connects only
    # when a test passes these in ``env``.
    "CLOCKWORK_BUS_ADDR",
    "CLOCKWORK_BUS_TOKEN",
    "CLOCKWORK_BUS_ROLE",
    "CLOCKWORK_PROXY_TOKEN",
)

#: The scripted model's one reply (no model is ever called for real).
SCRIPTED_REPLY = """```json
{"narration": "Mist clings to the birch trunks.",
 "choices": [{"id": "a", "text": "Walk on"}, {"id": "b", "text": "Wait"}]}
```"""


def scripted_model(_messages: Any) -> str:
    return SCRIPTED_REPLY


def new_password() -> str:
    """A generated test password (at least ten characters)."""
    return "pw-" + secrets.token_urlsafe(12)


@dataclass
class Hosted:
    """One hosted app and what a test needs around it."""

    scene: Any
    app: Any
    data_dir: Path
    config_dir: Path
    warmed: list[str] = field(default_factory=list)
    #: Each account ``add`` made: its generated password, by name.
    passwords: dict[str, str] = field(default_factory=dict)

    @property
    def state(self) -> Any:
        from engine.hosting.auth import hosting_state

        return hosting_state(self.app)

    def client(self) -> Any:
        return self.app.test_client()

    def add(self, name: str = "alice") -> tuple[Any, str]:
        """Make an account; returns ``(account, its password)``."""
        password = new_password()
        account = self.state.accounts.add(name, password)
        self.passwords[name] = password
        return account, password


def hosting_layer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    hosting: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> tuple[Path, Path]:
    """
    Point the config at a temp ``config/`` whose ``local.yaml`` turns hosting
    on (plus ``hosting`` keys and any ``extra`` top-level blocks), and the
    storage root at ``tmp_path/data``. Returns ``(config_dir, data_dir)``.
    """
    import engine.config as config

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    tree: dict[str, Any] = {"hosting": {"enabled": True, **(hosting or {})}}
    for key, value in (extra or {}).items():
        tree[key] = value
    (config_dir / "local.yaml").write_text(yaml.safe_dump(tree), encoding="utf-8")
    for name in CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    data_dir = tmp_path / "data"
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(data_dir))
    monkeypatch.setattr(config, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "_instance", None)
    return config_dir, data_dir


def build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    hosting: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    warm: bool = False,
    env: Optional[dict[str, str]] = None,
    llm_fn: Any = scripted_model,
) -> Hosted:
    """
    Build the hosted default scene (the caller resets the config after).
    ``env`` is set after ``CLEARED_ENV`` is cleared. ``llm_fn`` None builds
    the real model-server path (a test then answers it through
    ``tests/llm_wire.py``).
    """
    import engine.hosting as hosting_pkg
    from engine.scenes.default_scene import create_app, reset_store

    config_dir, data_dir = hosting_layer(monkeypatch, tmp_path, hosting=hosting, extra=extra)
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    warmed: list[str] = []
    if not warm:
        monkeypatch.setattr(hosting_pkg, "warm_process", lambda: warmed.append("warm_process"))
    reset_store()
    scene, app = create_app(testing=True, llm_fn=llm_fn)
    # The test client builds its URLs from this: the login page is posted over
    # "https" as a browser behind TLS would, so `cookie_secure: true` (the
    # default) is what runs. The plain-HTTP tests pass base_url themselves.
    app.config["PREFERRED_URL_SCHEME"] = "https"
    hosted = Hosted(scene=scene, app=app, data_dir=data_dir, config_dir=config_dir, warmed=warmed)
    _BUILT.append(hosted)
    return hosted


#: Every app ``build`` made since the last ``teardown``: their server-lock
#: handles are closed there (a hosted process holds one for its life).
_BUILT: list[Hosted] = []


def teardown() -> None:
    """Drop the hosted config and every cache built from it; free server locks."""
    import os

    from engine.config import reset_config
    from engine.hosting.metrics_emit import reset_hooks
    from engine.llm.gate import reset_lane_backend
    from engine.scenes.default_scene import reset_store

    # A supervised build (bus variables in ``env``) set the gate's lane
    # backend (v0.20.0 T11) and the turn metric hook (T17); the next test
    # gets this process's own lanes and no hook.
    reset_lane_backend()
    reset_hooks()
    while _BUILT:
        state = _BUILT.pop().state
        if state.server_lock is not None:
            os.close(state.server_lock)
            state.server_lock = None
    reset_config()
    reset_store()


class SharedQueue:
    """
    The supervisor's queue (``engine/hosting/supervisor/queue.py``) in THIS
    process, reached over a real loopback bus by ``RemoteLanes`` clients, as
    a supervised worker reaches it (v0.20.0 T11). ``install()`` makes it the
    gate's lane backend, so a test of the gate's rules runs against it as
    well as against the in-process lanes; ``close()`` puts everything back.

    ``view(lane)`` answers what a test asks of a lane, whichever backend:
    ``held``, ``waiting``, ``wait_until_waiting(n, timeout)``.
    """

    def __init__(self, limits: Optional[dict[str, int]] = None, *, story: str = "clockwork-dark") -> None:
        from engine.hosting.bus import BusServer
        from engine.hosting.supervisor.queue import LaneQueue

        self.story = story
        self.queue = LaneQueue(limits or {"narration": 1, "utility": 2}).start()
        self.server = BusServer().start()
        self.queue.attach(self.server)
        self.server.on_close = lambda conn: self.queue.close_connection(conn.id)
        self._clients: list[Any] = []

    def client(self, story: Optional[str] = None) -> Any:
        """A connected worker bus client (its lifeline defused: this process must not exit)."""
        from engine.hosting.bus import BusClient

        record = self.server.mint("worker", story=story or self.story)
        client = BusClient(self.server.addr, record.token)
        client.on_lost = lambda: None
        client.connect()
        self._clients.append(client)
        return client

    def lanes(self, story: Optional[str] = None) -> Any:
        """A ``RemoteLanes`` over a fresh connection."""
        from engine.hosting.lanes_remote import RemoteLanes

        return RemoteLanes(self.client(story))

    def install(self) -> Any:
        """Make a fresh ``RemoteLanes`` the gate's backend; it is returned."""
        from engine.llm.gate import set_lane_backend

        lanes = self.lanes()
        set_lane_backend(lanes)
        return lanes

    def view(self, lane: str) -> "QueueView":
        return QueueView(self.queue, lane)

    def close(self) -> None:
        from engine.llm.gate import reset_lane_backend

        reset_lane_backend()
        for client in self._clients:
            client.close()
        self.server.close()
        self.queue.close()


class QueueView:
    """One lane of a ``SharedQueue``, asked as a test asks a ``FifoSemaphore``."""

    def __init__(self, queue: Any, lane: str) -> None:
        self.queue = queue
        self.lane = lane

    def _row(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return next(row for row in snapshot["lanes"] if row["lane"] == self.lane)

    @property
    def held(self) -> int:
        return len(self._row(self.queue.snapshot())["holders"])

    @property
    def waiting(self) -> int:
        return len(self._row(self.queue.snapshot())["waiters"])

    def wait_until_waiting(self, count: int, timeout: float) -> bool:
        return self.queue.wait_for(lambda snap: len(self._row(snap)["waiters"]) >= count, timeout)

    def wait_until_held(self, count: int, timeout: float) -> bool:
        return self.queue.wait_for(lambda snap: len(self._row(snap)["holders"]) == count, timeout)


class Lanes:
    """
    What a test asks of the lanes, whichever backend serves them: this
    process's own FIFO lanes (T9), or the supervisor's queue over a real
    loopback bus through ``RemoteLanes`` (T11, ``SharedQueue``).
    """

    def __init__(self, shared: Optional[SharedQueue] = None) -> None:
        self.shared = shared

    def view(self, lane: str) -> Any:
        """``held``, ``waiting``, ``wait_until_waiting``: the lane's state."""
        from engine.llm import gate

        return self.shared.view(lane) if self.shared is not None else gate._semaphore(lane)

    def hold(self, lane: str) -> Any:
        """Another holder takes one slot of ``lane``; answers its release."""
        from engine.llm import gate

        if self.shared is not None:
            other = self.shared.lanes()
            ticket = other.acquire(lane, 1.0)
            return lambda: other.release(ticket)
        sem = gate._semaphore(lane)
        assert sem.acquire(timeout=1)
        return sem.release

    def take_all(self, lane: str) -> list[Any]:
        """Other holders take every free slot of ``lane``; answers their releases."""
        from engine.llm import gate

        releases: list[Any] = []
        if self.shared is not None:
            other = self.shared.lanes()
            while True:
                try:
                    ticket = other.acquire(lane, 0.0)
                except gate.InferenceBusy:
                    return releases
                releases.append(lambda t=ticket: other.release(t))
        sem = gate._semaphore(lane)
        while sem.acquire(blocking=False):
            releases.append(sem.release)
        return releases


_CSRF_RE = re.compile(r'name="csrf" value="([^"]*)"')


def csrf_of(body: Any) -> str:
    """The first form token in a page."""
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    match = _CSRF_RE.search(text)
    assert match, "no csrf field on the page"
    return match.group(1)


def login(client: Any, name: str, password: str, **kwargs: Any) -> Any:
    """GET the login page (its token), then POST the form. Returns the POST's response."""
    page = client.get("/login", **kwargs)
    token = csrf_of(page.data)
    return client.post(
        "/login", data={"csrf": token, "name": name, "password": password}, **kwargs
    )


__all__ = [
    "Hosted",
    "build",
    "csrf_of",
    "hosting_layer",
    "Lanes",
    "login",
    "new_password",
    "QueueView",
    "scripted_model",
    "SharedQueue",
    "teardown",
]

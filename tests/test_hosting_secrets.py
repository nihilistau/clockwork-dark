"""
Secrets and internals never leave a hosted server (v0.20.0 T8, spec §6.6,
§9.4).

With a known model-server API key, cookie key (``CLOCKWORK_SECRET_KEY``) and
two accounts' password hashes in place, a logged-in player drives EVERY rule
and method in the URL map and EVERY registered socket event, once normally
and once under forced failures:

- the model server down (every request answered ``ConnectError`` naming its
  URL, through ``tests/llm_wire.py``), and a turn that raises an exception
  naming it;
- speech-to-text failing with a ``raw`` body that names an internal URL (and
  succeeding with one);
- a malformed save, a missing one and one whose migration fails;
- a socket payload that is not an object.

Every response body and every emitted payload is scanned: none may carry the
API key, the cookie key, a password or its hash, the model server's or the
STT server's address, the STT server's ``raw`` body, a Python exception's
class name, the storage root's path, or any ``users.json`` field but the
logged-in account's own name.

The whole crawl runs once more with ``reset_config`` and
``reset_all_caches`` patched to raise wherever they are bound (spec §5.2):
serving must never reset a cache under other players' turns, so neither may
be called.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import secrets
import sys
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import httpx
import pytest

from tests.hosted_app import Hosted, build, login, teardown
from tests.llm_wire import wire
from tests.local_golden import wav_bytes

# In-process loopback servers: the hybrid run's serial phase (tests/tiers.py).
pytestmark = pytest.mark.loopback

MODEL_HOST = "model-crawl.internal"
MODEL_URL = f"http://{MODEL_HOST}:5999/v1"
STT_HOST = "stt-crawl.internal"
STT_URL = f"http://{STT_HOST}:5051"
RAW_MARKER = "raw-body-marker-" + secrets.token_hex(4)
API_KEY = "sk-crawl-" + secrets.token_hex(16)
COOKIE_KEY = secrets.token_urlsafe(32)
PLAYER = "crawl-player"
OTHER = "crawl-other-account"

#: A Python exception's class name (``KeyError``, ``ConnectError``,
#: ``MigrationError``...), or a traceback.
EXCEPTION_NAME = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:Error|Exception)\b|Traceback \(most recent")

#: The converters' samples, as the gate test fills them.
_SAMPLES = {"default": "x", "string": "x", "path": "x/y", "int": "1", "float": "1.0", "uuid": "0" * 32}
_ARG_RE = re.compile(r"<(?:(\w+)(?:\([^)]*\))?:)?(\w+)>")


@pytest.fixture
def secrets_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Callable[..., Hosted]]:
    def make(**kwargs: Any) -> Hosted:
        return build(
            monkeypatch,
            tmp_path,
            # The crawl drives every door many times over; the actions bucket
            # (v0.20.0 T9, tests/test_hosting_limits.py) would answer most of
            # them 429 before the route under test ran.
            hosting={"rate_limits": {"actions_per_minute": 10_000}},
            env={"CLOCKWORK_SECRET_KEY": COOKIE_KEY},
            extra={
                "llm": {"base_url": MODEL_URL, "api_key": API_KEY},
                "stt": {"base_url": STT_URL, "provider": "voxtral_http"},
            },
            **kwargs,
        )

    try:
        yield make
    finally:
        teardown()


# -- the stubs that force each failure ---------------------------------------------------


class _Stt:
    """A speech provider whose results carry internals (``raw``, a URL)."""

    name = "crawl_stub"

    def __init__(self, *, fail: bool) -> None:
        self.fail = fail

    def transcribe(self, _audio: bytes, **_kw: Any) -> dict[str, Any]:
        raw = {"note": RAW_MARKER, "upstream": f"{STT_URL}/v1/audio/transcriptions"}
        if not self.fail:
            return {"success": True, "transcript": "look about you", "source": "live", "provider": self.name, "raw": raw}
        return {
            "success": False,
            "transcript": "",
            "source": "stub",
            "provider": self.name,
            "message": f"ConnectError: All connection attempts failed: {STT_URL}",
            "raw": raw,
        }


def _bad_saves(hosted: Hosted, account_id: str) -> dict[str, str]:
    """A malformed save and one whose migration fails, in the player's store."""
    root = hosted.data_dir / "users" / account_id / "saves" / "clockwork-dark"
    malformed = root / "badbadbad001"
    malformed.mkdir(parents=True)
    (malformed / "save.json").write_text("{not json at all", encoding="utf-8")
    future = root / "future000002"
    future.mkdir(parents=True)
    (future / "save.json").write_text(
        json.dumps({"save_version": 999, "save_id": "future000002", "state": {"save_version": 999}}),
        encoding="utf-8",
    )
    unreadable = root / "brokenstate3"
    unreadable.mkdir(parents=True)
    (unreadable / "save.json").write_text(
        json.dumps({"save_id": "brokenstate3", "state": {"world_hour": "not an hour", "inventory": 7}}),
        encoding="utf-8",
    )
    return {"malformed": "badbadbad001", "migration": "future000002", "unreadable": "brokenstate3", "missing": "000000000000"}


# -- the crawl ----------------------------------------------------------------------------


class Crawl:
    """Every rule × method and every socket event, with each body kept to scan."""

    def __init__(self, hosted: Hosted, client: Any) -> None:
        self.hosted = hosted
        self.client = client
        self.seen: list[tuple[str, str]] = []
        created = client.post("/api/game/new", json={"seed": 5}).get_json()
        self.keep("POST /api/game/new", json.dumps(created))
        self.session_id = created["session_id"]
        self.save_id = created["save_id"]

    def keep(self, label: str, text: str) -> None:
        self.seen.append((label, text))

    def revive(self) -> None:
        """
        Make the crawl's run live again (v0.20.0 T9): an account has one live
        run, so every new game the crawl sends releases it, and a door naming
        it would answer "session not found" instead of doing its work. A
        resume of its save rebuilds it under the same id; once the crawl has
        deleted that save, a new run takes its place.
        """
        response = self.client.post(f"/api/saves/{self.save_id}/load")
        self.keep(f"POST /api/saves/{self.save_id}/load (revive)", response.get_data(as_text=True))
        if response.status_code == 200:
            return
        created = self.client.post("/api/game/new", json={"seed": 5})
        self.keep("POST /api/game/new (revive)", created.get_data(as_text=True))
        body = created.get_json()
        self.session_id = body["session_id"]
        self.save_id = body["save_id"]

    def _url(self, rule: Any, save_id: str) -> str:
        def fill(match: re.Match[str]) -> str:
            if match.group(2) == "save_id":
                return save_id
            converter = match.group(1) or "default"
            assert converter in _SAMPLES, f"no sample for converter {converter!r} in {rule.rule}"
            return _SAMPLES[converter]

        return _ARG_RE.sub(fill, rule.rule)

    def _send(self, method: str, url: str, save_id: str) -> Any:
        query = {"session_id": self.session_id}
        if url == "/api/voice/transcribe":
            return self.client.post(
                url,
                query_string=query,
                data={"session_id": self.session_id, "audio": (io.BytesIO(wav_bytes()), "a.wav")},
                content_type="multipart/form-data",
            )
        body = {"session_id": self.session_id, "save_id": save_id, "choice_id": "a", "seed": 5, "custom_text": "wait"}
        if method in {"GET", "DELETE"}:
            return self.client.open(url, method=method, query_string=query)
        return self.client.open(url, method=method, query_string=query, json=body)

    def http(self, save_ids: list[str]) -> None:
        """Every rule and method (bar HEAD and OPTIONS); deletes, then logout, last."""
        cases: list[tuple[int, str, str, str]] = []
        for rule in self.hosted.app.url_map.iter_rules():
            ids = save_ids if "<save_id>" in rule.rule else [self.save_id]
            for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
                for save_id in ids:
                    order = 2 if rule.endpoint.endswith(".logout") else 1 if method == "DELETE" else 0
                    cases.append((order, method, self._url(rule, save_id), save_id))
        for _order, method, url, save_id in sorted(cases):
            if not url.endswith("/logout"):
                self.revive()
            response = self._send(method, url, save_id)
            self.keep(f"{method} {url} -> {response.status_code}", response.get_data(as_text=True))
            for name, value in response.headers.items():
                if name.lower() == "location":
                    self.keep(f"{method} {url} Location", value)

    def malformed(self) -> None:
        """
        Fix round 1 (M6): every state-changing rule again with bodies a client
        should never send -- not JSON at all, every field the wrong type, and
        a typed action far past any length -- and every socket event with the
        same wrong-typed payload.
        """
        wrong = {
            "session_id": {},
            "save_id": [],
            "choice_id": 5,
            "seed": "x",
            "player_name": [],
            "archetype": {"a": 1},
            "slot": None,
            "custom_text": ["not", "text"],
            "changes": "x",
        }
        oversized = {"session_id": self.session_id, "choice_id": "a", "custom_text": "w" * 200_000}
        for rule in self.hosted.app.url_map.iter_rules():
            if rule.endpoint.endswith(".logout"):
                continue
            url = self._url(rule, self.save_id)
            for method in sorted((rule.methods or set()) & {"POST", "PUT", "PATCH", "DELETE"}):
                for label, kwargs in (
                    ("not json", {"data": "{not json", "content_type": "application/json"}),
                    ("wrong types", {"json": wrong}),
                    ("oversized", {"json": oversized}),
                    ("a form", {"data": {"session_id": "x", "audio": "not a file"}}),
                ):
                    response = self.client.open(url, method=method, **kwargs)
                    self.keep(f"{method} {url} [{label}] -> {response.status_code}", response.get_data(as_text=True))
        sio = self.hosted.scene.socketio.test_client(self.hosted.app, flask_test_client=self.client)
        assert sio.is_connected()
        for namespace, handlers in self.hosted.scene.socketio.server.handlers.items():
            for event in sorted(handlers):
                if event in {"connect", "disconnect"}:
                    continue
                for payload in (wrong, oversized, None, 7):
                    sio.emit(event, payload, namespace=namespace)
                    self.keep(f"socket {event} [malformed]", json.dumps(sio.get_received(namespace), default=str))
        sio.disconnect()

    def sockets(self, save_ids: list[str]) -> None:
        """Connect, then every registered event, with each save id and a non-object payload."""
        scene = self.hosted.scene
        sio = scene.socketio.test_client(self.hosted.app, flask_test_client=self.client)
        assert sio.is_connected()
        self.keep("socket connect", json.dumps(sio.get_received(), default=str))
        events = sorted(
            {(str(ns), str(event)) for ns, handlers in scene.socketio.server.handlers.items() for event in handlers}
        )
        for namespace, event in events:
            if event in {"connect", "disconnect"}:
                continue
            payloads: list[Any] = [
                {"session_id": self.session_id, "save_id": save_id, "choice_id": "a", "custom_text": "wait"}
                for save_id in save_ids
            ]
            payloads.append("not an object")
            for payload in payloads:
                sio.emit(event, payload, namespace=namespace)
                self.keep(f"socket {event} {payload!r:.60}", json.dumps(sio.get_received(namespace), default=str))
        sio.disconnect()


def _forbidden(hosted: Hosted, passwords: list[str]) -> dict[str, str]:
    """``label -> text`` no body or payload may contain."""
    rows = json.loads((hosted.data_dir / "hosting" / "users.json").read_text(encoding="utf-8"))["accounts"]
    out = {
        "the API key": API_KEY,
        "the cookie key": COOKIE_KEY,
        "the model server's host": MODEL_HOST,
        "the STT server's host": STT_HOST,
        "the STT raw body": RAW_MARKER,
        "the storage root": str(hosted.data_dir),
        "the storage root (slashes)": str(hosted.data_dir).replace("\\", "/"),
    }
    for i, password in enumerate(passwords):
        out[f"password {i}"] = password
    for row in rows:
        for field, value in row.items():
            if field == "name" and value == PLAYER:
                continue  # the account's own name is the one field it may see
            if isinstance(value, str) and len(value) >= 4:
                out[f"users.json {row['name']}.{field}"] = value
            elif isinstance(value, float):
                out[f"users.json {row['name']}.{field}"] = repr(value)
    return out


def _leaks(seen: list[tuple[str, str]], forbidden: dict[str, str]) -> list[str]:
    found = []
    for label, text in seen:
        for what, value in forbidden.items():
            if value and value in text:
                found.append(f"{label}: {what}")
        match = EXCEPTION_NAME.search(text)
        if match:
            found.append(f"{label}: an exception class name ({match.group(0)!r})")
    return found


def _player(hosted: Hosted) -> tuple[Any, list[str]]:
    _, mine = hosted.add(PLAYER)
    _, theirs = hosted.add(OTHER)
    client = hosted.client()
    assert login(client, PLAYER, mine).status_code == 303
    return client, [mine, theirs]


@contextlib.contextmanager
def _stt(monkeypatch: pytest.MonkeyPatch, *, fail: bool) -> Iterator[None]:
    import engine.agents.assistant as assistant
    import engine.media.stt as stt

    stub = _Stt(fail=fail)
    with monkeypatch.context() as patch:
        patch.setattr(stt, "get_stt_provider", lambda *a, **k: stub)
        # The Assistant transcribes again when the route's transcript is empty
        # (`process_voice_input`), through its own client: stubbed too, so no
        # request (not even a DNS lookup) leaves the test.
        patch.setattr(assistant, "transcribe_audio", lambda audio, **_k: stub.transcribe(audio))
        yield


def _crawl(hosted: Hosted, client: Any, save_ids: Optional[list[str]] = None) -> Crawl:
    crawl = Crawl(hosted, client)
    ids = [crawl.save_id] + list(save_ids or [])
    crawl.sockets(ids)
    crawl.malformed()
    crawl.http(ids)
    return crawl


# -- the tests ----------------------------------------------------------------------------


def test_a_normal_crawl_leaks_nothing(
    secrets_env: Callable[..., Hosted], monkeypatch: pytest.MonkeyPatch
) -> None:
    hosted = secrets_env()
    client, passwords = _player(hosted)
    with _stt(monkeypatch, fail=False):
        crawl = _crawl(hosted, client)
    assert len(crawl.seen) > 40, "the crawl reached too little to prove anything"
    assert not _leaks(crawl.seen, _forbidden(hosted, passwords)), "\n".join(_leaks(crawl.seen, _forbidden(hosted, passwords)))


def test_a_crawl_under_forced_failures_leaks_nothing(
    secrets_env: Callable[..., Hosted], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model server down, STT failing, broken and missing saves, a non-object payload."""
    hosted = secrets_env(llm_fn=None)
    client, passwords = _player(hosted)
    account = hosted.state.accounts.by_name(PLAYER)
    bad = _bad_saves(hosted, account.id)
    down = [{"raise": "ConnectError", "message": f"All connection attempts failed: {MODEL_URL}"}] * 2000
    with _stt(monkeypatch, fail=True), wire(down) as seam:
        crawl = _crawl(hosted, client, list(bad.values()))
    assert seam.requests, "the model server was never asked: the failure was not forced"
    leaks = _leaks(crawl.seen, _forbidden(hosted, passwords))
    assert not leaks, "\n".join(leaks)
    # Each forced failure was actually reached, and answered in public words.
    bodies = "\n".join(text for _label, text in crawl.seen)
    assert "Transcription failed (ref " in bodies
    assert "save could not be read" in bodies or "Save could not be read" in bodies
    assert "this build understands up to" in bodies, "the MigrationError's own words are kept"
    assert "The request could not be completed (ref " in bodies, "the non-object payload"


def test_a_turn_that_raises_is_answered_with_a_reference(
    secrets_env: Callable[..., Hosted], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import engine.scenes.default_scene as default_scene

    hosted = secrets_env()
    client, passwords = _player(hosted)

    def explode(*_a: Any, **_k: Any) -> Any:
        raise httpx.ConnectError(f"All connection attempts failed: {MODEL_URL} (api_key={API_KEY})")

    monkeypatch.setattr(default_scene, "run_turn", explode)
    with _stt(monkeypatch, fail=True), caplog.at_level("ERROR", logger="engine.hosting"):
        crawl = _crawl(hosted, client)
    leaks = _leaks(crawl.seen, _forbidden(hosted, passwords))
    assert not leaks, "\n".join(leaks)
    refs = re.findall(r"The turn could not be completed \(ref ([0-9a-f]{8})\)", "\n".join(t for _l, t in crawl.seen))
    assert refs, "no turn failure was answered"
    # The same reference is in the log, with the exception.
    logged = [r for r in caplog.records if refs[0] in r.getMessage()]
    assert logged and logged[0].exc_info and logged[0].exc_info[0] is httpx.ConnectError


def _patch_resets_to_raise(patch: pytest.MonkeyPatch) -> list[str]:
    """``reset_config`` and ``reset_all_caches`` raise, wherever a module holds them."""
    import engine.config as config
    import engine.games.caches as caches

    called: list[str] = []
    definitions = (config.reset_config, caches.reset_all_caches)
    originals = {id(config.reset_config): "reset_config", id(caches.reset_all_caches): "reset_all_caches"}

    def raiser(name: str) -> Callable[..., Any]:
        def refuse(*_a: Any, **_k: Any) -> Any:
            called.append(name)
            raise AssertionError(f"{name} called while serving")

        return refuse

    for module in list(sys.modules.values()):
        if module is None or not getattr(module, "__name__", "").startswith(("engine", "tests")):
            continue
        for attr, value in list(vars(module).items()):
            name = originals.get(id(value))
            if name is not None:
                patch.setattr(module, attr, raiser(name))
    # AT THE DEFINITION TOO (fix round 1, M6): a reference a closure or a
    # default argument captured escapes the module patch above, so each
    # function's own code is swapped for one that records and raises. The
    # swapped code runs in the function's own module, so it records through
    # the environment (builtins only), which ``patch`` restores.
    patch.delenv(_RESET_ENV, raising=False)
    for function in definitions:
        assert not function.__code__.co_freevars
        patch.setattr(function, "__code__", _refuse_reset.__code__)
    return called


#: Where a reset swapped at its definition records that it was called.
_RESET_ENV = "CLOCKWORK_TEST_RESET_CALLED"


def _refuse_reset(*_a: Any, **_k: Any) -> Any:
    """The code a reset is swapped for: builtins only, since it runs in another module."""
    __import__("os").environ["CLOCKWORK_TEST_RESET_CALLED"] = "1"
    raise AssertionError("a cache reset was called while serving")


def test_the_crawl_never_resets_a_cache_while_serving(
    secrets_env: Callable[..., Hosted], monkeypatch: pytest.MonkeyPatch
) -> None:
    hosted = secrets_env()
    client, passwords = _player(hosted)
    account = hosted.state.accounts.by_name(PLAYER)
    bad = _bad_saves(hosted, account.id)
    with monkeypatch.context() as patch:
        called = _patch_resets_to_raise(patch)
        with _stt(monkeypatch, fail=True):
            crawl = _crawl(hosted, client, list(bad.values()))
        swapped = __import__("os").environ.get(_RESET_ENV)
    assert called == [], f"serving reset a cache: {called}"
    assert swapped is None, "serving reset a cache through a reference the module patch missed"
    leaks = _leaks(crawl.seen, _forbidden(hosted, passwords))
    assert not leaks, "\n".join(leaks)


def test_local_mode_keeps_its_error_words() -> None:
    """The hosted generic text is hosted only: local mode's turn failure still names the cause."""
    from types import SimpleNamespace

    import engine.scenes.default_scene as default_scene

    session = SimpleNamespace(lock=__import__("threading").Lock(), session_id="abc")
    real = default_scene.run_turn
    try:
        default_scene.run_turn = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model said no"))
        payload, error, busy = default_scene.run_guarded(session, "wait", None)
    finally:
        default_scene.run_turn = real
    assert (payload, error, busy) == (None, "The turn could not be completed: model said no", False)


# -- the same crawl through the front door (v0.20.0 T12) ------------------------------------


class _Answer:
    """An ``httpx.Response`` as the crawl reads a Flask test response."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.status_code = response.status_code
        self.headers = response.headers

    def get_json(self) -> Any:
        try:
            return self.response.json()
        except ValueError:
            return None

    def get_data(self, as_text: bool = False) -> Any:
        return self.response.text if as_text else self.response.content


class FrontDoorClient:
    """The Flask test client's calls the crawl makes, sent through the front door over HTTP."""

    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def open(
        self,
        url: str,
        method: str = "GET",
        query_string: Optional[dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        content_type: Optional[str] = None,
    ) -> _Answer:
        kwargs: dict[str, Any] = {"params": query_string}
        if json is not None:
            kwargs["json"] = json
        elif isinstance(data, dict):
            files = {k: (v[1], v[0].getvalue()) for k, v in data.items() if isinstance(v, tuple)}
            form = {k: v for k, v in data.items() if not isinstance(v, tuple)}
            kwargs["data"] = form
            if files:
                kwargs["files"] = files
        elif data is not None:
            kwargs["content"] = data.encode("utf-8") if isinstance(data, str) else data
            if content_type:
                kwargs["headers"] = {"Content-Type": content_type}
        return _Answer(self.http.request(method, url, **kwargs))

    def get(self, url: str, **kwargs: Any) -> _Answer:
        return self.open(url, "GET", **kwargs)

    def post(self, url: str, **kwargs: Any) -> _Answer:
        return self.open(url, "POST", **kwargs)


def _polling_crawl(crawl: Crawl, http: httpx.Client, base: str, save_ids: list[str]) -> None:
    """Every socket event over long polling through the front door; the replies kept."""
    from tests.engineio_wire import PollingClient

    poll = PollingClient(http, base)
    poll.handshake()
    crawl.keep("polling connect", json.dumps(poll.connect(), default=str))
    handlers = crawl.hosted.scene.socketio.server.handlers
    events = sorted({str(event) for _ns, table in handlers.items() for event in table} - {"connect", "disconnect"})
    # Each event asks for an acknowledgement, which comes once its handler has
    # returned, after whatever it emitted: when every one is in, every
    # answer is (the handlers run concurrently, so no single reply can say so).
    asked: set[int] = set()
    for event in events:
        for save_id in save_ids:
            payload = {"session_id": crawl.session_id, "save_id": save_id, "choice_id": "a", "custom_text": "wait"}
            asked.add(poll.emit(event, payload, ack=True))  # type: ignore[arg-type]
        asked.add(poll.emit(event, "not an object", ack=True))  # type: ignore[arg-type]
    if poll.acked(asked) != asked:
        poll.until(lambda _e: poll.acked(asked) == asked, 120)
    for event in poll.received:
        crawl.keep(f"polling {event.get('name') or event['type']}", json.dumps(event, default=str))
    poll.close()


def _front_door_routes(crawl: Crawl, app: Any, client: FrontDoorClient) -> None:
    """The front door's own rules and methods (the proxy's catch-all with a sample path); logout last."""
    cases: list[tuple[int, str, str]] = []
    for rule in app.url_map.iter_rules():
        url = _ARG_RE.sub(lambda m: "x/y" if m.group(1) == "path" else "x", rule.rule)
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            cases.append((1 if url == "/logout" else 0, method, url))
    for _order, method, url in sorted(cases):
        response = client.open(url, method, json={"csrf": "x", "name": PLAYER, "password": "x"} if method != "GET" else None)
        crawl.keep(f"front door {method} {url} -> {response.status_code}", response.get_data(as_text=True))
        for name, value in response.headers.items():
            if name.lower() in ("location", "set-cookie"):
                crawl.keep(f"front door {method} {url} {name}", value)


def test_a_crawl_through_the_front_door_leaks_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    §9.4's crawl, driven through the front door (``InProcessFrontDoor``):
    every worker rule and method, the malformed bodies, every socket event
    over long polling, and the front door's own routes -- with speech failing
    and broken saves in place. Nothing it answers carries a secret: the API
    key, the cookie key, a password or ``users.json`` field, an internal
    address, the storage root, an exception's name -- and now the front
    door's proxy token and every bus token. (The model server stays scripted:
    ``tests/llm_wire.py`` patches every ``httpx`` transport in the process,
    the front door's own included.)
    """
    from tests.hosting_instance import InProcessFrontDoor, choose
    from tests.hosting_instance import login as front_login

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={"rate_limits": {"actions_per_minute": 10_000, "logins_per_minute": 1000}},
        extra={
            "llm": {"base_url": MODEL_URL, "api_key": API_KEY},
            "stt": {"base_url": STT_URL, "provider": "voxtral_http"},
        },
        env={"CLOCKWORK_SECRET_KEY": COOKIE_KEY},
    )
    door.start()
    http = door.http()
    try:
        hosted = door.hosted
        _, mine = hosted.add(PLAYER)
        _, theirs = hosted.add(OTHER)
        assert front_login(http, PLAYER, mine).status_code == 303
        assert choose(http, door.story).status_code == 303
        client = FrontDoorClient(http)
        bad = _bad_saves(hosted, hosted.state.accounts.by_name(PLAYER).id)
        with _stt(monkeypatch, fail=True):
            crawl = Crawl(hosted, client)  # type: ignore[arg-type]
            ids = [crawl.save_id] + list(bad.values())
            _polling_crawl(crawl, http, door.base, ids)
            crawl.http(ids)
            _front_door_routes(crawl, door.front_app, client)
        forbidden = _forbidden(hosted, [mine, theirs])
        forbidden["the proxy token"] = door.proxy_token
        for i, token in enumerate(door.tokens):
            forbidden[f"bus token {i}"] = token
        assert len(crawl.seen) > 60, "the crawl reached too little to prove anything"
        bodies = "\n".join(text for _label, text in crawl.seen)
        assert "Transcription failed (ref " in bodies, "the forced STT failure was not reached"
        leaks = _leaks(crawl.seen, forbidden)
        assert not leaks, "\n".join(leaks)
    finally:
        http.close()
        door.stop()


# -- the admin panel (v0.20.0 T14, spec §14.12) -----------------------------------------------


def _admin_cases(app: Any, target_id: str) -> list[tuple[str, str]]:
    """``(method, url)`` of every /admin rule and method (bar HEAD and OPTIONS)."""
    cases = []
    for rule in app.url_map.iter_rules():
        if not (rule.rule == "/admin" or rule.rule.startswith("/admin/")):
            continue

        def fill(match: re.Match[str]) -> str:
            name = match.group(2)
            return {"account_id": target_id, "filename": "admin.css"}.get(name, "x/y")

        url = _ARG_RE.sub(fill, rule.rule)
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            cases.append((method, url))
    return cases


def test_the_admin_panel_s_crawl_leaks_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    An admin's crawl of every /admin rule and method (each POST with the
    admin's own token) finds no API key, cookie key, password hash, known
    password, bus or proxy token, storage path or exception name; a
    non-admin's crawl of the same gets only the one fixed refusal.
    """
    from engine.hosting.admin.guard import FORBIDDEN
    from tests.hosting_instance import AdminDoor

    door = AdminDoor(
        monkeypatch,
        tmp_path,
        extra={"llm": {"base_url": MODEL_URL, "api_key": API_KEY}},
        env={"CLOCKWORK_SECRET_KEY": COOKIE_KEY},
    )
    door.start()
    try:
        door.add(PLAYER)
        victim = door.add(OTHER)
        player = door.login(PLAYER)
        admin = door.admin()
        token = door.token(admin)
        hashes = {row["hash"] for row in json.loads(door.accounts.path.read_text(encoding="utf-8"))["accounts"]}
        seen: list[tuple[str, str]] = []
        refusals: set[bytes] = set()
        for method, url in _admin_cases(door.app, victim.id):
            form = {"csrf": token, "name": "X", "confirm": "not-it", "mode": "keep", "password": "x"}
            answer = admin.open(url, method=method, data=form if method != "GET" else None)
            seen.append((f"admin {method} {url} -> {answer.status_code}", answer.get_data(as_text=True)))
            for name, value in answer.headers.items():
                seen.append((f"admin {method} {url} {name}", value))
            hashes |= {row["hash"] for row in json.loads(door.accounts.path.read_text(encoding="utf-8"))["accounts"]}
            refused = player.open(url, method=method, data={"csrf": "x"} if method != "GET" else None)
            assert refused.status_code == 403, (method, url)
            refusals.add(refused.get_data())
        assert refusals == {(json.dumps(FORBIDDEN, separators=(",", ":")) + "\n").encode("ascii")}
        assert len(seen) > 40, "the crawl reached too little to prove anything"
        forbidden = {
            "the API key": API_KEY,
            "the cookie key": COOKIE_KEY,
            "the model server's host": MODEL_HOST,
            "the proxy token": door.proxy_token,
            "the bus token": door.bus_token,
            "the storage root": str(door.data_dir),
            "the storage root (slashes)": str(door.data_dir).replace("\\", "/"),
        }
        forbidden.update({f"password of {name}": value for name, value in door.passwords.items()})
        forbidden.update({f"hash {i}": value for i, value in enumerate(sorted(hashes))})
        leaks = _leaks(seen, forbidden)
        assert not leaks, "\n".join(leaks)
    finally:
        door.stop()

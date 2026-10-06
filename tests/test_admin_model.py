"""
The admin panel's Model server and Queue pages, and the model apply (v0.20.0
T16, spec §14.9, §14.4, §14.3, §9.10).

First, in this process: the validation the front door and the supervisor
share (``engine/hosting/admin/model.py``), the key's source
(``ConfigManager.secret_source``) and the bus's ``changes`` shape.

Then ONE instance for the module, every process real
(``tests/hosting_instance.py``): the supervisor, two workers
(``tests/probes/scripted_worker.py``: it can hold a turn in flight, refuse to
boot under a named provider, reports the ``llm.*`` it booted with, and --
with ``CLOCKWORK_PROBE_FORBID_RESET`` -- makes any reset of its config after
boot write a marker and raise; so does the front door,
``tests/probes/frontdoor_relay.py``) and the engine's own front door. The model
server is a STUB on loopback, in this process (``StubModelServer``), which
the children reach because ``sandbox_model_stub_module`` registers its port
and writes it as the sandbox layer's ``llm.base_url`` -- so ``llm.base_url``
is a key ``CLOCKWORK_CONFIG`` sets, and locked in the panel (spec §3.5). The
instance's own config file names the API key's chain as the environment
alone, and the environment holds a SENTINEL key that must appear in no
response, log line or audit row. In order (each test leaves the instance as
the next expects it):

- the Model server page: provider, URL, status, models, the key as "set, from
  the environment";
- the Queue page and its JSON: a holder and a waiter, by account;
- ``llm.base_url`` locked and refused "set in <file>"; edits outside the
  allowlist, bad values and URLs with ``user:pass@``, a query or a fragment
  refused, nothing written;
- a valid apply: answered at once; it waits on a held ticket with the file
  untouched, a second apply refused meanwhile; then it writes, restarts the
  workers one at a time, the workers read the new values and the queue's
  narration lane has its new size;
- a drain past ``drain_seconds``: refused, nothing written, nothing restarted;
- a worker killed during a drain boots under the OLD, committed file;
- a new provider the probe finds silent: refused; with "apply anyway", done;
- a worker that will not boot under the new file: rolled back;
- no serving process reset its config, and the sentinel is nowhere.
"""

from __future__ import annotations

import html
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, Optional

import httpx
import pytest
import yaml

from tests.hosting_instance import SCRIPTED_WORKER, HostingInstance, choose, hosting_instance, login

A = "clockwork-dark"
B = "dev-story"
JOIN = 60.0
#: Long enough for a killed worker to restart AND boot inside one drain (the
#: crash test). 15 was enough here but not on CI's two-vCPU runner, where the
#: reborn worker's boot report missed it (v0.20.1).
DRAIN_SECONDS = 45
SENTINEL = "sk-t16-sentinel-" + secrets.token_hex(8)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm"

_OP_RE = re.compile(r"queued as (op-\d+)")

#: LM Studio's v1 list, one model (what ``parse_lmstudio_v1`` reads).
LMSTUDIO_MODELS = {
    "models": [
        {
            "type": "llm",
            "publisher": "stub",
            "key": "stub-model-7b",
            "display_name": "Stub 7B",
            "architecture": "llama",
            "quantization": {"name": "Q4_K_M", "bits_per_weight": 4},
            "max_context_length": 32768,
            "loaded_instances": [{"id": "stub-model-7b", "config": {"context_length": 8192}}],
            "capabilities": {"vision": False, "trained_for_tool_use": True},
        }
    ]
}


# -- in this process: the validation, the key's source, the bus shape ---------------


@pytest.mark.parametrize(
    ("url", "says"),
    [
        ("http://zork:hunter2@127.0.0.1:1234/v1", "user name or password"),
        ("http://zork@127.0.0.1:1234/v1", "user name or password"),
        ("http://127.0.0.1:1234/v1?api_key=hunter2", "query"),
        ("http://127.0.0.1:1234/v1#hunter2", "fragment"),
        ("ftp://127.0.0.1/v1", "http"),
        ("127.0.0.1:1234", "http"),
        ("http:///v1", "host"),
        ("http://127.0.0.1:99999/v1", "valid URL"),
        ("http://127.0.0.1:1234/v 1", "space"),
        ("http://${HOST}/v1", "${...}"),
        ("http://example.org/" + "x" * 200, "longer than"),
    ],
)
def test_the_url_rule_refuses_credentials_queries_and_fragments(url: str, says: str) -> None:
    from engine.hosting.admin.model import ChangeRefused, validate_base_url

    with pytest.raises(ChangeRefused) as caught:
        validate_base_url(url)
    assert says in str(caught.value)
    assert caught.value.key == "llm.base_url"
    for part in ("zork", "hunter2", "HOST"):
        if part in url:
            assert part not in str(caught.value), "a refusal echoed the URL"


@pytest.mark.parametrize("url", ["http://127.0.0.1:1234/v1", "https://models.example.org/v1", "http://[::1]:8080/v1"])
def test_the_url_rule_takes_a_plain_url(url: str) -> None:
    from engine.hosting.admin.model import validate_base_url

    assert validate_base_url(f"  {url} ") == url


def test_each_row_is_validated_by_its_own_rule() -> None:
    from engine.hosting.admin.model import ChangeRefused, validate_change, validate_changes

    assert validate_change("llm.provider", "ollama") == ("ollama", "")
    assert validate_change("llm.lanes.narration", "3") == (3, "")
    # The Settings panel's own row: clamped, with a note.
    value, note = validate_change("llm.profiles.big.temperature", "5")
    assert value == 2.0 and "clamped" in note
    assert validate_change("llm.prefer_native", "false") == (False, "")
    for key, bad in (
        ("llm.provider", "openai"),
        ("llm.lanes.utility", "0"),
        ("llm.lanes.utility", "17"),
        ("llm.lanes.narration", "two"),
        ("llm.profiles.big.temperature", "warm"),
        ("llm.profiles.big.reasoning", "maybe"),
        ("llm.profiles.big.model", "a;b"),
    ):
        with pytest.raises(ChangeRefused) as caught:
            validate_change(key, bad)
        assert caught.value.code == "bad_value" and caught.value.key == key
    for key in ("hosting.enabled", "llm.api_key", "llm.timeout_seconds", "storage.root"):
        with pytest.raises(ChangeRefused) as caught:
            validate_changes({key: "x"})
        assert caught.value.code == "not_editable"
    with pytest.raises(ChangeRefused) as caught:
        validate_changes({"llm.lanes.narration": 2}, {"llm.lanes.narration": "/srv/operator.yaml"})
    assert caught.value.code == "locked" and "set in /srv/operator.yaml" in str(caught.value)
    assert validate_changes({"llm.lanes.narration": 2}, {"llm.base_url": "/x"}) == ({"llm.lanes.narration": 2}, [])


def test_a_url_set_elsewhere_is_shown_without_its_credentials() -> None:
    from engine.hosting.admin.model import display_url, scrub

    assert display_url("http://user:secret@host:1/v1?key=abc#x") == "http://***@host:1/v1"
    assert display_url("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1"
    assert "secret" not in scrub("http://user:secret@host:1/v1 unreachable (ConnectError)")


def test_the_key_is_named_by_its_source_never_its_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from engine.config import ConfigManager

    monkeypatch.setenv("T16_KEY", SENTINEL)
    cfg = ConfigManager({"llm": {"provider": "ollama", "api_key": "${lmstudio?env:T16_OTHER|env:T16_KEY}"}})
    assert cfg.secret_source("llm.api_key") == ("environment", "T16_KEY")
    key_file = tmp_path / "key.txt"
    key_file.write_text(SENTINEL + "\n", encoding="utf-8")
    cfg = ConfigManager({"llm": {"api_key": f"${{file:{key_file}|env:T16_KEY}}"}})
    assert cfg.secret_source("llm.api_key") == ("file", str(key_file))
    monkeypatch.delenv("T16_KEY")
    assert ConfigManager({"llm": {"api_key": "${env:T16_KEY}"}}).secret_source("llm.api_key") == ("", "")
    assert ConfigManager({"llm": {"api_key": "plain"}}).secret_source("llm.api_key") == ("config", "llm.api_key")
    assert ConfigManager({"llm": {"api_key": ""}}).secret_source("llm.api_key") == ("", "")


def test_the_bus_carries_changes_as_a_flat_mapping_of_scalars() -> None:
    from engine.hosting.bus import OPS, BusRefusal, check_args

    spec = OPS["llm.apply"]
    assert check_args(spec, {"changes": {"llm.lanes.narration": 2, "llm.provider": "ollama"}, "apply_anyway": True})
    for bad in ({}, {"llm.provider": None}, {"llm.provider": ["x"]}, {"llm.provider": {"a": 1}}, {"k" * 65: 1},
                {f"k{i}": 1 for i in range(17)}, {"llm.base_url": "x" * 257}):
        with pytest.raises(BusRefusal):
            check_args(spec, {"changes": bad})
    with pytest.raises(BusRefusal):
        check_args(spec, {"changes": {"llm.provider": "ollama"}, "apply_anyway": "yes"})


# -- the stub model server -------------------------------------------------------------


class StubModelServer:
    """
    A model server on loopback, on a port the OS picks, in this process.
    ``routes`` maps a path to its JSON answer; any other path is 404. LM
    Studio's list and llama-server's recorded fixtures are served; Ollama's
    routes are not (a provider that does not answer). ``seen`` records each
    request's path and whether it carried the sentinel key.
    """

    def __init__(self) -> None:
        self.routes: dict[str, Any] = {
            "/api/v1/models": LMSTUDIO_MODELS,
            "/health": json.loads((FIXTURES / "llamacpp" / "health.json").read_text(encoding="utf-8")),
            "/v1/models": json.loads((FIXTURES / "llamacpp" / "models.json").read_text(encoding="utf-8")),
            "/props": json.loads((FIXTURES / "llamacpp" / "models_props.json").read_text(encoding="utf-8")),
        }
        self.seen: list[tuple[str, bool]] = []
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                with stub._lock:
                    stub.seen.append((path, self.headers.get("Authorization") == f"Bearer {SENTINEL}"))
                body = stub.routes.get(path)
                data = json.dumps(body if body is not None else {"error": "not found"}).encode("utf-8")
                self.send_response(200 if body is not None else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_POST = do_GET  # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="t16-stub-model", daemon=True)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def start(self) -> "StubModelServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)
        assert not self.thread.is_alive(), "the stub model server did not stop"


# -- fix round 1, I2: the API key follows a moved base URL only on the admin's word ----------


def _hosted_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, layer: Optional[dict[str, Any]],
                   external: Optional[dict[str, Any]] = None) -> Any:
    """This process's config with hosting on, the key a sentinel from the environment, and ``layer`` as admin.yaml."""
    import engine.config as config
    from tests import hosted_app

    _config_dir, data_dir = hosted_app.hosting_layer(
        monkeypatch, tmp_path, extra={"llm": {"provider": "openai_compat", "api_key": "${env:T16_KEY}"}}
    )
    monkeypatch.setenv("T16_KEY", SENTINEL)
    if external is not None:
        operator = tmp_path / "operator.yaml"
        operator.write_text(yaml.safe_dump(external), encoding="utf-8")
        monkeypatch.setenv("CLOCKWORK_CONFIG", str(operator))
    if layer is not None:
        (data_dir / "hosting").mkdir(parents=True, exist_ok=True)
        (data_dir / "hosting" / "admin.yaml").write_text(yaml.safe_dump(layer), encoding="utf-8")
    monkeypatch.setattr(config, "_instance", None)
    return config.get_config()


def test_the_key_is_withheld_from_a_base_url_moved_to_another_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sandbox_model_stub: Any
) -> None:
    """
    The admin layer moved llm.base_url to the NEW stub's origin, while the
    key was given for the OLD one: the key resolves empty, the page's source
    says withheld, and the new server is sent no Authorization header. With
    the admin's "send the API key to this host" (the layer's origin is the
    new one), it is sent.
    """
    import engine.config as config
    from engine.config import url_origin
    from engine.llm.providers import get_provider

    old, new = StubModelServer().start(), StubModelServer().start()
    new.routes["/v1/models"] = {"object": "list", "data": [{"id": "stub", "object": "model"}]}
    sandbox_model_stub(new.port)  # the one model server this test may dial (the old one is never asked)
    try:
        old_url, new_url = f"http://127.0.0.1:{old.port}/v1", f"http://127.0.0.1:{new.port}/v1"
        cfg = _hosted_config(
            monkeypatch, tmp_path, {"llm": {"base_url": new_url, "api_key_origin": url_origin(old_url)}}
        )
        assert cfg.get("llm.base_url") == new_url
        has_key = bool(cfg.get("llm.api_key"))
        assert has_key is False, "the key followed the base URL to another origin"
        assert cfg.withheld_key == ("environment", "T16_KEY")
        assert cfg.secret_source("llm.api_key") == ("", "")
        assert get_provider().health_probe(timeout=3)[0] is True
        assert ("/v1/models", True) not in new.seen and new.seen, new.seen

        # The admin sent the key there: the layer names the new origin.
        config.reset_config()
        cfg = _hosted_config(
            monkeypatch, tmp_path, {"llm": {"base_url": new_url, "api_key_origin": url_origin(new_url)}}
        )
        assert cfg.get("llm.api_key") == SENTINEL and cfg.withheld_key is None
        new.seen.clear()
        assert get_provider().health_probe(timeout=3)[0] is True
        assert ("/v1/models", True) in new.seen

        # An operator's own llm.base_url wins over the layer's: never withheld for the layer.
        config.reset_config()
        cfg = _hosted_config(
            monkeypatch,
            tmp_path,
            {"llm": {"base_url": new_url, "api_key_origin": url_origin(old_url)}},
            external={"llm": {"base_url": new_url}},
        )
        assert cfg.get("llm.api_key") == SENTINEL
    finally:
        config.reset_config()
        old.stop()
        new.stop()


def test_the_supervisor_records_where_the_key_may_go(tmp_path: Path) -> None:
    from engine.config import ConfigManager
    from engine.hosting.supervisor.llm import ModelServer

    cfg = ConfigManager({"llm": {"base_url": "http://10.0.0.1:1234/v1"}})
    layer = tmp_path / "admin.yaml"
    origin = ModelServer._key_origin
    moved = {"llm.base_url": "https://models.example:8443/v1"}
    # A move without the admin's word keeps the key with the origin in force.
    assert origin(None, cfg, moved, False, layer) == {"llm.api_key_origin": "http://10.0.0.1:1234"}
    # With it, the key goes to the new origin.
    assert origin(None, cfg, moved, True, layer) == {"llm.api_key_origin": "https://models.example:8443"}
    # A new path on the same origin needs nothing recorded.
    assert origin(None, cfg, {"llm.base_url": "http://10.0.0.1:1234/other"}, False, layer) == {}
    # A layer that already names the key's origin keeps it.
    layer.write_text(yaml.safe_dump({"llm": {"api_key_origin": "http://10.0.0.1:1234"}}), encoding="utf-8")
    assert origin(None, cfg, moved, False, layer) == {}
    assert origin(None, cfg, {"llm.lanes.narration": 2}, True, layer) == {}


def test_moving_the_base_url_asks_whether_the_key_goes_too_and_audits_the_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The front door's half: ``send_key`` reaches the supervisor only as the admin ticked it, audited."""
    from tests.hosting_instance import AdminDoor

    door = AdminDoor(monkeypatch, tmp_path)
    door.start()
    sent: list[dict[str, Any]] = []
    try:
        values = {
            "llm.provider": "lmstudio",
            "llm.base_url": "http://127.0.0.1:1234/v1",
            "llm.lanes.narration": 1,
            "llm.lanes.utility": 2,
            "llm.context_tokens": 8192,
            "llm.prefer_native": True,
            "llm.profiles.big.model": "",
            "llm.profiles.big.temperature": 0.8,
            "llm.profiles.big.max_tokens": 2048,
            "llm.profiles.big.reasoning_budget": 3200,
            "llm.profiles.big.reasoning": "on",
        }
        health = {
            "provider": "lmstudio", "base_url": "http://127.0.0.1:1234/v1", "ok": True, "detail": "",
            "key": {"set": True, "kind": "environment", "source": "CLOCKWORK_LLM_API_KEY", "withheld": False},
            "values": values, "locked": {}, "layer": {"path": "x", "keys": [], "version": "none"}, "declared": [],
        }
        door.server.handle("llm.health", lambda _c, _a: health)
        door.server.handle("llm.models", lambda _c, _a: {"models": [], "error": ""})
        door.server.handle("ops.list", lambda _c, _a: {"ops": []})

        def apply(_conn: Any, args: dict[str, Any]) -> dict[str, Any]:
            sent.append(dict(args))
            return {"op_id": f"op-{len(sent)}"}

        door.server.handle("llm.apply", apply)
        client = door.admin()
        page = client.get("/admin/model").get_data(as_text=True)
        assert "send the API key to this host" in page.lower() or "Send the API key to this host" in page
        form = _browser_form(page)
        assert form["version"] == "none" and form["was:llm.base_url"] == "http://127.0.0.1:1234/v1"
        for tick, expect in (("", False), ("1", True)):
            data = {**form, "llm.base_url": "http://models.example:8080/v1"}
            if tick:
                data["send_key"] = tick
            answer = client.post("/admin/model", data=data)
            assert answer.status_code == 303, answer.get_data(as_text=True)[:400]
            assert sent[-1]["send_key"] is expect and sent[-1]["changes"] == {"llm.base_url": "http://models.example:8080/v1"}
            said = client.get("/admin/model").get_data(as_text=True)
            assert ("WILL be sent" in said) is expect and ("will NOT be sent" in said) is not expect
        # A change on the same origin is no move: nothing to confirm, nothing recorded.
        answer = client.post("/admin/model", data={**form, "llm.base_url": "http://127.0.0.1:1234/v2", "send_key": "1"})
        assert answer.status_code == 303 and sent[-1]["send_key"] is False
        rows = [json.loads(line) for line in (door.data_dir / "hosting" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        started = [r["detail"] for r in rows if r["action"] == "llm.apply" and r["result"] == "started"]
        assert started == [{"apply_anyway": False, "send_key": False}, {"apply_anyway": False, "send_key": True},
                           {"apply_anyway": False}]
        # The page says a withheld key is withheld, and where it would come from.
        health["key"]["withheld"] = True
        page = client.get("/admin/model").get_data(as_text=True)
        assert "WITHHELD" in page and "CLOCKWORK_LLM_API_KEY" in page
    finally:
        door.stop()


@pytest.fixture(scope="module")
def stub() -> Iterator[StubModelServer]:
    server = StubModelServer().start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def instance(
    tmp_path_factory: pytest.TempPathFactory, stub: StubModelServer, sandbox_model_stub_module: Any
) -> Iterator[HostingInstance]:
    # The children's API key is the sandbox layer's own (fix round 1, I3: a
    # child has none otherwise): a chain to the sentinel in the environment.
    url = sandbox_model_stub_module(stub.port, api_key="${env:CLOCKWORK_LLM_API_KEY}")
    assert url.startswith("http://127.0.0.1:")
    yield from hosting_instance(
        tmp_path_factory,
        "admin_model",
        stories=[A, B],
        frontdoor="real",
        worker_module=SCRIPTED_WORKER,
        supervisor={
            "boot_seconds": 120,
            "health_failures": 5,
            "max_restarts": 5,
            "drain_seconds": DRAIN_SECONDS,
            "stop_seconds": 2,
            "shutdown_seconds": DRAIN_SECONDS + 2 + 7 + 10,  # + FRONTDOOR_STOP_RESERVE_SECONDS (T18)
        },
        hosting={
            "cookie_secure": False,
            "rate_limits": {
                "actions_per_minute": 1000,
                "logins_per_minute": 1000,
                "logins_per_minute_all": 1000,
                "admin_actions_per_minute": 1000,
            },
        },
        env={"CLOCKWORK_LLM_API_KEY": SENTINEL, "CLOCKWORK_PROBE_FORBID_RESET": "1"},
    )


@pytest.fixture(scope="module")
def passwords(instance: HostingInstance) -> dict[str, str]:
    found = {"root": instance.add_account("root", admin=True)}
    for name in ("ash", "birch", "cedar"):
        found[name] = instance.add_account(name)
    return found


@pytest.fixture(scope="module")
def admin(instance: HostingInstance, passwords: dict[str, str]) -> Iterator[httpx.Client]:
    http = instance.admin_http("root", passwords["root"])
    try:
        yield http
    finally:
        http.close()


# -- helpers ----------------------------------------------------------------------------


def _player(instance: HostingInstance, passwords: dict[str, str], name: str, slug: str) -> tuple[httpx.Client, str]:
    http = instance.http()
    assert login(http, name, passwords[name]).status_code == 303
    assert choose(http, slug).status_code == 303
    opened = http.post("/api/game/new", json={"seed": 4})
    assert opened.status_code == 200, opened.text[:300]
    return http, str(opened.json()["session_id"])


def _turn(http: httpx.Client, session_id: str, into: list[Any]) -> threading.Thread:
    thread = threading.Thread(
        target=lambda: into.append(http.post("/api/game/choice", json={"session_id": session_id, "choice_id": "a"})),
        name="admin-model-turn",
    )
    thread.start()
    return thread


class Held:
    """A turn in flight on ``slug``, its narration ticket held, until ``release``."""

    def __init__(self, instance: HostingInstance, passwords: dict[str, str], name: str, slug: str) -> None:
        self.instance = instance
        self.http, self.session_id = _player(instance, passwords, name, slug)
        self.hold = instance.control / f"worker-{slug}.hold"
        self.held = instance.control / f"worker-{slug}.held"
        self.answers: list[Any] = []
        self.thread: Optional[threading.Thread] = None

    def __enter__(self) -> "Held":
        self.held.unlink(missing_ok=True)
        self.hold.write_text("1", encoding="utf-8")
        self.thread = _turn(self.http, self.session_id, self.answers)
        self.instance.until(self.held.exists, 30, "the turn in flight")
        return self

    def release(self) -> None:
        self.hold.unlink(missing_ok=True)
        if self.thread is not None:
            self.thread.join(JOIN)
            assert not self.thread.is_alive(), "the held turn never finished"
        self.held.unlink(missing_ok=True)

    def __exit__(self, *_exc: Any) -> None:
        self.release()
        self.http.close()


_INPUT_RE = re.compile(r"<input\b([^>]*)/?>")
_SELECT_RE = re.compile(r"<select\b([^>]*)>(.*?)</select>", re.S)
_ATTR_RE = re.compile(r'([a-z_-]+)="([^"]*)"')


def _browser_form(page: str) -> dict[str, str]:
    """
    What a browser posts from the page's model form as it was rendered: every
    enabled input (hidden ones included, checkboxes left unticked) and every
    enabled select's selected option -- so a test posts exactly what the page
    showed (fix round 1, I1), whatever the page carries.
    """
    start = page.index('action="/admin/model"')
    form = page[start: page.index("</form>", start)]
    found: dict[str, str] = {}
    for raw in _INPUT_RE.findall(form):
        attrs = dict(_ATTR_RE.findall(raw))
        if " disabled" in raw or "name" not in attrs or attrs.get("type") == "checkbox":
            continue
        found[html.unescape(attrs["name"])] = html.unescape(attrs.get("value", ""))
    for raw, options in _SELECT_RE.findall(form):
        attrs = dict(_ATTR_RE.findall(raw))
        if " disabled" in raw or "name" not in attrs:
            continue
        chosen = re.search(r'<option value="([^"]*)" selected', options)
        found[html.unescape(attrs["name"])] = html.unescape(chosen.group(1)) if chosen else ""
    return found


def _post(admin: httpx.Client, fields: dict[str, str], page: Optional[str] = None) -> httpx.Response:
    """``POST /admin/model`` as a browser sends it from ``page`` (fetched now if not given), with ``fields`` edited."""
    form = _browser_form(page if page is not None else admin.get("/admin/model").text)
    form.update(fields)
    return admin.post("/admin/model", data=form)


def _apply(admin: httpx.Client, fields: dict[str, str], page: Optional[str] = None) -> tuple[str, float]:
    """``POST /admin/model``: the op id it queued and how long the POST took (it answers at once)."""
    began = time.monotonic()
    response = _post(admin, fields, page)
    took = time.monotonic() - began
    assert response.status_code == 303 and response.headers["location"] == "/admin/model", response.text[:600]
    page = admin.get("/admin/model")
    match = _OP_RE.search(page.text)
    assert match, page.text[:600]
    return match.group(1), took


def _refused(admin: httpx.Client, fields: dict[str, str], status: int, says: str) -> str:
    response = _post(admin, fields)
    assert response.status_code == status and says in response.text, (response.status_code, response.text[:800])
    assert "Nothing was written" in response.text
    return response.text


def _layer(instance: HostingInstance) -> Path:
    return instance.data_dir / "hosting" / "admin.yaml"


def _prev(instance: HostingInstance) -> Path:
    return instance.data_dir / "hosting" / "admin.yaml.prev"


def _read_layer(instance: HostingInstance) -> dict[str, Any]:
    return yaml.safe_load(_layer(instance).read_text(encoding="utf-8")) or {}


def _audit(instance: HostingInstance, action: str) -> list[dict[str, Any]]:
    path = instance.data_dir / "hosting" / "audit.jsonl"
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row["action"] == action]


def _outcome(instance: HostingInstance, op_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The apply's ``started`` row (the front door's) and its outcome (the supervisor's), one ref."""
    end = instance.until(
        lambda: next((r for r in _audit(instance, "llm.apply") if r["detail"].get("op_id") == op_id), None),
        15,
        f"the outcome row of {op_id}",
    )
    start = next(r for r in _audit(instance, "llm.apply") if r["ref"] == end["ref"] and r["result"] == "started")
    return start, end


def _llm(instance: HostingInstance, slug: str) -> dict[str, Any]:
    """What ``worker-<slug>``'s newest probe booted with (``<process>-<pid>.llm``)."""
    found = sorted(instance.control.glob(f"worker-{slug}-*.llm"), key=lambda p: p.stat().st_mtime_ns)
    assert found, f"worker-{slug} wrote no llm report"
    return json.loads(found[-1].read_text(encoding="utf-8"))


def _llm_of(instance: HostingInstance, slug: str, pid: int) -> Optional[dict[str, Any]]:
    path = instance.control / f"worker-{slug}-{pid}.llm"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _no_resets(instance: HostingInstance) -> None:
    resets = sorted(p.name for p in instance.control.glob("*.reset"))
    assert not resets, f"a serving process reset its config on the apply path: {resets}"


def _account_id(instance: HostingInstance, name: str) -> str:
    from engine.hosting.accounts import AccountStore

    account = AccountStore(instance.data_dir / "hosting").by_name(name)
    assert account is not None
    return str(account.id)


# -- the instance -------------------------------------------------------------------------


def test_the_page_shows_the_provider_its_health_models_and_the_key_as_present(
    instance: HostingInstance, admin: httpx.Client, stub: StubModelServer
) -> None:
    page = admin.get("/admin/model")
    assert page.status_code == 200, page.text[:300]
    text = page.text
    assert "lmstudio" in text and f"http://127.0.0.1:{stub.port}/v1" in text
    assert "<dd data-field=\"status\">ok</dd>" in text, text[:2000]
    assert "stub-model-7b" in text and "8192" in text and "tool_use" in text
    assert "set, from the environment (CLOCKWORK_LLM_API_KEY)" in text
    health = admin.get("/admin/api/health.json").json()
    assert health["status"] == "ok" and health["provider"] == "lmstudio"
    assert health["key"] == "set, from the environment (CLOCKWORK_LLM_API_KEY)"
    assert set(health) == {"provider", "base_url", "status", "detail", "latency_ms", "key", "error"}
    # The supervisor probed the stub with the key (it is used, only never shown).
    assert ("/api/v1/models", True) in stub.seen
    assert SENTINEL not in text and SENTINEL not in json.dumps(health)


def test_the_queue_page_shows_who_holds_and_who_waits_by_account(
    instance: HostingInstance, passwords: dict[str, str], admin: httpx.Client
) -> None:
    ash, birch = _account_id(instance, "ash"), _account_id(instance, "birch")
    waiter_http, waiter_session = _player(instance, passwords, "birch", B)
    waiting: list[Any] = []
    thread = None
    try:
        with Held(instance, passwords, "ash", A) as held:
            thread = _turn(waiter_http, waiter_session, waiting)  # narration has one slot: it waits
            data = instance.until(
                lambda: (lambda d: d if d["waiters"] else None)(admin.get("/admin/api/queue.json").json()),
                30,
                "a waiter",
            )
            narration = next(l for l in data["lanes"] if l["lane"] == "narration")
            assert narration == {"lane": "narration", "limit": 1, "paused": "", "held": 1, "waiting": 1}
            holder = next(h for h in data["holders"] if h["lane"] == "narration")
            assert (holder["story"], holder["account"], holder["name"]) == (A, ash, "ash")
            waiter = data["waiters"][0]
            assert (waiter["lane"], waiter["position"], waiter["story"], waiter["account"], waiter["name"]) == (
                "narration", 1, B, birch, "birch"
            )
            assert set(holder) == {"lane", "position", "story", "account", "name", "seconds"}
            assert set(data) == {"lanes", "holders", "waiters", "paused_stories", "closing_stories", "error"}
            page = admin.get("/admin/queue").text
            assert ash in page and birch in page and ">birch<" in page and ">ash<" in page
            # Never play text: no narration, choice or session in the page.
            assert "Mist clings" not in page and held.session_id not in page and "Walk on" not in page
            held.release()
    finally:
        if thread is not None:
            thread.join(JOIN)
        waiter_http.close()
    assert waiting and waiting[0].status_code == 200, "the waiting turn was not served once the slot freed"


def test_the_base_url_is_locked_and_every_bad_edit_is_refused_with_nothing_written(
    instance: HostingInstance, admin: httpx.Client
) -> None:
    from engine.hosting.admin.model import NOT_EDITABLE

    page = admin.get("/admin/model").text
    match = re.search(r'name="llm\.base_url" value="[^"]*" disabled />\s*</td>\s*<td><span class="locked">locked: set in <code>([^<]+)</code>', page)
    assert match, page[page.find("llm.base_url") - 200: page.find("llm.base_url") + 600]
    layer_file = Path(match.group(1))
    assert layer_file.name == "sandbox-config.yaml"
    _refused(admin, {"llm.base_url": "http://127.0.0.1:1/v1"}, 409, f"set in {layer_file}")
    _refused(admin, {"hosting.enabled": "false"}, 400, NOT_EDITABLE)
    _refused(admin, {"llm.api_key": "sk-anything"}, 400, NOT_EDITABLE)
    _refused(admin, {"llm.profiles.big.temperature": "warm"}, 400, "llm.profiles.big.temperature is refused")
    _refused(admin, {"llm.lanes.narration": "40"}, 400, "llm.lanes.narration must be a whole number from 1 to 16")
    _refused(admin, {"llm.provider": "openai"}, 400, "llm.provider must be one of")
    for url, says in (
        ("http://user:hunter2pass@127.0.0.1:1/v1", "user name or password"),
        ("http://127.0.0.1:1/v1?token=hunter2pass", "query"),
        ("http://127.0.0.1:1/v1#hunter2pass", "fragment"),
    ):
        text = _refused(admin, {"llm.base_url": url}, 400, says)
        assert "hunter2pass" not in text
    assert not _layer(instance).exists() and not _prev(instance).exists(), "a refused edit wrote the layer"
    refused = [r for r in _audit(instance, "llm.apply") if r["result"] == "refused"]
    assert len(refused) >= 9
    assert "hunter2pass" not in json.dumps(refused) and "sk-anything" not in json.dumps(refused)


def test_an_apply_answers_at_once_drains_first_then_writes_and_restarts_one_worker_at_a_time(
    instance: HostingInstance, passwords: dict[str, str], admin: httpx.Client
) -> None:
    before = {slug: instance.own_identity(f"worker-{slug}") for slug in (A, B)}
    mark = instance.mark()
    with Held(instance, passwords, "ash", A) as held:
        op_id, took = _apply(admin, {"llm.profiles.big.temperature": "0.55", "llm.lanes.narration": "2"})
        assert took < 5.0, f"the apply POST waited {took:.1f}s"
        instance.until(lambda: instance.op(op_id)["status"] == "draining", 15, "draining")
        # A second apply while one runs is refused at once, nothing sent on.
        second = _post(admin, {"llm.lanes.utility": "3"})
        assert second.status_code == 409 and "another operation is running" in second.text
        threading.Event().wait(1.5)
        assert instance.op(op_id)["status"] == "draining"
        assert not _layer(instance).exists(), "the layer was written while a ticket was held"
        page = admin.get("/admin/model").text
        assert f"{op_id}, by root: <strong>draining</strong>" in page
        held.release()
        assert held.answers and held.answers[0].status_code == 200, "the turn in flight did not complete"
    op = instance.wait_op(op_id, timeout=180)
    assert op["status"] == "done", op
    assert [s["status"] for s in op["steps"]] == ["queued", "validating", "draining", "restarting", "done"]
    assert _read_layer(instance) == {"llm": {"lanes": {"narration": 2}, "profiles": {"big": {"temperature": 0.55}}}}
    assert not _prev(instance).exists(), "there was no layer before, so there is no .prev"

    # One at a time, in hosting.stories order: A down and back before B goes down.
    def at(pattern: str) -> int:
        instance.wait_for(pattern, 5, after=mark)
        return next(i for i in range(mark, len(instance.lines)) if re.search(pattern, instance.lines[i]))

    order = [
        at(rf"Restarting worker-{A} for the model settings"),
        at(rf"worker-{A} is serving under the new model settings"),
        at(rf"Restarting worker-{B} for the model settings"),
        at(rf"worker-{B} is serving under the new model settings"),
    ]
    assert order == sorted(order), order
    for slug in (A, B):
        assert instance.own_identity(f"worker-{slug}") != before[slug], f"worker-{slug} was not restarted"
        booted = _llm(instance, slug)
        assert booted["llm.profiles.big.temperature"] == 0.55 and booted["llm.lanes.narration"] == 2, booted
        row = instance.row(f"worker-{slug}")
        assert row["state"] == "ready" and row["restarts"] == 0, "an apply's restart was counted as a crash"
    snapshot = instance.call("queue.snapshot")["result"]
    assert next(l for l in snapshot["lanes"] if l["lane"] == "narration")["limit"] == 2
    assert not snapshot["paused_stories"] and not snapshot["lanes"][0]["paused"]
    start, end = _outcome(instance, op_id)
    assert start["actor_name"] == "root" and start["detail"] == {"apply_anyway": False}
    assert end["result"] == "ok" and end["actor"] == start["actor"]
    assert end["target"] == "llm.lanes.narration,llm.profiles.big.temperature"
    assert end["detail"]["llm.lanes.narration"] == {"old": 1, "new": 2}
    assert end["detail"]["llm.profiles.big.temperature"]["new"] == 0.55
    refused = [r for r in _audit(instance, "llm.apply") if r["detail"].get("error") == "busy"]
    assert refused and refused[-1]["result"] == "refused"
    _no_resets(instance)


def test_a_form_loaded_before_another_apply_is_refused_whole(
    instance: HostingInstance, admin: httpx.Client
) -> None:
    """
    Fix round 1 (I1): two tabs load the page; the first applies a
    temperature; the second, still showing the old temperature, changes only
    the utility lane. Before, its post carried the old temperature too, which
    differed from the value in force, and silently reverted the first apply.
    Now it is refused whole, "These settings changed since you loaded the
    page", and nothing is sent. A fresh page then sends only the field changed.
    """
    # The engine-authored refusal, by its text (``admin.model.STALE``).
    stale_text = "These settings changed since you loaded the page."
    first_tab = admin.get("/admin/model").text
    second_tab = admin.get("/admin/model").text
    op_id, _took = _apply(admin, {"llm.profiles.big.temperature": "0.6"}, first_tab)
    assert instance.wait_op(op_id, timeout=180)["status"] == "done"
    written = _layer(instance).read_bytes()
    stale = _post(admin, {"llm.lanes.utility": "3"}, second_tab)
    assert stale.status_code == 409 and stale_text in html.unescape(stale.text), (stale.status_code, stale.text[:600])
    assert _layer(instance).read_bytes() == written, "a stale form changed the layer"
    assert _read_layer(instance)["llm"]["profiles"]["big"]["temperature"] == 0.6
    refused = [r for r in _audit(instance, "llm.apply") if r["result"] == "refused"]
    assert refused[-1]["detail"] == {"reason": "stale"}
    # A page loaded now sends the one field changed, and nothing it left alone.
    op_id, _took = _apply(admin, {"llm.profiles.big.temperature": "0.55"})
    assert instance.wait_op(op_id, timeout=180)["status"] == "done"
    _start, end = _outcome(instance, op_id)
    assert end["target"] == "llm.profiles.big.temperature", end
    assert _read_layer(instance) == {"llm": {"lanes": {"narration": 2}, "profiles": {"big": {"temperature": 0.55}}}}


def test_a_drain_past_drain_seconds_refuses_and_writes_and_restarts_nothing(
    instance: HostingInstance, passwords: dict[str, str], admin: httpx.Client
) -> None:
    from engine.hosting.supervisor.llm import DRAIN_REFUSED

    written = _layer(instance).read_bytes()
    kept = _prev(instance).read_bytes()
    before = {slug: instance.own_identity(f"worker-{slug}") for slug in (A, B)}
    with Held(instance, passwords, "ash", A):
        op_id, _took = _apply(admin, {"llm.profiles.big.temperature": "0.65"})
        op = instance.wait_op(op_id, timeout=DRAIN_SECONDS + 20)
        assert op["status"] == "refused" and op["reason"] == DRAIN_REFUSED, op
        assert DRAIN_REFUSED in admin.get("/admin/model").text
    assert _layer(instance).read_bytes() == written and _prev(instance).read_bytes() == kept
    assert {slug: instance.own_identity(f"worker-{slug}") for slug in (A, B)} == before, "a refused apply restarted"
    snapshot = instance.call("queue.snapshot")["result"]
    assert not snapshot["paused_stories"] and not any(l["paused"] for l in snapshot["lanes"]), "left paused"
    _start, end = _outcome(instance, op_id)
    assert end["result"] == "refused" and end["detail"]["reason"] == DRAIN_REFUSED


def test_a_worker_restarted_for_another_reason_during_the_drain_boots_under_the_old_file(
    instance: HostingInstance, passwords: dict[str, str], admin: httpx.Client
) -> None:
    killed = instance.own_identity(f"worker-{B}")
    with Held(instance, passwords, "ash", A) as held:
        op_id, _took = _apply(admin, {"llm.profiles.big.temperature": "0.75"})
        instance.until(lambda: instance.op(op_id)["status"] == "draining", 15, "draining")
        instance.kill_child(f"worker-{B}")
        reborn = instance.until(
            lambda: (lambda ident: ident if ident != killed else None)(instance.own_identity(f"worker-{B}")),
            DRAIN_SECONDS,
            "worker-B restarted after its crash",
        )
        booted = instance.until(lambda: _llm_of(instance, B, reborn.pid), DRAIN_SECONDS, "its llm report")
        assert instance.op(op_id)["status"] == "draining", "the drain ended before the crash restart was seen"
        assert booted["llm.profiles.big.temperature"] == 0.55, "a worker booted during the drain read the new file"
        held.release()
    assert instance.wait_op(op_id, timeout=180)["status"] == "done"
    assert _llm(instance, B)["llm.profiles.big.temperature"] == 0.75
    assert _read_layer(instance)["llm"]["profiles"]["big"]["temperature"] == 0.75
    assert yaml.safe_load(_prev(instance).read_text(encoding="utf-8"))["llm"]["profiles"]["big"]["temperature"] == 0.55
    assert not list(_layer(instance).parent.glob("*.tmp")), "a temp file was left beside the layer"
    _no_resets(instance)


def test_a_new_provider_that_does_not_answer_is_refused_unless_applied_anyway(
    instance: HostingInstance, admin: httpx.Client
) -> None:
    from engine.hosting.supervisor.llm import NOT_ANSWERING

    written = _layer(instance).read_bytes()
    op_id, _took = _apply(admin, {"llm.provider": "ollama"})
    op = instance.wait_op(op_id, timeout=30)
    assert op["status"] == "refused" and op["reason"] == NOT_ANSWERING, op
    assert _layer(instance).read_bytes() == written
    _start, end = _outcome(instance, op_id)
    assert end["result"] == "refused" and end["detail"]["apply_anyway"] is False

    op_id, _took = _apply(admin, {"llm.provider": "ollama", "apply_anyway": "1"})
    assert instance.wait_op(op_id, timeout=180)["status"] == "done"
    assert _read_layer(instance)["llm"]["provider"] == "ollama"
    for slug in (A, B):
        assert _llm(instance, slug)["llm.provider"] == "ollama"
    start, end = _outcome(instance, op_id)
    assert start["detail"] == {"apply_anyway": True}
    assert end["result"] == "ok" and end["detail"]["apply_anyway"] is True
    assert end["detail"]["llm.provider"] == {"old": "lmstudio", "new": "ollama"}
    _no_resets(instance)


def test_a_worker_that_will_not_boot_under_the_new_file_rolls_back(
    instance: HostingInstance, admin: httpx.Client
) -> None:
    refuse = instance.control / f"worker-{B}.refuse-provider"
    refuse.write_text("llamacpp", encoding="utf-8")
    before = _layer(instance).read_bytes()
    # The earlier kill was a real crash, counted; the rollback must add none.
    crashes = {slug: instance.row(f"worker-{slug}")["restarts"] for slug in (A, B)}
    mark = instance.mark()
    try:
        op_id, _took = _apply(admin, {"llm.provider": "llamacpp"})
        op = instance.wait_op(op_id, timeout=240)
    finally:
        refuse.unlink(missing_ok=True)
    assert op["status"] == "rolled_back", op
    assert f"worker-{B} did not start" in op["reason"]
    assert _layer(instance).read_bytes() == before, "the previous file was not restored"
    assert _read_layer(instance)["llm"]["provider"] == "ollama"
    # A was restarted under the new file, then again under the old one; B
    # failed, then came back under the old one.
    instance.wait_for(rf"Restarting worker-{A} under the previous model settings", 5, after=mark)
    instance.wait_for(rf"Restarting worker-{B} under the previous model settings", 5, after=mark)
    seen_a = [json.loads(p.read_text(encoding="utf-8"))["llm.provider"]
              for p in sorted(instance.control.glob(f"worker-{A}-*.llm"), key=lambda p: p.stat().st_mtime_ns)]
    assert seen_a[-2:] == ["llamacpp", "ollama"], seen_a
    for slug in (A, B):
        assert _llm(instance, slug)["llm.provider"] == "ollama"
        row = instance.wait_state(f"worker-{slug}", "ready", timeout=60)
        assert row["restarts"] == crashes[slug], "a rollback's restart was counted as a crash"
    rollback = _audit(instance, "llm.rollback")
    assert [r["result"] for r in rollback[-2:]] == ["started", "ok"] and rollback[-1]["actor"] == "supervisor"
    assert rollback[-1]["ref"] == rollback[-2]["ref"] and rollback[-1]["detail"]["op_id"] == op_id
    _start, end = _outcome(instance, op_id)
    assert end["result"] == "error" and "did not start" in end["detail"]["reason"]
    snapshot = instance.call("queue.snapshot")["result"]
    assert not snapshot["paused_stories"] and not snapshot["closing_stories"]
    _no_resets(instance)


def test_a_rollback_never_starts_a_story_an_admin_stopped(instance: HostingInstance, admin: httpx.Client) -> None:
    """
    T16 re-review (M1), added in T17: an admin stops B; an apply that A will
    not boot under rolls back; B, which the apply never took down, is still
    stopped afterwards -- the rollback restarts only the children it took
    down itself. Then B is started again for the next test.
    """
    reply = instance.call("stories.stop", {"slug": B, "actor_name": "root"})
    assert reply["ok"], reply
    assert instance.wait_op(reply["result"]["op_id"], timeout=60)["status"] == "done"
    instance.wait_state(f"worker-{B}", "stopped", timeout=30)
    refuse = instance.control / f"worker-{A}.refuse-provider"
    refuse.write_text("llamacpp", encoding="utf-8")
    try:
        op_id, _took = _apply(admin, {"llm.provider": "llamacpp"})
        op = instance.wait_op(op_id, timeout=240)
    finally:
        refuse.unlink(missing_ok=True)
    try:
        assert op["status"] == "rolled_back", op
        assert _read_layer(instance)["llm"]["provider"] == "ollama"
        instance.wait_state(f"worker-{A}", "ready", timeout=60)
        threading.Event().wait(2.0)  # a stray start would have been spawned by now
        assert instance.row(f"worker-{B}")["state"] == "stopped", "the rollback started a story an admin had stopped"
    finally:
        started = instance.call("stories.start", {"slug": B, "actor_name": "root"})
        assert started["ok"], started
        instance.wait_op(started["result"]["op_id"], timeout=60)
        instance.wait_state(f"worker-{B}", "ready", timeout=180)
    assert _llm(instance, B)["llm.provider"] == "ollama"


def test_no_serving_process_reset_and_the_key_is_nowhere_it_could_be_read(
    instance: HostingInstance, admin: httpx.Client
) -> None:
    _no_resets(instance)
    for url in ("/admin", "/admin/model", "/admin/api/health.json", "/admin/queue", "/admin/api/queue.json",
                "/admin/stories", "/admin/audit", "/admin/users"):
        response = admin.get(url)
        assert response.status_code == 200, url
        assert SENTINEL not in response.text, url
    # Every file the instance wrote (logs, the audit log, the layer); the
    # lock files hold a byte-range lock and nothing else.
    for path in (instance.data_dir / "hosting").rglob("*"):
        if path.is_file() and path.suffix != ".lock":
            assert SENTINEL.encode() not in path.read_bytes(), path
    with instance._cond:
        lines = list(instance.lines)
    assert not [line for line in lines if SENTINEL in line]

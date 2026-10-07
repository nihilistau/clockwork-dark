"""
The deployment files, read statically and their hooks called with fakes
(v0.20.0 T13, spec §7.1, §9.5; T18 adds the Docker files).

``deploy/gunicorn.conf.py`` is executed here as gunicorn executes it (a
plain module run), never with gunicorn itself, which cannot run on Windows:

- one gthread worker, ``hosting.threads`` threads, the heartbeat and
  graceful timeouts, no access log;
- the bind per role (``CLOCKWORK_BUS_ROLE``): the front door on
  ``scene.clockwork.host``/``port`` (an explicit 0 kept: a port the OS
  picks), a worker on ``127.0.0.1:0``;
- ``on_starting`` refuses a gunicorn whose settings were overridden (``-w``,
  ``GUNICORN_CMD_ARGS``: a worker off loopback, the forwarded-header trust
  widened, another worker class or count, recycled workers); gunicorn
  trusts no forwarded header itself;
- ``post_worker_init`` reports the port gunicorn bound to the supervisor
  from the worker holding the bus, and makes a ``shutdown`` or a lost link
  stop the master too;
- at import it touches nothing of gunicorn's and nothing of the engine's
  but its config.

THE DOCKER FILES (v0.20.0 T18, spec §8, §9.5), read as text and YAML, never
built here (the build and its smoke run are ``tests/test_docker_smoke.py``,
opt-in):

- the ``Dockerfile``: the base pinned by digest, every install under
  ``constraints.txt``, the non-root ``USER`` (uid 10001), ``/data`` given to
  it BEFORE ``VOLUME``, the ``HEALTHCHECK``, the entrypoint and the
  supervisor as ``CMD``, the image's environment, no secret, and nothing
  copied that the image does not run;
- ``.dockerignore``: every secret and runtime path of spec §8.1;
- ``deploy/entrypoint.sh`` and ``scripts/start.sh``: ``100755`` in the index,
  LF, ``exec "$@"``;
- ``config/docker.yaml``: hosting on, the 30-minute idle release, every
  service but the model server off, nothing started from the container;
- ``docker-compose.yml``: 5573 published and nothing else, no
  ``CLOCKWORK_GAME``, ``init: true``, and a ``stop_grace_period`` above
  ``hosting.supervisor.shutdown_seconds`` as ``config/default.yaml`` and
  ``config/docker.yaml`` resolve it (read from both files, not hardcoded).
"""

from __future__ import annotations

import ast
import re
import runpy
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
CONF = REPO / "deploy" / "gunicorn.conf.py"
DOCKERFILE = REPO / "Dockerfile"
DOCKERIGNORE = REPO / ".dockerignore"
COMPOSE = REPO / "docker-compose.yml"
DOCKER_YAML = REPO / "config" / "docker.yaml"
DEFAULT_YAML = REPO / "config" / "default.yaml"
ENTRYPOINT = REPO / "deploy" / "entrypoint.sh"
HEALTHCHECK = REPO / "deploy" / "healthcheck.py"

#: The base the image is built FROM, by digest (T4's and T13's pin).
BASE = "python:3.11-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b"

#: The image's user (spec §8.1).
UID = 10001


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The shipped default.yaml alone (no config/local.yaml), plus a layer the test may write."""
    import engine.config as config

    directory = tmp_path / "config"
    directory.mkdir()
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_instance", None)
    monkeypatch.delenv("CLOCKWORK_CONFIG", raising=False)
    monkeypatch.delenv("CLOCKWORK_ENV", raising=False)
    return directory


def _conf(monkeypatch: pytest.MonkeyPatch, role: str) -> dict[str, Any]:
    monkeypatch.setenv("CLOCKWORK_BUS_ROLE", role)
    return runpy.run_path(str(CONF))


def test_one_gthread_worker_with_the_hosting_threads(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.config import get_config

    conf = _conf(monkeypatch, "worker")
    assert conf["workers"] == 1
    assert conf["worker_class"] == "gthread"
    assert conf["threads"] == int(get_config().get("hosting.threads")) == 32
    assert conf["timeout"] == 120 and conf["graceful_timeout"] == 30
    assert conf["accesslog"] is None
    assert conf["preload_app"] is False  # the app (and its bus) is the worker's


def test_the_bind_per_role(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.config as config
    from engine.hosting.boot import WORKER_HOST
    from engine.scenes.spec import scene_host, scene_port

    assert _conf(monkeypatch, "worker")["bind"] == [f"{WORKER_HOST}:0"]
    assert _conf(monkeypatch, "frontdoor")["bind"] == [f"{scene_host()}:{scene_port()}"]
    (isolated_config / "local.yaml").write_text(
        "scene:\n  clockwork:\n    host: '::'\n    port: 0\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "_instance", None)
    assert _conf(monkeypatch, "frontdoor")["bind"] == ["[::]:0"]


class _Server:
    """gunicorn's ``server`` as ``on_starting`` sees it: its resolved ``cfg``."""

    def __init__(self, conf: dict[str, Any], **changed: Any) -> None:
        values = {
            "workers": conf["workers"],
            "worker_class_str": conf["worker_class"],
            "max_requests": conf["max_requests"],
            "forwarded_allow_ips": [],  # gunicorn's reading of ""
            "secure_scheme_headers": dict(conf["secure_scheme_headers"]),
            "bind": list(conf["bind"]),
            **changed,
        }
        self.cfg = type("Cfg", (), values)()


def test_on_starting_refuses_any_worker_count_but_one(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conf = _conf(monkeypatch, "worker")
    conf["on_starting"](_Server(conf))
    with pytest.raises(RuntimeError) as caught:
        conf["on_starting"](_Server(conf, workers=2))
    assert "2 workers" in str(caught.value) and "exactly one" in str(caught.value)


@pytest.mark.parametrize(
    ("role", "changed", "named"),
    [
        ("worker", {"bind": ["0.0.0.0:8000"]}, "loopback only"),
        ("worker", {"bind": ["[::]:0"]}, "loopback only"),
        ("worker", {"worker_class_str": "sync"}, "worker class sync"),
        ("worker", {"max_requests": 1000}, "max_requests 1000"),
        ("worker", {"forwarded_allow_ips": ["*"]}, "forwarded_allow_ips"),
        ("worker", {"secure_scheme_headers": {"X-FORWARDED-PROTO": "https"}}, "secure_scheme_headers"),
        ("frontdoor", {"bind": ["0.0.0.0:8000"]}, "scene.clockwork.host/port"),
    ],
)
def test_on_starting_refuses_whatever_overrode_the_file(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, role: str, changed: dict[str, Any], named: str
) -> None:
    """
    Fix round 1, I3: GUNICORN_CMD_ARGS (or the command line) applies AFTER
    the file, so ``on_starting`` refuses a gunicorn whose resolved settings
    differ from it -- a worker rebound off loopback above all.
    """
    conf = _conf(monkeypatch, role)
    conf["on_starting"](_Server(conf))  # the file's own settings start
    with pytest.raises(RuntimeError) as caught:
        conf["on_starting"](_Server(conf, **changed))
    assert named in str(caught.value) and "GUNICORN_CMD_ARGS" in str(caught.value)


def test_gunicorn_trusts_no_forwarded_header(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fix round 1, I2: gunicorn's default trusts X-Forwarded-Proto (and
    SCRIPT_NAME) from any loopback peer, before the engine's own layers run;
    the file trusts none, leaving spec §7.3's one decision to the engine.
    """
    for role in ("worker", "frontdoor"):
        conf = _conf(monkeypatch, role)
        assert conf["forwarded_allow_ips"] == ""
        assert conf["secure_scheme_headers"] == {}
        assert conf["max_requests"] == 0


def test_post_worker_init_reports_the_bound_port_and_ties_the_master_to_the_bus(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.hosting import BUS_EXTENSION
    from engine.hosting import boot
    from engine.hosting import bus as bus_module

    conf = _conf(monkeypatch, "worker")
    sent: list[tuple[str, dict[str, Any]]] = []

    class Bus:
        on_shutdown: Any = None
        on_lost: Any = None

        def request(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
            sent.append((op, args))
            return {}

    class App:
        extensions = {BUS_EXTENSION: Bus()}

    class Socket:
        def getsockname(self) -> tuple[str, int]:
            return ("127.0.0.1", 43210)

    from engine.hosting import process_identity

    # The master is noted by its IDENTITY when the worker is ready, and is
    # signalled only through process_identity.terminate (T15 fix round 2,
    # N1): both stood in for here, so no real pid 4242 is ever looked at.
    noted = process_identity.Identity(4242, 1234.5)
    monkeypatch.setattr(process_identity, "identify", lambda pid: noted if pid == 4242 else None)
    killed: list[tuple[Any, int]] = []
    monkeypatch.setattr(process_identity, "terminate", lambda who, sig=signal.SIGTERM: killed.append((who, sig)) or True)
    monkeypatch.setattr(boot.os, "kill", lambda pid, sig: pytest.fail("a bare pid was signalled"))
    worker = type("Worker", (), {"sockets": [Socket()], "wsgi": App(), "ppid": 4242})()
    conf["post_worker_init"](worker)
    assert sent == [("ready", {"port": 43210})]
    bus = App.extensions[BUS_EXTENSION]
    exits: list[int] = []
    monkeypatch.setattr(bus_module, "_exit_process", exits.append)
    bus.on_shutdown()
    bus.on_lost()
    assert killed == [(noted, signal.SIGTERM), (noted, signal.SIGTERM)]
    assert exits == [0, bus_module.LIFELINE_EXIT_CODE]


def test_the_conf_imports_nothing_but_the_engine_s_config() -> None:
    tree = ast.parse(CONF.read_text(encoding="utf-8"))
    top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = sorted(
        {alias.name for node in top if isinstance(node, ast.Import) for alias in node.names}
        | {node.module or "" for node in top if isinstance(node, ast.ImportFrom)}
    )
    assert names == ["engine.config", "ipaddress", "os"], names
    # The hooks import lazily, when gunicorn calls them: the boot module only.
    lazy = sorted(
        {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} - set(names)
    )
    assert lazy == ["engine.hosting.boot"], lazy


def test_reading_the_conf_loads_no_engine_module_but_config(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def loaded(prefix: str) -> set[str]:
        return {m for m in sys.modules if m == prefix or m.startswith(prefix + ".")}

    engine_before, gunicorn_before = loaded("engine"), loaded("gunicorn")
    _conf(monkeypatch, "frontdoor")
    added = loaded("engine") - engine_before
    assert added <= {"engine", "engine.config"}, sorted(added)
    # Where gunicorn is installed, an earlier test may have imported it: the
    # conf must add nothing of its own.
    assert loaded("gunicorn") == gunicorn_before


# -- the Dockerfile (v0.20.0 T18) ------------------------------------------------------


def _instructions() -> list[tuple[int, str, str]]:
    """``(stage, INSTRUCTION, arguments)`` in order: continuations joined, comments dropped."""
    lines: list[str] = []
    pending = ""
    for raw in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        if stripped.startswith("#"):
            continue  # a comment inside a continued instruction
        if stripped.endswith("\\"):
            pending += stripped[:-1].rstrip() + " "
            continue
        lines.append(pending + stripped)
        pending = ""
    assert not pending, "the Dockerfile ends inside a continued line"
    found: list[tuple[int, str, str]] = []
    stage = -1
    for line in lines:
        keyword, _, rest = line.partition(" ")
        keyword = keyword.upper()
        if keyword == "FROM":
            stage += 1
        found.append((stage, keyword, rest.strip()))
    return found


def _final(keyword: str) -> list[str]:
    instructions = _instructions()
    last = max(stage for stage, _, _ in instructions)
    return [rest for stage, key, rest in instructions if stage == last and key == keyword]


def test_every_stage_is_built_from_the_pinned_base() -> None:
    froms = [rest for _, key, rest in _instructions() if key == "FROM"]
    assert len(froms) >= 2, "a multi-stage build (spec §8.1)"
    for rest in froms:
        assert rest.split()[0] == BASE, rest


def test_every_install_is_held_to_the_constraints() -> None:
    runs = [rest for _, key, rest in _instructions() if key == "RUN"]
    installs = [segment for run in runs for segment in run.split("&&") if "pip install" in segment]
    assert installs, "the image installs its requirements"
    for segment in installs:
        assert "-c constraints.txt" in segment, segment
    assert any("-r requirements-server.txt" in segment for segment in installs)
    assert not any("requirements.txt " in segment.replace("requirements-server.txt", "") for segment in installs)
    assert "apt-get" not in " ".join(runs)  # no system package is fetched (T18 manifest row 3)


def test_the_image_runs_as_its_own_user_and_data_is_theirs_before_the_volume() -> None:
    instructions = _instructions()
    last = max(stage for stage, _, _ in instructions)
    final = [(key, rest) for stage, key, rest in instructions if stage == last]
    users = [rest for key, rest in final if key == "USER"]
    assert users and users[-1] not in {"root", "0", "0:0"} and users[-1].split(":")[0] == str(UID)
    runs = " ".join(rest for key, rest in final if key == "RUN")
    assert f"--uid {UID}" in runs and f"--gid {UID}" in runs
    keys = [key for key, _ in final]
    chown = next(i for i, (key, rest) in enumerate(final) if key == "RUN" and f"chown {UID}:{UID} /data" in rest)
    volume = keys.index("VOLUME")
    assert chown < volume < keys.index("USER")
    assert final[volume][1] == "/data"
    # Nothing after the USER line runs as root again.
    assert all(key != "USER" or rest == users[-1] for key, rest in final[keys.index("USER"):])


def test_the_image_s_environment_entrypoint_command_and_health() -> None:
    env = " ".join(_final("ENV"))
    for setting in ("CLOCKWORK_ENV=docker", "CLOCKWORK_DATA_DIR=/data", "CLOCKWORK_CONFIG=/data/config.yaml",
                    "HF_HOME=/data/cache/hf", "PYTHONPATH=/app"):
        assert setting in env, setting
    # Absolute (fix round 1, M5): a `docker run -w` elsewhere breaks neither.
    assert _final("ENTRYPOINT") == ['["/app/deploy/entrypoint.sh"]']
    assert _final("CMD") == ['["python", "-m", "engine.hosting.supervisor"]']
    assert _final("EXPOSE") == ["5573"]
    (health,) = _final("HEALTHCHECK")
    assert 'CMD ["python", "/app/deploy/healthcheck.py"]' in health
    assert "--start-period=" in health
    assert '/api/health"' in HEALTHCHECK.read_text(encoding="utf-8")


# -- the healthcheck (fix round 1, I1) -------------------------------------------------------


def _health(isolated_config: Path, monkeypatch: pytest.MonkeyPatch, host: str, port: int, env: str) -> Any:
    import engine.config as config

    (isolated_config / "local.yaml").write_text(
        yaml.safe_dump({"scene": {"clockwork": {"host": host, "port": port}}}), encoding="utf-8"
    )
    if env:
        monkeypatch.setenv("CLOCKWORK_ENV", env)
    else:
        monkeypatch.delenv("CLOCKWORK_ENV", raising=False)
    monkeypatch.setattr(config, "_instance", None)
    return runpy.run_path(str(HEALTHCHECK))


@pytest.fixture
def health_server() -> Any:
    """A server on 127.0.0.1 that answers GET /api/health 200, as a live front door would."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            ok = self.path == "/api/health"
            body = b'{"status": "ok"}' if ok else b"{}"
            self.send_response(200 if ok else 404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, name="t18-health", daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(10)
        assert not thread.is_alive()


@pytest.mark.loopback
def test_the_healthcheck_asks_a_wildcard_front_door_on_loopback(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, health_server: Any
) -> None:
    port = int(health_server.server_address[1])
    check = _health(isolated_config, monkeypatch, "0.0.0.0", port, "docker")
    assert check["health_url"]() == (f"http://127.0.0.1:{port}/api/health", "")
    assert check["main"]() == 0


@pytest.mark.loopback
def test_the_healthcheck_ignores_proxy_environment_variables(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, health_server: Any
) -> None:
    """Final review, finding 3: a proxy in the environment must not take the loopback request."""
    import socket

    with socket.socket() as dead:
        dead.bind(("127.0.0.1", 0))  # bound, never listening: a proxy that refuses
        proxy = f"http://127.0.0.1:{dead.getsockname()[1]}"
        for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
            monkeypatch.setenv(name, proxy)
        for name in ("no_proxy", "NO_PROXY"):
            monkeypatch.delenv(name, raising=False)
        port = int(health_server.server_address[1])
        check = _health(isolated_config, monkeypatch, "0.0.0.0", port, "docker")
        assert check["main"]() == 0


@pytest.mark.loopback
def test_in_the_image_a_loopback_front_door_is_unhealthy_though_it_answers(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, health_server: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    The front door answers 200 on 127.0.0.1, but in the image nothing
    published can reach the container's loopback: unhealthy, and why. The
    same bind outside the image is healthy.
    """
    port = int(health_server.server_address[1])
    check = _health(isolated_config, monkeypatch, "127.0.0.1", port, "docker")
    assert check["main"]() == 1
    assert "the published port reaches nothing" in capsys.readouterr().err
    outside = _health(isolated_config, monkeypatch, "127.0.0.1", port, "")
    assert outside["main"]() == 0


@pytest.mark.loopback
def test_the_healthcheck_fails_when_nothing_answers(isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])  # bound, never listening: refused
        check = _health(isolated_config, monkeypatch, "0.0.0.0", port, "docker")
        assert check["main"]() == 1


def test_the_image_holds_no_secret_and_copies_only_what_it_runs() -> None:
    instructions = _instructions()
    declared = " ".join(rest for _, key, rest in instructions if key in {"ENV", "ARG", "LABEL"})
    for secret in ("SECRET_KEY", "API_KEY", "TOKEN", "PASSWORD"):
        assert secret not in declared.upper(), secret
    copied = [rest for _, key, rest in instructions if key == "COPY" and not rest.startswith("--from")]
    sources = {part for rest in copied for part in rest.split()[:-1]}
    assert sources == {
        "requirements-server.txt", "constraints.txt", "engine/", "games/", "content/", "deploy/",
        "config/default.yaml", "config/docker.yaml", "launcher.py",
        "scripts/users.py", "scripts/doctor.py", "scripts/seed_lore.py",
    }, sorted(sources)
    runs = " ".join(rest for _, key, rest in instructions if key == "RUN")
    assert "seed_lore.py" in runs  # every shipped story's lore index, built in (spec §8.1)


# -- .dockerignore ---------------------------------------------------------------------


def _ignored() -> list[str]:
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_dockerignore_keeps_every_secret_and_runtime_path_out() -> None:
    patterns = _ignored()
    assert not any(p.startswith("!") for p in patterns), "no exception reopens a fenced path"
    for required in (
        ".git", ".venv", "**/node_modules", "ui/", "tests/", "Design_files/", "data/",
        "config/local.yaml", "llm_api_key.txt", "lmstudio.txt", "*.key", "**/*.key",
        "*.token", "**/*.token", ".env*", "**/.env*", "games/*/data/lore/*.db",
    ):
        assert required in patterns, required


# -- the entrypoint and the start script -------------------------------------------------


def _index_mode(path: str) -> str:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("no git history to read the index from")
    found = subprocess.run(
        ["git", "ls-files", "-s", "--", path], cwd=REPO, capture_output=True, text=True, timeout=30
    )
    line = found.stdout.strip()
    if not line:
        pytest.skip(f"{path} is not in the index yet")
    return line.split()[0]


@pytest.mark.parametrize("path", ["deploy/entrypoint.sh", "scripts/start.sh"])
def test_the_shell_scripts_are_executable_in_the_index(path: str) -> None:
    assert _index_mode(path) == "100755", path


def test_the_entrypoint_is_posix_sh_that_execs_its_arguments() -> None:
    raw = ENTRYPOINT.read_bytes()
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert "set -eu" in text
    assert text.rstrip().splitlines()[-1] == 'exec "$@"'
    assert '[ "$$" = "1" ]' in text and "--init" in text  # warns with no init (fix round 1, M5)
    assert f"chown -R {UID}:{UID}" in text  # the fix it names for a root-owned bind mount
    # Only the image's own default config path is made, never a path an operator set.
    assert '"${CLOCKWORK_CONFIG:-}" = "$data/config.yaml"' in text
    for bashism in ("[[", "function ", "source ", "local "):
        assert bashism not in text, bashism


# -- config/docker.yaml --------------------------------------------------------------------


def _layer() -> dict[str, Any]:
    data = yaml.safe_load(DOCKER_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_the_docker_layer_turns_hosting_on_and_every_other_service_off(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import engine.config as config
    from engine.hosting.config import load

    shipped = yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8"))["stack"]["services"]
    layer = _layer()
    services = layer["stack"]["services"]
    assert set(services) == set(shipped), "every shipped service is named"
    for name, row in services.items():
        assert row["manage"] is False, name
        assert row["enabled"] is (name == "llm"), name

    (isolated_config / "docker.yaml").write_text(DOCKER_YAML.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("CLOCKWORK_ENV", "docker")
    monkeypatch.setattr(config, "_instance", None)
    cfg = config.get_config()
    assert cfg.get("hosting.enabled") is True
    assert int(cfg.get("session.idle_ttl_minutes")) == 30
    assert cfg.get("scene.clockwork.host") == "0.0.0.0"
    assert cfg.get("llm.base_url") == "http://host.docker.internal:1234/v1"
    # No faster-whisper in the image (fix round 1, M6): the HTTP provider, with nothing to call.
    assert cfg.get("stt.provider") == "voxtral_http"
    assert load(cfg).enabled is True  # the closed hosting: schema accepts the image's settings
    for name in shipped:
        assert bool(cfg.get(f"stack.services.{name}.enabled")) is (name == "llm"), name
        assert cfg.get(f"stack.services.{name}.manage") is False, name


# -- docker-compose.yml ----------------------------------------------------------------------


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _seconds(value: Any) -> float:
    """A compose duration (``210s``, ``3m30s``, ``1h``) in seconds."""
    text = str(value).strip()
    parts = re.findall(r"(\d+(?:\.\d+)?)(h|ms|m|s|us)", text)
    assert parts and "".join(n + u for n, u in parts) == text, text
    scale = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001, "us": 0.000001}
    return sum(float(n) * scale[u] for n, u in parts)


def _shutdown_seconds() -> float:
    """``hosting.supervisor.shutdown_seconds`` as the image resolves it: default.yaml, then docker.yaml."""
    from engine.config import deep_merge

    merged = deep_merge(yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8")), _layer())
    return float(merged["hosting"]["supervisor"]["shutdown_seconds"])


def test_the_game_service_publishes_the_front_door_alone() -> None:
    services = _compose()["services"]
    game = services["game"]
    # On the host's LOOPBACK by default (fix round 1, I2; spec §8.2 amended):
    # wider is the operator's explicit edit, behind a reverse proxy.
    (published,) = game["ports"]
    host_ip, _, rest = str(published).rpartition(":")
    host_ip, _, host_port = host_ip.rpartition(":")
    assert (host_ip, host_port, rest) == ("127.0.0.1", "5573", "5573"), published
    assert "profiles" not in game, "the game is the default service"
    for name, service in services.items():
        if name != "game":
            assert "ports" not in service and "expose" not in service, name
            assert service.get("profiles"), f"{name} starts only under its profile"
    assert any(str(v).endswith(":/data") for v in game["volumes"])
    assert "host.docker.internal:host-gateway" in game["extra_hosts"]
    assert game.get("user") in (None, f"{UID}:{UID}"), "the image's own user"


@pytest.mark.parametrize("command", [["kill-master", "clockwork-dark"], ["resume", "clockwork-dark", "1", "1"]])
def test_the_smoke_probe_signals_nothing_outside_a_container(
    command: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix round 1 (M9): run by hand on a host serving an instance, it refuses before it looks."""
    from tests.probes import docker_smoke_probe as probe

    monkeypatch.setattr(probe, "_in_container", lambda: False)
    monkeypatch.setattr(probe, "_story_gunicorns", lambda slug: pytest.fail("it looked for processes"))
    monkeypatch.setattr(probe, "_signal", lambda row, sig: pytest.fail("it signalled"))
    assert probe.main(command) == 3
    assert "not inside a container" in capsys.readouterr().out


def test_the_game_service_is_hardened_and_never_pulled() -> None:
    """Fix round 1 (M3, M4): no privilege, a read-only root, built not pulled."""
    game = _compose()["services"]["game"]
    assert "no-new-privileges:true" in game["security_opt"]
    assert game["cap_drop"] == ["ALL"] and "cap_add" not in game
    assert game["read_only"] is True and "/tmp" in game["tmpfs"]
    assert game["pull_policy"] == "build"
    assert "privileged" not in game


def test_no_story_is_chosen_by_the_environment_and_no_secret_is_written() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    for service in _compose()["services"].values():
        env = service.get("environment") or []
        names = [str(item).split("=", 1)[0] for item in (env if isinstance(env, list) else list(env))]
        assert "CLOCKWORK_GAME" not in names
        # Secrets are passed through by NAME from the operator's shell, never given a value here.
        for item in env if isinstance(env, list) else [f"{k}={v}" for k, v in env.items()]:
            assert "=" not in str(item), item
    assert "CLOCKWORK_GAME" not in text.replace("CLOCKWORK_GAME for each worker", "")


def test_init_reaps_orphans_and_the_stop_grace_outlasts_the_supervisor_s_shutdown() -> None:
    game = _compose()["services"]["game"]
    assert game["init"] is True
    grace = _seconds(game["stop_grace_period"])
    assert grace > _shutdown_seconds(), (grace, _shutdown_seconds())


def test_the_vllm_service_is_a_profile_whose_tag_task_19_pins() -> None:
    vllm = _compose()["services"]["vllm"]
    assert vllm["profiles"] == ["vllm"]
    assert str(vllm["image"]).startswith("vllm/vllm-openai:")
    assert vllm["ipc"] == "host"
    (device,) = vllm["deploy"]["resources"]["reservations"]["devices"]
    assert device == {"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}
    assert "HF_TOKEN" in vllm["environment"]
    # T19 pinned what it ran live: no placeholder left, the tag by its digest,
    # and the command line Turing needed (docs/MODEL_SERVERS.md § vLLM).
    assert "PINNED-BY-T19" not in COMPOSE.read_text(encoding="utf-8")
    assert re.fullmatch(r"vllm/vllm-openai:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", str(vllm["image"]))
    command = [str(part) for part in vllm["command"]]
    for flag in ("--model", "--dtype", "--max-model-len", "--gpu-memory-utilization",
                 "--reasoning-parser"):
        assert flag in command, flag
    assert command[command.index("--dtype") + 1] == "half"
    assert command[command.index("--gpu-memory-utilization") + 1].startswith(
        "${VLLM_GPU_MEMORY_UTILIZATION"
    )

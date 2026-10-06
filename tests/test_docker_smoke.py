"""
The Docker image, run (v0.20.0 T18, spec §8, §9.8, §12): OPT-IN.

Skipped unless ``CLOCKWORK_DOCKER_SMOKE=1``, and then it needs a running
Docker engine and the image already built (``docker build -t
clockwork-dark .``): it never builds, pulls or pushes anything. It brings the
REAL ``docker-compose.yml`` up under its own project name
(``cwd-t18-smoke``), with one override -- the front door published on the
host's loopback, on a port the OS picks, instead of 5573 on every interface
-- and a ``/data/config.yaml`` serving two stories (``clockwork-dark``,
``hue-and-cry``), plain HTTP (``cookie_secure: false``) and a stub model
server INSIDE the container (``tests/probes/docker_smoke_probe.py stub``, on
its loopback: no model is called). Its two accounts are made in the
container with passwords from ``secrets``, held in this process's memory
and nowhere else. At the end it removes its own containers and volume
(``down -v``); the image is left.

In order (one container for the module):

1. the image runs as uid 10001, cannot write ``/app``, holds no secret, and
   serves the front door under gunicorn with a worker per story;
2. two accounts log in at the front door, pick a different story each, and
   play one turn each over the WebSocket, through the front door's relay,
   STREAMED (``narration_delta`` before ``turn_update``);
3. neither account can list, load, read or delete the other's run: each
   answer equals a missing id's, and the owner's run is untouched;
4. the admin's panel shows both live sessions, the queue while a turn
   holds the narration lane, the model server's health and the turns'
   timings;
5. ``host.docker.internal`` is measured against a stub bound to THIS
   host's loopback (spec §8.2: recorded either way, not asserted);
6. a story's gunicorn master SIGKILLed: its orphaned worker signals no
   process (it logs, or gunicorn's own "Parent changed" ends it), init reaps
   it, and the supervisor brings the story back (T15's stop_master check,
   under real gunicorn);
7. ``docker compose stop`` drains a turn in flight and the container exits
   0 within the stop grace, nothing killed.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("CLOCKWORK_DOCKER_SMOKE") != "1",
        reason="the Docker smoke test runs only with CLOCKWORK_DOCKER_SMOKE=1 (it needs Docker and the built image)",
    ),
    pytest.mark.skipif(shutil.which("docker") is None, reason="no docker on PATH"),
]

REPO = Path(__file__).resolve().parents[1]
PROJECT = "cwd-t18-smoke"
IMAGE = "clockwork-dark:latest"
PROBE = REPO / "tests" / "probes" / "docker_smoke_probe.py"
#: On the smoke's own /data volume: the root filesystem is read-only and /tmp
#: a tmpfs, which `docker cp` does not reach.
IN_CONTAINER_PROBE = "/data/docker_smoke_probe.py"
STUB_PORT = 18080
STORIES = ("clockwork-dark", "hue-and-cry")
#: alpha plays the first story and is the admin; beta the second.
ALPHA, BETA = "alpha", "beta"

#: What the smoke's config sets on the volume (no secret: the cookie key is generated there).
DATA_CONFIG = f"""\
hosting:
  stories: ["{STORIES[0]}", "{STORIES[1]}"]
  cookie_secure: false
  rate_limits:
    logins_per_minute: 1000
    logins_per_minute_all: 1000
    admin_actions_per_minute: 1000
llm:
  provider: openai_compat
  base_url: "http://127.0.0.1:{STUB_PORT}/v1"
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Stack:
    """The compose project this module started, and how to talk to it."""

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        override = workdir / "smoke.override.yml"
        override.write_text(
            "services:\n  game:\n    ports: !override\n"
            f'      - "127.0.0.1:{self.port}:5573"\n',
            encoding="utf-8",
        )
        self.compose = ["docker", "compose", "-p", PROJECT, "-f", str(REPO / "docker-compose.yml"),
                        "-f", str(override)]
        self.passwords: dict[str, str] = {}
        self.timings: dict[str, float] = {}

    def run(self, *args: str, timeout: float = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
        done = subprocess.run(
            [*self.compose, *args], cwd=REPO, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if check and done.returncode != 0:
            raise AssertionError(f"docker compose {' '.join(args[:3])} exited {done.returncode}: {done.stderr[-2000:]}")
        return done

    def exec(self, *argv: str, timeout: float = 60) -> str:
        return self.run("exec", "-T", "game", *argv, timeout=timeout).stdout

    def probe(self, *argv: str, timeout: float = 60) -> Any:
        return json.loads(self.exec("python", IN_CONTAINER_PROBE, *argv, timeout=timeout).strip().splitlines()[-1])

    def container_id(self) -> str:
        return self.run("ps", "-a", "-q", "game").stdout.strip()

    def logs(self) -> str:
        return self.run("logs", "--no-color", "game", timeout=60).stdout

    def process_log(self, process: str) -> str:
        return self.exec("sh", "-c", f"cat /data/hosting/logs/{process}.log* 2>/dev/null || true")

    def http(self) -> Any:
        import httpx

        return httpx.Client(base_url=self.base, trust_env=False, follow_redirects=False, timeout=30.0)

    def until(self, check: Callable[[], bool], seconds: float, what: str) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if check():
                    return
            except Exception:  # noqa: BLE001 -- the container may still be starting
                pass
            time.sleep(1.0)
        raise AssertionError(f"timed out after {seconds:.0f}s waiting for {what}")

    def healthy(self) -> bool:
        with self.http() as http:
            return http.get("/api/health", timeout=5).status_code == 200

    def ready(self) -> bool:
        """The front door healthy and every story's worker ``ready`` since the last start."""
        if not self.healthy():
            return False
        logs = self.logs()
        last = logs.rfind("Shutting down (operation=shutdown")
        tail = logs[last:] if last >= 0 else logs
        return all(f"worker-{slug} sent ready (operation=ready" in tail for slug in STORIES)


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, text=True, timeout=60)
    if found.returncode != 0:
        pytest.skip(f"{IMAGE} is not built (docker build -t clockwork-dark .)")
    workdir = tmp_path_factory.mktemp("docker_smoke")
    s = Stack(workdir)
    s.run("down", "-v", "--remove-orphans", timeout=300, check=False)  # a previous run's leftovers, ours only
    try:
        config = workdir / "config.yaml"
        config.write_text(DATA_CONFIG, encoding="utf-8")
        s.run("create", "--no-build", "--pull", "never", "game", timeout=120)
        s.run("cp", str(config), "game:/data/config.yaml")
        started = time.monotonic()
        s.run("start", "game", timeout=120)
        s.until(s.ready, 240, "the front door's /api/health and every story's worker")
        s.timings["boot_seconds"] = round(time.monotonic() - started, 1)
        s.run("cp", str(PROBE), f"game:{IN_CONTAINER_PROBE}")
        s.run("exec", "-d", "-T", "game", "python", IN_CONTAINER_PROBE, "stub", "--port", str(STUB_PORT))
        s.passwords = s.probe("accounts", f"{ALPHA}:admin", BETA)
        yield s
    finally:
        try:
            print("\n[docker smoke] timings:", json.dumps(s.timings))
        finally:
            s.run("down", "-v", "--remove-orphans", "--timeout", "210", timeout=400, check=False)


# -- helpers -----------------------------------------------------------------------------


def _login(stack: Stack, name: str, story: Optional[str] = None) -> Any:
    from tests.hosting_instance import choose, login

    http = stack.http()
    assert login(http, name, stack.passwords[name]).status_code == 303
    if story is not None:
        assert choose(http, story).status_code == 303
    return http


def _admin(stack: Stack) -> Any:
    from tests.hosting_instance import csrf_of

    http = _login(stack, ALPHA)
    page = http.get("/admin/reauth")
    assert page.status_code == 200, page.text[:200]
    answer = http.post("/admin/reauth", data={"csrf": csrf_of(page.text), "password": stack.passwords[ALPHA],
                                              "next": "/admin"})
    assert answer.status_code == 303, answer.text[:300]
    return http


def _new_run(http: Any) -> dict[str, Any]:
    opened = http.post("/api/game/new", json={"seed": 11, "player_name": "Wren"})
    assert opened.status_code == 200, opened.text[:300]
    return opened.json()


def _ws_turn(http: Any, base: str, run: dict[str, Any]) -> dict[str, Any]:
    """Connect over the WebSocket (as the browser does: no polling first), join, one choice."""
    from tests.engineio_wire import WebSocketClient

    choice = ((run.get("opening") or {}).get("choices") or [{"id": "a"}])[0]["id"]
    ws = WebSocketClient(http, base, timeout=120.0)
    try:
        ws.handshake()
        assert ws.connect()["type"] == "connect"
        mark = len(ws.received)
        ws.emit("join_session", {"session_id": run["session_id"]})
        ws.until(lambda e: e.get("name") in ("game_started", "error"))
        joined = ws.received[mark:]
        mark = len(ws.received)
        started = time.monotonic()
        ws.emit("player_choice", {"session_id": run["session_id"], "choice_id": choice})
        ws.until(lambda e: e.get("name") in ("turn_update", "turn_error") or e.get("type") == "close", timeout=180)
        turn = ws.received[mark:]
        seconds = time.monotonic() - started
    finally:
        ws.close()
    return {"joined": joined, "turn": turn, "seconds": seconds}


def _names(events: list[dict[str, Any]]) -> list[str]:
    return [str(e.get("name") or e.get("type")) for e in events]


def _assert_streamed(played: dict[str, Any]) -> dict[str, Any]:
    names = _names(played["turn"])
    assert "turn_update" in names, names
    first_update = names.index("turn_update")
    assert "narration_delta" in names[:first_update], f"the turn did not stream: {names}"
    update = next(e for e in played["turn"] if e.get("name") == "turn_update")["args"][0]
    assert update.get("streamed") is True
    return update


def _identities(killed: dict[str, Any]) -> set[tuple[int, int]]:
    """The killed master's and its workers' (pid, start time): a process, never a bare pid."""
    found = {(int(killed["master"]), int(killed["master_started"]))}
    found |= {(int(p), int(s)) for p, s in zip(killed["workers"], killed["workers_started"])}
    return found


#: Each account's run, kept for the later tests (filled by the turn test).
RUNS: dict[str, dict[str, Any]] = {}


# -- 1. the image ------------------------------------------------------------------------


def test_the_image_runs_unprivileged_with_no_secret_and_gunicorn_per_story(stack: Stack) -> None:
    assert stack.exec("id", "-u").strip() == "10001"
    denied = stack.run("exec", "-T", "game", "sh", "-c", "touch /app/written 2>/dev/null && echo yes || echo no")
    assert denied.stdout.strip() == "no", "the running user can write /app"
    inspected = json.loads(subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, text=True,
                                          timeout=60).stdout)[0]["Config"]
    names = [item.split("=", 1)[0] for item in inspected.get("Env") or []]
    assert not [n for n in names if any(w in n.upper() for w in ("SECRET", "API_KEY", "TOKEN", "PASSWORD"))], names
    assert inspected.get("User") == "10001:10001"
    rows = stack.probe("procs")
    assert rows[0]["pid"] == 1 and "init" in " ".join(rows[0]["argv"]), rows[0]  # docker-init (tini) is PID 1
    commands = [" ".join(r["argv"]) for r in rows]
    assert any("engine.hosting.supervisor" in c for c in commands)
    assert any("gunicorn" in c and "engine.hosting.frontdoor.wsgi:app" in c for c in commands)
    workers = [c for c in commands if "gunicorn" in c and "engine.hosting.wsgi:app" in c]
    # A master and its one gthread worker per story.
    assert len(workers) == 2 * len(STORIES), commands
    key = stack.exec("sh", "-c", "stat -c '%a %u' /data/hosting/secret_key").strip()
    assert key == "600 10001", key
    # Hardened (fix round 1, M3): a read-only root, a writable /tmp, no capability.
    root = stack.exec("sh", "-c", "touch /etc/written 2>/dev/null && echo yes || echo no").strip()
    scratch = stack.exec("sh", "-c", "touch /tmp/written && rm /tmp/written && echo yes || echo no").strip()
    assert (root, scratch) == ("no", "yes")
    caps = dict(line.split(":\t", 1) for line in stack.exec("cat", "/proc/1/status").splitlines() if ":\t" in line)
    assert int(caps["CapEff"].strip(), 16) == 0 and caps["NoNewPrivs"].strip() == "1", caps


def test_the_built_in_lore_is_read_by_the_running_user(stack: Stack) -> None:
    """Fix round 1 (M7): built as root at build time, read as uid 10001 on a read-only root."""
    for slug in STORIES:
        found = stack.probe("lore", slug, "the")
        assert found["uid"] == 10001 and found["count"] > 0 and found["hits"] > 0, (slug, found)


def test_the_doctor_runs_in_the_image(stack: Stack) -> None:
    """
    Fix round 1 (M1): the doctor inside the running container, and the form
    docs/HOSTING.md gives for a container that will not start (a run of its
    own, the entrypoint bypassed). No FAIL row.
    """
    for argv in (
        ("exec", "-T", "game", "python", "scripts/doctor.py"),
        ("run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "game", "scripts/doctor.py"),
    ):
        done = stack.run(*argv, timeout=180, check=False)
        rows = [line for line in done.stdout.splitlines() if "[FAIL]" in line]
        if argv[0] == "run":
            # A container of its own: the smoke's stub model server lives on
            # the RUNNING container's loopback, which this one cannot reach.
            rows = [line for line in rows
                    if f"127.0.0.1:{STUB_PORT}" not in line and not line.startswith("Something is broken")]
        assert rows == [], (argv[0], rows)
        assert "hosting block" in done.stdout and "accounts" in done.stdout, done.stdout[-1500:]
        print(f"\n[docker smoke] doctor ({argv[0]}) exit {done.returncode}, no FAIL row"
              f"{' but the unreachable stub' if argv[0] == 'run' else ''}")


# -- 2. two accounts, two stories, streamed over the WebSocket ---------------------------


def test_two_accounts_play_two_stories_streamed_over_the_websocket(stack: Stack) -> None:
    for name, story in ((ALPHA, STORIES[0]), (BETA, STORIES[1])):
        http = _login(stack, name, story)
        try:
            run = _new_run(http)
            played = _ws_turn(http, stack.base, run)
        finally:
            http.close()
        assert _names(played["joined"]) == ["game_started"], played["joined"]
        update = _assert_streamed(played)
        assert "Lamplight pools on the wet cobbles" in str(update.get("narration")), update.get("narration")
        stack.timings[f"turn_{story}_seconds"] = round(played["seconds"], 1)
        RUNS[name] = {"story": story, "session_id": run["session_id"], "save_id": run.get("save_id")}


# -- 3. ownership --------------------------------------------------------------------------


def test_neither_account_reaches_the_other_s_run(stack: Stack) -> None:
    assert set(RUNS) == {ALPHA, BETA}, "the turn test runs first"
    alpha = RUNS[ALPHA]
    owner = _login(stack, ALPHA, alpha["story"])
    other = _login(stack, BETA, alpha["story"])  # beta looks in alpha's story
    try:
        mine = owner.get("/api/saves")
        assert mine.status_code == 200
        saves = mine.json()
        rows = saves.get("saves", saves) if isinstance(saves, dict) else saves
        ids = [str(r.get("id") or r.get("save_id")) for r in rows]
        save_id = str(alpha.get("save_id") or (ids[0] if ids else ""))
        assert save_id and save_id in ids, (save_id, ids)

        theirs = other.get("/api/saves").json()
        their_rows = theirs.get("saves", theirs) if isinstance(theirs, dict) else theirs
        assert save_id not in json.dumps(their_rows)

        missing = "save_" + "0" * 12
        for method, path in (("POST", "/api/saves/{}/load"), ("DELETE", "/api/saves/{}")):
            real = other.request(method, path.format(save_id))
            none = other.request(method, path.format(missing))
            # Answered exactly as a missing id (a load 404, a delete {"deleted": false}).
            assert real.status_code == none.status_code, (method, real.status_code, none.status_code)
            assert real.text.replace(save_id, "<id>") == none.text.replace(missing, "<id>"), (method, real.text[:200])
            if method == "POST":
                assert real.status_code == 404, real.text[:200]
            else:
                assert real.json() == {"deleted": False}, real.text[:200]
        state = other.get("/api/game/state", params={"session_id": alpha["session_id"]})
        state_none = other.get("/api/game/state", params={"session_id": "s" * 32})
        assert state.status_code == state_none.status_code and state.status_code >= 400
        # alpha's run is still there.
        assert save_id in json.dumps(owner.get("/api/saves").json())
    finally:
        owner.close()
        other.close()


# -- 4. the admin panel --------------------------------------------------------------------


def test_the_admin_panel_shows_both_sessions_the_queue_health_and_timings(stack: Stack) -> None:
    admin = _admin(stack)
    try:
        sessions = admin.get("/admin/api/sessions.json")
        assert sessions.status_code == 200, sessions.text[:200]
        counts = {row["slug"]: row["sessions"] for row in sessions.json()["stories"]}
        assert all(counts.get(slug, 0) >= 1 for slug in STORIES), sessions.json()
        page = admin.get("/admin/sessions")
        assert page.status_code == 200
        for name, story in ((ALPHA, STORIES[0]), (BETA, STORIES[1])):
            assert name in page.text and story in page.text, (name, story)

        # The queue while beta's turn holds the narration lane (the stub streams for seconds).
        beta = _login(stack, BETA, STORIES[1])
        seen: list[dict[str, Any]] = []
        result: dict[str, Any] = {}

        def play() -> None:
            try:
                result["played"] = _ws_turn(beta, stack.base, _new_run(beta))
            except BaseException as exc:  # noqa: BLE001 -- reported below
                result["error"] = exc

        player = threading.Thread(target=play, name="t18-smoke-turn", daemon=True)
        player.start()
        try:
            stack.until(
                lambda: bool([h for h in (seen.append(admin.get("/admin/api/queue.json").json()) or seen[-1])["holders"]
                              if h["lane"] == "narration" and h["story"] == STORIES[1] and h["name"] == BETA]),
                90, "beta's turn holding the narration lane in the queue",
            )
        finally:
            player.join(240)
            beta.close()
        assert not player.is_alive(), "the turn did not end"
        assert "error" not in result, result.get("error")
        _assert_streamed(result["played"])

        health = admin.get("/admin/api/health.json")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ok" and not body["error"], body  # the stub answered as up
        assert body["provider"] == "openai_compat" and body["key"] == "not set"
        stack.timings["model_health_latency_ms"] = float(body.get("latency_ms") or 0)

        def timed() -> bool:
            metrics = admin.get("/admin/api/metrics.json").json()
            stories = {row.get("story") for row in metrics.get("durations") or []}
            return set(STORIES) <= stories

        stack.until(timed, 60, "both stories' turn timings in the metrics")
    finally:
        admin.close()


# -- 5. host.docker.internal (measured, recorded) -------------------------------------------


def test_host_docker_internal_reaches_a_loopback_bound_host_server_measured(stack: Stack) -> None:
    from tests.probes.docker_smoke_probe import StubModelServer

    server = StubModelServer("127.0.0.1", 0)
    thread = threading.Thread(target=server.server.serve_forever, name="t18-host-stub", daemon=True)
    thread.start()
    try:
        found = stack.probe("fetch", f"http://host.docker.internal:{server.port}/v1/models", timeout=60)
    finally:
        server.server.shutdown()
        server.server.server_close()
        thread.join(10)
    assert not thread.is_alive()
    reached = found.get("status") == 200 and "GET /v1/models" in server.seen
    print(f"\n[docker smoke] host.docker.internal -> a server bound to this host's 127.0.0.1: "
          f"{'reached' if reached else 'NOT reached'} ({found})")
    stack.timings["host_docker_internal_reached"] = 1.0 if reached else 0.0
    assert "status" in found or "error" in found


# -- 6. a killed gunicorn master -------------------------------------------------------------


def test_a_killed_master_s_orphan_signals_nobody_and_the_story_comes_back(stack: Stack) -> None:
    story = STORIES[1]
    killed = stack.probe("kill-master", story)
    assert "master" in killed, killed
    old = _identities(killed)
    assert len(old) == 2, killed  # the master and its one worker

    def gone() -> bool:
        return not old & {(r["pid"], r["started"]) for r in stack.probe("procs")}

    stack.until(gone, 60, "the killed master's orphaned worker to end and be reaped")

    def back() -> bool:
        rows = stack.probe("procs")
        fresh = [r for r in rows if "engine.hosting.wsgi:app" in r["argv"] and (r["pid"], r["started"]) not in old]
        return len(fresh) >= 2 * len(STORIES)

    stack.until(back, 180, "the supervisor to restart the story's master and worker")
    stack.until(stack.healthy, 60, "the front door healthy")
    zombies = [r for r in stack.probe("procs") if r["state"] == "Z"]
    assert zombies == [], zombies  # init reaped every child

    log = stack.process_log(f"worker-{story}")
    said = [line for line in log.splitlines()
            if "Parent changed" in line or "gunicorn master was not signalled" in line]
    print(f"\n[docker smoke] the orphan's own words: {said[-3:]}")
    assert said, "the orphaned worker left no trace of how it ended"
    # It never signalled the (reused, or foreign) pid: no "Terminating"/"Killing" of anything but the supervisor's own.
    assert not [line for line in log.splitlines() if "signalled" in line and "was not" not in line
                and "operation=stop_master" in line]

    # The restarted story serves a turn again.
    http = _login(stack, BETA, story)
    try:
        _assert_streamed(_ws_turn(http, stack.base, _new_run(http)))
    finally:
        http.close()


def test_a_frozen_orphan_woken_to_a_dead_master_and_a_closed_link_signals_nobody(stack: Stack) -> None:
    """
    T15's ``stop_master`` under real gunicorn (spec §14.3): the worker is
    SIGSTOPped, its master SIGKILLed, and the worker woken only once the
    supervisor has restarted the story, so it meets a re-parented life and a
    closed bus link at once. Whichever ends it -- ``stop_master``'s
    re-parented check or gunicorn's own "Parent changed" -- no process is
    signalled in the dead master's name, and init reaps it.
    """
    story = STORIES[0]
    killed = stack.probe("kill-master", story, "--freeze-worker")
    assert "master" in killed, killed
    old = _identities(killed)
    ((worker, worker_started),) = zip(killed["workers"], killed["workers_started"])

    def restarted() -> bool:
        fresh = [r for r in stack.probe("procs") if "engine.hosting.wsgi:app" in r["argv"]
                 and (r["pid"], r["started"]) not in old]
        return len(fresh) >= 2 * len(STORIES)

    stack.until(restarted, 180, "the supervisor to restart the story beside the frozen orphan")
    log_before = stack.process_log(f"worker-{story}")
    resumed = stack.probe("resume", story, str(worker), str(worker_started))
    assert resumed.get("resumed") == worker, resumed
    stack.until(lambda: (worker, worker_started) not in {(r["pid"], r["started"]) for r in stack.probe("procs")},
                60, "the woken orphan to end")
    zombies = [r for r in stack.probe("procs") if r["state"] == "Z"]
    assert zombies == [], zombies
    log = stack.process_log(f"worker-{story}")
    new = log[len(log_before):] if log.startswith(log_before) else log
    said = [line for line in new.splitlines()
            if "Parent changed" in line or "gunicorn master was not signalled" in line]
    print(f"\n[docker smoke] the frozen orphan, woken: {said[-3:]}")
    assert said, new[-2000:]
    assert not [line for line in new.splitlines() if "operation=stop_master" in line and "was not signalled" not in line]
    stack.until(stack.ready, 120, "the story serving again")
    http = _login(stack, ALPHA, story)
    try:
        _assert_streamed(_ws_turn(http, stack.base, _new_run(http)))
    finally:
        http.close()


# -- 7. stop: drained, clean, within the grace -------------------------------------------------


def test_stop_drains_a_turn_and_exits_cleanly_within_the_grace(stack: Stack) -> None:
    import yaml

    grace = str(yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
                ["services"]["game"]["stop_grace_period"])
    grace_seconds = float(grace.rstrip("s"))
    container = stack.container_id()
    http = _login(stack, ALPHA, STORIES[0])
    result: dict[str, Any] = {}

    run = _new_run(http)
    before = {row["save_id"]: row["turn_number"] for row in http.get("/api/saves").json()["saves"]}

    def play() -> None:
        try:
            result["played"] = _ws_turn(http, stack.base, run)
        except BaseException as exc:  # noqa: BLE001 -- the stop may close the socket first
            result["error"] = exc

    player = threading.Thread(target=play, name="t18-smoke-drain", daemon=True)
    player.start()
    try:
        admin = _admin(stack)
        try:
            stack.until(lambda: bool(admin.get("/admin/api/queue.json").json()["holders"]), 60, "a turn in flight")
        finally:
            admin.close()
        started = time.monotonic()
        stack.run("stop", "game", timeout=grace_seconds + 60)
        took = time.monotonic() - started
    finally:
        http.close()  # the stopped server's socket: the client's wait ends with it
        player.join(200)
    stack.timings["stop_seconds"] = round(took, 1)
    assert took < grace_seconds, (took, grace_seconds)
    state = json.loads(subprocess.run(["docker", "inspect", container], capture_output=True, text=True,
                                      timeout=60).stdout)[0]["State"]
    assert state["ExitCode"] == 0 and state["OOMKilled"] is False, state
    logs = stack.logs()
    assert "Shutting down (operation=shutdown" in logs and "Shut down (operation=shutdown)" in logs
    assert "did not drain" not in logs
    assert "Killing " not in logs and "Terminating " not in logs and "SIGKILL" not in logs
    for process in ("frontdoor", *(f"worker-{slug}" for slug in STORIES)):
        assert f"Stopped {process} (operation=stop, how=exited)" in logs, process
    print(f"\n[docker smoke] the client of the drained turn heard: "
          f"{_names(result['played']['turn']) if 'played' in result else repr(result.get('error'))[:200]}")
    # Fix round 1 (I3): the front door is stopped only after the workers'
    # drains, so the player mid-turn hears the turn's end before the close.
    assert "error" not in result, result.get("error")
    _assert_streamed(result["played"])
    logs_lines = logs.splitlines()
    door = max(i for i, line in enumerate(logs_lines) if "Stopped frontdoor (operation=stop" in line)
    for slug in STORIES:
        assert max(i for i, line in enumerate(logs_lines) if f"Stopped worker-{slug} (operation=stop" in line) < door

    # The turn in flight was DRAINED -- run to its end and saved -- not cut:
    # started again, the run's save has its turn.
    stack.run("start", "game", timeout=120)
    stack.until(stack.ready, 240, "the front door and the workers after the restart")
    again = _login(stack, ALPHA, STORIES[0])
    try:
        # The front door answers before the story's worker has warmed: wait for the story.
        stack.until(lambda: "saves" in again.get("/api/saves").json(), 180, "the story's worker after the restart")
        after = {row["save_id"]: row["turn_number"] for row in again.get("/api/saves").json()["saves"]}
    finally:
        again.close()
    grown = [sid for sid, turns in after.items() if turns > before.get(sid, -1) and turns >= 1]
    assert grown, (before, after)

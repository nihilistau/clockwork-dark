"""
The admin panel's Stories page and its operations (v0.20.0 T15, spec §14.8,
§14.3, §14.11, §9.10).

ONE instance for the module, every process real (``tests/hosting_instance.py``):
the supervisor, two workers (``tests/probes/scripted_worker.py``, whose
probe can hold a turn in flight or crash at its start) and the engine's own
front door, with ``drain_seconds`` shortened to 4. In order:

- a stop ``POST`` answers at once; the stop DRAINS -- a turn in flight
  completes, a turn queued behind it is answered busy, then the worker
  exits -- and the front door answers 503 once ``stories.changed`` arrives;
- a start brings it back, and the picker lists it again;
- a stop whose drain outlasts ``drain_seconds`` is shown ``refused`` and the
  story keeps serving;
- a story in a crash loop is held down; a restart clears the hold, and is not
  counted toward ``max_restarts``;
- every operation writes its audit rows: ``started`` by the front door
  before the op is sent, the outcome by the supervisor under the same ref.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Iterator

import httpx
import pytest

from tests.hosting_instance import SCRIPTED_WORKER, HostingInstance, choose, csrf_of, hosting_instance, login

A = "clockwork-dark"
B = "dev-story"
JOIN = 60.0
DRAIN_SECONDS = 4

_OP_RE = re.compile(r"queued as (op-\d+)")


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HostingInstance]:
    yield from hosting_instance(
        tmp_path_factory,
        "admin_stories",
        stories=[A, B],
        frontdoor="real",
        worker_module=SCRIPTED_WORKER,
        supervisor={
            "boot_seconds": 180,
            "health_failures": 5,
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


def _player(instance: HostingInstance, passwords: dict[str, str], name: str, slug: str) -> tuple[httpx.Client, str]:
    http = instance.http()
    assert login(http, name, passwords[name]).status_code == 303
    assert choose(http, slug).status_code == 303
    opened = http.post("/api/game/new", json={"seed": 4})
    assert opened.status_code == 200, opened.text[:300]
    return http, str(opened.json()["session_id"])


def _operate(admin: httpx.Client, action: str, slug: str) -> tuple[httpx.Response, str, float]:
    """``POST /admin/stories/<action>``: the response, its op id and how long it took."""
    token = csrf_of(admin.get("/admin/stories").text)
    began = time.monotonic()
    response = admin.post(f"/admin/stories/{action}", data={"csrf": token, "slug": slug})
    took = time.monotonic() - began
    # POST-redirect-GET (fix round 1, M6): the op's id is on the page it sends us to, once.
    assert response.status_code == 303 and response.headers["location"] == "/admin/stories", response.text[:500]
    page = admin.get("/admin/stories")
    match = _OP_RE.search(page.text)
    assert match, page.text[:500]
    assert not _OP_RE.search(admin.get("/admin/stories").text), "the note was shown twice"
    return page, match.group(1), took


def _audit(instance: HostingInstance, action: str, slug: str) -> list[dict[str, Any]]:
    path = instance.data_dir / "hosting" / "audit.jsonl"
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row["action"] == action and row["target"] == slug]


def _audited(instance: HostingInstance, action: str, slug: str, outcome: str, op_id: str) -> None:
    """The op's two rows: the front door's ``started`` and the supervisor's outcome, one ref, one admin."""
    rows = instance.until(
        lambda: (lambda found: found if any(r["detail"].get("op_id") == op_id for r in found) else None)(
            _audit(instance, action, slug)
        ),
        15,
        f"the {action} outcome row",
    )
    end = next(r for r in rows if r["detail"].get("op_id") == op_id)
    start = next(r for r in rows if r["ref"] == end["ref"] and r["result"] == "started")
    assert end["result"] == outcome, end
    for row in (start, end):
        assert row["actor_name"] == "root" and row["actor"].startswith("u_") and row["address"] == "127.0.0.1"


def _waiting(instance: HostingInstance, slug: str) -> int:
    reply = instance.call("queue.snapshot")
    assert reply["ok"], reply
    lane = next(l for l in reply["result"]["lanes"] if l["lane"] == "narration")
    return sum(1 for w in lane["waiters"] if w.get("story") == slug)


def _turn(http: httpx.Client, session_id: str, into: list[Any]) -> threading.Thread:
    thread = threading.Thread(
        target=lambda: into.append(http.post("/api/game/choice", json={"session_id": session_id, "choice_id": "a"})),
        name="admin-stories-turn",
    )
    thread.start()
    return thread


@pytest.mark.process
def test_a_stop_answers_at_once_drains_and_the_front_door_answers_503(
    instance: HostingInstance, passwords: dict[str, str], admin: httpx.Client
) -> None:
    first, first_run = _player(instance, passwords, "ash", A)
    second, second_run = _player(instance, passwords, "birch", A)
    hold = instance.control / f"worker-{A}.hold"
    held = instance.control / f"worker-{A}.held"
    held.unlink(missing_ok=True)
    hold.write_text("1", encoding="utf-8")
    in_flight: list[Any] = []
    queued: list[Any] = []
    threads: list[threading.Thread] = []
    try:
        threads.append(_turn(first, first_run, in_flight))
        instance.until(held.exists, 30, "the turn in flight")
        threads.append(_turn(second, second_run, queued))
        instance.until(lambda: _waiting(instance, A) == 1, 30, "the second turn queued")

        _response, op_id, took = _operate(admin, "stop", A)
        assert took < 3.0, f"the stop POST waited {took:.1f}s"
        instance.until(lambda: instance.op(op_id)["status"] == "draining", 10, "draining")
        page = admin.get("/admin/stories").text
        assert f"({op_id}, by root): draining" in page and "draining" in page
    finally:
        hold.unlink(missing_ok=True)
        for thread in threads:
            thread.join(JOIN)
        held.unlink(missing_ok=True)
    assert not any(t.is_alive() for t in threads)
    assert in_flight and in_flight[0].status_code == 200, "the turn in flight did not complete"
    assert queued and queued[0].status_code == 409, (queued[0].status_code, queued[0].text[:300])
    assert instance.wait_op(op_id)["status"] == "done"
    instance.wait_state(f"worker-{A}", "stopped")
    unavailable = instance.until(lambda: (lambda r: r if r.status_code == 503 else None)(first.get("/")), 15, "503")
    assert "stopped by the operator" in unavailable.text
    assert first.get("/api/games/active").json() == {"error": "story unavailable"}
    stories = admin.get("/admin/stories").text
    assert f"({op_id}, by root): done" in stories
    _audited(instance, "story.stop", A, "ok", op_id)
    first.close()
    second.close()


@pytest.mark.process
def test_a_start_brings_it_back_and_the_picker_lists_it(
    instance: HostingInstance, passwords: dict[str, str], admin: httpx.Client
) -> None:
    instance.wait_state(f"worker-{A}", "stopped")
    _response, op_id, took = _operate(admin, "start", A)
    assert took < 3.0
    assert instance.wait_op(op_id)["status"] == "done"
    row = instance.wait_state(f"worker-{A}", "ready", timeout=60)
    assert row["restarts"] == 0, "an admin's stop and start were counted as crashes"
    http = instance.http()
    try:
        assert login(http, "ash", passwords["ash"]).status_code == 303
        instance.until(lambda: 'action="/stories/clockwork-dark"' in http.get("/stories").text, 15, "the picker")
    finally:
        http.close()
    feed = admin.get("/admin/api/stories.json").json()
    row = next(r for r in feed["stories"] if r["slug"] == A)
    assert row["state"] == "ready" and row["op"] == "start" and row["op_status"] == "done"
    _audited(instance, "story.start", A, "ok", op_id)


@pytest.mark.process
def test_a_drain_past_drain_seconds_is_refused_and_the_story_keeps_serving(
    instance: HostingInstance, passwords: dict[str, str], admin: httpx.Client
) -> None:
    from engine.hosting.supervisor.server import DRAIN_REFUSED

    http, session_id = _player(instance, passwords, "cedar", B)
    hold = instance.control / f"worker-{B}.hold"
    held = instance.control / f"worker-{B}.held"
    held.unlink(missing_ok=True)
    hold.write_text("1", encoding="utf-8")
    answers: list[Any] = []
    thread = None
    try:
        thread = _turn(http, session_id, answers)
        instance.until(held.exists, 30, "the turn in flight")
        _response, op_id, took = _operate(admin, "stop", B)
        assert took < 3.0
        op = instance.wait_op(op_id, timeout=DRAIN_SECONDS + 15)
        assert op["status"] == "refused" and op["reason"] == DRAIN_REFUSED
        assert instance.row(f"worker-{B}")["state"] == "ready"
        page = admin.get("/admin/stories").text
        assert f"({op_id}, by root): refused" in page and DRAIN_REFUSED in page
    finally:
        hold.unlink(missing_ok=True)
        if thread is not None:
            thread.join(JOIN)
        held.unlink(missing_ok=True)
    assert answers and answers[0].status_code == 200
    assert http.get("/api/games/active").json()["active"] == B
    assert http.get("/api/game/state", params={"session_id": session_id}).status_code == 200
    http.close()
    _audited(instance, "story.stop", B, "refused", op_id)


@pytest.mark.process
def test_a_restart_clears_a_hold_down_and_is_not_counted(
    instance: HostingInstance, admin: httpx.Client
) -> None:
    crash = instance.control / f"worker-{B}.crash"
    crash.write_text("1", encoding="utf-8")
    try:
        _response, op_id, _took = _operate(admin, "restart", B)
        assert instance.wait_op(op_id, timeout=30)["status"] == "done"
        held_down = instance.wait_state(f"worker-{B}", "held_down", timeout=90)
        assert held_down["restarts"] == 2 and held_down["last_exit"] == 3 and held_down["held_down_at"] > 0
        page = admin.get("/admin/stories").text
        assert "held_down" in page and "code 3" in page
        _audited(instance, "story.restart", B, "ok", op_id)
    finally:
        crash.unlink(missing_ok=True)
    _response, revive, _took = _operate(admin, "restart", B)
    assert instance.wait_op(revive, timeout=30)["status"] == "done"
    row = instance.wait_state(f"worker-{B}", "ready", timeout=90)
    assert row["restarts"] == 0, "the admin's restart was counted, or the hold's history kept"
    _audited(instance, "story.restart", B, "ok", revive)
    held = [r for r in _audit(instance, "story.held_down", B)]
    assert [r["actor"] for r in held] == ["supervisor"]


@pytest.mark.loopback
def test_an_unanswered_operation_leaves_its_outcome_to_the_supervisor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """
    Fix round 1 (M3): a stop whose bus reply never comes may still have been
    queued, and then the supervisor writes its outcome under the ref; so the
    front door writes NO outcome (one per reference) and says it is
    unconfirmed. In this process (``AdminDoor``), its supervisor stand-in
    never answering. On 1261d42 the front door wrote ``refused``.
    """
    from engine.hosting.admin import stories as stories_module
    from tests.hosting_instance import AdminDoor

    door = AdminDoor(monkeypatch, tmp_path, hosting={"stories": [A]})
    door.start()
    try:
        door.server.handle_deferred("stories.stop", lambda _conn, _args, _answer: None)
        monkeypatch.setattr(stories_module, "OP_SECONDS", 0.5)
        client = door.admin()
        answer = client.post("/admin/stories/stop", data={"csrf": door.token(client), "slug": A})
        assert answer.status_code == 504 and "Not confirmed" in answer.get_data(as_text=True)
        path = door.data_dir / "hosting" / "audit.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        stops = [row for row in rows if row["action"] == "story.stop"]
        assert [row["result"] for row in stops] == ["started"], stops
    finally:
        door.stop()


@pytest.mark.process
def test_a_second_operation_while_one_runs_is_refused_and_audited(
    instance: HostingInstance, passwords: dict[str, str], admin: httpx.Client
) -> None:
    """One operation at a time: the second is refused at once, its started and refused rows written here."""
    http, session_id = _player(instance, passwords, "cedar", B)
    hold = instance.control / f"worker-{B}.hold"
    held = instance.control / f"worker-{B}.held"
    held.unlink(missing_ok=True)
    hold.write_text("1", encoding="utf-8")
    answers: list[Any] = []
    thread = None
    try:
        thread = _turn(http, session_id, answers)
        instance.until(held.exists, 30, "the turn in flight")
        _response, op_id, _took = _operate(admin, "stop", B)
        token = csrf_of(admin.get("/admin/stories").text)
        second = admin.post("/admin/stories/restart", data={"csrf": token, "slug": A})
        assert second.status_code == 409 and "another operation is running" in second.text
        refused = _audit(instance, "story.restart", A)
        assert [r["result"] for r in refused[-2:]] == ["started", "refused"]
        assert refused[-1]["ref"] == refused[-2]["ref"] and refused[-1]["detail"] == {"error": "busy"}
        assert instance.wait_op(op_id, timeout=DRAIN_SECONDS + 15)["status"] == "refused"
    finally:
        hold.unlink(missing_ok=True)
        if thread is not None:
            thread.join(JOIN)
        held.unlink(missing_ok=True)
        http.close()
    assert answers and answers[0].status_code == 200

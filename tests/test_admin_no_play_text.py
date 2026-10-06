"""
Metadata only, everywhere an admin looks (v0.20.0 T17, spec §14.10, §9.10).

ONE instance, every process real (``tests/hosting_instance.py``): the
supervisor, two workers (``tests/probes/scripted_worker.py``: the engine's
own hosted worker, its model scripted) and the engine's own front door, each
child recording every frame it sends the supervisor
(``CLOCKWORK_PROBE_BUS_TRACE``).

A SENTINEL string is played as the player's name, as typed actions, as a
manual save's label, inside the scripted model's narration and choices, as
the NAME OF A STAT the scripted model claims (so the Oracle records an
unearned claim under it), as the words of a scripted turn failure, and as the
name of a failed login; over several turns in two stories, a save, an error
and an admin's end of a session. Then:

- every ``/admin`` page and JSON a GET reaches (enumerated from the admin
  blueprint itself, so a page added later is fetched too) is read as an
  admin;
- the metrics database is dumped whole;
- the audit file is read whole;
- every frame the supervisor received from a child is read;

and the sentinel is in none of them. The same surfaces are shown to HOLD what
they should (the error's reference, the turns, the session the admin ended,
the claim counted with no name), so the test cannot pass on empty pages.

Rule 12 is the other half: the store keeps no text at all, so there is
nothing to rate, flag or filter (``tests/test_metrics_schema.py``).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest

from tests.engineio_wire import PollingClient
from tests.hosting_instance import SCRIPTED_WORKER, HostingInstance, choose, csrf_of, hosting_instance, login

A = "clockwork-dark"
B = "dev-story"

#: The play text: one word, so it fits a name (40 characters), a stat and a label.
SENTINEL = "Zq9Sentinel"

#: The scripted model's reply: the sentinel in the narration, a choice and the
#: NAME of a stat it claims (``stat_changes``), which the engine never applies
#: and the Oracle records as an unearned claim (``governance.R003``).
REPLY = (
    "```json\n"
    + json.dumps(
        {
            "narration": f"{SENTINEL} hums by the birch trunks.",
            "choices": [{"id": "a", "text": f"Follow {SENTINEL}"}, {"id": "b", "text": "Wait"}],
            "stat_changes": {SENTINEL: 50},
        }
    )
    + "\n```"
)


def _no_sentinel(where: str, text: str) -> None:
    assert SENTINEL.lower() not in text.lower(), f"the sentinel reached {where}"


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HostingInstance]:
    yield from hosting_instance(
        tmp_path_factory,
        "admin_no_play_text",
        stories=[A, B],
        frontdoor="real",
        worker_module=SCRIPTED_WORKER,
        supervisor={"boot_seconds": 180, "health_failures": 5},
        env={"CLOCKWORK_PROBE_BUS_TRACE": "1"},
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
def played(instance: HostingInstance) -> Iterator[dict[str, Any]]:
    """
    Everything a player does with the sentinel, and an admin's end of one of
    the sessions. ``{"admin": client, "ref": the failed turn's reference,
    "session_id": the session the admin ended}``.
    """
    (instance.control / "scripted.reply").write_text(REPLY, encoding="utf-8")
    root = instance.add_account("root", admin=True)
    wren = instance.add_account("wren")
    player = instance.http()
    admin = None
    try:
        # A failed login under the sentinel as a name: no such account.
        assert login(player, SENTINEL, "pw-not-a-password").status_code == 401
        assert login(player, "wren", wren).status_code == 303
        assert choose(player, A).status_code == 303
        opened = player.post("/api/game/new", json={"seed": 5, "player_name": SENTINEL})
        assert opened.status_code == 200, opened.text[:300]
        session_a = str(opened.json()["session_id"])
        for _ in range(2):
            turn = player.post("/api/game/choice", json={"session_id": session_a, "choice_id": "", "custom_text": f"{SENTINEL} waves"})
            assert turn.status_code == 200, turn.text[:300]
        assert SENTINEL in json.dumps(turn.json()), "the scripted narration did not carry the sentinel"
        saved = player.post("/api/saves", json={"session_id": session_a, "slot": SENTINEL})
        assert saved.status_code == 200, saved.text[:300]

        # The socket path (fix round 1, M7): a turn, and an action over the
        # input cap (refused_cap, through sockets.limit_action).
        poll = PollingClient(player, instance.base)
        try:
            poll.handshake()
            assert poll.connect()["type"] == "connect"
            poll.emit("join_session", {"session_id": session_a})
            poll.until(lambda e: e.get("name") in ("game_started", "error"))
            poll.emit("player_choice", {"session_id": session_a, "choice_id": "", "custom_text": f"{SENTINEL} sings"})
            assert poll.until(lambda e: e.get("name") in ("turn_update", "turn_error")).get("name") == "turn_update"
            poll.emit("player_choice", {"session_id": session_a, "choice_id": "", "custom_text": SENTINEL * 100})
            assert poll.until(lambda e: e.get("name") == "turn_error")
        finally:
            poll.close()
        # A resume (the session event `resumed`; the run it replaces `released`).
        save_id = str(saved.json().get("save_id") or "")
        resumed = player.post(f"/api/saves/{save_id}/load", json={})
        assert resumed.status_code == 200, resumed.text[:300]

        assert choose(player, B).status_code == 303
        opened = player.post("/api/game/new", json={"seed": 6, "player_name": SENTINEL})
        assert opened.status_code == 200, opened.text[:300]
        session_b = str(opened.json()["session_id"])
        fail = instance.control / f"worker-{B}.fail"
        fail.write_text(f"{SENTINEL} broke the turn", encoding="utf-8")
        try:
            failed = player.post("/api/game/choice", json={"session_id": session_b, "choice_id": "a"})
        finally:
            fail.unlink(missing_ok=True)
        assert failed.status_code == 500, failed.text[:300]
        _no_sentinel("the player's error text", failed.text)
        match = re.search(r"\(ref ([0-9a-f]{8})\)", failed.json()["error"])
        assert match, failed.text[:300]
        turn = player.post("/api/game/choice", json={"session_id": session_b, "choice_id": "a"})
        assert turn.status_code == 200, turn.text[:300]

        admin = instance.admin_http("root", root)
        token = csrf_of(admin.get("/admin/sessions").text)
        ended = admin.post("/admin/sessions/end", data={"csrf": token, "slug": B, "session_id": session_b})
        assert ended.status_code == 303, ended.text[:300]
        yield {"admin": admin, "ref": match.group(1), "session_id": session_b}
    finally:
        player.close()
        if admin is not None:
            admin.close()


def _get_pages() -> list[str]:
    """Every ``/admin`` GET rule with no variable part, from the blueprint itself."""
    from flask import Flask

    from engine.hosting.admin import admin_blueprint

    app = Flask("enumerate_admin")
    app.register_blueprint(admin_blueprint())
    return sorted(
        rule.rule
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/admin") and "GET" in (rule.methods or ()) and "<" not in rule.rule
    )


def _db(instance: HostingInstance) -> Path:
    return instance.data_dir / "hosting" / "metrics.sqlite3"


def _dump(path: Path) -> str:
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return "\n".join(db.iterdump())
    finally:
        db.close()


def _count(path: Path, sql: str) -> int:
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return int(db.execute(sql).fetchone()[0])
    finally:
        db.close()


def test_the_metrics_hold_what_happened_and_no_play_text(instance: HostingInstance, played: dict[str, Any]) -> None:
    admin: httpx.Client = played["admin"]
    ref = played["ref"]
    # The metrics arrive on their own: wait until the error's reference and
    # the admin's end are both kept.
    instance.until(
        lambda: ref in json.dumps(admin.get("/admin/api/errors.json").json()["errors_rows"]),
        30,
        "the failed turn's reference on the Errors page",
    )
    instance.until(
        lambda: _count(_db(instance), "SELECT COUNT(*) FROM session WHERE event = 'ended_by_admin'") >= 1,
        30,
        "the admin's end in the metrics",
    )
    path = _db(instance)
    assert _count(path, f"SELECT COUNT(*) FROM turn WHERE story = '{A}' AND outcome = 'ok'") >= 2
    assert _count(path, f"SELECT COUNT(*) FROM turn WHERE story = '{B}' AND outcome = 'error'") == 1
    # Refusals are counted per minute (fix round 1, I1), never a row each.
    assert _count(path, "SELECT COALESCE(SUM(count), 0) FROM refused WHERE kind = 'login' AND outcome = 'failed'") >= 1
    assert _count(path, "SELECT COUNT(*) FROM login WHERE outcome = 'failed'") == 0
    assert _count(
        path, f"SELECT COALESCE(SUM(count), 0) FROM refused WHERE kind = 'turn' AND outcome = 'refused_cap' AND story = '{A}'"
    ) >= 1
    assert _count(path, "SELECT COUNT(*) FROM login WHERE outcome = 'ok'") >= 2
    assert _count(path, "SELECT COUNT(*) FROM session WHERE event = 'created'") >= 2
    assert _count(path, "SELECT COUNT(*) FROM session WHERE event = 'resumed'") >= 1
    # The ERROR handler's own path (not public_error's): its logger, no ref.
    assert _count(path, "SELECT COUNT(*) FROM error WHERE ref IS NULL AND logger = 'tests.probes.scripted_worker'") >= 1
    assert _count(path, "SELECT COUNT(*) FROM lane WHERE lane = 'narration' AND outcome = 'granted'") >= 3
    assert _count(path, "SELECT COUNT(*) FROM process WHERE event = 'ready'") >= 3
    assert _count(path, f"SELECT COUNT(*) FROM error WHERE ref = '{ref}' AND process = 'worker-{B}'") == 1
    _no_sentinel("the metrics database", _dump(path))


def test_no_admin_page_or_json_shows_play_text(instance: HostingInstance, played: dict[str, Any]) -> None:
    admin: httpx.Client = played["admin"]
    pages = _get_pages()
    for wanted in ("/admin/metrics", "/admin/errors", "/admin/api/metrics.json", "/admin/api/errors.json"):
        assert wanted in pages
    for path in pages + ["/admin/metrics?page=2", "/admin/errors?page=2", "/admin/audit?page=2"]:
        if path.startswith("/admin/static") or path == "/admin/reauth":
            continue
        response = admin.get(path)
        assert response.status_code == 200, (path, response.status_code, response.text[:200])
        _no_sentinel(path, response.text)
    errors = admin.get("/admin/errors").text
    assert played["ref"] in errors and "RuntimeError" in errors and f"worker-{B}" in errors
    # Found by its reference (fix round 1, M5), and a sentinel typed there asks nothing.
    found = admin.get("/admin/errors/find", params={"ref": played["ref"].upper()})
    assert found.status_code == 200 and played["ref"] in found.text and "Recent errors" not in found.text
    typed = admin.get("/admin/errors/find", params={"ref": SENTINEL})
    assert typed.status_code == 200 and "not a reference" in typed.text.lower()
    _no_sentinel("/admin/errors/find", typed.text)
    metrics = admin.get("/admin/api/metrics.json").json()
    assert metrics["durations"] and metrics["usage"] and not metrics["errors"]
    oracle = {row["story"]: row["oracle"] for row in metrics["oracle"]}
    # The sentinel stat's claim is counted, its name nowhere.
    assert oracle[A]["unearned_claims_count"] >= 1 and oracle[A]["unearned_claims_largest_delta"] == 50
    users = admin.get("/admin/users").text
    assert users.count(" UTC</td>") >= 4  # two accounts' created and last login
    queue = admin.get("/admin/queue").text
    assert "lane: narration" in queue


def test_no_audit_line_holds_play_text(instance: HostingInstance, played: dict[str, Any]) -> None:
    files = sorted((instance.data_dir / "hosting").glob("audit.jsonl*"))
    assert files
    text = "".join(path.read_text(encoding="utf-8") for path in files if not path.name.endswith(".lock"))
    assert played["session_id"] in text  # the session.end row is there
    _no_sentinel("the audit log", text)


def test_no_bus_message_the_supervisor_received_holds_play_text(
    instance: HostingInstance, played: dict[str, Any]
) -> None:
    traces = sorted(instance.control.glob("*.bustrace"))
    names = {path.name.rsplit("-", 1)[0] for path in traces}
    assert {f"worker-{A}", f"worker-{B}", "frontdoor"} <= names, names
    frames = [line for path in traces for line in path.read_bytes().decode("utf-8").splitlines() if line]
    metrics = [json.loads(line) for line in frames if '"op":"metric"' in line]
    assert {m["args"]["event"]["kind"] for m in metrics} >= {"turn", "session", "login", "error"}
    for line in frames:
        _no_sentinel("a bus frame to the supervisor", line)

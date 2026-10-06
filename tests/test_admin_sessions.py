"""
The admin panel's Sessions page (v0.20.0 T15, spec §14.8, §14.2, §9.10).

ONE instance for the module, every process real (``tests/hosting_instance.py``):
the supervisor, two workers (``tests/probes/scripted_worker.py``: the
engine's own hosted worker, its model scripted, with a probe that can hold a
turn in flight or pad its sessions listing past one bus frame) and the
engine's own front door. Accounts: one admin and three players.

- the Sessions page and the supervisor's ``sessions.list`` show every
  account's live sessions across both stories, a page at a time, each row
  exactly the spec's fields (and nothing from the state);
- ending one releases it: the worker's store no longer has it, its room is
  closed (the player's socket hears "session not found" on its next event),
  its HTTP door answers "session not found", and its audit rows are written;
- ending one whose turn lock is held is refused and changes nothing;
- disabling an account ends its sessions in both stories;
- a ``sessions.list`` reply past 64 KiB arrives as ``too_large``: an error
  row, and the front door still up;
- METADATA ONLY: a marker in the player's name, a typed action and a save's
  label, and the scripted narration, appear on no admin page or JSON.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Iterator

import httpx
import pytest

from tests.engineio_wire import PollingClient
from tests.hosting_instance import SCRIPTED_WORKER, HostingInstance, choose, csrf_of, hosting_instance, login

A = "clockwork-dark"
B = "dev-story"
JOIN = 60.0

#: Play text a player puts into the game: none of it may reach the panel.
MARK_NAME = "Zephyrine-Q7NAME"
MARK_ACTION = "whistle at the Q7ACTION moon"
MARK_LABEL = "Q7LABEL-camp"
MARK_SAVEID = "Q7SAVEID-ford"
NARRATION = "Mist clings to the birch trunks."

#: Every admin page and JSON a GET reaches (the marker crawl).
ADMIN_PAGES = (
    "/admin",
    "/admin/users",
    "/admin/sessions",
    "/admin/saves",
    "/admin/stories",
    "/admin/audit",
    "/admin/api/overview.json",
    "/admin/api/sessions.json",
    "/admin/api/stories.json",
)


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HostingInstance]:
    yield from hosting_instance(
        tmp_path_factory,
        "admin_sessions",
        stories=[A, B],
        frontdoor="real",
        worker_module=SCRIPTED_WORKER,
        supervisor={"boot_seconds": 180, "health_failures": 5},
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
    for name in ("wren", "moss", "fern"):
        found[name] = instance.add_account(name)
    return found


@pytest.fixture(scope="module")
def admin(instance: HostingInstance, passwords: dict[str, str]) -> Iterator[httpx.Client]:
    http = instance.admin_http("root", passwords["root"])
    try:
        yield http
    finally:
        http.close()


@pytest.fixture(scope="module")
def runs(instance: HostingInstance, passwords: dict[str, str]) -> Iterator[dict[str, Any]]:
    """
    wren and moss each play a run in both stories: a name, a typed action and
    a manual save carrying markers. ``{(name, slug): {"session_id", "http"}}``.
    """
    made: dict[Any, Any] = {}
    clients: list[httpx.Client] = []
    try:
        for name in ("wren", "moss"):
            http = instance.http()
            clients.append(http)
            assert login(http, name, passwords[name]).status_code == 303
            for slug in (A, B):
                assert choose(http, slug).status_code == 303
                session_id = _new_run(http)
                made[(name, slug)] = {"session_id": session_id, "http": http}
        yield made
    finally:
        for http in clients:
            http.close()


def _new_run(http: httpx.Client) -> str:
    opened = http.post("/api/game/new", json={"seed": 3, "player_name": MARK_NAME})
    assert opened.status_code == 200, opened.text[:300]
    session_id = str(opened.json()["session_id"])
    turn = http.post("/api/game/choice", json={"session_id": session_id, "choice_id": "", "custom_text": MARK_ACTION})
    assert turn.status_code == 200, turn.text[:300]
    # A manual save under a label AND an id the player chose (T15 fix round 1,
    # M2): both are player text.
    saved = http.post("/api/saves", json={"session_id": session_id, "slot": MARK_LABEL, "save_id": MARK_SAVEID})
    assert saved.status_code == 200, saved.text[:300]
    return session_id


def _listing(instance: HostingInstance, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    reply = instance.call("sessions.list", {"limit": limit, "offset": offset}, timeout=30)
    assert reply["ok"], reply
    return reply["result"]


def _ids(instance: HostingInstance) -> set[str]:
    return {row["session_id"] for row in _listing(instance)["rows"]}


def _audit(instance: HostingInstance, action: str) -> list[dict[str, Any]]:
    path = instance.data_dir / "hosting" / "audit.jsonl"
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row["action"] == action]


def _token(admin: httpx.Client) -> str:
    return csrf_of(admin.get("/admin/sessions").text)


def _account_id(instance: HostingInstance, name: str) -> str:
    from engine.hosting.accounts import AccountStore

    account = AccountStore(instance.data_dir / "hosting").by_name(name)
    assert account is not None
    return str(account.id)


# -- the store (in this process) -----------------------------------------------------------


def test_an_ended_session_is_gone_in_the_same_step_as_its_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fix round 1 (M1): ``end`` takes the session out under the same guard as
    its turn-lock check, so anything that looks for it once it is ended --
    a second end, a racing request -- finds it MISSING, never "busy" behind
    a lock nobody will release. On 1261d42 the take came after the guard
    was let go, and a second end in that window was told a turn was running.
    """
    from types import SimpleNamespace

    from engine.session.store import SessionStore

    store = SessionStore()
    store._sessions["s1"] = SimpleNamespace(
        lock=threading.Lock(), owner="u_000000000001", session_id="s1", created=0.0, ending=False, end_after_turn=None
    )
    seen: list[str] = []

    def second_end(*_args: Any, **_kwargs: Any) -> None:
        if seen:
            return
        try:
            store.end("s1")
            seen.append("ended twice")
        except KeyError:
            seen.append("missing")
        except Exception as exc:  # noqa: BLE001 -- what the window answered
            seen.append(type(exc).__name__)

    monkeypatch.setattr(store, "delete", lambda session_id: (second_end(), SessionStore.delete(store, session_id)))
    monkeypatch.setattr(store, "_release", lambda session_id: second_end())
    store.end("s1")
    assert seen == ["missing"] and "s1" not in store._sessions


def test_a_new_run_admitted_before_a_disable_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """
    T15 fix round 2 (N3): ``POST /api/game/new`` passed the gate, and the
    account is disabled while its world is built. Its first save is refused
    (409, the engine's words), the run is not kept, and nothing is written
    under the account's folder. In this process (a hosted worker,
    ``tests/hosted_app.py``). On 9098e90 the save was written.
    """
    from engine.session import store as store_module
    from tests import hosted_app

    hosted = hosted_app.build(monkeypatch, tmp_path, hosting={"rate_limits": {"actions_per_minute": 1000}})
    try:
        account, password = hosted.add("birch")
        client = hosted.client()
        assert hosted_app.login(client, "birch", password).status_code == 303
        real = store_module.new_game_state

        def built_while_disabled(*args: Any, **kwargs: Any) -> Any:
            state = real(*args, **kwargs)
            hosted.state.accounts.disable(account.id, by_id=True)
            return state

        monkeypatch.setattr(store_module, "new_game_state", built_while_disabled)
        answer = client.post("/api/game/new", json={"seed": 2})
        assert answer.status_code == 409, answer.get_data(as_text=True)[:300]
        assert answer.get_json() == {"error": store_module.ACCOUNT_CLOSED}
        assert not (tmp_path / "data" / "users" / account.id).exists()
        assert not [s for s in hosted.scene.store._sessions.values() if s.owner == account.id]
    finally:
        hosted_app.teardown()


def test_a_manual_save_admitted_before_a_disable_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """
    T15 fix round 2 (N3): ``POST /api/saves`` passed the gate, and the account
    is disabled before its write. The save is refused (409, the engine's
    words) and the index keeps its one row. On 9098e90 it was written.
    """
    from engine.api import saves as saves_api
    from engine.session import store as store_module
    from tests import hosted_app

    hosted = hosted_app.build(monkeypatch, tmp_path, hosting={"rate_limits": {"actions_per_minute": 1000}})
    try:
        account, password = hosted.add("cedar")
        client = hosted.client()
        assert hosted_app.login(client, "cedar", password).status_code == 303
        opened = client.post("/api/game/new", json={"seed": 2}).get_json()
        real = saves_api.check_save_room

        def checked_then_disabled(*args: Any, **kwargs: Any) -> Any:
            real(*args, **kwargs)
            hosted.state.accounts.disable(account.id, by_id=True)

        monkeypatch.setattr(saves_api, "check_save_room", checked_then_disabled)
        answer = client.post("/api/saves", json={"session_id": opened["session_id"], "slot": "camp"})
        assert answer.status_code == 409, answer.get_data(as_text=True)[:300]
        assert answer.get_json() == {"error": store_module.ACCOUNT_CLOSED}
        index = next((tmp_path / "data" / "users" / account.id).rglob("index.json"))
        assert len(json.loads(index.read_text(encoding="utf-8"))["saves"]) == 1
    finally:
        hosted_app.teardown()


# -- the list ---------------------------------------------------------------------------


def test_the_row_keys_are_the_spec_s_on_both_sides() -> None:
    """The worker's ``describe`` row plus its socket count IS what the supervisor passes on."""
    from engine.hosting.admin.sessions import ROW_KEYS
    from engine.hosting.supervisor.server import SESSION_ROW_KEYS
    from engine.session.store import DESCRIBE_KEYS

    assert DESCRIBE_KEYS == ("owner", "session_id", "save_id", "created", "last_activity", "turns", "turn_running")
    assert SESSION_ROW_KEYS == DESCRIBE_KEYS + ("sockets",)
    # The page shows the save as a hash, never its id (fix round 1, M2).
    assert set(ROW_KEYS) == {"story", "owner_name", "ref", "save_ref"} | set(SESSION_ROW_KEYS) - {"save_id"}


def test_every_account_s_sessions_across_both_stories_a_page_at_a_time(
    instance: HostingInstance, runs: dict[Any, Any], admin: httpx.Client, passwords: dict[str, str]
) -> None:
    from engine.hosting.supervisor.server import SESSION_ROW_KEYS

    made = {run["session_id"]: key for key, run in runs.items()}
    pages = [_listing(instance, limit=2, offset=offset) for offset in (0, 2, 4)]
    assert [len(p["rows"]) for p in pages] == [2, 2, 0]
    assert all(p["total"] == 4 and p["errors"] == [] for p in pages)
    rows = pages[0]["rows"] + pages[1]["rows"]
    assert {row["session_id"] for row in rows} == set(made)
    for row in rows:
        assert set(row) == {"story"} | set(SESSION_ROW_KEYS), row
        name, slug = made[row["session_id"]]
        assert row["story"] == slug and row["owner"] == _account_id(instance, name)
        assert row["turns"] >= 1 and row["turn_running"] is False and row["save_id"]
    assert pages[0]["stories"] == {A: 2, B: 2}

    page = admin.get("/admin/sessions")
    assert page.status_code == 200
    saves = {row["session_id"]: row["save_id"] for row in rows}
    for session_id, (name, slug) in made.items():
        assert f"<code>{session_id[:6]}</code>" in page.text and name in page.text and slug in page.text
        assert f'name="session_id" value="{session_id}"' in page.text
        assert saves[session_id] not in page.text, "a save id printed verbatim"
    # Each save as a keyed 10-hex reference (the key is the front door's own).
    assert len(set(re.findall(r"<code>([0-9a-f]{10})</code>", page.text))) == len(made)
    feed = admin.get("/admin/api/sessions.json").json()
    assert feed == {"total": 4, "stories": [{"slug": A, "sessions": 2}, {"slug": B, "sessions": 2}], "errors": []}
    users = admin.get("/admin/users").text
    assert "<td>2</td>" in users  # wren's and moss's live sessions


def test_no_play_text_reaches_any_admin_surface(
    instance: HostingInstance, runs: dict[Any, Any], admin: httpx.Client
) -> None:
    """Rule 12, metadata only: the markers a player typed, and the narration, are on no admin page."""
    stories = admin.get("/admin/stories")
    assert stories.status_code == 200
    for path in ADMIN_PAGES:
        response = admin.get(path)
        assert response.status_code == 200, (path, response.status_code)
        for marker in (MARK_NAME, MARK_ACTION, MARK_LABEL, MARK_SAVEID, "Q7NAME", "Q7ACTION", "Q7LABEL", "Q7SAVEID", NARRATION):
            assert marker not in response.text, (path, marker)
    raw = json.dumps(_listing(instance))
    assert not any(m in raw for m in ("Q7NAME", "Q7ACTION", "Q7LABEL", NARRATION))
    # The saves are there, shown by a keyed hash of the id and the kind only.
    saves = admin.get("/admin/saves").text
    assert "manual" in saves and "auto" in saves and re.search(r"<code>[0-9a-f]{10}</code>", saves)


# -- ending one ---------------------------------------------------------------------------


def test_ending_a_session_releases_it_closes_its_room_and_is_audited(
    instance: HostingInstance, runs: dict[Any, Any], admin: httpx.Client
) -> None:
    run = runs[("wren", A)]
    session_id, http = run["session_id"], run["http"]
    assert choose(http, A).status_code == 303
    poll = PollingClient(http, instance.base)
    try:
        poll.handshake()
        assert poll.connect()["type"] == "connect"
        poll.emit("join_session", {"session_id": session_id})
        poll.until(lambda e: e.get("name") in ("game_started", "error"))
        row = instance.until(
            lambda: next((r for r in _listing(instance)["rows"] if r["session_id"] == session_id and r["sockets"]), None),
            15,
            "the socket in its room",
        )
        assert row["sockets"] == 1

        ended = admin.post(
            "/admin/sessions/end", data={"csrf": _token(admin), "slug": A, "session_id": session_id}
        )
        # POST-redirect-GET (fix round 1, M6): the note shows once on the page.
        assert ended.status_code == 303 and ended.headers["location"] == "/admin/sessions", ended.text[:500]
        assert "Ended session" in admin.get("/admin/sessions").text
        assert "Ended session" not in admin.get("/admin/sessions").text
        assert session_id not in _ids(instance)
        state = http.get("/api/game/state", params={"session_id": session_id})
        assert state.status_code == 404 and state.json() == {"error": "session not found"}
        mark = len(poll.received)
        poll.emit("player_choice", {"session_id": session_id, "choice_id": "a"})
        heard = poll.until(lambda e: e.get("name") in ("turn_error", "turn_update"))
        assert heard["name"] == "turn_error" and heard["args"][0]["message"] == "session not found"
        assert len(poll.received) > mark
    finally:
        poll.close()
    rows = [r for r in _audit(instance, "session.end") if r["target"] == session_id]
    assert [r["result"] for r in rows] == ["started", "ok"]
    assert rows[0]["ref"] == rows[1]["ref"] and rows[0]["actor_name"] == "root"
    assert rows[0]["detail"] == {"story": A}
    # Ending it again: it is no longer live, refused, one more refused outcome.
    again = admin.post("/admin/sessions/end", data={"csrf": _token(admin), "slug": A, "session_id": session_id})
    assert again.status_code == 404


def test_a_session_whose_turn_is_running_is_not_ended(
    instance: HostingInstance, runs: dict[Any, Any], admin: httpx.Client
) -> None:
    run = runs[("moss", B)]
    session_id, http = run["session_id"], run["http"]
    assert choose(http, B).status_code == 303
    hold = instance.control / f"worker-{B}.hold"
    held = instance.control / f"worker-{B}.held"
    held.unlink(missing_ok=True)
    hold.write_text("1", encoding="utf-8")
    answers: list[Any] = []
    turn = threading.Thread(
        target=lambda: answers.append(http.post("/api/game/choice", json={"session_id": session_id, "choice_id": "a"})),
        name="held-turn",
    )
    try:
        turn.start()
        instance.until(held.exists, 30, "the turn in flight")
        before = {r["session_id"]: r for r in _listing(instance)["rows"]}
        assert before[session_id]["turn_running"] is True
        refused = admin.post(
            "/admin/sessions/end", data={"csrf": _token(admin), "slug": B, "session_id": session_id}
        )
        assert refused.status_code == 409 and "a turn is running; try again in a moment" in refused.text
        assert session_id in _ids(instance)
    finally:
        hold.unlink()
        turn.join(JOIN)
        held.unlink(missing_ok=True)
    assert not turn.is_alive() and answers and answers[0].status_code == 200, answers
    assert session_id in _ids(instance)
    assert http.get("/api/game/state", params={"session_id": session_id}).status_code == 200
    rows = [r for r in _audit(instance, "session.end") if r["target"] == session_id]
    assert [r["result"] for r in rows] == ["started", "refused"] and rows[0]["ref"] == rows[1]["ref"]


def test_disabling_an_account_ends_its_sessions_in_both_stories(
    instance: HostingInstance, passwords: dict[str, str], admin: httpx.Client, runs: dict[Any, Any]
) -> None:
    http = instance.http()
    try:
        assert login(http, "fern", passwords["fern"]).status_code == 303
        mine = set()
        for slug in (A, B):
            assert choose(http, slug).status_code == 303
            mine.add(_new_run(http))
    finally:
        http.close()
    assert mine <= _ids(instance)
    fern = _account_id(instance, "fern")
    page = admin.get("/admin/users")
    done = admin.post(f"/admin/users/{fern}/disable", data={"csrf": csrf_of(page.text)})
    assert done.status_code == 303 and "live sessions with them" in admin.get("/admin/users").text
    assert not mine & _ids(instance)
    outcome = [r for r in _audit(instance, "account.disable") if r["target"] == fern][-1]
    assert outcome["result"] == "ok" and outcome["detail"] == {"sessions_ended": 2, "sessions_busy": 0}
    assert runs[("moss", B)]["session_id"] in _ids(instance), "another account's session was ended"


# -- a turn still running when its account goes (fix round 1, I1) ------------------------------


def _player_run(instance: HostingInstance, name: str, slug: str) -> tuple[httpx.Client, str, str]:
    """A new account ``name`` with one run in ``slug``: its client, session id and account id."""
    password = instance.add_account(name)
    http = instance.http()
    assert login(http, name, password).status_code == 303
    assert choose(http, slug).status_code == 303
    opened = http.post("/api/game/new", json={"seed": 8})
    assert opened.status_code == 200, opened.text[:300]
    return http, str(opened.json()["session_id"]), _account_id(instance, name)


def _held_turn(instance: HostingInstance, http: httpx.Client, session_id: str, slug: str) -> tuple[threading.Thread, list[Any]]:
    held = instance.control / f"worker-{slug}.held"
    held.unlink(missing_ok=True)
    (instance.control / f"worker-{slug}.hold").write_text("1", encoding="utf-8")
    answers: list[Any] = []
    turn = threading.Thread(
        target=lambda: answers.append(http.post("/api/game/choice", json={"session_id": session_id, "choice_id": "a"})),
        name="held-turn",
    )
    turn.start()
    instance.until(held.exists, 30, "the turn in flight")
    return turn, answers


def _release(instance: HostingInstance, slug: str, turn: threading.Thread) -> None:
    (instance.control / f"worker-{slug}.hold").unlink(missing_ok=True)
    turn.join(JOIN)
    (instance.control / f"worker-{slug}.held").unlink(missing_ok=True)
    assert not turn.is_alive()


def test_a_disable_during_a_turn_lets_it_finish_but_save_nothing(
    instance: HostingInstance, admin: httpx.Client
) -> None:
    """
    The turn running when its account is disabled is not cut; it writes no
    save and no transcript, and the session is released once it ends -- so a
    purge after it leaves the folder gone for good. Fails on 1261d42, whose
    turn autosaved after the disable (the transcript grew).
    """
    http, session_id, account = _player_run(instance, "oak", B)
    folder = instance.data_dir / "users" / account
    transcripts = lambda: sum(  # noqa: E731
        len(p.read_text(encoding="utf-8").splitlines()) for p in folder.rglob("transcript.jsonl")
    )
    index = next(folder.rglob("index.json"))
    before = (transcripts(), index.read_bytes())
    from engine.scenes import default_state

    turn, answers = _held_turn(instance, http, session_id, B)
    try:
        done = admin.post(f"/admin/users/{account}/disable", data={"csrf": _token(admin)})
        assert done.status_code == 303
    finally:
        _release(instance, B, turn)
    # Fix round 2 (N4): the player is told, in the engine's words, in the
    # narration the client shows and as ``notice``.
    assert answers and answers[0].status_code == 200, answers
    payload = answers[0].json()
    assert "notice" in payload, "the turn that saved nothing told the player nothing"
    notice = default_state.TURN_NOT_SAVED
    assert payload["notice"] == notice and payload["narration"].endswith(notice)
    outcome = [r for r in _audit(instance, "account.disable") if r["target"] == account][-1]
    assert outcome["detail"] == {"sessions_ended": 0, "sessions_busy": 1}
    instance.until(lambda: session_id not in _ids(instance), 15, "released after its turn")
    assert (transcripts(), index.read_bytes()) == before, "the ended session's turn saved"
    purged = admin.post(
        f"/admin/users/{account}/delete", data={"csrf": _token(admin), "mode": "purge", "confirm": "oak"}
    )
    assert purged.status_code == 303 and not folder.exists()
    http.close()


def test_a_purge_waits_while_a_turn_of_the_account_runs(instance: HostingInstance, admin: httpx.Client) -> None:
    """
    A delete with purge while one of the account's turns runs is REFUSED,
    with the engine's words, the account left disabled and its folder kept;
    once the turn is over the same delete goes through and the folder stays
    gone. Fails on 1261d42, which purged at once and let the turn write the
    folder back.
    """
    from engine.hosting.admin.users import PURGE_WAITING

    http, session_id, account = _player_run(instance, "elm", A)
    folder = instance.data_dir / "users" / account
    turn, _answers = _held_turn(instance, http, session_id, A)
    try:
        refused = admin.post(
            f"/admin/users/{account}/delete", data={"csrf": _token(admin), "mode": "purge", "confirm": "elm"}
        )
        assert refused.status_code == 409 and PURGE_WAITING.format(name="elm") in refused.text.replace("&#39;", "'")
        from engine.hosting.accounts import AccountStore

        still = AccountStore(instance.data_dir / "hosting").get(account)
        assert still is not None and still.disabled and folder.is_dir()
    finally:
        _release(instance, A, turn)
    rows = [r for r in _audit(instance, "account.delete") if r["target"] == account]
    assert [r["result"] for r in rows] == ["started", "refused"] and rows[1]["detail"]["sessions_busy"] == 1
    instance.until(lambda: session_id not in _ids(instance), 15, "released after its turn")
    again = admin.post(
        f"/admin/users/{account}/delete", data={"csrf": _token(admin), "mode": "purge", "confirm": "elm"}
    )
    assert again.status_code == 303 and not folder.exists()
    threading.Event().wait(0.5)  # nothing left to write it back
    assert not folder.exists()
    http.close()


# -- the frame cap ------------------------------------------------------------------------


def test_a_listing_past_one_bus_frame_is_an_error_row_and_the_front_door_stays_up(
    instance: HostingInstance, runs: dict[Any, Any], admin: httpx.Client
) -> None:
    bloat = instance.control / f"worker-{A}.bloat"
    bloat.write_text("1", encoding="utf-8")
    try:
        listing = _listing(instance)
        assert listing["errors"] == [{"story": A, "error": "too_large"}]
        assert {row["story"] for row in listing["rows"]} == {B}
        page = admin.get("/admin/sessions")
        assert page.status_code == 200
        assert 'class="error"' in page.text and "too_large" in page.text
        assert admin.get("/api/health").json()["status"] == "ok"
    finally:
        bloat.unlink()
    assert _listing(instance)["errors"] == []
    started = time.monotonic()
    assert admin.get("/admin/sessions").status_code == 200
    assert time.monotonic() - started < 10

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

and the sentinel is in none of them. A READ RECEIPTS run (v0.22.0 T10)
carries it too, as the player's bio and in every message sent, saved. The same surfaces are shown to HOLD what
they should (the error's reference, the turns, the session the admin ended,
the claim counted with no name), so the test cannot pass on empty pages.

Rule 12 is the other half: the store keeps no text at all, so there is
nothing to rate, flag or filter (``tests/test_metrics_schema.py``).
"""

from __future__ import annotations

import json
import threading
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest

from tests.engineio_wire import PollingClient
from tests.hosting_instance import SCRIPTED_WORKER, HostingInstance, choose, csrf_of, hosting_instance, login

pytestmark = pytest.mark.process

A = "clockwork-dark"
B = "dev-story"
#: v0.22.0 T10 (spec §17.1): a phone save -- READ RECEIPTS, a bio and
#: messages sent, a reply due -- in the same instance.
C = "read-receipts"

#: The play text: one word, so it fits a name (40 characters), a stat and a label.
SENTINEL = "Zq9Sentinel"
#: A typed world line's own sentinel (v0.23.0 T23E, addendum 4 §3): the scripted narration never carries it, so a
#: log line or metric holding it could only have come from the line the player typed.
TYPED = "Zq9Typed"
#: v0.23.0 T28: play text the engine's own paths write and no admin surface may show (planted by
#: ``tests/probes/scripted_worker.py::plant_play_text`` into the live phone run): a scene's narration, a
#: recap, the story so far, a chance scene's narration and a held text.
SCENE = "SCN-NARR-7f3a91"
RECAP = "RECAP-5c2e08"
STORY = "STORY-d41b6e"
CHANCE = "CHANCE-b83f27"
HELD = "HELD-a19c60"
PLANTED = (SCENE, RECAP, STORY, CHANCE, HELD)

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
    for planted in PLANTED:
        assert planted.lower() not in text.lower(), f"the planted play text {planted} reached {where}"


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HostingInstance]:
    yield from hosting_instance(
        tmp_path_factory,
        "admin_no_play_text",
        stories=[A, B, C],
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
                "phone_actions_per_minute": 1000,
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
    (instance.control / "scripted.voice").write_text(f"{SENTINEL} texts back", encoding="utf-8")
    # The match always reads and replies (pre-flight F16: the draws forced, not a seed hunted for):
    # since T16's 19:00 start, seed 7's one match ghosted on a send and no reply ever fell due.
    (instance.control / "scripted.always_replies").write_text("1", encoding="utf-8")
    # A person's voice note lands (T21 review M7): every media ask the app can carry is accepted.
    (instance.control / "scripted.media_yes").write_text("1", encoding="utf-8")
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

        _play_the_phone(player)
        _the_match_answers(instance)
        _until_the_phone_save_holds_voiced_words(instance)
        _plant_play_text(instance, player)

        admin = instance.admin_http("root", root)
        token = csrf_of(admin.get("/admin/sessions").text)
        ended = admin.post("/admin/sessions/end", data={"csrf": token, "slug": B, "session_id": session_b})
        assert ended.status_code == 303, ended.text[:300]
        yield {"admin": admin, "ref": match.group(1), "session_id": session_b}
    finally:
        player.close()
        if admin is not None:
            admin.close()


def _phone(player: httpx.Client, sid: str, action: str, target: str = "", args: Any = None, text: str = "") -> dict[str, Any]:
    """
    One phone action through the front door; its turn payload, the action not
    refused. Since T14 a background voicing pass holds the run's turn lock for
    its snapshot and each commit, so an action can be answered busy (409):
    re-sent after 150 ms, as the client does (spec §16.2), a bounded number
    of times.
    """
    pause = threading.Event()
    for _attempt in range(40):
        resp = player.post("/api/phone/action", json={"session_id": sid, "action": action, "target": target,
                                                      "args": args or {}, "text": text})
        if resp.status_code != 409:
            break
        pause.wait(0.15)
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert not body["receipts"][0].get("refused"), body["receipts"][0]
    return body


def _play_the_phone(player: httpx.Client) -> None:
    """
    A phone save holding play text (spec §17.1): the sentinel as a bio and in
    every message the player sends, then time passed so the match's replies
    fall due and the run is saved (at once on the match, then by the dirty
    timer and on each later save). Since T14 the worker's voicing pass (its
    model scripted: ``scripted.voice``, the sentinel's line) voices the
    replies in the background and, past the voice's verbatim window
    (`social.memory.verbatim`), keeps the conversation's words in the
    person's memory (v0.23.0 T6; a thread summary before) -- both saved. Since T21 the player also sends a voice note -- the sentinel in its
    transcript -- on a Front Porch match (Matchstick carries no voice), made
    from its "Likes you" row or a like on its deck, and asks for one back,
    which the person sends (``scripted.media_yes``): its transcript, the
    scripted voice's sentinel line, is on their media row and its message.
    """
    assert choose(player, C).status_code == 303
    opened = player.post("/api/game/new", json={"seed": 7})
    assert opened.status_code == 200, opened.text[:300]
    sid = str(opened.json()["session_id"])
    _phone(player, sid, "edit_profile", target="matchstick", args={"field": "bio"}, text=f"{SENTINEL} climbs")
    phone: dict[str, Any] = {}
    for _ in range(40):  # like down the deck, letting time pass, until someone likes back
        deck = (phone.get("deck") or {}).get("matchstick") if phone else None
        card = (deck or {}).get("card")
        if card:
            phone = _phone(player, sid, "swipe", target=card["pid"], args={"dir": "like"})["state"]["phone"]
        phone = _phone(player, sid, "wait", args={"until": "next"})["state"]["phone"]
        if phone["threads"]:
            break
    assert phone["threads"], "no match in forty likes"
    thread = phone["threads"][0]["thread_id"]
    for i in range(30):  # a conversation's worth of play text: the person's memory keeps it
        _phone(player, sid, "send", target=thread, args={"kind": "text"}, text=f"{SENTINEL} says {i}")
    _phone(player, sid, "wait", args={"until": "next"})          # their reply falls due: a pass is requested
    _phone(player, sid, "wait", args={"until": "1h"})
    phone = _phone(player, sid, "open_thread", target=thread)["state"]["phone"]
    porch = _front_porch_match(player, sid, phone)
    _phone(player, sid, "send", target=porch, args={"kind": "voice", "audio_transcript": f"{SENTINEL} hums"})
    _phone(player, sid, "ask", target=porch, args={"what": "voice"})   # their voice note: the scripted line
    # Their voice note is a background media job (the speech worker's thread, its result delivered at a LATER
    # action's drain), so the wait is in real time as well as game time: a batch run on a loaded machine fell
    # through twelve instant polls (v0.23.0 T28). The draws themselves are forced (scripted.always_replies,
    # scripted.media_yes).
    pause = threading.Event()
    for _ in range(60):
        opened = _phone(player, sid, "open_thread", target=porch)["state"]["phone"].get("open_thread") or {}
        if any(m.get("kind") == "voice" and m.get("from") not in ("player", "system")
               for m in opened.get("messages") or []):
            break
        _phone(player, sid, "wait", args={"until": "next"})
        pause.wait(0.5)
    else:
        raise AssertionError("their voice note never fell due")
    _typed_world_turns(player, sid)


def _plant_play_text(instance: HostingInstance, player: httpx.Client) -> None:
    """
    Scene narration, a recap, a story, a chance scene's narration and a held text (v0.23.0 T28): planted into the
    READ RECEIPTS worker's live run through the engine's own writers (``tests/probes/scripted_worker.py``,
    ``<worker>.plant``), the next request through the front door taking it. Then each is shown to be in the
    saved run (its archive, for a scene's), so the scans below are not empty-handed.
    """
    (instance.control / f"worker-{C}.plant").write_text(json.dumps({
        "scene": SCENE, "recap": RECAP, "story": STORY, "chance": CHANCE, "held": HELD}), encoding="utf-8")
    assert player.get("/api/social/creation").status_code == 200

    def saved() -> bool:
        text = ""
        for path in instance.data_dir.rglob("save.json"):
            if C in path.parts:
                text += path.read_text(encoding="utf-8")
                archive_file = path.parent / "phone_archive.jsonl"
                if archive_file.is_file():
                    text += archive_file.read_text(encoding="utf-8")
        return all(word in text for word in PLANTED)

    instance.until(saved, 30, "the saved phone run holding the planted scene, recap, story, chance and held text")


def _typed_world_turns(player: httpx.Client, sid: str) -> None:
    """
    Typed world lines (v0.23.0 T23E, addendum 4 §3): the phone put down, two lines typed into the world -- one
    the engine reads as an offered choice where one is on offer ("tidy up"), one it reads as nothing -- each
    carrying ``TYPED``. The line is play text: read under the lock, its action and target logged, never its words.
    """
    _phone(player, sid, "put_down")
    pause = threading.Event()
    for text in (f"tidy up, {TYPED}", f"{TYPED} looks around"):
        for _attempt in range(40):
            resp = player.post("/api/game/choice", json={"session_id": sid, "choice_id": "custom", "custom_text": text})
            if resp.status_code != 409:
                break
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if body.get("phone_up"):
                _phone(player, sid, "put_down")
            pause.wait(0.15)
        assert resp.status_code == 200, resp.text[:300]
        assert not any(r.get("refused") for r in resp.json().get("tool_receipts") or [])


def _front_porch_match(player: httpx.Client, sid: str, phone: dict[str, Any]) -> str:
    """A Front Porch thread: a "Likes you" row liked back (a match at once), else a like on the deck's top card."""
    for _ in range(40):
        porch = [t["thread_id"] for t in phone["threads"] if str(t["thread_id"]).startswith("front_porch:")]
        if porch:
            return porch[0]
        waiting = [r for r in phone.get("likes_you") or [] if r.get("app") == "front_porch"]
        deck = (phone.get("deck") or {}).get("front_porch") or {}
        if waiting:
            phone = _phone(player, sid, "like_back", target=waiting[0]["pid"])["state"]["phone"]
            continue
        if deck.get("card") and int(deck.get("likes_left") or 0) > 0:
            phone = _phone(player, sid, "like", target=deck["card"]["pid"], args={"on": "photo_0"})["state"]["phone"]
        phone = _phone(player, sid, "wait", args={"until": "next"})["state"]["phone"]
    raise AssertionError("no Front Porch match in forty tries")


def _the_match_answers(instance: HostingInstance) -> None:
    """
    Fail FAST, with the reason, when the phone's match cannot answer: the
    saved run's matched person must not be ghosted and must have a reply of
    theirs due or voiced. A content change that moves this course fails
    here, not as a 90 s wait for a reply that can never come.
    """

    def answered() -> bool:
        for path in instance.data_dir.rglob("save.json"):
            if C not in path.parts:
                continue
            social = ((json.loads(path.read_text(encoding="utf-8")).get("state") or {}).get("social") or {})
            for t in (social.get("threads") or {}).values():
                pid = t.get("pid")
                assert not ((social.get("people") or {}).get(pid) or {}).get("ghosted"), (
                    f"the phone's match {pid} ghosted the player: no reply can ever fall due "
                    "(is scripted.always_replies still honoured by tests/probes/scripted_worker.py?)")
                if any(m.get("from") == pid for m in t.get("messages") or []):
                    return True
        return False

    instance.until(answered, 30, "the phone's match has a reply due or voiced in the saved run")


def _until_the_phone_save_holds_voiced_words(instance: HostingInstance) -> None:
    """
    The READ RECEIPTS save holds a reply voiced in the background with the
    sentinel's line (in the save or its archive), the person's memory carrying
    the sentinel (v0.23.0 T6; a thread summary before), the
    player's voice note with the sentinel in its transcript and a person's
    voice-note row whose transcript is the sentinel's line (T21), before any
    page is scanned: the scans then cover all four.
    """

    def voiced_and_summarised() -> bool:
        for path in instance.data_dir.rglob("save.json"):
            if C not in path.parts:
                continue
            state = (json.loads(path.read_text(encoding="utf-8")).get("state") or {})
            threads = ((state.get("social") or {}).get("threads") or {}).values()
            # The save's messages and the archive's beside it: a closed conversation's messages leave state
            # for phone_archive.jsonl at the save (v0.23.0 T9 fix round 2, archive.keep_for).
            messages = [m for t in threads for m in t.get("messages") or []]
            archive_file = path.parent / "phone_archive.jsonl"
            if archive_file.is_file():
                for line in archive_file.read_text(encoding="utf-8").splitlines():
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and row.get("thread_id"):
                        messages.append(row)
            voiced = any(SENTINEL in " ".join(m.get("bubbles") or []) for m in messages
                         if m.get("from") not in ("player", "system") and m.get("voiced") is True)
            # Since v0.23.0 T6 a person's memory holds the conversation's words (`memory.current`, the
            # bridge), not a thread summary: the play text the save keeps about them.
            people = ((state.get("social") or {}).get("people") or {}).values()
            summarised = any(SENTINEL in json.dumps(p.get("memory") or {}, ensure_ascii=False) for p in people)
            spoken = any(SENTINEL in str(m.get("transcript") or "") for m in messages if m.get("from") == "player")
            rows = ((state.get("social") or {}).get("media") or {}).values()
            heard = any(r.get("kind") == "voice" and SENTINEL in str(r.get("transcript") or "") for r in rows)
            if voiced and summarised and spoken and heard:
                return True
        return False

    instance.until(voiced_and_summarised, 90,
                   "the phone save holding a voiced reply, the person's memory of it and both voice notes' transcripts")


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


def test_the_phone_save_holds_the_play_text_the_pages_do_not(instance: HostingInstance, played: dict[str, Any]) -> None:
    """The READ RECEIPTS run's save (and its transcript) carries the sentinel: the scans above are not empty-handed."""

    def saved_with_sentinel() -> bool:
        for path in instance.data_dir.rglob("save.json"):
            if C in path.parts and SENTINEL in path.read_text(encoding="utf-8"):
                return True
        return False

    instance.until(saved_with_sentinel, 30, "the phone save holding the sentinel")
    admin: httpx.Client = played["admin"]
    for path in ("/admin/saves", "/admin/sessions"):
        response = admin.get(path)
        assert response.status_code == 200, (path, response.status_code)
        _no_sentinel(path, response.text)


def test_no_log_line_or_metric_holds_a_typed_line(instance: HostingInstance, played: dict[str, Any]) -> None:
    """A typed world line (v0.23.0 T23E) is in no process log, no metric, no audit line and no admin page."""
    logs = [path for path in instance.data_dir.rglob("*.log*") if path.is_file() and not path.name.endswith(".lock")]
    assert logs, "no process log was written"
    for path in logs:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        assert TYPED.lower() not in text, f"{TYPED} in {path}"
        for planted in PLANTED:
            assert planted.lower() not in text, f"{planted} in {path}"
    assert TYPED.lower() not in _dump(_db(instance)).lower()
    admin: httpx.Client = played["admin"]
    for path in _get_pages():
        response = admin.get(path)
        if response.status_code == 200:
            assert TYPED.lower() not in response.text.lower(), path

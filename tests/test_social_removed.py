from __future__ import annotations

from pathlib import Path

import pytest

from tests.social_fixtures import matched, receipts_active, receipts_state  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
#: The server's removed names, scanned in the SERVER sources only (pre-flight F4).
GONE_NAMES = ("schedule_reply", "_reply_minutes", "_status_mult", "_burst_factor", "slot_start", "days_ahead",
              "propose_meet", "meet_start", "auto_wait", "summarize_thread", "SOCIAL_MEET",
              "played_on_the_phone", "ghost_per_exchange", "per_day_gain")
#: The client's removed names, scanned in `ui/src/stories/read-receipts` only, from T22 (which removes them).
CLIENT_GONE = ("letTimePass", "PlanMeet", "auto_wait")
#: Files that MUST name a removed name, each with its reason (pre-flight F4). Matched by relative path or by
#: file name; nothing else is exempt.
EXEMPT_FILES: dict[str, str] = {
    "CHANGELOG.md": "a changelog records what was removed, by name (every CHANGELOG.md under the scanned roots)",
    "engine/social/migrate.py": "the v0.22 -> v0.23 migration must name the keys it drops",
}


def _exempt(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return rel in EXEMPT_FILES or path.name in EXEMPT_FILES


def _sources(bases):
    for base in bases:
        for path in (ROOT / base).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".yaml", ".md", ".js", ".jsx") and not _exempt(path):
                yield path


def _hits(bases, names):
    return [f"{p.relative_to(ROOT).as_posix()}: {name}" for p in _sources(bases) for name in names
            if name in p.read_text(encoding="utf-8", errors="replace")]


def test_the_removed_names_are_gone() -> None:
    hits = _hits(("engine", "games/read-receipts", "scripts", "config"), GONE_NAMES)
    assert not hits, hits


def test_the_removed_client_names_are_gone() -> None:
    hits = _hits(("ui/src/stories/read-receipts",), CLIENT_GONE)
    assert not hits, hits


def test_every_exempt_file_exists() -> None:
    """An exemption whose file is gone is stale (no silent drift)."""
    for name in EXEMPT_FILES:
        if "/" in name:
            assert (ROOT / name).is_file(), name


def test_the_removed_prompts_are_gone() -> None:
    for name in ("date_recap.md", "thread_summary.md"):
        assert not (ROOT / "games" / "read-receipts" / "prompts" / name).exists()


def test_no_growth_gain_is_still_stubbed() -> None:
    from engine.social import growth

    assert growth._STUBBED == set()




def test_a_v022_recap_card_still_in_a_thread_does_not_stop_the_pass(receipts_state, matched) -> None:
    """A v0.22 save may hold a due meet-up recap card (a system message, `kind: recap`, not voiced). Nothing
    voices it now (v0.23.0 T19), and it must neither be taken as a reply to voice nor break the pass or the
    payload; T20's migration drops it at load."""
    from engine.social import messaging, payload, voicer
    from tests.social_fixtures import _VOICE_SESSIONS, _act, _open_episode, _replies_forced, _voice_all
    from tests.social_stub import StubVoice

    thread = matched("matchstick")
    card = messaging.new_message(receipts_state, thread, "system", "recap", voiced=False,
                                 decision={"situation": "recap", "kind": "recap", "meet_id": "t1"})
    pid = thread.split(":")[1]
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hello there")
    _voice_all(receipts_state, StubVoice("zero"))
    session = _VOICE_SESSIONS[id(receipts_state)][1]
    assert card["id"] not in {m["id"] for m in voicer._voiceable(receipts_state, session)}
    rows = {m["id"]: m for m in receipts_state.social["threads"][thread]["messages"]}
    assert rows[card["id"]]["voiced"] is False
    assert any(m["from"] not in ("player", "system") and m["voiced"] is True for m in rows.values())
    assert payload.phone_block(receipts_state)


def test_picking_a_venue_leaves_the_scene_stream_alone(receipts_state, matched) -> None:
    """Rule 4: a venue tie is its own stream (`SOCIAL_VENUE`), so it never shifts that person's next scene draw."""
    from engine.game import rng
    from engine.social import behaviour, places

    pid = matched("matchstick").split(":")[1]
    base = behaviour.person_rng(receipts_state, rng.SOCIAL_SCENE, pid).random()
    receipts_state.social["people"][pid]["rng_n"].pop(rng.SOCIAL_SCENE)
    for _ in range(6):
        places.pick_venue(receipts_state, pid)
    assert behaviour.person_rng(receipts_state, rng.SOCIAL_SCENE, pid).random() == base

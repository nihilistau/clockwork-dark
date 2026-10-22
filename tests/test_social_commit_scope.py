"""The voiced commit's scoped rollback (v0.22.0 T26; spec §16.3 step 4).

The commit's rollback snapshot was the whole state (``StateTransaction``'s
``to_save_dict``) under the turn lock: about 0.4 s a commit at day 30. It is
now ``voicer.ScopedTransaction``, which keeps the replying person's rows deep
and every other row by reference. These tests hold it to the whole-state
rollback's guarantee:

- every commit of a played run, its proposals, memory and regard included,
  forced to roll back AFTER all of its writes, leaves ``to_save_dict``
  byte-identical to the state before it;
- a commit writes nothing outside ``state.social`` and ``state.rng_counters``
  (which is what the snapshot keeps);
- a commit that raises part way (at each of its writes) or whose
  ``social_voiced`` refuses leaves the state as it was.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                    # scripts.* importable (tests/test_generate_art_cli.py:33)

from tests.social_fixtures import receipts_active  # noqa: E402,F401

#: Wall-clock stamps, never a mechanic (the replay test's `WALL`).
WALL = {"last_active_wall"}


def _whole(state: Any) -> str:
    data = state.to_save_dict()
    social = dict(data.get("social") or {})
    for key in WALL:
        social.pop(key, None)
    data["social"] = social
    return json.dumps(data, sort_keys=True, default=str)


def _outside(state: Any) -> str:
    data = state.to_save_dict()
    data.pop("social", None)
    data.pop("rng_counters", None)
    return json.dumps(data, sort_keys=True, default=str)


class _Proposer:
    """A stub voice that proposes every legal proposal in turn and shares and learns a fact each reply."""

    def __init__(self) -> None:
        self.n = 0
        self.used: dict[str, int] = {}

    def __call__(self, messages: list[dict[str, Any]], fmt: dict[str, Any]) -> str:
        self.n += 1
        props = (((fmt or {}).get("json_schema") or {}).get("schema") or {}).get("properties") or {}
        out: dict[str, Any] = {"bubbles": [{"text": "that sounds lovely, tell me more"}],
                               "regard": {"warmth": 3, "trust": 2, "mood": "fond"},
                               "learned": [f"likes thing {self.n}"], "shared": [f"grew up by the sea {self.n}"]}
        legal = list(((props.get("proposals") or {}).get("items") or {}).get("enum") or [])
        if "proposals" in props:
            # The legal proposal proposed least so far (then by name): every kind gets its turn in a short
            # run, where cycling by count let `cool_off`, legal at every reply, take most turns (v0.23.0 T3).
            pick = min(legal, key=lambda name: (self.used.get(name, 0), name)) if legal else None
            if pick is not None:
                self.used[pick] = self.used.get(pick, 0) + 1
            out["proposals"] = [pick] if pick is not None else []
        if "media" in props:
            out["media"] = {"caption": "this one's for you"}
        # v0.23.0 T7: the reply's own keys -- a promise whenever one is offered (winding or signing off),
        # and a follow-up every third reply -- so the commit's promise and open-row writes are covered.
        if "promise" in props:
            windows = props["promise"]["items"]["properties"]["window"]["enum"]
            out["promise"] = [{"window": windows[0], "about": ""}]
            self.used["promise"] = self.used.get("promise", 0) + 1
        if "followups" in props:
            out["followups"] = [{"about": f"thing {self.n}", "when": "tomorrow"}] if self.n % 3 == 0 else []
        return json.dumps(out)


def _play(monkeypatch: pytest.MonkeyPatch, check) -> dict[str, int]:
    """
    Four days of the attentive player, looking every waking hour (three Matchstick likes and one Front
    Porch like a day) with every like returned and
    the proposing voice; ``check(tx, state)`` runs at the end of every commit's
    transaction body, after all of its writes. Counts of the proposals applied.
    """
    import scripts.simulate_social as sim
    from engine.social import matching, relationships, voicer

    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    applied: dict[str, int] = {}
    real_proposal = relationships.apply_proposal

    def counting(state: Any, pid: str, name: str, **kw: Any) -> dict[str, Any]:
        out = real_proposal(state, pid, name, **kw)
        if out.get("ok", True):
            applied[name] = applied.get(name, 0) + 1
        return out

    monkeypatch.setattr(relationships, "apply_proposal", counting)
    real_followups = relationships.apply_followups

    def counting_followups(state: Any, pid: str, rows: Any, **kw: Any) -> list[dict[str, Any]]:
        made = real_followups(state, pid, rows, **kw)
        if made:
            applied["followups"] = applied.get("followups", 0) + len(made)
        return made

    monkeypatch.setattr(relationships, "apply_followups", counting_followups)
    # The number and meet-up gates open (T26 tuned them to weeks of contact): this is a commit's
    # coverage, not balance, and a meet-up proposal is one of the writes a commit can make.
    real_gate = relationships.gate_spec
    monkeypatch.setattr(relationships, "gate_spec",
                        lambda stage: {} if stage in ("numbers", "meeting") else real_gate(stage))
    # A media offer needs a budget the run's four days do not refill (v0.23.0 T3 shortened the run):
    # coverage again, not balance.
    from engine.social import media

    real_budget = media.budget_of
    monkeypatch.setattr(media, "budget_of", lambda person, kind: max(2.0, real_budget(person, kind)))
    real_scoped = voicer.scoped_transaction

    @contextmanager
    def checked(state: Any, pid: str):
        with real_scoped(state, pid) as tx:
            yield tx
            check(tx, state)

    monkeypatch.setattr(voicer, "scoped_transaction", checked)
    from tests.social_fixtures import _replies_forced

    # Every read answered and nobody ghosts (T26's tuning makes most matches go quiet within days), so
    # relationships reach the stages whose proposals (a number, a voice note, a meet-up) open.
    with sim._quiet_summaries(), _replies_forced():
        phone = sim.Phone(3, "romantic_model")
        phone.llm = _Proposer()
        try:
            player = sim.POLICIES["attentive"](phone, 3)
            player.matchstick_likes, player.porch_likes = 3, 1   # every like returned: a few people, often
            # v0.23.0: a reply lands at the send's minute, so `wait next` no longer stops at it; the player
            # looks every waking hour instead, and writes more, so the run still makes hundreds of commits.
            player.looks = tuple(range(7, 23))
            player.sends_per_person_day = 12
            end = phone.now + 4 * 24.0       # v0.23.0: four days of hourly looks make more commits than seven did
            while phone.now < end:
                player.step()
        finally:
            phone.close()
    return applied


@pytest.mark.slow                      # about three minutes: ~700 commits, each serialised three times
@pytest.mark.timeout(1800)
def test_every_commit_rolled_back_after_its_writes_leaves_the_whole_state_unchanged(
        receipts_active, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.game.transaction import restore_in_place

    seen = {"commits": 0, "wrote": 0}
    befores: list[tuple[str, str]] = []
    real_init = None

    from engine.social import voicer

    real_init = voicer.ScopedTransaction.__init__

    def init(self: Any, state: Any, pid: str) -> None:
        befores.append((_whole(state), _outside(state)))
        real_init(self, state, pid)

    monkeypatch.setattr(voicer.ScopedTransaction, "__init__", init)

    def check(tx: Any, state: Any) -> None:
        whole, outside = befores.pop()
        assert _outside(state) == outside, "a commit wrote outside state.social and state.rng_counters"
        after = state.to_save_dict()
        seen["wrote"] += _whole(state) != whole
        tx.rollback()
        assert _whole(state) == whole, "the scoped rollback missed a write"
        seen["commits"] += 1
        restore_in_place(state, type(state).from_dict(after))   # the commit, as it was, and play goes on

    applied = _play(monkeypatch, check)
    # Not vacuous: many commits, most of them writing, and the proposals of every kind a reply can carry.
    assert seen["commits"] >= 300, seen
    assert seen["wrote"] >= seen["commits"] // 2, seen
    for name in ("offer_number", "offer_voice", "invite_game", "ask_meet", "cool_off", "promise", "followups"):
        assert applied.get(name), f"no {name} was applied: {applied}"


@pytest.mark.parametrize("where", ["regard", "canon", "knows", "proposal", "followups"])
def test_a_commit_that_raises_part_way_leaves_the_state_as_it_was(
        receipts_active, monkeypatch: pytest.MonkeyPatch, where: str) -> None:
    """Each write of the commit made, then a raise: the transaction rolls back every write before it."""
    import dataclasses

    import scripts.simulate_social as sim
    from engine.session.store import release_turn
    from engine.social import memory, relationships, voicer, voicing

    from tests.test_social_replay import _due_phone

    target = {"regard": (relationships, "apply_regard"), "canon": (memory, "add_canon"),
              "knows": (memory, "add_knows"), "proposal": (relationships, "apply_proposal"),
              "followups": (relationships, "apply_followups")}[where]
    real = getattr(*target)
    calls = []

    def boom(*a: Any, **k: Any) -> Any:
        real(*a, **k)
        calls.append(where)
        raise RuntimeError(f"injected after {where}")

    with sim._quiet_summaries():
        phone = _due_phone(sim, monkeypatch)
        try:
            p = voicer.VoicePass(phone.session, phone.session.epoch)
            assert phone.session.lock.acquire(blocking=False)
            try:
                snaps = voicer.snapshot(phone.session, p)
            finally:
                release_turn(phone.session)
            snap = snaps[0]
            legal = list(relationships.legal_proposals(phone.state, snap.pid))
            assert "cool_off" in legal, legal
            reply = dataclasses.replace(voicing.fallback_reply(snap, "test"), fallback=False,
                                        bubbles=["that sounds lovely"], regard={"warmth": 3, "trust": 1},
                                        shared=["grew up by the sea"], learned=["likes jazz"],
                                        proposals=("cool_off",),
                                        followups=[{"about": "the interview", "when": "tomorrow"}])
            before = _whole(phone.state)
            monkeypatch.setattr(*target, boom)
            with pytest.raises(RuntimeError, match="injected"):
                voicer.commit(phone.session, p, reply)
            assert calls == [where]
            assert _whole(phone.state) == before
            assert not phone.session.lock.locked()
        finally:
            phone.close()


def test_the_snapshot_copies_only_the_replying_persons_rows(receipts_active) -> None:
    """The point of the scope: another person's rows are kept by reference, theirs by copy."""
    import scripts.simulate_social as sim
    from engine.social import voicer

    with sim._quiet_summaries():
        phone = sim.Phone(1, "zero")
        try:
            state = phone.state
            state.social["people"].setdefault("pA", {"warmth": 1})
            state.social["people"].setdefault("pB", {"warmth": 2})
            state.social["requests"]["rA"] = {"id": "rA", "pid": "pA", "status": "pending"}
            state.social["requests"]["rB"] = {"id": "rB", "pid": "pB", "status": "pending"}
            tx = voicer.ScopedTransaction(state, "pA")
            people = tx._saved["people"][1]
            requests = tx._saved["requests"][1]
            assert people["pB"] is state.social["people"]["pB"]
            assert people["pA"] is not state.social["people"]["pA"]
            assert requests["rB"] is state.social["requests"]["rB"]
            assert requests["rA"] is not state.social["requests"]["rA"]
            # A write to pA's rows, a new row and a new key are all undone, in place.
            people_map = state.social["people"]
            state.social["people"]["pA"]["warmth"] = 99
            state.social["requests"]["rA"]["status"] = "yes"
            state.social["requests"]["rC"] = {"id": "rC", "pid": "pA"}
            state.social["new_key"] = 1
            tx.rollback()
            assert state.social["people"] is people_map
            assert state.social["people"]["pA"]["warmth"] == 1
            assert state.social["requests"]["rA"]["status"] == "pending"
            assert "rC" not in state.social["requests"]
            assert "new_key" not in state.social
        finally:
            phone.close()


def test_a_commit_that_steps_growth_writes_it_inside_the_scope(receipts_active, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Lesson 12 (v0.23.0 T2): a voiced commit whose decision moves growth writes the person's
    ``growth`` row -- and the history row a step adds -- INSIDE ``voicer.ScopedTransaction``'s
    scope. Here the commit's regard write is followed by a ``social_growth`` gain that steps a rung
    (T3 wires the real gain); rolled back after every write, the state is byte-identical, and a
    raise after it leaves nothing behind.
    """
    import dataclasses
    from contextlib import contextmanager

    import scripts.simulate_social as sim
    from engine.game.effects import apply_effect
    from engine.session.store import release_turn
    from engine.social import growth, relationships, voicer, voicing

    from tests.test_social_replay import _due_phone

    real_regard = relationships.apply_regard
    real_scoped = voicer.scoped_transaction                  # production's context manager, taken once

    def regard_then_grow(state: Any, pid: str, *a: Any, **k: Any) -> Any:
        out = real_regard(state, pid, *a, **k)
        apply_effect(state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
        return out

    for mode in ("rollback", "raise"):
        with sim._quiet_summaries():
            phone = _due_phone(sim, monkeypatch)
            try:
                p = voicer.VoicePass(phone.session, phone.session.epoch)
                assert phone.session.lock.acquire(blocking=False)
                try:
                    snap = voicer.snapshot(phone.session, p)[0]
                finally:
                    release_turn(phone.session)
                pid = snap.pid
                # The everyday rung's floors met, so the gain steps (the scope must hold the step's writes).
                assert apply_effect(phone.state, {"type": "social_person", "pid": pid,
                                                  "set": {"warmth": 99, "trust": 99, "episodes_done": 9}})["ok"]
                reply = dataclasses.replace(voicing.fallback_reply(snap, "test"), fallback=False,
                                            bubbles=["that sounds lovely"], regard={"warmth": 3, "trust": 1})
                before = _whole(phone.state)
                seen: list[int] = []
                monkeypatch.setattr(relationships, "apply_regard", regard_then_grow)

                @contextmanager
                def checked(state: Any, scope_pid: str):
                    with real_scoped(state, scope_pid) as tx:
                        yield tx
                        seen.append(growth.depth(state, pid))
                        assert state.social["people"][pid]["memory"]["history"][-1]["kind"] == "growth"
                        if mode == "rollback":
                            tx.rollback()
                            assert _whole(state) == before, "the scoped rollback missed a growth write"
                        else:
                            # Raised INSIDE production's `with`: its own `except: tx.rollback(); raise`
                            # is what undoes the growth step (review M4).
                            raise RuntimeError("injected after the growth step")

                monkeypatch.setattr(voicer, "scoped_transaction", checked)
                if mode == "raise":
                    with pytest.raises(RuntimeError, match="injected"):
                        voicer.commit(phone.session, p, reply)
                else:
                    voicer.commit(phone.session, p, reply)
                assert seen == [1], seen
                assert _whole(phone.state) == before
            finally:
                monkeypatch.setattr(relationships, "apply_regard", real_regard)
                phone.close()


def test_a_commit_that_queues_the_next_decision_rolls_back_whole(receipts_active, monkeypatch) -> None:
    """
    Lesson 12 (v0.23.0 T3): a send made while the pass wrote (its reply MARKED) is answered by the commit,
    which queues the NEXT decision (`convo.after_commit`) -- a `social_episode` exchange, a growth gain,
    a new due message and its event -- INSIDE ``voicer.ScopedTransaction``'s scope: rolled back after
    every write, the state is byte-identical.
    """
    import dataclasses
    from contextlib import contextmanager

    from engine.session.store import release_turn
    from engine.social import messaging, voicer, voicing
    from tests.social_fixtures import _live_session, _matched_in, _open_episode, _phone, _replies_forced

    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    with _replies_forced():
        assert session.lock.acquire(blocking=False)
        try:
            _open_episode(state, pid, thread)
        finally:
            release_turn(session)
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text="how was the climb?")
        p = voicer.VoicePass(session, session.epoch)
        assert session.lock.acquire(blocking=False)
        try:
            (snap,) = voicer.snapshot(session, p)                  # MARKED for p
        finally:
            release_turn(session)
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text="and are you free friday?")
        assert len(messaging.unvoiced(state)) == 1                 # marked: the send changed nothing yet
        reply = dataclasses.replace(voicing.fallback_reply(snap, "test"), fallback=False,
                                    bubbles=["it was great"], regard={"warmth": 2, "trust": 1})
        real_scoped = voicer.scoped_transaction
        seen: list[int] = []

        @contextmanager
        def checked(state_: Any, scope_pid: str):
            before = _whole(state_)
            exchanges = state_.social["people"][scope_pid]["episode"]["exchanges"]
            with real_scoped(state_, scope_pid) as tx:
                yield tx
                due = messaging.unvoiced(state_)
                seen.append(len(due))
                assert state_.social["people"][scope_pid]["episode"]["exchanges"] == exchanges + 1
                tx.rollback()
                assert _whole(state_) == before, "the scoped rollback missed the next decision's writes"

        monkeypatch.setattr(voicer, "scoped_transaction", checked)
        assert session.lock.acquire(blocking=False)
        try:
            voicer._apply_reply(session, p.id, reply, p=p)
        finally:
            release_turn(session)
    assert seen == [1]                                             # the next decision, due, inside the scope
    assert p.rerun is True


def test_a_recap_commit_rolls_back_whole(receipts_active, monkeypatch) -> None:
    """
    v0.23.0 T6: a recap's commit (`voicer._recap_one`) writes the person's memory -- the episode, the
    bridge, `current` cleared, its `recap_due` row consumed -- INSIDE ``voicer.ScopedTransaction``'s
    scope: rolled back after every write, the state is byte-identical; a raise after them leaves nothing.
    """
    from contextlib import contextmanager

    from engine.game import clock
    from engine.session.store import release_turn
    from engine.social import memory, voicer
    from tests.social_fixtures import _live_session, _matched_in, _open_episode, _phone, _replies_forced
    from tests.social_stub import StubVoice

    for mode in ("rollback", "raise"):
        scene, session = _live_session()
        state = session.engine.state
        thread = _matched_in(session, "matchstick")
        pid = thread.split(":")[1]
        with _replies_forced():
            assert session.lock.acquire(blocking=False)
            try:
                _open_episode(state, pid, thread)
            finally:
                release_turn(session)
            _phone(scene, session, "send", target=thread, args={"kind": "text"}, text="how was the climb?")
        voicer.run_until_quiet(session, StubVoice("zero"))      # the reply voiced; no recap due yet
        assert session.lock.acquire(blocking=False)
        try:
            clock.advance_time(state, 1.0)                      # the episode lapses: a recap is due
        finally:
            release_turn(session)
        assert state.social["people"][pid].get("recap_due")
        real_scoped = voicer.scoped_transaction
        seen: list[str] = []

        @contextmanager
        def checked(state_: Any, scope_pid: str):
            before = _whole(state_)
            with real_scoped(state_, scope_pid) as tx:
                yield tx
                seen.append(memory.person(state_, scope_pid)["episodes"][-1]["recap"])
                assert not state_.social["people"][scope_pid].get("recap_due")
                assert memory.person(state_, scope_pid)["current"] == []
                if mode == "rollback":
                    tx.rollback()
                    assert _whole(state_) == before, "the scoped rollback missed a recap write"
                else:
                    raise RuntimeError("injected after the recap")

        monkeypatch.setattr(voicer, "scoped_transaction", checked)
        p = voicer.VoicePass(session, session.epoch)
        before = _whole(state)
        if mode == "raise":
            with pytest.raises(RuntimeError, match="injected"):
                voicer._recap_one(session, p)
        else:
            voicer._recap_one(session, p)
        monkeypatch.setattr(voicer, "scoped_transaction", real_scoped)
        assert len(seen) == 1 and seen[0]
        assert _whole(state) == before and state.social["people"][pid].get("recap_due")
        assert not session.lock.locked()

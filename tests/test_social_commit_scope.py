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

    def __call__(self, messages: list[dict[str, Any]], fmt: dict[str, Any]) -> str:
        self.n += 1
        props = (((fmt or {}).get("json_schema") or {}).get("schema") or {}).get("properties") or {}
        out: dict[str, Any] = {"bubbles": [{"text": "that sounds lovely, tell me more"}],
                               "regard": {"warmth": 3, "trust": 2, "mood": "fond"},
                               "learned": [f"likes thing {self.n}"], "shared": [f"grew up by the sea {self.n}"]}
        legal = list(((props.get("proposals") or {}).get("items") or {}).get("enum") or [])
        if "proposals" in props:
            out["proposals"] = [legal[self.n % len(legal)]] if legal else []
        if "media" in props:
            out["media"] = {"caption": "this one's for you"}
        return json.dumps(out)


def _play(monkeypatch: pytest.MonkeyPatch, check) -> dict[str, int]:
    """
    Seven days of the attentive player (three Matchstick likes and one Front
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
    # The number and meet-up gates open (T26 tuned them to weeks of contact): this is a commit's
    # coverage, not balance, and a meet-up proposal is one of the writes a commit can make.
    real_gate = relationships.gate_spec
    monkeypatch.setattr(relationships, "gate_spec",
                        lambda stage: {} if stage in ("numbers", "meeting") else real_gate(stage))
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
            end = phone.now + 7 * 24.0
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
    for name in ("offer_number", "offer_voice", "invite_game", "ask_meet", "cool_off"):
        assert applied.get(name), f"no {name} was applied: {applied}"


@pytest.mark.parametrize("where", ["regard", "canon", "knows", "proposal"])
def test_a_commit_that_raises_part_way_leaves_the_state_as_it_was(
        receipts_active, monkeypatch: pytest.MonkeyPatch, where: str) -> None:
    """Each write of the commit made, then a raise: the transaction rolls back every write before it."""
    import dataclasses

    import scripts.simulate_social as sim
    from engine.session.store import release_turn
    from engine.social import memory, relationships, voicer, voicing

    from tests.test_social_replay import _due_phone

    target = {"regard": (relationships, "apply_regard"), "canon": (memory, "add_canon"),
              "knows": (memory, "add_knows"), "proposal": (relationships, "apply_proposal")}[where]
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
                                        proposals=("cool_off",))
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

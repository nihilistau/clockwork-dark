"""
Records tests/fixtures/social/v022_save (v0.23.0 T20, spec §16.3): a READ RECEIPTS run played by v0.22.0's
OWN code, at 60215f4, saved by v0.22's own SessionStore/SaveStore. Run it from the root of a git worktree
of 60215f4 (README.md beside this file has the commands). It calls no model (the harness's stub voice and
summary), and it writes only into a fresh temporary CLOCKWORK_DATA_DIR and the --out folder.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.getcwd())                       # the 60215f4 worktree's root (the cwd)
_DATA = tempfile.mkdtemp(prefix="cd-v022-record-")
os.environ["CLOCKWORK_DATA_DIR"] = _DATA              # never the owner's storage
import engine                                          # noqa: E402

assert Path(engine.__file__).resolve().is_relative_to(Path(os.getcwd()).resolve()), engine.__file__

import argparse  # noqa: E402
import shutil  # noqa: E402
from typing import Any  # noqa: E402

SEED = 7
DAYS = 10
COMMIT = "60215f4"


def _newest_live_thread(state: Any) -> str:
    from engine.social import apps, messaging, relationships

    people = state.social.get("people") or {}
    rows = []
    for tid, t in (state.social.get("threads") or {}).items():
        person = people.get(t["pid"]) or {}
        if (t.get("closed") or apps.gone(state, t["pid"]) or person.get("ghosted")
                or not relationships.live(person)):
            continue
        rows.append((messaging._last_at(t), tid))
    if not rows:
        raise SystemExit("record_v022: no live thread to leave unanswered")
    return max(rows)[1]


def _agree_a_meet(phone: Any) -> str:
    """One meet `agreed` through v0.22's own `meets.propose`, its gate forced open (`answer_ask`'s check) and,
    for a picky run with nobody at `numbers` yet, its stage floor forced to `matched`."""
    from engine.social import kinds, meets

    state = phone.state
    if any(m.get("status") == "agreed" for m in (state.social.get("meets") or {}).values()):
        return "already"
    people = state.social.get("people") or {}
    threads = state.social.get("threads") or {}
    pids = sorted({t["pid"] for t in threads.values()},
                  key=lambda p: (-kinds.stage_rank((people.get(p) or {}).get("stage")), p))
    real_gate, real_rank = meets.gate_open, meets._from_rank
    meets.gate_open = lambda s, p: True                 # forced: "answer_ask forced True"
    meets._from_rank = lambda: 0
    try:
        for pid in pids:
            if meets.propose_refusal(state, pid):
                continue
            venue = meets.pick_venue(state, pid)
            found = meets.first_free(state, pid, float(meets.venue(venue)["duration_hours"]))
            if found is None:
                continue
            day, slot = found
            out = meets.propose(state, pid, venue, day - state.world_day, slot)
            if out.get("answer") == "accept":
                return pid
    finally:
        meets.gate_open, meets._from_rank = real_gate, real_rank
    raise SystemExit("record_v022: no meet could be agreed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--policy", default="picky")
    args = parser.parse_args()

    from scripts import simulate_social as sim
    from engine.session.store import release_turn
    from engine.social import archive, messaging

    run_dir = Path(_DATA) / "run"
    with sim._quiet_summaries():
        phone = sim.Phone(SEED, "romantic_model", disk=run_dir)
        player = sim.POLICIES[args.policy](phone, SEED)
        end = phone.now + DAYS * 24.0
        while phone.now < end:
            player.step()
        state = phone.state
        meet_pid = _agree_a_meet(phone)
        # One player message left unanswered: sent through v0.22's Phone, nothing advanced after it.
        for _ in range(5):
            tid = _newest_live_thread(state)
            phone.act("send", tid, {"kind": "text"}, "still around this week?")
            last = messaging.last_shown(state.social["threads"][tid])
            if last is not None and last.get("from") == "player":
                break
        else:
            raise SystemExit("record_v022: every send was answered at once")
        kinds_queued = {e["kind"] for e in state.social.get("queue") or []}
        if "daily" not in kinds_queued:
            raise SystemExit("record_v022: no daily queued")
        session = phone.session
        if not session.lock.acquire(blocking=False):
            raise RuntimeError("record_v022: the run's turn lock is held")
        try:
            archive.spill(session)
            session.saves.save(state, save_id=session.save_id, memory=session.ledger.to_dict())
        finally:
            release_turn(session)
        src = Path(session.saves.path_for(session.save_id))
        args.out.mkdir(parents=True, exist_ok=True)
        for name in ("save.json", "memory.json", "phone_archive.jsonl"):
            if (src / name).exists():
                shutil.copy(src / name, args.out / name)
        print(f"recorded {COMMIT} seed={SEED} days={DAYS} policy={args.policy} meet={meet_pid} "
              f"unanswered={tid} location={state.location_id}")
        for name in ("save.json", "memory.json", "phone_archive.jsonl"):
            if (args.out / name).exists():
                print(f"  {name}: {(args.out / name).stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        shutil.rmtree(_DATA, ignore_errors=True)       # the throwaway storage root, whatever happened

"""
Where the cast is, in person (v0.23.0 addendum 4 W4; T23C's plan tier, T23G's chance tier, W9).

A person is somewhere only when the engine has put them there:

- **the scene's person** is wherever the open scene is (`scene.current`);
- **the plan tier**: the person of an open `now` / `tonight` plan who has ARRIVED (`plans.has_arrived`,
  written by `plan_arrive`) is at that plan's place (`plans.place_of`; a `your_place` plan's is the
  player's flat);
- **the chance tier** (W9): only while the player is at a VENUE, a live contact may be there by their
  schedule (`chance_here`). Per person and block of scenes.yaml `chance.block_hours`, ONE counterless
  `stable_rng(seed, "chance:<pid>:<day>:<block>")` decides whether they are out (`chance.prob` of their
  status now, `out` or `free`) and, from the same draw, which ONE of the venues that fit them
  (`places.fitting_venues`) they are at. So a person is in one place per block, the answer replays, and
  reading it moves no counter (rule 4: no other system's draws shift). The candidates are the player's
  live contacts, never the population: at most `chance.max_candidates`, the most recently in contact
  first, less the blocked and unmatched, the ghosting, anyone away (a life event), the household
  partner, anyone with an open `now` / `tonight` plan (the plan tier places them) and the scene's
  person. At most `chance.max_here` are at one venue, by pid. After a chance scene with someone ends they are
  still here for the rest of their block (they have not left), only not approachable again (their row's
  `chance_met`, one "<day>:<block>" string, read by `scene.approach_options`).

Anyone else is nowhere the player can be (""): on their way, at home off-screen, at work. Nothing here
draws a counter or writes: `here_view` is read once per pass (I7) and `where` / `with_player` read it, so a
read path that asks never moves a stream or a row (`test_read_paths_draw_and_write_nothing_for_presence`,
`test_chance_presence_replays_and_writes_nothing`).

**Cost (I7).** Away from a venue the chance tier is never computed (the short-circuit): a view is O(open
plans). At a venue it reads the people rows once (no profile) and, for each candidate, one `stable_rng`;
only a candidate whose draw falls under the HIGHEST `chance.prob` has their profile read (the status and
the venues), so a pass reads ~max-prob x candidates profiles. `with_player` with no view (the delivery
seam's `messaging.held`, once per due event) asks about ONE person: the plan tier, then that person's own
draw, and the whole tier only when the draw puts them here (for the `max_here` cut). Stateless, with no
globals and no cache: no module-state row.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional

from engine.game.rng import stable_rng
from engine.game.state import GameState
from engine.social import behaviour, places, population
from engine.social.kinds import PRESENCE_PASS

#: The schedule statuses a person can be out at a venue in (scenes.yaml `chance.prob`'s keys that count).
_OUT_STATUSES: tuple[str, ...] = ("out", "free")


def _chance_cfg() -> dict[str, Any]:
    from engine import social

    return dict((social.data("scenes") or {}).get("chance") or {})


def _block(state: GameState, cfg: dict[str, Any]) -> tuple[int, int]:
    """(day, block) of now: the chance draw's key (a block of `block_hours` of the day)."""
    hours = float(state.world_clock_hours)
    size = float(cfg.get("block_hours", 3) or 3)
    return int(hours // 24), int((hours % 24) // size)


def _at_a_venue(state: GameState, here: str) -> bool:
    """The chance tier applies: the player is at a venue, not at work, in a story with `chance:` (the short-circuit)."""
    social_ = getattr(state, "social", None) or {}
    return bool(social_) and not social_.get("at_work") and bool(_chance_cfg()) and here in places.venue_ids()


def block_key(state: GameState) -> str:
    """Now's chance block as "<day>:<block>": what a person row's `chance_met` holds after a chance scene with them
    ended (scene `_end`), so "Go over to" is not offered again for the rest of that block (they stay present). One
    short string a person."""
    day, n = _block(state, _chance_cfg())
    return f"{day}:{n}"


def _chance_venue(state: GameState, pid: str, cfg: Optional[dict[str, Any]] = None,
                  block: Optional[tuple[int, int]] = None) -> str:
    """The ONE venue `pid` is at in this block, or "" (A4 W9). Counterless: reading draws no counter and writes
    nothing. The first value of the draw says whether they are out (under `prob[status]`); the second picks
    the venue among those that fit them."""
    cfg = _chance_cfg() if cfg is None else cfg
    probs = cfg.get("prob") or {}
    top = max((float(probs.get(s, 0.0) or 0.0) for s in _OUT_STATUSES), default=0.0)
    if top <= 0.0:
        return ""
    day, n = _block(state, cfg) if block is None else block
    rng = stable_rng(int(state.rng_seed), f"chance:{pid}:{day}:{n}")
    first = rng.random()
    if first >= top:                                   # out under no status: no profile read (I7)
        return ""
    person = population.profile(state, pid)
    status = behaviour.status_at(person, state.world_clock_hours)
    prob = float(probs.get(status, 0.0) or 0.0) if status in _OUT_STATUSES else 0.0
    if first >= prob:
        return ""
    fitting = places.fitting_venues(state, pid)
    return fitting[int(rng.random() * len(fitting))] if fitting else ""


def _last_contact(row: dict[str, Any]) -> float:
    marks = [row.get(k) for k in ("last_player_at", "last_them_at", "matched_at")]
    return max((float(v) for v in marks if v is not None), default=float("-inf"))


def candidates(state: GameState, cfg: Optional[dict[str, Any]] = None, *, scene_pid: str = "") -> list[str]:
    """The chance tier's candidates (A4 W9): the live contacts less the blocked and unmatched, the ghosting,
    anyone away, the household partner, anyone with an open `now` / `tonight` plan and the scene's person;
    at most `chance.max_candidates`, the most recently in contact first. Reads the people rows only, never
    the population. Reads only."""
    from engine.social import life, plans, relationships

    cfg = _chance_cfg() if cfg is None else cfg
    social_ = state.social or {}
    live = frozenset(relationships.LIVE_STAGES)
    planned = {str(r.get("pid")) for r in plans.open_for(state) if r.get("when") in ("now", "tonight")}
    skip = planned | {str(social_.get("household") or ""), scene_pid}
    now = float(state.world_clock_hours)
    rows = []
    for pid, row in (social_.get("people") or {}).items():
        if (not isinstance(row, dict) or row.get("stage") not in live or pid in skip
                or row.get("blocked") or row.get("unmatched_by") or row.get("ghosted")):
            continue
        rows.append((-_last_contact(row), pid, row))
    rows.sort(key=lambda r: (r[0], r[1]))
    cap = int(cfg.get("max_candidates", 200) or 0)
    out: list[str] = []
    for _, pid, row in rows:
        if len(out) >= cap:
            break
        if row.get("life") and life.unavailable(state, pid, now):
            continue                                     # away: a holiday of theirs (a life event)
        out.append(pid)
    return out


@contextlib.contextmanager
def one_pass() -> Iterator[None]:
    """One pass (I7): inside it `chance_here` is computed once per (state, place, hour, scene) and every caller --
    the narration block, each `legal_intents`, the payload's `world.here`, the holds -- reads that. Any social
    effect drops the memo (`kinds.recorded`), so nothing reads a tier from before a write. A ContextVar, set for
    the pass and reset after it: no module global. Nested passes share the outer one."""
    if PRESENCE_PASS.get() is not None:
        yield
        return
    token = PRESENCE_PASS.set({})
    try:
        yield
    finally:
        PRESENCE_PASS.reset(token)


def chance_here(state: GameState, location: str, *, scene_pid: Optional[str] = None) -> tuple[str, ...]:
    """Who the player knows is at `location` by chance now (A4 W9): () unless it is a venue (and the player is
    not at work); else the candidates whose one venue this block is `location`, by pid, at most
    `chance.max_here`. Reads only: no counter moves, nothing is written."""
    if not _at_a_venue(state, location):
        return ()
    from engine import social

    cfg = _chance_cfg()
    if scene_pid is None:
        from engine.social import scene

        scene_pid = str(scene.current(state).get("pid") or "") if social.scene_open(state) else ""
    memo = PRESENCE_PASS.get()
    key = (id(state), location, float(state.world_clock_hours), scene_pid)
    if memo is not None and key in memo:
        return memo[key]
    block = _block(state, cfg)
    here = sorted(pid for pid in candidates(state, cfg, scene_pid=scene_pid)
                  if _chance_venue(state, pid, cfg, block) == location)
    out = tuple(here[:max(0, int(cfg.get("max_here", 2) or 0))])
    if memo is not None:
        memo[key] = out
    return out


def here_view(state: GameState) -> dict[str, Any]:
    """Who is where now, read once: `location` (the player's), `scene` (the open scene's person and place, or
    {}), `arrived` (pid -> the place of their arrived plan), `chance` (the pids at the player's venue by chance,
    W9; () off venues, where it is never computed) and `with_player` (pids at the player's place, the chance
    tier's included)."""
    from engine import social
    from engine.social import plans, scene

    here = str(state.location_id or "")
    scn = scene.current(state) if social.scene_open(state) else {}
    arrived: dict[str, str] = {}
    together: list[str] = []
    for row in plans.open_for(state):
        if row.get("when") == "soon" or row.get("kind") == plans.WEDDING or not plans.has_arrived(row):
            continue
        pid = str(row["pid"])
        if pid in arrived:
            continue
        arrived[pid] = plans.place_of(state, row)
        if plans.player_at(state, row, here) and pid not in together:
            together.append(pid)
    pid = str(scn.get("pid") or "")
    if pid and pid not in together:
        together.insert(0, pid)
    chance = chance_here(state, here, scene_pid=pid)
    together += [p for p in chance if p not in together]
    return {"location": here, "scene": {"pid": pid, "location": str(scn.get("location") or "")} if pid else {},
            "arrived": arrived, "chance": chance, "with_player": together}


_here_view = here_view          # the name `where` and `with_player` reach past their own `here_view` argument


def where(state: GameState, pid: str, here_view: Optional[dict[str, Any]] = None) -> str:
    """The location id `pid` is at in person (the open scene's place, their arrived plan's, or the player's venue
    by chance), or "" for nowhere the player can be. Reads only."""
    view = here_view if here_view is not None else _here_view(state)
    scn = view.get("scene") or {}
    if scn.get("pid") == pid:
        return str(scn.get("location") or "")
    if pid in (view.get("chance") or ()):
        return str(view.get("location") or "")
    return str((view.get("arrived") or {}).get(pid) or "")


def _by_chance(state: GameState, pid: str) -> bool:
    """`pid` is at the player's venue by chance now: their own draw first (O(1)), the whole tier only when it puts
    them here (the `max_here` cut is by pid). Reads only."""
    here = str(state.location_id or "")
    if not _at_a_venue(state, here):
        return False
    cfg = _chance_cfg()
    if _chance_venue(state, pid, cfg) != here:
        return False
    return pid in chance_here(state, here)


def with_player(state: GameState, pid: str, here_view: Optional[dict[str, Any]] = None) -> bool:
    """`pid` is where the player is: in the open scene with them, arrived for a plan at the player's place (any
    of the flat's places, for a `your_place` plan), or at the player's venue by chance (W9: present across the
    room counts, approached or not: their texts wait, W5). Reads only. With no view (one question, the delivery
    seam's), only `pid`'s own chance draw is read unless it puts them here."""
    if here_view is not None:
        return pid in (here_view.get("with_player") or ())
    from engine import social
    from engine.social import plans, scene

    if social.scene_open(state) and str(scene.current(state).get("pid") or "") == pid:
        return True
    here = str(state.location_id or "")
    for row in plans.open_for(state, pid):           # `here_view`'s plan tier for one person: their first arrived row
        if row.get("when") != "soon" and row.get("kind") != plans.WEDDING and plans.has_arrived(row):
            if plans.player_at(state, row, here):
                return True
            break
    return _by_chance(state, pid)

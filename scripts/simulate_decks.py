"""
Headless Deck-Story Walker
==========================

The simulation harness for the OTHER story shape. ``scripts/simulate.py`` is a
graph-shape harness: its five policies walk a travel graph, buy bread from
named vendors and drill flagship skills, and every one of those nouns is The
Clockwork Dark's. A deck-shaped story -- authored day chapters, progress
clocks, threads, gated endings, epilogue cards -- had NO headless way to know
that an ending is unreachable, that a card can never be dealt, or that a clock
never fires. This script is how those claims get measured instead of asserted.

WHAT IT DRIVES, AND THROUGH WHICH DOORS. The real loaders, through the same
entry points the scene uses:

    deck.draw / deck.resolve_card      the hand and the beats, per chapter
    clocks.resolve                     auto-advance rules and threshold beats
    threads.offer/renegotiate/seal/
        discharge/break/expire_due     the bargain lifecycle
    endings.recompute/set_intent/
        lock/run_module                the finale chain (usually via the story's
                                       own ``ending_lock`` card effect)
    epilogue.for_state                 the last screen, on the real trigger

WHAT THE POLICY IS. Seeded weighted-random over every choice point the content
exposes: which beat of a ``menu`` card, what quality a ``band`` beat landed at,
which eligible ending is sworn and locked, which declared thread template gets
sealed and whether it is renegotiated first. No model anywhere -- a band with
no judged quality resolves through the same code path the engine ships for
that case, and the walker judges with a seeded uniform draw instead so the
range is actually swept.

WHAT IT APPROXIMATES, honestly:

  * **The day advance.** A chapter deck is played, then ``advance_time`` moves
    the clock ``CHAPTER_HOURS`` (24h) -- one deck, one day. In the running game
    the scene owns pacing; the walker's calendar is a modelling choice, made
    through the one legal writer of world time.
  * **Threads are agent-sealed in real play.** No card effect seals a bargain;
    an agent does, mid-scene. The walker stands in with a seeded policy
    (``--thread-rate`` per chapter) so thread-gated clocks, cutters and ending
    ``completable`` gates get exercised at all. A clock only agents wind (the
    Garden's ``ashen_pressure``, ``sophia_break``) will honestly report a low
    fire rate here -- that is the walker's blind spot, not the story's bug.
  * **Menu choices are uniform**, not in-character. The walker measures
    reachability, not taste.

RNG DISCIPLINE (CLAUDE.md rule 4). Engine-side draws (deck deals, hidden beat
checks, arbitrary cuts) run on the state's own named ``world_rng`` streams,
seeded by the run seed, exactly as they would in play. The walker's OWN choices
draw from ``stable_rng(run_seed, "sim.deck_policy")`` -- a named, documented
stream, so the same seed replays the same run and the policy's draws cannot
shift the engine's.

Usage:
    python scripts/simulate_decks.py --game wicked-garden --runs 200
    python scripts/simulate.py --game wicked-garden --runs 200   # same thing
    python scripts/simulate_decks.py --game wicked-garden --json > decks.json

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.content import deck as deck_module  # noqa: E402
from engine.game import clocks as clocks_module  # noqa: E402
from engine.game import endings as endings_module  # noqa: E402
from engine.game import epilogue as epilogue_module  # noqa: E402
from engine.game import threads as threads_module  # noqa: E402
from engine.game.clock import advance_time  # noqa: E402
from engine.game.rng import stable_rng  # noqa: E402
from engine.game.state import GameState  # noqa: E402
from engine.memory.ledger import StoryLedger  # noqa: E402
from engine.state.active import active_schema, store_for  # noqa: E402

#: In-game hours one chapter deck is worth. See the module docstring: the
#: walker's calendar, applied through the one legal writer of world time.
CHAPTER_HOURS = 24.0

#: Ceiling on forced-scene deck replays per run, so a clock that forces the
#: deck that fills it cannot loop the walker forever.
MAX_FORCED_PLAYS = 3

#: Named stream for every choice the WALKER makes (as opposed to the engine).
POLICY_STREAM = "sim.deck_policy"

#: Per-day chance an active thread is discharged / broken by the policy, so
#: ``on_discharge`` and ``on_break`` hooks and the ledger promise mirror both
#: get walked. Discharge is likelier: most bargains in most runs get paid.
DISCHARGE_CHANCE = 0.15
BREAK_CHANCE = 0.10


# ---------------------------------------------------------------------------
# per-run record
# ---------------------------------------------------------------------------


@dataclass
class DeckRunResult:
    """Everything one walked run produced."""

    seed: int
    days: int = 0
    steps: int = 0
    passes: int = 0
    ending_locked: str = ""
    ending_class: str = ""
    ending_forced: bool = False
    intent_sworn: str = ""
    epilogue_rendered: bool = False
    eligible_at_finale: list[str] = field(default_factory=list)
    #: (clock, beat_id, step) for every threshold beat that fired.
    clock_fires: list[tuple[str, str, int]] = field(default_factory=list)
    #: deck id -> card ids dealt (with multiplicity across passes).
    dealt: dict[str, list[str]] = field(default_factory=dict)
    #: deck id -> {card id: rejection reason} from the LAST deal of that deck.
    rejected: dict[str, dict[str, str]] = field(default_factory=dict)
    forced_raised: list[str] = field(default_factory=list)
    forced_pending_end: list[str] = field(default_factory=list)
    threads_sealed: int = 0
    threads_discharged: int = 0
    threads_broken: int = 0
    threads_transformed: int = 0
    threads_active_end: int = 0
    #: value name -> (min, max, final) observed across the run.
    meters: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# the walk
# ---------------------------------------------------------------------------


class DeckWalk:
    """One seeded walk of the active story's decks."""

    def __init__(self, seed: int, *, thread_rate: float, max_days: int) -> None:
        self.seed = seed
        self.thread_rate = thread_rate
        self.max_days = max_days
        self.state = GameState(rng_seed=seed)
        self._place_at_entry()
        self.ledger = StoryLedger()
        self.rng = stable_rng(seed, POLICY_STREAM)
        self.result = DeckRunResult(seed=seed)
        #: beat id -> clock, from the loaded table. Only these count as clock
        #: fires -- ``advance_when`` rules share the flag prefix and must not.
        self.beat_owner: dict[str, str] = {
            str(beat.get("id") or ""): str(clock)
            for clock, spec in clocks_module.load_clocks().items()
            if isinstance(spec, dict)
            for beat in spec.get("beats") or []
            if isinstance(beat, dict) and beat.get("id")
        }
        self._fired: set[str] = set()
        self._forced_plays = 0
        self._value_names = sorted(active_schema().values)

    def _place_at_entry(self) -> None:
        """Start where the manifest says a run starts. Best-effort: a walk
        that cannot learn the entry location walks from nowhere, which no
        deck condition in either shipped deck story reads anyway."""
        try:
            from engine.games.registry import peek

            manifest = peek()
            if manifest is not None and manifest.entry_location:
                self.state.location_id = manifest.entry_location
        except Exception:  # noqa: BLE001 -- location is cosmetic to a deck walk
            pass

    # -- observation -----------------------------------------------------

    def _sweep_meters(self) -> None:
        store = store_for(self.state)
        for name in self._value_names:
            current = float(store.get(name))
            low, high, _ = self.result.meters.get(name, (current, current, current))
            self.result.meters[name] = (min(low, current), max(high, current), current)

    def _record_clock_fires(self) -> None:
        """Diff the fired-beat flags against what we have already seen."""
        for beat_id, clock in self.beat_owner.items():
            if beat_id in self._fired:
                continue
            if clocks_module.has_fired(self.state, beat_id):
                self._fired.add(beat_id)
                self.result.clock_fires.append((clock, beat_id, self.result.steps))

    # -- choice points ---------------------------------------------------

    def _resolve_card(self, card: deck_module.Card) -> None:
        """One card, with the walker choosing where the content asks."""
        chosen: Optional[str] = None
        if deck_module.MENU_TAG in card.tags and card.beats:
            chosen = str(self.rng.choice([str(b.get("id")) for b in card.beats]))
        qualities = {
            str(beat.get("id")): self.rng.random()
            for beat in card.beats
            if isinstance(beat.get("band"), dict)
        }
        deck_module.resolve_card(
            self.state, card, chosen=chosen, qualities=qualities, ledger=self.ledger
        )

    def _swear_intent(self) -> None:
        """The Day-8 move: mark an eligible ending, seeded-random. In real
        play the mirror pool does this through the same ``set_intent`` door."""
        if endings_module.intent(self.state) != endings_module.NONE_ID:
            return
        report = endings_module.recompute(self.state, ledger=self.ledger)
        self.result.eligible_at_finale = sorted(report.eligible)
        if not report.eligible:
            return
        pick = str(self.rng.choice(sorted(report.eligible)))
        receipt = endings_module.set_intent(self.state, pick, ledger=self.ledger)
        if receipt.get("ok", True):
            self.result.intent_sworn = pick

    def _thread_policy(self) -> None:
        """Seed a bargain the way an agent would, sometimes renegotiated."""
        templates = sorted(threads_module.templates())
        if not templates or self.rng.random() >= self.thread_rate:
            return
        proposal = threads_module.offer(self.state, str(self.rng.choice(templates)))
        if proposal is None:
            return
        if proposal.variants and self.rng.random() < 0.5:
            variant = str(self.rng.choice(sorted(proposal.variants)))
            proposal = (
                threads_module.renegotiate(
                    self.state, proposal, variant, ledger=self.ledger
                )
                or proposal
            )
        threads_module.seal(self.state, proposal, ledger=self.ledger)

    def _thread_day_end(self) -> None:
        """Pay some debts, break a few, let the rest ride to their due day."""
        for thread in list(threads_module.active(self.state)):
            roll = self.rng.random()
            if roll < DISCHARGE_CHANCE:
                threads_module.discharge(
                    self.state, str(thread["id"]), ledger=self.ledger
                )
            elif roll < DISCHARGE_CHANCE + BREAK_CHANCE:
                threads_module.break_thread(
                    self.state, str(thread["id"]), ledger=self.ledger
                )

    # -- decks -----------------------------------------------------------

    def _play_deck(self, deck_id: str) -> None:
        hand = deck_module.draw(self.state, deck_id, ledger=self.ledger)
        self.result.dealt.setdefault(deck_id, []).extend(c.id for c in hand.cards)
        self.result.rejected[deck_id] = dict(hand.rejected)
        for card in hand.cards:
            try:
                self._resolve_card(card)
            except Exception as exc:  # noqa: BLE001 -- a harness survives to report
                self.result.errors.append(f"{deck_id}/{card.id}: {exc}")
            self.result.steps += 1
            try:
                clocks_module.resolve(self.state, ledger=self.ledger)
            except Exception as exc:  # noqa: BLE001
                self.result.errors.append(f"{deck_id}/clocks: {exc}")
            self._record_clock_fires()
            self._sweep_meters()
        self._play_forced_decks()

    def _play_forced_decks(self) -> None:
        """
        Answer what a filled clock owes, the way the live engine now does.

        A ``forces_scene`` may name a DECK (play it) or a single CARD inside one
        (that card's own gate answers it when its deck comes round). Both are
        legal and both ship; ``engine/content/director.py`` is the production
        resolver and this walk must not disagree with it.

        The card case used to be skipped AND left raised forever, so the walk
        reported 100% of the Garden's forced scenes pending at end -- which read
        as a broken promise when what was actually broken was this accounting.
        A card-shaped forced scene is retired here once its deck has dealt the
        card, which is the same moment the director retires it.

        Bounded either way: a scene that refills its own clock must not loop.
        """
        known_decks = set(deck_module.deck_ids())
        for scene_id in clocks_module.forced_scenes(self.state):
            if scene_id not in self.result.forced_raised:
                self.result.forced_raised.append(scene_id)
            if scene_id not in known_decks:
                # A card id. Retire it once the card has actually been dealt --
                # `dealt` is this walk's record of every card it played.
                played = any(
                    scene_id in cards for cards in self.result.dealt.values()
                )
                if played:
                    clocks_module.mark_scene_played(self.state, scene_id)
                continue
            if self._forced_plays >= MAX_FORCED_PLAYS:
                continue
            self._forced_plays += 1
            clocks_module.mark_scene_played(self.state, scene_id)
            hand = deck_module.draw(self.state, scene_id, ledger=self.ledger)
            self.result.dealt.setdefault(scene_id, []).extend(
                c.id for c in hand.cards
            )
            for card in hand.cards:
                try:
                    self._resolve_card(card)
                except Exception as exc:  # noqa: BLE001
                    self.result.errors.append(f"forced {scene_id}/{card.id}: {exc}")
                self.result.steps += 1
            self._record_clock_fires()
            self._sweep_meters()

    # -- the run ---------------------------------------------------------

    def _locked(self) -> bool:
        return endings_module.locked(self.state) != endings_module.NONE_ID

    def run(self) -> DeckRunResult:
        lock_decks = _decks_carrying_ending_lock(deck_module.deck_ids())
        # Lock-carrying decks go LAST in the pass, whatever their filenames
        # sort to: the lock ends the run, so anything sorted after the finale
        # (the Garden's ``thorn_labyrinth`` chamber deck) would never be
        # walked at all and every one of its cards would read as an orphan.
        order = [d for d in deck_module.deck_ids() if d not in lock_decks] + [
            d for d in deck_module.deck_ids() if d in lock_decks
        ]
        has_endings = bool(endings_module.declared())

        # Loop the chapter list until an ending locks or the day budget runs
        # out. A ten-day story locks on its own finale card in one pass; a
        # one-deck template is walked repeatedly, which is what lets its
        # meters actually travel far enough to open its gated ending.
        while order and not self._locked() and self.state.world_day <= self.max_days:
            self.result.passes += 1
            for deck_id in order:
                if has_endings and deck_id in lock_decks:
                    # The night before the finale: swear, so the story's own
                    # ``ending_lock`` card has an intent to honour.
                    self._swear_intent()
                self._play_deck(deck_id)
                self._thread_policy()
                advance_time(self.state, CHAPTER_HOURS)
                threads_module.expire_due(self.state, ledger=self.ledger)
                self._thread_day_end()
                self._record_clock_fires()
                if self._locked() or self.state.world_day > self.max_days:
                    break

        # The finale chain, for a story whose decks never lock (the walker's
        # explicit fallback) -- through the same entry points the scene uses.
        if has_endings:
            if not self._locked():
                self._swear_intent()
                report = endings_module.recompute(self.state, ledger=self.ledger)
                self.result.eligible_at_finale = sorted(report.eligible)
                if report.eligible:
                    pick = str(self.rng.choice(sorted(report.eligible)))
                    endings_module.lock(self.state, pick, ledger=self.ledger)
            elif not self.result.eligible_at_finale:
                # Locked by a card before any swear captured the set; record
                # the post-hoc answer so the report is never empty here.
                self.result.eligible_at_finale = sorted(
                    endings_module.eligible(self.state, ledger=self.ledger).eligible
                )
            if (
                self._locked()
                and endings_module.module_ran(self.state) == endings_module.NONE_ID
            ):
                endings_module.run_module(self.state, ledger=self.ledger)

            locked_id = endings_module.locked(self.state)
            if locked_id != endings_module.NONE_ID:
                self.result.ending_locked = locked_id
                body = endings_module.declared().get(locked_id) or {}
                self.result.ending_class = str(body.get("class") or locked_id)
                self.result.ending_forced = (
                    self.result.eligible_at_finale == [endings_module.fail_forward_id()]
                )
                self.result.epilogue_rendered = (
                    epilogue_module.for_state(self.state) is not None
                )

        # Final accounting.
        self.result.days = self.state.world_day
        statuses = Counter(str(t.get("status")) for t in self.state.threads)
        self.result.threads_sealed = len(self.state.threads)
        self.result.threads_discharged = statuses[threads_module.STATUS_DISCHARGED]
        self.result.threads_broken = statuses[threads_module.STATUS_BROKEN]
        self.result.threads_transformed = statuses[threads_module.STATUS_TRANSFORMED]
        self.result.threads_active_end = statuses[threads_module.STATUS_ACTIVE]
        self.result.forced_pending_end = clocks_module.forced_scenes(self.state)
        self._sweep_meters()
        return self.result


def _decks_carrying_ending_lock(order: list[str]) -> set[str]:
    """Deck ids whose cards carry an ``ending_lock`` effect -- the finale."""
    found: set[str] = set()
    for deck_id in order:
        deck = deck_module.load_deck(deck_id)
        if deck is None:
            continue
        for card in deck.cards:
            for beat in card.beats:
                gate = beat.get("gate") or {}
                for branch in ("on_pass", "on_fail"):
                    for effect in (gate.get(branch) or {}).get("effects") or []:
                        if str(effect.get("type")) == "ending_lock":
                            found.add(deck_id)
    return found


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def _distribution(values: list[float]) -> dict[str, float]:
    """Five-number-ish summary, matching scripts/simulate.py's shape."""
    if not values:
        return {"min": 0.0, "p10": 0.0, "median": 0.0, "mean": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 2),
        "p10": round(ordered[max(0, int(len(ordered) * 0.10) - 1)], 2),
        "median": round(statistics.median(ordered), 2),
        "mean": round(statistics.fmean(ordered), 2),
        "max": round(ordered[-1], 2),
    }


def summarize(results: list[DeckRunResult], config: dict[str, Any]) -> dict[str, Any]:
    """Fold the runs into one JSON-serializable report."""
    runs = max(1, len(results))
    declared = endings_module.declared()
    fail_forward = endings_module.fail_forward_id()
    epilogue_rows = set(epilogue_module.declared())

    locked = Counter(r.ending_locked for r in results if r.ending_locked)
    classes = Counter(r.ending_class for r in results if r.ending_class)
    reachable = sorted(
        set(locked) | {e for r in results for e in r.eligible_at_finale}
    )
    unreachable = sorted(set(declared) - set(reachable))

    # Clock beats: fire counts and when.
    clock_report: dict[str, dict[str, Any]] = {}
    for clock, spec in sorted(clocks_module.load_clocks().items()):
        beats: dict[str, dict[str, Any]] = {}
        for raw in (spec.get("beats") or []) if isinstance(spec, dict) else []:
            beat_id = str(raw.get("id") or "")
            if not beat_id:
                continue
            steps = [
                float(step)
                for r in results
                for c, b, step in r.clock_fires
                if b == beat_id
            ]
            beats[beat_id] = {
                "runs_fired": len(steps),
                "fire_rate": round(len(steps) / runs, 3),
                "step": _distribution(steps),
            }
        clock_report[str(clock)] = {"beats": beats}

    # Cards: dealt counts per deck, and the ones no run ever saw.
    cards_report: dict[str, dict[str, Any]] = {}
    orphans: list[str] = []
    for deck_id in deck_module.deck_ids():
        deck = deck_module.load_deck(deck_id)
        if deck is None:
            continue
        dealt = Counter(
            card_id for r in results for card_id in r.dealt.get(deck_id, [])
        )
        never = sorted(c.id for c in deck.cards if c.id not in dealt)
        orphans.extend(f"{deck_id}:{card_id}" for card_id in never)
        cards_report[deck_id] = {
            "cards": len(deck.cards),
            "dealt": dict(sorted(dealt.items())),
            "never_dealt": never,
        }

    meters_report: dict[str, dict[str, float]] = {}
    for name in sorted({n for r in results for n in r.meters}):
        rows = [r.meters[name] for r in results if name in r.meters]
        meters_report[name] = {
            "min": round(min(low for low, _, _ in rows), 2),
            "max": round(max(high for _, high, _ in rows), 2),
            "end_mean": round(statistics.fmean(end for _, _, end in rows), 2),
        }

    forced_raised = Counter(s for r in results for s in set(r.forced_raised))
    forced_pending = Counter(s for r in results for s in set(r.forced_pending_end))

    errors = [e for r in results for e in r.errors]

    missing_epilogues = sorted(set(declared) - epilogue_rows)
    orphan_epilogues = sorted(epilogue_rows - set(declared))
    locked_without_card = sorted(
        {r.ending_locked for r in results if r.ending_locked and not r.epilogue_rendered}
    )

    return {
        "config": {
            **config,
            "decks": deck_module.deck_ids(),
            "declared_endings": len(declared),
            "declared_epilogues": len(epilogue_rows),
            "fail_forward": fail_forward,
        },
        "days": _distribution([float(r.days) for r in results]),
        "steps": _distribution([float(r.steps) for r in results]),
        "passes": _distribution([float(r.passes) for r in results]),
        "endings": {
            "locked": dict(sorted(locked.items())),
            "classes": dict(sorted(classes.items())),
            "fail_forward_runs": locked.get(fail_forward, 0),
            "forced_runs": sum(1 for r in results if r.ending_forced),
            "intent_sworn_runs": sum(1 for r in results if r.intent_sworn),
            "eligible_size": _distribution(
                [float(len(r.eligible_at_finale)) for r in results]
            ),
            "reachable": reachable,
            "unreachable": unreachable,
        },
        "epilogues": {
            "rendered_runs": sum(1 for r in results if r.epilogue_rendered),
            "locked_without_epilogue": locked_without_card,
            "endings_without_row": missing_epilogues,
            "rows_without_ending": orphan_epilogues,
        },
        "clocks": clock_report,
        "threads": {
            "sealed": _distribution([float(r.threads_sealed) for r in results]),
            "discharged": sum(r.threads_discharged for r in results),
            "broken": sum(r.threads_broken for r in results),
            "transformed": sum(r.threads_transformed for r in results),
            "active_at_end": sum(r.threads_active_end for r in results),
        },
        "cards": cards_report,
        "orphans": sorted(orphans),
        "forced_scenes": {
            "raised": dict(sorted(forced_raised.items())),
            "pending_at_end": dict(sorted(forced_pending.items())),
        },
        "meters": meters_report,
        "errors": errors[:20],
        "error_count": len(errors),
        "acceptance": _acceptance(
            runs, declared, reachable, unreachable, orphans, clock_report,
            missing_epilogues, locked_without_card,
        ),
    }


def _acceptance(
    runs: int,
    declared: dict[str, Any],
    reachable: list[str],
    unreachable: list[str],
    orphans: list[str],
    clock_report: dict[str, dict[str, Any]],
    missing_epilogues: list[str],
    locked_without_card: list[str],
) -> dict[str, Any]:
    """The authoring acceptance metric, as data the renderer prints last."""
    clock_rates = {
        clock: max(
            (row["fire_rate"] for row in body["beats"].values()), default=0.0
        )
        for clock, body in clock_report.items()
    }
    return {
        "endings_reachable": f"{len(reachable)}/{len(declared)}",
        "endings_unreachable": unreachable,
        "orphan_cards": len(orphans),
        "clock_fire_rates": clock_rates,
        "epilogue_gaps": sorted(set(missing_epilogues) | set(locked_without_card)),
    }


def _render(report: dict[str, Any]) -> str:
    """Human-readable rendering, in scripts/simulate.py's voice."""
    cfg = report["config"]
    endings = report["endings"]
    acceptance = report["acceptance"]
    lines = [
        "=" * 68,
        f"game={cfg['game']}  runs={cfg['runs']}  seed={cfg['seed']}  "
        f"max_days={cfg['max_days']}  thread_rate={cfg['thread_rate']}",
        "=" * 68,
        f"decks                {cfg['decks']}",
        f"days                 {report['days']}",
        f"cards resolved       {report['steps']}  (passes {report['passes']})",
        f"endings locked       {endings['locked']}",
        f"  by class           {endings['classes']}",
        f"  fail-forward runs  {endings['fail_forward_runs']}  "
        f"forced {endings['forced_runs']}  intent sworn {endings['intent_sworn_runs']}",
        f"  eligible at finale {endings['eligible_size']}",
        f"epilogues            rendered in {report['epilogues']['rendered_runs']} runs; "
        f"locked without card {report['epilogues']['locked_without_epilogue']}",
        f"threads              sealed {report['threads']['sealed']}  "
        f"discharged {report['threads']['discharged']}  "
        f"broken {report['threads']['broken']}  "
        f"transformed {report['threads']['transformed']}  "
        f"live at end {report['threads']['active_at_end']}",
        "",
        "clock                beat                            fired  rate",
    ]
    for clock, body in report["clocks"].items():
        for beat_id, row in body["beats"].items():
            lines.append(
                f"  {clock:<18} {beat_id:<30} {row['runs_fired']:>5}  "
                f"{row['fire_rate']:>5}"
            )
        if not body["beats"]:
            lines.append(f"  {clock:<18} (no threshold beats)")
    lines += ["", "deck                 cards  never dealt"]
    for deck_id, row in report["cards"].items():
        lines.append(
            f"  {deck_id:<18} {row['cards']:>5}  {row['never_dealt'] or '-'}"
        )
    lines += ["", "meters (min..max, mean at end):"]
    for name, row in report["meters"].items():
        lines.append(
            f"  {name:<24} {row['min']:>8} .. {row['max']:<8} end {row['end_mean']}"
        )
    if report["forced_scenes"]["raised"]:
        lines += [
            "",
            f"forced scenes raised {report['forced_scenes']['raised']}",
            f"  pending at end     {report['forced_scenes']['pending_at_end']}",
        ]
    if report["errors"]:
        lines += ["", f"errors ({report['error_count']}):"] + [
            f"  {e}" for e in report["errors"]
        ]
    lines += [
        "",
        "-" * 68,
        "acceptance:",
        f"  endings reachable  {acceptance['endings_reachable']}"
        + (
            f"  (never: {', '.join(acceptance['endings_unreachable'])})"
            if acceptance["endings_unreachable"]
            else ""
        ),
        f"  orphan cards       {acceptance['orphan_cards']}"
        + (f"  ({', '.join(report['orphans'])})" if report["orphans"] else ""),
        "  clock fire rates   "
        + ", ".join(f"{c}={r}" for c, r in acceptance["clock_fire_rates"].items()),
        f"  epilogue gaps      {acceptance['epilogue_gaps'] or 'none'}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def simulate_deck_story(
    *,
    slug: str = "",
    runs: int = 200,
    seed: int = 42,
    max_days: int = 30,
    thread_rate: float = 0.35,
) -> dict[str, Any]:
    """
    Walk the active (or named) deck story ``runs`` times and report.

    Args:
        slug: Story to activate first. Empty means "whatever is active", which
            is the seam the tests use to walk a scaffolded story.
        runs: Number of seeded runs.
        seed: Base seed; run ``i`` plays on ``seed + i``. The engine's own
            per-state streams decorrelate consecutive seeds.
        max_days: Day budget per run, for stories whose decks never lock.
        thread_rate: Per-chapter chance the policy seals a declared bargain.

    Returns:
        Report dict, as produced by :func:`summarize`.
    """
    if slug:
        from engine.games.registry import activate

        activate(slug)

    results = [
        DeckWalk(seed + index, thread_rate=thread_rate, max_days=max_days).run()
        for index in range(max(1, runs))
    ]
    active = ""
    try:
        from engine.games.registry import active_slug

        active = active_slug()
    except Exception:  # noqa: BLE001 -- the report survives an anonymous story
        pass
    return summarize(
        results,
        {
            "game": slug or active,
            "runs": len(results),
            "seed": seed,
            "max_days": max_days,
            "thread_rate": thread_rate,
        },
    )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. ``scripts/simulate.py --game <slug>`` lands here too."""
    parser = argparse.ArgumentParser(
        description="Headless walker for deck-shaped stories."
    )
    parser.add_argument("--game", default="", help="Story slug to activate and walk.")
    parser.add_argument("--runs", type=int, default=200, help="Seeded runs to walk.")
    parser.add_argument("--seed", type=int, default=42, help="Base seed.")
    parser.add_argument(
        "--max-days",
        type=int,
        default=30,
        help="Day budget per run, for decks that never lock an ending.",
    )
    parser.add_argument(
        "--thread-rate",
        type=float,
        default=0.35,
        help="Per-chapter chance the policy seals a declared bargain.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON, not prose.")
    args = parser.parse_args(argv)

    report = simulate_deck_story(
        slug=args.game,
        runs=args.runs,
        seed=args.seed,
        max_days=args.max_days,
        thread_rate=args.thread_rate,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

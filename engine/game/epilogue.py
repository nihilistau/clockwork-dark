"""
Epilogues — the last words a run gets
=====================================

``engine/game/endings.py`` answers *how can this end*. This answers *what does
the player read when it does*.

Two files, declared together under ``paths.epilogues``:

    epilogue_index.yaml    ids, titles, gallery keys, echo speakers, NG+ seeds,
                           and the render contract (order, time line, clauses)
    epilogue_cards.yaml    the prose

Split because they change for different reasons. The index is structure a UI and
a gallery read; the cards are finished writing. The index names its prose file in
``prose_source`` rather than this module assuming a filename, so a story can ship
one file, two, or a prose file per class.

THE PROSE IS NOT IMPROVISED. Everything else in The Wicked Garden is authored
bone that agents fill; these are transcribed cards meant to be read exactly as
written. So this module renders and substitutes -- it does not summarise, and it
never hands an epilogue card to a model as source material.

THE TIME LINE IS COMPUTED FROM STATE, NOT FROM THE ENDING. The number of mortal
days lost is the story's thesis, and it has to be true even when it is
embarrassing: a run that lost the labyrinth and burned an hour on the wrong door
owes more than ``days * 10``. So ``mortal_days`` reads the declared
``time_debt_mortal_days`` value, which the toll maintains, rather than
recomputing it from the day index and under-reporting a bad run.

A story that declares no ``paths.epilogues`` gets an empty table and
:func:`render` returns ``None``. The Clockwork Dark ships no epilogues and this
module is inert for it -- same contract as clocks, threads and decks.

Version: v0.1.0 [2026-08-09]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

#: The index file inside ``paths.epilogues``. Fixed rather than configurable
#: because the index is the entry point -- something has to be findable without
#: already having been read, and one well-known name beats a second config key.
INDEX_FILE = "epilogue_index.yaml"

#: What the index renders, if it declares no order of its own.
DEFAULT_ORDER = ["title", "card_m", "card_g", "echoes", "time_line", "gallery_unlock"]

#: The declared value carrying mortal days owed. Named here rather than derived
#: so a story that spells it differently fails loudly at render rather than
#: quietly reporting a debt of zero.
TIME_DEBT_VALUE = "time_debt_mortal_days"


@dataclass
class Epilogue:
    """One rendered ending, ready for a renderer that knows no story nouns."""

    ending_id: str
    title: str = ""
    #: The waking world.
    card_m: str = ""
    #: The Garden, after.
    card_g: str = ""
    #: ``[{speaker, text}]``, in authored order.
    echoes: list[dict[str, str]] = field(default_factory=list)
    #: One substituted sentence. Always present, always last before the gallery.
    time_line: str = ""
    #: The art key this ending unlocks. NOT the ending id -- see the index.
    gallery_key: str = ""
    #: Carried into a New Game+ seed, or "" for endings that seed nothing.
    ng_plus_seed: str = ""
    #: Keys, in the order a renderer should lay them out.
    order: list[str] = field(default_factory=lambda: list(DEFAULT_ORDER))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ending_id": self.ending_id,
            "title": self.title,
            "card_m": self.card_m,
            "card_g": self.card_g,
            "echoes": [dict(e) for e in self.echoes],
            "time_line": self.time_line,
            "gallery_key": self.gallery_key,
            "ng_plus_seed": self.ng_plus_seed,
            "order": list(self.order),
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _root() -> Optional[Path]:
    from engine.config import get_config

    rel = get_config().get("paths.epilogues", "")
    return _ROOT / str(rel) if rel else None


@lru_cache(maxsize=8)
def _read(path_str: str, _mtime: float) -> dict[str, Any]:
    """Parse one YAML file, memoized on (path, mtime). See engine/game/endings.py."""
    try:
        with Path(path_str).open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error("[epilogue] Unreadable epilogue file: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def _read_if_present(path: Optional[Path]) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    return _read(str(path), mtime)


def load_index() -> dict[str, Any]:
    """
    The whole index document: render contract plus the ending rows.

    Empty for a story that declares no ``paths.epilogues``, which is not an
    error -- it is a story whose endings are the last thing the player sees.
    """
    root = _root()
    return _read_if_present(root / INDEX_FILE if root else None)


def load_cards() -> dict[str, Any]:
    """id -> prose card, from whatever file the index names in ``prose_source``."""
    root = _root()
    if root is None:
        return {}
    source = str(load_index().get("prose_source") or "").strip()
    if not source:
        return {}
    return _read_if_present(root / source).get("cards") or {}


def declared() -> dict[str, dict[str, Any]]:
    """
    id -> index row merged with its prose.

    One mapping rather than two, because every caller wants both and joining
    them at each call site is how a renderer ends up with a title from one file
    and prose from a stale copy of the other.
    """
    cards = load_cards()
    out: dict[str, dict[str, Any]] = {}
    for row in load_index().get("endings") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        ending_id = str(row["id"])
        prose = cards.get(ending_id) or {}
        out[ending_id] = {**row, **(prose if isinstance(prose, dict) else {})}
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _value(state: GameState, name: str) -> float:
    """One declared value, or 0.0 where the story does not declare it."""
    from engine.state.active import store_for

    try:
        return float(store_for(state).get(name))
    except Exception:  # noqa: BLE001 -- an absent value is zero, not a crash
        return 0.0


def time_line(state: GameState, index: Optional[dict[str, Any]] = None) -> str:
    """
    The sentence naming what the run cost, substituted from state.

    Always rendered, including for the endings that look like wins. The design's
    instruction is explicit -- "do not undervalue TimeDebt in good endings; cost
    is the thesis" -- so this is not conditional on the ending class.
    """
    doc = index if index is not None else load_index()
    template = str(doc.get("time_line_template") or "").strip()
    if not template:
        return ""
    garden_days = int(state.world_day)
    mortal_days = int(_value(state, TIME_DEBT_VALUE))
    return template.format(
        garden_days=garden_days,
        mortal_days=mortal_days,
        # So a template can read "{garden_days} {garden_days_word}" rather than
        # "1 days". English pluralisation belongs to whoever wrote the sentence,
        # not to this module -- the client used to do it, and it stopped being
        # able to when the sentence became server-rendered.
        garden_days_word="day" if garden_days == 1 else "days",
        mortal_days_word="day" if mortal_days == 1 else "days",
    )


def _echoes(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for echo in raw or []:
        if isinstance(echo, dict) and echo.get("text"):
            out.append(
                {"speaker": str(echo.get("speaker") or ""), "text": str(echo["text"]).strip()}
            )
    return out


def render(state: GameState, ending_id: str) -> Optional[Epilogue]:
    """
    The epilogue for one ending, fully substituted.

    Returns None for an id this story declares no epilogue for, so a caller can
    tell "no epilogue authored" from "an empty one", and a story with no
    epilogues at all falls through without special-casing.
    """
    row = declared().get(str(ending_id))
    if not row:
        return None

    index = load_index()
    card_m = str(row.get("card_m") or "").strip()

    # The hollow clause. A door that opens onto a decade is not a victory, and
    # the epilogue is not allowed to imply otherwise -- so past the declared
    # threshold this is appended to the MORTAL card, whichever ending it is.
    threshold = index.get("hollow_clause_if_time_debt_gte")
    clause = str(index.get("hollow_clause_text") or "").strip()
    if card_m and clause and threshold is not None:
        try:
            over = _value(state, TIME_DEBT_VALUE) >= float(threshold)
        except (TypeError, ValueError):
            logger.warning("[epilogue] Non-numeric hollow clause threshold: %r", threshold)
            over = False
        if over:
            card_m = f"{card_m}\n\n{clause}"

    order = [str(k) for k in (index.get("render_order") or DEFAULT_ORDER)]
    return Epilogue(
        ending_id=str(ending_id),
        title=str(row.get("title") or ending_id),
        card_m=card_m,
        card_g=str(row.get("card_g") or "").strip(),
        echoes=_echoes(row.get("echoes")),
        time_line=time_line(state, index),
        gallery_key=str(row.get("gallery_key") or ""),
        ng_plus_seed=str(row.get("ng_plus_seed") or ""),
        order=order,
    )


def for_state(state: GameState) -> Optional[Epilogue]:
    """
    The epilogue this run has earned, or None while it is still running.

    THE TRIGGER IS ``lock``, NOT ``resolve``. ``endings.resolve()`` always
    answers -- it falls forward rather than softlock a finale -- so a turn loop
    asking it "is there an ending yet?" would be told yes on turn one and show
    the player their epilogue before they had left the threshold. Locking is the
    declared point of no return: it is refused on a non-eligible id and refused
    a second time on an already-locked save, and it is the only thing in the
    story that cannot be walked back.

    AND THE MODULE HAS TO HAVE PLAYED. An ending that declares Speak/Act/Seal
    beats has not happened yet at the moment it is locked -- the lock is the
    decision, the module is the scene. Returning the cards on the locking turn
    would swap the play screen out from under the last three beats of the story
    and skip them, which is what a run did before ``run_module`` existed.
    An ending that declares no beats is over as soon as it is locked, and the
    module marks itself run in that case too, so "nothing to play" and "not
    played yet" stay distinguishable.

    A story with no declared endings never locks one, so this is None for The
    Clockwork Dark on every turn of every run -- and its terminal death, which
    sets ``state.ended``, stays what it was. Death is not an epilogue here; a
    story wanting one declares an ending and locks it.
    """
    from engine.game import endings as endings_module

    ending_id = endings_module.locked(state)
    if not ending_id or ending_id == endings_module.NONE_ID:
        return None
    if endings_module.module_ran(state) != ending_id:
        return None
    rendered = render(state, ending_id)
    if rendered is None:
        # Locked to a real ending with no card authored for it. Loud, because
        # the finale has already committed and the player is about to reach the
        # end of the story and be shown nothing.
        logger.error(
            "[epilogue] Locked ending has no epilogue (operation=for_state, ending=%s)",
            ending_id,
        )
    return rendered


__all__ = [
    "DEFAULT_ORDER",
    "INDEX_FILE",
    "TIME_DEBT_VALUE",
    "Epilogue",
    "declared",
    "for_state",
    "load_cards",
    "load_index",
    "render",
    "time_line",
]

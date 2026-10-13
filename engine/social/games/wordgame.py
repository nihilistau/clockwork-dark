"""
Tile Talk (v0.22.0 spec §21.1): a two-player word game on an 11x11 board,
played on the phone against a match or a contact, each side on its own clock.

The ENGINE decides everything here (rule 1): where tiles may go, which words
they form, whether each is a word (the story's `words.txt`, ENABLE), what
they score, and the person's own move -- found by anchor-based generation
over the word list's prefix set, bounded by a NODE budget (`games.yaml`
`wordgame.node_budget`, never a wall clock), sorted canonically and picked
from the top `k` for the person's skill on `SOCIAL_GAME`. No model sees a
rack, a bag or a score it could change.

A game row (`state.social["games"][game_id]`, the `wordgame` part):

    board    [size strings of size chars]: "." empty, a-z a tile, A-Z a blank
             played as that letter
    bag      the undrawn tiles in draw order ("?" a blank), shuffled once from
             stable_rng(seed, f"{SOCIAL_GAME}:{game_id}")
    racks    {"player": str, "them": str}
    scores   {"player": int, "them": int}
    turn     "player" | "them"
    scoreless  passes and swaps in a row

`bag` and `racks` never leave the server (the payload shows the player's
own rack and the bag's COUNT; tests/test_ui_contract.py scans for both).

This module is pure but for `apply_move`, which mutates a row and is called
only inside the `social_game` effect's handler (engine/social/games/__init__.py,
rule 3), and `their_move`, which draws on a person's stream inside the
`game_move` event's handler.

The word list is a module cache: `words()` and `prefixes()` are frozensets,
loaded once together under `_WORDS_LOCK` (a LEAF: the story's directory is
read from config before it is taken) and nulled by
`engine.games.caches.reset_content_caches` (NULLED_ATTRIBUTES), warmed by
`caches._warm_words` for a story declaring `paths.social`.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from engine import social
from engine.game.rng import SOCIAL_GAME, stable_rng
from engine.locks import renew_after_fork

logger = logging.getLogger(__name__)

#: The game's id in apps.yaml's `games.offers` and games.yaml.
GAME = "wordgame"
#: No reveal: a move of theirs may bring banter on a `banter_prob` draw (engine/social/games `_on_game_move`).
REVEALS = False
#: The word list's fixed file name, beside games.yaml (spec §2.1's fixed names).
WORDS_FILE = "words.txt"
#: A blank in a rack or the bag.
BLANK = "?"
EMPTY = "."
#: A premium square's code -> (letter multiplier, word multiplier).
PREMIUMS: dict[str, tuple[int, int]] = {
    ".": (1, 1), "*": (1, 1), "l": (2, 1), "L": (3, 1), "w": (1, 2), "W": (1, 3),
}
#: The sides of a game.
SIDES: tuple[str, str] = ("player", "them")
ALPHABET = "abcdefghijklmnopqrstuvwxyz"

# -- the engine's refusals (rule 1: each reaches the player) ---------------------------------
NOT_A_MOVE = "That isn't a move."
OFF_THE_BOARD = "That's off the board."
SQUARE_TAKEN = "That square is taken."
ONE_LINE = "Tiles must be in one unbroken line."
CROSS_THE_CENTRE = "The first word must cross the centre."
JOIN_THE_BOARD = "Your word must join the tiles already on the board."
TWO_LETTERS = "A word needs at least two letters."
NO_BLANK = "You don't have a blank."


def _no_letter(letter: str) -> str:
    return f"You don't have a {letter}."


def _not_a_word(word: str) -> str:
    return f"{word} is not a word."


# -- data ---------------------------------------------------------------------------------------


def spec() -> dict[str, Any]:
    """games.yaml's `wordgame:` block (checked whole at load, `data_faults`)."""
    block = social.data("games").get(GAME)
    if not isinstance(block, dict):
        raise ValueError("social: games.yaml: wordgame: required for Tile Talk (spec §21.1)")
    return block


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def data_faults(block: Any, directory: Optional[Path]) -> list[tuple[str, str]]:
    """
    Every fault of games.yaml's `wordgame:` block, as (key, message): the
    premiums `size` x `size`, the bag (`letters` plus `blanks`) holding 72,
    the numbers, and `words.txt` beside it. Read by the loader (the first
    fault a ValueError) and by `validation.check_social`.
    """
    out: list[tuple[str, str]] = []
    if not isinstance(block, dict):
        return [("wordgame", "must be a mapping")]
    size, rack = block.get("size"), block.get("rack")
    if size != 11:
        out.append(("wordgame.size", f"must be 11 (spec §21.1), not {size!r}"))
    if not isinstance(rack, int) or isinstance(rack, bool) or rack != 7:
        out.append(("wordgame.rack", f"must be 7 (spec §21.1), not {rack!r}"))
    premiums = block.get("premiums")
    if (not isinstance(premiums, list) or len(premiums) != 11
            or not all(isinstance(r, str) and len(r) == 11 for r in premiums)):
        out.append(("wordgame.premiums", "must be 11 rows of 11 squares (spec §21.1)"))
    else:
        bad = sorted({c for r in premiums for c in r if c not in PREMIUMS})
        if bad:
            out.append(("wordgame.premiums", f"unknown square codes {bad} (known: {''.join(PREMIUMS)})"))
        if premiums[5][5] != "*":
            out.append(("wordgame.premiums", "the centre square (row 5, column 5) must be `*`"))
    letters = block.get("letters")
    total = 0
    if not isinstance(letters, dict) or not letters:
        out.append(("wordgame.letters", "must map letters a-z to {count, value}"))
    else:
        for letter, row in letters.items():
            if letter not in ALPHABET or len(str(letter)) != 1:
                out.append((f"wordgame.letters.{letter}", "is not a letter a-z"))
                continue
            if not isinstance(row, dict) or not isinstance(row.get("count"), int) or row["count"] < 0 \
                    or not _num(row.get("value")) or row["value"] < 0:
                out.append((f"wordgame.letters.{letter}", "must be {count (whole, 0 or more), value (0 or more)}"))
                continue
            total += int(row["count"])
    blanks = block.get("blanks")
    if not isinstance(blanks, int) or isinstance(blanks, bool) or blanks < 0:
        out.append(("wordgame.blanks", f"must be a whole number, not {blanks!r}"))
    else:
        total += blanks
    if blanks != 2:
        out.append(("wordgame.blanks", f"must be 2 (spec §21.1), not {blanks!r}"))
    if total != 72:
        out.append(("wordgame.letters", f"the bag (letters plus blanks) must hold 72 tiles, not {total}"))
    for key in ("bingo_bonus", "node_budget", "scoreless_turns", "pace_mult", "banter_prob", "swap_bag_min"):
        if not _num(block.get(key)) or block[key] < 0:
            out.append((f"wordgame.{key}", "required: a number, 0 or more"))
    if _num(block.get("banter_prob")) and block["banter_prob"] > 1:
        out.append(("wordgame.banter_prob", "must be 0 to 1"))
    if _num(block.get("node_budget")) and block["node_budget"] < 1:
        out.append(("wordgame.node_budget", "must be at least 1"))
    top = block.get("top_k_by_skill")
    if (not isinstance(top, list) or not top
            or not all(isinstance(r, list) and len(r) == 2 and _num(r[0]) and isinstance(r[1], int)
                       and not isinstance(r[1], bool) and r[1] >= 1 for r in top)):
        out.append(("wordgame.top_k_by_skill", "must be a non-empty list of [skill at least, k (1 or more)]"))
    elif [r[0] for r in top] != sorted(r[0] for r in top) or top[0][0] != 0:
        out.append(("wordgame.top_k_by_skill", "must start at skill 0 and rise row by row"))
    effects = block.get("effects")
    if not isinstance(effects, dict):
        out.append(("wordgame.effects", "required: {finished: {familiarity, interest}, crushing_margin, ...}"))
    else:
        finished = effects.get("finished")
        if not isinstance(finished, dict) or not all(_num(finished.get(k)) for k in ("familiarity", "interest")):
            out.append(("wordgame.effects.finished", "required: {familiarity, interest}"))
        if not _num(effects.get("crushing_margin")):
            out.append(("wordgame.effects.crushing_margin", "required: points"))
        for key, value in effects.items():
            if key.endswith("_crushing_warmth") and not _num(value):
                out.append((f"wordgame.effects.{key}", "must be a number (warmth)"))
            elif key not in ("finished", "crushing_margin") and not key.endswith("_crushing_warmth"):
                out.append((f"wordgame.effects.{key}", "is not a key Tile Talk reads"))
    if directory is not None and not (directory / WORDS_FILE).is_file():
        out.append((WORDS_FILE, f"missing: games.yaml offers {GAME}, which needs its word list"))
    return out


def check_data(block: Any, directory: Optional[Path]) -> None:
    """At load (social._check_loaded): the first fault a ValueError naming file and key."""
    faults = data_faults(block, directory)
    if faults:
        key, message = faults[0]
        source = key if key == WORDS_FILE else "games.yaml"
        raise ValueError(f"social: {source}: {key}: {message}")


def premiums() -> list[str]:
    return [str(r) for r in spec()["premiums"]]


def values() -> dict[str, int]:
    return {str(k): int(v["value"]) for k, v in spec()["letters"].items()}


def size() -> int:
    return int(spec()["size"])


def rack_size() -> int:
    return int(spec()["rack"])


def bingo_bonus() -> int:
    return int(spec()["bingo_bonus"])


def node_budget() -> int:
    return int(spec()["node_budget"])


def label() -> str:
    return str(spec().get("label") or "Tile Talk")


# -- the word list (a module cache) --------------------------------------------------------------

#: The active story's word list. NULLED_ATTRIBUTES rows; each read once into a local.
_WORDS: Optional[frozenset[str]] = None
_PREFIXES: Optional[frozenset[str]] = None
_WORDS_LOCK = threading.Lock()   # a LEAF: its holder reads a file and builds two sets, nothing more


def _words_path() -> Optional[Path]:
    directory = social.social_dir()
    return (directory / WORDS_FILE) if directory is not None else None


def _read(path: Optional[Path]) -> tuple[frozenset[str], frozenset[str]]:
    if path is None or not path.is_file():
        return frozenset(), frozenset()
    found = frozenset(w for w in path.read_text(encoding="ascii").split() if w.isalpha() and w.islower())
    prefixes = frozenset(w[:i] for w in found for i in range(1, len(w) + 1))
    return found, prefixes


def _load() -> tuple[frozenset[str], frozenset[str]]:
    path = _words_path()                       # config read BEFORE the leaf lock is taken
    global _WORDS, _PREFIXES
    with _WORDS_LOCK:
        found = _WORDS                         # each read once into a local (tests/test_cache_reset_race.py)
        prefixes = _PREFIXES
        if found is None or prefixes is None:
            found, prefixes = _read(path)
            _WORDS, _PREFIXES = found, prefixes
        return found, prefixes


def words() -> frozenset[str]:
    """Every word of the active story's `words.txt` (cached; empty for a story with none)."""
    cached = _WORDS
    return cached if cached is not None else _load()[0]


def prefixes() -> frozenset[str]:
    """Every prefix of every word, the whole word included (cached; the move search's pruning)."""
    cached = _PREFIXES
    return cached if cached is not None else _load()[1]


def load_words() -> None:
    """The WARMERS loader: both sets."""
    _load()


# -- a new game --------------------------------------------------------------------------------


def _bag() -> list[str]:
    tiles: list[str] = []
    for letter in sorted(spec()["letters"]):
        tiles += [letter] * int(spec()["letters"][letter]["count"])
    return tiles + [BLANK] * int(spec()["blanks"])


def shuffled_bag(seed: int, game_id: str) -> str:
    """The game's bag, shuffled once from its own stream (spec §21.1): another game id, another order."""
    tiles = _bag()
    stable_rng(int(seed), f"{SOCIAL_GAME}:{game_id}").shuffle(tiles)
    return "".join(tiles)


def new_game(state: Any, game_id: str, pid: str) -> dict[str, Any]:
    """The `wordgame` part of a new row: an empty board, the shuffled bag, two racks of 7 (player first)."""
    bag = shuffled_bag(state.rng_seed, game_id)
    n = rack_size()
    return {
        "board": [EMPTY * size()] * size(),
        "racks": {"player": bag[:n], "them": bag[n:2 * n]},
        "bag": bag[2 * n:],
        "scores": {"player": 0, "them": 0},
        "turn": "player",
        "scoreless": 0,
    }


# -- placing and scoring -----------------------------------------------------------------------


def _tile(raw: Any) -> Optional[tuple[int, int, str, bool]]:
    """(x, y, letter, blank) from a tile dict, or None for a malformed one."""
    if not isinstance(raw, dict):
        return None
    x, y, letter = raw.get("x"), raw.get("y"), raw.get("letter")
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
        return None
    if not isinstance(letter, str) or len(letter) != 1 or letter.lower() not in ALPHABET:
        return None
    blank = raw.get("blank", False)
    if not isinstance(blank, bool):
        return None
    return x, y, letter.lower(), blank


def _cell(board: list[str], x: int, y: int) -> str:
    return board[y][x]


def _filled(board: list[str], x: int, y: int) -> bool:
    n = len(board)
    return 0 <= x < n and 0 <= y < n and board[y][x] != EMPTY


def _board_empty(board: list[str]) -> bool:
    return all(set(row) <= {EMPTY} for row in board)


def _rack_short(rack: str, placed: Iterable[tuple[int, int, str, bool]]) -> str:
    """'' when `rack` holds every tile placed (a blank for each blank); else the refusal."""
    left = list(rack)
    for _x, _y, letter, blank in placed:
        want = BLANK if blank else letter
        if want not in left:
            return NO_BLANK if blank else _no_letter(letter)
        left.remove(want)
    return ""


def _word_at(board: list[str], placed: dict[tuple[int, int], str], x: int, y: int,
             dx: int, dy: int) -> list[tuple[int, int, str, bool]]:
    """The run of tiles through (x, y) along (dx, dy): [(x, y, char, new)], char as on the board."""
    n = len(board)

    def at(px: int, py: int) -> Optional[str]:
        if not (0 <= px < n and 0 <= py < n):
            return None
        if (px, py) in placed:
            return placed[(px, py)]
        c = board[py][px]
        return None if c == EMPTY else c

    sx, sy = x, y
    while at(sx - dx, sy - dy) is not None:
        sx, sy = sx - dx, sy - dy
    run: list[tuple[int, int, str, bool]] = []
    px, py = sx, sy
    while (c := at(px, py)) is not None:
        run.append((px, py, c, (px, py) in placed))
        px, py = px + dx, py + dy
    return run


def _score_run(run: list[tuple[int, int, str, bool]], grid: list[str], value: dict[str, int]) -> int:
    total, mult = 0, 1
    for x, y, c, new in run:
        points = 0 if c.isupper() else value.get(c, 0)     # a blank (upper case) scores 0
        if new:
            letter_mult, word_mult = PREMIUMS.get(grid[y][x], (1, 1))
            points *= letter_mult
            mult *= word_mult
        total += points
    return total * mult


def score_placement(board: list[str], rack: str, tiles: list[Any],
                    words_: frozenset[str]) -> tuple[Optional[int], str, list[str]]:
    """
    (score, "", words formed) for a legal placement from `rack`; (None,
    reason, []) for an illegal one, the reason in the engine's words. The
    one judge of a move: the player's and the person's alike (rule 1).
    """
    parsed = [_tile(t) for t in tiles or ()]
    if not parsed or any(t is None for t in parsed):
        return None, NOT_A_MOVE, []
    placed_rows: list[tuple[int, int, str, bool]] = [t for t in parsed if t is not None]
    n = len(board)
    if any(not (0 <= x < n and 0 <= y < n) for x, y, _c, _b in placed_rows):
        return None, OFF_THE_BOARD, []
    if len({(x, y) for x, y, _c, _b in placed_rows}) != len(placed_rows):
        return None, NOT_A_MOVE, []
    short = _rack_short(rack, placed_rows)
    if short:
        return None, short, []
    if any(_filled(board, x, y) for x, y, _c, _b in placed_rows):
        return None, SQUARE_TAKEN, []
    xs = {x for x, _y, _c, _b in placed_rows}
    ys = {y for _x, y, _c, _b in placed_rows}
    if len(xs) > 1 and len(ys) > 1:
        return None, ONE_LINE, []
    placed = {(x, y): (c.upper() if b else c) for x, y, c, b in placed_rows}
    if len(ys) == 1 and len(xs) > 1:
        y = next(iter(ys))
        if any((x, y) not in placed and not _filled(board, x, y) for x in range(min(xs), max(xs) + 1)):
            return None, ONE_LINE, []
    elif len(xs) == 1 and len(ys) > 1:
        x = next(iter(xs))
        if any((x, y) not in placed and not _filled(board, x, y) for y in range(min(ys), max(ys) + 1)):
            return None, ONE_LINE, []
    centre = n // 2
    if _board_empty(board):
        if (centre, centre) not in placed:
            return None, CROSS_THE_CENTRE, []
    else:
        touching = any(_filled(board, x + dx, y + dy) for x, y in placed
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if not touching:
            return None, JOIN_THE_BOARD, []
    # The main word along the line (a lone tile: across first, then down), then every cross word.
    first = placed_rows[0]
    runs: list[list[tuple[int, int, str, bool]]] = []
    if len(placed_rows) > 1:
        main_dx, main_dy = (1, 0) if len(ys) == 1 else (0, 1)
        runs.append(_word_at(board, placed, first[0], first[1], main_dx, main_dy))
        cross = (0, 1) if main_dx else (1, 0)
        for x, y, _c, _b in sorted(placed_rows, key=lambda t: (t[1], t[0])):
            run = _word_at(board, placed, x, y, *cross)
            if len(run) > 1:
                runs.append(run)
    else:
        for dx, dy in ((1, 0), (0, 1)):
            run = _word_at(board, placed, first[0], first[1], dx, dy)
            if len(run) > 1:
                runs.append(run)
    runs = [r for r in runs if len(r) > 1]
    if not runs:
        return None, TWO_LETTERS, []
    formed: list[str] = []
    for run in runs:
        word = "".join(c.lower() for _x, _y, c, _new in run)
        if word not in words_:
            return None, _not_a_word(word), []
        formed.append(word)
    grid = premiums()
    value = values()
    score = sum(_score_run(run, grid, value) for run in runs)
    if len(placed_rows) == rack_size():
        score += bingo_bonus()
    return score, "", formed


def validate_move(game: dict[str, Any], tiles: list[dict[str, Any]],
                  words_: frozenset[str]) -> tuple[Optional[int], str]:
    """A play by the side whose turn it is: (score, "") or (None, the reason)."""
    side = str(game.get("turn") or "player")
    rack = str((game.get("racks") or {}).get(side) or "")
    score, reason, _formed = score_placement(list(game["board"]), rack, tiles, words_)
    return score, reason


# -- the person's search (anchor-based, over the prefix set, bounded by nodes) ---------------------


@dataclass
class NodeCounter:
    """The search's work: one node per prefix extension tried (spec §21.1). Never a clock."""

    nodes: int = 0


class _Spent(Exception):
    """The node budget is spent: the search stops with what it found."""


@dataclass
class _Search:
    board: list[str]
    rack: str
    words: frozenset[str]
    prefixes: frozenset[str]
    budget: int
    counter: NodeCounter
    found: dict[tuple, tuple[int, tuple]] = field(default_factory=dict)

    def tick(self) -> None:
        if self.counter.nodes >= self.budget:
            raise _Spent
        self.counter.nodes += 1


def _anchors(board: list[str]) -> set[tuple[int, int]]:
    """Empty squares next to a tile; the centre on an empty board."""
    n = len(board)
    if _board_empty(board):
        return {(n // 2, n // 2)}
    out: set[tuple[int, int]] = set()
    for y in range(n):
        for x in range(n):
            if board[y][x] == EMPTY and any(_filled(board, x + dx, y + dy)
                                            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                out.add((x, y))
    return out


def _cross_ok(board: list[str], words_: frozenset[str], x: int, y: int, letter: str,
              dx: int, dy: int, cache: dict[tuple[int, int, str], bool]) -> bool:
    """Whether `letter` at (x, y) forms a word (or nothing) across the line (dx, dy)."""
    key = (x, y, letter)
    hit = cache.get(key)
    if hit is not None:
        return hit
    cx, cy = dy, dx                                # the perpendicular
    before = []
    px, py = x - cx, y - cy
    while _filled(board, px, py):
        before.append(board[py][px].lower())
        px, py = px - cx, py - cy
    after = []
    px, py = x + cx, y + cy
    while _filled(board, px, py):
        after.append(board[py][px].lower())
        px, py = px + cx, py + cy
    ok = (not before and not after) or ("".join(reversed(before)) + letter + "".join(after)) in words_
    cache[key] = ok
    return ok


def _extend(search: _Search, x: int, y: int, dx: int, dy: int, prefix: str, rack: list[str],
            placed: list[dict[str, Any]], covers: bool, anchors: set[tuple[int, int]],
            cross: dict[tuple[int, int, str], bool]) -> None:
    """Extend `prefix` from square (x, y) along (dx, dy); record every word that ends here legally."""
    n = len(search.board)
    inside = 0 <= x < n and 0 <= y < n
    if placed and covers and len(prefix) > 1 and (not inside or search.board[y][x] == EMPTY) \
            and prefix in search.words:
        key = tuple(sorted((t["x"], t["y"], t["letter"], bool(t.get("blank"))) for t in placed))
        if key not in search.found:
            score, _reason, _formed = score_placement(search.board, search.rack, placed, search.words)
            if score is not None:
                search.found[key] = (score, tuple(dict(t) for t in sorted(
                    placed, key=lambda t: (t["x"], t["y"], t["letter"], bool(t.get("blank"))))))
    if not inside:
        return
    here = search.board[y][x]
    if here != EMPTY:
        word = prefix + here.lower()
        search.tick()
        if word in search.prefixes:
            _extend(search, x + dx, y + dy, dx, dy, word, rack, placed, covers, anchors, cross)
        return
    tried: set[tuple[str, bool]] = set()
    for i, tile in enumerate(rack):
        options = [(c, True) for c in ALPHABET] if tile == BLANK else [(tile, False)]
        for letter, blank in options:
            if (letter, blank) in tried:
                continue
            tried.add((letter, blank))
            word = prefix + letter
            search.tick()
            if word not in search.prefixes:
                continue
            if not _cross_ok(search.board, search.words, x, y, letter, dx, dy, cross):
                continue
            tile_row: dict[str, Any] = {"x": x, "y": y, "letter": letter}
            if blank:
                tile_row["blank"] = True
            _extend(search, x + dx, y + dy, dx, dy, word, rack[:i] + rack[i + 1:], placed + [tile_row],
                    covers or (x, y) in anchors, anchors, cross)


def _starts(board: list[str], anchors: set[tuple[int, int]], dx: int, dy: int,
            reach: int) -> list[tuple[int, int]]:
    """Squares a word along (dx, dy) may start at: nothing before them, an anchor within `reach` tiles."""
    n = len(board)
    out: list[tuple[int, int]] = []
    for y in range(n):
        for x in range(n):
            if _filled(board, x - dx, y - dy):
                continue                           # the word would start earlier
            empties, px, py, ok = 0, x, y, False
            while 0 <= px < n and 0 <= py < n:
                if (px, py) in anchors:
                    ok = True
                    break
                if board[py][px] == EMPTY:
                    empties += 1
                    if empties >= reach:
                        break
                px, py = px + dx, py + dy
            if ok:
                out.append((x, y))
    return out


def best_moves(game: dict[str, Any], rack: str, words_: frozenset[str], prefixes_: frozenset[str], *,
               node_budget: int, counter: Optional[NodeCounter] = None) -> list[tuple[int, tuple]]:
    """
    Every legal play from `rack` the search finds within `node_budget`
    prefix extensions, scored by `score_placement`, sorted canonically:
    `(-score, placement)`, a placement a tuple of tile dicts in (x, y)
    order. `counter`, when given, is the one the search counts on.
    """
    counter = counter if counter is not None else NodeCounter()
    board = list(game["board"])
    search = _Search(board, rack, words_, prefixes_, int(node_budget), counter)
    anchors = _anchors(board)
    tiles = sorted(rack, key=lambda c: (c == BLANK, c))
    try:
        for dx, dy in ((1, 0), (0, 1)):
            cross: dict[tuple[int, int, str], bool] = {}
            for x, y in _starts(board, anchors, dx, dy, len(rack)):
                _extend(search, x, y, dx, dy, "", tiles, [], False, anchors, cross)
    except _Spent:
        pass
    moves = list(search.found.values())
    moves.sort(key=lambda m: (-m[0], tuple((t["x"], t["y"], t["letter"], bool(t.get("blank"))) for t in m[1])))
    return moves


def top_k(skill: float) -> int:
    """How many of their best moves a person of `skill` picks among (games.yaml `top_k_by_skill`)."""
    k = 1
    for at_least, rows in spec()["top_k_by_skill"]:
        if float(skill) >= float(at_least):
            k = int(rows)
    return k


def pick_move(moves: list[tuple[int, tuple]], skill: float, rng: random.Random) -> Optional[tuple]:
    """One placement from the top `k` for `skill`, drawn on `rng` (their SOCIAL_GAME stream); None when none."""
    if not moves:
        return None
    pool = moves[:max(1, top_k(skill))]
    return pool[rng.randrange(len(pool))][1]


# -- applying a move (inside the social_game handler only: rule 3) ------------------------------------


def _other(side: str) -> str:
    return "them" if side == "player" else "player"


def _rack_value(rack: str) -> int:
    value = values()
    return sum(value.get(c, 0) for c in rack if c != BLANK)


def _finish(row: dict[str, Any], out_side: Optional[str]) -> None:
    """End of game: each side loses its rack's value; a side that went out gains the other's."""
    racks = row["racks"]
    if out_side is not None:
        gained = _rack_value(racks[_other(out_side)])
        row["scores"][out_side] += gained
        row["scores"][_other(out_side)] -= gained
    else:
        for side in SIDES:
            row["scores"][side] -= _rack_value(racks[side])
    row["status"] = "finished"


def apply_move(state: Any, row: dict[str, Any], by: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    One move by `by` on a live row: `move: play` (`tiles`), `pass`, or
    `swap` (`letters`, from their rack, while the bag holds as many). The
    row is changed only when the move is legal; the result names the words
    and the score, never a rack or the bag.
    """
    if row.get("turn") != by:
        return {"ok": False, "error": "It's not your turn"}
    kind = str(args.get("move") or "")
    racks, n = row["racks"], rack_size()
    record: dict[str, Any] = {"by": by, "kind": kind, "words": [], "score": 0}
    if kind == "play":
        tiles = list(args.get("tiles") or [])
        score, reason, formed = score_placement(list(row["board"]), racks[by], tiles, words())
        if score is None:
            return {"ok": False, "error": reason}
        board = [list(r) for r in row["board"]]
        rack = list(racks[by])
        for raw in tiles:
            x, y, letter, blank = _tile(raw)  # type: ignore[misc]
            board[y][x] = letter.upper() if blank else letter
            rack.remove(BLANK if blank else letter)
        row["board"] = ["".join(r) for r in board]
        draw = n - len(rack)
        racks[by] = "".join(rack) + row["bag"][:draw]
        row["bag"] = row["bag"][draw:]
        row["scores"][by] += score
        row["scoreless"] = 0
        record.update(words=formed, score=score, tiles=[{k: t[k] for k in ("x", "y", "letter", "blank") if k in t}
                                                        for t in tiles])
        if not racks[by] and not row["bag"]:
            _finish(row, by)
    elif kind == "swap":
        letters = str(args.get("letters") or "")
        left = list(racks[by])
        for c in letters:
            if c not in left:
                return {"ok": False, "error": NO_BLANK if c == BLANK else _no_letter(c)}
            left.remove(c)
        if not letters:
            return {"ok": False, "error": "Pick the tiles to swap."}
        if not can_swap(row, len(letters)):
            return {"ok": False, "error": "There aren't enough tiles left to swap."}
        drawn = row["bag"][:len(letters)]
        racks[by] = "".join(left) + drawn
        row["bag"] = row["bag"][len(letters):] + letters      # returned to the bottom of the bag
        row["scoreless"] = int(row.get("scoreless", 0)) + 1
        record["swapped"] = len(letters)                      # how many, never which
    elif kind == "pass":
        row["scoreless"] = int(row.get("scoreless", 0)) + 1
    else:
        return {"ok": False, "error": NOT_A_MOVE}
    if row.get("status") != "finished" and int(row.get("scoreless", 0)) >= int(spec()["scoreless_turns"]):
        _finish(row, None)
    if row.get("status") != "finished":
        row["turn"] = _other(by)
    return {"ok": True, "record": record}


def can_swap(row: dict[str, Any], count: int) -> bool:
    """A swap of `count` tiles is open: the bag holds as many, and at least games.yaml `swap_bag_min`."""
    bag = len(str(row.get("bag") or ""))
    return bag >= int(count) and bag >= int(spec()["swap_bag_min"])


def their_move(state: Any, row: dict[str, Any], pid: str, skill: float, rng: random.Random,
               counter: Optional[NodeCounter] = None) -> dict[str, Any]:
    """
    The person's move args, decided by the engine: their best plays within
    the node budget, one picked from the top `k` for their skill on `rng`;
    with none, a swap of the whole rack while the bag allows it, else a pass.
    """
    rack = str(row["racks"]["them"])
    moves = best_moves(row, rack, words(), prefixes(), node_budget=node_budget(), counter=counter)
    pick = pick_move(moves, skill, rng)
    if pick is not None:
        return {"move": "play", "tiles": [dict(t) for t in pick]}
    if rack and can_swap(row, len(rack)):
        return {"move": "swap", "letters": rack}
    return {"move": "pass"}


def winner(row: dict[str, Any]) -> str:
    """'player', 'them' or 'draw' (a finished row)."""
    p, t = int(row["scores"]["player"]), int(row["scores"]["them"])
    return "draw" if p == t else ("player" if p > t else "them")


def margin(row: dict[str, Any]) -> int:
    return int(row["scores"]["player"]) - int(row["scores"]["them"])


def bonus(row: dict[str, Any]) -> dict[str, int]:
    """A finished game's effects beyond `effects.finished`: none for Tile Talk (its crushing win is the framework's)."""
    return {"familiarity": 0, "interest": 0}


def compact(row: dict[str, Any]) -> None:
    """A finished row keeps no bag and no racks (bounded state, spec §17.2)."""
    row.pop("bag", None)
    row.pop("racks", None)


def view(state: Any, row: dict[str, Any]) -> dict[str, Any]:
    """What the player sees of a row: the board, THEIR rack, the scores, the bag's count. Never theirs."""
    racks = row.get("racks") or {}
    return {
        "board": list(row.get("board") or []),
        "premiums": premiums(),
        "rack": str(racks.get("player") or ""),
        "bag_left": len(str(row.get("bag") or "")),
        "scores": dict(row.get("scores") or {}),
        "turn": row.get("turn"),
    }


def banter_note(row: dict[str, Any]) -> str:
    """The voice's line about the game (engine words): the last move and the score."""
    moves = row.get("moves") or []
    last = moves[-1] if moves else {}
    p, t = int(row["scores"]["player"]), int(row["scores"]["them"])
    if last.get("kind") == "play" and last.get("words"):
        did = f"{'You' if last.get('by') == 'them' else 'They'} just played {str(last['words'][0]).upper()} " \
              f"for {int(last.get('score', 0))}."
    elif last.get("kind") == "swap":
        did = f"{'You' if last.get('by') == 'them' else 'They'} just swapped tiles."
    else:
        did = f"{'You' if last.get('by') == 'them' else 'They'} just passed."
    standing = "level" if p == t else ("you are ahead" if t > p else "they are ahead")
    state_line = "The game is over" if row.get("status") == "finished" else "The score is"
    return f"{label()}: {did} {state_line}: you {t}, them {p} ({standing})."


renew_after_fork(globals(), _WORDS_LOCK=threading.Lock)

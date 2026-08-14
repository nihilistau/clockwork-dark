"""
UI build and socket-contract tests.

The audit's single largest finding was drift between what the server sends and
what the client consumes: the server emitted `dice_result` and `cutscene_start`
to no listener, while the client listened for `narration_delta` that nothing
emitted. These tests make that drift fail the build.

There is a second drift in the same seam, one axis over: between `ui/src` and
the committed `dist` built from it. The socket tests read the SOURCE; a player
runs the BUILD. `test_the_committed_build_is_not_behind_its_source` is the only
test here that knows the difference.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "content" / "scenes" / "clockwork" / "static" / "dist"
TEMPLATE = ROOT / "content" / "scenes" / "clockwork" / "templates" / "clockwork.html"
UI_SRC = ROOT / "ui" / "src"

# Repo-relative, because git speaks in repo-relative paths.
DIST_PATH = "content/scenes/clockwork/static/dist"
# Every input to the build. `package.json` is in the list because a dependency
# bump changes the bundle without touching a line of src, and `index.html` is
# Vite's entry document, not decoration.
BUILD_INPUTS = ("ui/src", "ui/vite.config.js", "ui/package.json", "ui/index.html")

pytestmark = pytest.mark.skipif(
    not DIST.exists(), reason="UI not built — run `cd ui && npm run build`"
)


def test_build_output_exists():
    """dist/ is committed so the game plays without node installed."""
    assert (DIST / "app.js").exists()
    assert (DIST / "index.css").exists()


def test_template_points_at_the_built_assets():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "/static/dist/app.js" in html
    assert "/static/dist/index.css" in html


def test_nothing_loads_from_a_cdn():
    """
    A local-first game must boot with no network.

    The old template pulled socket.io from cdn.socket.io and the design tokens
    pulled four font families from Google Fonts.
    """
    sources = [TEMPLATE.read_text(encoding="utf-8")]
    for path in list(DIST.glob("*.css")) + list(DIST.glob("*.js")):
        sources.append(path.read_text(encoding="utf-8", errors="ignore"))

    offenders = []
    for text in sources:
        offenders += re.findall(r"https?://(?:cdn\.|unpkg|fonts\.googleapis|fonts\.gstatic)[^\s\"')]*", text)
    assert offenders == [], f"remote assets referenced: {offenders[:5]}"


def test_fonts_are_self_hosted():
    fonts = list((DIST / "fonts").glob("*.woff2"))
    assert len(fonts) >= 8, "expected the four families' latin subsets on disk"


# ---------------------------------------------------------------------------
# The freshness guard
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    """
    Run git at the repo root, or skip the calling test if git cannot answer.

    A source tarball, a `.git`-less export and a machine with no git installed
    are all legitimate ways to have this repository, and none of them can be
    asked about commit history. They skip; they do not fail.
    """
    if not (ROOT / ".git").exists():  # a worktree's .git is a file, hence .exists()
        pytest.skip("not a git checkout -- build freshness cannot be judged")
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH -- build freshness cannot be judged")
    try:
        done = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git could not be run: {exc}")
    if done.returncode != 0:
        pytest.skip(f"`git {' '.join(args)}` failed: {done.stderr.strip()}")
    return done.stdout.strip()


def test_the_committed_build_is_not_behind_its_source():
    """
    The dist a player runs must not be older than the source it was built from.

    Every test above this one proves the committed build is COMPLETE and
    offline-clean. None of them proves it is CURRENT. That gap let dist fall
    roughly seventeen source files behind: the whole multi-agent shell, the
    store, the story loader, the Play and Saves screens, ChoiceRow, Chrome,
    NarrativeLog, ReasoningPanel, the new FadeCard and MicButton,
    styles/index.css and several wicked-garden parts. Every one of them was
    written, reviewed, tested and committed, and not one reached a player,
    because what reaches a player is the dist and not the source.

    Mtime cannot answer this. A fresh clone writes every file at checkout time,
    so on the machine that matters most -- someone else's -- the source and the
    build are always exactly the same age. Git history can: `dist_commit` is the
    last commit that touched the build, and anything the build's inputs changed
    between there and HEAD is a change the shipped bundle does not contain.

    A tree diff rather than a timestamp comparison, deliberately. Comparing
    `git log -1 --format=%ct` across the two paths reads committer dates, and a
    merge or a rebase reorders those freely -- a branch cut last week and merged
    today carries last week's dates into a position after today's build commit,
    and the guard reads a stale dist as fresh. Diffing the build commit's tree
    against HEAD's asks the same question in the repository's own order instead
    of a clock's, and answers it in one call rather than one per source file.

    What this cannot see: a dist committed alongside a source change but built
    from the source as it stood before it. Only hashing the source tree into the
    build catches that, which costs a build artefact and a hashing convention.
    This catches the failure that actually happened.

    Only committed history is judged, at both ends. An uncommitted edit under
    `ui/src` is work in progress, not something a player can be served; and an
    uncommitted dist is a rebuild in flight, so the last BUILD commit is no
    longer the state being asked about and this skips rather than reporting a
    staleness the developer has already fixed. That leaves one hole -- a stray
    edit under dist silences the guard locally -- and it is the right trade,
    because the tree this guard exists to protect is the committed one, which on
    CI and on a fresh clone is always clean.

    The sequence it is built to walk you through: edit src, run pytest, FAIL;
    `npm run build`, run pytest, SKIP; commit src and dist together, PASS.
    """
    dirty = _git("status", "--porcelain", "--", DIST_PATH)
    if dirty:
        pytest.skip(
            f"{DIST_PATH} has uncommitted changes -- a rebuild is in flight; "
            "commit src and dist together and this judges the result"
        )

    dist_commit = _git("log", "-1", "--format=%H", "--", DIST_PATH)
    if not dist_commit:
        # A shallow clone whose depth does not reach the build commit, or a dist
        # present on disk but never committed. Neither is evidence of staleness.
        pytest.skip(f"no commit in this history touches {DIST_PATH}")

    changed = _git("diff", "--name-only", dist_commit, "HEAD", "--", *BUILD_INPUTS)
    behind = sorted(line for line in changed.splitlines() if line.strip())

    assert not behind, (
        f"the committed UI build is {len(behind)} source file(s) behind -- none of "
        f"these changes reach a player until dist is rebuilt:\n  "
        + "\n  ".join(behind)
        + f"\n\nlast commit touching {DIST_PATH}: {dist_commit[:12]}"
        + "\nfix: `cd ui && npm run build`, then commit dist in the same change."
    )


# -- socket contract -----------------------------------------------------


def _server_events(pattern: str) -> set[str]:
    """
    Event names the server passes to an emit call.

    Scans engine/scenes/ as well as content/: the default scene and its turn
    (the source of every emit) moved to engine/scenes/default_scene.py and
    default_state.py, while a story-owned scene package would still live under
    content/.
    """
    found: set[str] = set()
    for tree in (ROOT / "content", ROOT / "engine" / "scenes"):
        for path in tree.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            found |= set(re.findall(pattern, text))
    return found


def test_every_emitted_event_has_a_client_listener():
    emitted = _server_events(r'emit(?:_callback)?\(\s*"([a-z_]+)"')
    listened = set(
        re.findall(
            r'"([a-z_]+)"',
            (UI_SRC / "core" / "socket.js").read_text(encoding="utf-8").split("export const INBOUND")[1].split("]")[0],
        )
    )
    missing = emitted - listened
    assert not missing, f"server emits with no client listener: {sorted(missing)}"


def test_client_does_not_listen_for_events_nobody_sends():
    text = (UI_SRC / "core" / "socket.js").read_text(encoding="utf-8")
    inbound = set(
        re.findall(r'"([a-z_]+)"', text.split("export const INBOUND")[1].split("]")[0])
    )
    emitted = _server_events(r'emit(?:_callback)?\(\s*"([a-z_]+)"')
    # These are socket.io's own lifecycle events, plus ones landing in later
    # phases; anything else listening into the void is a mistake.
    allowed_unsent = {"error", "portrait_ready", "narration_audio"}
    orphans = inbound - emitted - allowed_unsent
    assert not orphans, f"client listens for events nothing emits: {sorted(orphans)}"


# ---------------------------------------------------------------------------
# The ending payload
#
# `turn_update` grew a field rather than the socket growing an event, so the
# INBOUND checks above cannot see this one. The drift it guards is the drift
# that was actually there: EpilogueCard read `id`, `mortal`, `garden`, `echo`
# and `gardenDays` while the server sends `ending_id`, `card_m`, `card_g`,
# `echoes` and a rendered `time_line` -- five names, none of them matching, and
# a component that computed the run's cost itself and got it wrong low.
# ---------------------------------------------------------------------------


def _epilogue_keys() -> set[str]:
    """The keys the server actually ships, from the dataclass that ships them."""
    from engine.game.epilogue import Epilogue

    return set(Epilogue(ending_id="x").to_dict())


def test_the_ending_field_is_read_under_the_name_the_server_sends():
    """A field the client stores under a different name is a field it drops."""
    store = (UI_SRC / "core" / "store.js").read_text(encoding="utf-8")
    assert "payload.ending" in store, "store.js never reads the turn payload's ending"
    assert re.search(r"^\s*ending:\s*null,", store, re.MULTILINE), "no initial ending state"

    app = (UI_SRC / "core" / "App.jsx").read_text(encoding="utf-8")
    assert "state.ending" in app, "App.jsx never routes to the ending screen"


def _destructured_props(text: str, component_name: str) -> set[str]:
    """
    The prop names in ``function <name>({ ... })``.

    Names, not values: ``card_m: mortal`` is the key ``card_m`` bound locally to
    ``mortal``, and it is the key that has to exist on the payload. Defaults are
    stripped, and a nested default containing braces would break this -- there
    are none, and a rename that introduced one would fail loudly here rather
    than quietly match nothing.
    """
    match = re.search(
        rf"function\s+{component_name}\s*\(\s*\{{(.*?)\}}\s*\)", text, re.DOTALL
    )
    assert match, f"could not find {component_name}'s props"
    body = re.sub(r"=\s*[^,]+", "", match.group(1))  # drop defaults
    body = re.sub(r"//.*$", "", body, flags=re.MULTILINE)
    return {
        part.split(":")[0].strip()
        for part in body.split(",")
        if part.strip() and not part.strip().startswith("...")
    }


def test_the_garden_card_destructures_the_payloads_own_keys():
    """
    EpilogueCard takes `{...ending}`, so its props ARE the server's keys.

    This is the exact drift that was there: it read `id`, `mortal`, `garden`,
    `echo` and `gardenDays` while the server sends `ending_id`, `card_m`,
    `card_g`, `echoes` and `time_line`. Five names, none of them matching, and
    every one would have rendered `undefined` -- which in React is a silently
    empty element, so the last screen of the story goes blank with nothing in
    any log to say why.
    """
    text = (UI_SRC / "stories" / "wicked-garden" / "parts" / "EpilogueCard.jsx").read_text(
        encoding="utf-8"
    )
    props = _destructured_props(text, "EpilogueCard")
    assert props, "matched no props at all"
    unknown = props - _epilogue_keys()
    assert not unknown, f"EpilogueCard takes props the server does not send: {sorted(unknown)}"


def test_the_core_screen_only_reads_keys_the_server_sends():
    """Core reads through `ending.<key>` rather than by destructuring."""
    text = (UI_SRC / "core" / "screens" / "Ending.jsx").read_text(encoding="utf-8")
    used = set(re.findall(r"\bending\.([a-z_]+)", text))
    assert used, "matched no field reads at all"
    unknown = used - _epilogue_keys()
    assert not unknown, f"Ending.jsx reads keys the server does not send: {sorted(unknown)}"


def test_no_client_recomputes_the_time_debt():
    """
    The mortal-day cost is rendered server-side and must not be re-derived.

    `time_debt_mortal_days` carries the extra shards a lost labyrinth and a
    wasted hour added, so `gardenDays * 10` -- which is what this component
    used to do -- under-reports precisely the runs the sentence exists to
    report. The whole story is about what it cost; the client does not get to
    round it down.
    """
    for component in ("core/screens/Ending.jsx", "stories/wicked-garden/parts/EpilogueCard.jsx"):
        text = (UI_SRC / component).read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)
        assert "MORTAL_PER_GARDEN_DAY" not in code, component
        assert not re.search(r"\*\s*10\b", code), f"{component} multiplies days by ten"


# ---------------------------------------------------------------------------
# The structural block
#
# `threads` and `endings` ride out beside `meters` and are consumed by two
# story components that were dark for months. Same class of drift the epilogue
# test above guards, arriving through a payload key rather than an event.
# ---------------------------------------------------------------------------


def _garden_part(name: str) -> str:
    return (UI_SRC / "stories" / "wicked-garden" / "parts" / name).read_text(
        encoding="utf-8"
    )


def test_the_gallery_wrapper_maps_only_keys_the_server_sends():
    """
    `GalleryOverlay` is the ONE place snake_case becomes camelCase.

    The component takes `{id, title, tier, tease, lockReason, gate, closeness}`
    and the server sends snake_case, so something has to translate. A second
    translator, or a key read under a name the server never ships, is the exact
    defect that had EpilogueCard rendering five `undefined`s -- which in React
    is a silently empty element with nothing in any log to say why.
    """
    from engine.game import endings

    text = _garden_part("GalleryOverlay.jsx")
    read = set(re.findall(r"\brow\.([a-z_]+)", text))
    assert read, "matched no field reads at all"
    unknown = read - set(endings.CLIENT_ROW_KEYS)
    assert not unknown, f"GalleryOverlay reads keys the server does not send: {sorted(unknown)}"


def test_the_contracts_overlay_reads_only_keys_the_summary_sends():
    """
    `threads.summary()` deliberately trims the record -- the effect hooks are
    the engine's business -- so the scroll must read the trimmed shape and not
    the one it can see in `seal()`.
    """
    from engine.game import threads
    from engine.game.state import GameState

    state = GameState(session_id="drift")
    state.threads = [
        {
            "id": "t_1",
            "source": "sophia",
            "tags": ["Protection"],
            "terms": "a term",
            "due_day": 4,
            "can_cut_with": ["law"],
            "sealed_by": "a word",
            "status": "active",
            "on_break": [{"type": "value"}],
        }
    ]
    served = set(threads.summary(state)[0])

    text = _garden_part("ContractsOverlay.jsx")
    read = set(re.findall(r"\bthread\.([a-z_]+)", text))
    assert read, "matched no field reads at all"
    unknown = read - served
    assert not unknown, f"ContractsOverlay reads keys summary() does not send: {sorted(unknown)}"


def test_the_two_revived_overlays_gate_on_the_key_that_feeds_them():
    """
    A screen wired against a key that may not exist is a permanently empty
    modal, which is the disease the plugin seam was built to cure. Both entries
    declare `when`, and both `when`s test the payload key rather than a slug --
    a story borrowing this skin with no bargains gets no scroll button.
    """
    text = (UI_SRC / "stories" / "wicked-garden" / "index.jsx").read_text(encoding="utf-8")
    for component, key in (("ContractsOverlay", "threads"), ("GalleryOverlay", "endings")):
        entry = text.split(f"Component: {component},")[1].split("}")[0]
        assert "when:" in entry, f"{component} is registered with no `when` gate"
        assert f"state.world?.{key}" in entry, f"{component} gates on the wrong key"
    assert "wicked-garden" not in text.split("overlays: [")[1].split("],")[0]


def _code_only(text: str) -> str:
    """The file with its comments removed, so prose about a rule is not a use of it."""
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)


def test_closeness_is_used_as_a_word_and_never_as_a_number():
    """
    THE VEILED RULE, arriving through a new key.

    An ending's `closeness` is its continuous 0-1 score banded by the same code
    that bands a veiled meter, and it lands under the same rule: the word is
    the whole truth the player is allowed. Looking it up in a table or putting
    it in a class name is a use; multiplying it, or turning it into a width or
    a percentage, is reconstructing the number the server declined to send.
    """
    for name in ("GalleryOverlay.jsx", "EndingGallery.jsx"):
        code = _code_only(_garden_part(name))
        for hit in re.findall(r"[^\n]*\bcloseness\b[^\n]*", code):
            assert not re.search(r"closeness\s*[*/+-]|[*/+-]\s*closeness", hit), (
                f"{name} does arithmetic on a band: {hit.strip()}"
            )
            assert "%" not in hit, f"{name} builds a percentage from a band: {hit.strip()}"
            assert "width" not in hit, f"{name} builds a width from a band: {hit.strip()}"


# ---------------------------------------------------------------------------
# The turn watchdog
# ---------------------------------------------------------------------------


def test_the_watchdog_outlasts_the_servers_own_giving_up():
    """
    The client must never declare the world dead while the server is still
    working, and at 240s against a 300s generation cap it did exactly that --
    on turns that a reasoning model legitimately spends 106-205 seconds on
    (config/default.yaml, profile `big`). The player got "no answer" and lost
    the turn a full minute before the server would have reported a real error
    with a real reason.
    """
    from engine.config import get_config

    text = (UI_SRC / "core" / "App.jsx").read_text(encoding="utf-8")
    match = re.search(r"TURN_WATCHDOG_MS\s*=\s*(\d+)", text)
    assert match, "App.jsx no longer declares a watchdog"
    watchdog_seconds = int(match.group(1)) / 1000

    server_seconds = float(get_config().get("lmstudio.timeout_seconds", 0))
    assert server_seconds > 0, "the generation timeout is no longer configured"
    assert watchdog_seconds > server_seconds, (
        f"the client gives up at {watchdog_seconds}s, before the server does at "
        f"{server_seconds}s -- a live turn would be reported as no answer"
    )


def test_a_failed_turn_can_be_retried_without_retyping():
    """
    Every failure used to end as one line in the footer and a compose box the
    player had to retype into from memory. The input is held; this is the
    press. And the retry must NOT re-echo the player's line: it is already in
    the log from the attempt that failed, and a retry is the same move tried
    again, not a second thing they did.
    """
    app = (UI_SRC / "core" / "App.jsx").read_text(encoding="utf-8")
    assert "again.current" in app, "App.jsx holds no way to repeat the last move"
    assert 'emit("")' in app, "the retry re-echoes the player's line into the log"

    chrome = (UI_SRC / "core" / "parts" / "Chrome.jsx").read_text(encoding="utf-8")
    assert "onRetry" in chrome, "the footer offers no way to act on an error"


def test_destroying_a_run_is_confirmed_and_reports_failure():
    """
    Deleting a save is the only irreversible thing this client can do and it
    was two unchecked `fetch` calls -- no guard, and a refusal at either end
    refreshed the list, showed the run still sitting there, and said nothing.
    """
    app = (UI_SRC / "core" / "App.jsx").read_text(encoding="utf-8")
    body = app.split("const deleteSave")[1].split("const saveNow")[0]
    assert body.count("if (!") >= 2, "deleteSave still ignores an HTTP status"
    assert "Could not delete" in body, "a failed delete says nothing to the player"

    saves = _code_only((UI_SRC / "core" / "screens" / "Saves.jsx").read_text(encoding="utf-8"))
    assert "asking" in saves, "Delete has no confirmation step"
    # A native dialog tears focus out of the modal's trap and speaks in the
    # browser's voice; the guard belongs inside the focus order.
    assert "window.confirm" not in saves


def test_styles_use_semantic_tokens_not_raw_hex():
    """
    Raw hex in the app stylesheet breaks the four phase themes: [data-phase]
    retints the semantic aliases, and a hardcoded colour ignores it.
    """
    css = (UI_SRC / "styles" / "index.css").read_text(encoding="utf-8")
    # Strip comments before scanning.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    assert hexes == [], f"raw hex in app styles: {sorted(set(hexes))}"

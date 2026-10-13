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

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_jobs_narration import plain  # noqa: F401 -- the fixture

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


#: package.json keys that never reach the bundle: the release's version,
#: and the screenshot tool (v0.21.0 T5) -- a script entry and a devDependency
#: no source file imports. Any OTHER change is judged.
BUNDLE_NEUTRAL: tuple[tuple[str, ...], ...] = (
    ("version",),
    ("scripts", "screenshots"),
    ("devDependencies", "playwright-core"),
)


def _without(tree: Any, paths: tuple[tuple[str, ...], ...]) -> Any:
    tree = json.loads(json.dumps(tree))
    for path in paths:
        node = tree
        for key in path[:-1]:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return tree


def _bundle_neutral_only(path: str, since: str) -> bool:
    """
    Whether `package.json`'s only changes since `since` are BUNDLE_NEUTRAL keys.

    THE FALSE POSITIVE THIS REMOVES. `package.json` earns its place in
    BUILD_INPUTS because a DEPENDENCY bump changes the bundle without touching
    a line of src. Its `version` field does not: nothing bundles it. Once
    releases started bumping it in step with `pyproject.toml`, every release
    commit put this guard into a state no rebuild could clear -- `npm run build`
    produces byte-identical output, so dist is never dirty, never committed, and
    the file stays permanently "ahead". A guard that cannot be satisfied is one
    somebody deletes.

    The screenshot tool (v0.21.0 T5) is the same case: `playwright-core` is a
    devDependency only `ui/tools/screenshots.mjs` imports, run by the
    `screenshots` script, and neither reaches the bundle -- a rebuild after
    adding them is byte-identical, so dist could never be committed "after"
    them. Exactly those two keys are ignored, not a whole section.

    Everything else in the file is still judged, so adding or upgrading a
    dependency fails exactly as it did before.
    """
    if path != "ui/package.json":
        return False
    try:
        before = json.loads(_git("show", f"{since}:{path}"))
        after = json.loads((ROOT / path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    return _without(before, BUNDLE_NEUTRAL) == _without(after, BUNDLE_NEUTRAL)

pytestmark = pytest.mark.skipif(
    not DIST.exists(), reason="UI not built — run `cd ui && npm run build`"
)


def test_build_output_exists():
    """dist/ is committed so the game plays without node installed."""
    assert (DIST / "app.js").exists()
    assert (DIST / "index.css").exists()


def test_a_tool_only_dependency_is_bundle_neutral() -> None:
    """The screenshot tool's two keys are ignored; a bundled dependency is not."""
    base = {"version": "0.21.0", "dependencies": {"react": "^18.3.1"}, "devDependencies": {"vite": "^5.4.11"}, "scripts": {"build": "vite build"}}
    tool = json.loads(json.dumps(base))
    tool["devDependencies"]["playwright-core"] = "1.48.2"
    tool["scripts"]["screenshots"] = "node tools/screenshots.mjs"
    assert _without(base, BUNDLE_NEUTRAL) == _without(tool, BUNDLE_NEUTRAL)
    bundled = json.loads(json.dumps(tool))
    bundled["dependencies"]["socket.io-client"] = "^4.8.3"
    assert _without(base, BUNDLE_NEUTRAL) != _without(bundled, BUNDLE_NEUTRAL)


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
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            # EXPLICIT, because `text=True` alone decodes with the locale
            # encoding -- cp1252 on this machine -- and git speaks UTF-8. It
            # never mattered while this only read path names, which are ASCII.
            # `git show`ing a FILE is different: `ui/package.json`'s description
            # holds an em-dash, cp1252 turned it into U+FFFD, and the content
            # comparison below reported a difference that does not exist.
            encoding="utf-8",
            timeout=30,
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
    NarrativeLog, ReasoningPanel, MicButton,
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
    behind = [p for p in behind if not _bundle_neutral_only(p, dist_commit)]

    assert not behind, (
        f"the committed UI build is {len(behind)} source file(s) behind -- none of "
        f"these changes reach a player until dist is rebuilt:\n  "
        + "\n  ".join(behind)
        + f"\n\nlast commit touching {DIST_PATH}: {dist_commit[:12]}"
        + "\nfix: `cd ui && npm run build`, then commit dist in the same change."
    )


# -- socket contract -----------------------------------------------------


#: An emit to a socket, not a metric: `metrics_emit.emit("turn" | "login" | ...)`
#: records metrics and is not a socket event (plan decision 5).
_SOCKET_EMIT = r'(?<!metrics_emit\.)emit(?:_callback)?\(\s*"([a-z_]+)"'


#: A push to one session's room, the event name second (v0.22.0): the scene's
#: `emit_to_session(session_id, "<event>", payload)`, and the two places the
#: phone reaches it through -- the voicer's installed `emitter(...)` and its
#: `voicer.emit(...)` (`phone_message`, `media_ready`; spec §17.3).
_SESSION_EMIT = r'\b(?:emit_to_session|emitter|voicer\.emit)\([^,\n()]*(?:\([^()\n]*\))?[^,\n()]*,\s*"([a-z_]+)"'


def _server_events(pattern: str = _SOCKET_EMIT) -> set[str]:
    """
    Event names the server passes to an emit call.

    Scans engine/scenes/ and content/ (the default scene and its turn), and
    engine/hosting/ since v0.21.0 (`session_ended`, Review 8), and
    engine/social/ since v0.22.0 (the phone's event and its pushes). The
    metrics module is skipped: its `emit` is a metric. With the default
    pattern, a push to one session's room (`_SESSION_EMIT`) is read too.
    """
    patterns = [pattern] + ([_SESSION_EMIT] if pattern == _SOCKET_EMIT else [])
    found: set[str] = set()
    trees = (ROOT / "content", ROOT / "engine" / "scenes", ROOT / "engine" / "hosting", ROOT / "engine" / "social")
    for tree in trees:
        for path in tree.rglob("*.py"):
            if path.name == "metrics_emit.py":
                continue
            text = path.read_text(encoding="utf-8")
            for each in patterns:
                found |= set(re.findall(each, text))
    return found


def test_the_phone_pushes_are_found_and_listened_for() -> None:
    """READ RECEIPTS' background pushes go out through `emit_to_session` by way of the
    voicer, not an `emit("...")` call: the scan reads them, and INBOUND has both."""
    emitted = _server_events()
    assert {"phone_message", "media_ready"} <= emitted
    inbound = (UI_SRC / "core" / "socket.js").read_text(encoding="utf-8").split("export const INBOUND")[1].split("]")[0]
    assert '"phone_message"' in inbound and '"media_ready"' in inbound
    assert re.findall(_SESSION_EMIT, 'scene.emit_to_session(sid, "session_ended", {})') == ["session_ended"]
    assert re.findall(_SESSION_EMIT, 'emitter(str(session.session_id), "phone_message", body)') == ["phone_message"]


def test_the_hosting_tree_is_scanned_and_its_metrics_are_not_events():
    emitted = _server_events()
    assert "session_ended" in emitted
    assert not {"login", "session", "turn"} & emitted


def test_every_emitted_event_has_a_client_listener():
    emitted = _server_events()
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
    emitted = _server_events()
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

    server_seconds = float(get_config().get("llm.timeout_seconds", 0))
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
    # `emit("", id)` since the final fix wave: the retry also names the id it
    # sends (a recovered frame's own, matched by intent), still with no echo.
    assert re.search(r'emit\(""[,)]', app), "the retry re-echoes the player's line into the log"

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


def test_the_choice_chip_reads_an_intent_label_the_server_writes():
    """
    The chip's mechanical affordance is a real payload key, not a hope.

    A choice's `intent` is executed before the next beat is written, and the
    narrator decides which choices carry one. It is told that a choice which is
    only talk carries none, and nothing can enforce that -- no grammar reads a
    sentence and tells conversation from movement. So the consequence is shown
    instead: `engine/scenes/default_state.py::_label_intents` writes
    `intent_label` onto every option whose intent the engine can describe, and
    ChoiceRow renders it.

    Both halves are asserted here because either alone is silent. A client
    reading a key nobody writes renders nothing; a server writing a key nobody
    reads is dead weight -- and this pairing is exactly the drift this file
    exists for.
    """
    chip = _code_only((UI_SRC / "core" / "parts" / "ChoiceRow.jsx").read_text(encoding="utf-8"))
    assert "choice.intent_label" in chip, "ChoiceRow does not render the intent label"

    server = (ROOT / "engine" / "scenes" / "default_state.py").read_text(encoding="utf-8")
    assert '"intent_label"' in server, "no server writes intent_label onto a choice"
    # And it must be applied where the client actually gets its options: the
    # turn payload AND the opening, which carries authored intents of its own.
    # Definition plus all three paths that hand the client options: the
    # turn payload, the opening, and the resume screen -- which is where a
    # road is most likely to be picked blind, the player having been away.
    assert server.count("_label_intents(") >= 4, (
        "intent labelling is missing from one of turn / opening / resume"
    )


# ---------------------------------------------------------------------------
# The core panels read only keys their producers send (v0.21.0, spec §12)
# ---------------------------------------------------------------------------

PANELS_SRC = UI_SRC / "core" / "panels"


def _reads(text: str, name: str) -> set[str]:
    return set(re.findall(rf"\b{name}\.([a-z_]+)", text))


def test_the_poster_reads_only_keys_the_law_block_sends(tmp_path: Path) -> None:
    import yaml

    from engine.config import set_overlay
    from engine.game.state import GameState
    from test_law import SPEC as LAW_SPEC

    path = tmp_path / "law.yaml"
    path.write_text(yaml.safe_dump(LAW_SPEC), encoding="utf-8")
    set_overlay({"paths": {"law": str(path)}})
    try:
        state = GameState(rng_seed=3, location_id="edgewood_square")
        state.law["custody"] = {"fine": 5, "days": 1}
        law = state.to_client_dict()["law"]
    finally:
        set_overlay(None)
    text = (PANELS_SRC / "WantedPoster.jsx").read_text(encoding="utf-8")
    for name, served in (("law", set(law)), ("custody", set(law["custody"])), ("scales", set(law["scales"]))):
        read = _reads(text, name)
        assert read, f"WantedPoster reads nothing off `{name}`: the scan matched nothing"
        assert read <= served, f"WantedPoster reads `{name}` keys the payload never sends: {sorted(read - served)}"


def test_the_job_panel_reads_only_keys_the_job_block_sends(plain: Path) -> None:
    from test_jobs_narration import _open, _world

    state = _world()
    _open(state)
    job = state.to_client_dict()["job"]
    text = (PANELS_SRC / "JobPanel.jsx").read_text(encoding="utf-8")
    for name, served in (("job", set(job)), ("active", set(job["active"])), ("scales", set(job["scales"]))):
        read = _reads(text, name)
        assert read, f"JobPanel reads nothing off `{name}`"
        assert read <= served, f"JobPanel reads `{name}` keys the payload never sends: {sorted(read - served)}"


def test_the_people_strip_reads_only_the_routes_keys() -> None:
    from engine.scenes.default_api import PERSON_KEYS

    read = _reads((PANELS_SRC / "PeopleStrip.jsx").read_text(encoding="utf-8"), "person")
    assert read and read <= set(PERSON_KEYS), sorted(read - set(PERSON_KEYS))


def test_the_roll_card_reads_only_keys_the_dice_result_sends() -> None:
    recorded = json.loads((ROOT / "tests" / "fixtures" / "local_mode" / "hue-and-cry" / "socket_stream_turn.json").read_text(encoding="utf-8"))

    def events(node: Any) -> list[dict[str, Any]]:
        if isinstance(node, dict):
            found = [node] if node.get("name") == "dice_result" else []
            return found + [e for value in node.values() for e in events(value)]
        if isinstance(node, list):
            return [e for value in node for e in events(value)]
        return []

    (dice,) = events(recorded)[:1]
    served = set(dice["args"][0]) | {"at"}  # `at` is the reducer's own stamp
    read = _reads((PANELS_SRC / "RollCard.jsx").read_text(encoding="utf-8"), "roll")
    assert read and read <= served, sorted(read - served)
    modifier_read = _reads((PANELS_SRC / "RollCard.jsx").read_text(encoding="utf-8"), "modifier")
    assert modifier_read <= {"label", "delta"}


def _strip_js_comments(text: str) -> str:
    """
    JS/JSX source with its `//` and `/* */` comments blanked (newlines kept,
    so line numbers hold). String and template literals are skipped over, so
    a `//` inside "http://..." is not taken for a comment. Good enough for a
    guard: a regex literal holding `//` would be over-stripped, and none does.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'`":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, j))
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _code_lines(path: Path) -> list[tuple[int, str]]:
    return list(enumerate(_strip_js_comments(path.read_text(encoding="utf-8")).splitlines(), 1))


def _ui_files(*roots: Path) -> list[Path]:
    return sorted(p for root in roots for p in root.rglob("*") if p.suffix in (".js", ".jsx"))


#: `onCustom` uses a plugin or a core panel may make, as {"path:line": why}.
#: Empty: none needs typed text. A real free-text feature adds exactly its line.
ON_CUSTOM_ALLOWED: dict[str, str] = {}

#: The only files that may speak the socket's choice protocol. `link.js` is
#: the connection's state machine (v0.21.0 T11): it emits `join_session` and
#: `resume`, never `player_choice`, each behind `socket.connected`.
SOCKET_FILES = {"ui/src/core/App.jsx", "ui/src/core/socket.js", "ui/src/core/link.js"}


def test_no_plugin_or_core_panel_uses_typed_text() -> None:
    """
    Rule 1 (spec §2.3, Review 1; T10 fix round 1): typed text carries no
    intent by definition (`default_state.resolve_player_intent`), so a move
    sent through `onCustom` resolves nothing. Structural, not a phrase match:
    after comments are stripped, no `onCustom` identifier appears anywhere
    under `ui/src/stories/` or `ui/src/core/panels/` -- a call, a prop, an
    alias or a split line alike -- unless `ON_CUSTOM_ALLOWED` names its line.
    """
    offenders = []
    for path in _ui_files(UI_SRC / "stories", UI_SRC / "core" / "panels"):
        rel = path.relative_to(ROOT).as_posix()
        for number, line in _code_lines(path):
            if re.search(r"\bonCustom\b", line) and f"{rel}:{number}" not in ON_CUSTOM_ALLOWED:
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert not offenders, "typed text reachable from a plugin or core panel:\n" + "\n".join(offenders)


def test_only_the_app_and_socket_speak_the_choice_protocol() -> None:
    """
    `player_choice`, `custom_text` and `.emit(` appear (outside comments) only
    in `core/App.jsx` and `core/socket.js`: no plugin or panel builds its own
    choice frame, with or without typed text.
    """
    offenders = []
    for path in _ui_files(UI_SRC):
        rel = path.relative_to(ROOT).as_posix()
        if rel in SOCKET_FILES:
            continue
        for number, line in _code_lines(path):
            if re.search(r"player_choice|custom_text|\.emit\s*\(", line):
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert not offenders, "the choice protocol spoken outside App/socket:\n" + "\n".join(offenders)


def test_the_comment_stripper_keeps_code_and_strings() -> None:
    text = 'a("http://x"); // onCustom(t)\n/* onCustom\n */ b(`//y`, onCustom)'
    stripped = _strip_js_comments(text)
    assert stripped.count("onCustom") == 1 and "http://x" in stripped and "`//y`" in stripped
    assert stripped.count("\n") == text.count("\n")


def test_the_encounter_panel_reads_only_keys_the_encounter_sends() -> None:
    recorded = json.loads((ROOT / "tests" / "fixtures" / "local_mode" / "hue-and-cry" / "state.json").read_text(encoding="utf-8"))
    encounter = recorded["json"]["state"]["encounter"]
    text = (PANELS_SRC / "EncounterPanel.jsx").read_text(encoding="utf-8")
    for name, served in (
        ("encounter", set(encounter)),
        ("approach", set(encounter["approaches"][0])),
        ("threat", set(encounter["threat"])),
    ):
        read = _reads(text, name)
        assert read, f"EncounterPanel reads nothing off `{name}`"
        assert read <= served, f"EncounterPanel reads `{name}` keys the payload never sends: {sorted(read - served)}"


# -- the phone block (v0.22.0 T10, spec §17.3) --------------------------------------------

from tests.social_fixtures import matched, receipts_active, receipts_state  # noqa: E402,F401 -- the fixtures

#: Values the engine keeps per person that never leave the server (spec §17.3).
HIDDEN_PHONE_KEYS = {"warmth", "interest", "trust", "mood", "mood_until", "ghosted", "arc_point", "rev",
                     "regard_today", "regard_day", "rng_n", "chemistry", "selectivity", "archetype",
                     # A game's undrawn tiles and both racks (T22): the payload shows the player's own rack
                     # (`rack`) and the bag's count (`bag_left`), never these.
                     "bag", "racks",
                     # This or That's picks (T23): the payload shows the player's own (`mine`) and theirs
                     # (`theirs`) only once the reveal has ended the game, never this.
                     "picks",
                     # A meet-up's flake, drawn when it is agreed and shown only at its start, and its
                     # quality (T24): the calendar shows the status and, once done, the band.
                     "flake", "quality"}


def _keys(tree: Any) -> set[str]:
    """Every dict key at any depth."""
    if isinstance(tree, dict):
        return set(tree) | {k for v in tree.values() for k in _keys(v)}
    if isinstance(tree, list):
        return {k for v in tree for k in _keys(v)}
    return set()


def test_the_phone_block_carries_no_hidden_key(receipts_state, matched) -> None:
    """A match, a due message and a request in state: no hidden key at any depth of `phone`, nor of a thread row."""
    from engine.social import messaging, payload, relationships
    from tests.social_fixtures import _force_stage

    state = receipts_state
    thread = matched("matchstick")
    pid = state.social["threads"][thread]["pid"]
    messaging.new_message(state, thread, pid, "text", voiced=False, decision={"situation": "reply"})
    _force_stage(state, pid, "talking")
    asked = relationships.ask(state, thread, "number")
    assert asked["ok"], asked
    assert state.social["people"][pid].get("warmth") is not None   # the slice holds them: the scan is not empty-handed
    assert messaging.open_thread(state, thread)["ok"]                # so message rows are scanned too
    block = payload.phone_block(state)
    assert block["threads"] and block["requests"] and block["open_thread"]["messages"]
    leaked = _keys(block) & HIDDEN_PHONE_KEYS
    assert not leaked, f"hidden keys in the phone block: {sorted(leaked)}"
    row = payload.thread_row(state, thread)
    assert row is not None and not (_keys(row) & HIDDEN_PHONE_KEYS)
    assert block["apps"] and all("badge" in a for a in block["apps"])


def test_the_phone_block_says_what_a_thread_can_attach(receipts_state) -> None:
    """T28 (spec §18.2, §13.7): each app row carries its apps.yaml `capabilities` (the compose bar's
    attachments), and `player` its camera roll with labels and the `player_subjects` it may send."""
    from engine import social
    from engine.social import media, payload

    block = payload.phone_block(receipts_state)
    declared = social.data("apps")["apps"]
    for row in block["apps"]:
        assert row["capabilities"] == [str(c) for c in declared[row["id"]].get("capabilities") or ()]
    caps = {row["id"]: row["capabilities"] for row in block["apps"]}
    assert "voice" not in caps["texts"] and "photo" in caps["texts"] and "video" in caps["natter"]
    roll = block["player"]["camera_roll"]
    assert [r["id"] for r in roll] == media.player_photos(receipts_state) and roll
    assert all(r["label"] and r["label"] != r["id"] for r in roll)
    subjects = block["player"]["subjects"]
    assert [s["id"] for s in subjects] == [r["id"] for r in media.player_subjects()]
    assert all(set(s) == {"id", "kinds", "label"} for s in subjects)
    assert not (_keys(block) & HIDDEN_PHONE_KEYS)


def test_a_fault_in_what_the_player_may_attach_costs_only_that_field(receipts_state, monkeypatch) -> None:
    """T28 review M2: `player.subjects` and `player.camera_roll` are fenced like sections."""
    from engine.social import media, payload

    def boom(*_a, **_k):
        raise RuntimeError("subjects unreadable")

    monkeypatch.setattr(media, "player_subjects", boom)
    block = payload.phone_block(receipts_state)
    assert block["player"]["subjects"] == [] and block["player"]["camera_roll"]
    assert block["player"]["name"] and block["threads"] is not None


def test_a_game_never_shows_their_rack_or_the_bag(receipts_state, matched) -> None:
    """T22 (spec §21.1): a Tile Talk game in state, their move made: no hidden key in `phone`, and no
    game entry carries a rack but the player's own."""
    from engine.game import clock
    from engine.social import payload
    from tests.social_fixtures import _act, _force_stage

    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    _force_stage(state, pid, "talking")
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    assert _act(state, "game_move", target=gid, args={"move": "pass"})["success"]
    due = [e for e in state.social["queue"] if e["kind"] == "game_move"][0]
    clock.advance_time(state, due["at"] - state.world_clock_hours + 1 / 60)
    row = state.social["games"][gid]
    assert row["racks"]["them"] and row["bag"]                       # the state holds them: the scan is not empty-handed
    block = payload.phone_block(state)
    leaked = _keys(block) & HIDDEN_PHONE_KEYS
    assert not leaked, f"hidden keys in the phone block: {sorted(leaked)}"
    (game,) = block["games"]
    assert game["rack"] == row["racks"]["player"] and game["bag_left"] == len(row["bag"])
    assert all(set(m) <= {"by", "kind", "words", "score", "at", "swapped"} for m in game["moves"])


def test_this_or_that_never_shows_their_picks_before_the_reveal(receipts_state, matched) -> None:
    """T23 (spec §21.2): a This or That game with both sides' picks in state and the reveal not yet run:
    no hidden key in `phone`, and their picks appear nowhere in the game's entry; after the reveal they do."""
    from engine.game.effects import apply_effect
    from engine.social import payload
    from engine.social.games import this_or_that
    from tests.social_fixtures import _act, _force_stage

    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    _force_stage(state, pid, "talking")
    gid = _act(state, "game_invite", target=pid, args={"game": "this_or_that"})["result"]["game_id"]
    assert _act(state, "game_move", target=gid, args={"move": "answer", "answers": ["a"] * 5})["success"]
    theirs = ["b", "b", "a", "b", "b"]
    assert apply_effect(state, {"type": "social_game", "op": "move", "game_id": gid, "by": "them",
                                "args": {"move": "answer", "answers": theirs}})["ok"]
    assert state.social["games"][gid]["picks"]["them"] == theirs   # the state holds them: the scan is not empty-handed
    block = payload.phone_block(state)
    leaked = _keys(block) & HIDDEN_PHONE_KEYS
    assert not leaked, f"hidden keys in the phone block: {sorted(leaked)}"
    (game,) = block["games"]
    assert game["mine"] == ["a"] * 5 and game["theirs"] is None and theirs not in game.values()
    assert all(set(m) <= {"by", "kind", "words", "score", "at", "swapped"} for m in game["moves"])
    assert this_or_that.reveal(state, gid)["ok"]
    (game,) = payload.phone_block(state)["games"]
    assert game["theirs"] == theirs and not (_keys(game) & HIDDEN_PHONE_KEYS)


def test_the_calendar_never_shows_a_flake_before_the_day(receipts_state, matched, monkeypatch) -> None:
    """T24 (spec §14.2): a meet-up agreed with its flake drawn true: the calendar shows it as `agreed`,
    with no hidden key at any depth of `phone`; at its start it shows `flaked`."""
    import dataclasses

    from engine.game import clock
    from engine.social import behaviour, messaging, payload, relationships
    from tests.social_fixtures import _act, _at, _force_stage, _set_person

    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    _force_stage(state, pid, "numbers")
    messaging.open_numbers(state, pid)
    _set_person(state, pid, **_at(relationships.gate_spec("meeting")))
    real = behaviour.archetype
    monkeypatch.setattr(behaviour, "archetype", lambda name: dataclasses.replace(real(name), flake_prob=1.0))
    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "free")
    made = _act(state, "propose_meet", target=pid, args={"venue": "copper_kettle", "day": 1, "slot": "afternoon"})
    assert made["success"] and made["result"]["answer"] == "accept", made
    mid = made["result"]["meet_id"]
    assert state.social["meets"][mid]["flake"] is True                 # the state holds it: the scan is not empty-handed
    block = payload.phone_block(state)
    (row,) = block["calendar"]
    assert row["id"] == mid and row["status"] == "agreed"
    leaked = _keys(block) & HIDDEN_PHONE_KEYS
    assert not leaked, f"hidden keys in the phone block: {sorted(leaked)}"
    clock.advance_time(state, state.social["meets"][mid]["start"] - state.world_clock_hours + 1 / 60)
    assert payload.phone_block(state)["calendar"][0]["status"] == "flaked"


def test_the_contact_card_and_photos_sections_carry_no_hidden_key(receipts_state, matched) -> None:
    """T29 (spec §18.2): the contact card's `contacts`, the Photos app's `gallery` and the planner's
    `meet_options`, with a person whose slice holds every hidden value, their canon AND what they know of
    the player in state: no hidden key at any depth, and `knows` (theirs about the player) nowhere."""
    from engine.social import media, memory, messaging, payload
    from tests.social_fixtures import _force_stage

    state = receipts_state
    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    _force_stage(state, pid, "numbers")
    messaging.open_numbers(state, pid)
    memory.add_canon(state, pid, ["I swim every morning"])
    memory.add_knows(state, pid, ["zz-knows-sentinel"])
    natter = f"natter:{pid}"
    photo = messaging.new_message(state, natter, pid, "photo", bubbles=["look"], voiced=True)
    media.mark_procedural(state, media.attach(state, pid, natter, photo["id"], "photo", "selfie_now"))
    person = state.social["people"][pid]
    assert person.get("warmth") is not None and person.get("knows")   # the slice holds them: the scan is not empty-handed
    block = payload.phone_block(state)
    assert block["contacts"] and block["gallery"] and block["meet_options"]["venues"]
    for name in ("contacts", "gallery", "meet_options", "settings"):
        leaked = _keys(block[name]) & (HIDDEN_PHONE_KEYS | {"knows", "canon", "seed", "subject", "prompt_id"})
        assert not leaked, f"hidden keys in {name}: {sorted(leaked)}"
    assert "zz-knows-sentinel" not in repr(block)


def test_let_time_pass_is_offered_in_local_mode_only(receipts_state, monkeypatch) -> None:
    """T29 (spec §15.1): the payload's `auto_wait` says whether the client may offer "Let time pass" -- the
    preference itself is the client's -- true locally and false hosted; `settings` carries Natter's
    receipts switch as the Settings app shows it, and the bio's cap (`social.max_text_chars`, review M10)."""
    import engine.config
    from engine.social import payload
    from tests.social_fixtures import _act

    block = payload.phone_block(receipts_state)
    from engine import social

    cap = int(social.setting("max_text_chars", 0))
    assert cap > 0
    assert block["auto_wait"] is True and block["settings"] == {"receipts": True, "bio_max": cap}
    assert _act(receipts_state, "set_receipts", target="natter", args={"to": "off"})["success"]
    assert payload.phone_block(receipts_state)["settings"] == {"receipts": False, "bio_max": cap}
    monkeypatch.setattr(engine.config, "hosting_enabled", lambda: True)
    assert payload.phone_block(receipts_state)["auto_wait"] is False


def test_the_phone_message_push_carries_no_hidden_key(receipts_active) -> None:
    """T14 (spec §17.3): `phone_message`, built from a committed reply -- a warm one, so regard moved -- carries
    no hidden key at any depth (`media_ready` is scanned below)."""
    from engine.social import voicer
    from tests.social_fixtures import _live_session, _matched_in, _phone, _replies_forced
    from tests.social_stub import StubVoice

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    with _replies_forced():                    # their reply drawn, never a ghost (T26's tuning: F16)
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text="hey you")
        _phone(scene, session, "wait", args={"until": "next"})
    pushed: list[dict[str, Any]] = []
    voicer.set_emitter(lambda _sid, event, body: pushed.append(body) if event == "phone_message" else None)
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=StubVoice("warm"), admit=False) == "ok"
    assert pushed and pushed[0]["message"]["bubbles"]                     # the scan is not empty-handed
    pid = thread.split(":")[1]
    assert session.engine.state.social["people"][pid].get("warmth") is not None
    leaked = _keys(pushed) & HIDDEN_PHONE_KEYS
    assert not leaked, f"hidden keys in phone_message: {sorted(leaked)}"


def test_the_media_ready_push_carries_no_hidden_key(receipts_active) -> None:
    """T19 (spec §17.3): `media_ready` -- `{message_id, mid, url, poster_url, kind, thread}`, the thread row built
    with the session -- carries no hidden key at any depth, after regard moved; nor does a message's `media` view."""
    import dataclasses

    from engine.media.comfy import storage
    from engine.media.comfy.jobs import JobResult, JobSpec
    from engine.session.store import release_turn
    from engine.social import media, messaging, voicer
    from tests.social_fixtures import _force_stage, _live_session, _matched_in, _set_person

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    state = session.engine.state
    assert session.lock.acquire(blocking=False)
    try:
        _force_stage(state, pid, "numbers")
        messaging.open_numbers(state, pid)
        _set_person(state, pid, warmth=70, trust=60, mood="fond")
        natter = f"natter:{pid}"
        message = messaging.new_message(state, natter, pid, "photo", bubbles=["look"], voiced=True,
                                        decision=dataclasses.asdict(media.send_decision("photo", "selfie_now")))
        mid = media.attach(state, pid, natter, message["id"], "photo", "selfie_now")
        media.mark_submitted(state, mid, {"positive": "x"}, account=session.owner, provider="stub")
    finally:
        release_turn(session)
    pushed: list[dict[str, Any]] = []
    voicer.set_emitter(lambda _sid, event, body: pushed.append(body) if event == "media_ready" else None)
    spec = JobSpec(mid=mid, kind="image", owner=session.owner, save_id=session.save_id, session_id=session.session_id,
                   epoch=session.epoch, workflow="photo", values={}, priority=0, account=session.owner)
    media.hand_off(spec, JobResult(mid, "ready", url=storage.url_for(session.save_id, f"{mid}.png"), kind="image"))
    assert pushed and pushed[0]["thread"]["thread_id"] == natter       # the scan is not empty-handed
    assert state.social["people"][pid].get("warmth") is not None
    leaked = _keys(pushed) & HIDDEN_PHONE_KEYS
    assert not leaked, f"hidden keys in media_ready: {sorted(leaked)}"
    view = messaging.message_view(state, state.social["threads"][natter], message)
    assert view["media"]["status"] == "ready" and not (_keys(view) & (HIDDEN_PHONE_KEYS | {"seed", "request", "account"}))

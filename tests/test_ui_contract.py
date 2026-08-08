"""
UI build and socket-contract tests.

The audit's single largest finding was drift between what the server sends and
what the client consumes: the server emitted `dice_result` and `cutscene_start`
to no listener, while the client listened for `narration_delta` that nothing
emitted. These tests make that drift fail the build.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "content" / "scenes" / "clockwork" / "static" / "dist"
TEMPLATE = ROOT / "content" / "scenes" / "clockwork" / "templates" / "clockwork.html"
UI_SRC = ROOT / "ui" / "src"

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


# -- socket contract -----------------------------------------------------


def _server_events(pattern: str) -> set[str]:
    """Event names the server passes to an emit call."""
    found: set[str] = set()
    for path in (ROOT / "content").rglob("*.py"):
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

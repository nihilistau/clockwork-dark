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

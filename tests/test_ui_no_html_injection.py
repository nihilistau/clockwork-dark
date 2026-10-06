"""
The game's client injects no HTML (v0.20.0 T14, spec §14.7).

The admin panel shares the game's origin (``/admin`` on the front door), so
script running on a game page could read it. Its real protection is that
nothing under ``ui/src`` turns text into markup: no ``innerHTML``,
``outerHTML``, ``insertAdjacentHTML``, ``dangerouslySetInnerHTML`` or
``document.write``, so neither model output nor a player's text can become
script on that origin. This static scan keeps it true until v0.21.0's client
overhaul, which must keep it or move the panel.

The canary: a stand-in source file under ``tmp_path`` that uses one is caught
by the same scanner.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"

#: The sinks that turn a string into markup (or script).
SINKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "dangerouslySetInnerHTML",
    "document.write",
    "document.writeln",
)

#: Every source a build reads.
SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".html", ".vue", ".svelte"}

_SINK_RE = re.compile(r"\b(?:" + "|".join(re.escape(sink) for sink in SINKS) + r")\b")


def scan(root: Path) -> list[str]:
    """``path:line: sink`` for every use of an HTML sink in a source under ``root``."""
    found: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in SUFFIXES):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            for match in _SINK_RE.finditer(line):
                found.append(f"{path.relative_to(root)}:{number}: {match.group(0)}")
    return found


def test_ui_src_uses_no_html_sink() -> None:
    assert UI_SRC.is_dir()
    sources = [p for p in UI_SRC.rglob("*") if p.is_file() and p.suffix in SUFFIXES]
    assert len(sources) > 20, "the scan found too few sources to mean anything"
    assert scan(UI_SRC) == []


def test_the_canary_a_stand_in_source_with_a_sink_is_caught(tmp_path: Path) -> None:
    for index, sink in enumerate(SINKS):
        source = tmp_path / f"Panel{index}.jsx"
        source.write_text(
            "export function Panel({ text }) {\n"
            f"  const node = document.body; // {sink} below\n"
            "  return null;\n"
            "}\n",
            encoding="utf-8",
        )
    found = scan(tmp_path)
    assert len(found) == len(SINKS), found
    assert {line.rsplit(": ", 1)[1] for line in found} == set(SINKS)


def test_the_panel_s_own_script_writes_text_only() -> None:
    """The admin panel's refresh script, under the same rule."""
    script = REPO / "engine" / "hosting" / "admin" / "static"
    assert scan(script) == []

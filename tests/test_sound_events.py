"""The engine's events, one table in Python and JS (v0.24.0 spec §5); each plugin's soundEvents declared."""

from __future__ import annotations

import re
from pathlib import Path

from engine.games import registry, sounds

UI = Path(__file__).resolve().parents[1] / "ui" / "src"


def _js_list(text: str, name: str) -> list[str]:
    """`name = [...]`, `name: [...]` or either through `Object.freeze(...)` (pre-flight F3)."""
    match = re.search(rf"{name}\s*[:=]\s*(?:Object\.freeze\()?\[(.*?)\]", text, re.S)
    assert match, f"no {name} list"
    return re.findall(r'"([^"]+)"', match.group(1))


def plugin_sound_events(plugin_dir: Path) -> list[str]:
    """A plugin's `soundEvents`: a literal list in index.jsx, or a bare identifier (`soundEvents: SOUND_EVENTS`)
    followed to the plugin's own `sounds.js` (READ RECEIPTS keeps its one list there)."""
    text = (plugin_dir / "index.jsx").read_text(encoding="utf-8")
    if "soundEvents" not in text:
        return []
    named = re.search(r"soundEvents\s*:\s*([A-Z_][A-Z0-9_]*)\b", text)
    if named:
        return _js_list((plugin_dir / "sounds.js").read_text(encoding="utf-8"), named.group(1))
    return _js_list(text, "soundEvents")


def test_the_engine_events_are_one_table() -> None:
    text = (UI / "core" / "sound" / "events.js").read_text(encoding="utf-8")
    assert tuple(_js_list(text, "ENGINE_EVENTS")) == sounds.ENGINE_EVENTS


def test_each_plugins_sound_events_are_its_storys() -> None:
    """Story -> plugin through ui.plugin (a plugin is not a story, review M11). A plugin's events must be declared
    by the story whose OWN plugin it is; a story borrowing a plugin need not declare them."""
    for slug, manifest in sorted(registry.discover().items()):
        plugin = manifest.ui_plugin or slug
        if plugin != slug:
            continue                                          # a borrower
        plugin_dir = UI / "stories" / plugin
        if not plugin_dir.is_dir():
            continue                                          # a story with no plugin of its own uses _engine
        assert (plugin_dir / "index.jsx").is_file(), f"{plugin}: a plugin directory with no index.jsx"
        events = plugin_sound_events(plugin_dir)
        story = sounds.load_story(manifest)
        declared = set((story or {}).get("data", {}).get("events") or {})
        assert set(events) == declared, (slug, sorted(set(events) ^ declared))


def test_an_undeclared_plugin_event_is_caught(tmp_path) -> None:
    """The canary (pre-flight F3): a plugin listing an event its story does not declare is read and differs."""
    plugin = tmp_path / "probe"
    plugin.mkdir()
    (plugin / "index.jsx").write_text('export default { slug: "probe", soundEvents: ["probe.extra"] };', encoding="utf-8")
    assert plugin_sound_events(plugin) == ["probe.extra"]
    (plugin / "index.jsx").write_text('export default { soundEvents: SOUND_EVENTS };', encoding="utf-8")
    (plugin / "sounds.js").write_text('export const SOUND_EVENTS = Object.freeze(["a.b", "c.d"]);', encoding="utf-8")
    assert plugin_sound_events(plugin) == ["a.b", "c.d"]

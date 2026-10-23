"""The sound data: loader, validator and merge (v0.24.0 spec §3-§5).

Sound is client-side data. This module reads the engine's ``sounds.yaml`` (``sound.root``) and a story's
(``paths.sounds``), checks them against the §4.4 list, and merges them for the audition page and the client.
It never plays, synthesises or writes anything: the browser makes the sound, the server only serves the data
and the files.
"""

from __future__ import annotations

import copy
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine import yamlio
from engine.config import get_config, project_root
from engine.names import is_portable_name

ENGINE_SCOPE = "_engine"
ENGINE_EVENTS: tuple[str, ...] = (
    "ui.press", "ui.toggle", "ui.open", "ui.close", "choice.pick", "choice.send", "turn.arrive",
    "roll.cast", "roll.crit_success", "roll.success", "roll.partial", "roll.failure", "roll.crit_failure",
    "alert.error", "link.lost", "link.back", "game.begin", "game.save", "game.ending", "cutscene.start",
    "encounter.start", "panel.wanted", "panel.job", "panel.casing", "plate.reveal",
)
ENGINE_FAMILIES: tuple[str, ...] = ("ui.", "choice.", "turn.", "roll.", "alert.", "link.", "game.", "cutscene.",
                                    "encounter.", "panel.", "plate.")
CATEGORIES: tuple[str, ...] = ("ui", "game", "alert", "phone", "world")
WAVES: tuple[str, ...] = ("sine", "square", "triangle", "sawtooth", "noise")
FILTERS: tuple[str, ...] = ("lowpass", "highpass", "bandpass")
NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
NOTE = re.compile(r"^([A-G])([#b]?)([0-8])$")
MAX_MS = 4000
TOP_ENGINE = frozenset({"version", "limits", "sounds", "bind"})
TOP_STORY = frozenset({"version", "events", "sounds", "bind"})
LIMIT_KEYS = frozenset({"voices", "throttle_ms", "roll_degree_delay_ms"})
SOUND_KEYS = frozenset({"category", "label", "gain", "throttle_ms", "essential", "note", "synth", "file", "rate",
                        "start_ms", "fallback"})
SYNTH_KEYS = frozenset({"layers", "sequence", "repeat", "jitter_cents"})
LAYER_KEYS = frozenset({"wave", "freq", "to", "glide_ms", "detune", "start_ms", "attack_ms", "decay_ms", "sustain",
                        "hold_ms", "release_ms", "gain", "filter", "tremolo"})
FILTER_KEYS = frozenset({"type", "freq", "q", "to", "glide_ms"})
TREMOLO_KEYS = frozenset({"rate_hz", "depth"})
SEQUENCE_KEYS = frozenset({"voice", "notes"})
REPEAT_KEYS = frozenset({"times", "gap_ms"})
EVENT_KEYS = frozenset({"label"})


class SoundError(ValueError):
    """A fault in a sounds.yaml: ``<file>: <key>: <message>``, with the three parts kept as attributes."""

    def __init__(self, file: str, key: str, message: str) -> None:
        super().__init__(f"{file}: {key}: {message}")
        self.file = file
        self.key = key
        self.message = message


def _fault(where: str, key: str, message: str) -> SoundError:
    return SoundError(where, key, message)


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _range(where: str, key: str, value: Any, low: float, high: float) -> float:
    if not _num(value) or not low <= float(value) <= high:
        raise _fault(where, key, f"must be a number from {low:g} to {high:g}")
    return float(value)


def _keys(where: str, key: str, row: Any, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise _fault(where, key, "must be a mapping")
    for extra in sorted(set(row) - allowed):
        raise _fault(where, f"{key}.{extra}" if key else extra, "is not a key here")
    return row


def exists_exact(root: Path, rel: str) -> bool:
    """`rel` (a '/' path) names a file under `root` with EXACTLY that case: each part is in its parent's listing.
    `Path.exists()` is case-blind on Windows and would pass a name that 404s on Linux (rule 11)."""
    here = Path(root)
    parts = rel.split("/")
    for part in parts:
        try:
            names = os.listdir(here)
        except OSError:
            return False
        if part not in names:
            return False
        here = here / part
    return here.is_file()


def _layer_ms(layer: dict[str, Any]) -> float:
    return sum(float(layer.get(k, 0) or 0) for k in ("start_ms", "attack_ms", "decay_ms", "hold_ms")) + float(
        layer.get("release_ms", 20) or 0)


def _check_layer(where: str, key: str, layer: Any, *, voice: bool = False) -> None:
    _keys(where, key, layer, LAYER_KEYS - ({"freq", "to", "glide_ms"} if voice else frozenset()))
    wave = layer.get("wave")
    if wave not in WAVES:
        raise _fault(where, f"{key}.wave", f"must be one of {', '.join(WAVES)}")
    if not voice and wave != "noise":
        _range(where, f"{key}.freq", layer.get("freq"), 20, 16000)
    if "to" in layer:
        _range(where, f"{key}.to", layer["to"], 20, 16000)
    for name in ("glide_ms", "start_ms", "attack_ms", "decay_ms", "hold_ms", "release_ms"):
        if name in layer:
            _range(where, f"{key}.{name}", layer[name], 0, MAX_MS)
    for name, high in (("gain", 1), ("sustain", 1)):
        if name in layer:
            _range(where, f"{key}.{name}", layer[name], 0, high)
    if "detune" in layer:
        _range(where, f"{key}.detune", layer["detune"], -1200, 1200)
    if "filter" in layer:
        flt = _keys(where, f"{key}.filter", layer["filter"], FILTER_KEYS)
        if flt.get("type") not in FILTERS:
            raise _fault(where, f"{key}.filter.type", f"must be one of {', '.join(FILTERS)}")
        _range(where, f"{key}.filter.freq", flt.get("freq"), 20, 16000)
        for name, low, high in (("q", 0.0001, 30), ("to", 20, 16000), ("glide_ms", 0, MAX_MS)):
            if name in flt:
                _range(where, f"{key}.filter.{name}", flt[name], low, high)
    if "tremolo" in layer:
        trem = _keys(where, f"{key}.tremolo", layer["tremolo"], TREMOLO_KEYS)
        _range(where, f"{key}.tremolo.rate_hz", trem.get("rate_hz"), 1, 60)
        _range(where, f"{key}.tremolo.depth", trem.get("depth"), 0, 1)


def _check_synth(where: str, key: str, synth: Any) -> None:
    _keys(where, key, synth, SYNTH_KEYS)
    if ("layers" in synth) == ("sequence" in synth):
        raise _fault(where, key, "needs exactly one of layers and sequence")
    total = 0.0
    if "layers" in synth:
        layers = synth["layers"]
        if not isinstance(layers, list) or not 1 <= len(layers) <= 6:
            raise _fault(where, f"{key}.layers", "must list 1 to 6 layers")
        for i, layer in enumerate(layers):
            _check_layer(where, f"{key}.layers.{i}", layer)
        total = max(_layer_ms(layer) for layer in layers)
    else:
        seq = _keys(where, f"{key}.sequence", synth["sequence"], SEQUENCE_KEYS)
        _check_layer(where, f"{key}.sequence.voice", seq.get("voice"), voice=True)
        notes = seq.get("notes")
        if not isinstance(notes, list) or not 1 <= len(notes) <= 32:
            raise _fault(where, f"{key}.sequence.notes", "must list 1 to 32 notes")
        for i, note in enumerate(notes):
            ok = (isinstance(note, list) and len(note) == 3 and _num(note[0]) and _num(note[2])
                  and ((_num(note[1]) and 20 <= float(note[1]) <= 16000) or (isinstance(note[1], str) and NOTE.match(note[1]))))
            if not ok:
                raise _fault(where, f"{key}.sequence.notes.{i}", "must be [at_ms, Hz or a note name, length_ms]")
            total = max(total, float(note[0]) + float(note[2]) + float(seq["voice"].get("release_ms", 20) or 0))
    if "repeat" in synth:
        rep = _keys(where, f"{key}.repeat", synth["repeat"], REPEAT_KEYS)
        times = rep.get("times")
        if not isinstance(times, int) or isinstance(times, bool) or not 1 <= times <= 4:
            raise _fault(where, f"{key}.repeat.times", "must be a whole number from 1 to 4")
        gap = _range(where, f"{key}.repeat.gap_ms", rep.get("gap_ms", 0), 0, MAX_MS)
        total = total * times + gap * (times - 1)
    if "jitter_cents" in synth:
        _range(where, f"{key}.jitter_cents", synth["jitter_cents"], 0, 100)
    if total > MAX_MS:
        raise _fault(where, key, f"lasts {total:.0f} ms, over {MAX_MS}")


def _check_file(where: str, key: str, path: Any, root: Path, engine_root: Optional[Path]) -> None:
    if not isinstance(path, str):
        raise _fault(where, key, "must be a path string")
    base, rel = (engine_root, path[len("engine:"):]) if path.startswith("engine:") else (root, path)
    parts = rel.split("/")
    if (base is None or "\\" in rel or rel.startswith("/") or any(p in ("", ".", "..") for p in parts)
            or rel != rel.lower() or not rel.endswith(".ogg") or not all(is_portable_name(p) for p in parts)):
        raise _fault(where, key, "must be a lower-case, portable .ogg path inside its sounds directory")
    if not exists_exact(base, rel):
        raise _fault(where, key, f"no file {rel!r} with exactly that case")


def _check_sound(where: str, sid: str, row: Any, root: Path, engine_root: Optional[Path]) -> None:
    key = f"sounds.{sid}"
    if not NAME.match(sid):
        raise _fault(where, key, "is not a dotted lower-case id")
    _keys(where, key, row, SOUND_KEYS)
    if row.get("category") not in CATEGORIES:
        raise _fault(where, f"{key}.category", f"must be one of {', '.join(CATEGORIES)}")
    if not isinstance(row.get("label"), str) or not row["label"].strip():
        raise _fault(where, f"{key}.label", "is required: the audition page's words")
    if ("synth" in row) == ("file" in row):
        raise _fault(where, key, "needs exactly one of synth and file")
    for name, low, high in (("gain", 0, 1), ("throttle_ms", 0, 10000), ("rate", 0.5, 2), ("start_ms", 0, MAX_MS)):
        if name in row:
            _range(where, f"{key}.{name}", row[name], low, high)
    if "synth" in row:
        _check_synth(where, f"{key}.synth", row["synth"])
        return
    _check_file(where, f"{key}.file", row["file"], root, engine_root)
    if "fallback" not in row:
        raise _fault(where, f"{key}.fallback", "every file sound needs a synth fallback (spec §4.2)")
    _check_synth(where, f"{key}.fallback", row["fallback"])


def check(data: Any, *, where: str, root: Path, story: bool, engine_sounds: Optional[dict[str, Any]] = None,
          engine_root: Optional[Path] = None) -> None:
    """Every §4.4 fault, raised as `SoundError` naming the file and the key."""
    _keys(where, "", data, TOP_STORY if story else TOP_ENGINE)
    if data.get("version") != 1:
        raise _fault(where, "version", "must be 1")
    if not story:
        _keys(where, "limits", data.get("limits") or {}, LIMIT_KEYS)
    own = data.get("sounds") or {}
    if not isinstance(own, dict):
        raise _fault(where, "sounds", "must be a mapping")
    for sid, row in own.items():
        _check_sound(where, str(sid), row, root, root if not story else engine_root)
    known = {**(engine_sounds or {}), **own}
    events = data.get("events") or {}
    if not isinstance(events, dict):
        raise _fault(where, "events", "must be a mapping")
    if story:
        for name, row in events.items():
            if not NAME.match(str(name)) or str(name).startswith(ENGINE_FAMILIES):
                raise _fault(where, f"events.{name}", "must be a dotted id outside the engine's families")
            _keys(where, f"events.{name}", row, EVENT_KEYS)
    bind = data.get("bind") or {}
    if not isinstance(bind, dict):
        raise _fault(where, "bind", "must be a mapping")
    allowed = set(ENGINE_EVENTS) | {str(e) for e in events}
    for event, value in bind.items():
        if str(event) not in allowed:
            raise _fault(where, f"bind.{event}", "is neither an engine event nor declared in events:")
        _check_binding(where, f"bind.{event}", value, known)
    bound = {str(e) for e in bind}
    for event in ([str(e) for e in events] if story else ENGINE_EVENTS):
        if event not in bound:
            raise _fault(where, f"bind.{event}", "is declared and never bound")


def _is_known(name: Any, known: dict[str, Any]) -> bool:
    return isinstance(name, str) and name in known


def _check_binding(where: str, key: str, value: Any, known: dict[str, Any]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if not _is_known(value, known):
            raise _fault(where, key, f"names no sound {value!r}")
        return
    row = _keys(where, key, value, frozenset({"default", "choices"}))
    choices = row.get("choices")
    default = row.get("default")
    if not _is_known(default, known) or not isinstance(choices, list) or default not in choices:
        raise _fault(where, key, "needs a known default listed in its choices")
    category = known[row["default"]].get("category")
    for choice in choices:
        if not _is_known(choice, known) or known[choice].get("category") != category:
            raise _fault(where, f"{key}.choices", f"{choice!r} is unknown or of another category")


def _engine_rel() -> str:
    """The engine's sounds directory as the config names it (`sound.root`): the label in every message."""
    return str(get_config().get("sound.root")).strip("/")


def engine_root() -> Path:
    return project_root() / _engine_rel()


def _engine_label() -> str:
    return f"{_engine_rel()}/sounds.yaml"


@lru_cache(maxsize=32)
def _load_file(path: str, mtime: float, where: str, scope: str, engine_key: Optional[tuple[str, float]]) -> dict[str, Any]:
    """One sounds.yaml, parsed AND checked once; keyed on (path, mtime) and, for a story, the engine file's, so an
    edit is seen (spec §3, review M1). The result is shared: callers go through `load_engine` / `load_story`
    (a deep copy) or `merge` (a fresh dict), and never mutate it."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = yamlio.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise _fault(where, "yaml", f"is not valid YAML: {exc}") from exc
    root = Path(path).parent
    if engine_key is None:
        check(data, where=where, root=root, story=False)
    else:
        engine_dir = Path(engine_key[0])
        engine = _load_file(str(engine_dir / "sounds.yaml"), engine_key[1], _engine_label(), ENGINE_SCOPE, None)
        check(data, where=where, root=root, story=True, engine_sounds=engine["data"]["sounds"],
              engine_root=engine_dir)
    return {"data": data, "root": root, "scope": scope, "file": where}


def _engine_entry() -> dict[str, Any]:
    path = engine_root() / "sounds.yaml"
    return _load_file(str(path), path.stat().st_mtime, _engine_label(), ENGINE_SCOPE, None)


def _story_entry(manifest: Any) -> Optional[dict[str, Any]]:
    rel = (manifest.paths or {}).get("sounds") if manifest is not None else None
    if not rel:
        return None
    path = manifest.resolve(rel) / "sounds.yaml"
    engine_path = engine_root() / "sounds.yaml"
    return _load_file(str(path), path.stat().st_mtime, f"{str(rel).rstrip('/')}/sounds.yaml", manifest.slug,
                      (str(engine_path.parent), engine_path.stat().st_mtime))


def load_engine() -> dict[str, Any]:
    """The engine's sounds.yaml, checked; a private copy the caller may change."""
    return copy.deepcopy(_engine_entry())


def load_story(manifest: Any) -> Optional[dict[str, Any]]:
    """The story's `paths.sounds`, checked against the engine's set; None when it declares none. A private copy."""
    return copy.deepcopy(_story_entry(manifest))


def merge(engine: dict[str, Any], story: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Engine sounds, then the story's by id; engine binds, then the story's (spec §4.3). Each row gains `scope`,
    `key` (the audition page's data key) and `overrides`. Everything returned is freshly built (deep-copied)."""
    out_sounds: dict[str, Any] = {}
    for src in (engine, story):
        if not src:
            continue
        for sid, row in (src["data"].get("sounds") or {}).items():
            out_sounds[sid] = {**copy.deepcopy(row), "scope": src["scope"], "key": f"{src['file']} › sounds › {sid}",
                               "overrides": src is story and sid in (engine["data"].get("sounds") or {})}
    bind = copy.deepcopy({**(engine["data"].get("bind") or {}), **((story or {}).get("data", {}).get("bind") or {})})
    events = list(ENGINE_EVENTS) + [e for e in ((story or {}).get("data", {}).get("events") or {})]
    return {"limits": copy.deepcopy(engine["data"].get("limits") or {}), "events": events, "sounds": out_sounds,
            "bind": bind}


def merged(manifest: Any) -> dict[str, Any]:
    """The merged set for the client: each file is checked once per edit, and the result is the caller's own."""
    return merge(_engine_entry(), _story_entry(manifest))


def warm() -> None:
    """The WARMERS entry: the engine file and the active story's, parsed once at hosted start. `peek()` never
    activates a story (`None` loads the engine set alone), and nothing is swallowed: a broken sounds.yaml fails
    hosted start like any other content, as `caches.warm_all_caches` requires (pre-flight F16)."""
    from engine.games import registry

    merged(registry.peek())

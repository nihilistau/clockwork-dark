"""
Settings HTTP API
=================

    GET  /api/settings    every player-settable knob, its live value, its state
    POST /api/settings    persist whitelisted changes into config/local.yaml

THE GAP THIS CLOSES: config/default.yaml carries ~25 knobs a player has a
legitimate opinion about -- whether narration is spoken, whether images are
generated during a turn, how fast the dark spreads -- and the only way to
touch any of them was to edit a checked-in YAML by hand. The Settings panel
shipped four localStorage toggles, none of which reached the engine.

The whitelist below is the entire contract. A key not named here cannot be
written by any request, so a malicious or malformed body cannot repoint
`paths.saves`, disable the evil ticker's clamp, or inject a service command
line. Every value is type-checked and clamped to its declared domain before
it is written, and writes go to config/local.yaml -- gitignored, the layer
the config manager already documents as machine-local, and one that
engine/config.py ignores wholesale if it ever fails to parse.

WHY THIS IS SHARED AND NOT STORY-OWNED. Every key here describes the MACHINE
or the player's own taste -- endpoints, GPU budgets, whether a voice speaks.
That is the same test ``engine/games/manifest.SETTING_ALLOWLIST`` applies from
the other side: a story declares the numbers that describe its shape, and the
player owns the rest. The two lists deliberately overlap on the four pacing
keys (evil rate, tick interval, cutscene budget and skip window) -- the story
sets the default, this panel lets the player at it, and the manifest overlay
loses to config/local.yaml because local.yaml is the higher layer.

Wire it into a scene with one line in its ``register()``::

    from engine.api.settings import settings_blueprint
    app.register_blueprint(settings_blueprint())

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from engine.config import get_config

logger = logging.getLogger(__name__)

BLUEPRINT_NAME = "settings"

# type: bool | int | float | enum | text
SETTING_SPECS: tuple[dict[str, Any], ...] = (
    # -- pace ------------------------------------------------------------
    {
        "key": "world.evil_base_rate_per_day",
        "label": "How fast the dark spreads",
        "group": "Pace",
        "type": "float",
        "min": 0.001,
        "max": 0.02,
        "step": 0.001,
        "restart": False,
        "hint": (
            "The difficulty slider. 0.006 reaches CONSUMING near day 130; "
            "0.012 does it in half that; below 0.003 the world is still quiet "
            "at day 40 and the premise evaporates."
        ),
        "marks": {"0.003": "Slow", "0.006": "Measured", "0.012": "Hunted"},
    },
    {
        "key": "world.tick_interval_seconds",
        "label": "Background tick",
        "group": "Pace",
        "type": "int",
        "min": 15,
        "max": 600,
        "restart": True,
        "hint": "Real seconds between world simulation ticks.",
    },
    # -- voice -----------------------------------------------------------
    {
        "key": "tts.enabled",
        "label": "Speak the narration",
        "group": "Voice",
        "type": "bool",
        "restart": False,
        "hint": (
            "Off by default on measurement, not taste: this machine "
            "synthesizes about 21x slower than realtime, so a full paragraph "
            "costs minutes."
        ),
    },
    {
        "key": "tts.assistant_enabled",
        "label": "Speak the Assistant",
        "group": "Voice",
        "type": "bool",
        "restart": False,
        "hint": "Its lines are one to three sentences — the only speech worth waiting for.",
    },
    {
        "key": "tts.voice",
        "label": "Voice",
        "group": "Voice",
        "type": "enum",
        "options": ["neutral_male", "neutral_female", "warm_female", "old_male"],
        "restart": False,
        "hint": "Whatever your Voxtral build ships. An unknown name falls back to text.",
    },
    {
        "key": "tts.euler_steps",
        "label": "Synthesis quality",
        "group": "Voice",
        "type": "int",
        "min": 1,
        "max": 12,
        "restart": False,
        "hint": "Higher is better and much slower. 3 is the measured floor that still sounds human.",
    },
    # -- pictures --------------------------------------------------------
    {
        "key": "media.live_generation",
        "label": "Generate pictures during play",
        "group": "Pictures",
        "type": "bool",
        "restart": False,
        "hint": (
            "Off, the shipped art pack answers instantly. On, a turn waits for "
            "the provider — minutes on Grok, seconds on ComfyUI."
        ),
    },
    {
        "key": "media.image_provider",
        "label": "Picture provider",
        "group": "Pictures",
        "type": "enum",
        "options": ["grokbuild", "comfyui", "procedural"],
        "restart": False,
        "hint": "Only consulted when live generation is on.",
    },
    {
        "key": "media.cutscene_budget",
        "label": "Cutscene budget",
        "group": "Pictures",
        "type": "enum",
        "options": ["phase_shift_only", "unlimited"],
        "restart": True,
        "hint": "One cutscene per evil phase, or as many as the story asks for.",
    },
    {
        "key": "media.cutscene_skip_after_seconds",
        "label": "Skippable after",
        "group": "Pictures",
        "type": "int",
        "min": 0,
        "max": 60,
        "restart": False,
        "hint": "Seconds before a cutscene will let you out of it. 0 means immediately.",
    },
    # -- the companion ---------------------------------------------------
    {
        "key": "awareness.reveal_threshold",
        "label": "Awareness before it will speak plainly",
        "group": "The companion",
        "type": "int",
        "min": 0,
        "max": 100,
        "restart": False,
        "hint": "Below this the Assistant answers in weather and omens.",
    },
    {
        "key": "awareness.reflection_form_min",
        "label": "Awareness before the reflection",
        "group": "The companion",
        "type": "int",
        "min": 0,
        "max": 100,
        "restart": False,
        "hint": "The fifth form is gated: it cannot appear until you have seen enough.",
    },
    {
        "key": "awareness.spoiler_gate_threshold",
        "label": "Lore spoiler gate",
        "group": "The companion",
        "type": "int",
        "min": 0,
        "max": 100,
        "restart": False,
        "hint": "Lore above this awareness is withheld from the prompt entirely.",
    },
    {
        "key": "assistant.max_tokens",
        "label": "How much it may say",
        "group": "The companion",
        "type": "int",
        "min": 60,
        "max": 600,
        "restart": False,
        "hint": "Tokens per line. It is a presence, not a chat window.",
    },
    # -- the model -------------------------------------------------------
    {
        "key": "lmstudio.profiles.big.model",
        "label": "Narration model",
        "group": "The model",
        "type": "text",
        "maxlength": 120,
        "restart": True,
        "hint": "Empty means discover one by capability from LM Studio. Otherwise an exact model id.",
    },
    {
        "key": "lmstudio.profiles.big.temperature",
        "label": "Narration temperature",
        "group": "The model",
        "type": "float",
        "min": 0.0,
        "max": 2.0,
        "step": 0.05,
        "restart": False,
    },
    {
        "key": "lmstudio.profiles.big.max_tokens",
        "label": "Narration token cap",
        "group": "The model",
        "type": "int",
        "min": 512,
        "max": 8000,
        "restart": False,
        "hint": "Covers reasoning AND prose combined. Too low and thinking eats the whole answer.",
    },
    {
        "key": "lmstudio.profiles.big.reasoning",
        "label": "Let it think out loud",
        "group": "The model",
        "type": "enum",
        "options": ["on", "off"],
        "restart": False,
        "hint": "On feeds the live reasoning panel. Off is faster and blanker.",
    },
    {
        "key": "lmstudio.context_tokens",
        "label": "Context window",
        "group": "The model",
        "type": "int",
        "min": 2048,
        "max": 131072,
        "restart": True,
        "hint": "Fallback only — the real number comes from the loaded model.",
    },
    {
        "key": "lmstudio.prefer_native",
        "label": "Use LM Studio's native endpoint",
        "group": "The model",
        "type": "bool",
        "restart": True,
        "hint": "The only transport that can actually turn reasoning off. Leave on unless it misbehaves.",
    },
)

SETTINGS_BY_KEY: dict[str, dict[str, Any]] = {s["key"]: s for s in SETTING_SPECS}

_LOCAL_CONFIG = Path("config") / "local.yaml"


def _dig(node: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _plant(root: dict[str, Any], dotted: str, value: Any) -> None:
    """Set a dotted key, creating intermediate dicts. Never replaces a dict."""
    parts = dotted.split(".")
    node = root
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _local_overrides() -> dict[str, Any]:
    """Whatever config/local.yaml currently holds, or {} if it is absent or bad."""
    import yaml

    from engine.config import project_root

    path = project_root() / _LOCAL_CONFIG
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[settings] local.yaml unreadable: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def settings_view() -> dict[str, Any]:
    """Every player-settable knob, its live value, and whether it is overridden."""
    cfg = get_config()
    overrides = _local_overrides()
    rows: list[dict[str, Any]] = []
    for spec in SETTING_SPECS:
        row = dict(spec)
        row["value"] = cfg.get(spec["key"])
        row["overridden"] = _dig(overrides, spec["key"]) is not None
        rows.append(row)
    return {
        "settings": rows,
        # Order is presentation, but it is stable order: a settings panel whose
        # groups reshuffle between loads is unusable.
        "groups": list(dict.fromkeys(s["group"] for s in SETTING_SPECS)),
        "config_path": str(_LOCAL_CONFIG).replace("\\", "/"),
    }


def _coerce_setting(spec: dict[str, Any], raw: Any) -> tuple[bool, Any, str]:
    """
    Validate one value against its spec.

    Returns (accepted, value, note). A number outside its range is CLAMPED and
    accepted with a note rather than rejected: the point of the whitelist is
    that no reachable value can brick a run, so the safe move is to land on the
    nearest legal one, not to hand back an error the player cannot act on.
    """
    kind = spec["type"]
    try:
        if kind == "bool":
            if isinstance(raw, str):
                return True, raw.strip().lower() in ("1", "true", "yes", "on"), ""
            return True, bool(raw), ""
        if kind in ("int", "float"):
            value = int(raw) if kind == "int" else float(raw)
            if value != value or value in (float("inf"), float("-inf")):
                return False, None, "not a finite number"
            low, high = spec.get("min"), spec.get("max")
            clamped = value
            if low is not None:
                clamped = max(low, clamped)
            if high is not None:
                clamped = min(high, clamped)
            note = "" if clamped == value else f"clamped to {clamped}"
            return True, (int(clamped) if kind == "int" else round(float(clamped), 6)), note
        if kind == "enum":
            value = str(raw)
            if value not in spec.get("options", []):
                return False, None, f"not one of {', '.join(spec.get('options', []))}"
            return True, value, ""
        if kind == "text":
            value = str(raw).strip()[: int(spec.get("maxlength", 120))]
            # A model id is an identifier, never a path or a shell fragment.
            if any(c in value for c in "\n\r\t\\'\"$`;|&<>"):
                return False, None, "contains characters an identifier cannot have"
            return True, value, ""
    except (TypeError, ValueError):
        return False, None, f"not a valid {kind}"
    return False, None, "unknown setting type"


def apply_settings(changes: dict[str, Any], *, reset: bool = False) -> dict[str, Any]:
    """
    Merge validated changes into config/local.yaml and reload the config.

    Only whitelisted keys are ever touched, so machine-specific values already
    in local.yaml (service roots, API hosts) survive untouched. The file is
    written to a sibling temp path and moved into place, so a crash mid-write
    cannot leave a half-parsed config behind -- and even if one somehow did,
    engine/config.py logs and ignores an unparseable layer rather than dying.
    """
    import yaml

    from engine.config import project_root, reset_config

    overrides = _local_overrides()
    applied: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    notes: dict[str, str] = {}

    if reset:
        # Remove only OUR keys. Anything else in the file is somebody's machine.
        for key in SETTINGS_BY_KEY:
            parts = key.split(".")
            node = overrides
            for part in parts[:-1]:
                node = node.get(part) if isinstance(node.get(part), dict) else {}
            if isinstance(node, dict):
                node.pop(parts[-1], None)
    else:
        for key, raw in (changes or {}).items():
            spec = SETTINGS_BY_KEY.get(str(key))
            if spec is None:
                rejected[str(key)] = "not a settable key"
                continue
            ok, value, note = _coerce_setting(spec, raw)
            if not ok:
                rejected[str(key)] = note
                continue
            _plant(overrides, str(key), value)
            applied[str(key)] = value
            if note:
                notes[str(key)] = note

    path = project_root() / _LOCAL_CONFIG
    temp = path.with_suffix(".yaml.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(
                "# Machine-local config overrides. Gitignored.\n"
                "# The game's Settings panel writes the keys it owns here;\n"
                "# anything else in this file is yours and is left alone.\n\n"
            )
            yaml.safe_dump(overrides, handle, sort_keys=True, allow_unicode=True)
        temp.replace(path)
    except OSError as exc:
        logger.error("[settings] Could not write %s: %s", path, exc)
        return {
            "ok": False,
            "error": f"could not write {_LOCAL_CONFIG}: {exc}",
            "applied": {},
            "rejected": rejected,
        }

    # Drops the config singleton AND every cache keyed off it, so a changed
    # path or rate is live on the next turn rather than the next launch.
    reset_config()

    restart_needed = sorted(
        k for k in applied if SETTINGS_BY_KEY[k].get("restart")
    )
    logger.info(
        "[settings] Settings written (operation=apply_settings, keys=%s)",
        sorted(applied) or "reset",
    )
    return {
        "ok": True,
        "applied": applied,
        "rejected": rejected,
        "notes": notes,
        "restart_needed": restart_needed,
        **settings_view(),
    }


def settings_blueprint(name: str = BLUEPRINT_NAME) -> Blueprint:
    """Build the settings blueprint. Factory, not a singleton -- see games/api.py."""
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/api/settings")
    def api_get_settings() -> Any:
        """Player-settable engine config: spec, live value, override state."""
        return jsonify(settings_view())

    @blueprint.post("/api/settings")
    def api_put_settings() -> Any:
        """
        Persist whitelisted settings into config/local.yaml.

        Not a game mutation: nothing here touches a GameState. Unknown keys
        are refused and numbers are clamped to their declared domain, so no
        body a client can send makes a run unplayable.
        """
        body = request.get_json(silent=True) or {}
        result = apply_settings(
            body.get("changes") or {},
            reset=bool(body.get("reset")),
        )
        return jsonify(result), (200 if result.get("ok") else 500)

    return blueprint


__all__ = [
    "BLUEPRINT_NAME",
    "SETTINGS_BY_KEY",
    "SETTING_SPECS",
    "apply_settings",
    "settings_blueprint",
    "settings_view",
]

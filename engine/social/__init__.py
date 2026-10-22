"""
The social engine (v0.22.0, docs/superpowers/specs/2026-10-08-v0.22.0-dating-sim-design.md).

Declared by ONE manifest key, `paths.social`, a directory whose files are
found by fixed name (AUTHORING §3.15). This module is the only part of the
package any other engine module imports unconditionally: it reads config and
nothing else. `boot()` imports the submodules, and is called only once the
story is known to declare the key.

``_DATA_LOCK`` sits in ``engine/locks.py``'s one order just before
``engine.net._lock``: it is taken holding nothing but possibly warming's
lock, and under it only the config's lock is taken (by ``social_dir``).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

from engine import yamlio
from engine.config import get_config
from engine.locks import renew_after_fork

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

#: Every fixed file name the directory may hold (spec §2.1; v0.23.0 §22 adds the second row).
FILES: tuple[str, ...] = (
    "creation", "population", "behaviours", "apps", "relationships", "media", "venues", "games",
    "conversation", "promises", "growth", "topics", "layers", "plans", "scenes", "life_events", "homes",
)

#: name -> parsed YAML, for the ACTIVE story. NULLED_ATTRIBUTES row; read once
#: into a local (tests/test_cache_reset_race.py).
_DATA_CACHE: Optional[dict[str, dict[str, Any]]] = None
_DATA_LOCK = threading.Lock()


def social_dir() -> Optional[Path]:
    rel = str(get_config().get("paths.social", "") or "").strip()
    return (_ROOT / rel) if rel else None


def declared() -> bool:
    """Whether the running story declares `paths.social`."""
    return social_dir() is not None


def world_dir() -> Optional[Path]:
    """The directory of `paths.locations` (Plan decision 6): `activities.yaml` is found beside it."""
    rel = str(get_config().get("paths.locations", "") or "").strip()
    return (_ROOT / rel).parent if rel else None


def scene_open(state: Any) -> bool:
    """
    Whether a social scene owns the turn (spec §10.1; Plan decision 15).
    Reads `state.social["scene"]` only: no submodule is imported, so
    `intents.scene_owns_turn` and `director.ensure_scene` may ask it for
    every story. False unless the running story declares `paths.social`.
    """
    if not declared():
        return False
    return bool(((getattr(state, "social", None) or {}).get("scene") or {}).get("pid"))


def load_file(directory: Path, name: str) -> dict[str, Any]:
    """One `<name>.yaml` from `directory`; {} when absent. A parse fault is a ValueError naming it."""
    path = directory / f"{name}.yaml"
    if not path.is_file():
        return {}
    try:
        loaded = yamlio.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- re-raised as the load rule's ValueError
        raise ValueError(f"social: {path.name}: does not parse: {exc}") from None
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"social: {path.name}: the top level must be a mapping")
    return loaded


def load_all() -> dict[str, dict[str, Any]]:
    """Every file of the active story's social directory (the WARMERS loader)."""
    global _DATA_CACHE
    cached = _DATA_CACHE
    if cached is not None:
        return cached
    with _DATA_LOCK:
        cached = _DATA_CACHE
        if cached is None:
            directory = social_dir()
            cached = {name: load_file(directory, name) for name in FILES} if directory else {}
            if directory:
                # The world's activities sit beside `paths.locations` (Plan decision 6); {} when absent.
                world = world_dir()
                cached["activities"] = load_file(world, "activities") if world else {}
            _check_loaded(cached)
            _DATA_CACHE = cached
    return cached


def _check_loaded(loaded: dict[str, dict[str, Any]]) -> None:
    """Blocks checked once, at load, rather than at every use (a ValueError naming file and key)."""
    behaviours_data = loaded.get("behaviours") or {}
    if behaviours_data:
        from engine.social import behaviour   # lazily: behaviour imports this module

        behaviour.check_canon(behaviours_data)   # every arc's reveal a canon row (T12)
    relationships_data = loaded.get("relationships")
    if relationships_data:
        from engine.social import relationships   # lazily: relationships imports this module

        relationships.check_data(relationships_data)
        relationships.check_cap_bands(loaded.get("behaviours") or {}, relationships_data)
    media_data = loaded.get("media")
    if media_data:
        from engine.social import media   # lazily: media imports this module

        media.check_data(media_data, loaded.get("population") or {}, relationships_data or {})
    traits = frozenset(str(t["id"]) for t in (loaded.get("population") or {}).get("traits") or []
                       if isinstance(t, dict) and t.get("id"))
    if loaded.get("venues") or "meets" in (relationships_data or {}):
        from engine.social import places, scene   # lazily: each imports this module

        faults = (places.venue_faults(loaded.get("venues") or {}, loaded.get("population") or None)
                  + scene.meets_faults(relationships_data or {}, venues_declared=bool(loaded.get("venues"))))
        if faults:
            source, key, message = faults[0]
            raise ValueError(f"social: {source}: {key}: {message}")
    if loaded.get("scenes"):
        from engine.social import scene   # lazily: scene imports this module

        scene.check_data(loaded["scenes"], traits=traits)   # move keys closed; fit.traits population traits (F23)
    games_data = loaded.get("games") or {}
    if "wordgame" in games_data:
        from engine.social.games import wordgame   # lazily: wordgame imports this module

        wordgame.check_data(games_data["wordgame"], social_dir())
    if "this_or_that" in games_data:
        from engine.social.games import this_or_that   # lazily: this_or_that imports this module

        this_or_that.check_data(games_data["this_or_that"], loaded.get("population") or None)
    if loaded.get("conversation"):
        from engine.social import convo   # lazily: convo imports this module

        archetypes = (loaded.get("behaviours") or {}).get("archetypes") or {}
        convo.check_data(loaded["conversation"], archetypes=archetypes if isinstance(archetypes, dict) else ())
    if loaded.get("growth"):
        from engine.social import growth   # lazily: growth imports this module

        growth.check_data(loaded["growth"], loaded.get("topics") or {}, loaded.get("layers") or {}, traits=traits)
    if loaded.get("promises"):
        from engine.social import promises   # lazily: promises imports this module

        promises.check_data(loaded["promises"])
    if loaded.get("plans"):
        from engine.social import plans   # lazily: plans imports this module

        plans.check_data(loaded["plans"])
    if loaded.get("life_events"):
        from engine.social import life   # lazily: life imports this module

        moods = ((relationships_data or {}).get("mood") or {}).get("values")
        life.check_data(loaded["life_events"], moods=tuple(moods) if isinstance(moods, list) else None)
    if loaded.get("activities"):
        from engine.social import world   # lazily: world imports this module

        world.check_activities(loaded["activities"])


def data(name: str) -> dict[str, Any]:
    return load_all().get(name, {})


def setting(key: str, default: Any) -> Any:
    """`social.<key>` from config (engine bounds, spec §20)."""
    return get_config().get(f"social.{key}", default)


def boot() -> None:
    """Import every submodule, registering its effect kinds, verbs and payload sections."""
    # FIRST, so every drawer registered by a later import finds the registry (v0.23.0 Plan decision 7).
    from engine.social import attrs  # noqa: F401  (v0.23 T1)
    # One line per task, in task order (Plan decision 12):
    from engine.social import population  # noqa: F401  (T3)
    from engine.social import creation  # noqa: F401  (T4)
    from engine.social import behaviour  # noqa: F401  (T5)
    from engine.social import events  # noqa: F401  (T5)
    from engine.social import intents, payload, turn  # noqa: F401  (T6)
    from engine.social import apps, matching  # noqa: F401  (T7)
    from engine.social import messaging  # noqa: F401  (T8)
    from engine.social import relationships  # noqa: F401  (T9)
    from engine.social import archive, saves  # noqa: F401  (T10)
    from engine.social import agreement  # noqa: F401  (T11)
    from engine.social import memory  # noqa: F401  (T12)
    from engine.social import voicing  # noqa: F401  (T13)
    from engine.social import inbox, voicer  # noqa: F401  (T14)
    from engine.social import away  # noqa: F401  (T16)
    from engine.social import media  # noqa: F401  (T19)
    from engine.social import games  # noqa: F401  (T22)
    from engine.social import growth  # noqa: F401  (v0.23 T2)
    from engine.social import convo, windows  # noqa: F401  (v0.23 T3)
    from engine.social import promises  # noqa: F401  (v0.23 T4)
    from engine.social import places  # noqa: F401  (v0.23 T10)
    from engine.social import world  # noqa: F401  (v0.23 T11)
    from engine.social import plans  # noqa: F401  (v0.23 T12)
    from engine.social import scene  # noqa: F401  (v0.23 T13)
    from engine.social import life  # noqa: F401  (v0.23 T17)
    from engine.social import migrate  # noqa: F401  (v0.23 T20)


#: Names already reported by import_fault (a log_once row): one ERROR per process, not one per advance.
_IMPORT_FAULTS_LOGGED: set[str] = set()


def import_fault(name: str, exc: BaseException) -> None:
    """A declared story's social submodule failed to import (Plan decision 27): ERROR, once per name."""
    if name in _IMPORT_FAULTS_LOGGED:
        return
    _IMPORT_FAULTS_LOGGED.add(name)
    logger.error("[social] A social module failed to import; its pass is skipped "
                 "(operation=import_fault, module=%s): %s", name, exc)


renew_after_fork(globals(), _DATA_LOCK=threading.Lock)

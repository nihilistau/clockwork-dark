"""
Player creation (v0.22.0 spec §3): the form is data, the engine validates it.

`creation.yaml`'s `fields:` declares every field (its shapes are documented
in that file's header). `resolved_form()` serves it to the client with each
`of_table` expanded to `{id, label}` rows from `population.yaml`, so the
player picks from the same lists the population is drawn from.
`apply(state, payload)` checks a payload against it -- an unknown key, a value
outside its list or range, or a list of the wrong length raises
`CreationError` naming the dotted field -- fills every omitted field's
default, and writes `state.social` through the one engine-only effect
`social_profile` (rule 3), which also queues the event queue's first `daily`
(engine/social/events.py).

A default that must be chosen (a choice with no `default:`, a `multi`) is a
seeded pick: `stable_rng(seed, f"{SOCIAL_POPULATION}:player:{field}")`, one
key per dotted field, so the same seed always makes the same default player
and a field added to the form moves no other field's default (rule 4).

The age floor is `creation.yaml`'s own `min: 18` (data; spec §3.1): there is
no engine age constant here.
"""

from __future__ import annotations

from typing import Any, Optional

from engine import social
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.social.kinds import recorded
from engine.game.rng import SOCIAL_POPULATION, stable_rng
from engine.game.state import GameState
from engine.social import events
from engine.social.kinds import empty_slice
from engine.social.population import table

#: Every field kind the form may declare (validated by `check_social`).
FIELD_KINDS: frozenset[str] = frozenset({"text", "choice", "int", "multi", "sliders"})

#: A slider's default when the payload names none (spec §3.1 shows none).
SLIDER_DEFAULT = 3


class CreationError(ValueError):
    """A creation payload refused; `field` is the dotted name of the field at fault."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


def form_fields() -> dict[str, Any]:
    """`creation.yaml`'s `fields:` mapping ({} when the story declares none)."""
    fields = social.data("creation").get("fields")
    return fields if isinstance(fields, dict) else {}


def start_hours() -> Optional[float]:
    """
    The world clock a new run is born at (spec §15.4): `creation.yaml`'s
    `start_hour` on day 1, or None (the engine's default, 08:00) when the
    story names none. A value outside 0-23 is a ValueError naming it.
    """
    raw = social.data("creation").get("start_hour")
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 23:
        raise ValueError(f"social: creation.yaml: start_hour: must be a whole hour 0-23, not {raw!r}")
    return float(raw)


def is_field(spec: Any) -> bool:
    """A leaf field (it has a `kind:`), as against a mapping of fields."""
    return isinstance(spec, dict) and "kind" in spec


def options(spec: dict[str, Any]) -> list[dict[str, str]]:
    """A choice's or multi's rows, `{id, label}`: its table's, or its inline ids (label = id)."""
    if spec.get("of_table"):
        return [
            {"id": str(row["id"]), "label": str(row.get("label", row["id"]))}
            for row in table(str(spec["of_table"]))
            if isinstance(row, dict) and "id" in row
        ]
    return [{"id": str(value), "label": str(value)} for value in spec.get("of") or []]


#: The engine's own player name (``GameState.player_name``'s default): a new
#: game sending only it has named nobody.
ENGINE_DEFAULT_NAME: str = GameState.__dataclass_fields__["player_name"].default


def seeded_name(payload: Any, player_name: str) -> Any:
    """
    ONE IDENTITY (v0.22.0 T4 ruling, wired in T27): `creation.name` is the
    story's name for the player, and a new game's `player_name` -- when it is
    not the engine default and is a name the form accepts -- is that field's
    default. A payload naming its own `name` keeps it; anything not a mapping
    is returned untouched for `apply` to refuse.
    """
    if not isinstance(payload, dict) or "name" in payload:
        return payload
    spec = form_fields().get("name")
    if not is_field(spec) or spec.get("kind") != "text":
        return payload
    if not isinstance(player_name, str) or not player_name.strip() or player_name == ENGINE_DEFAULT_NAME:
        return payload
    try:
        _field(spec, player_name, given=True, dotted="name", seed=0)
    except CreationError:
        return payload            # too long for the form: the form's own default stands
    return {**payload, "name": player_name}


def name_of(payload: Any) -> Optional[str]:
    """
    The name `apply` will store for `payload` (its `name`, stripped, or the
    form's default), or None when the form has no text `name` field or the
    payload's would be refused -- `apply` says why.
    """
    spec = form_fields().get("name")
    if not is_field(spec) or spec.get("kind") != "text":
        return None
    payload = payload if isinstance(payload, dict) else {}
    try:
        return str(_field(spec, payload.get("name"), given="name" in payload, dotted="name", seed=0))
    except CreationError:
        return None


def resolved_form() -> dict[str, Any]:
    """The form as the client renders it (spec §3.2): every table expanded to `{id, label}` rows."""
    return {"fields": _resolve_form(form_fields())}


def _resolve_form(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, spec in fields.items():
        if not is_field(spec):
            out[str(name)] = _resolve_form(spec if isinstance(spec, dict) else {})
            continue
        row = dict(spec)
        if row["kind"] in ("choice", "multi"):
            row["of"] = options(spec)
        out[str(name)] = row
    return out


# -- validation ---------------------------------------------------------------


def apply(state: GameState, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, fill defaults, write state.social through `social_profile` (spec §3.2).

    Returns the stored profile. Raises `CreationError` naming the field at fault;
    nothing is written when it does.
    """
    if not isinstance(payload, dict):
        raise CreationError("creation", "must be an object")
    profile = _resolve(form_fields(), payload, prefix="", seed=int(state.rng_seed))
    discovery = profile.get("discovery")
    if isinstance(discovery, dict) and "age_min" in discovery and "age_max" in discovery:
        if discovery["age_min"] > discovery["age_max"]:
            raise CreationError("discovery", "age_min must not be above age_max")
    result = apply_effect(state, {"type": "social_profile", "profile": profile})
    if not result.get("ok"):
        raise CreationError("creation", str(result.get("text") or "refused"))
    return state.social["player"]


def _resolve(form: dict[str, Any], payload: dict[str, Any], *, prefix: str, seed: int) -> dict[str, Any]:
    """One mapping of the form against one mapping of the payload; recursive for nested mappings."""
    for key in payload:
        if key not in form:
            raise CreationError(f"{prefix}{key}", "unknown field")
    out: dict[str, Any] = {}
    for name, spec in form.items():
        dotted = f"{prefix}{name}"
        given = name in payload
        value = payload.get(name)
        if not is_field(spec):
            if given and not isinstance(value, dict):
                raise CreationError(dotted, "must be an object")
            out[name] = _resolve(spec or {}, value if given else {}, prefix=f"{dotted}.", seed=seed)
            continue
        out[name] = _field(spec, value, given=given, dotted=dotted, seed=seed)
    return out


def _int_in(value: Any, spec: dict[str, Any], dotted: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CreationError(dotted, "must be a whole number")
    low, high = spec.get("min"), spec.get("max")
    if low is not None and value < int(low):
        raise CreationError(dotted, f"must be at least {low}")
    if high is not None and value > int(high):
        raise CreationError(dotted, f"must be at most {high}")
    return value


def _field(spec: dict[str, Any], value: Any, *, given: bool, dotted: str, seed: int) -> Any:
    kind = spec["kind"]
    if kind == "text":
        if not given:
            return str(spec.get("default", ""))
        if not isinstance(value, str):
            raise CreationError(dotted, "must be text")
        text = value.strip()
        if spec.get("max") is not None and len(text) > int(spec["max"]):
            raise CreationError(dotted, f"must be at most {spec['max']} characters")
        return text or str(spec.get("default", ""))
    if kind == "int":
        if not given:
            return int(spec["default"])
        return _int_in(value, spec, dotted)
    if kind == "choice":
        ids = [row["id"] for row in options(spec)]
        if not given:
            if "default" in spec:
                return str(spec["default"])
            return _rng(seed, dotted).choice(ids)
        if not isinstance(value, str) or value not in ids:
            raise CreationError(dotted, f"must be one of {', '.join(ids)}")
        return value
    if kind == "multi":
        ids = [row["id"] for row in options(spec)]
        low, high = int(spec.get("min", 0)), int(spec.get("max", len(ids)))
        if not given:
            return _rng(seed, dotted).sample(ids, min(low, len(ids)))
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise CreationError(dotted, "must be a list of ids")
        unknown = [v for v in value if v not in ids]
        if unknown:
            raise CreationError(dotted, f"{unknown[0]!r} is not one of the choices")
        if len(set(value)) != len(value):
            raise CreationError(dotted, "must not name an id twice")
        if not low <= len(value) <= high:
            raise CreationError(dotted, f"must name {low} to {high}")
        return list(value)
    if kind == "sliders":
        names = [str(n) for n in spec.get("of") or []]
        if given and not isinstance(value, dict):
            raise CreationError(dotted, "must be an object")
        given_values = value if given else {}
        for key in given_values:
            if key not in names:
                raise CreationError(f"{dotted}.{key}", "unknown field")
        return {
            name: _int_in(given_values[name], spec, f"{dotted}.{name}") if name in given_values else SLIDER_DEFAULT
            for name in names
        }
    raise CreationError(dotted, f"unknown field kind {kind!r}")


def _rng(seed: int, dotted: str) -> Any:
    return stable_rng(seed, f"{SOCIAL_POPULATION}:player:{dotted}")


# -- the effect -----------------------------------------------------------------


@effect_kind("social_profile")
@recorded
def _e_social_profile(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """Engine-only (`ENGINE_ONLY_EFFECTS`): the social slice is born holding the player's profile."""
    if (state.social or {}).get("player"):
        return {"type": "social_profile", "ok": False, "text": "a profile already exists"}
    profile = effect.get("profile")
    if not isinstance(profile, dict) or not profile:
        return {"type": "social_profile", "ok": False, "text": "no profile given"}
    state.social = {**empty_slice(), "player": dict(profile)}
    # The queue's first `daily` (spec §9.1): it re-queues itself from then on.
    events.push(state, events.next_daily(state.world_clock_hours), "", "daily")
    return {"type": "social_profile", "ok": True, "text": "profile created"}

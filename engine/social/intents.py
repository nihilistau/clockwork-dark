"""
The phone catalogue (v0.22.0 spec §7, rule 1).

Nobody samples this catalogue: the player presses it. It reuses
engine.game.intents.IntentVerb -- targets are checked by membership, dynamic
enums ride in `extra` -- and adds a PAYLOAD per verb, checked here: enums,
text caps (refused, never cut), ints in range, lists bounded. Rows are
registered with @phone_verb by the module that owns the mechanic (Plan
decision 12), so the catalogue grows task by task with no stub.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from engine import social
from engine.game.intents import IntentVerb
from engine.game.state import GameState

logger = logging.getLogger(__name__)

LegalFn = Callable[[GameState], Optional[IntentVerb]]
LabelFn = Callable[[GameState, dict[str, Any]], str]
WhyNotFn = Callable[[GameState], str]
RefuseFn = Callable[[GameState, dict[str, Any]], str]


@dataclass(frozen=True)
class ArgSpec:
    kind: str                          # enum | text | int | id | list
    values: tuple[str, ...] = ()
    max_len: int = 0
    min_len: int = 0                   # list: at least this many items (T23: This or That's five answers)
    min: int = 0
    max: int = 0
    required: bool = False
    item: Optional["ArgSpec"] = None


@dataclass(frozen=True)
class VerbRow:
    action: str
    legal: LegalFn
    payload: dict[str, ArgSpec]
    skill: str
    takes_text: bool
    text_cap: str
    label: LabelFn
    #: The engine's words for why the verb is not legal now ("No likes left
    #: today"), or "" for the generic refusal. Read only when `legal` says no.
    why_not: Optional[WhyNotFn] = None
    #: The engine's words for refusing THIS intent (a target the verb does not
    #: offer now, "Give it a while"), or "": checked before the generic refusals
    #: of an illegal verb or target, and of an argument whose value the row
    #: declares but does not offer now (`not_offered`). Never consulted for a
    #: malformed payload (a value the row never takes, a wrong type, a cap):
    #: that keeps its own problem.
    refuse: Optional[RefuseFn] = None


#: action -> row, in registration order (the order the client lists them).
_ROWS: dict[str, VerbRow] = {}
#: action -> skill name (tests/test_reachability.py, Plan decision 4).
PHONE_SKILL_FOR_ACTION: dict[str, str] = {}
#: action -> payload schema, for the client and the HTTP twin's docs.
PAYLOADS: dict[str, dict[str, ArgSpec]] = {}


def _default_label(state: GameState, intent: dict[str, Any]) -> str:
    return f"{intent['action']} {intent.get('target', '')}".strip()


def phone_verb(action: str, *, payload: dict[str, ArgSpec], skill: str, takes_text: bool = False,
               text_cap: str = "", label: Optional[LabelFn] = None,
               why_not: Optional[WhyNotFn] = None,
               refuse: Optional[RefuseFn] = None) -> Callable[[LegalFn], LegalFn]:
    def decorator(legal: LegalFn) -> LegalFn:
        if action in _ROWS and _ROWS[action].legal is not legal:
            raise ValueError(f"phone verb {action!r} registered twice")
        _ROWS[action] = VerbRow(action, legal, dict(payload), skill, takes_text, text_cap,
                                label or _default_label, why_not, refuse)
        PHONE_SKILL_FOR_ACTION[action] = skill
        PAYLOADS[action] = dict(payload)
        return legal
    return decorator


def row(action: str) -> Optional[VerbRow]:
    return _ROWS.get(action)


def label_of(state: GameState, intent: dict[str, Any]) -> str:
    """The player's sentence for a normalised intent; read under the turn lock (a label may read state)."""
    entry = _ROWS.get(str(intent.get("action") or ""))
    if entry is None:
        return str(intent.get("action") or "")
    return entry.label(state, intent)


def why_not(state: GameState, action: str) -> str:
    """The row's own reason a verb is not legal now; "" when it has none (or its reason faulted)."""
    entry = _ROWS.get(action)
    if entry is None or entry.why_not is None:
        return ""
    try:
        return str(entry.why_not(state) or "")
    except Exception:  # noqa: BLE001 -- the generic refusal still reaches the player
        logger.exception("[social] A why_not reason failed (operation=why_not, action=%s)", action)
        return ""


def refusal_for(state: GameState, intent: dict[str, Any]) -> str:
    """The row's own words for refusing this intent; "" when it has none (or its reason faulted)."""
    entry = _ROWS.get(str(intent.get("action") or ""))
    if entry is None or entry.refuse is None:
        return ""
    try:
        return str(entry.refuse(state, intent) or "")
    except Exception:  # noqa: BLE001 -- the generic refusal still reaches the player
        logger.exception("[social] A refusal reason failed (operation=refusal_for, action=%s)", entry.action)
        return ""


def legal_phone_intents(state: GameState) -> tuple[IntentVerb, ...]:
    """Every verb legal NOW, rebuilt from the live state (never cached)."""
    out: list[IntentVerb] = []
    for entry in _ROWS.values():
        try:
            verb = entry.legal(state)
        except Exception:  # noqa: BLE001 -- one broken row must not empty the phone
            logger.exception("[social] Catalogue row failed (operation=legal_phone_intents, action=%s)",
                             entry.action)
            continue
        if verb is not None:
            out.append(verb)
    return tuple(out)


def normalise_phone(raw: Any) -> Optional[dict[str, Any]]:
    """Coerce the wire body to {action, target, args, text}; None for anything unusable."""
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or "").strip()
    if not action:
        return None
    args = raw.get("args")
    return {
        "action": action,
        "target": str(raw.get("target") or "").strip(),
        "args": dict(args) if isinstance(args, dict) else {},
        "text": str(raw.get("text") or "").strip(),
    }


def _check_arg(name: str, spec: ArgSpec, value: Any, dynamic: tuple[str, ...]) -> str:
    if value is None or value == "":
        return f"{name} is required" if spec.required else ""
    if spec.kind in ("enum", "id"):
        allowed = dynamic or spec.values
        if str(value) not in allowed:
            return f"{name} must be one of: {', '.join(allowed)}" if allowed else f"{name} is not available"
        return ""
    if spec.kind == "text":
        if not isinstance(value, str):
            return f"{name} must be text"
        if spec.max_len and len(value) > spec.max_len:
            return f"{name} is longer than {spec.max_len} characters"
        return ""
    if spec.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{name} must be a whole number"
        if not spec.min <= value <= spec.max:
            return f"{name} must be between {spec.min} and {spec.max}"
        return ""
    if spec.kind == "list":
        if not isinstance(value, list):
            return f"{name} must be a list"
        if spec.min_len and spec.min_len == spec.max_len and len(value) != spec.min_len:
            return f"{name} must have exactly {spec.min_len} items"
        if spec.max_len and len(value) > spec.max_len:
            return f"{name} has more than {spec.max_len} items"
        if spec.min_len and len(value) < spec.min_len:
            return f"{name} has fewer than {spec.min_len} items"
        if spec.item is not None:
            for i, item in enumerate(value):
                problem = _check_arg(f"{name}[{i}]", spec.item, item, ())
                if problem:
                    return problem
        return ""
    return f"{name} has an unknown kind {spec.kind!r}"


def check_payload(entry: VerbRow, verb: IntentVerb, intent: dict[str, Any]) -> str:
    """'' when the intent's args and text fit the row; else the refusal reason."""
    args = intent["args"]
    unknown = sorted(set(args) - set(entry.payload))
    if unknown:
        return f"{entry.action} takes no {', '.join(unknown)}"
    for name, spec in entry.payload.items():
        problem = _check_arg(name, spec, args.get(name), tuple(verb.extra.get(name, ())))
        if problem:
            return problem
    text = intent["text"]
    if text and not entry.takes_text:
        return f"{entry.action} takes no text"
    if entry.text_cap:
        cap = int(social.setting(entry.text_cap.removeprefix("social."), 600))
        if len(text) > cap:
            return f"That message is longer than {cap} characters."
    return ""


def not_offered(entry: VerbRow, verb: IntentVerb, intent: dict[str, Any]) -> bool:
    """
    Whether the intent's only payload fault is an enum value the row DECLARES
    (its static `values`) but does not offer NOW (the verb's dynamic `extra`):
    a legal kind of argument, illegal at the moment -- the case the row's
    `refuse` words are for (asking for a photo where the app cannot carry
    it, or past today's asks).
    """
    args = intent["args"]
    found = False
    for name, spec in entry.payload.items():
        value = args.get(name)
        dynamic = tuple(verb.extra.get(name, ()))
        if spec.kind != "enum" or value in (None, "") or not dynamic or str(value) in dynamic:
            continue
        if str(value) not in spec.values:
            return False                                  # a value the row never takes: malformed
        found = True
    return found


def phone_refusal(intent: dict[str, Any], reason: str) -> dict[str, Any]:
    """The engine declining a phone action, in a receipt's shape (rule 1)."""
    return {
        "type": "phone",
        "skill": str(intent.get("action") or "phone"),
        "args": dict(intent),
        "result": {"ok": False, "error": reason},
        "success": False,
        "refused": True,
        "intent": dict(intent),
    }

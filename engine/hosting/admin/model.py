"""
The Admin Panel: the Model Server
=================================

``EDITABLE`` (v0.20.0 T14) is the closed allowlist of config keys the admin
panel may edit (spec §14.9), and so the only keys the admin layer,
``<storage.root>/hosting/admin.yaml``, may hold: ``engine/config.py`` reads it
to check that layer whenever hosting is on, and refuses a file holding any
other key, naming it. Every key is a model-server setting, and none is a
secret: an API key goes in the environment or a key file (spec §2), and a
base URL with credentials in it is refused (``validate_base_url``).

``hosting.*`` is not here, so the layer can never turn hosting on (or keep it
on) by itself, nor change who may log in or how fast. Editing anything
outside this list in the panel is NOT WIRED (docs/GOVERNANCE.md), and so is
setting a secret there.

THE VALIDATION (v0.20.0 T16), shared by the front door (the page's ``POST``)
and the supervisor (``llm.apply``, which checks again before it holds the
changes): ``validate_changes`` takes ``{dotted key: value}`` and, in order,

1. refuses a key outside ``EDITABLE`` ("not editable from the panel");
2. validates each value: the rows the Settings panel already has through ITS
   row table (``engine.api.settings.validate_setting``, reused, not copied: a
   number out of range is clamped, with a note), ``llm.provider`` as a
   ``PROVIDERS`` key, ``llm.base_url`` by ``validate_base_url`` (``http`` or
   ``https``, a host, no ``user:pass@``, no query, no fragment), a lane an
   integer from 1 to 16;
3. refuses a key a ``CLOCKWORK_CONFIG`` file sets ("set in ``<file>``"): that
   file outranks the admin layer, so an edit would be silently shadowed. The
   page shows those keys locked.

A refusal names the key and the rule, never the value: a refused base URL may
carry a credential, and nothing echoes it.

THE PAGE: ``GET /admin/model`` shows what the SUPERVISOR reports (the front
door never reads ``llm.*``; spec §14.9): the provider, the base URL (any
credentials or query in a URL set elsewhere hidden, ``display_url``), the
health probe's status, detail and latency, the loaded models (id, context,
capabilities) and ``llm.declared_models``, cached there for 10 s
(``llm.health``, ``llm.models``); the API key as "set, from the environment
(``CLOCKWORK_LLM_API_KEY``)", "set, from a file (``llm_api_key.txt``)" or
"not set" -- never its value, its length or any part of it (setting one here
is NOT WIRED); every editable key with its value, the locked ones disabled
with the file that sets them; and the last apply's progress (``ops.list``).

``POST /admin/model`` (every editable field, plus the "apply anyway" and
"send the API key to this host" boxes) sends ONLY the keys the admin
changed -- each compared with the value the form SHOWED (``was:<key>``),
never with the value in force -- and refuses the whole form, ``STALE``, when
the admin layer's version changed since the page was loaded (fix round 1,
I1: a second tab cannot revert another admin's apply). A base URL moved to
another origin takes the API key with it only when "send the API key to this
host" is ticked in the same submit, audited (``send_key``; fix round 1, I2:
the supervisor records the key's origin in the layer, and the config
withholds the key from any other). It is sent as ``llm.apply`` (spec §14.3,
§14.9): audited write-first (``llm.apply``, the keys its target, ``apply_anyway``
in its detail), answered AT ONCE with the operation's id, by a 303 to the page
(POST-redirect-GET), which follows the operation: ``validating``, ``draining``,
``restarting``, ``done``, ``refused`` or ``rolled_back``. The supervisor does
the rest (``engine/hosting/supervisor/llm.py``): it probes a new server, drains
every story, writes the layer, and restarts the workers one at a time -- never
a reset in place -- rolling back to the previous file if a worker will not
boot under the new one. Its outcome rows are its own.

``GET /admin/api/health.json``: the health row, for the refresh script.

Version: v0.2.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: The admin layer's file name under ``<storage.root>/hosting/``.
ADMIN_LAYER_FILE = "admin.yaml"

#: The admin layer's previous version, beside it (spec §14.9 step 4).
ADMIN_LAYER_PREV = "admin.yaml.prev"

#: Every dotted key the panel may edit, and the admin layer may hold.
EDITABLE = frozenset(
    {
        "llm.provider",
        "llm.base_url",
        "llm.lanes.narration",
        "llm.lanes.utility",
        "llm.context_tokens",
        "llm.prefer_native",
        "llm.profiles.big.model",
        "llm.profiles.big.temperature",
        "llm.profiles.big.max_tokens",
        "llm.profiles.big.reasoning_budget",
        "llm.profiles.big.reasoning",
    }
)

#: The admin layer's keys that the panel never edits, written by the
#: supervisor alone (v0.20.0 T16 fix round 1): ``llm.api_key_origin``, the
#: origin the API key may be sent to while the layer sets ``llm.base_url``
#: (``engine/config.py::_key_withheld``). The layer may hold them; a form
#: posting one is refused like any key outside ``EDITABLE``.
LAYER_ONLY = frozenset({"llm.api_key_origin"})

#: The order the page lists them in.
EDITABLE_ORDER = (
    "llm.provider",
    "llm.base_url",
    "llm.lanes.narration",
    "llm.lanes.utility",
    "llm.context_tokens",
    "llm.prefer_native",
    "llm.profiles.big.model",
    "llm.profiles.big.temperature",
    "llm.profiles.big.max_tokens",
    "llm.profiles.big.reasoning_budget",
    "llm.profiles.big.reasoning",
)

#: The keys whose change makes the supervisor probe the NEW server first.
SERVER_KEYS = ("llm.provider", "llm.base_url")

#: The lane keys, and their range (spec §14.9).
LANE_KEYS = ("llm.lanes.narration", "llm.lanes.utility")
LANE_MIN = 1
LANE_MAX = 16

#: The longest base URL the panel takes (it is shown and audited).
URL_MAX = 200

#: What a refusal for each rule says (the key is named, the value never).
NOT_EDITABLE = "is not editable from the panel"
LOCKED = "is set in {file}, which outranks the panel's edits; change it there"

#: Characters a base URL may not hold: whitespace and controls (and a
#: ``${...}`` template, refused by name below).
_URL_BAD = re.compile(r"[\s\x00-\x1f\x7f]")

#: ``scheme://user:pass@`` in any text: what ``scrub`` hides.
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]*@")


class ChangeRefused(ValueError):
    """One change refused: ``key`` and the rule it broke (never its value)."""

    def __init__(self, key: str, reason: str, code: str = "bad_value") -> None:
        super().__init__(f"{key} {reason}")
        self.key = key
        self.reason = reason
        #: The bus code the supervisor answers with (``not_editable``,
        #: ``bad_value``, ``locked``).
        self.code = code


def validate_base_url(raw: Any) -> str:
    """
    ``llm.base_url`` as the panel takes it (spec §14.9): an ``http`` or
    ``https`` URL with a host, at most ``URL_MAX`` characters, with no
    ``user:pass@``, no query and no fragment -- what keeps the allowlist free
    of secrets, since the URL is shown on the page and written, old and new,
    to the audit log. The value, stripped.

    Raises:
        ChangeRefused: naming the rule, never the value.
    """
    key = "llm.base_url"
    if not isinstance(raw, str):
        raise ChangeRefused(key, "must be a URL")
    value = raw.strip()
    if not value:
        raise ChangeRefused(key, "must be a URL")
    if len(value) > URL_MAX:
        raise ChangeRefused(key, f"is longer than {URL_MAX} characters")
    if "${" in value:
        raise ChangeRefused(key, "cannot be a ${...} reference; write it in the operator's file")
    if _URL_BAD.search(value):
        raise ChangeRefused(key, "holds a space or a control character")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ChangeRefused(key, "is not a valid URL") from None
    if parts.scheme not in ("http", "https"):
        raise ChangeRefused(key, "must start http:// or https://")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise ChangeRefused(
            key, "carries a user name or password (user:pass@); a key goes in the environment or a key file"
        )
    if parts.query or "?" in value:
        raise ChangeRefused(key, "carries a query (?...); a key goes in the environment or a key file")
    if parts.fragment or "#" in value:
        raise ChangeRefused(key, "carries a fragment (#...)")
    if not parts.hostname:
        raise ChangeRefused(key, "names no host")
    if port is not None and not 1 <= port <= 65535:
        raise ChangeRefused(key, "names a port outside 1-65535")
    return value


def validate_change(key: str, raw: Any) -> tuple[Any, str]:
    """
    One change's value, by its row: ``(value, note)``.

    Raises:
        ChangeRefused: ``key`` is outside ``EDITABLE`` (code
            ``not_editable``) or the value breaks its row (``bad_value``).
    """
    if key not in EDITABLE:
        raise ChangeRefused(key, NOT_EDITABLE, "not_editable")
    if key == "llm.provider":
        from engine.llm.providers import PROVIDERS

        value = str(raw).strip() if isinstance(raw, str) else ""
        if value not in PROVIDERS:
            raise ChangeRefused(key, f"must be one of {', '.join(PROVIDERS)}")
        return value, ""
    if key == "llm.base_url":
        return validate_base_url(raw), ""
    if key in LANE_KEYS:
        if isinstance(raw, bool):
            raise ChangeRefused(key, f"must be a whole number from {LANE_MIN} to {LANE_MAX}")
        try:
            value = int(str(raw).strip()) if isinstance(raw, str) else int(raw)
        except (TypeError, ValueError):
            raise ChangeRefused(key, f"must be a whole number from {LANE_MIN} to {LANE_MAX}") from None
        if isinstance(raw, float) and raw != value:
            raise ChangeRefused(key, f"must be a whole number from {LANE_MIN} to {LANE_MAX}")
        if not LANE_MIN <= value <= LANE_MAX:
            raise ChangeRefused(key, f"must be a whole number from {LANE_MIN} to {LANE_MAX}")
        return value, ""
    # Every other editable key is a Settings panel row: ITS rule, reused.
    from engine.api.settings import validate_setting

    accepted, value, note = validate_setting(key, raw)
    if not accepted:
        raise ChangeRefused(key, f"is refused: {note}")
    return value, (f"{key} {note}" if note else "")


def validate_changes(
    changes: Mapping[str, Any], locked: Optional[Mapping[str, str]] = None
) -> tuple[dict[str, Any], list[str]]:
    """
    Every change, in the module docstring's order: ``(values by key, notes)``.

    Raises:
        ChangeRefused: the first change refused (``not_editable``,
            ``bad_value`` or ``locked``).
    """
    if not isinstance(changes, Mapping) or not changes:
        raise ChangeRefused("the form", "changes nothing", "bad_value")
    for key in changes:
        if not isinstance(key, str) or key not in EDITABLE:
            raise ChangeRefused(str(key)[:64], NOT_EDITABLE, "not_editable")
    clean: dict[str, Any] = {}
    notes: list[str] = []
    for key in sorted(changes):
        value, note = validate_change(key, changes[key])
        clean[key] = value
        if note:
            notes.append(note)
    for key in sorted(clean):
        source = (locked or {}).get(key)
        if source:
            raise ChangeRefused(key, LOCKED.format(file=source), "locked")
    return clean, notes


def display_url(value: Any) -> str:
    """
    A URL as the page and the audit log show it: any ``user:pass@`` replaced
    by ``***@`` and any query or fragment dropped. A URL the panel wrote has
    neither (``validate_base_url``); one an operator's file or ``local.yaml``
    set may, and a credential there is never displayed.
    """
    if not isinstance(value, str):
        return "" if value is None else str(value)
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return scrub(value)
    netloc = parts.netloc
    if "@" in netloc:
        netloc = "***@" + netloc.rsplit("@", 1)[1]
    shown = f"{parts.scheme}://{netloc}{parts.path}" if parts.scheme else scrub(value.split("?", 1)[0])
    return shown


def scrub(text: Any) -> str:
    """``text`` with any ``scheme://user:pass@`` written ``scheme://***@`` (a probe's detail line)."""
    return _USERINFO.sub(r"\1***@", str(text or ""))


def nested(changes: Mapping[str, Any]) -> dict[str, Any]:
    """``{dotted: value}`` as a nested mapping (the layer file's shape)."""
    out: dict[str, Any] = {}
    for dotted, value in changes.items():
        node = out
        parts = dotted.split(".")
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        node[parts[-1]] = value
    return out


# -- the page (the front door) -------------------------------------------------

#: How long the page waits for the supervisor's health and models (it probes
#: the model server at most every 10 s, with a 3 s timeout of its own).
BUS_SECONDS = 15.0

#: How long the apply's bus round trip may take: it is answered at once.
OP_SECONDS = 10.0

#: The bus codes that leave it unknown whether the apply was queued.
UNANSWERED = frozenset({"timeout", "closed"})

#: What a refusal answered at once is told, by the bus's code.
APPLY_REFUSALS = (
    ("busy", 409, "another operation is running; wait for it to finish"),
    ("locked", 409, "a key is set in the operator's configuration file"),
    ("not_editable", 400, "a key is not editable from the panel"),
    ("bad_value", 400, "a value was refused"),
    ("bad_args", 400, "the form was refused"),
    ("shutting_down", 503, "the server is shutting down"),
    ("stale", 409, "these settings changed since you loaded the page; reload it and apply again"),
)

#: The form's own fields, beside the editable keys and their ``was:<key>``
#: twins (the value each field showed).
FORM_FIELDS = frozenset({"csrf", "apply_anyway", "send_key", "version"})

#: The prefix of a field holding the value an editable field SHOWED.
WAS = "was:"

#: What a form loaded before the admin layer last changed is told (fix round
#: 1, I1): it is refused whole, never applied over another admin's change.
STALE = "These settings changed since you loaded the page. Reload it, and apply your change again."


def _ask(op: str, args: Optional[dict[str, Any]] = None, timeout: float = BUS_SECONDS) -> dict[str, Any]:
    from engine.hosting.admin.sessions import ask

    return ask(op, args, timeout=timeout)


def health_data() -> dict[str, Any]:
    """The supervisor's ``llm.health`` row, or ``{"error": code}``; never raises."""
    from engine.hosting.bus import BusError

    try:
        return _ask("llm.health")
    except BusError as exc:
        logger.warning("[admin] The model server's health could not be read (operation=llm.health, error=%s)", exc.code)
        return {"error": exc.code}


def models_data() -> dict[str, Any]:
    """The supervisor's ``llm.models`` answer, or ``{"error": code}``; never raises."""
    from engine.hosting.bus import BusError

    try:
        return _ask("llm.models")
    except BusError as exc:
        logger.warning("[admin] The model list could not be read (operation=llm.models, error=%s)", exc.code)
        return {"models": [], "error": exc.code}


def last_apply() -> dict[str, Any]:
    """The newest ``llm.apply`` operation's row, or {}; never raises."""
    from engine.hosting.bus import BusError

    try:
        operations = _ask("ops.list").get("ops") or []
    except BusError:
        return {}
    applies = [op for op in operations if isinstance(op, dict) and op.get("kind") == "llm.apply"]
    return applies[-1] if applies else {}


def key_text(key: Mapping[str, Any]) -> str:
    """The API key's row: presence and source kind, never the value."""
    kind, source = str(key.get("kind") or ""), str(key.get("source") or "")
    if kind == "environment":
        text = f"set, from the environment ({source})"
    elif kind == "file":
        text = f"set, from a file ({source})"
    elif kind == "config":
        text = f"set, in the configuration ({source})"
    else:
        return "not set"
    if key.get("withheld"):
        # Fix round 1 (I2): the base URL was moved to another origin without
        # the admin's "send the API key to this host".
        return (
            f"{text}, but WITHHELD: llm.base_url is on another host than the key was given for, "
            "and the key is not sent there (apply the URL again with \"send the API key to this host\" ticked)"
        )
    return text


def _rows(health: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each editable key: its value as shown, and the file that locks it ("" for none)."""
    values = health.get("values") if isinstance(health.get("values"), dict) else {}
    locked = health.get("locked") if isinstance(health.get("locked"), dict) else {}
    rows = []
    for key in EDITABLE_ORDER:
        value = values.get(key)
        shown = display_url(value) if key == "llm.base_url" else ("" if value is None else value)
        if isinstance(shown, bool):
            shown = "true" if shown else "false"
        rows.append({"key": key, "value": str(shown), "locked": str(locked.get(key) or "")})
    return rows


def model_page(message: str = "", status: int = 200) -> Any:
    from engine.hosting.admin.guard import admin_account, take_done
    from engine.hosting.admin.pages import render
    from engine.hosting.admin.users import when
    from engine.hosting.auth import form_token
    from engine.llm.providers import PROVIDERS

    admin = admin_account()
    message = message or take_done()
    health = health_data()
    models = models_data()
    op = last_apply()
    checked = float(health.get("checked_at") or 0.0)
    return (
        render(
            "model.html",
            admin=admin,
            csrf=form_token(admin),
            page="model",
            health=health,
            checked=when(checked, seconds=True) if checked else "",
            key=key_text(health.get("key") or {}),
            models=models,
            rows=_rows(health),
            version=str((health.get("layer") or {}).get("version") or ""),
            key_set=bool((health.get("key") or {}).get("set")),
            providers=list(PROVIDERS),
            op=op,
            message=message,
        ),
        status,
    )


def health_json() -> dict[str, Any]:
    """The refresh script's view: the health row, no form data."""
    health = health_data()
    return {
        "provider": str(health.get("provider") or ""),
        "base_url": display_url(health.get("base_url")),
        "status": "" if "ok" not in health else ("ok" if health.get("ok") else "down"),
        "detail": scrub(health.get("detail")),
        "latency_ms": health.get("latency_ms"),
        "key": key_text(health.get("key") or {}),
        "error": str(health.get("error") or ""),
    }


def _posted(form: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """
    The editable fields posted, the values the form SHOWED for them
    (``was:<key>``), and any field name that is neither editable nor the
    form's own.
    """
    fields: dict[str, str] = {}
    shown: dict[str, str] = {}
    unknown: list[str] = []
    for name in form:
        if name in FORM_FIELDS:
            continue
        if name in EDITABLE:
            fields[name] = str(form.get(name, ""))
        elif name.startswith(WAS) and name[len(WAS):] in EDITABLE:
            shown[name[len(WAS):]] = str(form.get(name, ""))
        else:
            unknown.append(str(name)[:64])
    return fields, shown, unknown


def _changed(key: str, value: Any, shown: Optional[str], current: Any) -> bool:
    """
    Whether ``key`` was CHANGED by the admin (fix round 1, I1): its validated
    value against the value the form showed -- validated the same way -- or,
    for a form that carried none, against the value in force.
    """
    if shown is None:
        return not _same(key, value, current)
    try:
        was, _note = validate_change(key, shown)
    except ChangeRefused:
        return str(value) != shown
    return not _same(key, value, was)


def origin_changes(changed: Mapping[str, Any], values: Mapping[str, Any]) -> bool:
    """Whether an apply moves ``llm.base_url`` to another origin (scheme, host, port)."""
    from engine.config import url_origin

    if "llm.base_url" not in changed:
        return False
    return url_origin(changed["llm.base_url"]) != url_origin(values.get("llm.base_url"))


def _same(key: str, value: Any, current: Any) -> bool:
    if key in LANE_KEYS or isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return float(value) == float(current)
        except (TypeError, ValueError):
            return False
    if isinstance(value, bool):
        return bool(current) is value and isinstance(current, bool)
    return str(value) == ("" if current is None else str(current))


def apply_post() -> Any:
    """``POST /admin/model``: validate, keep the changed keys, audit write-first, send ``llm.apply``."""
    from flask import request

    from engine.hosting import audit
    from engine.hosting.admin.guard import done_redirect
    from engine.hosting.admin.sessions import actor
    from engine.hosting.bus import BusError

    who = actor()
    ticked = ("1", "on", "true", "yes")
    anyway = str(request.form.get("apply_anyway", "") or "") in ticked
    send_key = str(request.form.get("send_key", "") or "") in ticked
    version = str(request.form.get("version", "") or "")
    fields, shown, unknown = _posted(request.form)
    if unknown:
        audit.refused("llm.apply", actor=who, target=unknown[0], detail={"reason": "not editable"})
        return model_page(f"Not changed: {unknown[0]} {NOT_EDITABLE}. Nothing was written.", 400)
    health = health_data()
    if "values" not in health:
        audit.refused("llm.apply", actor=who, detail={"reason": "the supervisor did not answer"})
        return model_page(
            f"Not changed: the supervisor did not answer ({health.get('error', 'unknown')}). Nothing was written.", 503
        )
    values = health.get("values") or {}
    locked = health.get("locked") or {}
    try:
        # Validated BEFORE the comparison and the lock check, so a value that
        # breaks its row (a URL with a password in it) is refused by its rule.
        # ONLY the fields the admin changed (fix round 1, I1): each compared
        # with the value the form showed, never with the value in force, so
        # a field left alone is never sent -- not even one that another admin
        # changed since this page was loaded.
        changed, notes = {}, []
        for key in sorted(fields):
            value, note = validate_change(key, fields[key])
            if not _changed(key, value, shown.get(key), values.get(key)):
                continue
            changed[key] = value
            if note:
                notes.append(note)
        withheld = bool((health.get("key") or {}).get("withheld"))
        releases = send_key and withheld and "llm.base_url" not in locked
        if releases and "llm.base_url" not in changed:
            # The key is withheld from the URL in force, and the admin now
            # sends it there: the same URL, applied with the key (fix round 1, I2).
            changed["llm.base_url"], _note = validate_change("llm.base_url", values.get("llm.base_url"))
        if not changed:
            return model_page("Nothing to change: every value is as the page showed it.")
        changed, more = validate_changes(changed, locked)
        notes += [n for n in more if n not in notes]
    except ChangeRefused as refusal:
        audit.refused("llm.apply", actor=who, target=refusal.key[:64], detail={"reason": refusal.code})
        return model_page(f"Not changed: {refusal}. Nothing was written.", 409 if refusal.code == "locked" else 400)
    current_version = str((health.get("layer") or {}).get("version") or "")
    stale = version != current_version or any(
        key in shown and _changed(key, values.get(key), shown[key], None) for key in changed
    )
    if stale:
        # The admin layer (or a value this form showed) changed since the
        # page was loaded: refused whole, nothing sent (fix round 1, I1).
        audit.refused(
            "llm.apply", actor=who, target=",".join(sorted(changed))[: audit.MAX_TEXT], detail={"reason": "stale"}
        )
        return model_page(f"Not changed: {STALE} Nothing was written.", 409)
    moves = origin_changes(changed, values) or (releases and "llm.base_url" in changed)
    keys = sorted(changed)
    target = ",".join(keys)
    if len(target) > audit.MAX_TEXT:
        target = f"{len(keys)} llm keys"
    ref = audit.new_ref()
    try:
        started: dict[str, Any] = {"apply_anyway": anyway}
        if moves:
            # The base URL moves to another origin: whether the API key goes
            # with it is the admin's explicit choice, recorded (fix round 1, I2).
            started["send_key"] = send_key
        audit.append("llm.apply", actor=who, result=audit.STARTED, target=target, detail=started, ref=ref)
    except audit.AuditUnavailable:
        return model_page(audit.UNAVAILABLE, 503)
    try:
        reply = _ask(
            "llm.apply",
            {
                "changes": changed,
                "apply_anyway": anyway,
                "send_key": bool(moves and send_key),
                "version": current_version,
                "actor": who.id,
                "actor_name": who.name,
                "address": who.address[:64],
                "ref": ref,
            },
            timeout=OP_SECONDS,
        )
    except BusError as exc:
        if exc.code in UNANSWERED:
            logger.warning("[admin] A model apply went unanswered (operation=llm.apply, error=%s)", exc.code)
            return model_page(f"Not confirmed: the supervisor did not answer ({exc.code}); see the progress below.", 504)
        try:
            audit.append(
                "llm.apply", actor=who, result=audit.REFUSED, target=target, detail={"error": exc.code}, ref=ref
            )
        except audit.AuditUnavailable:
            pass  # logged; the started row stands
        for code, status, text in APPLY_REFUSALS:
            if exc.code == code:
                return model_page(f"Not changed: {text}. Nothing was written.", status)
        return model_page(f"Not changed: the supervisor answered {exc.code}. Nothing was written.", 502)
    op_id = str(reply.get("op_id") or "")
    logger.info("[admin] Model apply queued (operation=llm.apply, op_id=%s, keys=%d, by=%s)", op_id, len(keys), who.id)
    said = f" ({'; '.join(notes)})" if notes else ""
    key_note = ""
    if moves:
        key_note = (
            " The API key WILL be sent to this host."
            if send_key
            else " The API key will NOT be sent to the new host: it is withheld until you apply the URL "
            "with \"send the API key to this host\" ticked."
        )
    return done_redirect(
        "/admin/model",
        f"Apply of {', '.join(keys)} queued as {op_id}{said}.{key_note} Every story drains, then each restarts "
        "in turn; players must reload their page. Its progress is below.",
    )


def register(blueprint: Any) -> None:
    """The Model server page, its apply and ``/admin/api/health.json``, on the admin blueprint."""
    from flask import jsonify

    @blueprint.get("/model")
    def model() -> Any:
        return model_page()

    @blueprint.post("/model")
    def model_apply() -> Any:
        return apply_post()

    @blueprint.get("/api/health.json")
    def health() -> Any:
        return jsonify(health_json())


__all__ = [
    "ADMIN_LAYER_FILE",
    "ADMIN_LAYER_PREV",
    "ChangeRefused",
    "EDITABLE",
    "EDITABLE_ORDER",
    "LANE_KEYS",
    "LAYER_ONLY",
    "STALE",
    "origin_changes",
    "SERVER_KEYS",
    "display_url",
    "nested",
    "register",
    "scrub",
    "validate_base_url",
    "validate_change",
    "validate_changes",
]

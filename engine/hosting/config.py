"""
Hosted Mode: the ``hosting:`` Block
===================================

A CLOSED SCHEMA (spec §6.9). ``validate`` refuses, naming the dotted key, a
key it does not know, a value of the wrong type and a number out of range, so
a typo never runs as a silent default and nothing can be hung off the block
that nobody reads. That is also the mechanical form of AGENTS.md rule 12: the
block holds the service's own knobs (who may log in, how fast, how large a
request), and there is no place in it for anything that judges what a player
writes. ``tests/test_hosting_config.py`` pins the key set to the spec's.

Each later v0.20.0 task that reads a new key (the supervisor's, the admin
panel's, the logs') adds it here, to ``config/default.yaml`` and to that test
in the same change. T10 added ``stories``, ``supervisor.*`` (bar T11's
``max_hold_seconds``) and ``observability.log_max_mb``/``log_keep``, with
spec §6.9's cross-check ``shutdown_seconds >= drain_seconds + stop_seconds``,
plus the stop's own tail (``TERMINATE_GRACE_SECONDS + KILL_WAIT_SECONDS``,
T10 fix round 1), plus the front door's stop after the workers'
(``FRONTDOOR_STOP_RESERVE_SECONDS``, T18 fix round 1). T11 added ``supervisor.max_hold_seconds``, checked at
least ``turn_deadline_seconds + MAX_HOLD_MARGIN_SECONDS`` (``max_hold_floor``;
fix round 1: it was ``3 x llm.timeout_seconds + 60``, which rested on a
per-phase timeout read as a total), and ``turn_deadline_seconds``. T14 added
``rate_limits.admin_actions_per_minute`` and ``admin.reauth_minutes``, and its
fix round 1 ``observability.audit_max_mb`` and ``observability.audit_keep``.
T17 added ``observability.retention_days`` (the metrics store's window), and
its fix round 1 ``observability.metrics_max_mb`` (the store's size cap).

Version: v0.5.0 [2026-10-06]
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

#: The block's own name, and the prefix every refusal names.
BLOCK = "hosting"


class HostingConfigError(RuntimeError):
    """
    Hosted mode refuses to start. The message names the key (``hosting.*``,
    ``llm.mcp.enabled``, ``CLOCKWORK_STUDIO``) and what to do about it.
    """

    def __init__(self, key: str, message: str) -> None:
        super().__init__(f"{key}: {message}")
        self.key = key


# (type, minimum, maximum). ``bool`` is its own type here: YAML's ``true`` is
# a bool, and a bool is never accepted where a number is (Python's bool is an
# int, which is how ``threads: true`` would otherwise mean one thread).
_INT = "int"
_BOOL = "bool"
_STR = "str"
#: A list of story slugs (``hosting.stories``): its range is its length.
_SLUGS = "slugs"

#: Every key the block may hold, dotted under ``hosting.``, with its type and,
#: for a number, its range. The ONLY place the key set is written in code.
SCHEMA: dict[str, tuple[str, int, int]] = {
    "enabled": (_BOOL, 0, 0),
    "public_origin": (_STR, 0, 0),
    "trusted_proxies": (_INT, 0, 8),
    "cookie_secure": (_BOOL, 0, 0),
    "session_days": (_INT, 1, 365),
    "secret_key": (_STR, 0, 0),
    "queue_wait_seconds": (_INT, 1, 3600),
    "utility_wait_seconds": (_INT, 1, 600),
    # T11 fix round 1: an admitted turn's wall-clock budget, utility calls
    # included; past it the turn ends through the model-failure path.
    "turn_deadline_seconds": (_INT, 1, 86400),
    # T12 fix round 1: a turn request's whole body must arrive within this,
    # before it may take a turn slot; past it, 408.
    "body_read_seconds": (_INT, 1, 600),
    "threads": (_INT, 1, 1024),
    # T13 fix round 1: one account's open game connections (WebSockets and
    # long polls) at once, at the front door and at each worker.
    "max_connections_per_account": (_INT, 1, 1024),
    "max_upload_mb": (_INT, 1, 512),
    "max_input_chars": (_INT, 1, 100_000),
    "max_saves_per_story": (_INT, 1, 100_000),
    "max_concurrent_logins": (_INT, 1, 64),
    "rate_limits.actions_per_minute": (_INT, 1, 10_000),
    "rate_limits.logins_per_minute": (_INT, 1, 10_000),
    "rate_limits.logins_per_minute_all": (_INT, 1, 100_000),
    # The admin panel (spec §14.7, T14): every POST under /admin, per admin;
    # and how long a re-auth lasts before the panel asks again.
    "rate_limits.admin_actions_per_minute": (_INT, 1, 10_000),
    "admin.reauth_minutes": (_INT, 1, 1440),
    # The supervisor (spec §14.3, T10). Empty `stories` passes the schema and
    # is refused by the supervisor at startup and FAILed by the doctor, each
    # naming the key (both also check every slug against the registry).
    "stories": (_SLUGS, 0, 64),
    "supervisor.health_interval_seconds": (_INT, 1, 3600),
    "supervisor.health_failures": (_INT, 1, 100),
    "supervisor.boot_seconds": (_INT, 1, 3600),
    "supervisor.hello_seconds": (_INT, 1, 30),
    "supervisor.max_restarts": (_INT, 1, 1000),
    "supervisor.restart_window_minutes": (_INT, 1, 1440),
    "supervisor.drain_seconds": (_INT, 1, 3600),
    "supervisor.stop_seconds": (_INT, 1, 600),
    "supervisor.shutdown_seconds": (_INT, 1, 7200),
    # T11 (fix round 1): a lane ticket held longer than this is reclaimed;
    # at least turn_deadline_seconds + MAX_HOLD_MARGIN_SECONDS.
    "supervisor.max_hold_seconds": (_INT, 1, 86400),
    "observability.log_max_mb": (_INT, 1, 1024),
    "observability.log_keep": (_INT, 1, 100),
    # T14 fix round 1 (M4): the audit log rotates by size and keeps this many
    # rotated files (engine/hosting/audit.py).
    "observability.audit_max_mb": (_INT, 1, 1024),
    "observability.audit_keep": (_INT, 1, 1000),
    # T17 (spec §14.10): metrics rows older than this are pruned hourly by
    # the supervisor (engine/hosting/supervisor/metrics.py).
    "observability.retention_days": (_INT, 1, 3650),
    # T17 fix round 1 (I1): the metrics file's cap; past it the oldest rows
    # of every table are deleted first.
    "observability.metrics_max_mb": (_INT, 1, 100_000),
}

#: How long a child gets after ``terminate()`` before ``kill()``, and how long
#: the kill is then waited for, in seconds. Fixed, not keys: they are the
#: operating system's part of a stop, and the shutdown's arithmetic holds them
#: (``shutdown_seconds >= drain_seconds + stop_seconds + both``).
TERMINATE_GRACE_SECONDS = 5
KILL_WAIT_SECONDS = 2

#: The end of a shutdown kept for the FRONT DOOR, stopped only after every
#: worker has drained and stopped (v0.20.0 T18 fix round 1), so a turn in
#: flight reaches its player before the relay closes. It runs no turn, so its
#: stop is short: 3 s for the bus ``shutdown``, then the terminate grace and
#: the kill's wait. ``shutdown_seconds`` holds it too.
FRONTDOOR_STOP_RESERVE_SECONDS = 3 + TERMINATE_GRACE_SECONDS + KILL_WAIT_SECONDS

#: The shortest cookie key accepted, in characters (spec §6.2; T7 fix round 1).
#: A short key can be found offline from one captured cookie, and then any
#: account's cookie forged.
MIN_SECRET_KEY_CHARS = 32

#: The fewest different characters an operator's cookie key may use (T7 fix
#: round 2): 32 characters of one repeated word is a guessable key.
MIN_SECRET_KEY_DISTINCT = 16

#: A pasted random hex key (``openssl rand -hex 32``) has only sixteen digits
#: to draw on and misses one about one time in four, so a hex key at least
#: ``MIN_HEX_KEY_CHARS`` long needs only ``MIN_HEX_KEY_DISTINCT`` (v0.20.1:
#: the first CI run refused its own such key).
MIN_HEX_KEY_CHARS = 64
MIN_HEX_KEY_DISTINCT = 10

#: The nested sections of the block (a key under them is in ``SCHEMA``).
SECTIONS = frozenset({"rate_limits", "admin", "supervisor", "observability"})


@dataclass(frozen=True)
class HostingSettings:
    """The validated block. ``secret_key`` is the expanded value, or ""."""

    enabled: bool
    public_origin: str
    trusted_proxies: int
    cookie_secure: bool
    session_days: int
    secret_key: str
    queue_wait_seconds: int
    utility_wait_seconds: int
    turn_deadline_seconds: int
    body_read_seconds: int
    threads: int
    max_connections_per_account: int
    max_upload_mb: int
    max_input_chars: int
    max_saves_per_story: int
    max_concurrent_logins: int
    actions_per_minute: int
    logins_per_minute: int
    logins_per_minute_all: int
    admin_actions_per_minute: int
    admin_reauth_minutes: int
    stories: tuple[str, ...]
    health_interval_seconds: int
    health_failures: int
    boot_seconds: int
    hello_seconds: int
    max_restarts: int
    restart_window_minutes: int
    drain_seconds: int
    stop_seconds: int
    shutdown_seconds: int
    max_hold_seconds: int
    log_max_mb: int
    log_keep: int
    audit_max_mb: int
    audit_keep: int
    retention_days: int
    metrics_max_mb: int


def _flatten(block: Mapping[str, Any]) -> dict[str, Any]:
    """The block as ``{dotted key: value}``, refusing an unknown key or section."""
    flat: dict[str, Any] = {}
    for key, value in block.items():
        name = str(key)
        if name in SECTIONS:
            if not isinstance(value, Mapping):
                raise HostingConfigError(f"{BLOCK}.{name}", "must be a mapping of keys")
            for inner, inner_value in value.items():
                flat[f"{name}.{inner}"] = inner_value
            continue
        flat[name] = value
    for dotted in flat:
        if dotted not in SCHEMA:
            raise HostingConfigError(
                f"{BLOCK}.{dotted}",
                "is not a hosting key (the block is a closed schema; see config/default.yaml)",
            )
    return flat


def _check(dotted: str, value: Any) -> Any:
    kind, low, high = SCHEMA[dotted]
    key = f"{BLOCK}.{dotted}"
    if kind == _BOOL:
        if not isinstance(value, bool):
            raise HostingConfigError(key, f"must be true or false, not {type(value).__name__}")
        return value
    if kind == _STR:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise HostingConfigError(key, f"must be a string, not {type(value).__name__}")
        return value
    if kind == _SLUGS:
        if value is None:
            return ()
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise HostingConfigError(key, "must be a list of story slugs (python launcher.py --list-games)")
        if len(value) > high:
            raise HostingConfigError(key, f"may name at most {high} stories, not {len(value)}")
        duplicate = sorted({v for v in value if value.count(v) > 1})
        if duplicate:
            raise HostingConfigError(key, f"names {duplicate[0]!r} twice (one worker per story)")
        return tuple(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HostingConfigError(key, f"must be a whole number, not {type(value).__name__}")
    if not low <= value <= high:
        raise HostingConfigError(key, f"must be between {low} and {high}, not {value}")
    return value


def check_public_origin(value: str) -> str:
    """
    ``""``, or exactly ``scheme://host[:port]``: http or https, no path, no
    query, no credentials. It is compared byte for byte with a browser's
    ``Origin`` header (Socket.IO's own check), so a trailing slash or a path
    would silently match nothing.
    """
    text = value.strip()
    if not text:
        return ""
    key = f"{BLOCK}.public_origin"
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise HostingConfigError(key, f"is not a URL ({exc})") from exc
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or "@" in parts.netloc
        or f"{parts.scheme}://{parts.netloc}" != text
    ):
        raise HostingConfigError(
            key,
            'must be "" or exactly scheme://host[:port], e.g. "https://play.example.org" '
            "(no path, no trailing slash)",
        )
    return text


def check_secret_key(key: str, *, source: str, configured: bool = True) -> str:
    """
    ``key``, or ``HostingConfigError`` naming ``hosting.secret_key`` when it is
    set and shorter than ``MIN_SECRET_KEY_CHARS``, or (a ``configured`` key,
    one an operator typed or pasted) that is one shorter pattern repeated
    (``"changeme" * 4``) or made of fewer than ``MIN_SECRET_KEY_DISTINCT``
    different characters -- ``MIN_HEX_KEY_DISTINCT`` for a hex key of at least
    ``MIN_HEX_KEY_CHARS``, as ``openssl rand -hex 32`` prints. ``""`` means
    "generate one" and passes. ``source`` says where the key came from.

    The engine's own generated key (``configured=False``: the key file) is
    checked for length only. It is 64 hex digits from ``secrets``, and a
    random hex string that happens to miss one of the sixteen digits (about
    one in four do) is no weaker for it.
    """
    if not key:
        return key
    generator = (
        'Make one with python -c "import secrets; print(secrets.token_urlsafe(32))", '
        "or leave it empty to have one generated"
    )
    if len(key) < MIN_SECRET_KEY_CHARS:
        raise HostingConfigError(
            f"{BLOCK}.secret_key",
            f"the cookie key from {source} is {len(key)} characters; it must be at least "
            f"{MIN_SECRET_KEY_CHARS} (a short key lets anyone forge a login). {generator}",
        )
    if not configured:
        return key
    if (key + key).find(key, 1) < len(key):
        raise HostingConfigError(
            f"{BLOCK}.secret_key",
            f"the cookie key from {source} is one shorter pattern repeated "
            f"(a repeated word can be guessed). {generator}",
        )
    distinct = len(set(key))
    floor = MIN_SECRET_KEY_DISTINCT
    if len(key) >= MIN_HEX_KEY_CHARS and all(c in string.hexdigits for c in key):
        floor = MIN_HEX_KEY_DISTINCT
    if distinct < floor:
        raise HostingConfigError(
            f"{BLOCK}.secret_key",
            f"the cookie key from {source} uses only {distinct} different characters; "
            f"it needs at least {floor} (a repeated word can be guessed). "
            f"{generator}",
        )
    return key


#: How far past ``turn_deadline_seconds`` a ticket may legitimately be held
#: (T11 fix round 1). At the deadline no model call starts and the one in
#: flight is cut (its timeout was capped to what was left), so what remains
#: is the turn's own engine work -- committing, the autosave -- in seconds.
#: Two minutes leaves a wide margin for a loaded host.
MAX_HOLD_MARGIN_SECONDS = 120


def max_hold_floor(turn_deadline_seconds: int) -> int:
    """
    The least ``supervisor.max_hold_seconds`` may be (spec §6.9): a hosted
    turn's wall-clock deadline plus ``MAX_HOLD_MARGIN_SECONDS``. A worker
    ends every turn by its deadline, so a ticket held past this is a hung
    turn, and the supervisor's reclaim is a backstop, never the clock a
    healthy turn runs against.
    """
    return int(turn_deadline_seconds) + MAX_HOLD_MARGIN_SECONDS


def validate(block: Any, *, secret_key: str = "") -> HostingSettings:
    """
    Check the raw ``hosting:`` block (as the config layers hold it, before
    ``${...}`` expansion) and return it typed.

    Args:
        block: The block.
        secret_key: ``hosting.secret_key`` as ``get_config().get`` expands it.

    Raises:
        HostingConfigError: naming the first key that is unknown, missing,
            of the wrong type or out of range.
    """
    if not isinstance(block, Mapping):
        raise HostingConfigError(BLOCK, "must be a mapping of keys")
    flat = _flatten(block)
    values: dict[str, Any] = {}
    for dotted in SCHEMA:
        if dotted not in flat:
            raise HostingConfigError(f"{BLOCK}.{dotted}", "is missing (config/default.yaml sets it)")
        values[dotted] = _check(dotted, flat[dotted])
    expanded = (secret_key if isinstance(secret_key, str) else "").strip()
    check_secret_key(expanded, source="hosting.secret_key")
    # Spec §6.9's cross-check, with the stop's own tail (T10 fix round 1):
    # the whole shutdown holds a worker's drain, its stop, the terminate grace
    # and the kill's wait, and then (T18 fix round 1) the front door's own
    # stop after them, so it is never cut short of any of them.
    tail = TERMINATE_GRACE_SECONDS + KILL_WAIT_SECONDS
    needed = (
        values["supervisor.drain_seconds"]
        + values["supervisor.stop_seconds"]
        + tail
        + FRONTDOOR_STOP_RESERVE_SECONDS
    )
    if values["supervisor.shutdown_seconds"] < needed:
        raise HostingConfigError(
            f"{BLOCK}.supervisor.shutdown_seconds",
            f"must be at least drain_seconds + stop_seconds + {tail} (the terminate grace and the kill) "
            f"+ {FRONTDOOR_STOP_RESERVE_SECONDS} (the front door's stop, last) = {needed}, not "
            f"{values['supervisor.shutdown_seconds']}: the shutdown drains and stops each story, "
            "then the front door",
        )
    floor = max_hold_floor(values["turn_deadline_seconds"])
    if values["supervisor.max_hold_seconds"] < floor:
        raise HostingConfigError(
            f"{BLOCK}.supervisor.max_hold_seconds",
            f"must be at least turn_deadline_seconds + {MAX_HOLD_MARGIN_SECONDS} = {floor}, not "
            f"{values['supervisor.max_hold_seconds']}: a worker ends every turn by "
            "hosting.turn_deadline_seconds, and the supervisor reclaims only a ticket held well "
            "past it (a hung turn); a shorter hold would reclaim the ticket of a turn still "
            "inside its deadline",
        )
    return HostingSettings(
        enabled=values["enabled"],
        public_origin=check_public_origin(values["public_origin"]),
        trusted_proxies=values["trusted_proxies"],
        cookie_secure=values["cookie_secure"],
        session_days=values["session_days"],
        secret_key=expanded,
        queue_wait_seconds=values["queue_wait_seconds"],
        utility_wait_seconds=values["utility_wait_seconds"],
        turn_deadline_seconds=values["turn_deadline_seconds"],
        body_read_seconds=values["body_read_seconds"],
        threads=values["threads"],
        max_connections_per_account=values["max_connections_per_account"],
        max_upload_mb=values["max_upload_mb"],
        max_input_chars=values["max_input_chars"],
        max_saves_per_story=values["max_saves_per_story"],
        max_concurrent_logins=values["max_concurrent_logins"],
        actions_per_minute=values["rate_limits.actions_per_minute"],
        logins_per_minute=values["rate_limits.logins_per_minute"],
        logins_per_minute_all=values["rate_limits.logins_per_minute_all"],
        admin_actions_per_minute=values["rate_limits.admin_actions_per_minute"],
        admin_reauth_minutes=values["admin.reauth_minutes"],
        stories=values["stories"],
        health_interval_seconds=values["supervisor.health_interval_seconds"],
        health_failures=values["supervisor.health_failures"],
        boot_seconds=values["supervisor.boot_seconds"],
        hello_seconds=values["supervisor.hello_seconds"],
        max_restarts=values["supervisor.max_restarts"],
        restart_window_minutes=values["supervisor.restart_window_minutes"],
        drain_seconds=values["supervisor.drain_seconds"],
        stop_seconds=values["supervisor.stop_seconds"],
        shutdown_seconds=values["supervisor.shutdown_seconds"],
        max_hold_seconds=values["supervisor.max_hold_seconds"],
        log_max_mb=values["observability.log_max_mb"],
        log_keep=values["observability.log_keep"],
        audit_max_mb=values["observability.audit_max_mb"],
        audit_keep=values["observability.audit_keep"],
        retention_days=values["observability.retention_days"],
        metrics_max_mb=values["observability.metrics_max_mb"],
    )


def story_problems(slugs: Any) -> list[tuple[str, str]]:
    """
    ``(slug, problem)`` for each of ``hosting.stories`` that the registry
    does not know or that does not validate, without activating any; one
    ``("", "is empty ...")`` row for an empty list. ``[]``: all sound.
    Shared by the supervisor's startup refusal and the doctor's row
    (spec §14.3, §7.4).
    """
    from engine.games import registry

    names = list(slugs or ())
    if not names:
        return [("", "is empty: name at least one story (python launcher.py --list-games)")]
    problems: list[tuple[str, str]] = []
    for slug in names:
        manifest = registry.get(slug)
        if manifest is None:
            problems.append((slug, "is not an installed story (python launcher.py --list-games)"))
            continue
        found = registry.validate(manifest)
        if found:
            problems.append((slug, f"does not validate: {found[0]}"))
    return problems


def load(cfg: Any) -> HostingSettings:
    """The running config's block, validated (``cfg`` is a ``ConfigManager``)."""
    raw = cfg._raw(BLOCK, None)
    secret = cfg.get(f"{BLOCK}.secret_key", "")
    return validate(raw, secret_key=str(secret or ""))


__all__ = [
    "BLOCK",
    "HostingConfigError",
    "HostingSettings",
    "KILL_WAIT_SECONDS",
    "FRONTDOOR_STOP_RESERVE_SECONDS",
    "SCHEMA",
    "TERMINATE_GRACE_SECONDS",
    "SECTIONS",
    "MIN_SECRET_KEY_CHARS",
    "MIN_HEX_KEY_CHARS",
    "MIN_HEX_KEY_DISTINCT",
    "MIN_SECRET_KEY_DISTINCT",
    "check_public_origin",
    "check_secret_key",
    "load",
    "MAX_HOLD_MARGIN_SECONDS",
    "max_hold_floor",
    "story_problems",
    "validate",
]

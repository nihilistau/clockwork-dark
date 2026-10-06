"""
Hosted Mode: the Metrics Schema
===============================

OBSERVABILITY, NOT MODERATION (spec §14.10, AGENTS.md rule 12). The metrics
store records how the service ran -- timings, waits, counts, and errors by
reference -- and nothing of what was played: no prompt, narration, choice,
typed action, player name, save content, model output, reasoning or log
message text. No field rates, classifies, flags or filters content, and none
can be added without failing ``tests/test_metrics_schema.py``, which pins
``KINDS`` to the spec's table.

THE SIX KINDS, each a closed set of fields (``KINDS``). Every field is one of:

- a timestamp (``ts``: wall-clock seconds, a number);
- a number of milliseconds, or an exit code (an integer);
- an id matching its pattern: an account (``u_`` and 12 hex digits, as
  ``engine/hosting/accounts.py`` mints it), a story slug (one of
  ``hosting.stories`` when the caller names them), a process
  (``frontdoor``, ``supervisor`` or ``worker-<slug>``: the name of its log
  file), an 8-hex reference (``errors.new_ref``);
- a NAME matching ``NAME_PATTERN`` (``exc_class`` and ``logger`` only: a
  Python identifier path, which carries no message text);
- a member of a fixed enum.

There is no free string anywhere. ``validate(event)`` answers the event
normalized, or None: an unknown kind, an unknown or missing field, or a value
that fails its type is refused, and the store counts it (``metrics_rejected``)
and never keeps it as text.

THE ORACLE PROJECTION (``project_oracle``). The Oracle's ``metrics()`` and
``recent()`` (``engine/telemetry/oracle.py``) do NOT hold only numbers:
``unearned_claims`` is keyed by whatever stat name the model claimed,
``TurnRecord.evil_progress`` is play state, and ``assistant_intent`` and
``challenge_kind`` are free strings. So ``oracle.snapshot`` passes through
this projection before it leaves the worker, and again through
``clean_projection`` in the supervisor:

- counts, latencies and totals, as numbers;
- rule ids only if they match ``RULE_ID_PATTERN`` (``R003``);
- ``unearned_claims`` collapsed to a count and the largest delta, with no
  stat names;
- ``challenge_kind`` and ``assistant_intent`` only as members of enums built
  from the engine's own tables (``engine.challenges.spec.KINDS``,
  ``engine.agents.assistant_director``'s ``INTENT_*``), otherwise counted as
  ``other``;
- no ``evil_progress``, and nothing else from a turn's state.

``PROJECTION_KEYS`` and ``RECENT_KEYS`` are pinned beside ``KINDS``.

Version: v0.1.0 [2026-10-06]
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

#: A name: a Python identifier path (``exc_class``, ``logger``). No spaces, no
#: quotes, no punctuation but dots: it cannot carry a sentence.
NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")

#: An account id, as ``engine/hosting/accounts.py`` mints it.
ACCOUNT_PATTERN = re.compile(r"^u_[0-9a-f]{12}$")

#: A story slug's shape (and, when the caller names them, one of ``hosting.stories``).
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: A player-facing error reference (``engine.hosting.errors.new_ref``).
REF_PATTERN = re.compile(r"^[0-9a-f]{8}$")

#: A governance rule id (``R001``).
RULE_ID_PATTERN = re.compile(r"^[A-Z]\d{3}$")

#: The two processes that are not a story's worker.
FRONTDOOR_PROCESS = "frontdoor"
SUPERVISOR_PROCESS = "supervisor"

#: The latest timestamp accepted (the year 5138): a sanity bound, not a clock.
MAX_TS = 1e11

#: The longest duration accepted, in milliseconds (about 115 days).
MAX_MS = 1e10

#: An exit code's range.
MAX_EXIT_CODE = 2**31

# Field types.
TIMESTAMP = "timestamp"
MILLISECONDS = "milliseconds"
EXIT_CODE = "exit_code"
ACCOUNT = "account"
STORY = "story"
PROCESS = "process"
REF = "ref"
NAME = "name"
ENUM = "enum"

#: Every field type there is (the schema test holds every field to one).
TYPES = frozenset({TIMESTAMP, MILLISECONDS, EXIT_CODE, ACCOUNT, STORY, PROCESS, REF, NAME, ENUM})


@dataclass(frozen=True)
class Field:
    """One field: its type, its enum when it is one, and whether it may be null."""

    type: str
    values: tuple[str, ...] = ()
    nullable: bool = False

    @property
    def sql(self) -> str:
        """Its SQLite column type."""
        if self.type in (TIMESTAMP, MILLISECONDS):
            return "REAL"
        if self.type == EXIT_CODE:
            return "INTEGER"
        return "TEXT"


_TS = Field(TIMESTAMP)
_MS = Field(MILLISECONDS)
_STORY = Field(STORY)
_ACCOUNT_OR_NONE = Field(ACCOUNT, nullable=True)

#: THE SIX KINDS (spec §14.10's table), each field typed. The only place the
#: schema is written; the store's tables are built from it.
KINDS: dict[str, dict[str, Field]] = {
    # A worker: run_guarded (admission wait, duration, outcome) and the limits.
    "turn": {
        "ts": _TS,
        "story": _STORY,
        "account": _ACCOUNT_OR_NONE,
        "admit_wait_ms": _MS,
        "duration_ms": _MS,
        "outcome": Field(ENUM, ("ok", "busy", "error", "refused_cap", "refused_rate")),
    },
    # The supervisor: it runs the queue.
    "lane": {
        "ts": _TS,
        "story": _STORY,
        "account": _ACCOUNT_OR_NONE,
        "lane": Field(ENUM, ("narration", "utility")),
        "wait_ms": _MS,
        "hold_ms": _MS,
        "outcome": Field(ENUM, ("granted", "timeout", "cancelled", "other_window")),
    },
    # A worker's session store.
    "session": {
        "ts": _TS,
        "story": _STORY,
        "account": _ACCOUNT_OR_NONE,
        "event": Field(ENUM, ("created", "resumed", "released", "swept", "ended_by_admin")),
    },
    # The front door's login (account null for a name that is no account).
    "login": {
        "ts": _TS,
        "account": _ACCOUNT_OR_NONE,
        "outcome": Field(ENUM, ("ok", "failed", "limited", "disabled", "must_change")),
    },
    # public_error (ref), and the ERROR logging handler (no ref; the class
    # and the logger's name, never the message).
    "error": {
        "ts": _TS,
        "process": Field(PROCESS),
        "ref": Field(REF, nullable=True),
        "exc_class": Field(NAME, nullable=True),
        "logger": Field(NAME),
    },
    # The supervisor, of its children.
    "process": {
        "ts": _TS,
        "process": Field(PROCESS),
        "event": Field(ENUM, ("started", "ready", "unhealthy", "exited", "restarted", "held_down", "stopped")),
        "exit_code": Field(EXIT_CODE, nullable=True),
    },
}

#: The fields the supervisor STAMPS from the connection a metric came on,
#: whatever the sender said (spec §14.2).
STAMPED_FIELDS = ("process", "story")

#: How a lane name outside ``KINDS["lane"]`` is treated: not recorded (a
#: profile's custom lane; see docs/HOSTING.md § Metrics).
LANES = KINDS["lane"]["lane"].values


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check(spec: Field, value: Any, stories: Optional[frozenset[str]]) -> tuple[bool, Any]:
    """``(ok, normalized value)`` for one field."""
    if value is None:
        return spec.nullable, None
    kind = spec.type
    if kind == TIMESTAMP:
        return (_number(value) and 0 <= value <= MAX_TS), (float(value) if _number(value) else None)
    if kind == MILLISECONDS:
        return (_number(value) and 0 <= value <= MAX_MS), (round(float(value), 3) if _number(value) else None)
    if kind == EXIT_CODE:
        ok = isinstance(value, int) and not isinstance(value, bool) and -MAX_EXIT_CODE <= value <= MAX_EXIT_CODE
        return ok, value
    if not isinstance(value, str):
        return False, None
    if kind == ENUM:
        return value in spec.values, value
    if kind == ACCOUNT:
        return bool(ACCOUNT_PATTERN.fullmatch(value)), value
    if kind == STORY:
        return bool(SLUG_PATTERN.fullmatch(value)) and (stories is None or value in stories), value
    if kind == PROCESS:
        return is_process(value, stories), value
    if kind == REF:
        return bool(REF_PATTERN.fullmatch(value)), value
    if kind == NAME:
        return bool(NAME_PATTERN.fullmatch(value)), value
    return False, None


def is_process(value: Any, stories: Optional[Iterable[str]] = None) -> bool:
    """``frontdoor``, ``supervisor`` or ``worker-<slug>`` (a slug of ``stories``, when named)."""
    if not isinstance(value, str):
        return False
    if value in (FRONTDOOR_PROCESS, SUPERVISOR_PROCESS):
        return True
    if not value.startswith("worker-"):
        return False
    slug = value[len("worker-"):]
    if not SLUG_PATTERN.fullmatch(slug):
        return False
    return stories is None or slug in set(stories)


def validate(event: Any, *, stories: Optional[Iterable[str]] = None) -> Optional[dict[str, Any]]:
    """
    ``event`` (``{"kind": ..., <fields>}``) normalized, or None when it has
    an unknown kind, an unknown or missing field, or a value that fails its
    type. ``stories``: the instance's ``hosting.stories``, which a story and
    a worker's process name must be one of.
    """
    if not isinstance(event, Mapping):
        return None
    kind = event.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        return None
    fields = KINDS[kind]
    if set(event) != {"kind"} | set(fields):
        return None
    allowed = frozenset(stories) if stories is not None else None
    clean: dict[str, Any] = {"kind": kind}
    for name, spec in fields.items():
        ok, value = _check(spec, event[name], allowed)
        if not ok:
            return None
        clean[name] = value
    return clean


def safe_name(value: Any, fallback: Optional[str] = None) -> Optional[str]:
    """``value`` if it is a NAME (``NAME_PATTERN``), else ``fallback``."""
    return value if isinstance(value, str) and NAME_PATTERN.fullmatch(value) else fallback


def exception_name(exc_type: Any) -> Optional[str]:
    """
    An exception class as a NAME: ``module.QualName`` (``builtins`` left
    off), or its bare name, or None when neither fits the pattern. A class
    name is code, never a message.
    """
    if not isinstance(exc_type, type):
        return None
    module = getattr(exc_type, "__module__", "") or ""
    qualname = getattr(exc_type, "__qualname__", "") or ""
    full = qualname if module in ("", "builtins") else f"{module}.{qualname}"
    return safe_name(full) or safe_name(getattr(exc_type, "__name__", ""))


# ---------------------------------------------------------------------------
# the Oracle projection
# ---------------------------------------------------------------------------

#: The projection's keys, exactly (pinned by tests/test_metrics_schema.py).
PROJECTION_KEYS = (
    "turns",
    "violation_rate",
    "violations_total",
    "violations_by_rule",
    "violations_other_rules",
    "assistant_intervention_rate",
    "assistant_misled_count",
    "gifts",
    "avg_latency_ms",
    "unearned_claims_count",
    "unearned_claims_largest_delta",
    "challenges_started",
    "recent",
)

#: A recent turn's keys, exactly: ``TurnRecord`` less ``evil_progress``.
RECENT_KEYS = (
    "turn",
    "latency_ms",
    "violations",
    "rule_ids",
    "assistant_spoke",
    "assistant_intent",
    "assistant_reliable",
    "gift",
    "tools",
    "challenge_kind",
)

#: What a string outside its enum is counted as.
OTHER = "other"

#: The most recent turns a projection carries (the Oracle's own default).
MAX_RECENT = 20

#: The most rule ids one recent turn carries.
MAX_RULE_IDS = 16


def assistant_intents() -> frozenset[str]:
    """The Assistant director's intents (``engine.agents.assistant_director``), the enum."""
    from engine.agents import assistant_director as director

    return frozenset(
        value for name, value in vars(director).items() if name.startswith("INTENT_") and isinstance(value, str)
    )


def challenge_kinds() -> frozenset[str]:
    """The registered challenge kinds (``engine.challenges.spec.KINDS``), the enum."""
    from engine.challenges.spec import KINDS as CHALLENGE_KINDS

    return frozenset(CHALLENGE_KINDS)


def _count(value: Any) -> int:
    return int(value) if _number(value) and value >= 0 else 0


def _real(value: Any, digits: int = 3) -> float:
    return round(float(value), digits) if _number(value) else 0.0


def _member(value: Any, enum: frozenset[str], *, empty: str = "") -> str:
    """``value`` if it is in ``enum``; ``empty`` for an empty or missing one; else ``other``."""
    if value is None or value == "":
        return empty
    return value if isinstance(value, str) and value in enum else OTHER


def _rule_counts(raw: Any) -> tuple[dict[str, int], int]:
    """``violations_by_rule`` kept to well-formed rule ids; the rest summed."""
    kept: dict[str, int] = {}
    other = 0
    if isinstance(raw, Mapping):
        for rule, count in raw.items():
            if isinstance(rule, str) and RULE_ID_PATTERN.fullmatch(rule):
                kept[rule] = kept.get(rule, 0) + _count(count)
            else:
                other += _count(count)
    return dict(sorted(kept.items())), other


def _kind_counts(raw: Any, enum: frozenset[str]) -> dict[str, int]:
    """``challenges_started`` keyed by enum members, everything else under ``other``."""
    counts: dict[str, int] = {}
    if isinstance(raw, Mapping):
        for kind, count in raw.items():
            key = _member(kind, enum, empty=OTHER)
            counts[key] = counts.get(key, 0) + _count(count)
    return dict(sorted(counts.items()))


def _largest(claims: Any) -> int:
    """The largest delta (by size, sign kept) over every claim, with no stat name."""
    largest = 0
    if isinstance(claims, Mapping):
        for claim in claims.values():
            delta = claim.get("max_delta") if isinstance(claim, Mapping) else None
            if _number(delta) and abs(int(delta)) > abs(largest):
                largest = int(delta)
    return largest


def _claim_count(metrics: Mapping[str, Any]) -> int:
    total = metrics.get("unearned_claims_total")
    if _number(total):
        return _count(total)
    claims = metrics.get("unearned_claims")
    if isinstance(claims, Mapping):
        return sum(_count(c.get("count")) for c in claims.values() if isinstance(c, Mapping))
    return 0


def _recent_row(row: Any, intents: frozenset[str], kinds: frozenset[str]) -> dict[str, Any]:
    row = row if isinstance(row, Mapping) else {}
    rules = row.get("rule_ids")
    rule_ids = [r for r in rules if isinstance(r, str) and RULE_ID_PATTERN.fullmatch(r)] if isinstance(rules, list) else []
    return {
        "turn": _count(row.get("turn")),
        "latency_ms": _real(row.get("latency_ms"), 1),
        "violations": _count(row.get("violations")),
        "rule_ids": rule_ids[:MAX_RULE_IDS],
        "assistant_spoke": bool(row.get("assistant_spoke") is True),
        "assistant_intent": _member(row.get("assistant_intent"), intents, empty=OTHER),
        "assistant_reliable": bool(row.get("assistant_reliable") is True),
        "gift": bool(row.get("gift") is True),
        "tools": _count(row.get("tools")),
        "challenge_kind": _member(row.get("challenge_kind"), kinds),
    }


def project_oracle(
    metrics: Any,
    recent: Any,
    *,
    intents: Optional[frozenset[str]] = None,
    kinds: Optional[frozenset[str]] = None,
) -> dict[str, Any]:
    """
    The Oracle's ``metrics()`` and ``recent()`` as ``PROJECTION_KEYS``: numbers,
    well-formed rule ids and enum members only (see the module docstring).
    ``intents``/``kinds``: the enums (the engine's own tables by default).
    """
    intents = assistant_intents() if intents is None else intents
    kinds = challenge_kinds() if kinds is None else kinds
    metrics = metrics if isinstance(metrics, Mapping) else {}
    rules, other_rules = _rule_counts(metrics.get("violations_by_rule"))
    rows = list(recent)[-MAX_RECENT:] if isinstance(recent, list) else []
    return {
        "turns": _count(metrics.get("turns")),
        "violation_rate": _real(metrics.get("violation_rate")),
        "violations_total": _count(metrics.get("violations_total")),
        "violations_by_rule": rules,
        "violations_other_rules": other_rules,
        "assistant_intervention_rate": _real(metrics.get("assistant_intervention_rate")),
        "assistant_misled_count": _count(metrics.get("assistant_misled_count")),
        "gifts": _count(metrics.get("gifts")),
        "avg_latency_ms": _real(metrics.get("avg_latency_ms"), 1),
        "unearned_claims_count": _claim_count(metrics),
        "unearned_claims_largest_delta": _largest(metrics.get("unearned_claims")),
        "challenges_started": _kind_counts(metrics.get("challenges_started"), kinds),
        "recent": [_recent_row(r, intents, kinds) for r in rows],
    }


def clean_projection(
    projected: Any,
    *,
    intents: Optional[frozenset[str]] = None,
    kinds: Optional[frozenset[str]] = None,
) -> dict[str, Any]:
    """
    A projection as it came back over the bus, held to ``PROJECTION_KEYS``
    again by the supervisor (a worker is inside the trust boundary, but the
    panel shows only what this function lets through).
    """
    intents = assistant_intents() if intents is None else intents
    kinds = challenge_kinds() if kinds is None else kinds
    data = projected if isinstance(projected, Mapping) else {}
    rules, other_rules = _rule_counts(data.get("violations_by_rule"))
    delta = data.get("unearned_claims_largest_delta")
    rows = data.get("recent")
    return {
        "turns": _count(data.get("turns")),
        "violation_rate": _real(data.get("violation_rate")),
        "violations_total": _count(data.get("violations_total")),
        "violations_by_rule": rules,
        "violations_other_rules": other_rules + _count(data.get("violations_other_rules")),
        "assistant_intervention_rate": _real(data.get("assistant_intervention_rate")),
        "assistant_misled_count": _count(data.get("assistant_misled_count")),
        "gifts": _count(data.get("gifts")),
        "avg_latency_ms": _real(data.get("avg_latency_ms"), 1),
        "unearned_claims_count": _count(data.get("unearned_claims_count")),
        "unearned_claims_largest_delta": int(delta) if _number(delta) else 0,
        "challenges_started": _kind_counts(data.get("challenges_started"), kinds | {OTHER}),
        "recent": [_recent_row(r, intents | {OTHER}, kinds | {OTHER}) for r in (rows if isinstance(rows, list) else [])][
            -MAX_RECENT:
        ],
    }


__all__ = [
    "ACCOUNT_PATTERN",
    "FRONTDOOR_PROCESS",
    "Field",
    "KINDS",
    "LANES",
    "NAME_PATTERN",
    "OTHER",
    "PROJECTION_KEYS",
    "RECENT_KEYS",
    "REF_PATTERN",
    "RULE_ID_PATTERN",
    "SLUG_PATTERN",
    "STAMPED_FIELDS",
    "SUPERVISOR_PROCESS",
    "TYPES",
    "assistant_intents",
    "challenge_kinds",
    "clean_projection",
    "exception_name",
    "is_process",
    "project_oracle",
    "safe_name",
    "validate",
]

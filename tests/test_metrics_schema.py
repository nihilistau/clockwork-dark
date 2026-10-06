"""
The closed metrics schema and the Oracle projection (v0.20.0 T17, spec §14.10).

OBSERVABILITY, NOT MODERATION (AGENTS.md rule 12):

- the six kinds and their field sets are pinned to spec §14.10's table, so a
  field added to any kind fails here;
- every field is a timestamp, a number, a patterned id, a patterned NAME or a
  member of a fixed enum -- no free string -- and an ``exc_class`` holding a
  space or a quote is refused;
- the Oracle projection's key set is pinned, and a stat name the model
  claimed, an unknown ``challenge_kind`` or ``assistant_intent`` and
  ``evil_progress`` in the raw input are absent from its output;
- a word scan over every kind, field, enum member and projection key finds
  nothing that rates, flags, filters or moderates content.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from engine.hosting import metrics_schema as schema
from engine.hosting.metrics_schema import (
    KINDS,
    NAME_PATTERN,
    PROJECTION_KEYS,
    RECENT_KEYS,
    clean_projection,
    project_oracle,
    validate,
)

STORIES = ("clockwork-dark", "dev-story")
ACCOUNT = "u_0123456789ab"

#: Spec §14.10's table, exactly.
SPEC_FIELDS = {
    "turn": {"ts", "story", "account", "admit_wait_ms", "duration_ms", "outcome"},
    "lane": {"ts", "story", "account", "lane", "wait_ms", "hold_ms", "outcome"},
    "session": {"ts", "story", "account", "event"},
    "login": {"ts", "account", "outcome"},
    "error": {"ts", "process", "ref", "exc_class", "logger"},
    "process": {"ts", "process", "event", "exit_code"},
}

SPEC_ENUMS = {
    ("turn", "outcome"): {"ok", "busy", "error", "refused_cap", "refused_rate"},
    ("lane", "lane"): {"narration", "utility"},
    ("lane", "outcome"): {"granted", "timeout", "cancelled", "other_window"},
    ("session", "event"): {"created", "resumed", "released", "swept", "ended_by_admin"},
    ("login", "outcome"): {"ok", "failed", "limited", "disabled", "must_change"},
    ("process", "event"): {"started", "ready", "unhealthy", "exited", "restarted", "held_down", "stopped"},
}

#: One valid event of each kind.
GOOD = {
    "turn": {"kind": "turn", "ts": 1_790_000_000.5, "story": "clockwork-dark", "account": ACCOUNT,
             "admit_wait_ms": 12.5, "duration_ms": 3400, "outcome": "ok"},
    "lane": {"kind": "lane", "ts": 1_790_000_000, "story": "dev-story", "account": None, "lane": "utility",
             "wait_ms": 0, "hold_ms": 80.0, "outcome": "granted"},
    "session": {"kind": "session", "ts": 1_790_000_000, "story": "dev-story", "account": ACCOUNT, "event": "swept"},
    "login": {"kind": "login", "ts": 1_790_000_000, "account": None, "outcome": "failed"},
    "error": {"kind": "error", "ts": 1_790_000_000, "process": "worker-dev-story", "ref": "3fa9c2e1",
              "exc_class": "httpx.ConnectError", "logger": "engine.hosting.errors"},
    "process": {"kind": "process", "ts": 1_790_000_000, "process": "frontdoor", "event": "exited", "exit_code": -9},
}

#: Words a schema that rated, classified or filtered what players write would
#: need. None may appear in any name the schema or the projection holds.
FORBIDDEN_WORDS = (
    "content", "rating", "rated", "safety", "safe_", "moderat", "flag", "filter", "explicit", "nsfw",
    "toxic", "sexual", "violence", "violent", "intensity", "tier", "classif", "category", "score",
    "sentiment", "profan", "obscen", "abuse", "harm", "offens", "mature", "adult", "censor", "block",
    "allowed", "banned", "text", "message", "prompt", "choice", "player_name", "label",
)
# ("narration" is not in the list: it is the model server's lane of that name.)


def test_the_kinds_and_their_fields_are_the_spec_s() -> None:
    assert {kind: set(fields) for kind, fields in KINDS.items()} == SPEC_FIELDS


def test_the_enums_are_the_spec_s() -> None:
    found = {
        (kind, name): set(spec.values)
        for kind, fields in KINDS.items()
        for name, spec in fields.items()
        if spec.type == schema.ENUM
    }
    assert found == SPEC_ENUMS


def test_every_field_is_typed_and_no_field_is_a_free_string() -> None:
    for kind, fields in KINDS.items():
        for name, spec in fields.items():
            assert spec.type in schema.TYPES, (kind, name)
            if spec.type == schema.ENUM:
                assert spec.values, (kind, name)
    # The only NAME fields are the exception's class and the logger's name.
    names = {(k, n) for k, fields in KINDS.items() for n, spec in fields.items() if spec.type == schema.NAME}
    assert names == {("error", "exc_class"), ("error", "logger")}
    assert NAME_PATTERN.pattern == r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$"


@pytest.mark.parametrize("kind", sorted(GOOD))
def test_a_good_event_of_each_kind_validates(kind: str) -> None:
    clean = validate(GOOD[kind], stories=STORIES)
    assert clean is not None and set(clean) == {"kind"} | SPEC_FIELDS[kind]


@pytest.mark.parametrize("kind", sorted(GOOD))
def test_an_unknown_or_missing_field_is_refused(kind: str) -> None:
    extra = {**GOOD[kind], "note": "anything"}
    assert validate(extra, stories=STORIES) is None
    for name in SPEC_FIELDS[kind]:
        missing = {k: v for k, v in GOOD[kind].items() if k != name}
        assert validate(missing, stories=STORIES) is None, name


@pytest.mark.parametrize(
    ("kind", "field", "value"),
    [
        ("error", "exc_class", "Runtime Error"),  # a space
        ("error", "exc_class", 'Error"'),  # a quote
        ("error", "exc_class", "Error: the player typed this"),
        ("error", "exc_class", "1Error"),
        ("error", "exc_class", "E" * 129),
        ("error", "logger", "engine hosting"),
        ("error", "logger", "engine.hosting'"),
        ("error", "logger", None),
        ("error", "ref", "3FA9C2E1"),
        ("error", "ref", "3fa9c2e"),
        ("error", "process", "worker-no-such-story"),
        ("error", "process", "worker"),
        ("turn", "story", "no-such-story"),
        ("turn", "story", "Clockwork Dark"),
        ("turn", "account", "alice"),
        ("turn", "account", "u_0123456789AB"),
        ("turn", "outcome", "slow"),
        ("turn", "duration_ms", -1),
        ("turn", "duration_ms", "12"),
        ("turn", "duration_ms", True),
        ("turn", "duration_ms", float("nan")),
        ("turn", "ts", 1e12),
        ("lane", "lane", "custom"),
        ("lane", "outcome", "busy"),
        ("session", "event", "deleted"),
        ("login", "outcome", "maybe"),
        ("process", "exit_code", 1.5),
        ("process", "exit_code", "1"),
        ("process", "event", "crashed"),
    ],
)
def test_a_bad_value_is_refused(kind: str, field: str, value: Any) -> None:
    assert validate({**GOOD[kind], field: value}, stories=STORIES) is None


def test_an_unknown_kind_or_a_non_mapping_is_refused() -> None:
    assert validate({**GOOD["login"], "kind": "content"}) is None
    assert validate({**GOOD["login"], "kind": None}) is None
    assert validate(["login"]) is None
    assert validate("login") is None


def test_exception_names_carry_no_message() -> None:
    class Odd(Exception):
        pass

    Odd.__qualname__ = "Odd thing: with words"
    Odd.__name__ = "Odd thing"
    assert schema.exception_name(RuntimeError) == "RuntimeError"
    assert schema.exception_name(json.JSONDecodeError) == "json.decoder.JSONDecodeError"
    assert schema.exception_name(Odd) is None
    assert schema.exception_name(None) is None


# -- the Oracle projection -------------------------------------------------------------

SENTINEL = "Zq7SENTINELstat"


def _raw() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """An Oracle's metrics() and recent(), as engine/telemetry/oracle.py makes them, with model text in them."""
    from engine.telemetry.oracle import Oracle

    oracle = Oracle()
    oracle.record_unearned_claim(SENTINEL, 50)
    oracle.record_unearned_claim("gold", -70)
    oracle.record_turn(
        {
            "governance": [{"rule_id": "R003"}, {"rule_id": f"x{SENTINEL}"}],
            "assistant": {"spoke": True, "intent": f"say {SENTINEL}", "reliable": False},
            "challenge": {"kind": f"{SENTINEL}-kind"},
            "tool_receipts": [{}, {}],
        },
        latency_ms=1234.5,
        evil_progress=0.4242,
    )
    oracle.record_turn({"assistant": {"spoke": True, "intent": "hint"}, "challenge": {"kind": "puzzle"}}, latency_ms=10)
    return oracle.metrics(), oracle.recent()


def test_the_raw_oracle_does_hold_model_text_and_play_state() -> None:
    """Why the projection exists (design review I6): the raw dicts carry both."""
    metrics, recent = _raw()
    raw = json.dumps([metrics, recent])
    assert SENTINEL in raw and "evil_progress" in raw


def test_the_projection_s_keys_are_pinned() -> None:
    assert PROJECTION_KEYS == (
        "turns", "violation_rate", "violations_total", "violations_by_rule", "violations_other_rules",
        "assistant_intervention_rate", "assistant_misled_count", "gifts", "avg_latency_ms",
        "unearned_claims_count", "unearned_claims_largest_delta", "challenges_started", "recent",
    )
    assert RECENT_KEYS == (
        "turn", "latency_ms", "violations", "rule_ids", "assistant_spoke", "assistant_intent",
        "assistant_reliable", "gift", "tools", "challenge_kind",
    )
    metrics, recent = _raw()
    projected = project_oracle(metrics, recent)
    assert tuple(projected) == PROJECTION_KEYS
    assert all(tuple(row) == RECENT_KEYS for row in projected["recent"])


def test_no_stat_name_unknown_kind_or_intent_or_evil_progress_survives() -> None:
    metrics, recent = _raw()
    for projected in (project_oracle(metrics, recent), clean_projection(project_oracle(metrics, recent))):
        text = json.dumps(projected)
        assert SENTINEL not in text and "gold" not in text
        assert "evil" not in text and "0.4242" not in text
        assert projected["unearned_claims_count"] == 2
        assert projected["unearned_claims_largest_delta"] == -70
        assert projected["violations_by_rule"] == {"R003": 1} and projected["violations_other_rules"] == 1
        assert projected["challenges_started"] == {"other": 1, "puzzle": 1}
        first, second = projected["recent"]
        assert first["assistant_intent"] == "other" and first["challenge_kind"] == "other"
        assert first["rule_ids"] == ["R003"] and first["tools"] == 2 and first["latency_ms"] == 1234.5
        assert second["assistant_intent"] == "hint" and second["challenge_kind"] == "puzzle"


def test_the_enums_come_from_the_engine_s_own_tables() -> None:
    from engine.agents import assistant_director
    from engine.challenges.spec import KINDS as CHALLENGE_KINDS

    assert schema.challenge_kinds() == frozenset(CHALLENGE_KINDS)
    assert schema.assistant_intents() == {
        assistant_director.INTENT_SILENT, assistant_director.INTENT_QUIP, assistant_director.INTENT_HINT,
        assistant_director.INTENT_LORE, assistant_director.INTENT_WARNING, assistant_director.INTENT_GIFT,
    }


def test_the_supervisor_s_clean_holds_a_projection_to_its_keys_again() -> None:
    """A worker is inside the trust boundary, but what the panel shows passes the supervisor's own check."""
    tampered = {
        **project_oracle(*_raw()),
        "evil_progress": 0.9,
        "unearned_claims": {SENTINEL: {"count": 1}},
        "violations_by_rule": {"R003": 1, SENTINEL: 4},
        "challenges_started": {SENTINEL: 2},
        "recent": [{"turn": 1, "assistant_intent": SENTINEL, "challenge_kind": SENTINEL, "evil_progress": 1.0,
                    "rule_ids": [SENTINEL, "R001"]}],
    }
    cleaned = clean_projection(tampered)
    assert tuple(cleaned) == PROJECTION_KEYS
    text = json.dumps(cleaned)
    assert SENTINEL not in text and "evil" not in text
    assert cleaned["violations_other_rules"] == 5 and cleaned["challenges_started"] == {"other": 2}
    assert cleaned["recent"][0]["rule_ids"] == ["R001"]


# -- rule 12: the words ------------------------------------------------------------------


def _names() -> list[str]:
    names: list[str] = []
    for kind, fields in KINDS.items():
        names.append(kind)
        for name, spec in fields.items():
            names.append(name)
            names.extend(spec.values)
    names.extend(PROJECTION_KEYS)
    names.extend(RECENT_KEYS)
    return names


def test_no_name_in_the_schema_or_the_projection_rates_flags_or_filters() -> None:
    for name in _names():
        lowered = name.lower()
        for word in FORBIDDEN_WORDS:
            assert word not in lowered, f"{name!r} contains {word!r} (AGENTS.md rule 12)"


def test_the_word_scan_catches_what_it_is_for() -> None:
    """Canary for the scan itself: a moderation field would be caught."""
    planted = _names() + ["content_rating", "flagged", "nsfw_score"]
    hits = [n for n in planted if any(w in n.lower() for w in FORBIDDEN_WORDS)]
    assert hits == ["content_rating", "flagged", "nsfw_score"]


def test_the_schema_module_names_no_play_text_source() -> None:
    """The schema is code, not a list of things to look for in what players write."""
    source = (schema.__file__ and open(schema.__file__, encoding="utf-8").read()) or ""
    assert not re.search(r"\bdef\s+\w*(moderat|filter|flag)\w*\(", source)

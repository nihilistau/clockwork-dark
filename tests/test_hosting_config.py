"""
The ``hosting:`` block is a closed schema (v0.20.0 T7, spec §6.9).

- Its key set equals spec §6.9's, less the keys a later task adds (each of
  Tasks 10-17 adds its keys here, to the schema and to config/default.yaml
  together): a key added to any one of the three fails.
- An unknown key, a wrong type and an out-of-range value are refused at
  startup, naming the key.
- AGENTS.md rule 12: no key or comment in the block speaks of judging what a
  player writes (a word scan of the block as config/default.yaml ships it).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from engine.hosting.config import SCHEMA, HostingConfigError, validate

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "docs" / "superpowers" / "specs" / "2026-09-30-linux-and-hosting-design.md"
DEFAULT = REPO / "config" / "default.yaml"

#: Spec §6.9's keys that land with a later task (their comments name it).
LATER_KEYS: set[str] = set()  # T17 added the last of them, observability.retention_days
LATER_SECTIONS: tuple[str, ...] = ()


def _flatten(tree: dict[str, Any], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in tree.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            keys |= _flatten(value, dotted + ".")
        else:
            keys.add(dotted)
    return keys


def _spec_keys() -> set[str]:
    text = SPEC.read_text(encoding="utf-8")
    section = text.split("### 6.9 The `hosting:` block", 1)[1]
    block = section.split("```yaml", 1)[1].split("```", 1)[0]
    return _flatten(yaml.safe_load(block)["hosting"])


def _default_block() -> dict[str, Any]:
    return yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))["hosting"]


def _default_block_text() -> str:
    """The block as shipped, WITH its comments: from the comment run above
    ``hosting:`` to the next top-level key."""
    lines = DEFAULT.read_text(encoding="utf-8").splitlines()
    start = lines.index("hosting:")
    first = start
    while first > 0 and lines[first - 1].startswith("#"):
        first -= 1
    end = start + 1
    while end < len(lines) and (not lines[end] or lines[end][0] in " #"):
        end += 1
    return "\n".join(lines[first:end])


def test_the_key_set_is_the_spec_s_less_the_later_tasks_keys() -> None:
    expected = {
        key
        for key in _spec_keys()
        if key not in LATER_KEYS and not key.startswith(LATER_SECTIONS)
    }
    assert set(SCHEMA) == expected
    assert _flatten(_default_block()) == expected


def test_the_shipped_block_validates_and_is_off() -> None:
    settings = validate(_default_block())
    assert settings.enabled is False
    assert settings.cookie_secure is True
    assert settings.session_days == 14
    assert settings.logins_per_minute == 5
    assert settings.public_origin == ""


def _block(**changes: Any) -> dict[str, Any]:
    block = copy.deepcopy(_default_block())
    for dotted, value in changes.items():
        node = block
        parts = dotted.split("__")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return block


@pytest.mark.parametrize(
    ("changes", "key"),
    [
        ({"expose_metrics": True}, "hosting.expose_metrics"),
        ({"safety": {"tier": 1}}, "hosting.safety"),
        ({"admin__allowlist": ["10.0.0.0/8"]}, "hosting.admin.allowlist"),  # NOT WIRED (T14)
        ({"observability__retention": 30}, "hosting.observability.retention"),
        ({"supervisor__port": 9000}, "hosting.supervisor.port"),
    ],
)
def test_an_unknown_key_is_refused_by_name(changes: dict[str, Any], key: str) -> None:
    with pytest.raises(HostingConfigError) as caught:
        validate(_block(**changes))
    assert caught.value.key == key
    assert key in str(caught.value)


@pytest.mark.parametrize(
    ("changes", "key"),
    [
        ({"enabled": "yes"}, "hosting.enabled"),
        ({"cookie_secure": 1}, "hosting.cookie_secure"),
        ({"threads": True}, "hosting.threads"),
        ({"session_days": "14"}, "hosting.session_days"),
        ({"secret_key": 12345}, "hosting.secret_key"),
        ({"rate_limits": 5}, "hosting.rate_limits"),
        ({"rate_limits__logins_per_minute": 2.5}, "hosting.rate_limits.logins_per_minute"),
        ({"stories": "clockwork-dark"}, "hosting.stories"),
        ({"stories": ["clockwork-dark", 3]}, "hosting.stories"),
        ({"stories": [""]}, "hosting.stories"),
        ({"supervisor": ["boot_seconds"]}, "hosting.supervisor"),
        ({"supervisor__boot_seconds": "120"}, "hosting.supervisor.boot_seconds"),
        ({"supervisor__health_failures": True}, "hosting.supervisor.health_failures"),
        ({"observability__log_keep": 1.5}, "hosting.observability.log_keep"),
        ({"admin": 15}, "hosting.admin"),
        ({"admin__reauth_minutes": "15"}, "hosting.admin.reauth_minutes"),
        ({"rate_limits__admin_actions_per_minute": True}, "hosting.rate_limits.admin_actions_per_minute"),
    ],
)
def test_a_wrong_type_is_refused_by_name(changes: dict[str, Any], key: str) -> None:
    with pytest.raises(HostingConfigError) as caught:
        validate(_block(**changes))
    assert caught.value.key == key


@pytest.mark.parametrize(
    ("changes", "key"),
    [
        ({"session_days": 0}, "hosting.session_days"),
        ({"trusted_proxies": -1}, "hosting.trusted_proxies"),
        ({"threads": 0}, "hosting.threads"),
        ({"max_input_chars": 0}, "hosting.max_input_chars"),
        ({"utility_wait_seconds": 0}, "hosting.utility_wait_seconds"),
        ({"turn_deadline_seconds": 0}, "hosting.turn_deadline_seconds"),
        ({"turn_deadline_seconds": 86401}, "hosting.turn_deadline_seconds"),
        ({"body_read_seconds": 0}, "hosting.body_read_seconds"),  # T12 fix round 1
        ({"body_read_seconds": 601}, "hosting.body_read_seconds"),
        ({"max_saves_per_story": 0}, "hosting.max_saves_per_story"),
        ({"rate_limits__logins_per_minute": 0}, "hosting.rate_limits.logins_per_minute"),
        ({"rate_limits__actions_per_minute": 10**6}, "hosting.rate_limits.actions_per_minute"),
        ({"public_origin": "https://play.example.org/"}, "hosting.public_origin"),
        ({"public_origin": "play.example.org"}, "hosting.public_origin"),
        ({"public_origin": "ftp://play.example.org"}, "hosting.public_origin"),
        ({"public_origin": "https://u@play.example.org"}, "hosting.public_origin"),
        ({"stories": ["clockwork-dark", "clockwork-dark"]}, "hosting.stories"),
        ({"stories": [f"s{i}" for i in range(65)]}, "hosting.stories"),
        ({"supervisor__health_interval_seconds": 0}, "hosting.supervisor.health_interval_seconds"),
        ({"supervisor__health_failures": 0}, "hosting.supervisor.health_failures"),
        ({"supervisor__boot_seconds": 0}, "hosting.supervisor.boot_seconds"),
        ({"supervisor__hello_seconds": 0}, "hosting.supervisor.hello_seconds"),
        ({"supervisor__hello_seconds": 31}, "hosting.supervisor.hello_seconds"),
        ({"supervisor__max_restarts": 0}, "hosting.supervisor.max_restarts"),
        ({"supervisor__restart_window_minutes": 1441}, "hosting.supervisor.restart_window_minutes"),
        ({"supervisor__drain_seconds": 0}, "hosting.supervisor.drain_seconds"),
        ({"supervisor__stop_seconds": 601}, "hosting.supervisor.stop_seconds"),
        ({"supervisor__shutdown_seconds": 0}, "hosting.supervisor.shutdown_seconds"),
        ({"supervisor__max_hold_seconds": 0}, "hosting.supervisor.max_hold_seconds"),
        ({"supervisor__max_hold_seconds": 86401}, "hosting.supervisor.max_hold_seconds"),
        ({"observability__log_max_mb": 0}, "hosting.observability.log_max_mb"),
        ({"observability__log_keep": 0}, "hosting.observability.log_keep"),
        ({"observability__retention_days": 0}, "hosting.observability.retention_days"),
        ({"observability__retention_days": 3651}, "hosting.observability.retention_days"),
        ({"observability__metrics_max_mb": 0}, "hosting.observability.metrics_max_mb"),
        ({"admin__reauth_minutes": 0}, "hosting.admin.reauth_minutes"),
        ({"admin__reauth_minutes": 1441}, "hosting.admin.reauth_minutes"),
        ({"rate_limits__admin_actions_per_minute": 0}, "hosting.rate_limits.admin_actions_per_minute"),
    ],
)
def test_an_out_of_range_value_is_refused_by_name(changes: dict[str, Any], key: str) -> None:
    with pytest.raises(HostingConfigError) as caught:
        validate(_block(**changes))
    assert caught.value.key == key


def test_a_missing_key_is_refused_by_name() -> None:
    block = _block()
    del block["threads"]
    with pytest.raises(HostingConfigError) as caught:
        validate(block)
    assert caught.value.key == "hosting.threads"


@pytest.mark.parametrize("key", ["x", "changeme", "0123456789abcdef0123456789abcde"])
def test_a_short_secret_key_is_refused(key: str) -> None:
    with pytest.raises(HostingConfigError) as caught:
        validate(_block(), secret_key=key)
    assert caught.value.key == "hosting.secret_key"
    assert "secrets.token_urlsafe(32)" in str(caught.value)
    if len(key) > 1:
        assert key not in str(caught.value), "the key itself was echoed"


def test_a_long_secret_key_is_accepted_and_empty_means_generate() -> None:
    import secrets

    key = secrets.token_urlsafe(32)
    assert validate(_block(), secret_key=key).secret_key == key
    # Exactly 16 different characters is enough.
    assert validate(_block(), secret_key="0123456789abcdef" + "fedcba9876543210").secret_key


@pytest.mark.parametrize("key", ["a" * 32, "changeme" * 4, "0123456789abcde" * 3])
def test_a_repetitive_secret_key_is_refused(key: str) -> None:
    with pytest.raises(HostingConfigError) as caught:
        validate(_block(), secret_key=key)
    assert caught.value.key == "hosting.secret_key"
    assert "repeated" in str(caught.value)


def test_a_pasted_random_hex_key_missing_a_digit_is_accepted() -> None:
    """``openssl rand -hex 32`` misses one of the sixteen digits about one
    time in four (v0.20.0's first CI run refused its own such key)."""
    key = "f3a9c1e07b5d2846" + "93e1c7a05fd2b864" + "1d7e3a9c5b0f8246" + "c0a7e93d51b2f864"
    key = key.replace("f", "e")  # 64 hex digits, 15 different, no period
    assert len(key) == 64 and len(set(key)) == 15
    assert validate(_block(), secret_key=key).secret_key == key
    assert validate(_block(), secret_key=key.upper()).secret_key == key.upper()


@pytest.mark.parametrize(
    "key",
    [
        "0123456789abcde" * 5,  # hex, 75 long, but one pattern repeated
        "0123456789" * 7,  # hex, 70 long, 10 different, repeated
        "0123456789abcdef" * 4,  # 16 different, but repeated
        "abcdefghijklmnopqrstuvwx" * 2,  # 24 different, repeated
        "1a2b3c4d" * 9,  # hex, too few different characters
    ],
)
def test_a_repeated_pattern_key_is_refused(key: str) -> None:
    with pytest.raises(HostingConfigError) as caught:
        validate(_block(), secret_key=key)
    assert caught.value.key == "hosting.secret_key"
    assert key not in str(caught.value)


def test_a_generated_key_file_is_checked_for_length_only() -> None:
    """A random hex key missing a digit or two is the engine's own, and fine."""
    from engine.hosting.config import check_secret_key

    hexy = "0123456789abcde" * 5  # 75 characters, 15 different
    assert check_secret_key(hexy, source="the key file", configured=False) == hexy
    assert validate(_block(), secret_key="   ").secret_key == ""


def test_the_login_work_keys() -> None:
    settings = validate(_block())
    assert settings.max_concurrent_logins == 4
    assert settings.logins_per_minute_all == 60


def test_the_supervisor_keys_ship_with_the_spec_s_values() -> None:
    settings = validate(_block())
    assert settings.stories == ("clockwork-dark",)
    assert (
        settings.health_interval_seconds,
        settings.health_failures,
        settings.boot_seconds,
        settings.max_restarts,
        settings.restart_window_minutes,
        settings.drain_seconds,
        settings.stop_seconds,
        settings.shutdown_seconds,
    ) == (10, 3, 120, 5, 10, 120, 30, 180)
    assert settings.hello_seconds == 2
    assert settings.max_hold_seconds == 1200  # T11
    assert (settings.log_max_mb, settings.log_keep) == (20, 5)
    assert settings.retention_days == 30  # T17: the metrics store's window (spec §6.9, §14.10)
    assert settings.metrics_max_mb == 512  # T17 fix round 1: its size cap


def test_the_admin_panel_keys_ship_with_the_spec_s_values() -> None:
    """T14: the admin actions bucket and the re-auth interval (spec §6.9, §14.7)."""
    settings = validate(_block())
    assert settings.admin_actions_per_minute == 30
    assert settings.admin_reauth_minutes == 15


def test_the_turn_deadline_ships_at_fifteen_minutes() -> None:
    """T11 fix round 1: an admitted turn's wall-clock budget (default.yaml says why 900)."""
    assert validate(_block()).turn_deadline_seconds == 900


@pytest.mark.parametrize(
    ("hold", "deadline", "ok"),
    [
        (1020, 900, True),  # the shipped deadline + 120
        (1019, 900, False),
        (1200, 900, True),  # the shipped pair
        (1200, 1100, False),  # 1100 + 120 = 1220
        (121, 1, True),
        (120, 1, False),
    ],
)
def test_max_hold_must_outlast_the_turn_deadline(hold: int, deadline: int, ok: bool) -> None:
    """
    T11 fix round 1 (spec §6.9): max_hold_seconds >= turn_deadline_seconds +
    120, named at startup -- the supervisor's reclaim is a backstop behind
    the worker's own deadline. Fails on 31cb510, which had no such key.
    """
    block = _block(supervisor__max_hold_seconds=hold, turn_deadline_seconds=deadline)
    if ok:
        settings = validate(block)
        assert (settings.max_hold_seconds, settings.turn_deadline_seconds) == (hold, deadline)
        return
    with pytest.raises(HostingConfigError) as caught:
        validate(block)
    assert caught.value.key == "hosting.supervisor.max_hold_seconds"
    assert str(deadline + 120) in str(caught.value)
    assert "llm.timeout_seconds" not in str(caught.value)


def test_a_long_model_timeout_no_longer_refuses_hosted_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    T11 fix round 1: ``max_hold_seconds`` no longer follows
    ``llm.timeout_seconds`` (a per-phase timeout, never a call's total), so
    an owner's long local timeout starts hosted mode. On 31cb510 a 600 s
    timeout was refused (1860 > 1200).
    """
    from engine.config import get_config, reset_config
    from engine.hosting.config import load
    from tests.hosted_app import hosting_layer

    hosting_layer(monkeypatch, tmp_path, extra={"llm": {"timeout_seconds": 600}})
    try:
        assert load(get_config()).max_hold_seconds == 1200
    finally:
        reset_config()


def test_an_empty_story_list_passes_the_schema_and_is_refused_by_the_story_check() -> None:
    """Empty is the supervisor's and the doctor's refusal (naming the key), not a type error."""
    from engine.hosting.config import story_problems

    assert validate(_block(stories=[])).stories == ()
    assert story_problems([]) == [("", "is empty: name at least one story (python launcher.py --list-games)")]
    assert story_problems(["clockwork-dark", "hue-and-cry"]) == []
    (row,) = story_problems(["no-such-story"])
    assert row[0] == "no-such-story" and "not an installed story" in row[1]


@pytest.mark.parametrize(
    ("drain", "stop", "shutdown", "ok"),
    [(120, 30, 167, True), (120, 30, 166, False), (120, 30, 157, False), (1, 1, 19, True), (1, 1, 18, False),
     (10, 5, 31, False), (120, 30, 150, False)],
)
def test_shutdown_must_hold_a_drain_a_stop_and_its_tail(drain: int, stop: int, shutdown: int, ok: bool) -> None:
    """
    drain + stop + 7 (the terminate grace and the kill) + 10 (the front door's
    stop, after every worker's: T18 fix round 1, deliberately raising T10's
    budget by FRONTDOOR_STOP_RESERVE_SECONDS). The shipped 180 still holds it.
    """
    from engine.hosting.config import FRONTDOOR_STOP_RESERVE_SECONDS

    assert FRONTDOOR_STOP_RESERVE_SECONDS == 10
    block = _block(
        supervisor__drain_seconds=drain,
        supervisor__stop_seconds=stop,
        supervisor__shutdown_seconds=shutdown,
    )
    if ok:
        assert validate(block).shutdown_seconds == shutdown
        return
    with pytest.raises(HostingConfigError) as caught:
        validate(block)
    assert caught.value.key == "hosting.supervisor.shutdown_seconds"
    assert str(drain + stop + 7 + 10) in str(caught.value)


def test_a_public_origin_with_a_port_is_accepted() -> None:
    assert validate(_block(public_origin="https://play.example.org:8443")).public_origin == (
        "https://play.example.org:8443"
    )


#: Rule 12's words: none may appear in the block's keys or comments.
RULE_12_WORDS = re.compile(
    r"\b(?:content\w*|rating\w*|rated|safe\w*|moderat\w*|nsfw|explicit\w*|intensity|censor\w*|filter\w*)\b",
    re.IGNORECASE,
)


def test_no_key_or_comment_in_the_block_speaks_of_judging_what_players_write() -> None:
    text = _default_block_text()
    assert "hosting:" in text and "logins_per_minute" in text
    found = sorted(set(m.group(0).lower() for m in RULE_12_WORDS.finditer(text)))
    assert not found, f"config/default.yaml's hosting block mentions {found} (AGENTS.md rule 12)"
    keys = " ".join(SCHEMA)
    assert not RULE_12_WORDS.search(keys), keys


def test_a_story_may_not_declare_hosting() -> None:
    from engine.games.manifest import refusal_reason

    assert "operator" in refusal_reason("hosting.enabled")

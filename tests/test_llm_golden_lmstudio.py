"""
LM Studio is byte-identical: the golden, replayed.

THE INVARIANT. v0.19.0 makes the engine model-server agnostic, and nothing
about that may change what an LM Studio user's engine sends or what it makes of
the answers. ``tests/llm_golden.py`` recorded, from untouched v0.18.0 code, the
requests of every LM Studio path and the parse of every canned answer, for the
shipped config and for a v0.18-shaped ``lmstudio:`` ``local.yaml``. This file
replays each scenario against the RECORDED answers (``*.responses.json``) and
asserts the request list and the parse both equal the recording.

A FAILURE HERE IS A REGRESSION, or a spec decision to take back to the owner --
never a reason to re-record. Two differences are sanctioned, each named and
asserted exactly:

* the ``structured_output: off`` format block (spec §4.2, v0.19.0):
  ``06_turn_off``'s requests are compared with the block the engine rendered
  taken back off, and must then equal the recording; no other scenario may
  render one;
* the stack's model-server probe URL in the LEGACY variant (spec §8, v0.19.0
  T6): ``23_stack_probe`` asks ``llm.base_url``'s server
  (``http://127.0.0.1:1235``), where v0.18 asked a fixed
  ``http://localhost:1234`` -- a v0.18 bug. That one field is put back and the
  request must then equal the recording; the parse is compared unchanged.

The doctor and launcher baseline is asserted here too: the text
``scripts/doctor.py``'s ``check_llm`` and ``check_services`` and
``launcher.py``'s ``_report`` produce against a healthy LM Studio, which later
doctor work is measured against.

Nothing here opens a socket (``tests/llm_wire.py`` answers at the transport),
and ``tests/conftest.py``'s guard stays up. ``real_discovery`` lifts only the
conftest's discovery pin, because discovery's own request is part of what is
pinned.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.llm_golden import (
    BASELINE_ANSWERS,
    FIXTURES,
    SCENARIO_BY_NAME,
    SCENARIOS,
    TRANSPORT_HEADERS,
    VARIANTS,
    capture_baseline,
    fixture_paths,
    fixture_to_request,
    request_to_fixture,
    run_scenario,
)
from tests.llm_wire import build_response, canonical_json

pytestmark = pytest.mark.real_discovery


def _load(path: Path) -> Any:
    assert path.is_file(), f"missing golden fixture {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _diff(expected: Any, actual: Any) -> str:
    left = json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    right = json.dumps(actual, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    return "\n".join(
        difflib.unified_diff(left, right, "recorded (v0.18.0)", "now", lineterm="", n=2)
    )


def _as_fixtures(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [request_to_fixture(r) for r in requests]


#: The first scenario whose requests may differ from v0.18's, and only by the
#: format block (spec §4.2): `structured_output: off` on LM Studio sends no
#: grammar, so since v0.19.0 its prompt carries the shape instead.
SANCTIONED = "06_turn_off"

#: The second (v0.19.0 T6, spec §8): the stack's model-server probe, in the
#: LEGACY variant only, and only by the one URL. v0.18 health-checked a fixed
#: `http://localhost:1234/api/v1/models` whatever `lmstudio.base_url` said, so
#: an LM Studio moved to another port was checked on the wrong one -- a v0.18
#: bug. The probe is now derived from `llm.base_url`. Headers (the key is
#: still sent: the origin is the configured server's) and the parse are
#: v0.18's; the shipped variant is byte-identical.
SANCTIONED_URL = (
    "23_stack_probe",
    "legacy",
    "http://localhost:1234/api/v1/models",
    "http://127.0.0.1:1235/api/v1/models",
)


def _with_the_v18_url(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The requests with the derived URL put back to v0.18's fixed one,
    asserting it was there exactly once, on the one request, and was the
    legacy variant's own base.
    """
    _, _, v18, derived = SANCTIONED_URL
    assert [r["url"] for r in requests] == [derived], (
        f"the stack probe asked {[r['url'] for r in requests]}, not {derived}"
    )
    return [{**requests[0], "url": v18}]


def _without_the_block(
    requests: list[dict[str, Any]], blocks: list[str]
) -> list[dict[str, Any]]:
    """
    The requests with the rendered format block taken back off, asserting it
    was there exactly once: appended to the native ``system_prompt`` after a
    blank line, and nowhere else.
    """
    assert len(blocks) == 1 and blocks[0], f"expected one rendered block, got {blocks}"
    suffix = "\n\n" + blocks[0]
    carried = 0
    out = []
    for request in requests:
        body = json.loads(request["body"]) if request["body"].startswith("{") else None
        prompt = (body or {}).get("system_prompt")
        if isinstance(prompt, str) and prompt.endswith(suffix):
            carried += 1
            body["system_prompt"] = prompt[: -len(suffix)]
            request = {**request, "body": canonical_json(body)}
        out.append(request)
    assert carried == 1, f"the format block reached {carried} requests, not one"
    return out


@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_lm_studio_is_byte_identical(
    scenario: Any, variant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Replay one scenario: the same requests go out, the same parse comes back.

    ``06_turn_off`` differs by exactly the rendered format block -- the block
    the engine rendered for that turn, taken off its request -- and in no
    other byte; every other scenario is compared whole.
    """
    paths = fixture_paths(variant, scenario.name)
    recorded_requests = _load(paths["requests"])
    answers = _load(paths["responses"])
    recorded_parse = _load(paths["parsed"])

    from engine.llm import schemas

    blocks: list[str] = []
    render = schemas.render_format_block

    def spy(schema: Any) -> str:
        blocks.append(render(schema))
        return blocks[-1]

    monkeypatch.setattr(schemas, "render_format_block", spy)
    outcome = run_scenario(scenario, variant, tmp_path / "config", answers=answers)
    if scenario.name == SANCTIONED:
        outcome["requests"] = _without_the_block(outcome["requests"], blocks)
    else:
        assert not blocks, f"{scenario.name} [{variant}] rendered a format block"
    if (scenario.name, variant) == SANCTIONED_URL[:2]:
        outcome["requests"] = _with_the_v18_url(outcome["requests"])

    # Requests: compared as the capture writes them -- the body as canonical
    # JSON TEXT -- so an int that became a float, or 0 that became 0.0, is a
    # difference even though Python calls the two equal.
    expected = [fixture_to_request(entry) for entry in recorded_requests]
    assert outcome["requests"] == expected, (
        f"{scenario.name} [{variant}] sent different requests:\n"
        + _diff(recorded_requests, _as_fixtures(outcome["requests"]))
    )

    assert canonical_json(outcome["parsed"]) == canonical_json(recorded_parse), (
        f"{scenario.name} [{variant}] parsed the answers differently:\n"
        + _diff(recorded_parse, outcome["parsed"])
    )


def test_the_stand_down_sends_nothing_further(tmp_path: Path) -> None:
    """
    A starved answer with no reasoning count, and no native route: exactly one
    chat request, and no retry after it -- run live, not only read off disk.
    """
    scenario = SCENARIO_BY_NAME["15_starvation_stand_down"]
    for variant in VARIANTS:
        paths = fixture_paths(variant, scenario.name)
        outcome = run_scenario(
            scenario, variant, tmp_path / variant, answers=_load(paths["responses"])
        )
        live = outcome["requests"]
        assert len(live) == 2, (variant, [r["url"] for r in live])
        assert [r["method"] for r in live].count("POST") == 1, variant

        recorded = _load(paths["requests"])
        chats = [r for r in recorded if r["method"] == "POST"]
        assert len(chats) == 1, (variant, [r["url"] for r in recorded])


def test_every_recording_is_on_disk_and_accounted_for() -> None:
    """No scenario without its three files, and no stray file in the golden."""
    expected: set[Path] = set()
    for variant in VARIANTS:
        for scenario in SCENARIOS:
            expected |= set(fixture_paths(variant, scenario.name).values())
    expected |= {FIXTURES / f"{name}.txt" for name in BASELINE_ANSWERS}
    on_disk = {p for p in FIXTURES.rglob("*") if p.is_file()}
    assert not (expected - on_disk), sorted(str(p) for p in expected - on_disk)
    assert not (on_disk - expected), sorted(str(p) for p in on_disk - expected)


def test_every_recorded_request_carries_the_pinned_key() -> None:
    """
    The key is pinned, so every request authenticates the same way everywhere;
    and no fixture holds a header httpx's transport authors, since those move
    with an httpx release rather than with the engine.
    """
    for variant in VARIANTS:
        for scenario in SCENARIOS:
            for request in _load(fixture_paths(variant, scenario.name)["requests"]):
                where = (variant, scenario.name, request["url"])
                assert request["headers"].get("authorization") == "Bearer golden-test-key", where
                assert not set(request["headers"]) & TRANSPORT_HEADERS, where


#: sha256 of the bytes the seam renders for three recorded answers. The golden
#: replays through `build_response`/`render_sse`, so a change to either would
#: change what every golden scenario is served without touching a fixture.
_SEAM_RENDERINGS = {
    ("01_turn_streamed_flagship", 0): "717d24152147d75e1679218a348d039baced7901a5bd8304010cf361b88364df",
    ("01_turn_streamed_flagship", 2): "c32d602921343aa62f6f86ec37087f5bda77fb677558ee39b43ed64faaf7ecd8",
    ("06_turn_off", 2): "4998b3945c976deae996a280ebefd14d4a87bc5c45b96c786b01aeb9f1b9d26b",
}


def test_the_seam_renders_the_recorded_answers_unchanged() -> None:
    """Pins `tests/llm_wire.py`'s rendering: status, content type and bytes."""
    import hashlib

    import httpx

    request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    for (name, index), digest in _SEAM_RENDERINGS.items():
        answer = _load(fixture_paths("shipped", name)["responses"])[index]
        response = build_response(answer, request)
        seen = hashlib.sha256(
            f"{response.status_code}|{response.headers['content-type']}|".encode()
            + response.content
        ).hexdigest()
        assert seen == digest, (name, index, seen)


@pytest.mark.parametrize("name", sorted(BASELINE_ANSWERS))
def test_the_doctor_and_launcher_baseline(name: str, tmp_path: Path) -> None:
    """What the doctor and the launcher say about a healthy LM Studio, unchanged."""
    path = FIXTURES / f"{name}.txt"
    assert path.is_file(), f"missing baseline {path}"
    recorded = path.read_text(encoding="utf-8")
    now = capture_baseline(name, tmp_path / "config")
    assert now == recorded, "\n".join(
        difflib.unified_diff(
            recorded.splitlines(), now.splitlines(), "recorded (v0.18.0)", "now", lineterm=""
        )
    )

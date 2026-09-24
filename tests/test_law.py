"""
The Law, part one: its data and the wanted level it keeps.

THE SHAPE. ``paths.law`` names one YAML file (the contract is in
docs/superpowers/plans/2026-09-24-v0.10.0-the-law.md). This task loads and
validates it and keeps the arithmetic the rest of the Law reads: a wanted
SCORE per guise per jurisdiction -- the sum of severity x precision over the
reports filed there -- and the BAND word that score falls in. Reports arrive
through the ``report`` effect, a bribe discharges them through
``quash_reports``, and time cools them through ``law_cool``.

WHAT THESE TESTS HOLD. Every threshold lands in its band; guises the watch
believes are one person share heat and others do not; a quash takes only what
it matches; cooling lowers the band over days and never below the first; a
story that declares no Law is inert end to end and its state carries only an
empty ``law``; and every malformed file fails loudly, naming itself -- a law
file that loads, validates and polices nothing is the inert shape this repo
has shipped before.

The synthetic file uses the flagship's own locations and items, so it tests
the loader's cross-references against real registries rather than stubs.

Version: v0.1.0 [2026-09-24]
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game.effects import apply_effect
from engine.game.state import GameState
from engine.world import law

SPEC: dict[str, Any] = {
    "roles": ["watch", "sergeant"],
    "reporters": {"vendor": 0.3},
    "jurisdictions": {
        "village": ["edgewood_square", "edgewood_bakery"],
        "town": ["millhaven_gate", "millhaven_market"],
    },
    "deeds": {
        "pickpocket": {"severity": 1},
        "loitering": {"severity": 0},
        "fencing": {"severity": 2},
        "assault_watch": {"severity": 5},
    },
    "notice": {"base": 0.6, "night": -0.25, "per_margin": -0.05},
    "wanted": {
        "bands": ["unknown", "noticed", "sought", "wanted", "hunted"],
        "thresholds": [0, 2, 5, 9, 14],
        "cool_per_day": 1.5,
    },
    "precision": {1: 1.0, 2: 0.6, 3: 0.3},
    "recognise": {"sought": 0.25, "wanted": 0.5, "hunted": 0.8},
    "guises": {
        "self": {"label": "your own face"},
        "magpie": {"label": "the Magpie's mask", "item": "golden_ring"},
        "porter": {"label": "a porter", "item": "candle"},
    },
    "links": [["self", "magpie"]],
    # No `encounter`: a law file naming one is checked against the running
    # story's encounters at load (Task 7), and this synthetic file runs on the
    # flagship's, which ship no watch_stop. tests/test_law_arrest.py adds it
    # alongside the scene it authors.
    "arrest": {
        "gaol": "millhaven_barracks",
        "fine_per_severity": 6,
        "days_per_severity": 1,
    },
}


def _write(tmp_path: Path, doc: Any) -> Path:
    """A mapping is dumped; a string is written verbatim (for syntax faults)."""
    path = tmp_path / "law.yaml"
    text = doc if isinstance(doc, str) else yaml.safe_dump(doc)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    path = _write(tmp_path, SPEC)
    set_overlay({"paths": {"law": str(path)}})
    try:
        yield path
    finally:
        set_overlay(None)


def _report(state: GameState, guise: str, deed: str = "pickpocket", *,
            where: str = "village", precision: float = 1.0) -> dict[str, Any]:
    return apply_effect(
        state,
        {"type": "report", "deed": deed, "guise": guise, "jurisdiction": where,
         "precision": precision},
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_the_contract_loads_with_its_defaults(declared: Path) -> None:
    spec = law.load_spec()
    assert law.declared()
    assert spec["jurisdictions"]["town"] == ["millhaven_gate", "millhaven_market"]
    assert spec["deeds"]["fencing"] == 2
    assert spec["precision"] == {1: 1.0, 2: 0.6, 3: 0.3}
    # Optional keys a later task reads, defaulted here so the reader has one
    # place to look rather than a scattering of `.get(..., 0.3)`.
    assert spec["spread_per_hour"] == 0.3
    assert law.jurisdiction_of("edgewood_bakery") == "village"
    assert law.jurisdiction_of("forest_clearing") == ""


def _mutated(**changes: Any) -> dict[str, Any]:
    doc = copy.deepcopy(SPEC)
    for dotted, value in changes.items():
        node = doc
        *parents, leaf = dotted.split("__")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return doc


MALFORMED = {
    "a location in two jurisdictions": _mutated(
        jurisdictions={"village": ["edgewood_square"], "town": ["edgewood_square"]}
    ),
    "a jurisdiction naming no real location": _mutated(
        jurisdictions={"village": ["the_moon"]}
    ),
    "bands and thresholds of different lengths": _mutated(
        wanted__thresholds=[0, 2, 5, 9]
    ),
    "thresholds that do not ascend": _mutated(wanted__thresholds=[0, 5, 5, 9, 14]),
    "thresholds not starting at zero": _mutated(wanted__thresholds=[1, 2, 5, 9, 14]),
    "a guise item the registry lacks": _mutated(
        guises={"self": {"label": "you"}, "ghost": {"label": "a ghost", "item": "no_such_thing"}}
    ),
    "no `self` guise": _mutated(guises={"magpie": {"label": "the Magpie's mask"}}),
    "a guise with no label": _mutated(guises={"self": {}}),
    "a link naming an unknown guise": _mutated(links=[["self", "nobody"]]),
    "a gaol that is not a location": _mutated(arrest__gaol="the_moon"),
    "an unknown deed kind referenced in arrest": _mutated(
        arrest__approaches={"fight": {"deed": "treason"}}
    ),
    "a negative severity": _mutated(deeds={"pickpocket": {"severity": -1}}),
    "a recognise band that is not a band": _mutated(recognise={"notorious": 0.5}),
    "a spread chance above one": _mutated(spread_per_hour=1.5),
    "a reporter chance above one": _mutated(reporters={"vendor": 2}),
    "a precision hop of zero": _mutated(precision={0: 1.0}),
    "a notice base above one": _mutated(notice__base=1.5),
    "a YAML syntax error": "roles: [watch\ndeeds: {pickpocket: {severity: 1}\n",
}


@pytest.mark.parametrize("fault", sorted(MALFORMED))
def test_a_malformed_file_fails_naming_itself(tmp_path: Path, fault: str) -> None:
    path = _write(tmp_path, MALFORMED[fault])
    set_overlay({"paths": {"law": str(path)}})
    try:
        with pytest.raises(ValueError) as caught:
            law.load_spec()
    finally:
        set_overlay(None)
    assert str(path) in str(caught.value), fault


def test_a_declared_file_that_is_missing_is_a_broken_install(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere.yaml"
    set_overlay({"paths": {"law": str(missing)}})
    try:
        with pytest.raises(ValueError, match="nowhere.yaml"):
            law.load_spec()
    finally:
        set_overlay(None)


# ---------------------------------------------------------------------------
# Wanted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "severity_total, band",
    [(0, "unknown"), (1, "unknown"), (2, "noticed"), (4, "noticed"), (5, "sought"),
     (9, "wanted"), (13, "wanted"), (14, "hunted"), (30, "hunted")],
)
def test_each_threshold_lands_in_its_band(
    declared: Path, severity_total: int, band: str
) -> None:
    state = GameState()
    for _ in range(severity_total):
        _report(state, "porter")
    assert law.wanted_score(state, "porter", "village") == pytest.approx(severity_total)
    assert law.wanted_band(state, "porter", "village") == band


def test_precision_weights_a_report(declared: Path) -> None:
    state = GameState()
    _report(state, "porter", "fencing", precision=0.3)
    assert law.wanted_score(state, "porter", "village") == pytest.approx(0.6)


def test_a_report_counts_only_in_its_own_jurisdiction(declared: Path) -> None:
    state = GameState()
    _report(state, "porter", "assault_watch", where="town")
    assert law.wanted_band(state, "porter", "town") == "sought"
    assert law.wanted_band(state, "porter", "village") == "unknown"


def test_linked_guises_share_heat(declared: Path) -> None:
    """The watch believes the Magpie is you: a report on the mask is on you."""
    state = GameState()
    _report(state, "magpie", "assault_watch")
    assert law.wanted_score(state, "self", "village") == pytest.approx(5)
    assert law.wanted_score(state, "magpie", "village") == pytest.approx(5)
    # Symmetric: the link is a belief about one person, not a direction.
    _report(state, "self", "fencing")
    assert law.wanted_score(state, "magpie", "village") == pytest.approx(7)


def test_unlinked_guises_do_not(declared: Path) -> None:
    state = GameState()
    _report(state, "porter", "assault_watch")
    assert law.wanted_score(state, "self", "village") == 0
    assert law.wanted_score(state, "magpie", "village") == 0


def test_links_held_in_state_replace_the_files_starting_belief(declared: Path) -> None:
    """Breaking `self = magpie` is the spine; the file only says where it starts."""
    state = GameState()
    state.law["links"] = []
    _report(state, "magpie", "assault_watch")
    assert law.wanted_score(state, "self", "village") == 0


def test_the_report_receipt_is_prose(declared: Path) -> None:
    state = GameState()
    out = _report(state, "magpie", "fencing", precision=0.6)
    assert out["ok"] is True
    text = out["text"]
    assert "the Magpie's mask" in text
    assert "magpie" not in text.replace("Magpie", "")
    assert "fencing" not in text and "village" not in text
    assert not any(ch.isdigit() for ch in text)
    row = state.law["reports"][0]
    # A report filed on its own is a deed of its own: it gets a fresh id.
    assert row == {"deed_id": "d1", "deed": "fencing", "severity": 2, "guise": "magpie",
                   "jurisdiction": "village", "precision": 0.6, "day": state.world_day}


@pytest.mark.parametrize(
    "effect",
    [
        {"deed": "treason", "guise": "self", "jurisdiction": "village"},
        {"deed": "pickpocket", "guise": "nobody", "jurisdiction": "village"},
        {"deed": "pickpocket", "guise": "self", "jurisdiction": "the_moon"},
        {"deed": "pickpocket", "guise": "self", "jurisdiction": "village", "precision": 3},
    ],
)
def test_an_unusable_report_is_refused_and_writes_nothing(
    declared: Path, effect: dict[str, Any]
) -> None:
    state = GameState()
    out = apply_effect(state, {"type": "report", **effect})
    assert out["ok"] is False
    assert state.law == {}


# ---------------------------------------------------------------------------
# Quashing
# ---------------------------------------------------------------------------


def test_quash_removes_only_what_it_matches(declared: Path) -> None:
    state = GameState()
    _report(state, "porter", "pickpocket")
    _report(state, "porter", "assault_watch")
    _report(state, "magpie", "pickpocket")
    _report(state, "porter", "pickpocket", where="town")

    out = apply_effect(
        state,
        {"type": "quash_reports", "jurisdiction": "village", "guise": "porter",
         "max_severity": 2},
    )
    assert out["ok"] is True
    assert not any(ch.isdigit() for ch in out["text"])
    left = [(r["guise"], r["deed"], r["jurisdiction"]) for r in state.law["reports"]]
    assert left == [
        ("porter", "assault_watch", "village"),
        ("magpie", "pickpocket", "village"),
        ("porter", "pickpocket", "town"),
    ]


def test_an_unfiltered_quash_clears_everything(declared: Path) -> None:
    state = GameState()
    _report(state, "porter")
    _report(state, "self", where="town")
    apply_effect(state, {"type": "quash_reports"})
    assert state.law["reports"] == []


# ---------------------------------------------------------------------------
# Cooling
# ---------------------------------------------------------------------------


def test_cooling_lowers_the_band_over_days_and_never_below_the_first(declared: Path) -> None:
    state = GameState()
    _report(state, "porter", "assault_watch")
    _report(state, "porter", "fencing")
    assert law.wanted_band(state, "porter", "village") == "sought"  # 7

    law.cool(state, 1)  # 7 - 1.5
    assert law.wanted_score(state, "porter", "village") == pytest.approx(5.5)
    assert law.wanted_band(state, "porter", "village") == "sought"
    law.cool(state, 1)  # 4.0
    assert law.wanted_band(state, "porter", "village") == "noticed"
    law.cool(state, 10)
    assert law.wanted_score(state, "porter", "village") == 0
    assert law.wanted_band(state, "porter", "village") == "unknown"


def test_cooling_is_not_banked_against_a_fresh_report(declared: Path) -> None:
    """
    Ten quiet days over a score of two must not pre-forgive the next crime.

    Without the cap the offset grows while there is nothing to cool, and the
    first severity-5 assault after a long quiet spell would land at zero.
    """
    state = GameState()
    _report(state, "porter", "fencing")
    law.cool(state, 10)
    _report(state, "porter", "assault_watch")
    assert law.wanted_score(state, "porter", "village") == pytest.approx(5)


def test_cooling_is_written_through_the_effect(declared: Path) -> None:
    state = GameState()
    _report(state, "porter", "assault_watch")
    out = law.cool(state, 1)
    assert out["type"] == "law_cool" and out["ok"] is True
    assert not any(ch.isdigit() for ch in out["text"])


# ---------------------------------------------------------------------------
# Undeclared: the flagship
# ---------------------------------------------------------------------------


def test_an_undeclared_law_is_inert_end_to_end() -> None:
    assert not law.declared()
    state = GameState()
    assert law.wanted_score(state, "self", "village") == 0
    assert law.wanted_band(state, "self", "village") == ""
    assert law.jurisdiction_of("edgewood_square") == ""
    for out in (
        law.cool(state, 3),
        _report(state, "self"),
        apply_effect(state, {"type": "quash_reports"}),
    ):
        assert out["ok"] is False
        # A refusal says why, so a log or a thread's receipt is diagnosable.
        assert out["message"]
    assert state.law == {}


def test_the_flagship_save_round_trips_with_an_empty_law() -> None:
    state = GameState()
    data = state.to_save_dict()
    assert data["law"] == {}
    assert GameState.from_dict(data).law == {}
    # A save written before the Law existed loads as "the watch knows nothing".
    data.pop("law")
    assert GameState.from_dict(data).law == {}
    assert "law" not in state.to_client_dict()

# ---------------------------------------------------------------------------
# Fix round 1: per-guise cooling, linked quash, refusals
# ---------------------------------------------------------------------------


def test_cooling_one_guise_does_not_forgive_another(declared: Path) -> None:
    """
    Quiet days wear down the file each report was FILED under, not the town.

    With one offset per jurisdiction, three days' cooling over the Magpie's
    two assaults pre-forgave a porter's fresh one down to "unknown".
    """
    state = GameState()
    _report(state, "magpie", "assault_watch")
    _report(state, "magpie", "assault_watch")
    law.cool(state, 3)
    assert law.wanted_score(state, "magpie", "village") == pytest.approx(5.5)
    _report(state, "porter", "assault_watch")
    assert law.wanted_score(state, "porter", "village") == pytest.approx(5)
    assert law.wanted_band(state, "porter", "village") == "sought"


def test_linked_guises_sum_their_cooled_files(declared: Path) -> None:
    state = GameState()
    _report(state, "magpie", "assault_watch")  # 5
    law.cool(state, 2)                         # magpie file -> 2
    _report(state, "self", "fencing")          # self file 2, uncooled
    assert law.wanted_score(state, "self", "village") == pytest.approx(4)
    assert law.wanted_score(state, "magpie", "village") == pytest.approx(4)


def test_links_are_transitive(tmp_path: Path) -> None:
    doc = copy.deepcopy(SPEC)
    doc["links"] = [["self", "magpie"], ["magpie", "porter"]]
    set_overlay({"paths": {"law": str(_write(tmp_path, doc))}})
    try:
        state = GameState()
        _report(state, "porter", "assault_watch")
        assert law.wanted_score(state, "self", "village") == pytest.approx(5)
    finally:
        set_overlay(None)


def test_quash_is_exact_by_default_and_linked_on_request(declared: Path) -> None:
    state = GameState()
    _report(state, "self", "pickpocket")
    _report(state, "magpie", "pickpocket")
    _report(state, "porter", "pickpocket")
    apply_effect(state, {"type": "quash_reports", "guise": "self"})
    assert [r["guise"] for r in state.law["reports"]] == ["magpie", "porter"]

    state = GameState()
    _report(state, "self", "pickpocket")
    _report(state, "magpie", "pickpocket")
    _report(state, "porter", "pickpocket")
    out = apply_effect(state, {"type": "quash_reports", "guise": "self", "linked": True})
    assert out["ok"] is True
    # The watch takes you for the Magpie, so a sergeant paid to lose you loses
    # both files -- and the porter, whom it does not connect, keeps his.
    assert [r["guise"] for r in state.law["reports"]] == ["porter"]


@pytest.mark.parametrize(
    "effect", [{"guise": "the_magpye"}, {"jurisdiction": "dockside"}]
)
def test_a_quash_naming_something_unknown_is_refused(
    declared: Path, effect: dict[str, Any]
) -> None:
    state = GameState()
    _report(state, "magpie", "pickpocket")
    before = copy.deepcopy(state.law)
    out = apply_effect(state, {"type": "quash_reports", **effect})
    assert out["ok"] is False and out["message"]
    assert state.law == before


def test_an_unusable_report_says_why(declared: Path) -> None:
    out = apply_effect(GameState(), {"type": "report", "deed": "treason",
                                     "guise": "self", "jurisdiction": "village"})
    assert out["ok"] is False and out["message"]


def test_a_quash_that_removes_nothing_writes_nothing(declared: Path) -> None:
    state = GameState()
    out = apply_effect(state, {"type": "quash_reports", "guise": "self"})
    assert out["ok"] is True and out["text"] == ""
    assert state.law == {}


def test_a_quash_recaps_the_cooling_left_over(declared: Path) -> None:
    """
    Canary for the post-quash re-cap: cooling that wore down a quashed report
    must not survive it to pre-forgive the next one.
    """
    state = GameState()
    _report(state, "porter", "assault_watch")
    _report(state, "porter", "fencing")
    law.cool(state, 5)  # porter file 7, offset capped at 7
    assert law.wanted_score(state, "porter", "village") == 0
    apply_effect(state, {"type": "quash_reports", "guise": "porter", "max_severity": 2})
    _report(state, "porter", "fencing")  # raw 7 again; offset must now be 5
    assert law.wanted_score(state, "porter", "village") == pytest.approx(2)


def test_a_malformed_cool_entry_reads_as_uncooled(declared: Path) -> None:
    """
    A jurisdiction whose cooling is not a mapping of files reads as no cooling.

    The flat `{jurisdiction: offset}` shape existed only on the unreleased
    v0.10.0 branch, so there is no migration -- but a reader that raises on a
    hand-edited or half-written save takes the whole turn down with it.
    """
    state = GameState()
    _report(state, "porter", "assault_watch")
    state.law["cool"] = {"village": 0.5}
    assert law.wanted_score(state, "porter", "village") == pytest.approx(5)
    out = law.cool(state, 1)
    assert out["ok"] is True
    assert law.wanted_score(state, "porter", "village") == pytest.approx(3.5)
    apply_effect(state, {"type": "report", "deed": "fencing", "guise": "porter",
                         "jurisdiction": "village"})
    state.law["cool"] = {"village": 0.5}
    apply_effect(state, {"type": "quash_reports", "max_severity": 2})
    assert law.wanted_score(state, "porter", "village") == pytest.approx(5)

"""
``ui.panels``: which engine panels a story draws, declared in ``game.yaml``
(v0.21.0, spec §2.2).

Omitted, a story gets the data-gated panels (they render only when their
payload key is present, which only a story declaring the system sends).
Present, exactly the listed panels, in order, each in its default region or
the one named. Malformed is a problem at activation, like every manifest key;
a data-gated panel listed by a story without its system is an advisory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from engine.games.manifest import UI_PANEL_SYSTEMS, UI_PANELS, from_dict, ui_panel_problems

ALL_PATHS = {"law": "l.yaml", "jobs": "j.yaml", "premises": "p", "encounters": "e"}


def _manifest(panels: Any = None, *, paths: dict[str, str] | None = None, omit: bool = False) -> Any:
    ui: dict[str, Any] = {"plugin": "_engine"}
    if not omit:
        ui["panels"] = panels
    return from_dict({"title": "T", "paths": dict(ALL_PATHS if paths is None else paths), "ui": ui}, slug="probe")


def test_the_table_is_the_specs() -> None:
    assert UI_PANELS == {
        "wanted": ("ledger", ("ledger", "shelf"), "data"),
        "job": ("shelf", ("shelf", "ledger"), "data"),
        "casing": ("ledger", ("ledger", "shelf"), "data"),
        "negotiation": ("shelf", ("shelf",), "data"),
        "rolls": ("toast", ("toast",), "data"),
        "people": ("stage", ("stage", "ledger"), "declared"),
        "encounter": ("shelf", ("shelf",), "declared"),
    }
    assert list(UI_PANELS) == ["wanted", "job", "casing", "negotiation", "rolls", "people", "encounter"]
    assert set(UI_PANEL_SYSTEMS) <= set(UI_PANELS)


def test_omitted_is_no_declaration_and_no_problem() -> None:
    manifest = _manifest(omit=True)
    assert manifest.panel_declaration is None
    assert ui_panel_problems(manifest) == ([], [])


def test_a_well_formed_declaration_is_carried_raw() -> None:
    panels = ["wanted", {"id": "people", "region": "stage"}, "encounter", {"id": "job"}]
    manifest = _manifest(panels)
    assert ui_panel_problems(manifest) == ([], [])
    assert manifest.panel_declaration == panels
    assert manifest.to_dict()["ui"]["panels"] == panels
    assert _manifest([]).panel_declaration == []


@pytest.mark.parametrize(
    ("panels", "fragment"),
    [
        ("wanted", "must be a list"),
        ({"wanted": True}, "must be a list"),
        (["poster"], "'poster' is not an engine panel"),
        (["wanted", "wanted"], "'wanted' is listed twice"),
        ([{"id": "rolls", "region": "shelf"}], "rolls cannot be drawn in region 'shelf'"),
        ([{"id": "people", "region": "header"}], "people cannot be drawn in region 'header'"),
        ([7], "neither a panel id nor an {id, region} mapping"),
        ([{"id": "job", "place": "shelf"}], "a key other than id/region: place"),
        ([{"id": ["job"]}], "is not an engine panel"),
        ([{"id": "job", "region": 5}], "job cannot be drawn in region 5"),
        ([{"id": "job", "region": ["shelf"]}], "job cannot be drawn in region ['shelf']"),
    ],
)
def test_each_malformed_declaration_is_an_error(panels: Any, fragment: str) -> None:
    errors, _advisories = ui_panel_problems(_manifest(panels))
    assert len(errors) == 1 and fragment in errors[0], errors


def test_a_panel_whose_system_is_undeclared_is_an_advisory() -> None:
    errors, advisories = ui_panel_problems(_manifest(["wanted", "job", "casing", "encounter", "people"], paths={}))
    assert errors == []
    assert advisories == [
        f"ui.panels lists {panel}, but the story declares no paths.{system}: it will never render"
        for panel, system in (("wanted", "law"), ("job", "jobs"), ("casing", "premises"), ("encounter", "encounters"))
    ]


def test_activation_refuses_a_malformed_declaration() -> None:
    from engine.games.registry import validate

    problems = validate(_manifest(["poster"]))
    assert any("'poster' is not an engine panel" in p for p in problems), problems


def test_the_content_validator_reports_both_kinds() -> None:
    from engine.games.validation import StoryValidator

    validator = StoryValidator(_manifest(["poster", "wanted"], paths={}))
    validator.check_ui_panels()
    rows = sorted((i.severity, i.source, i.ref_id, i.message) for i in validator.issues)
    assert rows == [
        ("error", "game.yaml", "ui.panels", "ui.panels[0]: 'poster' is not an engine panel "
         f"(legal: {', '.join(UI_PANELS)})"),
        ("warning", "game.yaml", "ui.panels",
         "ui.panels lists wanted, but the story declares no paths.law: it will never render"),
    ]


def test_a_null_region_is_the_default_and_a_region_error_keeps_its_advisory() -> None:
    assert ui_panel_problems(_manifest([{"id": "job", "region": None}])) == ([], [])
    errors, advisories = ui_panel_problems(_manifest([{"id": "wanted", "region": "toast"}], paths={}))
    assert len(errors) == 1 and "wanted cannot be drawn in region 'toast'" in errors[0]
    assert len(advisories) == 1 and "paths.law" in advisories[0]


def test_the_doctor_warns_for_a_panel_that_will_never_render(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util
    from pathlib import Path

    from engine.games import registry

    spec = importlib.util.spec_from_file_location(
        "doctor_ui_panels_under_test", Path(__file__).resolve().parents[1] / "scripts" / "doctor.py"
    )
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)

    manifest = _manifest(["wanted"], paths={})
    monkeypatch.setattr(registry, "discover", lambda: {"probe": manifest})
    monkeypatch.setattr(registry, "catalog", lambda: [])
    report = doctor.Report()
    doctor.check_games(report)
    warns = [row for row in report.rows if row[2] == doctor.WARN]
    assert warns == [
        ("Games", "probe", doctor.WARN,
         "ui.panels lists wanted, but the story declares no paths.law: it will never render")
    ]


def test_every_shipped_story_declares_well_formed_panels_or_none() -> None:
    from engine.games.registry import discover

    for slug, manifest in sorted(discover().items()):
        assert ui_panel_problems(manifest) == ([], []), slug


def test_hue_and_cry_declares_its_seven_panels_with_no_advisory() -> None:
    """
    v0.21.0 T14 (spec §9): HUE & CRY is the one shipped story that declares
    ``ui.panels``, every panel in its default region, and it declares each
    panel's system (law, jobs, premises, encounters), so the content
    validator has nothing to say about it.
    """
    from engine.games.registry import discover
    from engine.games.validation import StoryValidator

    manifest = discover()["hue-and-cry"]
    assert manifest.extras["ui"] == {
        "plugin": "hue-and-cry",
        "panels": ["wanted", "casing", "job", "people", "encounter", "negotiation", "rolls"],
    }
    for system in UI_PANEL_SYSTEMS.values():
        assert manifest.paths.get(system), system
    validator = StoryValidator(manifest)
    validator.check_ui_panels()
    assert validator.issues == []
    declaring = sorted(slug for slug, m in discover().items() if "panels" in (m.extras.get("ui") or {}))
    assert declaring == ["hue-and-cry"]


REGISTRY = Path(__file__).resolve().parents[1] / "ui" / "src" / "core" / "panels" / "registry.js"
_ROW = re.compile(
    r'\{\s*id:\s*"([a-z]+)",\s*region:\s*"([a-z]+)",\s*regions:\s*\[([^\]]*)\],\s*gate:\s*"(data|declared)"'
)


def _without_comments(source: str) -> str:
    """The registry's code with ``// ...`` and ``/* ... */`` comments removed,
    so a commented-out row is not read as a live one (T7 review 7)."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)//.*$", "", source)


def _registry_rows(source: str) -> list[tuple[str, str, str, str]]:
    return _ROW.findall(_without_comments(source))


def test_a_commented_out_registry_row_is_not_read() -> None:
    live = '{ id: "job", region: "shelf", regions: ["shelf"], gate: "data" },'
    text = (
        f"{live}\n"
        '// { id: "rolls", region: "toast", regions: ["toast"], gate: "data" },\n'
        '/* { id: "people", region: "stage", regions: ["stage"], gate: "declared" } */'
    )
    assert [row[0] for row in _registry_rows(text)] == ["job"]
    assert [row[0] for row in _ROW.findall(text)] == ["job", "rolls", "people"], "the canary: raw text reads them"


def test_the_client_registry_agrees_with_UI_PANELS() -> None:
    """One table in Python, one in the client (spec §2.2): read as text, compared whole."""
    rows = _registry_rows(REGISTRY.read_text(encoding="utf-8"))
    client = {
        panel_id: (region, tuple(re.findall(r'"([a-z]+)"', regions)), gate)
        for panel_id, region, regions, gate in rows
    }
    assert [row[0] for row in rows] == list(UI_PANELS), "order or ids differ"
    assert client == UI_PANELS

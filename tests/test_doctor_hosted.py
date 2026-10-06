"""
The doctor's hosted rows (v0.20.0 T18, spec §7.4).

With ``hosting.enabled``, ``check_config`` says how the service is set up,
read from the config and the storage root only (the doctor asks no live
process anything, and never prints a secret):

- ``hosting``: hosted, the front door's address, every request behind a login
  (local mode's LAN-exposure WARN does not apply to it);
- ``hosting block``: the closed schema as the instance reads it, a FAIL naming
  the key;
- ``accounts``: the count, a FAIL at zero ("nobody can log in");
- ``secret key``: its source, never the value;
- ``cookie_secure``: a WARN when false; ``public_origin`` and
  ``trusted_proxies`` shown;
- ``refusals``: a FAIL for each §6.7 startup refusal that would fire;
- ``production server``: a WARN on Windows; on POSIX, gunicorn or not;
- ``llm.lanes``: shown, with the sizing hint;
- ``storage``: in the image (``CLOCKWORK_ENV=docker``), a data root uid 10001
  cannot write is a FAIL naming the likely cause and the ``chown``.

With hosting off none of these rows exists: local mode's doctor is
v0.19.0's (its baselines, ``doctor_llm.txt`` and ``doctor_services.txt``,
are pinned elsewhere).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config

REPO = Path(__file__).resolve().parents[1]

HOSTED_ROWS = {
    "hosting block", "accounts", "secret key", "cookie_secure", "public_origin",
    "trusted_proxies", "refusals", "production server", "llm.lanes",
}

#: A key long and varied enough to be accepted; never expected in any row.
SENTINEL_KEY = "T18-sentinel-cookie-key-0123456789abcdefXYZ"


def _doctor() -> Any:
    spec = importlib.util.spec_from_file_location("doctor_hosted_under_test", REPO / "scripts" / "doctor.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


DOCTOR = _doctor()


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    directory = tmp_path / "config"
    directory.mkdir()
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_CONFIG", "CLOCKWORK_SECRET_KEY", "CLOCKWORK_STUDIO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield directory
    config._instance = None


def _write(directory: Path, tree: dict[str, Any]) -> None:
    (directory / "local.yaml").write_text(yaml.safe_dump(tree), encoding="utf-8")
    config._instance = None


def _hosting(directory: Path, extra: dict[str, Any] | None = None, **block: Any) -> None:
    _write(directory, {"hosting": {"enabled": True, **block}, **(extra or {})})


def _report() -> list[tuple[str, str, str, str]]:
    report = DOCTOR.Report()
    DOCTOR.check_config(report)
    return list(report.rows)


def _named(name: str) -> list[tuple[str, str]]:
    return [(row[2], row[3]) for row in _report() if row[1] == name]


def _one(name: str) -> tuple[str, str]:
    rows = _named(name)
    assert len(rows) == 1, (name, rows)
    return rows[0]


def _add_account(tmp_path: Path, name: str, *, disabled: bool = False) -> None:
    from engine.hosting.accounts import AccountStore
    from tests.hosted_app import new_password

    store = AccountStore(tmp_path / "data" / "hosting")
    store.add(name, new_password())
    if disabled:
        store.disable(name, force=True)


def test_local_mode_has_none_of_the_hosted_rows(cfg_dir: Path) -> None:
    names = {row[1] for row in _report()}
    assert not names & HOSTED_ROWS, names & HOSTED_ROWS


def test_the_hosting_row_says_hosted_not_exposed(cfg_dir: Path) -> None:
    _hosting(cfg_dir, extra={"scene": {"clockwork": {"host": "0.0.0.0"}}})
    status, detail = _one("hosting")
    assert status == DOCTOR.OK
    assert detail.startswith("hosted: the front door on 0.0.0.0:") and "login" in detail


def test_in_the_image_a_loopback_front_door_warns(cfg_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T18 fix round 1 (I1): the published port never reaches the container's loopback."""
    _hosting(cfg_dir, extra={"scene": {"clockwork": {"host": "127.0.0.1"}}})
    assert _one("hosting")[0] == DOCTOR.OK  # outside a container, loopback is right
    monkeypatch.setenv("CLOCKWORK_ENV", "docker")
    config._instance = None
    status, detail = _one("hosting")
    assert status == DOCTOR.WARN and "published port reaches nothing" in detail
    _hosting(cfg_dir, extra={"scene": {"clockwork": {"host": "0.0.0.0"}}})
    assert _one("hosting")[0] == DOCTOR.OK


def test_no_account_is_a_fail_naming_the_command(cfg_dir: Path) -> None:
    _hosting(cfg_dir)
    assert _one("accounts") == (DOCTOR.FAIL, "nobody can log in: python scripts/users.py add <name>")


def test_the_accounts_are_counted(cfg_dir: Path, tmp_path: Path) -> None:
    _hosting(cfg_dir)
    _add_account(tmp_path, "alice")
    _add_account(tmp_path, "bob")
    assert _one("accounts") == (DOCTOR.OK, "2 enabled of 2")
    _add_account(tmp_path, "carol", disabled=True)
    assert _one("accounts") == (DOCTOR.OK, "2 enabled of 3")


def test_only_disabled_accounts_is_a_fail(cfg_dir: Path, tmp_path: Path) -> None:
    _hosting(cfg_dir)
    _add_account(tmp_path, "alice", disabled=True)
    assert _one("accounts")[0] == DOCTOR.FAIL


def test_the_secret_key_s_source_and_never_its_value(cfg_dir: Path, monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    _hosting(cfg_dir)
    status, detail = _one("secret key")
    path = tmp_path / "data" / "hosting" / "secret_key"
    assert (status, detail) == (DOCTOR.OK, f"generated: {path} (made at the first start)")

    monkeypatch.setenv("CLOCKWORK_SECRET_KEY", SENTINEL_KEY)
    config._instance = None
    assert _one("secret key") == (DOCTOR.OK, "from the environment (CLOCKWORK_SECRET_KEY)")
    assert SENTINEL_KEY not in repr(_report())


def test_a_short_secret_key_fails_the_block_and_is_not_shown(cfg_dir: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    short = "too-short-key-T18"
    monkeypatch.setenv("CLOCKWORK_SECRET_KEY", short)
    _hosting(cfg_dir)
    status, detail = _one("hosting block")
    assert status == DOCTOR.FAIL and detail.startswith("hosting.secret_key:")
    assert short not in repr(_report())
    assert _named("secret key") == []  # nothing to say about a key that will not be used


def test_cookie_secure_false_warns(cfg_dir: Path) -> None:
    _hosting(cfg_dir)
    assert _one("cookie_secure")[0] == DOCTOR.OK
    _hosting(cfg_dir, cookie_secure=False)
    status, detail = _one("cookie_secure")
    assert status == DOCTOR.WARN and "plain HTTP" in detail


def test_public_origin_and_trusted_proxies_are_shown(cfg_dir: Path) -> None:
    _hosting(cfg_dir)
    assert _one("public_origin") == (DOCTOR.OK, '"" - same-origin only')
    assert _one("trusted_proxies") == (DOCTOR.OK, "0 - forwarded headers are ignored")
    _hosting(cfg_dir, public_origin="https://play.example.org", trusted_proxies=1)
    assert _one("public_origin") == (DOCTOR.OK, "https://play.example.org")
    status, detail = _one("trusted_proxies")
    assert status == DOCTOR.OK and detail.startswith("1 - ")


def test_each_startup_refusal_is_a_fail(cfg_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _hosting(cfg_dir)
    status, detail = _one("refusals")
    assert status == DOCTOR.OK and "POST /api/settings answers 403" in detail

    _hosting(cfg_dir, extra={"llm": {"mcp": {"enabled": True}}})
    status, detail = _one("refusals")
    assert status == DOCTOR.FAIL and "llm.mcp.enabled" in detail

    _hosting(cfg_dir)
    monkeypatch.setenv("CLOCKWORK_STUDIO", "1")
    status, detail = _one("refusals")
    assert status == DOCTOR.FAIL and "CLOCKWORK_STUDIO" in detail


def test_the_production_server_row(cfg_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.hosting.supervisor import process

    _hosting(cfg_dir)
    monkeypatch.setattr(DOCTOR, "_on_windows", lambda: True)
    assert _one("production server") == (DOCTOR.WARN, DOCTOR.WINDOWS_SERVER_WARNING)
    assert "gunicorn does not run on Windows" in DOCTOR.WINDOWS_SERVER_WARNING

    monkeypatch.setattr(DOCTOR, "_on_windows", lambda: False)
    monkeypatch.setattr(process, "gunicorn_runs_here", lambda: True)
    status, detail = _one("production server")
    assert status == DOCTOR.OK and detail.startswith("gunicorn")
    monkeypatch.setattr(process, "gunicorn_runs_here", lambda: False)
    status, detail = _one("production server")
    assert status == DOCTOR.WARN and "requirements-server.txt" in detail


def test_the_lanes_are_shown_with_the_sizing_hint(cfg_dir: Path) -> None:
    _hosting(cfg_dir, extra={"llm": {"lanes": {"narration": 3, "utility": 2}}})
    status, detail = _one("llm.lanes")
    assert status == DOCTOR.OK
    assert detail.startswith("narration 3, utility 2 - ")
    assert DOCTOR.LANES_HINT in detail and "OLLAMA_NUM_PARALLEL" in detail


def test_in_the_image_an_unwritable_data_root_names_the_chown(cfg_dir: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    _hosting(cfg_dir)
    monkeypatch.setattr(DOCTOR, "_writable", lambda directory: (False, f"cannot write in {directory}: denied"))
    status, detail = _one("storage")
    assert status == DOCTOR.FAIL and "chown" not in detail  # outside the image: the plain fact

    monkeypatch.setenv("CLOCKWORK_ENV", "docker")
    config._instance = None
    status, detail = _one("storage")
    assert status == DOCTOR.FAIL
    assert "uid 10001" in detail and "sudo chown -R 10001:10001 <the host directory>" in detail

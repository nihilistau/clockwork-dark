"""
The legacy config names are refused (v0.21.0, spec §10).

v0.19.0 renamed the model server's block ``lmstudio:`` to ``llm:`` (and
``stack.services.lmstudio`` to ``stack.services.llm``), and v0.20.0 moved
saves under ``storage.root``; both old names were still read, with a WARNING,
for two releases. v0.21.0 removes the aliases. An OPERATOR layer -- a
``CLOCKWORK_ENV`` layer, ``config/local.yaml``, a ``CLOCKWORK_CONFIG`` file,
hosted mode's admin layer -- that still holds one is REFUSED at config load
with ``LegacyConfigError``, naming the file, the old key and the fix. Never
ignored: ignoring ``lmstudio:`` would point the game at the shipped default
server, and ignoring ``paths.saves`` would hide every save in the old folder.

Also here: the AST scans that keep the old names out of first-party code (no
``get("lmstudio.…")``, and no import of or string naming the deleted
``engine.lmstudio`` package), and the test that the package is gone.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config
from engine.llm.providers import PROVIDERS

REPO = Path(__file__).resolve().parents[1]

#: One sample layer per refused key.
LEGACY_LAYERS: dict[str, dict[str, Any]] = {
    "lmstudio": {"lmstudio": {"base_url": "http://10.9.8.7:4321/v1", "ttl_seconds": 600}},
    "stack.services.lmstudio": {"stack": {"services": {"lmstudio": {"enabled": False}}}},
    "paths.saves": {"paths": {"saves": "old-saves"}},
}


@pytest.fixture
def layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The real default layer, and ``tmp_path / "config"`` standing in for ``config/``."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield config_dir
    config._instance = None


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    return path


def _fresh() -> config.ConfigManager:
    config._instance = None
    return config.get_config()


def _assert_refused(error: config.LegacyConfigError, path: Path, key: str) -> None:
    assert isinstance(error, config.ConfigError) and isinstance(error, ValueError)
    assert [(source, dotted) for source, dotted, _ in error.findings] == [(str(path), key)]
    message = str(error)
    assert message.startswith(f"{path}: ") and "v0.21.0" in message, message


def _doctor() -> Any:
    spec = importlib.util.spec_from_file_location("doctor_legacy", REPO / "scripts" / "doctor.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# -- each operator layer, each key -----------------------------------------------


@pytest.mark.parametrize("key", sorted(LEGACY_LAYERS))
def test_local_yaml_holding_a_legacy_key_is_refused(layers: Path, key: str) -> None:
    path = _write(layers / "local.yaml", LEGACY_LAYERS[key])
    with pytest.raises(config.LegacyConfigError) as caught:
        _fresh()
    _assert_refused(caught.value, path, key)


@pytest.mark.parametrize("key", sorted(LEGACY_LAYERS))
def test_an_environment_layer_holding_a_legacy_key_is_refused(
    layers: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    path = _write(layers / "staging.yaml", LEGACY_LAYERS[key])
    monkeypatch.setenv("CLOCKWORK_ENV", "staging")
    with pytest.raises(config.LegacyConfigError) as caught:
        _fresh()
    _assert_refused(caught.value, path, key)


@pytest.mark.parametrize("key", sorted(LEGACY_LAYERS))
def test_a_clockwork_config_file_holding_a_legacy_key_is_refused(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    path = _write(tmp_path / "operator" / "game.yaml", LEGACY_LAYERS[key])
    monkeypatch.setenv("CLOCKWORK_CONFIG", str(path))
    with pytest.raises(config.LegacyConfigError) as caught:
        _fresh()
    _assert_refused(caught.value, path, key)


@pytest.mark.parametrize("key", sorted(LEGACY_LAYERS))
def test_the_admin_layer_holding_a_legacy_key_is_refused(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    from engine.hosting.admin.model import ADMIN_LAYER_FILE

    _write(layers / "local.yaml", {"hosting": {"enabled": True}})
    data = tmp_path / "data"
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(data))
    path = _write(data / "hosting" / ADMIN_LAYER_FILE, LEGACY_LAYERS[key])
    with pytest.raises(config.LegacyConfigError) as caught:
        _fresh()
    _assert_refused(caught.value, path, key)


def test_every_finding_is_reported_at_once_in_layer_order(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _write(layers / "local.yaml", LEGACY_LAYERS["lmstudio"])
    external = _write(
        tmp_path / "operator" / "game.yaml",
        {**LEGACY_LAYERS["paths.saves"], **LEGACY_LAYERS["stack.services.lmstudio"]},
    )
    monkeypatch.setenv("CLOCKWORK_CONFIG", str(external))
    with pytest.raises(config.LegacyConfigError) as caught:
        _fresh()
    assert [(s, k) for s, k, _ in caught.value.findings] == [
        (str(local), "lmstudio"),
        (str(external), "stack.services.lmstudio"),
        (str(external), "paths.saves"),
    ]
    assert len(str(caught.value).splitlines()) == 3


def test_the_messages_are_the_specs(layers: Path) -> None:
    path = _write(layers / "local.yaml", {**LEGACY_LAYERS["lmstudio"], **LEGACY_LAYERS["paths.saves"]})
    with pytest.raises(config.LegacyConfigError) as caught:
        _fresh()
    assert str(caught.value).splitlines() == [
        f'{path}: the "lmstudio:" block was renamed "llm:" in v0.19.0 and is no longer read '
        '(v0.21.0). Rename the block; "ttl_seconds" inside it is now "keep_alive_seconds".',
        f'{path}: "paths.saves" is no longer read (v0.21.0). Saves live under storage.root as '
        "<root>/saves: set storage.root (or CLOCKWORK_DATA_DIR) to the folder that holds your "
        "saves folder, or move the saves there.",
    ]


def test_the_shipped_default_holds_no_legacy_key() -> None:
    shipped = config._load_yaml(REPO / "config" / "default.yaml")
    assert config.legacy_findings(shipped, "config/default.yaml") == []


def test_the_suites_sandbox_layer_holds_no_legacy_key() -> None:
    raw = os.environ.get(config.TEST_SANDBOX_ENV, "")
    _pid, _sep, layer = raw.partition(os.pathsep)
    assert layer, f"{config.TEST_SANDBOX_ENV} names no sandbox layer: {raw!r}"
    assert config.legacy_findings(config._load_yaml(Path(layer)), layer) == []


def test_the_llm_block_is_read_by_its_own_name_only(layers: Path) -> None:
    _write(layers / "local.yaml", {"llm": {"base_url": "http://10.9.8.7:4321/v1"}})
    cfg = _fresh()
    assert cfg.get("llm.base_url") == "http://10.9.8.7:4321/v1"
    # No read alias any more: the old dotted name is simply absent. (Built at
    # run time, so the AST scan below does not count these as reads.)
    old = "lmstudio" + ".base_url"
    assert cfg.get(old) is None
    assert cfg._raw(old) is None
    assert "lmstudio" not in cfg.as_dict()


# -- where the refusal surfaces --------------------------------------------------


def test_the_doctor_reports_each_refusal_as_a_config_fail(layers: Path) -> None:
    doctor = _doctor()
    path = _write(layers / "local.yaml", {**LEGACY_LAYERS["lmstudio"], **LEGACY_LAYERS["paths.saves"]})
    report = doctor.Report()
    doctor.check_config(report)
    fails = [row for row in report.rows if row[0] == "Config" and row[2] == doctor.FAIL]
    assert [row[1] for row in fails] == ["legacy lmstudio", "legacy paths.saves"]
    assert all(row[3].startswith(f"{path}: ") for row in fails)
    assert report.failed


def test_the_doctor_runs_to_the_end_and_exits_nonzero(
    layers: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doctor = _doctor()
    for name in (
        "check_python", "check_games", "check_state_schemas", "check_story_content",
        "check_inherited_content", "check_services", "check_llm", "check_voice",
        "check_content", "check_saves",
    ):
        monkeypatch.setattr(doctor, name, lambda report: None)

    def check_ui(report: Any) -> None:  # stands in for any check that needs a config
        config.get_config()

    monkeypatch.setattr(doctor, "check_ui", check_ui)
    _write(layers / "local.yaml", LEGACY_LAYERS["lmstudio"])
    # -v: without it main() calls logging.disable(WARNING) and never undoes
    # it, which would silence every later caplog test in this process.
    assert doctor.main(["-v"]) == 1
    out = capsys.readouterr().out
    assert "legacy lmstudio" in out
    assert "check_ui" in out and "not run: the config does not load" in out
    assert "LegacyConfigError(" not in out


def test_the_doctors_saves_check_leaves_the_refusal_to_main(layers: Path) -> None:
    """Fix round 1: not repeated as a ``Saves [warn] store`` row, but "not run"."""
    doctor = _doctor()
    _write(layers / "local.yaml", LEGACY_LAYERS["paths.saves"])
    report = doctor.Report()
    with pytest.raises(config.LegacyConfigError):
        doctor.check_saves(report)
    assert not [row for row in report.rows if row[0] == "Saves"]


def test_a_layer_read_twice_is_reported_once(layers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix round 1: ``CLOCKWORK_ENV=local`` names local.yaml as the env layer too."""
    path = _write(layers / "local.yaml", LEGACY_LAYERS["lmstudio"])
    monkeypatch.setenv("CLOCKWORK_ENV", "local")
    with pytest.raises(config.LegacyConfigError) as caught:
        _fresh()
    _assert_refused(caught.value, path, "lmstudio")


def test_the_launcher_prints_the_refusal_and_exits_2(
    layers: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import launcher

    path = _write(layers / "local.yaml", LEGACY_LAYERS["stack.services.lmstudio"])
    assert launcher.main(["--list"]) == 2
    assert f'{path}: "stack.services.lmstudio" was renamed' in capsys.readouterr().err


def test_the_supervisor_refuses_to_start_and_exits_1(
    layers: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from engine.hosting.supervisor.__main__ import REFUSED_PREFIX, main

    path = _write(layers / "local.yaml", {"hosting": {"enabled": True}, **LEGACY_LAYERS["paths.saves"]})
    assert main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith(f"{REFUSED_PREFIX}: {path}: ")


def test_the_conftest_guard_exits_2_with_the_message(capsys: pytest.CaptureFixture[str]) -> None:
    """Plan decision 2: the guard is tested as a function (a child pytest is refused)."""
    from conftest import _exit_on_legacy_config  # the loaded conftest, not a copy

    finding = ("C:/owner/config/local.yaml", "lmstudio", "C:/owner/config/local.yaml: renamed")

    def resolve() -> Any:
        raise config.LegacyConfigError([finding])

    with pytest.raises(SystemExit) as caught:
        _exit_on_legacy_config(resolve)
    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("The test suite cannot start: ")
    assert "C:/owner/config/local.yaml: renamed" in err
    assert _exit_on_legacy_config(lambda: ("root", "saves")) == ("root", "saves")


def _calls_guard(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_exit_on_legacy_config"
        for n in ast.walk(node)
    )


def _imports_engine_beyond_config(node: ast.stmt) -> bool:
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom) and node.level == 0:
        names = [node.module or ""]
    else:
        return False
    return any((n == "engine" or n.startswith("engine.")) and n != "engine.config" for n in names)


def test_the_conftest_guard_runs_before_any_engine_import() -> None:
    """
    Fix round 1: the guard must be CALLED at module level before the first
    import of an engine module other than ``engine.config``. Importing
    ``engine.game.engine`` loads the locations, which builds the config, so a
    guard placed after it never runs: a legacy key ended in "ImportError
    while loading conftest" (exit 4), not the message with exit 2.
    """
    body = ast.parse((REPO / "tests" / "conftest.py").read_text(encoding="utf-8")).body
    guard = [i for i, node in enumerate(body) if not isinstance(node, ast.FunctionDef) and _calls_guard(node)]
    engine = [i for i, node in enumerate(body) if _imports_engine_beyond_config(node)]
    assert guard and engine, (guard, engine)
    assert guard[0] < engine[0], (
        f"conftest's first engine import (statement {engine[0]}) runs before the "
        f"legacy-config guard (statement {guard[0]})"
    )


# -- a story may set neither block; providers -------------------------------------


def test_a_story_may_not_set_either_block() -> None:
    from engine.games.manifest import SETTING_REFUSALS, refusal_reason

    prefixes = dict(SETTING_REFUSALS)
    assert prefixes["llm"] == prefixes["lmstudio"]
    assert "machine" in refusal_reason("llm.api_key")
    assert "machine" in refusal_reason("lmstudio.base_url")


def test_an_unknown_provider_is_refused_at_load(layers: Path) -> None:
    _write(layers / "local.yaml", {"llm": {"provider": "lm-studio"}})
    with pytest.raises(ValueError) as caught:
        _fresh()
    message = str(caught.value)
    assert "lm-studio" in message
    for name in PROVIDERS:
        assert name in message


def test_every_legal_provider_loads(layers: Path) -> None:
    assert set(PROVIDERS) == {"lmstudio", "vllm", "llamacpp", "ollama", "openai_compat"}
    for name in PROVIDERS:
        _write(layers / "local.yaml", {"llm": {"provider": name}})
        assert _fresh().get("llm.provider") == name


# -- the AST scans -----------------------------------------------------------------

#: The config readers a legacy dotted key could be passed to.
_READERS = frozenset({"get", "section", "_raw", "resolve_path"})
#: The old package's names, built at run time so this file names none of them.
_OLD = "engine." + "lmstudio"
_OLD_SPELLINGS = (_OLD, "engine/" + "lmstudio", "engine\\" + "lmstudio")


def _first_party() -> list[Path]:
    files = [REPO / "launcher.py"]
    for top in ("engine", "scripts", "tests", "content"):
        files.extend((REPO / top).rglob("*.py"))
    return sorted(p for p in files if "__pycache__" not in p.parts)


def legacy_key_reads(source: str, name: str) -> list[str]:
    """Every ``x.get("lmstudio.…")``-shaped call (get/section/_raw/resolve_path)."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source, filename=name)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _READERS or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.startswith("lmstudio."):
            hits.append(f"{name}:{node.lineno}: {node.func.attr}({first.value!r})")
    return hits


def _names_old_package(text: str) -> bool:
    return any(
        text == old or (old + ".") in text or (old + "/") in text or (old + "\\") in text
        for old in _OLD_SPELLINGS
    )


def _package_of(path: Path) -> list[str]:
    try:
        return list(path.resolve().relative_to(REPO.resolve()).with_suffix("").parts)[:-1]
    except ValueError:
        return []


def old_package_references(source: str, path: Path) -> list[str]:
    """Every import of, and string naming, the deleted package (relative imports resolved)."""
    package = _package_of(path)
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if isinstance(node, ast.Import):
            found += [f"{node.lineno}: import {a.name}" for a in node.names if _names_old_package(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                module = node.module or ""
            elif node.level - 1 <= len(package):
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = ""
            if module and _names_old_package(module):
                found.append(f"{node.lineno}: from {module} import ...")
            if module == "engine" and any(a.name == "lmstudio" for a in node.names):
                found.append(f"{node.lineno}: from engine import lmstudio")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _names_old_package(node.value):
            found.append(f"{node.lineno}: string {node.value.splitlines()[0][:80]!r}")
    return found


def test_no_first_party_code_reads_a_lmstudio_key() -> None:
    hits: list[str] = []
    for path in _first_party():
        hits += legacy_key_reads(path.read_text(encoding="utf-8"), str(path.relative_to(REPO)))
    assert not hits, "a lmstudio.* key is still read:\n" + "\n".join(hits)


def test_no_first_party_code_names_the_deleted_package() -> None:
    offenders = {
        str(path.relative_to(REPO)): refs
        for path in _first_party()
        if (refs := old_package_references(path.read_text(encoding="utf-8"), path))
    }
    assert not offenders, offenders


def test_the_scans_catch_what_they_guard(tmp_path: Path) -> None:
    """Canary: neither scan is vacuous, and the key-source scopes are not reads."""
    assert len(legacy_key_reads('cfg.get("lmstudio.base_url")\ncfg.section("lmstudio.profiles")', "p")) == 2
    assert legacy_key_reads('cfg.get("llm.api_key", "${file:a|lmstudio?file:lmstudio.txt}")', "p") == []
    probe = tmp_path / "engine" / "probe.py"
    probe.parent.mkdir()
    old = "engine." + "lmstudio"
    source = f"import {old}.backend\nfrom {old}.registry import M\nfrom engine import lmstudio\nT = '{old}.backend.x'\n"
    assert len(old_package_references(source, probe)) == 4
    assert old_package_references("import engine.llm.backend\nNAME = 'lmstudio'\n", probe) == []


def test_the_shim_package_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("engine." + "lmstudio")
    assert not (REPO / "engine" / "lmstudio").exists()

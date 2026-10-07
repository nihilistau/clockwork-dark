"""engine/yamlio.py (v0.21.1): libyaml when it agrees, the pure parser's
own error when it does not, and no engine site left on the slow parser."""

from __future__ import annotations

import ast
import io
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from engine import yamlio

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"

if shutil.which("git") is None:
    pytest.skip("git is not on PATH: the tracked files cannot be listed", allow_module_level=True)

#: Tracked files only (git ls-files), so the owner's storage root (the
#: top-level data/: saves, media -- untracked) and config/local.yaml
#: (gitignored) are never read.
SHIPPED = sorted(
    ROOT / line for line in subprocess.run(
        ["git", "ls-files", "--", "*.yaml", "*.yml"], cwd=str(ROOT),
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout.splitlines()
    if line and not line.startswith("data/") and not line.endswith("local.yaml")
)

#: Malformed documents, one per kind of failure: a scanner, parser, composer
#: and constructor error, a tab, a control character, a bad version.
BAD = [
    "a: [1, 2\n",
    "a: b: c\n",
    "\tkey: 1\n",
    "- a\nb: 1\n",
    "a: *nowhere\n",
    "a: !!python/object:os.system x\n",
    "a: \x07\n",
    "%YAML 2.0\n---\na: 1\n",
    "a: 'unclosed\n",
    'a: "\\q"\n',
    "a: |\n  x\n b\n",
]


#: Documents libyaml reads MORE leniently than the pure parser (T3 review,
#: finding 1): a tab after a token, which the pure parser refuses, and a
#: byte-order mark past the first character. yamlio must give the pure
#: parser's answer for each -- its error, or its value.
LENIENT = [
    "a: 1\t\n",
    "a:\t1\n",
    "- a\t\n",
    "a: [1,\t2]\n",
    'a: "x"\t\n',
    "a: 1 \t# c\n",
    "a: {b:\t1}\n",
    "? a\t\n",
    "\ufeff\ufeffa: 1\n",
    "a: 1\n\ufeffb: 2\n",
]


def _outcome(load: Any, make: Any) -> Any:
    """What a load gives: the value's shape, or the error's type and text."""
    try:
        return ("value", _shape(load(make()), {}))
    except yaml.YAMLError as exc:
        return ("error", type(exc).__name__, str(exc))


def _shape(value: Any, seen: dict[int, int]) -> Any:
    """``value`` as nested tuples that keep what ``==`` does not: each node's
    type, a mapping's key order, and which nodes are one object (an alias)."""
    if isinstance(value, (dict, list, set)):
        if id(value) in seen:
            return ("alias", seen[id(value)])
        seen[id(value)] = len(seen)
    if isinstance(value, dict):
        return ("dict", tuple((_shape(k, seen), _shape(v, seen)) for k, v in value.items()))
    if isinstance(value, list):
        return ("list", tuple(_shape(v, seen) for v in value))
    if isinstance(value, set):
        return ("set", tuple(sorted(repr(v) for v in value)))
    return (type(value).__name__, repr(value))


def test_libyaml_is_present() -> None:
    assert yaml.__with_libyaml__, "PyYAML was installed without libyaml: reinstall the wheel"


def test_the_shipped_files_were_found() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in SHIPPED}
    assert "config/default.yaml" in names
    assert any(n.startswith("games/hue-and-cry/") for n in names)


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_shipped_file_parses_the_same_both_ways(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    try:
        pure = yaml.safe_load(text)
    except yaml.YAMLError:
        # A template not yet filled in (scripts/story_template/*: `{{slug}}`)
        # is not YAML until it is: it must fail exactly as it did.
        pure_err, ours_err = _both(yamlio.safe_load, lambda: text)
        assert type(ours_err) is type(pure_err) and str(ours_err) == str(pure_err)
        return
    assert yamlio.safe_load(text) == pure
    assert _shape(yamlio.safe_load(text), {}) == _shape(pure, {})
    with path.open(encoding="utf-8") as handle:  # as most engine sites pass it
        assert _shape(yamlio.safe_load(handle), {}) == _shape(pure, {})


def test_types_order_and_anchors_are_kept() -> None:
    text = (
        "z: 1\na: 1.5\nm: 2001-12-14\nb: !!binary aGk=\nn: ~\nt: yes\n"
        "base: &b {k: [1, 2]}\nuse: *b\nmerged:\n  <<: *b\n  j: 0o17\n"
    )
    ours, pure = yamlio.safe_load(text), yaml.safe_load(text)
    assert list(ours) == list(pure) == ["z", "a", "m", "b", "n", "t", "base", "use", "merged"]
    assert ours["use"] is ours["base"]
    assert _shape(ours, {}) == _shape(pure, {})


def test_a_stream_is_read_like_text() -> None:
    assert yamlio.safe_load(io.StringIO("a: [1, 2]\n")) == {"a": [1, 2]}
    assert yamlio.safe_load(io.BytesIO(b"\xef\xbb\xbfa: 1\n")) == {"a": 1}
    assert yamlio.safe_load("") is None and yamlio.safe_load(io.StringIO("")) is None


def _both(load: Any, make: Any) -> tuple[BaseException, BaseException]:
    with pytest.raises(Exception) as pure:
        yaml.safe_load(make())
    with pytest.raises(Exception) as ours:
        load(make())
    return pure.value, ours.value


@pytest.mark.parametrize("bad", BAD)
def test_a_malformed_document_raises_the_pure_parsers_own_error(bad: str) -> None:
    pure, ours = _both(yamlio.safe_load, lambda: bad)
    assert isinstance(pure, yaml.YAMLError)
    assert type(ours) is type(pure) and str(ours) == str(pure)
    pure, ours = _both(yamlio.safe_load, lambda: bad.encode("utf-8"))
    assert type(ours) is type(pure) and str(ours) == str(pure)


@pytest.mark.parametrize("doc", LENIENT, ids=ascii)
def test_what_libyaml_would_accept_reads_as_the_pure_parser_reads_it(doc: str, tmp_path: Path) -> None:
    assert _outcome(yamlio.safe_load, lambda: doc) == _outcome(yaml.safe_load, lambda: doc)
    raw = doc.encode("utf-8")
    assert _outcome(yamlio.safe_load, lambda: raw) == _outcome(yaml.safe_load, lambda: raw)
    path = tmp_path / "lenient.yaml"
    path.write_bytes(raw)
    for mode in ({"encoding": "utf-8"}, {"mode": "rb"}):
        with path.open(**mode) as a, path.open(**mode) as b:
            assert _outcome(yamlio.safe_load, lambda: a) == _outcome(yaml.safe_load, lambda: b)


def test_no_shipped_file_pays_for_the_lenient_guard() -> None:
    """Every tracked file still goes through libyaml: none holds a tab or a
    byte-order mark past its first character."""
    routed = [p.relative_to(ROOT).as_posix() for p in SHIPPED if yamlio._pure_only(p.read_bytes())]
    assert not routed, routed


@pytest.mark.parametrize("bad", BAD)
def test_a_malformed_file_keeps_its_name_in_the_error(bad: str, tmp_path: Path) -> None:
    """A stream's error names the file and quotes no line (rule 5: the config
    layers' messages rely on it); a string's would say ``<unicode string>``."""
    path = tmp_path / "broken.yaml"
    path.write_text(bad, encoding="utf-8")
    for mode in ({"encoding": "utf-8"}, {"mode": "rb"}):
        handles: list[Any] = []

        def make() -> Any:
            handles.append(path.open(**mode))
            return handles[-1]

        try:
            pure, ours = _both(yamlio.safe_load, make)
        finally:
            for handle in handles:
                handle.close()
        assert type(ours) is type(pure) and str(ours) == str(pure)
        mark = getattr(pure, "problem_mark", None)
        if mark is not None:
            assert mark.name == str(path)


def test_a_file_that_is_not_utf8_fails_as_it_did(tmp_path: Path) -> None:
    """The read itself fails: the stream is rewound and the pure parser fails
    it as before -- here a syntax error in its first chunk, before the parser
    ever reads the bad byte 100 KB on (read whole, the byte would win)."""
    for name, data in (
        ("bad_byte.yaml", b"a: \xff\xfe\n"),
        ("late_byte.yaml", b"a: b: c\n" + b"# pad\n" * 20000 + b"z: \xff\n"),
    ):
        path = tmp_path / name
        path.write_bytes(data)
        handles: list[Any] = []

        def make() -> Any:
            handles.append(path.open(encoding="utf-8"))
            return handles[-1]

        try:
            pure, ours = _both(yamlio.safe_load, make)
        finally:
            for handle in handles:
                handle.close()
        assert type(ours) is type(pure) and str(ours) == str(pure)
    assert isinstance(pure, yaml.YAMLError)  # the late byte never mattered


def test_a_broken_manifest_reports_as_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end through an author-facing message (``ManifestError``)."""
    from engine.games import manifest as manifest_mod

    story = tmp_path / "broken-story"
    story.mkdir()
    path = story / "game.yaml"
    path.write_text("id: broken-story\ntitle: [unclosed\n", encoding="utf-8")
    with pytest.raises(manifest_mod.ManifestError) as ours:
        manifest_mod.load(path)
    monkeypatch.setattr(yamlio, "_FAST", None)  # the pure parser alone, as before v0.21.1
    with pytest.raises(manifest_mod.ManifestError) as pure:
        manifest_mod.load(path)
    assert str(ours.value) == str(pure.value)
    assert f'in "{path}"' in str(ours.value)


def test_no_engine_module_calls_yaml_safe_load_directly() -> None:
    offenders = []
    for path in ENGINE.rglob("*.py"):
        if path.name == "yamlio.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Attribute) and node.attr in ("safe_load", "safe_load_all")
                    and isinstance(node.value, ast.Name) and node.value.id == "yaml"):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, f"use engine.yamlio.safe_load: {offenders}"

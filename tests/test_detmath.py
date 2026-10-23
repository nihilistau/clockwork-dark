"""The engine's transcendental math is the same float on every platform (v0.23.2, AGENTS.md rule 11).

CI (Linux) and the owner's workstation (Windows) gave two different saves for one seed: READ RECEIPTS' day-60 run
(``tests/test_social_turn_cost.py``) matched p0387 at ``170.38475129978946`` hours on Windows and
``170.38475129978943`` on Linux, a lognormal draw (``random.gauss`` and ``math.exp``) one ulp apart because MSVC's
and glibc's libm round differently. ``engine/game/detmath.py`` computes those functions in software. Three guards:

- **the scan**: no module under ``engine/`` but ``detmath`` calls a libm transcendental, a ``random`` distribution
  built on one, ``statistics.NormalDist``, or a float ``**``;
- **another libm**: every engine draw built on them gives the same float when ``math``'s and ``random``'s
  functions are moved one ulp, as another platform's libm can be (fails on the cause on ANY platform);
- **pinned values**: detmath's results as exact hex floats, recorded in a ``python:3.11-slim-bookworm`` container
  (glibc) and held on Windows.
"""

from __future__ import annotations

import ast
import math
import random
from pathlib import Path

import pytest

from engine.game import detmath
from engine.social import behaviour, growth, population
from engine.social.games import this_or_that

ROOT = Path(__file__).resolve().parents[1]

#: libm functions whose last bit is the platform's (sqrt, floor, fabs, copysign and the like are IEEE-exact).
LIBM = {"exp", "exp2", "expm1", "log", "log2", "log10", "log1p", "pow", "sin", "cos", "tan", "asin", "acos",
        "atan", "atan2", "sinh", "cosh", "tanh", "asinh", "acosh", "atanh", "erf", "erfc", "gamma", "lgamma",
        "hypot", "cbrt", "dist"}
#: random.Random's distributions built on libm (uniform, randint, choice, choices, sample, shuffle, triangular
#: and random itself are plain arithmetic or sqrt).
DISTRIBUTIONS = {"gauss", "normalvariate", "lognormvariate", "expovariate", "vonmisesvariate", "gammavariate",
                 "betavariate", "paretovariate", "weibullvariate", "binomialvariate"}


def libm_uses(source: str) -> list[str]:
    """Every platform-dependent float operation in ``source``: a ``math.<libm>`` call or import, a libm-backed
    ``Random`` method, ``statistics.NormalDist``, or a ``**`` whose base is not an int literal."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in ("math", "cmath") and node.attr in LIBM:
                found.append(f"{node.lineno}: math.{node.attr}")
            if node.value.id == "statistics" and node.attr == "NormalDist":
                found.append(f"{node.lineno}: statistics.NormalDist")
        if isinstance(node, ast.Attribute) and node.attr in DISTRIBUTIONS and not (
                isinstance(node.value, ast.Name) and node.value.id == "detmath"):
            found.append(f"{node.lineno}: .{node.attr}")
        if isinstance(node, ast.ImportFrom) and node.module in ("math", "cmath", "statistics", "random"):
            for alias in node.names:
                if alias.name in LIBM | DISTRIBUTIONS | {"NormalDist"}:
                    found.append(f"{node.lineno}: from {node.module} import {alias.name}")
        pow_ = (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)) or (
            isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Pow))
        if pow_:
            base = node.left if isinstance(node, ast.BinOp) else node.target
            if not (isinstance(base, ast.Constant) and type(base.value) is int):
                found.append(f"{node.lineno}: {ast.unparse(node)}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "pow":
            found.append(f"{node.lineno}: {ast.unparse(node)}")
    return found


def test_no_engine_module_but_detmath_uses_the_platforms_libm():
    offenders = {}
    for path in sorted((ROOT / "engine").rglob("*.py")):
        if path.name == "detmath.py" and path.parent.name == "game":
            continue
        uses = libm_uses(path.read_text(encoding="utf-8"))
        if uses:
            offenders[path.relative_to(ROOT).as_posix()] = uses
    assert not offenders, f"use engine.game.detmath, not the platform's libm (rule 11): {offenders}"


@pytest.mark.parametrize("snippet", [
    "import math\nx = math.exp(1.0)\n",
    "from math import log\n",
    "y = rng.gauss(0, 1)\n",
    "from statistics import NormalDist\n",
    "import statistics\nn = statistics.NormalDist(0, 1)\n",
    "f = 0.97 ** days\n",
    "f = step ** 2\n",
    "f = pow(base, 2)\n",
    "z = random.Random(1).gauss(0, 1)\n",
])
def test_the_scan_catches_each_platform_dependent_form(snippet):
    assert libm_uses(snippet), snippet


@pytest.mark.parametrize("snippet", ["n = 2 ** 31\n", "w = 2 ** attempts\n", "r = math.sqrt(2.0)\n",
                                     "x = math.floor(y)\n", "u = rng.uniform(0, 1)\n",
                                     "z = detmath.gauss(rng, 0, 1)\n"])
def test_the_scan_leaves_exact_operations_alone(snippet):
    assert not libm_uses(snippet), snippet


# -- another platform's libm ----------------------------------------------------------------------------------------


def _one_ulp_up(fn):
    def moved(*args):
        return math.nextafter(fn(*args), math.inf)
    return moved


def _fixed_data(monkeypatch) -> None:
    """The draws' data, so no story need be active."""
    monkeypatch.setattr(growth, "_data", lambda: {"pace": {"jitter": 0.2}})
    monkeypatch.setattr(population, "_filter_spec", lambda: {"age_from_discovery": True})
    monkeypatch.setattr(this_or_that, "spec", lambda: {"lean": {"sharpness": 1.3, "noise": 0.2}})
    monkeypatch.setattr(this_or_that, "_pull", lambda person, tags: 0.37 * len(tags))


def _draws() -> dict[str, list[float]]:
    """Every engine draw built on transcendental math, on fixed seeds."""
    data = {"ages": {"app": {"mean": 31.0, "sd": 6.5}}, "age_bounds": {"min": 18, "max": 80}, "age_spill": 0.1}
    return {
        "lognormal_minutes": [behaviour.lognormal_minutes(random.Random(s), 30.0, 0.8) for s in range(40)],
        "growth_jitter": [growth._jitter(random.Random(s)) for s in range(40)],
        "age": [float(population._age(random.Random(s), data, "app", {})) for s in range(40)],
        "this_or_that": [this_or_that.chance_of_a(None, {"a": {"tags": ["x"] * n}, "b": {"tags": ["y"]}})
                         for n in range(6)],
        "gauss": [detmath.gauss(random.Random(s), 0.5, 0.2) for s in range(40)],
        "normal": [detmath.normal_inv_cdf(detmath.normal_cdf(x / 7.0, 0.3, 1.1), 0.3, 1.1) for x in range(-20, 21)],
        "pow": [detmath.pow(0.97, d / 3.0) for d in range(40)] + [detmath.pow(0.65, n) for n in range(12)],
    }


def test_every_draw_is_the_same_float_under_another_libm(monkeypatch):
    _fixed_data(monkeypatch)
    own = _draws()
    for name in ("exp", "log", "sin", "cos", "erf", "pow"):
        monkeypatch.setattr(math, name, _one_ulp_up(getattr(math, name)))
    for name in ("_log", "_cos", "_sin", "_exp"):
        monkeypatch.setattr(random, name, _one_ulp_up(getattr(random, name)))
    moved = _draws()
    for name in own:
        assert [x.hex() for x in moved[name]] == [x.hex() for x in own[name]], name


def test_gauss_draws_what_random_gauss_draws_and_keeps_its_spare():
    """Same two ``random()`` draws, same spare on ``gauss_next``: the stream after a draw is the stdlib's."""
    a, b = random.Random(11), random.Random(11)
    for _ in range(500):
        x, y = detmath.gauss(a, 0.25, 3.0), b.gauss(0.25, 3.0)
        assert math.isclose(x, y, rel_tol=1e-13, abs_tol=1e-13), (x, y)
    assert a.getstate() == b.getstate()


def test_the_functions_agree_with_the_platform_to_an_ulp():
    rng = random.Random(3)
    for _ in range(2000):
        x = rng.uniform(-30.0, 30.0)
        assert abs(detmath.exp(x) - math.exp(x)) <= math.ulp(math.exp(x))
        y = rng.uniform(1e-12, 1e6)
        assert abs(detmath.log(y) - math.log(y)) <= math.ulp(math.log(y))
        t = rng.uniform(-50.0, 50.0)
        assert abs(detmath.sin(t) - math.sin(t)) <= 2 * math.ulp(1.0)
        assert abs(detmath.cos(t) - math.cos(t)) <= 2 * math.ulp(1.0)
        e = rng.uniform(-7.0, 7.0)
        assert abs(detmath.erf(e) - math.erf(e)) <= 2 * math.ulp(1.0)
        p = rng.uniform(1e-9, 1 - 1e-9)
        assert abs(detmath.normal_inv_cdf(p, 0.0, 1.0) - __import__("statistics").NormalDist().inv_cdf(p)) <= 1e-12
        b, n = rng.uniform(0.01, 3.0), rng.uniform(-8.0, 8.0)
        assert abs(detmath.pow(b, n) - b ** n) <= 2 * math.ulp(b ** n)
    with pytest.raises(ValueError):
        detmath.log(0.0)
    with pytest.raises(OverflowError):
        detmath.exp(1000.0)
    assert detmath.exp(-math.inf) == 0.0 and detmath.pow(2.0, 10) == 1024.0 and detmath.pow(0.5, -2) == 4.0


#: detmath's results, recorded with ``float.hex`` in python:3.11-slim-bookworm (glibc). The same bits on Windows.
PINNED = {
    "exp[0]": "0x1.7455fe323fafdp-11",
    "exp[1]": "0x1.78b56362cef38p-2",
    "exp[2]": "0x1.c48946a8fcf96p-1",
    "exp[3]": "0x1.a61298e1e069cp+0",
    "exp[4]": "0x1.5bf0a8b145769p+1",
    "exp[5]": "0x1.4000000000001p+3",
    "exp[6]": "0x1.0c08ea4cfb973p+14",
    "exp[7]": "0x1.078401f5a3ec8p+48",
    "log[0]": "-0x1.4b927f32bffb8p+4",
    "log[1]": "-0x1.26bb1bbb55515p+1",
    "log[2]": "-0x1.62e42fefa39efp-1",
    "log[3]": "-0x1.0c6f82d74d230p-20",
    "log[4]": "0x1.62e42fefa39efp-1",
    "log[5]": "0x1.26bb1bbb55516p+1",
    "log[6]": "0x1.c7951d51791d7p+2",
    "sin[0]": "0x1.98eaecb8bcb2cp-4",
    "cos[0]": "0x1.fd712f9a817c1p-1",
    "sin[1]": "0x1.aed548f090ceep-1",
    "cos[1]": "0x1.14a280fb5068cp-1",
    "sin[2]": "0x1.326af0dcfcab1p-1",
    "cos[2]": "-0x1.9a2f7ef858b7dp-1",
    "sin[3]": "0x1.6428a6aa44cd0p-19",
    "cos[3]": "-0x1.fffffffff8420p-1",
    "sin[4]": "-0x1.0000000000000p+0",
    "cos[4]": "-0x1.a79394c9e8a0ap-53",
    "sin[5]": "-0x1.65cde2f18c803p-14",
    "cos[5]": "0x1.ffffffe0be81fp-1",
    "erf[0]": "-0x1.ffcaa8f4c9beap-1",
    "erf[1]": "-0x1.50838881dea0fp-2",
    "erf[2]": "0x1.27cc3804d374cp-10",
    "erf[3]": "0x1.5b08c21171646p-1",
    "erf[4]": "0x1.fc4f06f2b1c89p-1",
    "erf[5]": "0x1.ffffffe778b3bp-1",
    "inv_cdf[0]": "-0x1.4b28ae2ccec50p+3",
    "inv_cdf[1]": "0x1.fc1ea0df06189p+3",
    "inv_cdf[2]": "0x1.b9765c5a16fc9p+4",
    "inv_cdf[3]": "0x1.f000000000000p+4",
    "inv_cdf[4]": "0x1.1e6b877d5829cp+5",
    "inv_cdf[5]": "0x1.98b12c2651bcep+5",
    "pow[0]": "0x1.cc39d2dc92430p-1",
    "pow[1]": "0x1.91972b95b0003p-5",
    "pow[2]": "0x1.9b3d438ada293p-2",
    "pow[3]": "0x1.fec982d5bb8afp+0",
    "gauss[0]": "-0x1.06057b7a4b411p-2",
    "gauss[1]": "0x1.05da59e8cdf2bp-1",
    "gauss[2]": "-0x1.cf0b818bf4a85p-3",
    "gauss[3]": "-0x1.42a14be7a8b63p-2",
    "gauss[4]": "-0x1.dc2b58203e26dp-1",
    "gauss[5]": "-0x1.b4d7a6c2c7070p-3",
    "gauss[6]": "0x1.1ca69e1330b24p+0",
    "gauss[7]": "0x1.b25382241c676p-2",
    "lognormal[0]": "0x1.50c950085b321p+3",
    "lognormal[1]": "0x1.25d2438f420ecp-1",
    "lognormal[2]": "0x1.52e48df8a57e0p+1",
    "lognormal[3]": "0x1.d43ad340584eap+1",
    "lognormal[4]": "0x1.908ab2065a283p+2",
    "lognormal[5]": "0x1.c71403dbf812ap+3",
    "lognormal[6]": "0x1.8bd3d25f0aca5p+4",
    "lognormal[7]": "0x1.752367a0ce4fcp+4",
}


def _pinned_now() -> dict[str, str]:
    out = {}
    for i, x in enumerate((-7.25, -1.0, -0.123456789, 0.5, 1.0, 2.302585092994046, 9.75, 33.3)):
        out[f"exp[{i}]"] = detmath.exp(x).hex()
    for i, x in enumerate((1e-9, 0.1, 0.5, 0.999999, 2.0, 10.0, 1234.5678)):
        out[f"log[{i}]"] = detmath.log(x).hex()
    for i, x in enumerate((0.1, 1.0, 2.5, 3.14159, 4.71238898038469, 6.2831)):
        out[f"sin[{i}]"] = detmath.sin(x).hex()
        out[f"cos[{i}]"] = detmath.cos(x).hex()
    for i, x in enumerate((-2.5, -0.3, 0.001, 0.7, 1.9, 4.2)):
        out[f"erf[{i}]"] = detmath.erf(x).hex()
    for i, p in enumerate((1e-10, 0.01, 0.3, 0.5, 0.77, 0.999)):
        out[f"inv_cdf[{i}]"] = detmath.normal_inv_cdf(p, 31.0, 6.5).hex()
    for i, (b, e) in enumerate(((0.97, 3.5), (0.65, 7), (1.5, -2.25), (10.0, 0.3))):
        out[f"pow[{i}]"] = detmath.pow(b, e).hex()
    rng = random.Random(7)
    for i in range(8):
        out[f"gauss[{i}]"] = detmath.gauss(rng, 0.0, 1.0).hex()
    rng = random.Random(170)
    for i in range(8):
        out[f"lognormal[{i}]"] = detmath.lognormal(rng, 6.0, 1.1).hex()
    return out


def test_the_results_are_the_bits_recorded_on_linux():
    assert _pinned_now() == PINNED

"""
Platform-neutral transcendental math (v0.23.2, AGENTS.md rule 11).

``math.exp``, ``math.log``, ``math.cos``, ``math.sin`` and float ``**`` call the
platform's C library, and Windows' (MSVC) and Linux's (glibc) do not always
round the last bit alike. ``random.Random.gauss`` uses three of them. A draw
that lands one ulp apart is a different float in the save: READ RECEIPTS'
day-60 run matched one person at ``170.38475129978946`` hours on Windows and
``170.38475129978943`` on Linux (a lognormal "see the like" delay,
``matching.see_like_hours``), so the same seed and choices gave two saves.

This module computes the same functions in software, through ``decimal``
(libmpdec, the same algorithm on every platform) at ``PREC`` significant
digits, then rounds once to a float: the result is the correctly rounded
value in all but vanishingly rare cases, and is the SAME float on every
platform in every case. ``gauss`` is ``random.Random.gauss``'s own algorithm
(3.11, Kinderman-Monahan's sibling: Box-Muller with the spare kept on
``rng.gauss_next``), the same two ``random()`` draws in the same order, with
its ``log``/``cos``/``sin`` taken from here; ``sqrt`` is IEEE-exact everywhere
and stays ``math.sqrt``.

Every engine path that draws or computes one of these goes through this
module; ``tests/test_detmath.py`` scans ``engine/`` for a direct use.
Each call builds its own ``decimal.Context`` and does every operation through it (never an operator, which
would round in the THREAD's context): nothing here is module or thread state.
"""

from __future__ import annotations

import math
import random
from decimal import Context, Decimal, ROUND_HALF_EVEN

#: Working precision, in significant decimal digits (a double carries ~17).
PREC = 40
#: pi to 80 digits, for reducing a sine's or cosine's argument.
_PI_TEXT = "3.1415926535897932384626433832795028841971693993751058209749445923078164062862090"
#: random.Random.gauss's own constant (``2.0 * pi`` as a float), multiplied in float exactly as it does.
TWOPI = 2.0 * math.pi


def _ctx(prec: int = PREC) -> Context:
    return Context(prec=prec, rounding=ROUND_HALF_EVEN, Emax=999_999, Emin=-999_999, traps=[])


def _special(x: float) -> bool:
    return math.isnan(x) or math.isinf(x)


def exp(x: float) -> float:
    """``e ** x``, the same float on every platform (``math.exp``'s domain; overflow is ``OverflowError``)."""
    x = float(x)
    if math.isnan(x):
        return x
    if math.isinf(x):
        return x if x > 0 else 0.0
    out = float(_ctx().exp(Decimal(x)))
    if math.isinf(out):
        raise OverflowError("math range error")
    return out


def log(x: float) -> float:
    """The natural log, the same float on every platform (``ValueError`` at or below 0, as ``math.log``)."""
    x = float(x)
    if math.isnan(x):
        return x
    if x <= 0.0:
        raise ValueError("math domain error")
    if math.isinf(x):
        return x
    return float(_ctx().ln(Decimal(x)))


def pow(base: float, exponent: float) -> float:  # noqa: A001 - the name is the point
    """``base ** exponent`` for a float result, the same float on every platform.

    A whole exponent is exact repeated multiplication in ``decimal`` (any sign of base); otherwise the base must be
    positive (``exp(exponent * ln base)`` at working precision), as for ``math.pow`` with a real result.
    """
    base, exponent = float(base), float(exponent)
    if _special(base) or _special(exponent):
        return math.pow(base, exponent)               # nan/inf: IEEE-specified, alike everywhere
    if exponent == 0.0:
        return 1.0
    if base == 0.0:
        if exponent < 0.0:
            raise ZeroDivisionError("0.0 cannot be raised to a negative power")
        return 0.0
    ctx = _ctx()
    if exponent.is_integer():
        out = ctx.power(Decimal(base), int(exponent))
    elif base < 0.0:
        raise ValueError("math domain error")
    else:
        out = ctx.exp(ctx.multiply(Decimal(exponent), ctx.ln(Decimal(base))))
    result = float(out)
    if math.isinf(result):
        raise OverflowError("math range error")
    return result


def _sin_cos(x: float) -> tuple[float, float]:
    """``(sin x, cos x)`` by Taylor series after reducing ``x`` into ``[-pi, pi]`` (``decimal``, extra digits)."""
    ctx = _ctx(PREC + 20)
    pi = Decimal(_PI_TEXT)
    two_pi = ctx.multiply(pi, Decimal(2))
    r = Decimal(x)
    k = ctx.to_integral_value(ctx.divide(r, two_pi))
    r = ctx.subtract(r, ctx.multiply(k, two_pi))
    if r > pi:
        r = ctx.subtract(r, two_pi)
    elif r < ctx.minus(pi):
        r = ctx.add(r, two_pi)
    eps = ctx.power(Decimal(10), -(PREC + 10))
    r2 = ctx.multiply(r, r)
    s_term, c_term = r, Decimal(1)
    s_sum, c_sum = r, Decimal(1)
    n = 1
    while ctx.abs(s_term) > eps or ctx.abs(c_term) > eps:
        c_term = ctx.divide(ctx.multiply(ctx.minus(c_term), r2), Decimal((2 * n - 1) * (2 * n)))
        s_term = ctx.divide(ctx.multiply(ctx.minus(s_term), r2), Decimal((2 * n) * (2 * n + 1)))
        c_sum = ctx.add(c_sum, c_term)
        s_sum = ctx.add(s_sum, s_term)
        n += 1
    return float(s_sum), float(c_sum)


def sin(x: float) -> float:
    """The sine, the same float on every platform (finite ``x``)."""
    x = float(x)
    if _special(x):
        return math.sin(x)                            # nan, or ValueError at inf: IEEE-specified, alike everywhere
    return _sin_cos(x)[0]


def cos(x: float) -> float:
    """The cosine, the same float on every platform (finite ``x``)."""
    x = float(x)
    if _special(x):
        return math.cos(x)                            # nan, or ValueError at inf: IEEE-specified, alike everywhere
    return _sin_cos(x)[1]


def gauss(rng: random.Random, mu: float = 0.0, sigma: float = 1.0) -> float:
    """``rng.gauss(mu, sigma)``: the same draws from ``rng``, the same spare kept, the same float on every platform."""
    z = rng.gauss_next
    rng.gauss_next = None
    if z is None:
        draw = rng.random
        x2pi = draw() * TWOPI
        g2rad = math.sqrt(-2.0 * log(1.0 - draw()))
        s, c = _sin_cos(x2pi)
        z = c * g2rad
        rng.gauss_next = s * g2rad
    return mu + z * sigma


def lognormal(rng: random.Random, median: float, spread: float) -> float:
    """``median * e ** (spread * N(0, 1))``: the engine's lognormal, on ``gauss`` and ``exp`` above."""
    return median * exp(spread * gauss(rng, 0.0, 1.0))


def erf(x: float) -> float:
    """The error function, the same float on every platform (Maclaurin series in ``decimal``; ``+-1.0`` past 6)."""
    x = float(x)
    if math.isnan(x):
        return x
    if abs(x) >= 6.0:                                  # 1 - erf(6) is 2e-17: below a double's last bit at 1.0
        return math.copysign(1.0, x)
    # The series' terms grow to about e**(x*x) before they shrink: carry that many more digits.
    ctx = _ctx(PREC + 20 + int(x * x / 2.302585) + 1)
    d = Decimal(x)
    d2 = ctx.multiply(d, d)
    term, total, n = d, d, 0
    eps = ctx.power(Decimal(10), -(PREC + 10))
    while ctx.abs(term) > eps:
        n += 1
        term = ctx.divide(ctx.multiply(ctx.minus(term), d2), Decimal(n))
        total = ctx.add(total, ctx.divide(term, Decimal(2 * n + 1)))
    two_over_root_pi = ctx.divide(Decimal(2), ctx.sqrt(Decimal(_PI_TEXT)))
    return float(ctx.multiply(total, two_over_root_pi))


def normal_cdf(x: float, mu: float, sigma: float) -> float:
    """``statistics.NormalDist(mu, sigma).cdf(x)``'s formula, on ``erf`` above (``sigma`` > 0)."""
    return 0.5 * (1.0 + erf((x - mu) / (sigma * math.sqrt(2.0))))


def normal_inv_cdf(p: float, mu: float, sigma: float) -> float:
    """``statistics.NormalDist(mu, sigma).inv_cdf(p)``: Wichura's AS241, the stdlib's own pure-Python fallback
    (``statistics._normal_dist_inv_cdf``, 3.11), coefficients and order unchanged, its ``log`` taken from here."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in the range 0.0 < p < 1.0")
    q = p - 0.5
    if abs(q) <= 0.425:
        r = 0.180625 - q * q
        num = (((((((2.5090809287301226727e+3 * r +
                     3.3430575583588128105e+4) * r +
                     6.7265770927008700853e+4) * r +
                     4.5921953931549871457e+4) * r +
                     1.3731693765509461125e+4) * r +
                     1.9715909503065514427e+3) * r +
                     1.3314166789178437745e+2) * r +
                     3.3871328727963666080e+0) * q
        den = (((((((5.2264952788528545610e+3 * r +
                     2.8729085735721942674e+4) * r +
                     3.9307895800092710610e+4) * r +
                     2.1213794301586595867e+4) * r +
                     5.3941960214247511077e+3) * r +
                     6.8718700749205790830e+2) * r +
                     4.2313330701600911252e+1) * r +
                     1.0)
        return mu + (num / den) * sigma
    r = p if q <= 0.0 else 1.0 - p
    r = math.sqrt(-log(r))
    if r <= 5.0:
        r = r - 1.6
        num = (((((((7.74545014278341407640e-4 * r +
                     2.27238449892691845833e-2) * r +
                     2.41780725177450611770e-1) * r +
                     1.27045825245236838258e+0) * r +
                     3.64784832476320460504e+0) * r +
                     5.76949722146069140550e+0) * r +
                     4.63033784615654529590e+0) * r +
                     1.42343711074968357734e+0)
        den = (((((((1.05075007164441684324e-9 * r +
                     5.47593808499534494600e-4) * r +
                     1.51986665636164571966e-2) * r +
                     1.48103976427480074590e-1) * r +
                     6.89767334985100004550e-1) * r +
                     1.67638483018380384940e+0) * r +
                     2.05319162663775882187e+0) * r +
                     1.0)
    else:
        r = r - 5.0
        num = (((((((2.01033439929228813265e-7 * r +
                     2.71155556874348757815e-5) * r +
                     1.24266094738807843860e-3) * r +
                     2.65321895265761230930e-2) * r +
                     2.96560571828504891230e-1) * r +
                     1.78482653991729133580e+0) * r +
                     5.46378491116411436990e+0) * r +
                     6.65790464350110377720e+0)
        den = (((((((2.04426310338993978564e-15 * r +
                     1.42151175831644588870e-7) * r +
                     1.84631831751005468180e-5) * r +
                     7.86869131145613259100e-4) * r +
                     1.48753612908506148525e-2) * r +
                     1.36929880922735805310e-1) * r +
                     5.99832206555887937690e-1) * r +
                     1.0)
    x = num / den
    if q < 0.0:
        x = -x
    return mu + x * sigma

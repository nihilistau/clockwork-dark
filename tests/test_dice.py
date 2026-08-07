"""Dice engine tests."""

from __future__ import annotations

import random

from engine.game.dice import roll_dice


def test_roll_dice_bounded():
    rng = random.Random(42)
    for _ in range(50):
        r = roll_dice(sides=20, modifier=2, reason="test", rng=rng)
        assert 3 <= r.total <= 22
        assert len(r.rolls) == 1


def test_nat_20_critical():
    class Fixed:
        def randint(self, a: int, b: int) -> int:
            return 20

    r = roll_dice(sides=20, rng=Fixed())
    assert r.critical is True
    assert r.fumble is False


def test_nat_1_fumble():
    class Fixed:
        def randint(self, a: int, b: int) -> int:
            return 1

    r = roll_dice(sides=20, rng=Fixed())
    assert r.fumble is True
    assert r.critical is False
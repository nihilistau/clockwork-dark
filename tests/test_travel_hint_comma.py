"""
A travel chip's hint is the cost, whatever commas the place's name holds.

``intents._travel`` labels a road ``"<name>, <hours>h"`` and
``default_state._trim_echo`` drops the name half the choice text already
says. It used to split at the FIRST comma, so THE LONG CON's "Vance & Vance,
Investigations" (``locations.yaml``) took "Vance & Vance" for the name and
the chip read "-> Investigations, 1h" where it should read "-> 1h".
"""

from __future__ import annotations

import pytest

from engine.scenes.default_state import _trim_echo


def test_a_comma_in_the_name_is_part_of_the_name() -> None:
    text = "Set out for Vance & Vance, Investigations"
    assert _trim_echo("Vance & Vance, Investigations, 1h", text) == "1h"
    # No cost half: the text says the whole label, so nothing is left.
    assert _trim_echo("Vance & Vance, Investigations", text) == ""


def test_the_old_cases_stand() -> None:
    assert _trim_echo("The Saloon, 0h", "Set out for The Saloon") == "0h"
    assert _trim_echo("Edgewood", "Set out for Edgewood") == ""
    # A name the text does not say survives whole.
    assert _trim_echo("Millhaven Gate, 4h", "Take the long road") == "Millhaven Gate, 4h"
    assert _trim_echo("Lamp oil from Pell, 3 crowns", "Buy something") == "Lamp oil from Pell, 3 crowns"


@pytest.mark.parametrize(
    "slug", ["clockwork-dark", "wicked-garden", "neon-city", "the-long-con", "hue-and-cry", "dev-story"]
)
def test_every_storys_travel_chip_keeps_only_the_cost(slug: str) -> None:
    from engine.game import intents
    from engine.game.locations import LOCATIONS
    from engine.game.procgen import new_game_state
    from engine.games import registry

    registry.activate(slug)
    try:
        checked = 0
        for here in sorted(LOCATIONS):
            state = new_game_state(seed=1, location_id=here)
            verb = intents._travel(state)
            for target, label in verb.options if verb else ():
                name = str((LOCATIONS.get(target) or {}).get("name") or target)
                cost = label[len(name) + 2:] if label != name else ""
                assert label == name or label.startswith(f"{name}, "), label
                assert _trim_echo(label, f"Set out for {name}") == cost, (here, target, label)
                checked += 1
        assert checked, f"{slug}: no travel label was checked"
    finally:
        registry.deactivate()

"""
Livelihood Skills
=================

The tools for staying alive and getting paid: foraging, labour and trade.

WHY THESE ARE TOOLS AND NOT PROSE: everything here moves gold, food or
standing, and CLAUDE.md's first rule is that the engine resolves mechanics
while the model narrates them. A narrator that could say "you find enough
mushrooms for the night" is a narrator that decides whether the player starves.
So every entry point below is a thin wrapper: it binds the active engine,
calls the module that owns the maths, and returns the receipt verbatim.

Each returns JSON with a ``text`` line for narration and the full arithmetic
underneath it, so the UI can render a breakdown and a test can assert the
engine did not quietly add a number it did not show.

Registered by importing this module; ``engine/skills/builtin/__init__.py`` does
that, and importing any sibling imports the package.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import json

from engine.game.engine import get_active_engine
from engine.skills.registry import AGENT_STORYTELLER, skill


# ---------------------------------------------------------------------------
# foraging
# ---------------------------------------------------------------------------


@skill(
    pack="clockwork",
    description=(
        "What foraging HERE would cost and give: the hours, the stamina, the "
        "difficulty, the season, and how picked-over the ground already is. "
        "Read-only -- rolls nothing and spends no time. Call before offering "
        "the player a forage."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def query_forage() -> str:
    """Read-only forage preview for the current location."""
    from engine.game import foraging

    engine = get_active_engine()
    return json.dumps(foraging.snapshot(engine.state))


@skill(
    pack="clockwork",
    description=(
        "Forage: work the ground here for food and materials. Costs hours and "
        "stamina whether or not anything is found, rolls survival against the "
        "node's own difficulty, and yields less each time the same ground is "
        "worked. MUST call before narrating what the player finds."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def forage(node_id: str = "") -> str:
    """
    Spend hours searching for food.

    This is the answer to a broke player. Before it existed the only food in
    the game had a price, and ``scripts/simulate.py`` measured every policy
    dying of starvation dozens of times per run with an empty purse.

    Args:
        node_id: Optional specific forage node. Omit to work the least
            picked-over ground at this location.

    Returns:
        JSON receipt: the check, the itemised season/daypart/phase modifiers,
        every item found, the hours spent and the node's new wear.
    """
    from engine.game import foraging

    engine = get_active_engine()
    return json.dumps(foraging.forage(engine.state, node_id=node_id))


# ---------------------------------------------------------------------------
# labour
# ---------------------------------------------------------------------------


@skill(
    pack="clockwork",
    description=(
        "What paid work is on offer here right now, what each shift pays, and "
        "how many shifts the player has left today. Read-only. A job that is "
        "not hiring in this evil phase, or whose standing gate is unmet, is "
        "absent -- never offer work that is not in this list."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def query_work() -> str:
    """Read-only view of the local labour market."""
    from engine.game import economy

    engine = get_active_engine()
    return json.dumps(economy.snapshot(engine.state))


@skill(
    pack="clockwork",
    description=(
        "Take a shift of paid work. Spends the hours and stamina pass or fail, "
        "rolls the job's skill, and pays coin scaled by the result, the "
        "player's standing with the employer's faction, and how badly the work "
        "is wanted in the current evil phase. MUST call before narrating a "
        "day's work or handing over any wage."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def work(job_id: str) -> str:
    """
    Work a shift for money.

    DESIGN.md makes "become a baker, not a hero" a pillar and there was no way
    to be paid for baking: gold entered the game as a quest reward and left it
    at a vendor's counter.

    Args:
        job_id: Job id from ``query_work``.

    Returns:
        JSON receipt: the check, the wage and its breakdown, in-kind pay,
        reputation moved, and how many shifts remain today.
    """
    from engine.game import economy

    engine = get_active_engine()
    return json.dumps(economy.work(engine.state, job_id))


# ---------------------------------------------------------------------------
# trade
# ---------------------------------------------------------------------------


@skill(
    pack="clockwork",
    description=(
        "Everything a vendor sells with current prices, AND what they would "
        "pay for each thing the player is carrying. Read-only. Use this "
        "rather than guessing a price -- prices move with reputation, the evil "
        "phase and today's haggling."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def trade_browse(npc_id: str) -> str:
    """Vendor stock and standing offers for the player's inventory."""
    from engine.game import trade as trade_module

    engine = get_active_engine()
    return json.dumps(trade_module.browse(engine.state, npc_id))


@skill(
    pack="clockwork",
    description=(
        "The exact price a vendor will do one trade at, with the whole "
        "breakdown: base, spread, reputation, scarcity, haggling. Read-only. "
        "side = buy (player pays) | sell (player receives)."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def trade_quote(npc_id: str, item_id: str, side: str = "buy", qty: int = 1) -> str:
    """One priced quote. This is the vendor's standing counter-offer."""
    from engine.game import trade as trade_module

    engine = get_active_engine()
    return json.dumps(trade_module.quote(engine.state, npc_id, item_id, side, qty))


@skill(
    pack="clockwork",
    description=(
        "Argue about a price. One attempt per vendor per day. The player names "
        "an offer; the engine sets the difficulty from how greedy it is, rolls "
        "persuasion, and moves today's price with this vendor -- the WRONG way "
        "on a failure. Returns the counter-offer. MUST call before narrating "
        "any negotiation."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def trade_haggle(npc_id: str, item_id: str, side: str = "buy", offer: int = 0) -> str:
    """
    Haggle over one item.

    Args:
        npc_id: Vendor npc id.
        item_id: What is being argued over.
        side: ``buy`` or ``sell``.
        offer: Price per unit the player is pushing for. Zero means "try it
            on", scored as a standard-band attempt.

    Returns:
        JSON receipt: the check, the points moved, the new counter price, and
        whether the player's offer was met.
    """
    from engine.game import trade as trade_module

    engine = get_active_engine()
    return json.dumps(
        trade_module.haggle(engine.state, npc_id, item_id, side, int(offer))
    )


@skill(
    pack="clockwork",
    description=(
        "Buy qty of an item from a vendor at the standing quote. Fails "
        "cleanly if the vendor does not stock it or the player cannot afford "
        "it. MUST call before narrating a purchase."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def trade_buy(npc_id: str, item_id: str, qty: int = 1) -> str:
    """Execute a purchase at the engine's price."""
    from engine.game import trade as trade_module

    engine = get_active_engine()
    return json.dumps(trade_module.buy(engine.state, npc_id, item_id, int(qty)))


@skill(
    pack="clockwork",
    description=(
        "Sell qty of a carried item to a vendor at the standing quote. Any "
        "item the vendor deals in has a price, whether or not it appears on "
        "their stock list. MUST call before narrating a sale."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def trade_sell(npc_id: str, item_id: str, qty: int = 1) -> str:
    """
    Execute a sale at the engine's price.

    This is the half of the shop that did not previously exist: the old
    ``trade("sell")`` path refused any item without an explicit ``buys`` row,
    which was almost everything the player could pick up.
    """
    from engine.game import trade as trade_module

    engine = get_active_engine()
    return json.dumps(trade_module.sell(engine.state, npc_id, item_id, int(qty)))


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------


@skill(
    pack="clockwork",
    description=(
        "The player's purse and everything they carry, joined against the item "
        "registry: name, description, tags, unit value, stack value and weight. "
        "Read-only. Use it rather than inventing what an item is or is worth."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def query_inventory() -> str:
    """Carried inventory with registry data attached."""
    from engine.game import inventory as inventory_module

    engine = get_active_engine()
    return json.dumps(inventory_module.snapshot(engine.state))

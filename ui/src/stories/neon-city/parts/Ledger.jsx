/**
 * The runner's readout — this story's right-hand column.
 *
 * WHAT FEEDS IT: `state.meters` alone, the block the server projects from
 * games/neon-city/state.yaml, plus two facts off the raw payload (the pack, the
 * clock) that every graph story has. Nothing here fabricates a value and
 * nothing here is keyed to a name the story does not declare: a meter this file
 * has no opinion about falls through to core's generic renderer rather than
 * being dropped, because a value a story bothered to declare visible must never
 * be invisible.
 *
 * WHAT IS DELIBERATELY ABSENT, and it is the interesting half:
 *
 *   Collections (`debt`). The brief for this column asked for heat, credits,
 *   the timestamp and DEBT. Three of those are here. `debt` is declared
 *   `visibility: hidden` in state.yaml -- "debt is a thing that arrives, not a
 *   gauge you watch" -- so it never leaves the server and there is nothing in
 *   the payload to draw. Drawing it would mean inventing it. The clock is real
 *   and it runs (data/rules/clocks.yaml: reminder, visit, consequence); the
 *   player meets it as a two-person crew standing across from Mira's counter,
 *   which is the design working, not a gap in this file.
 *
 *   The eight per-face standings, for the same reason and by the same rule.
 *
 * TYPOGRAPHY IS A CONTRACT HERE. Every number in this column is mono; money is
 * mono AND gold AND carries `₵`; every label is tracked all-caps. Those are not
 * preferences, they are BIBLE §7.4 and the README's non-negotiables 4 and 7.
 */
import React from "react";

import Meters from "@core/parts/Meters.jsx";
import { FileChip, HeatLadder } from "./Ladder.jsx";

/** Names this column draws itself. Everything else falls through to core. */
const OWN = new Set(["heat", "timestamp", "credits"]);

/**
 * Money, in the one form this story is allowed to write it.
 *
 * `₵` always, the sign and never the word; grouped in threes because a Sprawl
 * price is a figure on a receipt. Rounded to whole chips: prices in this story
 * are integers (economy.yaml), and a stray `.0` in a HUD reads as a rounding
 * error rather than as money.
 */
function Credits({ row }) {
  const chips = Math.round(Number(row?.value ?? 0));
  return (
    <div className="nc-credits">
      <span className="nc-credits__label">{row?.label || "CREDITS"}</span>
      <span className="nc-credits__amount">
        <span className="nc-credits__sign" aria-hidden="true">₵</span>
        {chips.toLocaleString("en-US")}
      </span>
    </div>
  );
}

/**
 * The pack, priced the way this engine prices it.
 *
 * `carry` is a core payload block -- weight against allowance, plus the flag
 * the travel-cost multiplier reads -- and an expedition is exactly the story
 * that needs it visible: the next leg costs half again when this is over, and
 * a number that moves silently is a rule the player cannot play against.
 */
function Pack({ carry }) {
  if (!carry || typeof carry.weight !== "number") return null;
  const over = Boolean(carry.overloaded);
  return (
    <div className="nc-row" data-alert={over ? "on" : "off"}>
      <span className="nc-row__key">LOAD</span>
      <span className="nc-row__val">
        {carry.weight}
        <span className="nc-row__of"> / {carry.limit}</span>
      </span>
      {over && <span className="nc-row__flag">OVER</span>}
    </div>
  );
}

/** Day and hour, as a timestamp. The city runs on the clock, not on daypart. */
function Stamp({ world }) {
  const day = String(world?.world_day ?? 1).padStart(2, "0");
  const hour = String(world?.world_hour ?? 0).padStart(2, "0");
  return (
    <div className="nc-row">
      <span className="nc-row__key">LOCAL</span>
      <span className="nc-row__val">
        D{day}
        <span className="nc-row__of"> · {hour}:00</span>
      </span>
    </div>
  );
}

export default function Ledger({ state }) {
  const meters = state.meters || {};
  const world = state.world || {};
  const rest = Object.fromEntries(
    Object.entries(meters).filter(([name]) => !OWN.has(name))
  );

  return (
    <aside className="ledger nc-ledger" aria-label="Runner">
      <header className="nc-ledger__head">
        <span className="nc-ledger__name">{world.player_name || "RUNNER"}</span>
        {world.archetype && (
          <span className="nc-ledger__kind">{String(world.archetype).replace(/_/g, " ")}</span>
        )}
      </header>

      {meters.credits && <Credits row={meters.credits} />}

      {/* The two veiled readouts. Both take a band word and neither takes a
          number -- see Ladder.jsx for why that is the whole point. */}
      {meters.heat && <HeatLadder band={meters.heat.band} />}
      {meters.timestamp && <FileChip band={meters.timestamp.band} />}

      <div className="nc-ledger__rows">
        <Stamp world={world} />
        <Pack carry={world.carry} />
      </div>

      {/* Condition, energy, focus, hunger, the four attributes: all public,
          all bounded, all drawn by core's generic sheet. Retinted by this
          story's tokens, not reimplemented by it. */}
      <Meters meters={rest} title="Condition" />

      {Object.keys(meters).length === 0 && (
        <p className="ledger__empty">No telemetry. The deck is not reading.</p>
      )}
    </aside>
  );
}

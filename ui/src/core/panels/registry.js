/**
 * The engine panels, in one table (v0.21.0, spec §2.1).
 *
 * MIRRORED IN PYTHON: `engine/games/manifest.py::UI_PANELS` holds the same
 * ids, default regions, allowed regions and gates, in the same order, and
 * `tests/test_ui_panels_manifest.py` reads THIS FILE AS TEXT and fails when
 * the two disagree. Keep each row's first four fields in this order and on
 * the shape `{ id: "...", region: "...", regions: [...], gate: "..." ...`.
 *
 * A new panel joins both tables together (AGENTS.md, "The client").
 *
 * `Component` is what a region renders, with the panel props
 * {state, region, onChoose, showDiceBreakdown, narrow, blocked, onOpenSheet,
 * bindDigits}. Never `onCustom`: typed text carries no intent (rule 1), and
 * `tests/test_ui_contract.py` bans it under `core/panels/`. It renders null
 * when its data is absent. `null` here means "not built yet": resolved,
 * never rendered.
 */
import React from "react";

import CasingBoard from "./CasingBoard.jsx";
import EncounterPanel from "./EncounterPanel.jsx";
import JobPanel from "./JobPanel.jsx";
import NegotiationPanel from "./NegotiationPanel.jsx";
import PeopleStrip from "./PeopleStrip.jsx";
import RollCard from "./RollCard.jsx";
import WantedPoster, { WantedChip } from "./WantedPoster.jsx";

function CasingPanel({ state }) {
  return React.createElement(CasingBoard, {
    premises: state.premises,
    // Between jobs prep is still earned by casing, so the board says it.
    prep: state.world?.job?.prep || "",
  });
}

function NegotiationShelf({ state }) {
  return React.createElement(NegotiationPanel, { negotiation: state.negotiation });
}

export const REGIONS = ["header", "stage", "shelf", "ledger", "toast"];

export const PANELS = [
  { id: "wanted", region: "ledger", regions: ["ledger", "shelf"], gate: "data", Component: WantedPoster, Chip: WantedChip },
  { id: "job", region: "shelf", regions: ["shelf", "ledger"], gate: "data", Component: JobPanel },
  { id: "casing", region: "ledger", regions: ["ledger", "shelf"], gate: "data", Component: CasingPanel },
  { id: "negotiation", region: "shelf", regions: ["shelf"], gate: "data", Component: NegotiationShelf },
  { id: "rolls", region: "toast", regions: ["toast"], gate: "data", Component: RollCard },
  { id: "people", region: "stage", regions: ["stage", "ledger"], gate: "declared", Component: PeopleStrip },
  { id: "encounter", region: "shelf", regions: ["shelf"], gate: "declared", Component: EncounterPanel },
];

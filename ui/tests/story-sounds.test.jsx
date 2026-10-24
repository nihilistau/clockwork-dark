// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { mount } from "./helpers/dom.js";
import { installCatalog, resetSound, setLevels, soundLog, turnSent } from "../src/core/sound/index.js";
import { useTurnSounds } from "../src/core/sound/hooks.js";
import flagship from "../src/stories/clockwork-dark/index.jsx";
import DiceToast from "../src/stories/clockwork-dark/parts/DiceToast.jsx";
import garden from "../src/stories/wicked-garden/index.jsx";
import neon from "../src/stories/neon-city/index.jsx";

const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1 };
const EVENTS = ["clockwork.phase", "garden.omen", "neon.watched", "roll.cast", "roll.success", "encounter.start"];
const CAT = { ...CATALOG, limits: { ...CATALOG.limits, throttle_ms: 0 }, events: EVENTS,
  sounds: { s: { category: "world", label: "s", synth: { layers: [{ wave: "sine", freq: 440, decay_ms: 40 }] } } },
  bind: Object.fromEntries(EVENTS.map((e) => [e, "s"])) };
let view;
beforeEach(() => { installFakeAudio(); resetSound({ logPlays: true }); installCatalog(CAT); gesture(); setLevels(PREFS); view = mount(); });
afterEach(() => { view.unmount(); resetSound(); });
const heard = () => soundLog().filter((r) => !r.dropped).map((r) => r.event);

/** App's shape: settles the turn; the story's component is its child. `turns` advances with each turn payload. */
function Shell({ busy, turns, children }) {
  useTurnSounds({ busy, error: "", phoneUp: false, link: "live", turns });
  return children;
}
/** Load at `first`, then deliver `next` in a sent turn: the app's real sequence. */
function playTurn(render, first, next) {
  view.render(<Shell busy={false} turns={0}>{render(first)}</Shell>);       // the load: silent
  turnSent();
  view.render(<Shell busy={true} turns={0}>{render(first)}</Shell>);
  view.render(<Shell busy={false} turns={1}>{render(next)}</Shell>);        // result and busy:false in one commit
}

describe("the story events", () => {
  it("each plugin declares its own", () => {
    expect(flagship.soundEvents).toEqual(["clockwork.phase"]);
    expect(garden.soundEvents).toEqual(["garden.omen"]);
    expect(neon.soundEvents).toEqual(["neon.watched"]);
  });

  it("the flagship's badge tolls on a phase change in a sent turn, never on a load", () => {
    const Badge = flagship.HeaderBadge;
    const at = (phase) => <Badge state={{ story: { phase, formHistory: [] }, world: { evil_phase: phase } }} />;
    view.render(<Shell busy={false} turns={0}>{at("spreading")}</Shell>);   // a save loaded at "spreading"
    expect(heard()).toEqual([]);
    playTurn(at, "spreading", "consuming");
    expect(heard()).toEqual(["clockwork.phase"]);
  });

  it("NEON CITY's mark scans when watching turns true in a sent turn", () => {
    const Mark = neon.Mark;
    playTurn((w) => <Mark state={{ story: { watching: w } }} />, false, true);
    expect(heard()).toEqual(["neon.watched"]);
  });

  it("the Garden's omen sting sounds once per new omen in a sent turn, never on a load (gap 2)", () => {
    const Toast = garden.Toast;
    const at = (omen) => <Toast state={{ story: { omen } }} />;
    view.render(<Shell busy={false} turns={0}>{at({ id: "favor-utmost" })}</Shell>);   // loaded with an omen showing
    expect(heard()).toEqual([]);
    view.unmount(); view = mount();
    playTurn(at, null, { id: "autonomy-none" });
    expect(heard()).toEqual(["garden.omen"]);
    turnSent();
    view.render(<Shell busy={true} turns={1}>{at({ id: "autonomy-none" })}</Shell>);
    view.render(<Shell busy={false} turns={2}>{at({ id: "autonomy-none" })}</Shell>);   // the same id again
    expect(heard()).toEqual(["garden.omen"]);
  });

  it("the flagship's DiceToast casts and lands its degree inside a sent turn (F10)", () => {
    playTurn((at) => <DiceToast dice={at ? { degree: "success", at, total: 15, dc: 12 } : null} showBreakdown />, null, 7);
    expect(heard()).toEqual(["roll.cast", "roll.success"]);
  });

  it("NEON CITY's Stage starts an encounter with its sound (F10)", () => {
    const Stage = neon.Stage;
    const at = (live) => <Stage state={{ story: { district: "neoncity", watching: false }, choices: [],
      world: { location_id: "x", encounter: live ? { id: "e1", approaches: [], threat: {} } : {} } }} onChoose={() => {}} />;
    playTurn(at, false, true);
    expect(heard()).toContain("encounter.start");
  });

  it("the flagship's Stage starts an encounter with its sound, through the always-mounted slot (F10)", () => {
    const Stage = flagship.Stage;
    const at = (live) => <Stage state={{ story: { phase: "dormant", formHistory: [] }, choices: [],
      world: { location_id: "x", encounter: live ? { id: "e1", approaches: [], threat: { name: "Wolf" } } : {} } }} onChoose={() => {}} />;
    playTurn(at, false, true);
    expect(heard()).toEqual(["encounter.start"]);
  });
});

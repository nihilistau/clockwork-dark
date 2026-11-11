// @vitest-environment jsdom
/** The flagship's encounter (v0.25.0 §8.2): digits bind only when the choice row is empty, never to an unlit plate. */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { key, mount } from "./helpers/dom.js";
import EncounterPanel from "../src/stories/clockwork-dark/parts/EncounterPanel.jsx";
import Play from "../src/core/screens/Play.jsx";
import { initialState } from "../src/core/store.js";
import flagship from "../src/stories/clockwork-dark/index.jsx";

const ENCOUNTER = {
  id: "the_toll_men", round: 0, resolved: false,
  intro: "Two men and a chain across the road.",
  threat: { name: "The toll men", resolve: 3, resolve_max: 3 },
  approaches: [
    { id: "pay", text: "Pay the toll", skill: "persuasion", difficulty: "easy", auto: false, cost_gold: 2 },
    { id: "talk", text: "Talk past them", skill: "persuasion", difficulty: "standard", auto: false, cost_gold: 0 },
    { id: "around", text: "Go round", skill: "stealth", difficulty: "standard", auto: false, cost_gold: 0 },
  ],
};
const offered = (ids) => new Map(ids.map((id) => [id, { id: `c-${id}`, intent: { action: "encounter", target: id } }]));

let view;
beforeEach(() => {
  view = mount();
  globalThis.fetch = vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }));
});
afterEach(() => view.unmount());

const render = (props) => view.render(
  <EncounterPanel encounter={ENCOUNTER} world={{}} phase="stirring" sceneImage="" busy={false} {...props} />);

describe("the encounter's keys and look", () => {
  it("binds 1-9 to the pressable approaches in order when the choice row is empty", () => {
    const onTake = vi.fn();
    render({ offered: offered(["pay", "around"]), onTake, choiceRowEmpty: true });
    key("2");
    expect(onTake).toHaveBeenCalledWith(ENCOUNTER.approaches[2]);
    expect(view.host.querySelectorAll(".approach__key").length).toBe(2);
  });
  it("binds nothing while other choices are on screen", () => {
    const onTake = vi.fn();
    render({ offered: offered(["pay", "around"]), onTake, choiceRowEmpty: false });
    key("1");
    expect(onTake).not.toHaveBeenCalled();
  });
  it("draws an unoffered approach unlit, unnumbered and not pressable", () => {
    const onTake = vi.fn();
    render({ offered: offered(["pay"]), onTake, choiceRowEmpty: true });
    const unlit = view.host.querySelectorAll(".approach.is-unlit");
    expect(unlit.length).toBe(2);
    unlit.forEach((plate) => {
      expect(plate.getAttribute("aria-disabled")).toBe("true");
      expect(plate.querySelector(".approach__key")).toBeNull();
      expect(plate.textContent).toContain("not offered this turn");
    });
  });
  it("binds nothing while a turn runs", () => {
    const onTake = vi.fn();
    render({ offered: offered(["pay"]), onTake, choiceRowEmpty: true, busy: true });
    key("1");
    expect(onTake).not.toHaveBeenCalled();
  });
});

// v0.25.0 T12 fix round 1: the flagship's Stage slot, as core's play screen draws it.
const PAY = { id: "c-pay", text: "Pay them", intent: { action: "encounter", target: "pay" } };
const AROUND = { id: "c-around", text: "Slip round", intent: { action: "encounter", target: "around" } };
const LOOK = { id: "c-look", text: "Look about" };
const playState = (choices) => ({
  ...initialState, screen: "scene", sessionId: "s1", link: "live",
  world: { location_id: "edgewood_square", encounter: ENCOUNTER }, choices, story: { phase: "stirring" },
  log: [{ id: "e1", kind: "narration", text: "A chain across the road." }],
});
const Stage = flagship.Stage;

describe("the flagship's Stage slot", () => {
  it("binds no digit while a choice the approaches do not press is on screen", () => {
    const onChoose = vi.fn();
    view.render(<Stage state={playState([PAY, LOOK])} onChoose={onChoose} controlsOff={false} blocked={false} />);
    expect(view.host.querySelectorAll(".approach__key").length).toBe(0);
    key("1");
    expect(onChoose).not.toHaveBeenCalled();
  });
  it("presses the approach's choice by digit when every choice is an approach", () => {
    const onChoose = vi.fn();
    view.render(<Stage state={playState([PAY, AROUND])} onChoose={onChoose} controlsOff={false} blocked={false} />);
    key("2");
    expect(onChoose).toHaveBeenCalledWith(AROUND);
  });
  it("binds no digit with no choices at all (core's rule)", () => {
    const onChoose = vi.fn();
    view.render(<Stage state={playState([])} onChoose={onChoose} controlsOff={false} blocked={false} />);
    expect(view.host.querySelectorAll(".approach__key").length).toBe(0);
  });
});

describe("the approach digits with a dialog up (spec §8.2: off while blocked)", () => {
  const noop = () => {};
  const play = (blocked, onChoose) => view.render(
    <Play state={playState([PAY, AROUND])} story={flagship} blocked={blocked}
      onChoose={onChoose} onCustom={noop} onRetry={noop} onOpenSaves={noop} onOpenSettings={noop}
      onOpenOverlay={noop} onOpenMenu={noop} onToggleReasoning={noop} composeRef={{ current: null }} />);
  it("a digit pressed while an overlay is open commits nothing", () => {
    const onChoose = vi.fn();
    play(true, onChoose);
    key("1");
    expect(onChoose).not.toHaveBeenCalled();
  });
  it("the same digit with nothing open presses the approach", () => {
    const onChoose = vi.fn();
    play(false, onChoose);
    key("1");
    expect(onChoose).toHaveBeenCalledWith(PAY);
  });
});

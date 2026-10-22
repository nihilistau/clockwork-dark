// @vitest-environment jsdom
// ui/tests/rr-scene-plate.test.jsx -- READ RECEIPTS' world layer shows the place's plate after every frame (v0.23.0 fix).
//
// The world layer draws core's ScenePlate from `state.sceneImage`. A resume, a phone action's answer, a world turn
// (a room move) and a plan's arrival each carry `scene_image`; core reduces it, and the layer shows that plate.
import React from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { initialState, reducer } from "../src/core/store.js";
import World from "../src/stories/read-receipts/world/World.jsx";
import { phoneFixture } from "./fixtures/phone.js";
import { mount } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => { view.unmount(); });

const LOUNGE = "/story-art/scenes/apt-lounge-dusk.jpg";
const ANCHOR = "/story-art/scenes/the-anchor-night.jpg";
const HALL = "/story-art/scenes/apt-hall-night.jpg";

const socket = (event, payload = {}) => ({ type: "SOCKET", event, payload });
const phone = () => phoneFixture({ phone: { world: { phone_up: false, location: "", buzz: { count: 0, who: [] } } } });
const at = (location_id) => ({ location_id, location_name: location_id, world_day: 1, meters: {}, phone: phone() });

function plateOf(state) {
  view.render(<World state={{ ...state, link: "live" }} phoneUp={false} onChoose={() => {}} />);
  const img = view.host.querySelector("img.sceneplate__img");
  return img ? img.getAttribute("src") : null;
}

describe("the world layer's scene plate", () => {
  it("shows the place's plate after a resume, a phone action, a room move and an arrival", () => {
    let state = reducer(initialState, socket("game_resumed", {
      session_id: "s1", save_id: "v1", state: at("apt_lounge"),
      opening: { narration: "", choices: [], resumed: true, scene_image: LOUNGE },
    }));
    expect(plateOf(state)).toBe(LOUNGE);

    // A phone action (the Places app's `go`): no narration, the new venue's plate.
    state = reducer(state, socket("turn_update", { narration: "", choices: [], state: at("the_anchor"), scene_image: ANCHOR }));
    expect(plateOf(state)).toBe(ANCHOR);

    // A world turn that moves between rooms of the flat.
    state = reducer(state, socket("turn_update", { narration: "You go through to the hall.", choices: [], state: at("apt_hall"), scene_image: HALL }));
    expect(plateOf(state)).toBe(HALL);

    // T23C's second update for an arrival: the arrival line alone, the same room's plate.
    state = reducer(state, socket("turn_update", { narration: "Cole arrives.", choices: [], state: at("apt_hall"), scene_image: HALL, streamed: false }));
    expect(plateOf(state)).toBe(HALL);
  });

  it("keeps the plate it has when a turn carries none, as every other story's turn does", () => {
    let state = reducer(initialState, socket("game_started", {
      session_id: "s1", state: at("apt_lounge"), opening: { narration: "", choices: [], scene_image: LOUNGE },
    }));
    state = reducer(state, socket("turn_update", { narration: "Rain.", choices: [], state: at("apt_lounge") }));
    expect(state.sceneImage).toBe(LOUNGE);
    state = reducer(state, socket("image_ready", { url: HALL }));
    expect(plateOf(state)).toBe(HALL);
  });
});

// @vitest-environment jsdom
// ui/tests/rr-playtest.test.jsx -- the owner's playtest on the client (v0.23.0 addendum 4 §7, T23H).
//
// Symptom (d): "the options didn't appear at all until I refreshed". The reducer is core's real one, fed the
// socket events a phone action and a "Wait for" produce; the screen is READ RECEIPTS' real PlayScreen.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PlayScreen from "../src/stories/read-receipts/PlayScreen.jsx";
import plugin from "../src/stories/read-receipts/index.jsx";
import { createStore } from "../src/core/store.js";
import { phoneFixture } from "./fixtures/phone.js";
import { button, byTestId, click, mount, typeInto } from "./helpers/dom.js";

// The COMPOSED reducer (core's with the plugin's `reduce`), so the frames pass through the phone's slice (T14 b6).
const { initial: initialState, reducer } = createStore(plugin);

let view;
beforeEach(() => { view = mount(); });
afterEach(() => { view.unmount(); vi.restoreAllMocks(); delete window.matchMedia; });

const socket = (event, payload = {}) => ({ type: "SOCKET", event, payload });
const WORLD = (over = {}) => ({ phone_up: true, at_work: false, location: "The Anchor", buzz: { count: 0, who: [] }, ...over });
const down = () => phoneFixture({ phone: { world: WORLD({ phone_up: false }) } });

const screen = (state, props = {}) => (
  <PlayScreen state={{ ...state, link: "live" }} sessionId="s1" onAct={() => true}
              onChoose={() => {}} onCustom={() => {}} onOpenMenu={() => {}} onOpenSaves={() => {}} {...props} />
);

const started = () => reducer(initialState, socket("game_started", {
  session_id: "s1", save_id: "v1", state: { phone: phoneFixture({ phone: { world: WORLD() } }) },
  opening: { narration: "Your phone is in your hand.", choices: [] },
}));

describe("the playtest, on the client", () => {
  it("shows the world's choices after a phone action, with no refresh", () => {
    // put_down answers with a turn_update: the choices ride it, so the row is there at once.
    let state = reducer(started(), socket("turn_update", {
      narration: "", streamed: false, state: { phone: down() },
      choices: [{ id: "w1", text: "Wait for Kai" }, { id: "w2", text: "Look around the bar" }],
    }));
    view.render(screen(state));
    expect(state.choices).toHaveLength(2);
    const wait = button(view.host, /Wait for Kai/);
    expect(wait).not.toBeNull();
    expect(wait.disabled).toBe(false);
    expect(button(view.host, /Look around the bar/)).not.toBeNull();
  });

  it("shows the arrival line and the scene's choices in the same frame", () => {
    let state = reducer(started(), socket("turn_update", {
      narration: "", streamed: false, state: { phone: down() }, choices: [{ id: "w1", text: "Wait for Kai" }],
    }));
    // The wait's own turn: the arrival line and the scene's moves arrive together.
    state = reducer(state, socket("turn_update", {
      narration: "Kai arrives.", streamed: false, state: { phone: down() },
      choices: [{ id: "s1", text: "Ask about music" }, { id: "s2", text: "Call it a night" }],
    }));
    view.render(screen(state));
    expect(state.log.filter((e) => e.kind === "narration").map((e) => e.text)).toContain("Kai arrives.");
    expect(view.host.textContent).toContain("Kai arrives.");
    expect(button(view.host, /Ask about music/)).not.toBeNull();
    expect(button(view.host, /Call it a night/)).not.toBeNull();
    expect(button(view.host, /Wait for Kai/)).toBeNull();                 // the stale row is gone
  });

  it("sends a typed line from the compose box once the phone is down", () => {
    const onCustom = vi.fn();
    const state = reducer(started(), socket("turn_update", {
      narration: "", streamed: false, state: { phone: down() }, choices: [{ id: "w1", text: "Look around" }],
    }));
    view.render(screen(state, { onCustom }));
    const form = byTestId(view.host, "rr-compose");
    expect(form).not.toBeNull();
    const input = form.querySelector("input");
    expect(input.readOnly).toBe(false);
    typeInto(input, "you have a nice laugh");
    click(button(form, "Send"));
    expect(onCustom).toHaveBeenCalledWith("you have a nice laugh");
  });

  it("keeps the compose box shut while the phone is up", () => {
    view.render(screen(started()));
    const input = byTestId(view.host, "rr-compose").querySelector("input");
    expect(input.readOnly).toBe(true);
  });
});

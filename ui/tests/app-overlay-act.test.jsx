// @vitest-environment jsdom
/**
 * App's overlay press (v0.25.0 T14, review c1): an overlay's `{action, target}` act is emitted as
 * `overlay_action` with the session and the intent, marks the turn busy, and is never sent while the link is
 * not live or a turn runs; a string act is still the player's typed words (`player_choice`, `custom_text`).
 * The server tests emit the event themselves, so without this nothing held the client's half.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let appSocket = null;
vi.mock("socket.io-client", () => ({ io: () => appSocket }));
vi.mock("../src/core/parts/MicButton.jsx", () => ({ default: () => null }));

import App from "../src/core/App.jsx";
import { click, mount } from "./helpers/dom.js";

function fakeSocket() {
  const handlers = {};
  const socket = {
    connected: false,
    active: true,
    emitted: [],
    on(name, fn) { (handlers[name] ||= []).push(fn); return socket; },
    onAny() { return socket; },
    emit(name, payload) { socket.emitted.push([name, payload]); },
    connect() {},
    disconnect() {},
    close() { socket.connected = false; },
    io: { _reconnecting: false, on() {}, off() {} },
    fire(name, ...args) { for (const fn of handlers[name] || []) fn(...args); },
  };
  return socket;
}

let seenBusy = [];
function Pack({ onAct, busy }) {
  seenBusy.push(busy);
  return (
    <div role="dialog" aria-label="Pack">
      <button type="button" data-act="eat" onClick={() => onAct({ action: "eat", target: "loaf", label: "Eat: Loaf" })}>
        Eat
      </button>
      <button type="button" data-act="words" onClick={() => onAct("I look in the pack")}>
        Words
      </button>
    </div>
  );
}

function story() {
  return {
    slug: "ovl",
    title: "Ovl",
    overlays: [{ id: "pack", key: "p", label: "Pack", Component: Pack }],
    onboarding: [],
    initialState: {},
    reduce: (s) => s,
  };
}

let dom;
beforeEach(() => {
  window.localStorage.clear();
  globalThis.fetch = vi.fn(() => Promise.reject(new Error("no server in this test")));
  appSocket = fakeSocket();
  seenBusy = [];
  dom = mount();
});
afterEach(() => dom.unmount());

const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
const startRun = () => {
  appSocket.connected = true;
  fire("connect");
  fire("game_started", {
    session_id: "s1",
    save_id: "v1",
    state: { world: { location_id: "here" } },
    opening: { narration: "Here.", choices: [{ id: "a", text: "Go on" }] },
  });
};
const openPack = () => React.act(() => {
  window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "p", bubbles: true, cancelable: true }));
});
const press = (act) => click(dom.host.querySelector(`[data-act=${act}]`));
const sent = (name) => appSocket.emitted.filter(([event]) => event === name);

describe("App's overlay press", () => {
  it("emits overlay_action with the session and the intent, and marks the turn busy", () => {
    dom.render(<App story={story()} />);
    startRun();
    openPack();
    expect(dom.host.querySelector("[data-act=eat]")).not.toBeNull();
    expect(seenBusy.at(-1)).toBe(false);
    press("eat");
    expect(sent("overlay_action")).toEqual([
      ["overlay_action", { session_id: "s1", intent: { action: "eat", target: "loaf" }, label: "Eat: Loaf" }],
    ]);
    expect(sent("player_choice")).toEqual([]);
    expect(seenBusy.at(-1)).toBe(true);
    // Busy: a second press sends nothing.
    press("eat");
    expect(sent("overlay_action")).toHaveLength(1);
  });

  it("sends a string act as the player's typed words", () => {
    dom.render(<App story={story()} />);
    startRun();
    openPack();
    press("words");
    expect(sent("overlay_action")).toEqual([]);
    const choices = sent("player_choice");
    expect(choices).toHaveLength(1);
    expect(choices[0][1]).toMatchObject({ session_id: "s1", custom_text: "I look in the pack" });
  });

  it("sends nothing while the link is not live", () => {
    dom.render(<App story={story()} />);
    startRun();
    openPack();
    appSocket.connected = false;
    fire("disconnect", "transport close");
    press("eat");
    expect(sent("overlay_action")).toEqual([]);
  });
});

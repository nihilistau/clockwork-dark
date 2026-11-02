// @vitest-environment jsdom
/**
 * One Escape, one effect (v0.25.0 T12, found by the layout check's overlay probe).
 *
 * A dialog's focus trap answers Escape on the document (capture) and calls preventDefault. In a real browser
 * React flushes that close in a microtask BEFORE the event reaches window, so App's own keydown listener was
 * re-bound with `blocked` false and saw the same Escape: it opened the pause menu on the press that closed an
 * overlay, and re-opened the menu on the press that closed it. jsdom dispatches synchronously, so the race
 * itself cannot be staged here; what is held is App's guard: a key a dialog already handled
 * (`defaultPrevented`) is never a shortcut.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let appSocket = null;
vi.mock("socket.io-client", () => ({ io: () => appSocket }));
vi.mock("../src/core/parts/MicButton.jsx", () => ({ default: () => null }));

import App from "../src/core/App.jsx";
import { mount } from "./helpers/dom.js";

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

function story() {
  const PlayScreen = () => <div data-testid="play">play</div>;
  return { slug: "esc", title: "Esc", overlays: [], onboarding: [], initialState: {}, reduce: (s) => s, PlayScreen };
}

let dom;
beforeEach(() => {
  window.localStorage.clear();
  globalThis.fetch = vi.fn(() => Promise.reject(new Error("no server in this test")));
  appSocket = fakeSocket();
  dom = mount();
});
afterEach(() => dom.unmount());

const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
const startRun = () => {
  appSocket.connected = true;
  fire("connect");
  fire("game_started", { session_id: "s1", save_id: "v1", state: {}, opening: { choices: [] } });
};
const escape = (handled) => React.act(() => {
  const event = new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
  if (handled) event.preventDefault();
  window.dispatchEvent(event);
});
const paused = () => [...dom.host.querySelectorAll("[role=dialog]")].some((d) => d.getAttribute("aria-label") === "Paused");

describe("App's Escape", () => {
  it("opens the pause menu from the play screen", () => {
    dom.render(<App story={story()} />);
    startRun();
    expect(dom.host.querySelector("[data-testid=play]")).not.toBeNull();
    escape(false);
    expect(paused()).toBe(true);
  });

  it("does nothing for an Escape a dialog already handled", () => {
    dom.render(<App story={story()} />);
    startRun();
    escape(true);
    expect(paused()).toBe(false);
  });
});

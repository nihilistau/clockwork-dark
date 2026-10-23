// @vitest-environment jsdom
/**
 * The REAL App's sound wiring (v0.24.0 T6 fix round 1), with a fake socket as phone-seams.test.jsx drives it:
 * `turnSent` in send/begin, one turn.arrive per answered turn, game.begin once, cutscene.start, a resume frame
 * silent, phone_up cleared on the next submit, and a slider drag not restarting the narration.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let appSocket = null;
vi.mock("socket.io-client", () => ({ io: () => appSocket }));
vi.mock("../src/core/parts/MicButton.jsx", () => ({ default: () => null }));

import App from "../src/core/App.jsx";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { button, click, mount, typeInto } from "./helpers/dom.js";
import { installCatalog, resetSound, setLevels, soundLog } from "../src/core/sound/index.js";
import { resetTurns } from "../src/core/sound/turns.js";

const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1 };
const CAT = {
  ...CATALOG,
  limits: { ...CATALOG.limits, throttle_ms: 0 },
  events: [...CATALOG.events, "ui.open", "ui.close", "game.begin", "cutscene.start", "game.ending", "link.lost", "link.back"],
  bind: {
    ...CATALOG.bind, "ui.open": null, "ui.close": null, "game.begin": "game.turn", "cutscene.start": "game.turn",
    "game.ending": "game.turn", "link.lost": "alert.error", "link.back": "alert.error",
  },
};

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

/** A story whose play screen is two buttons; the cutscene, the menu and the audio are App's own. */
function story() {
  function PlayScreen({ onChoose, onOpenMenu, state }) {
    return (
      <div data-testid="play">
        <button type="button" data-sound="none" onClick={() => onChoose({ id: "c1", text: "Go" })}>Go</button>
        <button type="button" data-sound="none" onClick={onOpenMenu}>Menu</button>
        <p data-testid="busy">{String(state.busy)}</p>
      </div>
    );
  }
  return { slug: "snd", title: "Snd", overlays: [], onboarding: [], initialState: {}, reduce: (s) => s, PlayScreen };
}

let dom;
beforeEach(() => {
  window.localStorage.clear();
  installFakeAudio();
  resetSound({ logPlays: true });
  resetTurns();
  installCatalog(CAT);
  gesture();
  setLevels(PREFS);
  // Everything but the begin POST fails, which leaves the installed catalogue alone.
  globalThis.fetch = vi.fn((url) => {
    if (url === "/api/game/new") {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ save_id: "v1", session_id: "s1" }) });
    }
    return Promise.reject(new Error("no server in this test"));
  });
  appSocket = fakeSocket();
  dom = mount();
});
afterEach(() => {
  dom.unmount();
  resetSound();
  resetTurns();
});

const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
const plays = (event) => soundLog().filter((r) => r.event === event && !r.dropped).length;
const startRun = () => {
  appSocket.connected = true;
  fire("connect");
  fire("game_started", { session_id: "s1", save_id: "v1", state: {}, opening: { choices: [] } });
};
const choose = () => click(button(dom.host, "Go"));

describe("App's sound wiring", () => {
  it("a resume frame with no sent turn is silent", () => {
    dom.render(<App story={story()} />);
    startRun();
    fire("turn_update", { narration: "back again", choices: [] });
    fire("cutscene_start", { id: "k1", captions: [] });
    fire("turn_error", { message: "x" });
    for (const event of ["turn.arrive", "cutscene.start", "alert.error", "game.begin"]) {
      expect(plays(event)).toBe(0);
    }
  });

  it("a sent turn plays turn.arrive once, and a later push plays nothing", () => {
    dom.render(<App story={story()} />);
    startRun();
    choose();
    expect(appSocket.emitted.some(([name]) => name === "player_choice")).toBe(true);
    fire("turn_update", { narration: "ok", choices: [] });
    expect(plays("turn.arrive")).toBe(1);
    fire("turn_update", { narration: "a push", choices: [] });
    expect(plays("turn.arrive")).toBe(1);
  });

  it("cutscene.start sounds once when the cutscene opens inside a sent turn", () => {
    dom.render(<App story={story()} />);
    startRun();
    choose();
    fire("cutscene_start", { id: "k1", captions: [] });
    fire("turn_update", { narration: "ok", choices: [] });
    expect(plays("cutscene.start")).toBe(1);
  });

  it("a phone_up refusal is silent and does not silence the next, non-socket error", () => {
    vi.useFakeTimers();
    try {
      dom.render(<App story={story()} />);
      startRun();
      choose();
      fire("turn_error", { message: "phone is up", phone_up: true });
      expect(plays("alert.error")).toBe(0);
      choose(); // a new submit forgets the refusal; the watchdog then ends it with an ERROR of its own
      React.act(() => { vi.advanceTimersByTime(340000); });
      expect(plays("alert.error")).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("game.begin sounds once when a new run opens, and its settle plays no turn.arrive", async () => {
    dom.render(<App story={story()} />);
    typeInto(dom.host.querySelector(".field__input"), "Ada");
    await React.act(async () => { button(dom.host, "Begin").click(); });
    expect(plays("game.begin")).toBe(1);
    fire("game_started", { session_id: "s1", save_id: "v1", state: {}, opening: { choices: [] } });
    fire("turn_update", { narration: "opening", choices: [] });
    expect(plays("game.begin")).toBe(1);
    expect(plays("turn.arrive")).toBe(0);
  });

  it("dragging the master slider does not restart the narration", () => {
    const play = vi.fn(() => Promise.resolve());
    const proto = window.HTMLMediaElement.prototype;
    const was = proto.play;
    proto.play = play;
    try {
      dom.render(<App story={story()} />);
      startRun();
      choose();
      fire("turn_update", { narration: "ok", choices: [] });
      fire("narration_audio", { url: "/media/a.wav" });
      const first = play.mock.calls.length;
      expect(first).toBeGreaterThan(0);
      click(button(dom.host, "Menu"));
      const master = dom.host.querySelector('input[type="range"]');
      expect(master).not.toBeNull();
      typeInto(master, "0.3");
      typeInto(master, "0.5");
      expect(play.mock.calls.length).toBe(first);
    } finally {
      proto.play = was;
    }
  });
});

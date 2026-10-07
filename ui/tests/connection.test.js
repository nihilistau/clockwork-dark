// @vitest-environment jsdom
/**
 * The connection's state machine (v0.21.0, spec §6.3), one case per
 * transition, named by its number. A fake socket stands in for
 * socket.io-client 4.8.3's behaviour (§6.1): `connected` and `active` are
 * set by hand, a server refusal is an Error with no `type`, a transport
 * failure has `type: "TransportError"`. Every case asserts the state it
 * reaches and the emits it made -- and that no OTHER emit happened -- and
 * whether the controls are live there, through the reducer (spec §6.8).
 *
 * jsdom, for the last block only: the banner's countdown and the controls
 * are asserted on what React renders, not on the machine's dispatches,
 * because the countdown lives in the component (C13) and the `send` guard
 * lives in App (F5). Transitions 29-32 (hosted `session_ended`, Begin/Load)
 * close the "transitions" block.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// App's socket is the test's fake (below); MicButton reaches for media APIs.
let appSocket = null;
vi.mock("socket.io-client", () => ({ io: () => appSocket }));
vi.mock("../src/core/parts/MicButton.jsx", () => ({ default: () => null }));

import App from "../src/core/App.jsx";
import ConnectionBanner from "../src/core/parts/ConnectionBanner.jsx";
import Play from "../src/core/screens/Play.jsx";
import {
  AWAIT_POLL_MS, BACKOFF_MS, BOUNCE_KEY, JOIN_WAITS_MS, LINK, PROBE_URL, SIGNOUT_DELAY_MS, banner, createLink,
} from "../src/core/link.js";
import { controlsLive, initialState, reducer } from "../src/core/store.js";

function fakeSocket() {
  const handlers = {};
  const manager = {};
  const socket = {
    connected: false,
    active: true,
    emitted: [],
    connects: 0,
    calls: [],
    on(name, fn) { (handlers[name] ||= []).push(fn); return socket; },
    onAny() { return socket; },
    emit(name, payload) { socket.emitted.push([name, payload]); },
    connect() { socket.connects += 1; socket.calls.push("connect"); },
    disconnect() { socket.calls.push("disconnect"); socket.connected = false; socket.fire("disconnect", "io client disconnect"); },
    close() { socket.connected = false; },
    io: {
      _reconnecting: false,
      on(name, fn) { (manager[name] ||= []).push(fn); },
      off(name, fn) { manager[name] = (manager[name] || []).filter((f) => f !== fn); },
    },
    managerListeners: (name) => (manager[name] || []).length,
    fire(name, ...args) { for (const fn of handlers[name] || []) fn(...args); },
    fireManager(name, ...args) { for (const fn of manager[name] || []) fn(...args); },
  };
  return socket;
}

function setup({ session = "", save = "", busy = false } = {}) {
  const socket = fakeSocket();
  const actions = [];
  const stored = new Map();
  const h = {
    socket, actions, stored, fetches: [], assigned: [],
    probe: { status: 200, body: {} },
    refs: {
      session: { current: session }, save: () => h.save, link: { current: "connecting" },
      busy: { current: busy }, busyAtDrop: { current: false }, outgoing: { current: new Set() },
    },
    save,
  };
  const env = {
    fetch: async (url) => {
      h.fetches.push(url);
      if (h.probe === "network") throw new TypeError("Failed to fetch");
      return { status: h.probe.status, json: async () => h.probe.body };
    },
    assign: (url) => h.assigned.push(url),
    storage: { getItem: (k) => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, String(v)), removeItem: (k) => stored.delete(k) },
    random: () => 0.5,
  };
  h.ctl = createLink({ socket, dispatch: (a) => actions.push(a), refs: h.refs, env });
  h.state = () => h.ctl.state;
  h.links = () => actions.filter((a) => a.type === "LINK");
  h.banner = () => h.links().at(-1)?.banner ?? null;
  h.drain = () => socket.emitted.splice(0);
  // The controls, as the store sees them: every LINK the machine dispatched,
  // reduced from a fresh page (spec §6.8, C20).
  h.controls = () => controlsLive(h.links().reduce(reducer, initialState));
  return h;
}

/** Let the probe's awaits settle (microtasks; timers are fake). */
const settle = async () => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); };

const connect = (h) => { h.socket.connected = true; h.socket.fire("connect"); };
const drop = (h, reason = "transport close") => { h.socket.connected = false; h.socket.fire("disconnect", reason); };
const transportError = () => Object.assign(new Error("websocket error"), { type: "TransportError" });
const refusal = (message) => new Error(message);

function toLive(h) { connect(h); expect(h.state()).toBe("live"); h.drain(); }
function toRetrying(h) { toLive(h); drop(h); expect(h.state()).toBe("retrying"); }
function toRejoining(h) { toRetrying(h); connect(h); expect(h.state()).toBe("rejoining"); h.drain(); }
function toAwaiting(h) {
  toRejoining(h);
  h.socket.fire("game_started", { session_id: h.refs.session.current, turn_running: true });
  expect(h.state()).toBe("awaiting");
}
function toResuming(h) { connect(h); expect(h.state()).toBe("resuming"); h.drain(); }

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("transitions", () => {
  it("1: connecting + connect with no stored save goes live, emitting nothing", () => {
    const h = setup();
    connect(h);
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(true);
  });

  it("2: connecting + connect with a stored save resumes it", () => {
    const h = setup({ save: "v1" });
    connect(h);
    expect(h.state()).toBe("resuming");
    expect(h.drain()).toEqual([["resume", { save_id: "v1" }]]);
    expect(h.controls()).toBe(false);
  });

  it("3: a disconnect the page made itself changes nothing", () => {
    const h = setup();
    toLive(h);
    drop(h, "io client disconnect");
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(true);
  });

  it("4: live + a server or transport drop goes retrying and remembers whether a turn was running", () => {
    const h = setup({ busy: true });
    toLive(h);
    drop(h);
    expect(h.state()).toBe("retrying");
    expect(h.refs.busyAtDrop.current).toBe(true);
    expect(h.controls()).toBe(false);
    vi.advanceTimersByTime(60000);
    expect(h.socket.connects).toBe(0); // Socket.IO retries by itself (`active`)
    expect(h.drain()).toEqual([]);
  });

  it("4: a drop Socket.IO will not retry ('io server disconnect') schedules the client's own connect", () => {
    const h = setup();
    toLive(h);
    h.socket.active = false;
    drop(h, "io server disconnect");
    expect(h.state()).toBe("retrying");
    expect(h.banner().retryAt).toBeGreaterThan(Date.now());
    vi.advanceTimersByTime(BACKOFF_MS[0] * 1.2 + 1);
    expect(h.socket.connects).toBe(1);
    expect(h.drain()).toEqual([]);
  });

  it("5: retrying + a Manager retry below five stays retrying", () => {
    const h = setup();
    toRetrying(h);
    h.socket.fireManager("reconnect_attempt", 3);
    expect(h.state()).toBe("retrying");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(false);
  });

  it("6: retrying + the fifth Manager retry is offline", () => {
    const h = setup();
    toRetrying(h);
    h.socket.fireManager("reconnect_attempt", 5);
    expect(h.state()).toBe("offline");
    expect(h.banner().text).toBe("The server is not answering.");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(false);
  });

  it("7: retrying + a transport error probes, at most once per ten seconds", async () => {
    const h = setup();
    toRetrying(h);
    h.socket.fire("connect_error", transportError());
    h.socket.fire("connect_error", transportError());
    await settle();
    expect(h.fetches).toEqual([PROBE_URL]);
    expect(h.state()).toBe("retrying");
    expect(h.drain()).toEqual([]);
  });

  it("8: retrying + a server refusal shows its words and schedules the client's own connect", async () => {
    const h = setup();
    toRetrying(h);
    h.socket.active = false;
    h.socket.fire("connect_error", refusal("Too many windows are open on this account."));
    await settle();
    expect(h.banner().detail).toBe("Too many windows are open on this account.");
    vi.advanceTimersByTime(BACKOFF_MS[0] * 1.2 + 1);
    expect(h.socket.connects).toBe(1);
    expect(h.state()).toBe("retrying");
    expect(h.drain()).toEqual([]);
  });

  it.each([
    [401, {}],
    [403, { error: "password change required" }],
    [409, {}],
  ])("9: a probe answering %i signs out once and goes to /", async (status, body) => {
    const h = setup();
    toRetrying(h);
    h.probe = { status, body };
    h.socket.fire("connect_error", transportError());
    await settle();
    expect(h.state()).toBe("signed_out");
    expect(h.banner().role).toBe("alert");
    expect(h.controls()).toBe(false);
    expect(h.assigned).toEqual([]);
    vi.advanceTimersByTime(SIGNOUT_DELAY_MS);
    expect(h.assigned).toEqual(["/"]);
    expect(JSON.parse(h.stored.get(BOUNCE_KEY))).toHaveLength(1);
    expect(h.drain()).toEqual([]);
  });

  it("10: with two bounces in the last minute it stops instead of looping", async () => {
    const h = setup();
    toRetrying(h); // (reaching live clears the list, so the bounces come after it)
    h.stored.set(BOUNCE_KEY, JSON.stringify([Date.now() - 5000, Date.now() - 1000]));
    h.probe = { status: 401, body: {} };
    h.socket.fire("connect_error", transportError());
    await settle();
    expect(h.state()).toBe("auth_stuck");
    expect(h.controls()).toBe(false);
    vi.advanceTimersByTime(120000);
    expect(h.assigned).toEqual([]);
    expect(h.socket.connected).toBe(false);
    expect(h.socket.connects).toBe(0);
    expect(h.drain()).toEqual([]);
  });

  it("11: a 503 shows the front door's own words", async () => {
    const h = setup();
    toRetrying(h);
    h.probe = { status: 503, body: { error: "story unavailable" } };
    h.socket.fire("connect_error", transportError());
    await settle();
    expect(h.state()).toBe("retrying");
    expect(h.banner().detail).toBe("story unavailable");
    expect(h.drain()).toEqual([]);
  });

  it.each([[{ status: 200, body: {} }], ["network"]])("12: a probe that answers %j changes nothing", async (probe) => {
    const h = setup();
    toRetrying(h);
    h.probe = probe;
    h.socket.fire("connect_error", transportError());
    await settle();
    expect(h.state()).toBe("retrying");
    expect(h.assigned).toEqual([]);
    expect(h.drain()).toEqual([]);
  });

  it("13: retrying + connect with a live session rejoins it and starts the join timer", () => {
    const h = setup({ session: "s1" });
    toRetrying(h);
    h.save = "v1"; // a stored save too: the live session is joined, never resumed over (B3)
    connect(h);
    expect(h.state()).toBe("rejoining");
    expect(h.controls()).toBe(false);
    expect(h.drain()).toEqual([["join_session", { session_id: "s1" }]]);
    vi.advanceTimersByTime(JOIN_WAITS_MS[0]);
    expect(h.drain()).toEqual([["join_session", { session_id: "s1" }]]);
  });

  it("14: retrying + connect with no session, a stored save and no run left this page resumes", () => {
    const h = setup();
    toRetrying(h);
    h.save = "v1";
    connect(h);
    expect(h.state()).toBe("resuming");
    expect(h.drain()).toEqual([["resume", { save_id: "v1" }]]);
    expect(h.controls()).toBe(false);
  });

  it("14: a run this page has left is never resumed into (outgoingRef)", () => {
    const h = setup();
    toRetrying(h);
    h.save = "v1";
    h.refs.outgoing.current.add("s0");
    connect(h);
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
  });

  it("15: retrying + connect with nothing to pick up goes live, saying so once", () => {
    const h = setup();
    toRetrying(h);
    connect(h);
    expect(h.state()).toBe("live");
    expect(h.banner().kind).toBe("reconnected");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(true);
  });

  it("16: rejoining + its own game_started with no turn running goes live, checking for an unanswered move", () => {
    const h = setup({ session: "s1", busy: true });
    h.stored.set(BOUNCE_KEY, JSON.stringify([Date.now()]));
    toRejoining(h);
    h.socket.fire("game_started", { session_id: "s1", turn_running: false });
    expect(h.state()).toBe("live");
    expect(h.actions.at(-1)).toMatchObject({ type: "LINK", link: "live", checkUnanswered: true });
    expect(h.stored.has(BOUNCE_KEY)).toBe(false);
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(true);
  });

  it("16: another session's game_started is not this rejoin's answer", () => {
    const h = setup({ session: "s1" });
    toRejoining(h);
    h.socket.fire("game_started", { session_id: "s2", turn_running: false });
    expect(h.state()).toBe("rejoining");
    expect(h.drain()).toEqual([]);
  });

  it("16/17: a late answer while live and idle that says a turn runs re-joins (R1)", () => {
    const h = setup({ session: "s1" });
    toRejoining(h);
    h.socket.fire("game_started", { session_id: "s1", turn_running: false });
    expect(h.state()).toBe("live");
    h.drain();
    h.socket.fire("game_started", { session_id: "s1", turn_running: true });
    expect(h.state()).toBe("rejoining");
    expect(h.drain()).toEqual([["join_session", { session_id: "s1" }]]);
    expect(h.controls()).toBe(false);
  });

  it("16/17: a late answer while this page's own move is in flight is ignored", () => {
    const h = setup({ session: "s1" });
    toRejoining(h);
    h.socket.fire("game_started", { session_id: "s1", turn_running: false });
    h.refs.busy.current = true; // the player pressed a move
    h.socket.fire("game_started", { session_id: "s1", turn_running: true });
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
  });

  it("17: rejoining + game_started with a turn running waits (busy kept)", () => {
    const h = setup({ session: "s1" });
    toAwaiting(h);
    expect(h.drain()).toEqual([]);
    const awaiting = h.links().at(-1);
    expect(awaiting).toMatchObject({ type: "LINK", link: "awaiting" });
    // The store, in the order the page dispatches: socket.js's SOCKET first
    // (registered before the link), then the link's LINK.
    const rejoining = { ...reducer(initialState, { type: "SOCKET", event: "game_started", payload: { session_id: "s1", opening: {} } }), link: "rejoining" };
    let state = reducer(rejoining, { type: "SOCKET", event: "game_started", payload: { session_id: "s1", turn_running: true, opening: {} } });
    state = reducer(state, awaiting);
    expect(state.link).toBe("awaiting");
    expect(state.busy).toBe(true);
    expect(controlsLive(state)).toBe(false);
    // The poll that ends it (24) is still armed: it is not shortened (§6.3).
    vi.advanceTimersByTime(AWAIT_POLL_MS - 1);
    expect(h.state()).toBe("awaiting");
    expect(h.drain()).toEqual([]);
  });

  // (A stored save is set only once rejoining: with one at the FIRST connect,
  // transition 2 would resume instead of going live.)

  it("18: rejoining + the join's exact miss resumes the stored save", () => {
    const h = setup({ session: "s1" });
    toRejoining(h);
    h.save = "v1";
    h.socket.fire("error", { message: "session not found" });
    expect(h.state()).toBe("resuming");
    expect(h.drain()).toEqual([["resume", { save_id: "v1" }]]);
    expect(h.controls()).toBe(false);
    vi.advanceTimersByTime(JOIN_WAITS_MS[2] * 4);
    expect(h.drain()).toEqual([]); // the join timer is gone
  });

  it("19: a dead login's 'login required' probes at once, inside the ten-second window too", async () => {
    const h = setup();
    toLive(h);
    h.socket.fire("error", { error: "login required" });
    h.socket.fire("error", { error: "login required" });
    await settle();
    expect(h.fetches).toEqual([PROBE_URL, PROBE_URL]);
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
  });

  it("20: rejoining + any other error is ignored", () => {
    const h = setup({ session: "s1" });
    toRejoining(h);
    h.save = "v1";
    h.socket.fire("error", { message: "something else" });
    expect(h.state()).toBe("rejoining");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(false);
  });

  it("21: the join timer re-joins, backing off 8, 16, 30, 30 s, and never resumes", () => {
    const h = setup({ session: "s1" });
    toRejoining(h);
    h.save = "v1";
    for (const wait of [JOIN_WAITS_MS[0], JOIN_WAITS_MS[1], JOIN_WAITS_MS[2], JOIN_WAITS_MS[2]]) {
      vi.advanceTimersByTime(wait - 1);
      expect(h.drain()).toEqual([]);
      vi.advanceTimersByTime(1);
      expect(h.drain()).toEqual([["join_session", { session_id: "s1" }]]);
    }
    expect(h.state()).toBe("rejoining");
  });

  it("22: awaiting + the turn's update goes live", () => {
    const h = setup({ session: "s1" });
    toAwaiting(h);
    h.socket.fire("turn_update", {});
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(true);
    vi.advanceTimersByTime(AWAIT_POLL_MS * 2);
    expect(h.drain()).toEqual([]); // the poll is cleared
  });

  it("23: awaiting + the turn's error goes live", () => {
    const h = setup({ session: "s1" });
    toAwaiting(h);
    h.socket.fire("turn_error", { message: "the model went away" });
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(true);
  });

  it("24: awaiting + the poll re-joins", () => {
    const h = setup({ session: "s1" });
    toAwaiting(h);
    vi.advanceTimersByTime(AWAIT_POLL_MS);
    expect(h.state()).toBe("rejoining");
    expect(h.drain()).toEqual([["join_session", { session_id: "s1" }]]);
    expect(h.controls()).toBe(false);
  });

  it("25: resuming + game_resumed goes live", () => {
    const h = setup({ save: "v1" });
    toResuming(h);
    h.socket.fire("game_resumed", { session_id: "s2" });
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(true);
  });

  it("25: a recovery's resume (after the join's miss) checks for an unanswered move", () => {
    const h = setup({ session: "s1", busy: true });
    toRejoining(h);
    h.save = "v1";
    h.socket.fire("error", { message: "session not found" });
    h.drain();
    h.socket.fire("game_resumed", { session_id: "s2" });
    expect(h.state()).toBe("live");
    expect(h.actions.at(-1)).toMatchObject({ type: "LINK", link: "live", checkUnanswered: true });
    expect(h.refs.busyAtDrop.current).toBe(false);
    expect(h.drain()).toEqual([]);
  });

  it("25: a first-load resume asks nothing", () => {
    const h = setup({ save: "v1", busy: true });
    toResuming(h);
    h.socket.fire("game_resumed", { session_id: "s2" });
    expect(h.actions.at(-1).checkUnanswered).toBeUndefined();
  });

  it("26: resuming + resume_failed goes live (the start screen shows the message)", () => {
    const h = setup({ save: "v1" });
    toResuming(h);
    h.socket.fire("resume_failed", { message: "That save is gone." });
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(true);
    const shown = reducer({ ...initialState, screen: "scene" }, { type: "SOCKET", event: "resume_failed", payload: { message: "That save is gone." } });
    expect(shown.screen).toBe("start");
    expect(shown.error).toBe("That save is gone.");
  });

  it("27: resuming + turn_error (a rate limit) keeps the message and offers Resume", () => {
    const h = setup({ save: "v1" });
    toResuming(h);
    h.socket.fire("turn_error", { message: "Slow down." });
    expect(h.state()).toBe("resume_refused");
    expect(h.banner()).toMatchObject({ text: "Slow down.", action: "resume" });
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(false);
  });

  it("28: Resume from resume_refused resumes, only while connected", () => {
    const h = setup({ save: "v1" });
    toResuming(h);
    h.socket.fire("turn_error", { message: "Slow down." });
    h.socket.connected = false;
    h.ctl.resume();
    expect(h.drain()).toEqual([]);
    h.socket.connected = true;
    h.ctl.resume();
    expect(h.state()).toBe("resuming");
    expect(h.drain()).toEqual([["resume", { save_id: "v1" }]]);
  });

  it("33: Try now connects at once", () => {
    const h = setup();
    toRetrying(h);
    h.ctl.tryNow();
    expect(h.socket.connects).toBe(1);
    expect(h.state()).toBe("retrying");
    expect(h.drain()).toEqual([]);
  });

  it("33: Try now while the Manager is mid-backoff closes it, then opens at once", () => {
    const h = setup();
    toRetrying(h);
    h.socket.io._reconnecting = true; // socket.io-client 4.8's connect() would skip io.open()
    h.ctl.tryNow();
    expect(h.socket.calls).toEqual(["disconnect", "connect"]);
    expect(h.state()).toBe("retrying"); // the page's own disconnect is transition 3
    expect(h.drain()).toEqual([]);
  });

  it("34: Sign in again is a plain navigation", async () => {
    const h = setup();
    toRetrying(h);
    h.stored.set(BOUNCE_KEY, JSON.stringify([Date.now(), Date.now()]));
    h.probe = { status: 401, body: {} };
    h.socket.fire("connect_error", transportError());
    await settle();
    expect(h.state()).toBe("auth_stuck");
    h.ctl.signIn();
    expect(h.assigned).toEqual(["/"]);
    expect(h.drain()).toEqual([]);
  });

  it("35: a fatal turn_error while live offers Resume", () => {
    const h = setup();
    toLive(h);
    h.socket.fire("turn_error", { message: "session not found", fatal: true });
    expect(h.state()).toBe("live");
    expect(h.banner()).toMatchObject({ kind: "lost", action: "resume" });
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(true);
  });

  it("36: a first connect that fails on the transport shows the banner and probes at once", async () => {
    const h = setup();
    h.socket.fire("connect_error", transportError());
    await settle();
    expect(h.state()).toBe("retrying");
    expect(h.banner().text).toBe("Connection lost.");
    expect(h.fetches).toEqual([PROBE_URL]);
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(false);
  });

  it("37: a first connect the server refuses says so in its words and retries on the client's backoff", async () => {
    const h = setup();
    h.socket.active = false;
    h.socket.fire("connect_error", refusal("Too many windows are open on this account."));
    await settle();
    expect(h.state()).toBe("refused");
    expect(h.banner().text).toBe("Too many windows are open on this account.");
    expect(h.fetches).toEqual([PROBE_URL]);
    vi.advanceTimersByTime(BACKOFF_MS[0] * 1.2 + 1);
    expect(h.socket.connects).toBe(1);
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(false);
  });

  it("38: refused + a dead login goes to sign in", async () => {
    const h = setup();
    h.socket.active = false;
    h.probe = { status: 401, body: {} };
    h.socket.fire("connect_error", refusal("Too many windows"));
    await settle();
    expect(h.state()).toBe("signed_out");
    vi.advanceTimersByTime(SIGNOUT_DELAY_MS);
    expect(h.assigned).toEqual(["/"]);
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(false);
  });

  it("38: refused + a dead login with the bounce guard tripped stops", async () => {
    const h = setup();
    h.stored.set(BOUNCE_KEY, JSON.stringify([Date.now(), Date.now()]));
    h.socket.active = false;
    h.probe = { status: 401, body: {} };
    h.socket.fire("connect_error", refusal("Too many windows"));
    await settle();
    expect(h.state()).toBe("auth_stuck");
    vi.advanceTimersByTime(120000);
    expect(h.assigned).toEqual([]);
    expect(h.drain()).toEqual([]);
  });

  it("39: refused + a good login keeps the banner and never navigates", async () => {
    const h = setup();
    h.socket.active = false;
    h.socket.fire("connect_error", refusal("Too many windows"));
    await settle();
    vi.advanceTimersByTime(SIGNOUT_DELAY_MS * 10);
    expect(h.state()).toBe("refused");
    expect(h.banner().text).toBe("Too many windows");
    expect(h.assigned).toEqual([]);
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(false);
  });

  it("39: refused + a transport error keeps the server's words (the server is down, not refusing)", async () => {
    const h = setup();
    h.socket.active = false;
    h.socket.fire("connect_error", refusal("Too many windows"));
    await settle();
    h.socket.fire("connect_error", transportError());
    expect(h.state()).toBe("refused");
    expect(h.banner().text).toBe("Too many windows");
    expect(h.drain()).toEqual([]);
  });

  it("36 + P 429: behind the front door the cap's words come through the probe, with no run to rejoin", async () => {
    const h = setup();
    h.probe = { status: 429, body: { error: "You already have 4 game connections open." } };
    h.socket.fire("connect_error", transportError()); // the 429 upgrade, unreadable
    await settle();
    expect(h.state()).toBe("refused");
    expect(h.banner().text).toBe("You already have 4 game connections open.");
    expect(h.banner().retryAt).toBeNull(); // Socket.IO's own retry runs (active)
    vi.advanceTimersByTime(SIGNOUT_DELAY_MS * 10);
    expect(h.assigned).toEqual([]);
    expect(h.drain()).toEqual([]);
    expect(h.controls()).toBe(false);
    connect(h); // a window was closed
    expect(h.state()).toBe("live");
  });

  it("P 429 with a run on screen stays retrying (it must rejoin) and says why", async () => {
    const h = setup({ session: "s1" });
    toRetrying(h);
    h.probe = { status: 429, body: { error: "You already have 4 game connections open." } };
    h.socket.fire("connect_error", transportError());
    await settle();
    expect(h.state()).toBe("retrying");
    expect(h.banner().detail).toBe("You already have 4 game connections open.");
    connect(h);
    expect(h.drain()).toEqual([["join_session", { session_id: "s1" }]]);
  });

  it("40: refused + a connect resumes, or goes live and clears the bounce list", () => {
    const withSave = setup({ save: "v1" });
    withSave.socket.active = false;
    withSave.socket.fire("connect_error", refusal("Too many windows"));
    connect(withSave);
    expect(withSave.state()).toBe("resuming");
    expect(withSave.drain()).toEqual([["resume", { save_id: "v1" }]]);
    expect(withSave.controls()).toBe(false);
    const bare = setup();
    bare.stored.set(BOUNCE_KEY, JSON.stringify([Date.now()]));
    bare.socket.active = false;
    bare.socket.fire("connect_error", refusal("Too many windows"));
    connect(bare);
    expect(bare.state()).toBe("live");
    expect(bare.stored.has(BOUNCE_KEY)).toBe(false);
    expect(bare.drain()).toEqual([]);
    expect(bare.controls()).toBe(true);
  });

  it("29: session_ended for this tab's run: elsewhere, the session forgotten, no automatic resume", () => {
    const h = setup({ session: "s1" });
    toLive(h);
    h.save = "v1";
    h.socket.fire("session_ended", { session_id: "s1", reason: "elsewhere" });
    expect(h.state()).toBe("elsewhere");
    expect(h.refs.session.current).toBe("");
    expect(h.banner()).toMatchObject({ kind: "elsewhere", action: "play" });
    drop(h);
    connect(h);
    expect(h.drain()).toEqual([]);
  });

  it.each(["ended", "idle"])("29: session_ended (%s) is ended, offering Resume", (reason) => {
    const h = setup({ session: "s1" });
    toLive(h);
    h.socket.fire("session_ended", { session_id: "s1", reason });
    expect(h.state()).toBe("ended");
    expect(h.banner()).toMatchObject({ kind: "ended", action: "resume" });
  });

  it("30: session_ended for another run is ignored", () => {
    const h = setup({ session: "s2" });
    toLive(h);
    h.socket.fire("session_ended", { session_id: "s1", reason: "elsewhere" });
    expect(h.state()).toBe("live");
    expect(h.refs.session.current).toBe("s2");
  });

  it("31: Begin/Load first drops the outgoing run, so a reconnect never resumes into it", () => {
    const h = setup({ session: "s1" });
    toLive(h);
    h.ctl.leaving();
    expect(h.refs.session.current).toBe("");
    expect([...h.refs.outgoing.current]).toEqual(["s1"]);
    h.save = "v-old";
    drop(h);
    connect(h);
    expect(h.state()).toBe("live");
    expect(h.drain()).toEqual([]);
  });

  it("32: this tab's own new run goes live on its game_started, whatever the state", () => {
    const h = setup({ session: "s1" });
    toLive(h);
    h.socket.fire("session_ended", { session_id: "s1", reason: "elsewhere" });
    h.ctl.join("s2");
    expect(h.drain()).toEqual([["join_session", { session_id: "s2" }]]);
    h.socket.fire("game_started", { session_id: "s2", turn_running: false });
    expect(h.state()).toBe("live");
    expect(h.refs.session.current).toBe("s2");
  });

  it.each([["elsewhere", "elsewhere"], ["ended", "ended"], ["idle", "ended"]])(
    "28 after 29 (%s): Play here / Resume resumes this tab's save, re-adopts the same id, and a later release counts again",
    (reason, state) => {
      const h = setup({ session: "s1" });
      toLive(h);
      h.save = "vA";
      h.socket.fire("session_ended", { session_id: "s1", reason });
      expect(h.state()).toBe(state);
      h.ctl.resume();
      expect(h.drain()).toEqual([["resume", { save_id: "vA" }]]);
      expect(h.state()).toBe("resuming");
      // A resume of the same save rebuilds the SAME id: React's effect would
      // not re-send it, so the machine adopts it.
      h.socket.fire("game_resumed", { session_id: "s1", save_id: "vA" });
      expect(h.state()).toBe("live");
      expect(h.refs.session.current).toBe("s1");
      h.socket.fire("session_ended", { session_id: "s1", reason: "elsewhere" });
      expect(h.state()).toBe("elsewhere");
    }
  );

  it("28 after 29 with the socket down: the press connects, checks the login, and resumes on the connect", async () => {
    const h = setup({ session: "s1" });
    toLive(h);
    h.save = "vA";
    h.socket.fire("session_ended", { session_id: "s1", reason: "idle" });
    drop(h);
    h.ctl.resume();
    expect(h.socket.connects).toBe(1);
    await settle();
    expect(h.fetches).toEqual([PROBE_URL]);
    expect(h.drain()).toEqual([]);
    connect(h);
    expect(h.drain()).toEqual([["resume", { save_id: "vA" }]]);
    expect(h.state()).toBe("resuming");
  });

  it("31 undone: a refused Begin/Load keeps the run -- its release counts and a reconnect rejoins it", () => {
    const h = setup({ session: "s1" });
    toLive(h);
    const left = h.ctl.leaving();
    expect(left).toBe("s1");
    h.ctl.stay(left);
    expect(h.refs.session.current).toBe("s1");
    expect([...h.refs.outgoing.current]).toEqual([]);
    drop(h);
    connect(h);
    expect(h.drain()).toEqual([["join_session", { session_id: "s1" }]]); // 13
    h.socket.fire("game_started", { session_id: "s1", turn_running: false });
    h.socket.fire("session_ended", { session_id: "s1", reason: "elsewhere" });
    expect(h.state()).toBe("elsewhere");
  });

  it("31 undone after a reconnect that came while the Begin/Load was out: stay rejoins", () => {
    const h = setup({ session: "s1" });
    toLive(h);
    const left = h.ctl.leaving();
    drop(h);
    connect(h); // no run to rejoin: goes live without joining
    expect(h.drain()).toEqual([]);
    h.ctl.stay(left);
    expect(h.drain()).toEqual([["join_session", { session_id: "s1" }]]);
    expect(h.state()).toBe("rejoining");
  });

  it("32 with the socket down: the reconnect joins the new run, and its answer goes live", () => {
    const h = setup({ session: "s1" });
    toLive(h);
    h.ctl.leaving();
    drop(h);
    h.ctl.join("s2");
    expect(h.drain()).toEqual([]); // not buffered (B3)
    h.save = "v2";
    connect(h);
    expect(h.drain()).toEqual([["join_session", { session_id: "s2" }]]);
    h.socket.fire("game_started", { session_id: "s2", turn_running: false });
    expect(h.state()).toBe("live");
    expect(h.refs.session.current).toBe("s2");
  });

  it("32 with the socket down and the new run gone meanwhile: the miss resumes its save (18)", () => {
    const h = setup({ session: "s1" });
    toLive(h);
    h.ctl.leaving();
    drop(h);
    h.ctl.join("s2");
    h.save = "v2";
    connect(h);
    h.drain();
    h.socket.fire("error", { message: "session not found" });
    expect(h.drain()).toEqual([["resume", { save_id: "v2" }]]);
  });

  it("31 while rejoining: Begin stops the old run's rejoin, so its miss never resumes the old save", () => {
    const h = setup({ session: "s1", save: "v-old" });
    h.save = "";
    toRejoining(h);
    h.save = "v-old";
    h.ctl.leaving();
    expect(h.state()).toBe("live");
    vi.advanceTimersByTime(JOIN_WAITS_MS[0] * 4);
    expect(h.drain()).toEqual([]); // no re-join with an empty id
    h.socket.fire("error", { message: "session not found" }); // the old join's late miss
    expect(h.drain()).toEqual([]);
    expect(h.state()).toBe("live");
  });
});

describe("the machine's guards", () => {
  it("never emits while the socket is down (no buffered emit, B3)", () => {
    const h = setup({ session: "s1" });
    toRejoining(h);
    h.socket.connected = false;
    vi.advanceTimersByTime(JOIN_WAITS_MS[0]);
    expect(h.drain()).toEqual([]);
  });

  it("reads refs, not a closure: a session changed after mount is the one rejoined", () => {
    const h = setup({ session: "s1" });
    toRetrying(h);
    h.refs.session.current = "s9";
    connect(h);
    expect(h.drain()).toEqual([["join_session", { session_id: "s9" }]]);
  });

  it("the banner's words carry no number: the countdown rides retryAt", () => {
    const h = setup();
    toLive(h);
    h.socket.active = false;
    drop(h, "io server disconnect");
    const first = h.banner().text;
    expect(first).not.toMatch(/\d/);
    expect(h.banner().retryAt).toBeGreaterThan(Date.now());
  });

  it("controls are live only when the link is live and no turn is running (F5)", () => {
    expect(controlsLive({ ...initialState, link: "live", busy: false })).toBe(true);
    expect(controlsLive({ ...initialState, link: "live", busy: true })).toBe(false);
    for (const link of Object.values(LINK).filter((name) => name !== "live")) {
      expect(controlsLive({ ...initialState, link, busy: false }), link).toBe(false);
    }
  });

  it("dispose leaves no listener on the shared Manager", () => {
    const h = setup();
    expect(h.socket.managerListeners("reconnect_attempt")).toBe(1);
    h.ctl.dispose();
    expect(h.socket.managerListeners("reconnect_attempt")).toBe(0);
  });

  it("socket.io-client is still 4.8, the behaviour this machine encodes (Risk 7)", () => {
    // ...including the private flag Try now reads (review 3).
    const source = readFileSync(resolve(process.cwd(), "node_modules/socket.io-client/build/esm/socket.js"), "utf8");
    expect(source).toMatch(/if \(!this\.io\["_reconnecting"\]\)\s*this\.io\.open\(\)/);
    const pkg = JSON.parse(readFileSync(resolve(process.cwd(), "node_modules/socket.io-client/package.json"), "utf8"));
    expect(pkg.version.split(".").slice(0, 2).join(".")).toBe("4.8");
  });
});

describe("what React renders", () => {
  let host;
  let root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    React.act(() => root.unmount());
    host.remove();
    appSocket = null;
  });

  it("the banner's live text does not change between countdown ticks (Review 22, C13)", () => {
    React.act(() => root.render(React.createElement(ConnectionBanner, { banner: banner("retrying", { retryAt: Date.now() + 5000 }) })));
    const strip = host.querySelector('[role="status"]');
    const text = () => strip.querySelector(".linkbanner__text").textContent;
    const count = () => strip.querySelector(".linkbanner__count");
    const before = { text: text(), count: count().textContent };
    expect(count().getAttribute("aria-hidden")).toBe("true");
    React.act(() => vi.advanceTimersByTime(2000));
    expect(text()).toBe(before.text);
    expect(text()).not.toMatch(/\d/);
    expect(count().textContent).not.toBe(before.count);
  });

  it("the play screen's controls are off while the link is not live", () => {
    const state = {
      ...initialState, screen: "scene", sessionId: "s1",
      world: { location_id: "here", world_day: 1, time_of_day: "day" },
      log: [{ id: "e1", kind: "narration", text: "Quiet." }],
      choices: [{ id: "a", text: "Wait" }],
    };
    const noop = () => {};
    const draw = (link) => React.act(() => root.render(React.createElement(Play, {
      state: { ...state, link, connected: link === "live" },
      story: { slug: "probe", title: "Probe", overlays: [], onboarding: [] },
      onChoose: noop, onCustom: noop, onRetry: noop, onOpenSaves: noop, onOpenSettings: noop,
      onOpenOverlay: noop, onOpenMenu: noop, onToggleReasoning: noop, onToggleMute: noop,
    })));
    const chip = () => [...host.querySelectorAll(".choices button")].find((b) => b.textContent.includes("Wait"));
    // Off is `aria-disabled` (and the compose box `readOnly`), never
    // `disabled`, since v0.21.0 T13: a disabled control drops focus (§8.2).
    const off = (el) => el.getAttribute("aria-disabled") === "true";
    const box = () => host.querySelector(".compose__input");
    draw("live");
    expect(off(chip())).toBe(false);
    expect(off(box())).toBe(false);
    expect(box().readOnly).toBe(false);
    for (const link of ["retrying", "rejoining", "awaiting", "refused"]) {
      draw(link);
      expect(off(chip()), link).toBe(true);
      expect(off(box()), link).toBe(true);
      expect(box().readOnly, link).toBe(true);
      expect(chip().disabled, link).toBe(false);
      expect(box().disabled, link).toBe(false);
    }
  });

  it("send emits nothing while the link is not live, even from a plugin's own button (F5)", async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("no server in this test")));
    try {
      window.localStorage.clear();
    } catch {
      /* ignore */
    }
    appSocket = fakeSocket();
    // A plugin button that ignores `busy` (preflight 3.22): only `send`'s
    // own guard stands between it and the socket.
    const Aside = ({ state, onChoose }) =>
      React.createElement("button", { type: "button", id: "plugin-move", onClick: () => onChoose(state.choices[0]) }, "Plugin move");
    const story = { slug: "probe", title: "Probe", overlays: [], onboarding: [], Aside };
    React.act(() => root.render(React.createElement(App, { story })));
    const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
    appSocket.connected = true;
    fire("connect");
    fire("game_started", { session_id: "s1", save_id: "v1", state: { location_id: "here" }, opening: { narration: "Quiet.", choices: [{ id: "a", text: "Wait" }] } });
    const press = () => React.act(() => host.querySelector("#plugin-move").click());
    const choices = () => appSocket.emitted.filter(([name]) => name === "player_choice");

    appSocket.connected = false;
    fire("disconnect", "transport close");
    press();
    expect(choices()).toEqual([]);

    appSocket.connected = true;
    fire("connect"); // rejoining: still not live
    press();
    expect(choices()).toEqual([]);
    expect(appSocket.emitted.at(-1)).toEqual(["join_session", { session_id: "s1" }]);

    fire("game_started", { session_id: "s1", turn_running: false, opening: { narration: "Quiet.", choices: [{ id: "a", text: "Wait" }] } });
    press();
    expect(choices()).toEqual([["player_choice", { session_id: "s1", choice_id: "a", custom_text: null }]]);
    press(); // busy now: the turn is in flight
    expect(choices()).toHaveLength(1);
  });

  it("the pressed chip keeps focus through the turn, in the whole App (F9, T13)", () => {
    // App's default `Wrap` was an arrow made on every render, so each render
    // was a NEW component type and React remounted the whole play screen:
    // the focused chip was thrown away the moment the turn began (and the
    // compose box's typed text with it). Found by the T13 browser check.
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("no server in this test")));
    window.localStorage.clear();
    appSocket = fakeSocket();
    const story = { slug: "probe", title: "Probe", overlays: [], onboarding: [] };
    React.act(() => root.render(React.createElement(App, { story })));
    const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
    appSocket.connected = true;
    fire("connect");
    fire("game_started", { session_id: "s1", save_id: "v1", state: { location_id: "here" }, opening: { narration: "Quiet.", choices: [{ id: "a", text: "Wait" }, { id: "b", text: "Go" }] } });
    const chip = [...host.querySelectorAll(".choices button")].find((b) => b.textContent.includes("Wait"));
    const box = host.querySelector(".compose__input");
    chip.focus();
    React.act(() => chip.click());
    expect(appSocket.emitted.at(-1)[0]).toBe("player_choice");
    expect(chip.isConnected).toBe(true);
    expect(box.isConnected).toBe(true);
    expect(chip.getAttribute("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(chip);
    fire("narration_delta", { delta: "You wait." });
    expect(document.activeElement).toBe(chip);
    // The turn lands with NEW choice ids: the pressed chip's node is gone,
    // and focus goes to the first new chip, not to <body> (T13 fix round 1).
    fire("turn_update", { narration: "You wait.", choices: [{ id: "c", text: "Cross" }, { id: "d", text: "Knock" }] });
    expect(chip.isConnected).toBe(false);
    expect(document.activeElement.classList.contains("chip")).toBe(true);
    expect(document.activeElement.textContent).toContain("Cross");
  });

  it("an overlay's act buttons are off while the link is not live, not only mid-turn (T13)", () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("no server in this test")));
    window.localStorage.clear();
    appSocket = fakeSocket();
    const Probe = ({ busy }) => React.createElement("button", { type: "button", id: "overlay-act", disabled: busy }, "Act");
    const story = { slug: "probe", title: "Probe", onboarding: [], overlays: [{ id: "probe", key: "p", label: "Probe", Component: Probe }] };
    React.act(() => root.render(React.createElement(App, { story })));
    const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
    appSocket.connected = true;
    fire("connect");
    fire("game_started", { session_id: "s1", save_id: "v1", state: { location_id: "here" }, opening: { narration: "Quiet.", choices: [{ id: "a", text: "Wait" }] } });
    React.act(() => window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "p", bubbles: true })));
    const act = () => host.querySelector("#overlay-act");
    expect(act()).not.toBeNull();
    expect(act().disabled).toBe(false);
    appSocket.connected = false;
    fire("disconnect", "transport close");
    expect(act().disabled).toBe(true);
  });

  it("Try again never re-sends a move whose turn_update already arrived (R1)", () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("no server in this test")));
    window.localStorage.clear();
    appSocket = fakeSocket();
    const story = { slug: "probe", title: "Probe", overlays: [], onboarding: [] };
    React.act(() => root.render(React.createElement(App, { story })));
    const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
    appSocket.connected = true;
    fire("connect");
    fire("game_started", { session_id: "s1", save_id: "v1", state: { location_id: "here" }, opening: { narration: "Quiet.", choices: [{ id: "a", text: "Wait" }] } });
    React.act(() => [...host.querySelectorAll(".choices button")].find((b) => b.textContent.includes("Wait")).click());
    fire("turn_update", { narration: "You wait.", choices: [{ id: "b", text: "Go" }] });
    // Any later failure shows the footer's Try again (the watchdog's, or an error).
    fire("error", { message: "Something else went wrong." });
    const again = [...host.querySelectorAll(".status__retry")].find((b) => b.textContent === "Try again");
    expect(again).toBeTruthy();
    React.act(() => again.click());
    expect(appSocket.emitted.filter(([name]) => name === "player_choice")).toHaveLength(1);
  });

  it("a move lost to a server restart is offered again, and Try again goes to the NEW session (review 2)", () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("no server in this test")));
    window.localStorage.clear();
    appSocket = fakeSocket();
    const story = { slug: "probe", title: "Probe", overlays: [], onboarding: [] };
    React.act(() => root.render(React.createElement(App, { story })));
    const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
    const opening = { narration: "The bell counts the hour.", choices: [{ id: "a", text: "Wait" }] };
    appSocket.connected = true;
    fire("connect");
    fire("game_started", { session_id: "s1", save_id: "v1", state: { location_id: "here" }, opening });
    React.act(() => [...host.querySelectorAll(".choices button")].find((b) => b.textContent.includes("Wait")).click());
    expect(appSocket.emitted.at(-1)).toEqual(["player_choice", { session_id: "s1", choice_id: "a", custom_text: null }]);

    // The server restarts mid-turn: the join misses, the save is resumed in a new session.
    appSocket.connected = false;
    fire("disconnect", "transport close");
    appSocket.connected = true;
    fire("connect");
    fire("error", { message: "session not found" });
    expect(appSocket.emitted.at(-1)).toEqual(["resume", { save_id: "v1" }]);
    fire("game_resumed", { session_id: "s2", save_id: "v1", state: { location_id: "here" }, opening });

    // The canned line appears once, and the dropped move is offered again.
    // Counted in the log's entries: the sentence announcer's live region
    // holds the line for a moment as well (NarrativeLog), and before T13's
    // Wrap fix every render remounted it empty, which hid that from this.
    const inLog = [...host.querySelectorAll(".entry")].filter((el) => el.textContent.includes("The bell counts the hour."));
    expect(inLog).toHaveLength(1);
    const again = [...host.querySelectorAll(".linkbanner__action")].find((b) => b.textContent === "Try again");
    expect(again).toBeTruthy();
    React.act(() => again.click());
    expect(appSocket.emitted.at(-1)).toEqual(["player_choice", { session_id: "s2", choice_id: "a", custom_text: null }]);
    expect(host.querySelector(".linkbanner")).toBeNull();
  });

  // -- T12 fix round 1: two tabs of one browser, and a refused Load ---------

  const opening = { narration: "Quiet.", choices: [{ id: "a", text: "Wait" }] };
  const bannerButton = (label) => [...host.querySelectorAll(".linkbanner__action")].find((b) => b.textContent === label);

  function mountPlaying(fetchImpl) {
    globalThis.fetch = vi.fn(fetchImpl);
    window.localStorage.clear();
    appSocket = fakeSocket();
    const story = { slug: "probe", title: "Probe", overlays: [], onboarding: [] };
    React.act(() => root.render(React.createElement(App, { story })));
    const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
    appSocket.connected = true;
    fire("connect");
    fire("game_started", { session_id: "s1", save_id: "vA", state: { location_id: "here" }, opening });
    return fire;
  }

  it.each([
    ["elsewhere", "Play here"],
    ["ended", "Resume"],
  ])("after %s, %s resumes THIS tab's save, not the one another tab stored since", (reason, label) => {
    const fire = mountPlaying(() => Promise.reject(new Error("no server in this test")));
    // The other tab of this browser began a run: it wrote ITS save to the
    // shared localStorage, and the server released this tab's run.
    window.localStorage.setItem("clockwork_save_id", "vB");
    fire("session_ended", { session_id: "s1", reason });
    const press = bannerButton(label);
    expect(press).toBeTruthy();
    React.act(() => press.click());
    expect(appSocket.emitted.at(-1)).toEqual(["resume", { save_id: "vA" }]);
  });

  async function loadAnotherRun(loadAnswer) {
    const saves = [{ save_id: "v2", player_name: "Wren", archetype: "x", world_day: 1, location_id: "here", turn_number: 1, evil_phase: "dormant", updated_at: 0 }];
    const fire = mountPlaying((url) => {
      if (String(url) === "/api/saves") return Promise.resolve({ ok: true, status: 200, json: async () => ({ saves }) });
      if (String(url).endsWith("/load")) return loadAnswer();
      return Promise.reject(new Error("no server in this test"));
    });
    await React.act(async () => host.querySelector('[aria-label="Saved runs"]').click());
    const go = [...host.querySelectorAll(".saverow button")].find((b) => b.textContent.trim() === "Continue");
    expect(go).toBeTruthy();
    await React.act(async () => go.click());
    return fire;
  }

  it("a Load the server refuses (the save cap) keeps this tab's run: its release still says why", async () => {
    const fire = await loadAnotherRun(() =>
      Promise.resolve({ ok: false, status: 409, json: async () => ({ error: "You have 20 saved runs in this story." }) })
    );
    expect(appSocket.emitted.filter(([name]) => name === "join_session")).toEqual([]);
    fire("session_ended", { session_id: "s1", reason: "elsewhere" });
    expect(bannerButton("Play here")).toBeTruthy();
  });

  it("a Load that never reached the server keeps this tab's run (T12 re-review R2)", async () => {
    const fire = await loadAnotherRun(() => Promise.reject(new TypeError("Failed to fetch")));
    fire("session_ended", { session_id: "s1", reason: "elsewhere" });
    expect(bannerButton("Play here")).toBeTruthy();
  });

  it("a Load answered ok whose body will not parse keeps the drop: the server may have opened the run", async () => {
    const fire = await loadAnotherRun(() =>
      Promise.resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError("bad JSON"); } })
    );
    fire("session_ended", { session_id: "s1", reason: "elsewhere" });
    expect(bannerButton("Play here")).toBeFalsy();
  });
});

describe("final fix wave: the link forgets a pending join that missed (T12 re-review R1)", () => {
  it("this tab's own join missing while live clears it, so a reconnect never re-joins it", () => {
    const h = setup({ session: "s1" });
    toLive(h);
    h.ctl.leaving();
    h.ctl.join("s2");
    expect(h.drain()).toEqual([["join_session", { session_id: "s2" }]]);
    h.socket.fire("error", { message: "session not found" });
    expect(h.state()).toBe("live");
    drop(h);
    connect(h);
    const sent = h.drain();
    expect(sent.filter(([name, body]) => name === "join_session" && body.session_id === "s2")).toEqual([]);
    expect(h.state()).toBe("live");
  });
});

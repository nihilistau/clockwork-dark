// @vitest-environment jsdom
/**
 * The client's core seams for READ RECEIPTS (v0.22.0, spec §18.1): the
 * `phone_action` sender and its busy re-send, the two background pushes, and
 * the `PlayScreen` / `NewRun` slots as App wires them.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// App's socket is the test's fake (below); MicButton reaches for media APIs.
let appSocket = null;
vi.mock("socket.io-client", () => ({ io: () => appSocket }));
vi.mock("../src/core/parts/MicButton.jsx", () => ({ default: () => null }));

import App from "../src/core/App.jsx";
import {
  INBOUND, OUTBOUND, PHONE_RETRY_MS, PHONE_RETRY_TRIES, createPhoneSender, emitPhone,
} from "../src/core/socket.js";
import { initialState, reducer } from "../src/core/store.js";
import { button, click, key, mount, typeInto } from "./helpers/dom.js";

describe("phone seams", () => {
  it("lists the phone events", () => {
    expect(OUTBOUND).toContain("phone_action");
    expect(INBOUND).toEqual(expect.arrayContaining(["phone_message", "media_ready"]));
  });

  it("emits only the catalogue shape", () => {
    const socket = { emit: vi.fn() };
    emitPhone(socket, "s1", { action: "swipe", target: "p0004", args: { dir: "like" }, extra: "x" });
    expect(socket.emit).toHaveBeenCalledWith("phone_action", {
      session_id: "s1", action: "swipe", target: "p0004", args: { dir: "like" }, text: "",
    });
  });

  it("refuses an action-less intent", () => {
    const socket = { emit: vi.fn() };
    expect(emitPhone(socket, "s1", {})).toBe(false);
    expect(socket.emit).not.toHaveBeenCalled();
  });

  it("core keeps nothing of a push: phone_message and media_ready are the plugin's", () => {
    const state = { ...initialState, screen: "scene", sessionId: "s1" };
    for (const event of ["phone_message", "media_ready"]) {
      expect(reducer(state, { type: "SOCKET", event, payload: { message: { id: "m1" } } })).toBe(state);
    }
  });
});

/** Hand-run timers: `run()` fires every one that is due by the clock. */
function manualTimers() {
  let now = 0;
  let next = 1;
  const pending = new Map();
  return {
    set: (fn, ms) => {
      const id = next++;
      pending.set(id, { fn, at: now + ms });
      return id;
    },
    clear: (id) => pending.delete(id),
    advance(ms) {
      now += ms;
      for (const [id, t] of [...pending]) {
        if (t.at <= now && pending.has(id)) {
          pending.delete(id);
          t.fn();
        }
      }
    },
    count: () => pending.size,
  };
}

const SOCKET = (event, payload = {}) => ({ type: "SOCKET", event, payload });

describe("the phone sender (busy is contention, re-sent; spec §18.2)", () => {
  let socket;
  let timers;
  let sender;
  let dropped;
  beforeEach(() => {
    socket = { emit: vi.fn() };
    timers = manualTimers();
    dropped = [];
    sender = createPhoneSender({ getSocket: () => socket, timers, onDrop: (intents) => dropped.push(intents) });
  });
  const sent = () => socket.emit.mock.calls.map(([, body]) => body.action);

  it("re-sends a busy action once after 150 ms, swallowing the busy answer", () => {
    expect(PHONE_RETRY_MS).toBe(150);
    expect(PHONE_RETRY_TRIES).toBe(2);
    sender.send("s1", { action: "send", target: "t1", text: "hi" });
    expect(sent()).toEqual(["send"]);
    expect(sender.filter(SOCKET("turn_error", { message: "A turn is already in progress.", busy: true }))).toBe(true);
    timers.advance(149);
    expect(sent()).toEqual(["send"]);
    timers.advance(1);
    expect(sent()).toEqual(["send", "send"]);
    expect(socket.emit.mock.calls[1]).toEqual(["phone_action", { session_id: "s1", action: "send", target: "t1", args: {}, text: "hi" }]);
    // Answered: the answer reaches the store, and the line is free.
    expect(sender.filter(SOCKET("turn_update", { state: {} }))).toBe(false);
    expect(sender.pending()).toBe(0);
  });

  it("is bounded: a second busy reaches the store, so the plugin can keep the text", () => {
    sender.send("s1", { action: "send", target: "t1", text: "hi" });
    expect(sender.filter(SOCKET("turn_error", { busy: true }))).toBe(true);
    timers.advance(PHONE_RETRY_MS);
    expect(sender.filter(SOCKET("turn_error", { busy: true }))).toBe(false);
    expect(sent()).toHaveLength(PHONE_RETRY_TRIES);
    timers.advance(10 * PHONE_RETRY_MS);
    expect(sent()).toHaveLength(PHONE_RETRY_TRIES);
    expect(sender.pending()).toBe(0);
  });

  it("never retries a real failure", () => {
    sender.send("s1", { action: "swipe", target: "p1", args: { dir: "like" } });
    expect(sender.filter(SOCKET("turn_error", { message: "session not found", fatal: true }))).toBe(false);
    timers.advance(1000);
    expect(sent()).toEqual(["swipe"]);
  });

  it("sends one action at a time: the next waits for the first one's answer", () => {
    sender.send("s1", { action: "swipe", target: "p1", args: { dir: "like" } });
    sender.send("s1", { action: "swipe", target: "p2", args: { dir: "pass" } });
    expect(socket.emit.mock.calls.map(([, b]) => b.target)).toEqual(["p1"]);
    // A busy answer is the FIRST action's: only it is re-sent.
    sender.filter(SOCKET("turn_error", { busy: true }));
    timers.advance(PHONE_RETRY_MS);
    expect(socket.emit.mock.calls.map(([, b]) => b.target)).toEqual(["p1", "p1"]);
    sender.filter(SOCKET("turn_update", {}));
    expect(socket.emit.mock.calls.map(([, b]) => b.target)).toEqual(["p1", "p1", "p2"]);
  });

  it("an answer that never comes stops holding the line; a disconnect drops the queue", () => {
    sender.send("s1", { action: "open_thread", target: "t1" });
    sender.send("s1", { action: "open_thread", target: "t2" });
    timers.advance(10000);
    expect(socket.emit.mock.calls.map(([, b]) => b.target)).toEqual(["t1", "t2"]);
    sender.send("s1", { action: "open_thread", target: "t3" });
    expect(sender.filter({ type: "DISCONNECTED", reason: "transport close" })).toBe(false);
    expect(sender.pending()).toBe(0);
    expect(timers.count()).toBe(0);
    // t2 was sent and may have been applied: only the never-sent t3 is reported.
    expect(dropped).toEqual([[{ action: "open_thread", target: "t3" }]]);
  });

  it("a queued send cut off by a disconnect is reported once, with its intent (I1)", () => {
    const second = { action: "send", target: "t1", text: "are you free friday?" };
    sender.send("s1", { action: "open_thread", target: "t1" });
    sender.send("s1", second);
    sender.filter({ type: "DISCONNECTED", reason: "transport close" });
    expect(dropped).toEqual([[second]]);
    sender.filter({ type: "DISCONNECTED", reason: "transport close" });
    expect(dropped).toHaveLength(1);
  });

  it("a disconnect during the 150 ms busy wait reports the action whose busy was swallowed", () => {
    const first = { action: "send", target: "t1", text: "hi" };
    const second = { action: "send", target: "t2", text: "hey" };
    sender.send("s1", first);
    sender.send("s1", second);
    expect(sender.filter(SOCKET("turn_error", { busy: true }))).toBe(true);
    timers.advance(100);
    sender.filter({ type: "DISCONNECTED", reason: "transport close" });
    expect(dropped).toEqual([[first, second]]);
    timers.advance(1000);
    expect(sent()).toEqual(["send"]);
  });

  it("a retry with no socket to go on is reported, and so is the queue behind it", () => {
    const first = { action: "send", target: "t1", text: "hi" };
    const second = { action: "swipe", target: "p1", args: { dir: "like" } };
    sender.send("s1", first);
    sender.send("s1", second);
    sender.filter(SOCKET("turn_error", { busy: true }));
    socket = null;
    timers.advance(PHONE_RETRY_MS);
    expect(dropped).toEqual([[first], [second]]);
    expect(sender.pending()).toBe(0);
  });

  it("after a timeout, the late answer is credited to nobody (M1)", () => {
    sender.send("s1", { action: "open_thread", target: "a1" });
    sender.send("s1", { action: "open_thread", target: "a2" });
    sender.send("s1", { action: "open_thread", target: "a3" });
    const targets = () => socket.emit.mock.calls.map(([, b]) => b.target);
    timers.advance(10000); // a1 unanswered: a2 goes
    expect(targets()).toEqual(["a1", "a2"]);
    // a1's late answer: passed to the store, but a2 is still waiting.
    expect(sender.filter(SOCKET("turn_update", {}))).toBe(false);
    expect(targets()).toEqual(["a1", "a2"]);
    // a2's own busy is a2's: swallowed and re-sent, never charged to a3.
    expect(sender.filter(SOCKET("turn_error", { busy: true }))).toBe(true);
    timers.advance(PHONE_RETRY_MS);
    expect(targets()).toEqual(["a1", "a2", "a2"]);
    sender.filter(SOCKET("turn_update", {}));
    expect(targets()).toEqual(["a1", "a2", "a2", "a3"]);
  });

  it("an owed late answer is forgotten after a while, so it cannot stall the line", () => {
    const targets = () => socket.emit.mock.calls.map(([, b]) => b.target);
    sender.send("s1", { action: "open_thread", target: "a1" });
    timers.advance(10000); // a1 times out; its answer never comes
    timers.advance(10000); // the debt is forgotten
    sender.send("s1", { action: "open_thread", target: "a2" });
    sender.send("s1", { action: "open_thread", target: "a3" });
    sender.filter(SOCKET("turn_update", {})); // a2's answer, credited to a2
    expect(targets()).toEqual(["a1", "a2", "a3"]);
  });

  it("an answer eaten as the owed late one never re-arms the debt (T27)", () => {
    // a1 times out and its late answer never comes; a2's own answer is eaten
    // as a1's. a2 then times out too -- it must owe nothing, or a3's answer
    // would be eaten in turn and the line would stall from action to action.
    const targets = () => socket.emit.mock.calls.map(([, b]) => b.target);
    for (const t of ["a1", "a2", "a3", "a4"]) sender.send("s1", { action: "open_thread", target: t });
    timers.advance(10000); // a1 unanswered: a2 goes
    expect(targets()).toEqual(["a1", "a2"]);
    const eaten = SOCKET("turn_update", {});
    expect(sender.filter(eaten)).toBe(false); // a2's answer, taken for a1's
    expect(eaten.stale).toBe(true); // and said so, for the plugin's own count
    timers.advance(10000); // a2 times out, owing nothing: a3 goes
    expect(targets()).toEqual(["a1", "a2", "a3"]);
    sender.filter(SOCKET("turn_update", {})); // a3's answer is a3's
    expect(targets()).toEqual(["a1", "a2", "a3", "a4"]);
  });

  it("passes everything else through untouched", () => {
    expect(sender.filter(SOCKET("turn_error", { busy: true }))).toBe(false); // nothing in flight
    sender.send("s1", { action: "wait" });
    for (const event of ["phone_message", "media_ready", "narration_delta", "game_started"]) {
      expect(sender.filter(SOCKET(event, {}))).toBe(false);
    }
    expect(sender.filter({ type: "LINK", link: "live" })).toBe(false);
    expect(sender.pending()).toBe(1);
  });
});

// -- App ---------------------------------------------------------------------

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

const DECK = { matchstick: { app: "matchstick", card: { pid: "p0004" }, likes_left: 30 }, front_porch: { app: "front_porch", card: { pid: "p0009" } } };

/** A phone plugin in miniature: what it was handed, and a button per act. */
function phoneStory(extra = {}) {
  const seen = { props: null, took: [] };
  function PlayScreen(props) {
    seen.props = props;
    const { state, onAct, onOpenMenu } = props;
    return (
      <div data-testid="phone">
        <button type="button" onClick={() => onAct({ action: "swipe", target: "p0004", args: { dir: "like" } })}>Like</button>
        <button type="button" onClick={() => seen.took.push(onAct({ action: "send", target: "t1", text: "hello" }))}>Send</button>
        <button type="button" onClick={onOpenMenu}>Menu</button>
        <input data-testid="compose" defaultValue="half a message" />
        <p data-testid="error">{state.error}</p>
        <p data-testid="pushes">{state.story.pushes}</p>
        <p data-testid="dropped">{(state.story.dropped || []).map((i) => i.text).join("|")}</p>
        <p data-testid="deck">{Object.keys(state.world?.phone?.deck || {}).join(",")}</p>
      </div>
    );
  }
  const reduce = (slice, action) => {
    if (action.type === "RESET") return { pushes: 0 };
    if (action.type === "PHONE_DROPPED") return { ...slice, dropped: action.intents };
    if (action.type === "SOCKET" && (action.event === "phone_message" || action.event === "media_ready")) {
      return { ...slice, pushes: slice.pushes + 1 };
    }
    return slice;
  };
  return { story: { slug: "phone", title: "Phone", overlays: [], onboarding: [], initialState: { pushes: 0 }, reduce, PlayScreen, ...extra }, seen };
}

describe("App with a PlayScreen (spec §18.1)", () => {
  let dom;
  let fetches;
  beforeEach(() => {
    vi.useFakeTimers();
    window.localStorage.clear();
    fetches = [];
    globalThis.fetch = vi.fn((url, init) => {
      fetches.push([url, init]);
      return Promise.reject(new Error("no server in this test"));
    });
    appSocket = fakeSocket();
    dom = mount();
  });
  afterEach(() => {
    dom.unmount();
    vi.useRealTimers();
  });

  const fire = (name, ...args) => React.act(() => appSocket.fire(name, ...args));
  const phoneActions = () => appSocket.emitted.filter(([name]) => name === "phone_action");
  const startRun = () => {
    appSocket.connected = true;
    fire("connect");
    fire("game_started", { session_id: "s1", save_id: "v1", state: { phone: { deck: DECK } }, opening: { choices: [] } });
  };

  it("replaces Play wholesale and hands the slot its props", () => {
    const { story, seen } = phoneStory();
    dom.render(<App story={story} />);
    startRun();
    expect(dom.host.querySelector('[data-testid="phone"]')).not.toBeNull();
    expect(dom.host.querySelector(".compose__input")).toBeNull();
    expect(Object.keys(seen.props).sort()).toEqual(["blocked", "busy", "onAct", "onChoose", "onCustom", "onOpenMenu", "onOpenSaves", "sessionId", "state"]);
    expect(seen.props.blocked).toBe(false);
    click(button(dom.host, "Menu"));
    expect(seen.props.blocked).toBe(true);
    expect(seen.props.sessionId).toBe("s1");
    // The deck arrives keyed by app (T7) and core passes it through whole.
    expect(dom.host.querySelector('[data-testid="deck"]').textContent).toBe("matchstick,front_porch");
  });

  it("onAct emits phone_action with the session and never sets busy", () => {
    const { story, seen } = phoneStory();
    dom.render(<App story={story} />);
    startRun();
    click(button(dom.host, "Like"));
    expect(phoneActions()).toEqual([
      ["phone_action", { session_id: "s1", action: "swipe", target: "p0004", args: { dir: "like" }, text: "" }],
    ]);
    expect(seen.props.busy).toBe(false);
    expect(appSocket.emitted.some(([name]) => name === "player_choice")).toBe(false);
  });

  it("a busy answer is re-sent after 150 ms and never shown; a second busy is", () => {
    const { story } = phoneStory();
    dom.render(<App story={story} />);
    startRun();
    click(button(dom.host, "Send"));
    fire("turn_error", { message: "A turn is already in progress.", busy: true });
    expect(dom.host.querySelector('[data-testid="error"]').textContent).toBe("");
    React.act(() => vi.advanceTimersByTime(PHONE_RETRY_MS));
    expect(phoneActions()).toHaveLength(2);
    expect(phoneActions()[1][1]).toEqual({ session_id: "s1", action: "send", target: "t1", args: {}, text: "hello" });
    fire("turn_error", { message: "A turn is already in progress.", busy: true });
    expect(dom.host.querySelector('[data-testid="error"]').textContent).toBe("A turn is already in progress.");
    React.act(() => vi.advanceTimersByTime(10 * PHONE_RETRY_MS));
    expect(phoneActions()).toHaveLength(2);
  });

  it("sends nothing while the link is not live, and onAct says so", () => {
    const { story, seen } = phoneStory();
    dom.render(<App story={story} />);
    startRun();
    click(button(dom.host, "Send"));
    expect(seen.took).toEqual([true]);
    fire("turn_update", { state: {}, choices: [] });
    appSocket.connected = false;
    fire("disconnect", "transport close");
    click(button(dom.host, "Send"));
    expect(seen.took).toEqual([true, false]);
    expect(phoneActions()).toHaveLength(1);
  });

  it("an action cut off by a disconnect comes back to the plugin as PHONE_DROPPED (I1)", () => {
    const { story } = phoneStory();
    dom.render(<App story={story} />);
    startRun();
    click(button(dom.host, "Send"));
    fire("turn_error", { message: "A turn is already in progress.", busy: true }); // swallowed, waiting to re-send
    appSocket.connected = false;
    fire("disconnect", "transport close");
    expect(dom.host.querySelector('[data-testid="dropped"]').textContent).toBe("hello");
    React.act(() => vi.advanceTimersByTime(10 * PHONE_RETRY_MS));
    expect(phoneActions()).toHaveLength(1);
  });

  it("leaves `/` to the phone: core does not take it for a compose box it has not drawn", () => {
    const { story } = phoneStory();
    dom.render(<App story={story} />);
    startRun();
    const event = new window.KeyboardEvent("keydown", { key: "/", bubbles: true, cancelable: true });
    React.act(() => window.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(false);
  });

  it("Escape while typing in the phone leaves the field; with nothing focused it opens the menu (T27)", () => {
    const { story } = phoneStory();
    dom.render(<App story={story} />);
    startRun();
    const field = dom.host.querySelector('[data-testid="compose"]');
    field.focus();
    expect(document.activeElement).toBe(field);
    const typing = new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    React.act(() => field.dispatchEvent(typing));
    expect(dom.host.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).not.toBe(field);
    expect(field.value).toBe("half a message");
    key("Escape");
    expect(dom.host.querySelector('[role="dialog"]')).not.toBeNull();
  });

  it("the pushes reach the plugin's reduce", () => {
    const { story } = phoneStory();
    dom.render(<App story={story} />);
    startRun();
    fire("phone_message", { message: { id: "m1" }, thread: { thread_id: "t1" }, badges: {}, notification: null });
    fire("media_ready", { message_id: "m1", mid: "x", url: "/u", poster_url: "", kind: "photo", thread: {} });
    expect(dom.host.querySelector('[data-testid="pushes"]').textContent).toBe("2");
  });

  it("keeps the menu around the phone, and offers no overlay", () => {
    const { story } = phoneStory();
    dom.render(<App story={story} />);
    startRun();
    key("k"); // core's clue board, on any other story
    key("m");
    expect(dom.host.querySelector('[role="dialog"]')).toBeNull();
    click(button(dom.host, "Menu"));
    expect(dom.host.querySelector('[role="dialog"]')).not.toBeNull();
  });
});

describe("App with a NewRun (spec §18.1)", () => {
  let dom;
  let posts;
  let answer;
  beforeEach(() => {
    window.localStorage.clear();
    posts = [];
    answer = { ok: false, status: 400, body: { error: "creation.name: must not be empty" } };
    globalThis.fetch = vi.fn((url, init) => {
      if (url === "/api/game/new") {
        posts.push(JSON.parse(init.body));
        return Promise.resolve({ ok: answer.ok, status: answer.status, json: () => Promise.resolve(answer.body) });
      }
      return Promise.reject(new Error("no server in this test"));
    });
    appSocket = fakeSocket();
    dom = mount();
  });
  afterEach(() => dom.unmount());

  function NewRun({ onBegin, onCancel, error }) {
    const [name, setName] = React.useState("");
    return (
      <div data-testid="new-run">
        <input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <button type="button" onClick={() => onBegin({ name, age: 29 })}>Start</button>
        <button type="button" onClick={onCancel}>Back</button>
        {error && <p role="alert">{error}</p>}
      </div>
    );
  }

  it("Begin opens it; its creation goes to /api/game/new whole; a refusal says why", async () => {
    const { story } = phoneStory({ NewRun });
    dom.render(<App story={story} />);
    // The start screen gives way: no name, class or seed of its own.
    expect(dom.host.querySelector(".field__input")).toBeNull();
    click(button(dom.host, "Begin"));
    expect(dom.host.querySelector('[data-testid="new-run"]')).not.toBeNull();
    typeInto(dom.host.querySelector('input[aria-label="Name"]'), "Ada");
    await React.act(async () => {
      button(dom.host, "Start").click();
    });
    expect(posts).toEqual([{ player_name: "Ada", creation: { name: "Ada", age: 29 } }]);
    expect(dom.host.querySelector('[data-testid="new-run"] [role="alert"]').textContent).toBe("Could not begin: creation.name: must not be empty");
    expect(dom.host.querySelector('[data-testid="new-run"]')).not.toBeNull();
    click(button(dom.host, "Back"));
    expect(dom.host.querySelector('[data-testid="new-run"]')).toBeNull();
    expect(button(dom.host, "Begin")).not.toBeNull();
  });

  it("a story with no NewRun begins at once, as before", async () => {
    const { story } = phoneStory();
    dom.render(<App story={story} />);
    typeInto(dom.host.querySelector(".field__input"), "Ada");
    await React.act(async () => {
      button(dom.host, "Begin").click();
    });
    expect(posts).toHaveLength(1);
    expect(posts[0].player_name).toBe("Ada");
    expect(posts[0].creation).toBeUndefined();
  });
});

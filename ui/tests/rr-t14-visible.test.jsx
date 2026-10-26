// @vitest-environment jsdom
// v0.24.0 T14 fix wave B: every phone sound has something to look at (spec §7), the deck keys are the phone's
// own, and the two layers hand control to each other. Rendered through the real PlayScreen and plugin reducer.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { byTestId, click, key, mount } from "./helpers/dom.js";
import { installCatalog, resetSound, setLevels, soundLog, turnSent } from "../src/core/sound/index.js";
import { useTurnSounds } from "../src/core/sound/hooks.js";
import { SOUND_EVENTS } from "../src/stories/read-receipts/sounds.js";
import { initialState, reduce } from "../src/stories/read-receipts/state.js";
import PlayScreen from "../src/stories/read-receipts/PlayScreen.jsx";
import { NOTICE_MS } from "../src/stories/read-receipts/phone/Notice.jsx";
import Companion from "../src/stories/read-receipts/world/Companion.jsx";
import Buzz from "../src/stories/read-receipts/world/Buzz.jsx";
import { coreState, threadProps } from "./fixtures/phone-harness.jsx";
import Thread from "../src/stories/read-receipts/thread/Thread.jsx";
import { phoneFixture } from "./fixtures/phone.js";

const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1, soundChoices: {} };
const tone = { category: "phone", label: "t", synth: { layers: [{ wave: "sine", freq: 880, decay_ms: 40 }] } };
const CAT = {
  ...CATALOG, limits: { ...CATALOG.limits, throttle_ms: 0 },
  events: [...SOUND_EVENTS, "ui.press", "choice.send", "turn.arrive"],
  sounds: { a: tone },
  bind: { ...Object.fromEntries(SOUND_EVENTS.map((e) => [e, "a"])), "ui.press": "a", "choice.send": "a", "turn.arrive": "a" },
};
const heard = () => soundLog().filter((r) => !r.dropped).map((r) => r.event);

const WORLD = (over = {}) => ({ phone_up: true, at_work: false, location: "Your flat", buzz: { count: 0, who: [] }, household: {}, ...over });
const base = (over = {}) => phoneFixture({ phone: { world: WORLD(over) } });
const push = (slice, event, payload) => reduce(slice, { type: "SOCKET", event, payload });
const messagePush = (id = "matchstick:p1190", at = 99) => {
  const phone = phoneFixture();
  const row = { ...phone.threads.find((t) => t.thread_id === id), last: { at, from: "p1190", kind: "text", pending: false, preview: "are you free later" } };
  return { thread: row, badges: {}, notification: { id: `n${at}`, thread_id: id, name: row.name, pid: row.pid, preview: "are you free later", app: "matchstick", at, kind: "text" }, message: null, messages: [] };
};

let view; let onAct;
beforeEach(() => {
  installFakeAudio(); resetSound({ logPlays: true }); installCatalog(CAT); gesture(); setLevels(PREFS);
  view = mount(); onAct = vi.fn(() => true);
  window.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} });
});
afterEach(() => { view.unmount(); resetSound(); vi.useRealTimers(); delete window.matchMedia; });

const screen = (phone, story, props = {}) => (
  <PlayScreen state={{ ...coreState(phone, story), link: "live", choices: [], log: [] }} sessionId="s1" onAct={onAct}
              onChoose={() => {}} onCustom={() => {}} onOpenMenu={() => {}} onOpenSaves={() => {}} prefs={PREFS} onPrefs={vi.fn()} {...props} />
);
const opened = (over = {}) => ({ ...initialState, openSeq: 1, ...over });
const unlock = () => click(view.host.querySelector(".rr-lock__open"));

describe("d1: a push with the phone down raises the buzz banner with its sound", () => {
  it("buzzes and shows who, at once, without waiting for a turn_update", () => {
    const phone = base({ phone_up: false });
    view.render(screen(phone, opened()));
    expect(byTestId(view.host, "rr-buzz")).toBeNull();
    const story = push(opened(), "phone_message", messagePush());
    view.render(screen(phone, story));
    expect(heard()).toEqual(["phone.buzz"]);
    const banner = byTestId(view.host, "rr-buzz");
    expect(banner.textContent).toContain("Your phone buzzed");
    expect(banner.textContent).toContain("Yusuf");
    expect(banner.textContent).not.toContain("are you free later");          // names only, never words
  });

  it("counts a notification the payload already holds once", () => {
    const phone = base({ phone_up: false, buzz: { count: 1, who: ["Yusuf"] } });
    phone.notifications = [...phone.notifications, { id: "n99", thread_id: "matchstick:p1190", name: "Yusuf", pid: "p1190", preview: "New message", app: "matchstick", at: 99, kind: "text" }];
    view.render(screen(phone, push(opened(), "phone_message", messagePush())));
    expect(byTestId(view.host, "rr-buzz").textContent).not.toMatch(/times/);
  });
});

describe("d2: a message in another thread, and a match, are seen as they are heard", () => {
  it("shows the sender and preview with phone.notify, opens that thread on a tap, and dismisses itself", () => {
    vi.useFakeTimers();
    const phone = base();
    view.render(screen(phone, opened()));
    unlock();
    view.render(screen(phone, push(opened(), "phone_message", messagePush())));
    expect(heard()).toEqual(["phone.unlock", "phone.notify"]);
    const notice = byTestId(view.host, "rr-notice");
    expect(notice.textContent).toContain("Yusuf");
    expect(notice.textContent).toContain("are you free later");
    React.act(() => { vi.advanceTimersByTime(NOTICE_MS + 10); });
    expect(byTestId(view.host, "rr-notice")).toBeNull();
    view.render(screen(phone, push(opened(), "phone_message", messagePush("matchstick:p1190", 120))));
    click(view.host.querySelector(".rr-notice__open"));
    expect(onAct).toHaveBeenCalledWith(expect.objectContaining({ action: "open_thread", target: "matchstick:p1190" }));
    expect(byTestId(view.host, "rr-notice")).toBeNull();
  });

  it("a match shows 'It's a match' with phone.match, naming them", () => {
    const phone = base();
    view.render(screen(phone, opened()));
    unlock();
    const matched = { ...phone, threads: [{ ...phone.threads[2], thread_id: "matchstick:p7777", pid: "p7777", name: "Rae", last: null }, ...phone.threads] };
    view.render(screen(matched, opened()));
    expect(heard()).toEqual(["phone.unlock", "phone.match"]);
    const notice = byTestId(view.host, "rr-notice");
    expect(notice.textContent).toContain("It's a match");
    expect(notice.textContent).toContain("Rae");
  });
});

describe("d7: one sound for an arrival", () => {
  function Shell({ phone, story, busy, turns }) {
    useTurnSounds({ busy, error: "", phoneUp: true, link: "live", turns });
    return screen(phone, story);
  }
  it("a scene door and a message together sound the door only, and the bell stands down", () => {
    const phone = base();
    view.render(<Shell phone={phone} story={opened()} busy={false} turns={0} />);
    turnSent();
    view.render(<Shell phone={phone} story={opened()} busy turns={0} />);
    const arrived = { ...phone, scene: { id: "p1190@40.0", pid: "p1190", name: "Yusuf" } };
    view.render(<Shell phone={arrived} story={push(opened(), "phone_message", messagePush())} busy={false} turns={1} />);
    expect(heard()).toEqual(["scene.open"]);
  });

  it("a plain arrival still gets the bell", () => {
    const phone = base();
    view.render(<Shell phone={phone} story={opened()} busy={false} turns={0} />);
    turnSent();
    view.render(<Shell phone={phone} story={opened()} busy turns={0} />);
    view.render(<Shell phone={phone} story={opened()} busy={false} turns={1} />);
    expect(heard()).toEqual(["turn.arrive"]);
  });
});

describe("b1: the deck's arrow keys belong to a deck the player can see", () => {
  it("a swipe key does nothing once the phone is put down, and works while it is up", () => {
    const phone = base();
    view.render(screen(phone, opened()));
    unlock();
    click([...view.host.querySelectorAll("button")].find((b) => /Matchstick/.test(b.textContent)));
    key("ArrowRight", document.body);
    expect(onAct).toHaveBeenCalledWith(expect.objectContaining({ action: "swipe" }));
    onAct.mockClear();
    click(view.host.querySelector(".rr-status__down"));
    onAct.mockClear();
    view.render(screen(base({ phone_up: false }), opened()));
    key("ArrowRight", document.body);
    key("ArrowUp", document.body);
    expect(onAct).not.toHaveBeenCalled();
  });
});

describe("b2: control passes between the layers", () => {
  it("puts focus on the world when the phone goes down, and on the phone when it comes back", () => {
    const up = base();
    view.render(screen(up, opened()));
    view.render(screen(base({ phone_up: false }), opened()));
    expect(document.activeElement).toBe(view.host.querySelector(".rr-world"));
    view.render(screen(up, opened()));
    expect(document.activeElement).toBe(view.host.querySelector(".rr-view"));
  });

  it("the dimmed world under a raised phone, and the phone put down under 1200px, are inert", () => {
    view.render(screen(base(), opened()));
    expect(byTestId(view.host, "rr-world-layer").hasAttribute("inert")).toBe(true);
    expect(byTestId(view.host, "rr-phone-layer").hasAttribute("inert")).toBe(false);
    view.render(screen(base({ phone_up: false }), opened()));
    expect(byTestId(view.host, "rr-world-layer").hasAttribute("inert")).toBe(false);
    expect(byTestId(view.host, "rr-phone-layer").hasAttribute("inert")).toBe(true);
  });
});

describe("b3: a resume starts from the server's word on the phone", () => {
  it("clears a local pick-up", () => {
    const down = base({ phone_up: false, buzz: { count: 1, who: ["Cole"] } });
    view.render(screen(down, opened()));
    click(view.host.querySelector(".rr-buzz__pick"));
    expect(byTestId(view.host, "rr-world-layer").hasAttribute("inert")).toBe(true);     // picked up locally
    view.render(screen(down, opened({ openSeq: 2 })));
    expect(byTestId(view.host, "rr-world-layer").hasAttribute("inert")).toBe(false);
  });
});

describe("b4: a late game_started for the run on screen leaves the pushes alone", () => {
  it("the slice mirrors core's no-op", () => {
    const world = { phone: phoneFixture() };
    const s1 = reduce(initialState, { type: "SOCKET", event: "game_started", payload: { session_id: "s1", state: world } }, { world });
    const pushed = push(s1, "phone_message", messagePush());
    expect(pushed.pushes).toHaveLength(1);
    const late = { session_id: "s1", state: { phone: phoneFixture() } };
    const after = reduce(pushed, { type: "SOCKET", event: "game_started", payload: late }, { world });     // core kept its world
    expect(after).toBe(pushed);
    const rejoin = reduce(pushed, { type: "SOCKET", event: "game_started", payload: late }, { world: late.state });   // core took it
    expect(rejoin.openSeq).toBe(pushed.openSeq + 1);
  });
});

describe("b7: roles", () => {
  it("the companion card is a named group, and only the buzz's words are a live region", () => {
    view.render(<Companion person={{ pid: "p1", name: "Kai" }} />);
    expect(byTestId(view.host, "rr-companion").getAttribute("role")).toBe("group");
    view.render(<Buzz buzz={{ count: 1, who: ["Kai"] }} onPickUp={() => {}} />);
    const banner = byTestId(view.host, "rr-buzz");
    expect(banner.getAttribute("role")).toBeNull();
    expect(banner.querySelector('[role="status"]').textContent).toContain("Kai");
    expect(banner.querySelector("button").closest('[role="status"]')).toBeNull();
  });
});

describe("b5: the thread's plan sheet offers the engine's kinds", () => {
  it("lists what meet_options carries, not the client's own list", () => {
    view.render(<Thread {...threadProps({ phone: { meet_options: { kinds: ["coffee", "karaoke"], venues: [] } } })} />);
    click([...view.host.querySelectorAll("button")].find((b) => b.textContent === "Ask"));
    click([...view.host.querySelectorAll("button")].find((b) => /meet up/i.test(b.textContent)));
    const options = [...byTestId(view.host, "plan-kind").querySelectorAll("option")].map((o) => o.value);
    expect(options).toEqual(["", "coffee", "karaoke"]);
  });
});

describe("b6: a resume brings unread messages and makes no sound", () => {
  it("through the composed reducer and PlayScreen", async () => {
    const { createStore } = await import("../src/core/store.js");
    const { default: plugin } = await import("../src/stories/read-receipts/index.jsx");
    const { initial, reducer } = createStore(plugin);
    const loaded = base();
    loaded.threads = loaded.threads.map((t, i) => (t.last ? { ...t, last: { ...t.last, at: 500 + i } } : t));
    let state = reducer(initial, { type: "SOCKET", event: "game_started", payload: { session_id: "s1", state: { phone: base() }, opening: {} } });
    view.render(<PlayScreen state={{ ...state, link: "live", choices: [], log: [] }} sessionId="s1" onAct={onAct} onChoose={() => {}} onCustom={() => {}} onOpenMenu={() => {}} onOpenSaves={() => {}} prefs={PREFS} onPrefs={vi.fn()} />);
    state = reducer(state, { type: "SOCKET", event: "game_resumed", payload: { session_id: "s1", state: { phone: loaded }, opening: {} } });
    view.render(<PlayScreen state={{ ...state, link: "live", choices: [], log: [] }} sessionId="s1" onAct={onAct} onChoose={() => {}} onCustom={() => {}} onOpenMenu={() => {}} onOpenSaves={() => {}} prefs={PREFS} onPrefs={vi.fn()} />);
    expect(state.story.openSeq).toBeGreaterThan(1);
    expect(heard()).toEqual([]);
  });
});

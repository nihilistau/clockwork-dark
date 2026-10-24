// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { click, mount, typeInto } from "./helpers/dom.js";
import { installCatalog, installClickSounds, resetSound, setLevels, soundLog } from "../src/core/sound/index.js";
import { hydrate, messageKey, phoneSounds, SOUND_EVENTS } from "../src/stories/read-receipts/sounds.js";
import { PrefsContext } from "../src/stories/read-receipts/prefs.js";
import { initialState, reduce } from "../src/stories/read-receipts/state.js";
import PlayScreen from "../src/stories/read-receipts/PlayScreen.jsx";
import Thread from "../src/stories/read-receipts/thread/Thread.jsx";
import PhoneSettings from "../src/stories/read-receipts/settings/Settings.jsx";
import World from "../src/stories/read-receipts/world/World.jsx";
import { Harness, PID, coreState, threadProps, worldState } from "./fixtures/phone-harness.jsx";
import { phoneFixture } from "./fixtures/phone.js";

const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1, soundChoices: {} };
const tone = (extra = {}) => ({ category: "phone", label: "t", synth: { layers: [{ wave: "sine", freq: 880, decay_ms: 40 }] }, ...extra });
const CAT = {
  ...CATALOG, limits: { ...CATALOG.limits, throttle_ms: 0 },
  events: [...SOUND_EVENTS, "ui.press", "choice.send"],
  sounds: { a: tone(), b: tone(), tick: tone({ throttle_ms: 4000 }), "ring.marimba": tone(), "ring.classic": tone(), "ring.pulse": tone() },
  bind: {
    ...Object.fromEntries(SOUND_EVENTS.map((e) => [e, "a"])),
    "phone.notify": "b", "phone.typing": "tick",
    "phone.ring": { default: "ring.marimba", choices: ["ring.marimba", "ring.classic", "ring.pulse"] },
    "ui.press": "a", "choice.send": "a",
  },
};

const row = (id, last, extra = {}) => ({ thread_id: id, app: "matchstick", last, ...extra });
const msg = (at, from = "them", kind = "text", extra = {}) => ({ from, kind, at, preview: "hi", pending: false, ...extra });
const phone = (threads, { scene = {}, up = true } = {}) => ({ threads, scene, world: { phone_up: up } });
const CTX = { openThread: "", up: true };

beforeEach(() => { installFakeAudio(); resetSound({ logPlays: true }); installCatalog(CAT); gesture(); setLevels(PREFS); });
afterEach(() => resetSound());
const heard = () => soundLog().filter((r) => !r.dropped).map((r) => r.event);
const flush = () => React.act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe("one message, one sound (spec §9.7)", () => {
  const before = phone([row("t1", msg(10)), row("t2", msg(10))]);

  it("the open thread pops", () => {
    phoneSounds(before, phone([row("t1", msg(11)), row("t2", msg(10))]), { openThread: "t1", up: true });
    expect(heard()).toEqual(["phone.message_in"]);
  });

  it("another thread notifies", () => {
    phoneSounds(before, phone([row("t1", msg(10)), row("t2", msg(11))]), { openThread: "t1", up: true });
    expect(heard()).toEqual(["phone.notify"]);
  });

  it("the phone down buzzes", () => {
    phoneSounds(before, phone([row("t1", msg(11)), row("t2", msg(10))], { up: false }), { openThread: "t1", up: false });
    expect(heard()).toEqual(["phone.buzz"]);
  });

  it("a voice note or a video rings, wherever the phone is", () => {
    phoneSounds(before, phone([row("t1", msg(11, "them", "voice"))], { up: false }), { openThread: "", up: false });
    expect(heard()).toEqual(["phone.ring"]);
  });

  it("a burst plays its highest sound once", () => {
    phoneSounds(before, phone([row("t1", msg(11)), row("t2", msg(11, "them", "video"))]), { openThread: "t1", up: true });
    expect(heard()).toEqual(["phone.ring"]);
  });

  it("a push, then a turn_update re-carrying the same rows: heard once (F2)", () => {
    const pushed = phone([row("t1", msg(10)), row("t2", msg(11))]);
    phoneSounds(before, pushed, CTX);
    const again = phone([row("t1", msg(10)), row("t2", msg(11))]);         // a NEW object, identical rows
    phoneSounds(pushed, again, CTX);
    expect(heard()).toEqual(["phone.notify"]);
  });

  it("pending in the payload, then voiced by push with the same at: heard once, at the push (F2)", () => {
    const pending = phone([row("t1", msg(10)), row("t2", msg(11, "them", "text", { pending: true }))]);
    phoneSounds(before, pending, CTX);
    expect(heard()).toEqual([]);
    const voiced = phone([row("t1", msg(10)), row("t2", msg(11))]);
    phoneSounds(pending, voiced, CTX);
    phoneSounds(voiced, phone([row("t1", msg(10)), row("t2", msg(11))]), CTX);
    expect(heard()).toEqual(["phone.notify"]);
  });

  it("a media_ready for a voice note that already rang never rings again (F21)", () => {
    const rang = phone([row("t1", msg(12, "them", "voice"))]);
    phoneSounds(before, rang, CTX);
    phoneSounds(rang, phone([row("t1", msg(12, "them", "voice", { preview: "Voice note (0:07)" }))]), CTX);
    expect(heard()).toEqual(["phone.ring"]);
  });

  it("the player's own messages and unvoiced ones are silent", () => {
    phoneSounds(before, phone([row("t1", msg(11, "player")), row("t2", msg(11, "them", "text", { pending: true }))]), CTX);
    expect(heard()).toEqual([]);
  });

  it("a resume with unread messages is silent", () => {
    const loaded = phone([row("t1", msg(30)), row("t3", msg(31))], { scene: { id: "p1@30.0", pid: "p1" } });
    hydrate(loaded);
    phoneSounds({ threads: [] }, loaded, CTX);
    expect(heard()).toEqual([]);
  });

  it("a new DATING-APP thread chimes once; a number swap's texts thread does not (F14)", () => {
    phoneSounds(before, phone([...before.threads, row("t8", null, { app: "texts" })]), CTX);
    phoneSounds(before, phone([...before.threads, row("t9", null, { app: "front_porch" })]), CTX);
    expect(heard()).toEqual(["phone.match"]);
  });

  it("a scene id new to the page opens with the door, once", () => {
    phoneSounds(before, phone(before.threads, { scene: { id: "p1@40.5", pid: "p1" } }), CTX);
    phoneSounds(before, phone(before.threads, { scene: { id: "p1@40.5", pid: "p1" } }), CTX);
    expect(heard()).toEqual(["scene.open"]);
  });

  it("the player's ringtone choice is the next ring", () => {
    setLevels({ ...PREFS, soundChoices: { "phone.ring": "ring.classic" } });
    phoneSounds(before, phone([row("t1", msg(12, "them", "voice"))]), CTX);
    expect(soundLog().at(-1).sound).toBe("ring.classic");
  });

  it("keys a message by thread and time (Plan decision 1)", () => {
    expect(messageKey(row("t1", msg(10.25)))).toBe("msg:t1@10.25");
  });
});

describe("hydration on every opening, a rejoin included (F12)", () => {
  it("state.js bumps openSeq on a rejoin's game_started with the same session", () => {
    const s1 = reduce(initialState, { type: "SOCKET", event: "game_started", payload: { session_id: "s1" } });
    const s2 = reduce(s1, { type: "SOCKET", event: "game_started", payload: { session_id: "s1" } });
    expect(s2.openSeq).toBe(s1.openSeq + 1);
    expect(s2.lockSeq).toBe(s1.lockSeq);                                       // no lock screen for a rejoin
  });

  it("a rejoin carrying two new messages is silent", () => {
    const view = mount();
    const a = phoneFixture();
    const props = { sessionId: "s1", onAct: vi.fn(), onOpenMenu: () => {}, onOpenSaves: () => {}, prefs: PREFS, onPrefs: vi.fn() };
    view.render(<PlayScreen state={coreState(a, { ...initialState, openSeq: 1 })} {...props} />);
    const b = { ...a, threads: (a.threads || []).map((t, i) => ({ ...t, last: msg(500 + i, "p9") })) };
    view.render(<PlayScreen state={coreState(b, { ...initialState, openSeq: 2 })} {...props} />);
    expect(heard()).toEqual([]);
    view.unmount();
  });
});

describe("the phone's own controls (pre-flight gap 1)", () => {
  let view; let off;
  beforeEach(() => { view = mount(); off = installClickSounds(document); });
  afterEach(() => { off(); view.unmount(); });

  it("typing ticks once per (thread, last message); a second within 4 s is throttled", () => {
    view.render(<Thread {...threadProps({ typing: true })} />);
    view.render(<Thread {...threadProps({ typing: true })} />);
    expect(heard()).toEqual(["phone.typing"]);
    view.render(<Thread {...threadProps({ typing: true, row: { last: msg(99, PID) } })} />);
    expect(soundLog().at(-1).dropped).toBe("throttled");
  });

  it("sending plays phone.send alone, by button or Enter; nothing when empty or refused", async () => {
    const props = threadProps({});
    view.render(<Thread {...props} />);
    typeInto(view.host.querySelector(".rr-compose__input"), "hello");
    click(view.host.querySelector(".rr-compose__send"));
    typeInto(view.host.querySelector(".rr-compose__input"), "again");
    React.act(() => { view.host.querySelector(".rr-compose__input").form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    click(view.host.querySelector(".rr-compose__send"));                       // empty: disabled
    await flush();
    expect(heard()).toEqual(["phone.send", "phone.send"]);
    view.render(<Thread {...threadProps({ act: vi.fn(() => false) })} />);       // the sender refuses
    typeInto(view.host.querySelector(".rr-compose__input"), "no");
    click(view.host.querySelector(".rr-compose__send"));
    await flush();
    expect(heard()).toEqual(["phone.send", "phone.send"]);
  });

  it("unlocking by a notification or by Open phone, and locking, each sound once (F17)", async () => {
    view.render(<Harness onAct={vi.fn()} />);                                  // the harness taps a lock-screen notification
    click(view.host.querySelector('button[aria-label="Lock"]'));
    click(view.host.querySelector(".rr-lock__open"));
    await flush();
    expect(heard()).toEqual(["phone.unlock", "phone.lock", "phone.unlock"]);
  });

  it("putting the phone down and picking it up", async () => {
    const up = phoneFixture({ phone: { world: { phone_up: true } } });
    view.render(<Harness onAct={vi.fn()} phone={up} />);
    click(view.host.querySelector(".rr-status__down"));
    await flush();
    expect(heard()).toContain("phone.down");
    view.unmount(); view = mount();
    const down = phoneFixture({ phone: { world: { phone_up: false, buzz: { count: 1, names: ["Cole"] } } } });
    view.render(<PlayScreen state={coreState(down)} sessionId="s1" onAct={vi.fn()} onOpenMenu={() => {}} onOpenSaves={() => {}} />);
    click(view.host.querySelector(".rr-buzz__pick"));
    await flush();
    expect(heard().at(-1)).toBe("phone.up");
  });

  it("the world's typed line plays choice.send (F17)", async () => {
    const onCustom = vi.fn();
    view.render(<World state={worldState()} phoneUp={false} onChoose={() => {}} onCustom={onCustom} />);
    const input = view.host.querySelector(".rr-world form input");
    typeInto(input, "look around");
    React.act(() => { input.form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    await flush();
    expect(onCustom).toHaveBeenCalledWith("look around");
    expect(heard()).toEqual(["choice.send"]);
  });

  it("the Settings app writes the ringtone choice through onPrefs, and previews it (F13)", async () => {
    const onPrefs = vi.fn();
    view.render(<PhoneSettings phone={phoneFixture()} act={vi.fn()} pending={null} prefs={PREFS} onPrefs={onPrefs} />);
    click([...view.host.querySelectorAll("label")].find((l) => l.textContent.includes("Classic")).querySelector("input"));
    expect(onPrefs).toHaveBeenCalledWith(expect.objectContaining({ soundChoices: { "phone.ring": "ring.classic" } }));
    click(view.host.querySelector('[data-preview="ring.classic"]'));
    await flush();
    expect(soundLog().filter((r) => !r.dropped).at(-1).sound).toBe("ring.classic");
  });
});

describe("a reply during play sounds, without a sent turn (F2)", () => {
  it("a new message in another thread, arriving as a phone push, notifies once", () => {
    const view = mount();
    const a = phoneFixture();
    const props = { sessionId: "s1", onAct: vi.fn(), onOpenMenu: () => {}, onOpenSaves: () => {}, prefs: PREFS, onPrefs: vi.fn() };
    const story = { ...initialState, openSeq: 1 };
    view.render(<PlayScreen state={coreState(a, story)} {...props} />);
    const b = { ...a, threads: (a.threads || []).map((t, i) => (i === 0 ? { ...t, last: msg(900, t.pid || "p9") } : t)) };
    view.render(<PlayScreen state={coreState(b, story)} {...props} />);
    view.render(<PlayScreen state={coreState({ ...b, threads: [...b.threads] }, story)} {...props} />);   // the same rows again
    expect(heard()).toEqual(["phone.notify"]);
    view.unmount();
  });

  it("a hydrated unvoiced message sounds when it is voiced", () => {
    const pending = phone([row("t1", msg(10, "them", "text", { pending: true }))]);
    hydrate(pending);
    phoneSounds(pending, phone([row("t1", msg(10))]), CTX);
    expect(heard()).toEqual(["phone.notify"]);
  });
});

describe("the voice note's volume (spec §9.7)", () => {
  it("follows master x phone and the mute", () => {
    const view = mount();
    const voiceMsg = { id: "v1", from: PID, kind: "voice", at: 40.5, bubbles: [], pending: false, media_id: "x4",
      media: { mid: "x4", kind: "voice", status: "ready", url: "/api/phone/media/save-1/x4-abc.wav", transcript: "hi", seconds: 3 } };
    const props = threadProps({ messages: [voiceMsg] });
    const at = (prefs) => <PrefsContext.Provider value={prefs}><Thread {...props} /></PrefsContext.Provider>;
    view.render(at({ ...PREFS, soundMaster: 0.5, soundPhone: 0.4 }));
    const audio = () => view.host.querySelector("audio.rr-voice__audio");
    expect(audio().volume).toBeCloseTo(0.2);
    view.render(at({ ...PREFS, muted: true }));
    expect(audio().volume).toBe(0);
    view.unmount();
  });
});

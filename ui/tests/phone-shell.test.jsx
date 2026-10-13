// @vitest-environment jsdom
// ui/tests/phone-shell.test.jsx -- READ RECEIPTS' phone around its apps (v0.22.0 T27, spec §18.2):
// the lock screen, home, the slice's push merging, the kept "Not sent", and the borrowing rule.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import plugin from "../src/stories/read-receipts/index.jsx";
import PlayScreen from "../src/stories/read-receipts/PlayScreen.jsx";
import { currentPhone, initialState, MAX_PUSHES, reduce } from "../src/stories/read-receipts/state.js";
import { resolveStory } from "../src/core/story.js";
import { phoneFixture } from "./fixtures/phone.js";
import { button, byTestId, byText, click, mount, typeInto } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => view.unmount());

const SOCKET = (event, payload) => ({ type: "SOCKET", event, payload });

/** Core's state as the store holds it for this plugin: the payload's world, the plugin's slice. */
function coreState(phone, story = initialState) {
  return { world: { phone }, story, busy: false, sessionId: "s1", error: "" };
}

/** PlayScreen on a state, re-rendered on the same root as the slice moves. */
function Shell({ phone, story, onAct }) {
  return <PlayScreen state={coreState(phone, story)} onAct={onAct} onOpenMenu={() => {}} onOpenSaves={() => {}} />;
}

describe("the lock screen", () => {
  it("lists notifications newest first, puts the phone down, and opens onto home", () => {
    const onAct = vi.fn(() => true);
    const phone = phoneFixture();
    view.render(<Shell phone={phone} story={initialState} onAct={onAct} />);
    expect(byTestId(view.host, "lock-screen")).not.toBeNull();
    const ids = [...view.host.querySelectorAll('[data-testid^="notif-"]')].map((el) => el.dataset.testid);
    expect(ids).toEqual(phone.notifications.map((n) => `notif-${n.id}`).reverse());
    expect(byTestId(view.host, "status-time").textContent).toBe("17:41");
    click(button(view.host, "Put it down"));
    expect(onAct).toHaveBeenCalledWith({ action: "wait", target: "", args: { until: "next" }, text: "" });
    click(button(view.host, "Open phone"));
    expect(byTestId(view.host, "home")).not.toBeNull();
  });

  it("shows a new run's opening, and a resume's away line", () => {
    let slice = reduce(initialState, SOCKET("game_started", {
      session_id: "s1", opening: { narration: "The flat still smells of cardboard." },
    }));
    view.render(<Shell phone={phoneFixture()} story={slice} onAct={vi.fn()} />);
    expect(view.host.textContent).toContain("The flat still smells of cardboard.");
    slice = reduce(slice, SOCKET("game_resumed", {
      session_id: "s1", opening: { lock_screen: { text: "While you were away: 1 new match", lines: ["1 new match"] } },
    }));
    view.render(<Shell phone={phoneFixture()} story={slice} onAct={vi.fn()} />);
    expect(view.host.textContent).toContain("While you were away: 1 new match");
  });

  it("goes back to the lock screen on a resume, not on a rejoin of the run on screen", () => {
    let slice = reduce(initialState, SOCKET("game_started", { session_id: "s1", opening: {} }));
    view.render(<Shell phone={phoneFixture()} story={slice} onAct={vi.fn()} />);
    click(button(view.host, "Open phone"));
    expect(byTestId(view.host, "home")).not.toBeNull();
    slice = reduce(slice, SOCKET("game_started", { session_id: "s1", opening: {}, turn_running: true }));
    view.render(<Shell phone={phoneFixture()} story={slice} onAct={vi.fn()} />);
    expect(byTestId(view.host, "home")).not.toBeNull();
    slice = reduce(slice, SOCKET("game_resumed", { session_id: "s1", opening: { lock_screen: { text: "" } } }));
    view.render(<Shell phone={phoneFixture()} story={slice} onAct={vi.fn()} />);
    expect(byTestId(view.host, "lock-screen")).not.toBeNull();
  });

  it("opens the thread a notification names", () => {
    const onAct = vi.fn(() => true);
    const phone = phoneFixture();
    const newest = phone.notifications[phone.notifications.length - 1];
    view.render(<Shell phone={phone} story={initialState} onAct={onAct} />);
    click(byTestId(view.host, `notif-${newest.id}`));
    expect(onAct).toHaveBeenCalledWith({ action: "open_thread", target: newest.thread_id, args: {}, text: "" });
    expect(view.host.querySelector(".rr-thread")).not.toBeNull();
  });
});

describe("focus follows the screen (review I3)", () => {
  it("unlock, an app, a thread: the new screen has the focus", () => {
    view.render(<Shell phone={phoneFixture()} story={initialState} onAct={vi.fn(() => true)} />);
    const open = button(view.host, "Open phone");
    open.focus();
    click(open);
    expect(document.activeElement).toBe(view.host.querySelector(".rr-view"));
    click(byTestId(view.host, "app-matchstick"));
    expect(document.activeElement.tagName).toBe("H2");
    expect(document.activeElement.textContent).toBe("Matchstick");
    click(view.host.querySelector('[role="tab"]:nth-child(3)'));
    click(byTestId(view.host, "chat-matchstick:p0347"));
    expect(document.activeElement).toBe(view.host.querySelector("textarea"));
    click(button(view.host, "Back"));
    expect(document.activeElement.textContent).toBe("Matchstick");
  });
});

describe("hidden values in every row the phone draws (review M8)", () => {
  const HIDDEN = { warmth: 7311, interest: 6911, trust: 5821, ghosted: "zz-ghosted-sentinel", mood: "zz-mood-sentinel" };
  const clean = () => {
    const html = view.host.innerHTML;
    for (const value of Object.values(HIDDEN)) expect(html).not.toContain(String(value));
    for (const name of Object.keys(HIDDEN)) expect(view.host.querySelector("[data-" + name + "], [" + name + "]")).toBeNull();
  };
  it("the lock screen, the chats, Likes you and a thread", () => {
    const phone = phoneFixture({ hidden: HIDDEN });
    view.render(<Shell phone={phone} story={initialState} onAct={vi.fn(() => true)} />);
    expect(view.host.querySelectorAll(".rr-notif").length).toBeGreaterThan(0);
    clean();
    click(button(view.host, "Open phone"));
    click(byTestId(view.host, "app-matchstick"));
    click(view.host.querySelector('[role="tab"]:nth-child(3)'));
    expect(view.host.querySelectorAll(".rr-chat").length).toBeGreaterThan(0);
    clean();
    click(button(view.host, "Home"));
    click(byTestId(view.host, "app-front_porch"));
    click(view.host.querySelector('[role="tab"]:nth-child(2)'));
    expect(view.host.querySelectorAll(".rr-likes__row").length).toBeGreaterThan(0);
    clean();
    click(button(view.host, "Home"));
    click(byTestId(view.host, "app-matchstick"));
    click(view.host.querySelector('[role="tab"]:nth-child(3)'));
    click(byTestId(view.host, "chat-" + phone.open_thread.thread_id));
    expect(view.host.querySelectorAll(".rr-bubble").length).toBeGreaterThan(0);
    clean();
  });
});

describe("home", () => {
  it("draws every app, the dock's four, and the badges", () => {
    const phone = phoneFixture();
    view.render(<Shell phone={phone} story={initialState} onAct={vi.fn()} />);
    click(button(view.host, "Open phone"));
    for (const app of phone.apps) expect(byTestId(view.host, `app-${app.id}`)).not.toBeNull();
    const dock = view.host.querySelector('nav[aria-label="Dock"]');
    expect([...dock.querySelectorAll("[data-app]")].map((el) => el.dataset.app)).toEqual(["texts", "natter", "matchstick", "front_porch"]);
    expect(byTestId(view.host, "badge-matchstick").textContent).toBe("2");
    expect(byTestId(view.host, "badge-front_porch")).toBeNull();
    click(byTestId(view.host, "app-matchstick"));
    expect(view.host.querySelector('[aria-label="Matchstick"]')).not.toBeNull();
    click(button(view.host, "Home"));
    expect(byTestId(view.host, "home")).not.toBeNull();
    // The side button: back to the lock screen, where the phone is put down.
    click(button(view.host, "Lock"));
    expect(byTestId(view.host, "lock-screen")).not.toBeNull();
    expect(button(view.host, "Lock")).toBeNull();
  });

  it("shows the engine's refusal of the last action", () => {
    const phone = phoneFixture({ phone: { refusal: { action: "swipe", target: "p0004", reason: "No likes left today." } } });
    view.render(<Shell phone={phone} story={initialState} onAct={vi.fn()} />);
    expect(view.host.querySelector('[role="status"]').textContent).toContain("No likes left today.");
  });
});

describe("the slice: pushes merged idempotently (spec §17.3)", () => {
  const phone = phoneFixture();
  const open = phone.open_thread;
  const row = phone.threads.find((t) => t.thread_id === open.thread_id);
  const message = { id: "m9", from: row.pid, kind: "photo", at: 40, bubbles: ["look at this"], pending: false,
                    media_id: "x1", media: { mid: "x1", kind: "photo", status: "sending", url: "", poster_url: "", caption: "the harbour" } };
  const pushed = SOCKET("phone_message", {
    message, messages: [message], thread: { ...row, unread: 3, last: { from: row.pid, kind: "photo", at: 40, preview: "look at this", pending: false } },
    badges: { matchstick: 5 }, notification: { id: "n99", app: "matchstick", thread_id: row.thread_id, pid: row.pid, kind: "photo", preview: "look at this", at: 40, name: row.name },
  });
  const ready = SOCKET("media_ready", { message_id: "m9", mid: "x1", url: "/api/phone/media/v1/x1.png", poster_url: "", kind: "photo", thread: null });
  const state = (slice) => ({ world: { phone }, story: slice });

  it("applies a message push to the thread, the badges, the notifications and the open thread", () => {
    const now = currentPhone(state(reduce(initialState, pushed)));
    expect(now.open_thread.messages.map((m) => m.id)).toEqual([...open.messages.map((m) => m.id), "m9"]);
    expect(now.threads[0].thread_id).toBe(row.thread_id);
    expect(now.threads.find((t) => t.thread_id === row.thread_id).unread).toBe(3);
    expect(now.apps.find((a) => a.id === "matchstick").badge).toBe(5);
    expect(now.apps.find((a) => a.id === "front_porch").badge).toBe(0);
    expect(now.notifications.at(-1).id).toBe("n99");
    expect(phone.open_thread.messages).toHaveLength(open.messages.length); // the payload itself untouched
  });

  it("a voiced message's push updates its notification in place: the lock screen drops \"New message\" (T30)", () => {
    // The payload listed the notification while its message was still being written ("New message");
    // the voicing pass's push carries the SAME notification id with the words now written.
    const waiting = { id: "n99", app: "matchstick", thread_id: row.thread_id, pid: row.pid, kind: "text", preview: "New message", at: 40, name: row.name };
    const base = { ...phone, notifications: [...phone.notifications, waiting] };
    const voiced = SOCKET("phone_message", {
      message: { id: "m9", from: row.pid, kind: "text", at: 40, bubbles: ["tell me more"], pending: false, media_id: null },
      thread: { ...row, last: { from: row.pid, kind: "text", at: 40, preview: "tell me more", pending: false } },
      badges: {}, notification: { ...waiting, preview: "tell me more" },
    });
    const now = currentPhone({ world: { phone: base }, story: reduce(initialState, voiced) });
    const rows = now.notifications.filter((n) => n.id === "n99");
    expect(rows).toHaveLength(1);
    expect(rows[0].preview).toBe("tell me more");
    expect(now.notifications.at(-1).id).toBe("n99");   // its place kept
  });

  it("pushes apply in arrival order: an older media row never overwrites a newer message row (review I1)", () => {
    const older = { ...row, unread: 1, last: { from: row.pid, kind: "photo", at: 41, preview: "Photo", pending: false } };
    const newer = { ...row, unread: 2, last: { from: row.pid, kind: "text", at: 42, preview: "newer text", pending: false } };
    const m10 = { id: "m10", from: row.pid, kind: "text", at: 42, bubbles: ["newer text"], pending: false, media_id: null };
    const media = SOCKET("media_ready", { message_id: "m9", mid: "x1", url: "/u.png", poster_url: "", kind: "photo", thread: older });
    const text = SOCKET("phone_message", { message: m10, messages: [m10], thread: newer, badges: { matchstick: 2 }, notification: null });
    const now = currentPhone(state(reduce(reduce(initialState, media), text)));
    const held = now.threads.find((t) => t.thread_id === row.thread_id);
    expect(held.unread).toBe(2);
    expect(held.last.preview).toBe("newer text");
    // The other way round: a newer media row after an older message row is taken.
    const late = { ...row, unread: 3, last: { from: row.pid, kind: "photo", at: 43, preview: "Photo", pending: false } };
    const lateMedia = SOCKET("media_ready", { message_id: "m9", mid: "x1", url: "/u.png", poster_url: "", kind: "photo", thread: late });
    const after = currentPhone(state(reduce(reduce(initialState, text), lateMedia)));
    expect(after.threads.find((t) => t.thread_id === row.thread_id).unread).toBe(3);
  });

  it("keeps at most MAX_PUSHES between two payloads, dropping the oldest (review M2)", () => {
    let slice = initialState;
    for (let i = 0; i < MAX_PUSHES + 5; i += 1) {
      slice = reduce(slice, SOCKET("phone_message", { message: { id: "k" + i }, thread: null, badges: {}, notification: null }));
    }
    expect(slice.pushes).toHaveLength(MAX_PUSHES);
    expect(slice.pushes[0].body.message.id).toBe("k5");
    expect(slice.pushes.at(-1).body.message.id).toBe("k" + (MAX_PUSHES + 4));
  });

  it("an answer core credits to no action (stale) answers nothing of ours (review M1)", () => {
    expect(reduce(initialState, { ...SOCKET("turn_update", {}), stale: true }).turnSeq).toBe(0);
    expect(reduce(initialState, { ...SOCKET("turn_error", { busy: true }), stale: true }).busySeq).toBe(0);
    expect(reduce(initialState, SOCKET("turn_update", {})).turnSeq).toBe(1);
  });

  it("a duplicate push changes nothing more", () => {
    const once = currentPhone(state(reduce(initialState, pushed)));
    const twice = currentPhone(state(reduce(reduce(initialState, pushed), pushed)));
    expect(twice).toEqual(once);
  });

  it("a media_ready before its phone_message still lands on the message", () => {
    const inOrder = currentPhone(state(reduce(reduce(initialState, pushed), ready)));
    const early = currentPhone(state(reduce(reduce(initialState, ready), pushed)));
    expect(early).toEqual(inOrder);
    const m9 = early.open_thread.messages.find((m) => m.id === "m9");
    expect(m9.media).toMatchObject({ url: "/api/phone/media/v1/x1.png", status: "ready", caption: "the harbour" });
    const again = currentPhone(state(reduce(reduce(reduce(initialState, ready), pushed), ready)));
    expect(again).toEqual(inOrder);
  });

  it("a full payload supersedes the pushes; an unrelated action keeps the slice", () => {
    const slice = reduce(initialState, pushed);
    expect(reduce(slice, SOCKET("turn_update", {})).pushes).toEqual([]);
    expect(reduce(slice, { type: "REASONING_TOGGLE" })).toBe(slice);
    expect(reduce(slice, { type: "RESET" })).toEqual(initialState);
  });
});

describe("a phone action that never went (spec §18.2)", () => {
  function play(onAct) {
    let slice = initialState;
    const phone = phoneFixture();
    const render = () => view.render(<Shell phone={phone} story={slice} onAct={onAct} />);
    render();
    click(byTestId(view.host, `notif-${phone.notifications[phone.notifications.length - 1].id}`));
    const thread = phone.notifications[phone.notifications.length - 1].thread_id;
    slice = reduce(slice, SOCKET("turn_update", {}));
    render();
    return { thread, render, step: (action) => { slice = reduce(slice, action); render(); } };
  }

  it("a second busy keeps the text with Not sent — tap to retry; the retry sends it again", () => {
    const onAct = vi.fn(() => true);
    const { thread, step } = play(onAct);
    typeInto(view.host.querySelector("textarea"), "see you at 8");
    click(button(view.host, "Send"));
    const sent = { action: "send", target: thread, args: { kind: "text" }, text: "see you at 8" };
    expect(onAct).toHaveBeenLastCalledWith(sent);
    expect(view.host.querySelector("textarea").value).toBe("");
    // Core re-sent the first busy itself; the one that reaches the store is final.
    step(SOCKET("turn_error", { busy: true, message: "A turn is already in progress." }));
    expect(byText(view.host, "Not sent — tap to retry")).not.toBeNull();
    expect(view.host.querySelector("textarea").value).toBe("see you at 8");
    expect(onAct).toHaveBeenCalledTimes(2); // open_thread, send: no third send of its own
    click(byText(view.host, "Not sent — tap to retry"));
    expect(onAct).toHaveBeenLastCalledWith(sent);
    expect(byText(view.host, "Not sent — tap to retry")).toBeNull();
  });

  it("an action core reports dropped keeps its text", () => {
    const onAct = vi.fn(() => true);
    const { step } = play(onAct);
    typeInto(view.host.querySelector("textarea"), "running late!");
    click(button(view.host, "Send"));
    const sent = onAct.mock.calls.at(-1)[0];
    step({ type: "PHONE_DROPPED", intents: [sent] });
    expect(view.host.querySelector("textarea").value).toBe("running late!");
    expect(byText(view.host, "Not sent — tap to retry")).not.toBeNull();
  });

  it("an onAct that refuses (the link down) keeps the text at once", () => {
    const onAct = vi.fn((intent) => intent.action !== "send");
    play(onAct);
    typeInto(view.host.querySelector("textarea"), "hello?");
    click(button(view.host, "Send"));
    expect(view.host.querySelector("textarea").value).toBe("hello?");
    expect(byText(view.host, "Not sent — tap to retry")).not.toBeNull();
  });

  it("a stale late answer does not end our send: its busy still keeps the text (review M1)", () => {
    const onAct = vi.fn(() => true);
    const { step } = play(onAct);
    typeInto(view.host.querySelector("textarea"), "are you free friday");
    click(button(view.host, "Send"));
    step({ ...SOCKET("turn_update", {}), stale: true }); // an earlier action's late answer
    step(SOCKET("turn_error", { busy: true }));
    expect(view.host.querySelector("textarea").value).toBe("are you free friday");
    expect(byText(view.host, "Not sent — tap to retry")).not.toBeNull();
  });

  it("an answered action is done with: no Not sent", () => {
    const onAct = vi.fn(() => true);
    const { step } = play(onAct);
    typeInto(view.host.querySelector("textarea"), "hi");
    click(button(view.host, "Send"));
    step(SOCKET("turn_update", {}));
    step(SOCKET("turn_error", { busy: true }));
    expect(byText(view.host, "Not sent — tap to retry")).toBeNull();
  });
});

describe("the plugin", () => {
  it("exports both slots, and a borrowing story's load strips them", async () => {
    expect(plugin.PlayScreen).toBe(PlayScreen);
    expect(typeof plugin.NewRun).toBe("function");
    const real = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        active: "borrower",
        games: [{ slug: "borrower", title: "The Borrower", active: true, ui_plugin: "read-receipts", ui: { panels: [] } }],
      }),
    }));
    try {
      const borrowed = await resolveStory();
      expect(borrowed.title).toBe("The Borrower");
      expect(borrowed.PlayScreen).toBeNull();
      expect(borrowed.NewRun).toBeNull();
      expect(borrowed.reduce).toBe(plugin.reduce); // the look and the slice stay; the screens go
      globalThis.fetch = vi.fn(async () => ({
        ok: true,
        json: async () => ({ active: "read-receipts", games: [{ slug: "read-receipts", title: "Read Receipts", active: true, ui_plugin: "read-receipts" }] }),
      }));
      const own = await resolveStory();
      expect(own.PlayScreen).toBe(PlayScreen);
      expect(own.NewRun).toBe(plugin.NewRun);
    } finally {
      globalThis.fetch = real;
    }
  });
});

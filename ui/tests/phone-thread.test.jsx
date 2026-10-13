// @vitest-environment jsdom
// ui/tests/phone-thread.test.jsx -- READ RECEIPTS' thread, whole (v0.22.0 T28, spec §18.2): bubbles,
// read state and typing, the media tiles, request / game / meet-up cards, the compose bar and its
// attachments, "Load earlier", the busy rule, the landscape split, and the hidden-value scan.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Thread from "../src/stories/read-receipts/thread/Thread.jsx";
import { mediaSrc } from "../src/stories/read-receipts/thread/media.js";
import { SPLIT_QUERY } from "../src/stories/read-receipts/PlayScreen.jsx";
import { currentPhone, initialState, keptPushes, reduce } from "../src/stories/read-receipts/state.js";
import { phoneFixture } from "./fixtures/phone.js";
import { Harness, PID, threadProps } from "./fixtures/phone-harness.jsx";
import { button, byTestId, byText, click, mount, typeInto } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => view.unmount());

const compose = () => view.host.querySelector("textarea");
const typeAndSend = (text) => { typeInto(compose(), text); click(button(view.host, /^send$/i)); };
const sends = (fn) => fn.mock.calls.filter(([intent]) => intent.action === "send");
const flush = () => React.act(async () => { await Promise.resolve(); await Promise.resolve(); });

const MEDIA = "/api/phone/media/save-1/x3-abc123.png";

describe("the busy rule (spec §18.2; T27 deviation 1: core re-sends, the plugin never does)", () => {
  it("adds no re-send of its own on busy, and then keeps the text", () => {
    vi.useFakeTimers();
    try {
      const onAct = vi.fn(() => true);
      view.render(<Harness onAct={onAct} />);
      typeAndSend("see you at 8");
      expect(sends(onAct)).toHaveLength(1);
      // The busy that reaches the store is core's second: its own re-send already went.
      view.render(<Harness onAct={onAct} busySeq={1} />);
      React.act(() => vi.advanceTimersByTime(150));
      expect(sends(onAct)).toHaveLength(1);
      expect(byText(view.host, "Not sent — tap to retry")).not.toBeNull();
      expect(compose().value).toBe("see you at 8");
      // The retry is the player's tap: one more send, the same words.
      click(byText(view.host, "Not sent — tap to retry"));
      expect(sends(onAct)).toHaveLength(2);
      expect(sends(onAct)[1][0]).toEqual({ action: "send", target: `matchstick:${PID}`, args: { kind: "text" }, text: "see you at 8" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps a photo attachment and its caption through a busy", () => {
    const onAct = vi.fn(() => true);
    const phone = phoneFixture();
    phone.open_thread.thread_id = `texts:${PID}`;
    phone.open_thread.app = "texts";
    phone.threads = phone.threads.map((t) => (t.pid === PID ? { ...t, app: "texts", thread_id: `texts:${PID}` } : t));
    phone.notifications = phone.notifications.map((n) => (n.pid === PID ? { ...n, thread_id: `texts:${PID}` } : n));
    view.render(<Harness onAct={onAct} phone={phone} />);
    click(button(view.host, "Attach a photo"));
    click(button(view.host, "halfway up a climbing wall"));
    typeAndSend("me last week");
    expect(sends(onAct)[0][0]).toEqual({ action: "send", target: `texts:${PID}`, args: { kind: "photo", photo_id: "climbing_wall" }, text: "me last week" });
    view.render(<Harness onAct={onAct} phone={phone} busySeq={1} />);
    expect(compose().value).toBe("me last week");
    expect(byTestId(view.host, "compose-attachment").textContent).toContain("halfway up a climbing wall");
  });
});

describe("the bubbles", () => {
  it("shows dots only while typing and an ellipsis for an unvoiced message", () => {
    view.render(<Thread {...threadProps({ typing: false, unvoiced: 1 })} />);
    expect(byTestId(view.host, "typing-dots")).toBeNull();
    expect(byText(view.host, "…")).not.toBeNull();
    view.render(<Thread {...threadProps({ typing: true, unvoiced: 0 })} />);
    expect(byTestId(view.host, "typing-dots")).not.toBeNull();
    expect(byText(view.host, "…")).toBeNull();
  });

  it("reads 'Read 21:15' (its read_at) on a receipts app and 'Delivered' elsewhere", () => {
    const mine = { id: "m10", from: "player", kind: "text", at: 40.5, bubbles: ["you up?"], pending: false, read_at: 45.25 };
    view.render(<Thread {...threadProps({ app: "natter", messages: [mine], row: { read_state: "read" } })} />);
    expect(byTestId(view.host, "read-state").textContent).toBe("Read 21:15");
    view.render(<Thread {...threadProps({ app: "texts", messages: [{ ...mine, read_at: null }], row: { read_state: "delivered" } })} />);
    expect(byTestId(view.host, "read-state").textContent).toBe("Delivered");
  });

  it("draws the engine's lines and the player's asks and answers in words", () => {
    const lines = [
      { id: "m20", from: "system", kind: "system", at: 40, bubbles: ["You matched with Cole."], pending: false },
      { id: "m21", from: "player", kind: "request", at: 40.1, bubbles: [], ask: "number", request_id: "r1", pending: false },
      { id: "m22", from: "player", kind: "request", at: 40.2, bubbles: [], answer: "later", request_id: "r2", pending: false },
    ];
    view.render(<Thread {...threadProps({ messages: lines })} />);
    expect(byText(view.host, "You matched with Cole.")).not.toBeNull();
    expect(byText(view.host, "You asked Cole for their number.")).not.toBeNull();
    expect(byText(view.host, "You said maybe later.")).not.toBeNull();
  });
});

describe("a no that means not yet (owner bug, v0.22.0)", () => {
  it("says Not yet. under their decline when the engine's why was the gate, and nothing for a plain no", () => {
    const notYet = { id: "m20", from: PID, kind: "text", at: 41, bubbles: ["slow down, we only just started"], pending: false, declined: "not_yet" };
    view.render(<Thread {...threadProps({ messages: [notYet] })} />);
    expect(byText(view.host, "Not yet.")).not.toBeNull();
    view.render(<Thread {...threadProps({ messages: [{ ...notYet, declined: "no" }] })} />);
    expect(byText(view.host, "Not yet.")).toBeNull();
  });
});

describe("media tiles (spec §13.5-13.8)", () => {
  const photo = (media) => ({ id: "m30", from: PID, kind: "photo", at: 40, bubbles: [], pending: false, media_id: "x3", media });
  const voice = (media) => ({ id: "m31", from: PID, kind: "voice", at: 40.1, bubbles: [], pending: false, media_id: "x4", media });
  const video = (media) => ({ id: "m32", from: PID, kind: "video", at: 40.2, bubbles: [], pending: false, media_id: "x5", media });

  it("renders photo, voice and video tiles from a ready and a fallback row", () => {
    const ready = [
      photo({ mid: "x3", kind: "photo", status: "ready", url: MEDIA, poster_url: "", caption: "my coffee" }),
      voice({ mid: "x4", kind: "voice", status: "ready", url: "/api/phone/media/save-1/x4-abc.wav", poster_url: "", caption: "", transcript: "hey you", seconds: 7 }),
      video({ mid: "x5", kind: "video", status: "ready", url: "/api/phone/media/save-1/x5-abc.mp4", poster_url: "/api/phone/media/save-1/x5-abc.png", caption: "the view" }),
    ];
    view.render(<Thread {...threadProps({ messages: ready })} />);
    expect(byTestId(view.host, "photo-x3").querySelector("img").getAttribute("src")).toBe(MEDIA);
    expect(byTestId(view.host, "voice-x4").querySelector("audio").getAttribute("src")).toBe("/api/phone/media/save-1/x4-abc.wav");
    expect(byTestId(view.host, "voice-x4").textContent).toContain("0:07");
    expect(byTestId(view.host, "voice-x4").textContent).toContain("“hey you”");
    const clip = byTestId(view.host, "video-x5").querySelector("video");
    expect(clip.getAttribute("src")).toBe("/api/phone/media/save-1/x5-abc.mp4");
    expect(clip.getAttribute("poster")).toBe("/api/phone/media/save-1/x5-abc.png");

    const fallback = [
      photo({ mid: "x3", kind: "photo", status: "fallback", url: "", poster_url: "", caption: "my coffee" }),
      voice({ mid: "x4", kind: "voice", status: "fallback", url: "", poster_url: "", caption: "", transcript: "hey you", seconds: 7 }),
      video({ mid: "x5", kind: "video", status: "fallback", url: "", poster_url: "", caption: "the view" }),
    ];
    view.render(<Thread {...threadProps({ messages: fallback })} />);
    expect(byTestId(view.host, "photo-x3").querySelector("img")).toBeNull();
    expect(byTestId(view.host, "photo-x3").textContent).toContain("my coffee");
    // A procedural tile shows its caption (their words) under the tile, as a generated one does (T30 follow-up).
    expect(byTestId(view.host, "photo-x3").querySelector(".rr-tile__caption--under").textContent).toBe("Photo: my coffee");
    expect(byTestId(view.host, "video-x5").querySelector(".rr-tile__caption--under").textContent).toBe("Video: the view");
    // One accessible name per tile (T30 review M3): everything not aria-hidden reads "Photo: my coffee", once.
    const spoken = (el) => {
      const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let out = "";
      for (let n = walk.nextNode(); n; n = walk.nextNode()) if (!n.parentElement.closest("[aria-hidden='true']")) out += n.textContent;
      return out.trim();
    };
    expect(spoken(byTestId(view.host, "photo-x3"))).toBe("Photo: my coffee");
    expect(byTestId(view.host, "voice-x4").querySelector("audio")).toBeNull();
    expect(byTestId(view.host, "voice-x4").textContent).toContain("“hey you”");
    expect(byTestId(view.host, "voice-x4").querySelectorAll(".rr-voice__wave span").length).toBeGreaterThan(10);
    expect(byTestId(view.host, "video-x5").querySelector("video")).toBeNull();
    expect(byTestId(view.host, "video-x5").textContent).toContain("the view");
    view.render(<Thread {...threadProps({ messages: [photo({ mid: "x3", kind: "photo", status: "fallback", url: "", poster_url: "", caption: "" })] })} />);
    expect(spoken(byTestId(view.host, "photo-x3"))).toBe("Photo");
  });

  it("loads media only from the server's media route", () => {
    expect(mediaSrc(MEDIA)).toBe(MEDIA);
    for (const bad of ["https://evil.example/x.png", "javascript:alert(1)", "data:image/png;base64,AAAA",
      "/api/phone/media/../x/x3-a.png", "/api/phone/media/s/x3-a.svg", "//evil.example/api/phone/media/s/x.png", 42]) {
      expect(mediaSrc(bad)).toBe("");
    }
    view.render(<Thread {...threadProps({ messages: [photo({ mid: "x3", kind: "photo", status: "ready", url: "https://evil.example/a.png", caption: "c" })] })} />);
    expect(view.host.querySelector("img[src]")).toBeNull();
    expect(byTestId(view.host, "photo-x3").textContent).toContain("c");
  });
});

describe("requests, games and meet-ups in the thread", () => {
  const theirs = { id: "r3", pid: PID, name: "Cole", from: "them", what: "number", status: "pending", at: 40, thread_id: `matchstick:${PID}` };

  it("answers a request card through answer", () => {
    const act = vi.fn(() => true);
    view.render(<Thread {...threadProps({ act, phone: { requests: [theirs] } })} />);
    expect(byText(view.host, "Cole asked for your number.")).not.toBeNull();
    click(button(view.host, "Yes"));
    expect(act).toHaveBeenCalledWith({ action: "answer", target: "r3", args: { reply: "yes" }, text: "" });
    click(button(view.host, "Maybe later"));
    expect(act).toHaveBeenLastCalledWith({ action: "answer", target: "r3", args: { reply: "later" }, text: "" });
  });

  it("words a meet-up request as the payload does, and the player's own ask waits with no buttons", () => {
    const meet = { ...theirs, id: "r4", what: "meet", venue: "the_anchor", day: 3, slot: "evening", venue_label: "The Anchor", when: "Wed 19:00" };
    const mine = { ...theirs, id: "r5", from: "player", what: "photo" };
    view.render(<Thread {...threadProps({ phone: { requests: [meet, mine] } })} />);
    expect(byTestId(view.host, "request-r4").textContent).toContain("The Anchor · Wed 19:00");
    const waiting = byTestId(view.host, "request-r5");
    expect(waiting.textContent).toContain("You asked Cole for a photo.");
    expect(waiting.querySelector("button")).toBeNull();
  });

  it("words the player's own ask answered 'later' as theirs, not as still waiting (T30 follow-up)", () => {
    const later = { ...theirs, id: "r7", from: "player", what: "video", status: "later" };
    view.render(<Thread {...threadProps({ phone: { requests: [later] } })} />);
    const card = byTestId(view.host, "request-r7");
    expect(card.textContent).toContain("Cole said maybe later.");
    expect(card.textContent).not.toContain("Waiting for");
  });

  it("takes a counter-offer in one tap, through propose_meet at the countered slot (T30 follow-up)", () => {
    const act = vi.fn(() => true);
    const counter = { venue: "copper_kettle", slot: "evening", days_ahead: 1, when: "Fri 19:00", open: true };
    const line = { id: "m40", from: "system", kind: "system", at: 40, bubbles: ["Cole can't make that. Fri 19:00 works."], pending: false, counter };
    view.render(<Thread {...threadProps({ act, messages: [line] })} />);
    const row = byTestId(view.host, "msg-m40");
    expect(row.textContent).toContain("Fri 19:00 works.");
    click(button(row, "Accept Fri 19:00"));
    expect(act).toHaveBeenCalledWith({ action: "propose_meet", target: PID, args: { venue: "copper_kettle", day: 1, slot: "evening" }, text: "" });
    // A counter no longer open (taken, gone by, or the slot filled) is words only.
    view.render(<Thread {...threadProps({ act, messages: [{ ...line, counter: { ...counter, open: false } }] })} />);
    expect(byTestId(view.host, "msg-m40").querySelector("button")).toBeNull();
  });

  it("shows a game with them -- whose turn and the scores, never their rack", () => {
    const game = { id: "g1", game: "wordgame", label: "Tile Talk", pid: PID, name: "Cole", status: "active", turn: "player",
      scores: { player: 12, them: 9 }, rack: "zqxjkvw", board: [], moves: [] };
    const onOpenGame = vi.fn();
    view.render(<Thread {...threadProps({ phone: { games: [game] } })} onOpenGame={onOpenGame} />);
    const card = byTestId(view.host, "game-g1");
    expect(card.textContent).toContain("Tile Talk · Your turn");
    expect(card.textContent).toContain("You 12 · Cole 9");
    expect(view.host.innerHTML).not.toContain("zqxjkvw");
    click(button(card, "Play"));
    expect(onOpenGame).toHaveBeenCalledWith("g1");
  });

  it("goes to a meet-up that is due, and asks before calling one off", () => {
    const act = vi.fn(() => true);
    const meet = { id: "t1", pid: PID, name: "Cole", venue: "the_anchor", venue_label: "The Anchor", when: "Tue 19:00", status: "due", start: 43, end: 45.5 };
    view.render(<Thread {...threadProps({ act, phone: { calendar: [meet] } })} />);
    const card = byTestId(view.host, "meet-t1");
    expect(card.textContent).toContain("The Anchor · Tue 19:00");
    click(button(card, "Cancel"));
    expect(act).not.toHaveBeenCalled();
    click(button(card, "Keep it"));
    click(button(card, "Go"));
    expect(act).toHaveBeenCalledWith({ action: "meet", target: "t1", args: { do: "go" }, text: "" });
    click(button(card, "Cancel"));
    click(button(card, "Call it off"));
    expect(act).toHaveBeenLastCalledWith({ action: "meet", target: "t1", args: { do: "cancel" }, text: "" });
  });
});

describe("the compose bar", () => {
  it("offers only the app's attachments", () => {
    view.render(<Thread {...threadProps({ app: "texts" })} />);
    expect(button(view.host, /voice/i)).toBeNull();
    expect(button(view.host, /video/i)).toBeNull();
    expect(button(view.host, /photo/i)).not.toBeNull();
    view.render(<Thread {...threadProps({ app: "matchstick" })} />);
    expect(button(view.host, /photo|video|voice/i)).toBeNull();
    view.render(<Thread {...threadProps({ app: "natter" })} />);
    for (const name of [/photo/i, /video/i, /voice/i]) expect(button(view.host, name)).not.toBeNull();
  });

  it("asks only for what the app can carry, and their number only on a dating app", () => {
    const act = vi.fn(() => true);
    view.render(<Thread {...threadProps({ app: "matchstick", act, row: { asks: ["number"] } })} />);
    click(button(view.host, "Ask"));
    expect(button(view.host, "Their number")).not.toBeNull();
    expect(button(view.host, "A photo")).toBeNull();
    click(button(view.host, "Their number"));
    expect(act).toHaveBeenCalledWith({ action: "ask", target: `matchstick:${PID}`, args: { what: "number" }, text: "" });
    view.render(<Thread {...threadProps({ app: "natter", act })} />);
    click(button(view.host, "Ask"));
    expect(button(view.host, "Their number")).toBeNull();
    expect(button(view.host, "A video")).not.toBeNull();
  });

  it("greys their number until the engine's row says it is open (owner bug, v0.22.0)", () => {
    const act = vi.fn(() => true);
    view.render(<Thread {...threadProps({ app: "matchstick", act, row: { asks: [] } })} />);
    click(button(view.host, "Ask"));
    const number = button(view.host, "Their number");
    expect(number.disabled).toBe(true);
    click(number);
    expect(act).not.toHaveBeenCalled();
    view.render(<Thread {...threadProps({ app: "matchstick", act, row: { asks: ["number"] } })} />);
    expect(button(view.host, "Their number").disabled).toBe(false);
  });

  it("sends a video subject and a voice note as the catalogue shapes them", () => {
    const act = vi.fn(() => true);
    view.render(<Thread {...threadProps({ app: "natter", act })} />);
    click(button(view.host, "Attach a video"));
    expect(button(view.host, "what I'm cooking")).toBeNull(); // a photo-only subject
    click(button(view.host, "my walk"));
    click(button(view.host, /^send$/i));
    expect(act).toHaveBeenLastCalledWith({ action: "send", target: `natter:${PID}`, args: { kind: "video", subject: "my_walk" }, text: "" });
    click(button(view.host, "Voice note"));
    typeAndSend("running ten minutes late");
    expect(act).toHaveBeenLastCalledWith({ action: "send", target: `natter:${PID}`, args: { kind: "voice", audio_transcript: "running ten minutes late" }, text: "" });
  });

  it("refuses to send over 600 characters client-side and shows the count", () => {
    const act = vi.fn(() => true);
    view.render(<Thread {...threadProps({ act })} />);
    typeInto(compose(), "a".repeat(600));
    expect(byTestId(view.host, "compose-count").textContent).toBe("600/600");
    expect(button(view.host, /^send$/i).disabled).toBe(false);
    typeInto(compose(), "a".repeat(601));
    expect(byTestId(view.host, "compose-count").textContent).toBe("601/600");
    expect(button(view.host, /^send$/i).disabled).toBe(true);
    compose().dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(act).not.toHaveBeenCalled();
  });

  it("ignores turn_running on join: a busy core state leaves the compose bar enabled", () => {
    const onAct = vi.fn(() => true);
    view.render(<Harness onAct={onAct} busy />);
    expect(compose().disabled).toBe(false);
    typeAndSend("hi");
    expect(sends(onAct)).toHaveLength(1);
  });
});

describe("load earlier (the archive, spec §17.2)", () => {
  it("pages older messages in above, oldest first, and stops when there are no more", async () => {
    const fetchPage = vi.fn(async () => ({
      thread_id: `matchstick:${PID}`, more: false,
      messages: [
        { id: "m0b", from: PID, kind: "text", at: 20, bubbles: ["second oldest"], pending: false },
        { id: "m0a", from: "player", kind: "text", at: 19, bubbles: ["oldest"], pending: false },
      ],
    }));
    const props = threadProps({ fetchPage });
    props.phone.open_thread.more = true;
    view.render(<Thread {...props} />);
    click(button(view.host, "Load earlier"));
    await flush();
    expect(fetchPage).toHaveBeenCalledWith("s1", `matchstick:${PID}`, "m1", 50);
    const ids = [...view.host.querySelectorAll('[data-testid^="msg-"]')].map((el) => el.dataset.testid);
    expect(ids.slice(0, 3)).toEqual(["msg-m0a", "msg-m0b", "msg-m1"]);
    expect(button(view.host, "Load earlier")).toBeNull();
  });

  it("drops a page that lands after another thread opened (review M6)", async () => {
    let resolve;
    const fetchPage = vi.fn(() => new Promise((r) => { resolve = r; }));
    const props = threadProps({ fetchPage });
    props.phone.open_thread.more = true;
    view.render(<Thread {...props} />);
    click(button(view.host, "Load earlier"));
    const other = threadProps({ app: "natter", fetchPage });
    view.render(<Thread {...other} />);
    resolve({ messages: [{ id: "m0z", from: PID, kind: "text", at: 1, bubbles: ["from the old thread"], pending: false }], more: false });
    await flush();
    expect(byTestId(view.host, "msg-m0z")).toBeNull();
    expect(view.host.textContent).not.toContain("from the old thread");
  });

  it("says so when the page cannot be read, and offers it again", async () => {
    const fetchPage = vi.fn(async () => { throw new Error("busy"); });
    const props = threadProps({ fetchPage });
    props.phone.open_thread.more = true;
    view.render(<Thread {...props} />);
    click(button(view.host, "Load earlier"));
    await flush();
    expect(view.host.textContent).toContain("The phone is busy. Try again in a moment.");
    expect(button(view.host, "Load earlier")).not.toBeNull();
  });
});

describe("a push the payload has not caught up with (T27 review M3)", () => {
  const thread = `matchstick:${PID}`;
  const voiced = { id: "m4", from: PID, kind: "text", at: 32.562878742028026, bubbles: ["sorry, didn't mean to spam you"], pending: false };

  it("keeps a push newer than the turn_update's payload, and drops one it already holds", () => {
    const payloadPhone = phoneFixture();
    // The payload was built while m4 was still being written.
    payloadPhone.open_thread.messages = payloadPhone.open_thread.messages.map((m) => (m.id === "m4" ? { ...m, bubbles: [], pending: true } : m));
    const cole = payloadPhone.threads.find((t) => t.pid === PID);
    cole.last = { ...cole.last, pending: true };
    cole.typing = true;
    const newer = { via: "message", body: { message: voiced, thread: { ...cole, typing: false, last: { ...cole.last, pending: false } } } };
    const older = { via: "message", body: { message: { ...voiced, id: "m2" }, thread: { ...cole, last: { ...cole.last, at: 31 } } } };
    let slice = { ...initialState, pushes: [older, newer] };
    slice = reduce(slice, { type: "SOCKET", event: "turn_update", payload: { state: { phone: payloadPhone } } });
    expect(slice.pushes).toEqual([newer]);
    const phone = currentPhone({ world: { phone: payloadPhone }, story: slice });
    expect(phone.open_thread.messages.find((m) => m.id === "m4").bubbles).toEqual(voiced.bubbles);
    expect(phone.threads.find((t) => t.pid === PID).typing).toBe(false);
    // The next payload holds it: nothing left to keep.
    const caught = reduce(slice, { type: "SOCKET", event: "turn_update", payload: { state: { phone: phoneFixture() } } });
    expect(caught.pushes).toEqual([]);
  });

  it("keeps a media push for a message the payload shows still sending, or one a kept push brings", () => {
    const payloadPhone = phoneFixture();
    payloadPhone.open_thread.messages.push({ id: "m9", from: PID, kind: "photo", at: 33, bubbles: [], pending: false, media_id: "x9",
      media: { mid: "x9", kind: "photo", status: "sending", url: "", poster_url: "", caption: "c" } });
    const media = { via: "media", body: { message_id: "m9", mid: "x9", url: MEDIA, poster_url: "", kind: "photo", thread: null } };
    const ghost = { via: "media", body: { message_id: "m77", mid: "x77", url: MEDIA, kind: "photo", thread: null } };
    expect(keptPushes([media, ghost], payloadPhone)).toEqual([media]);
    payloadPhone.open_thread.messages.at(-1).media.status = "ready";
    expect(keptPushes([media], payloadPhone)).toEqual([]);
    // A thread the payload no longer lists keeps nothing.
    const gone = { via: "message", body: { message: { ...voiced, id: "m50", at: 99 }, thread: { thread_id: "matchstick:p9999", last: { at: 99 } } } };
    expect(keptPushes([gone], payloadPhone)).toEqual([]);
    expect(keptPushes([gone], undefined)).toEqual([]);
  });
});

describe("the landscape phone (spec §18.3: list | thread above 700px wide)", () => {
  function withMedia(matches) {
    const original = window.matchMedia;
    window.matchMedia = (query) => ({ matches: query === SPLIT_QUERY && matches, media: query, addEventListener() {}, removeEventListener() {} });
    return () => { window.matchMedia = original; };
  }

  it("puts the app's conversations beside the open thread, the compose bar still there", () => {
    const restore = withMedia(true);
    try {
      view.render(<Harness onAct={vi.fn(() => true)} />);
      const split = byTestId(view.host, "thread-split");
      expect(split).not.toBeNull();
      expect(split.querySelector(".rr-split__list [aria-current='true']").dataset.testid).toBe(`chat-matchstick:${PID}`);
      expect(split.querySelector(".rr-thread .rr-compose")).not.toBeNull();
    } finally {
      restore();
    }
  });

  it("shows the thread alone otherwise", () => {
    const restore = withMedia(false);
    try {
      view.render(<Harness onAct={vi.fn(() => true)} />);
      expect(byTestId(view.host, "thread-split")).toBeNull();
      expect(view.host.querySelector(".rr-compose")).not.toBeNull();
    } finally {
      restore();
    }
  });
});

describe("hidden values (spec §17.3)", () => {
  const HIDDEN = { warmth: 7311, interest: 6911, trust: 5821, ghosted: "zz-ghosted-sentinel", mood: "zz-mood-sentinel",
    flake: "zz-flake-sentinel", quality: 0.4271, picks: "zz-picks-sentinel", racks: "zz-racks-sentinel", bag: "zz-bag-sentinel" };

  it("draws no hidden value or key from the thread's media, requests, games and meet-ups", () => {
    const media = { id: "m40", from: PID, kind: "photo", at: 40, bubbles: [], pending: false, media_id: "x40",
      media: { mid: "x40", kind: "photo", status: "fallback", url: "", poster_url: "", caption: "cap" } };
    const voice = { id: "m41", from: PID, kind: "voice", at: 40.2, bubbles: [], pending: false, media_id: "x41",
      media: { mid: "x41", kind: "voice", status: "fallback", url: "", poster_url: "", caption: "", transcript: "hi", seconds: 2 } };
    const props = threadProps({
      typing: true,
      messages: [media, voice],
      hidden: HIDDEN,
      phone: {
        requests: [{ id: "r3", pid: PID, name: "Cole", from: "them", what: "meet", status: "pending", at: 40, thread_id: `matchstick:${PID}`, venue: "the_anchor", venue_label: "The Anchor", when: "Wed 19:00" }],
        games: [{ id: "g1", game: "this_or_that", label: "This or That", pid: PID, name: "Cole", status: "finished", ended_at: 41, agreements: 3, pairs: [{}, {}, {}, {}, {}], mine: ["a"], theirs: ["b"] }],
        calendar: [{ id: "t1", pid: PID, name: "Cole", venue: "the_anchor", venue_label: "The Anchor", when: "Wed 19:00", status: "agreed", start: 67, end: 69.5 }],
      },
    });
    view.render(<Thread {...props} />);
    expect(byTestId(view.host, "request-r3")).not.toBeNull();
    expect(byTestId(view.host, "game-g1").textContent).toContain("You agree on 3 of 5");
    expect(byTestId(view.host, "meet-t1")).not.toBeNull();
    const html = view.host.innerHTML;
    for (const value of Object.values(HIDDEN)) expect(html).not.toContain(String(value));
    for (const name of Object.keys(HIDDEN)) expect(view.host.querySelector("[data-" + name + "], [" + name + "]")).toBeNull();
  });

  it("draws markup the payload carries as text, never as markup (no innerHTML)", () => {
    const TAG = "<img src=x onerror=zz-tag-sentinel><b>zz-bold-sentinel</b>";
    const said = { id: "m42", from: PID, kind: "text", at: 40, bubbles: [TAG], pending: false };
    const photo = { id: "m43", from: PID, kind: "photo", at: 40.1, bubbles: [], pending: false, media_id: "x43",
      media: { mid: "x43", kind: "photo", status: "fallback", url: "", poster_url: "", caption: TAG } };
    view.render(<Thread {...threadProps({ messages: [said, photo], phone: {
      requests: [{ id: "r6", pid: PID, name: TAG, from: "them", what: "meet", status: "pending", at: 40, thread_id: `matchstick:${PID}`, venue: "v", venue_label: TAG, when: "" }] } })} />);
    expect(view.host.querySelector("b")).toBeNull();
    expect(view.host.querySelector("img[onerror]")).toBeNull();
    for (const el of view.host.querySelectorAll("*")) expect(el.innerHTML).not.toContain("<b>zz-bold-sentinel</b>");
    expect(view.host.textContent).toContain("<b>zz-bold-sentinel</b>");
  });
});

describe("focus never falls to the page (review I1)", () => {
  const natter = () => threadProps({ app: "natter" });

  it("puts focus in the text box after a photo pick, a video pick and the chip's removal", () => {
    view.render(<Thread {...natter()} />);
    click(button(view.host, "Attach a photo"));
    click(button(view.host, "halfway up a climbing wall"));
    expect(document.activeElement).toBe(compose());
    click(button(view.host, "Attach a video"));
    click(button(view.host, "my walk"));
    expect(document.activeElement).toBe(compose());
    click(button(view.host, "Remove the attachment"));
    expect(byTestId(view.host, "compose-attachment")).toBeNull();
    expect(document.activeElement).toBe(compose());
  });

  it("puts focus back on the Ask toggle after an ask", () => {
    view.render(<Thread {...natter()} />);
    const toggle = button(view.host, "Ask");
    click(toggle);
    click(button(view.host, "A photo"));
    expect(document.activeElement).toBe(button(view.host, "Ask"));
  });

  it("puts focus in the text box after tap to retry", () => {
    const lost = { action: "send", target: `natter:${PID}`, args: { kind: "text" }, text: "again" };
    view.render(<Thread {...threadProps({ app: "natter", notSent: lost })} />);
    click(byText(view.host, "Not sent — tap to retry"));
    expect(document.activeElement).toBe(compose());
  });

  it("moves focus into the meet card's confirm and back", () => {
    const act = vi.fn(() => true);
    const meet = { id: "t1", pid: PID, name: "Cole", venue: "the_anchor", venue_label: "The Anchor", when: "Tue 19:00", status: "agreed", start: 43, end: 45.5 };
    view.render(<Thread {...threadProps({ act, phone: { calendar: [meet] } })} />);
    const card = () => byTestId(view.host, "meet-t1");
    click(button(card(), "Cancel"));
    expect(document.activeElement).toBe(button(card(), "Keep it"));
    click(button(card(), "Keep it"));
    expect(document.activeElement).toBe(button(card(), "Cancel"));
    click(button(card(), "Cancel"));
    click(button(card(), "Call it off"));
    expect(act).toHaveBeenLastCalledWith({ action: "meet", target: "t1", args: { do: "cancel" }, text: "" });
    // Awaiting the answer, Cancel is aria-disabled (not disabled), so it still holds focus.
    view.render(<Thread {...threadProps({ act, pending: { action: "meet", target: "t1" }, phone: { calendar: [meet] } })} />);
    expect(document.activeElement).toBe(button(card(), "Cancel"));
    click(button(card(), "Cancel"));
    expect(button(card(), "Call it off")).toBeNull();
  });
});

describe("what is spoken (review M5)", () => {
  it("speaks their newest message from one status line, not the whole list, and the count only near the cap", () => {
    view.render(<Thread {...threadProps()} />);
    const list = view.host.querySelector(".rr-thread__list");
    expect(list.getAttribute("aria-live")).toBeNull();
    expect(byTestId(view.host, "thread-announce").textContent).toBe("Cole: sorry, didn't mean to spam you");
    typeInto(compose(), "hi");
    expect(byTestId(view.host, "compose-count").getAttribute("aria-live")).toBe("off");
    typeInto(compose(), "a".repeat(501));
    expect(byTestId(view.host, "compose-count").getAttribute("aria-live")).toBe("polite");
  });
});

describe("a dropped ask, answer or meet says so (review M1)", () => {
  const actionOf = (verb) => ({
    ask: { action: "ask", target: `matchstick:${PID}`, args: { what: "number" }, text: "" },
    answer: { action: "answer", target: "r3", args: { reply: "yes" }, text: "" },
    meet: { action: "meet", target: "t1", args: { do: "go" }, text: "" },
  })[verb];

  for (const verb of ["ask", "answer", "meet"]) {
    it(`shows Not sent for a dropped ${verb} in the thread, and its retry sends it again`, () => {
      const onAct = vi.fn(() => true);
      const phone = phoneFixture();
      phone.requests = [{ id: "r3", pid: PID, name: "Cole", from: "them", what: "number", status: "pending", at: 40, thread_id: `matchstick:${PID}` }];
      phone.threads = phone.threads.map((t) => (t.pid === PID ? { ...t, asks: ["number"] } : t));
      phone.calendar = [{ id: "t1", pid: PID, name: "Cole", venue: "the_anchor", venue_label: "The Anchor", when: "Tue 19:00", status: "due", start: 43, end: 45.5 }];
      view.render(<Harness onAct={onAct} phone={phone} />);
      if (verb === "ask") { click(button(view.host, "Ask")); click(button(view.host, "Their number")); }
      if (verb === "answer") click(button(byTestId(view.host, "request-r3"), "Yes"));
      if (verb === "meet") click(button(byTestId(view.host, "meet-t1"), "Go"));
      expect(onAct).toHaveBeenLastCalledWith(actionOf(verb));
      view.render(<Harness onAct={onAct} phone={phone} busySeq={1} />);
      const notice = byText(view.host, "Not sent — tap to retry");
      expect(notice).not.toBeNull();
      click(notice);
      expect(onAct).toHaveBeenLastCalledWith(actionOf(verb));
    });
  }
});

describe("PlayScreen passes the thread its session", () => {
  it("pages with the core state's session id", async () => {
    const page = vi.fn(async () => new Response(JSON.stringify({ messages: [], more: false }), { status: 200 }));
    const original = globalThis.fetch;
    globalThis.fetch = page;
    try {
      const phone = phoneFixture();
      phone.open_thread.more = true;
      view.render(<Harness onAct={vi.fn(() => true)} phone={phone} />);
      click(button(view.host, "Load earlier"));
      await flush();
      expect(String(page.mock.calls[0][0])).toBe(`/api/phone/thread/matchstick%3A${PID}?session_id=s1&before=m1&limit=50`);
    } finally {
      globalThis.fetch = original;
    }
  });
});

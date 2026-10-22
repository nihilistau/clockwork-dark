// @vitest-environment jsdom
// ui/tests/rr-conversation.test.jsx -- READ RECEIPTS' conversation UI (v0.23.0 T22, spec §14.2, §19.9).
// Fixtures are in the shapes the server sends (engine/social/payload.py `hints`, plans.py `plans`,
// promises.py `promises`, relationships.py `requests`, world.py `places`).
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initialState as coreInitial, reducer as coreReducer } from "../src/core/store.js";
import PlayScreen from "../src/stories/read-receipts/PlayScreen.jsx";
import Places from "../src/stories/read-receipts/apps/Places.jsx";
import Calendar from "../src/stories/read-receipts/calendar/Calendar.jsx";
import ContactCard from "../src/stories/read-receipts/contact/ContactCard.jsx";
import PlanSheet from "../src/stories/read-receipts/contact/PlanSheet.jsx";
import ComposeBar from "../src/stories/read-receipts/thread/ComposeBar.jsx";
import Thread from "../src/stories/read-receipts/thread/Thread.jsx";
import { phoneFixture } from "./fixtures/phone.js";
import { Harness, PID, threadProps, worldState } from "./fixtures/phone-harness.jsx";
import { button, byTestId, click, mount, typeInto } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => { view.unmount(); vi.restoreAllMocks(); delete window.matchMedia; });

const THREAD = `matchstick:${PID}`;

describe("conversation UI", () => {
  it("offers Talk later chips that send sign_off with the window, through onSend", () => {
    const onSend = vi.fn();                               // ComposeBar's real send path (pre-flight F8)
    view.render(<ComposeBar threadId={`natter:${PID}`} act={vi.fn()} onSend={onSend} canSignOff />);
    click(button(view.host, "Talk later"));
    click(button(view.host, /Message me in the morning/));
    expect(onSend).toHaveBeenCalledWith({ action: "sign_off", target: `natter:${PID}`,
      args: { who: "you", window: "morning" }, text: "" });
    click(button(view.host, "Talk later"));
    click(button(view.host, /I.ll message you tonight/));
    expect(onSend).toHaveBeenLastCalledWith({ action: "sign_off", target: `natter:${PID}`,
      args: { who: "me", window: "tonight" }, text: "" });
  });

  it("offers Talk later only where the thread can sign off, and not over an unsent message", () => {
    view.render(<ComposeBar threadId={THREAD} act={vi.fn()} onSend={vi.fn()} />);
    expect(button(view.host, "Talk later")).toBeNull();
    const lost = { action: "send", target: THREAD, args: { kind: "text" }, text: "again" };
    view.render(<ComposeBar threadId={THREAD} act={vi.fn()} onSend={vi.fn()} canSignOff lost={lost} />);
    click(button(view.host, "Talk later"));
    expect(button(view.host, /Message me in the morning/).disabled).toBe(true);
  });

  it("keeps the draft when a send is refused busy (Review Focus 2)", () => {
    // v0.22's real path (F8): the send reaches PlayScreen's onAct; a later busy answer reaches the store as a
    // new `busySeq`; usePhoneAct puts the intent back as `notSent`; Thread hands it to ComposeBar as `lost`.
    const onAct = vi.fn(() => true);
    view.render(<Harness onAct={onAct} busySeq={0} />);
    typeInto(view.host.querySelector("textarea"), "still there?");
    click(button(view.host, /^send$/i));                  // v0.22 phone-thread.test.jsx's own selector
    expect(onAct).toHaveBeenCalledWith(expect.objectContaining({ action: "send", text: "still there?" }));
    view.render(<Harness onAct={onAct} busySeq={1} />);   // the busy answer, re-rendered on the same root
    expect(view.host.querySelector("textarea").value).toBe("still there?");
    expect(button(view.host, /^send$/i).disabled).toBe(false);   // sendable once the turn ends
  });

  it("has no slot grid in Calendar, and lists Coming up", () => {
    const phone = phoneFixture({ phone: {
      plans: [{ id: "pl1", pid: PID, name: "Kai", kind: "drinks", venue: "the_anchor", venue_label: "The Anchor",
        place: "Drinks at The Anchor", when: "soon", words: "Drinks at The Anchor, soon", by: "player" }],
      promises: [{ id: "pr1", pid: PID, name: "Kai", by: "person", window_words: "in the morning", opens_at_words: "07:00", status: "open" }] } });
    view.render(<Calendar phone={phone} />);
    expect(byTestId(view.host, "rr-slot-grid")).toBeNull();
    expect(view.host.textContent).toContain("Coming up");
    expect(view.host.textContent).toContain("Drinks at The Anchor, soon");
    expect(view.host.textContent).toContain("in the morning");
  });

  it("shows no number on the contact card, only words and booleans (planted sentinels absent)", () => {
    // Lesson 7 / pre-flight F9: sentinel VALUES planted in the hint row, never an English-word grep.
    const phone = phoneFixture({ phone: { hints: { [PID]: {
      closer_soon: true, available_words: "Usually at the hospital till 7", number: { ok: false, why: "Not there yet" },
      warmth: 61.987654, openness: 73.123457 } } } });
    const contact = phone.contacts.find((c) => c.pid === PID);   // ContactCard takes a contact ROW (F8)
    view.render(<ContactCard contact={contact} phone={phone} act={() => {}} onBack={() => {}} />);
    expect(view.host.textContent).toContain("Getting closer");
    expect(view.host.textContent).toContain("Usually at the hospital till 7");
    expect(view.host.textContent).toContain("Not there yet");
    expect(view.host.textContent).not.toContain("61.987654");
    expect(view.host.textContent).not.toContain("73.123457");
  });

  it("shows the promises and plans open with a person on their card", () => {
    const phone = phoneFixture({ phone: {
      plans: [{ id: "pl1", pid: PID, name: "Cole", kind: "walk", venue: "river_walk", venue_label: "River Walk", place: "A walk by River Walk", when: "tonight", words: "A walk by River Walk, tonight", by: "person" }],
      promises: [{ id: "pr1", pid: PID, name: "Cole", by: "player", window_words: "after work", opens_at_words: "17:00", status: "open" },
        { id: "pr0", pid: PID, name: "Cole", by: "player", window_words: "at lunch", opens_at_words: "now", status: "kept" }] } });
    view.render(<ContactCard contact={phone.contacts[0]} phone={phone} act={() => {}} onBack={() => {}} />);
    const open = byTestId(view.host, "contact-open");
    expect(open.textContent).toContain("A walk by River Walk, tonight");
    expect(open.textContent).toContain("You'll message Cole after work");
    expect(open.textContent).not.toContain("at lunch");                 // a kept promise is not open
  });

  it("shows what they have told of their days in the thread header, and nothing else of the hint", () => {
    const hints = { [PID]: { closer_soon: false, available_words: "Works nights this week", number: { ok: true, why: "" }, openness: 88.7654321 } };
    view.render(<Thread {...threadProps({ phone: { hints } })} />);
    expect(byTestId(view.host, "thread-available").textContent).toBe("Works nights this week");
    expect(view.host.innerHTML).not.toContain("88.7654321");
    view.render(<Thread {...threadProps()} />);
    expect(byTestId(view.host, "thread-available")).toBeNull();
  });

  it("asks for a plan with no time from the plan sheet", () => {
    const act = vi.fn();
    view.render(<PlanSheet pid={PID} threadId={`natter:${PID}`} venues={[{ id: "the_anchor", label: "The Anchor" }]} act={act} />);
    click(button(view.host, "Free now?"));
    expect(act).toHaveBeenCalledWith({ action: "ask", target: `natter:${PID}`, args: { what: "meet", when: "now" }, text: "" });
  });

  it("the compose bar's To meet up opens the plan sheet, not a bare ask", () => {
    const act = vi.fn();
    view.render(<ComposeBar threadId={THREAD} act={act} onSend={vi.fn()} pid={PID} venues={[{ id: "the_anchor", label: "The Anchor" }]} readyAsks={["meet"]} />);
    click(button(view.host, "Ask"));
    click(button(view.host, "To meet up"));
    expect(act).not.toHaveBeenCalled();
    click(button(view.host, "Sometime soon"));
    expect(act).toHaveBeenCalledWith({ action: "ask", target: THREAD, args: { what: "meet", when: "soon" }, text: "" });
  });

  it("lists every venue in Places and goes", () => {
    const act = vi.fn();
    const venues = Array.from({ length: 15 }, (_, i) => ({ id: `v${i}`, label: `Venue ${i}` }));
    view.render(<Places venues={venues} act={act} />);
    expect(view.host.querySelectorAll("[data-venue]").length).toBe(15);
    click(button(view.host, "Venue 3"));
    expect(act).toHaveBeenCalledWith({ action: "go", target: "v3", args: {}, text: "" });
  });

  it("opens Places from the home screen, from the payload's places section", () => {
    const onAct = vi.fn(() => true);
    view.render(<Harness onAct={onAct} />);
    click(button(view.host, "Home"));
    click(byTestId(view.host, "app-places"));
    expect(view.host.querySelectorAll("[data-venue]").length).toBe(2);
    click(button(view.host, "River Walk"));
    expect(onAct).toHaveBeenLastCalledWith({ action: "go", target: "river_walk", args: {}, text: "" });
  });

  it("has no Places icon when the payload carries no places section", () => {
    const phone = phoneFixture();
    delete phone.places;
    view.render(<Harness onAct={vi.fn(() => true)} phone={phone} />);
    click(button(view.host, "Home"));
    expect(byTestId(view.host, "app-places")).toBeNull();
  });
});

describe("their requests, worded for what they are (T17, T18)", () => {
  const request = (what, over = {}) => ({ id: "r9", pid: PID, name: "Cole", from: "them", what, status: "pending", at: 40, thread_id: THREAD, ...over });

  it("words a job offered elsewhere as stay, go or later, never a plain yes and no", () => {
    const act = vi.fn(() => true);
    view.render(<Thread {...threadProps({ act, phone: { requests: [request("stay_or_go")] } })} />);
    const card = byTestId(view.host, "request-r9");
    expect(card.textContent).toContain("Cole has been offered a job elsewhere.");
    expect(button(card, "Yes")).toBeNull();
    expect(button(card, "No")).toBeNull();
    expect(button(card, "Maybe later")).toBeNull();
    click(button(card, "Ask them to stay"));
    expect(act).toHaveBeenLastCalledWith({ action: "answer", target: "r9", args: { reply: "yes" }, text: "" });
    click(button(card, "Later"));
    expect(act).toHaveBeenLastCalledWith({ action: "answer", target: "r9", args: { reply: "later" }, text: "" });
    click(button(card, "Let them go"));
    expect(act).toHaveBeenLastCalledWith({ action: "answer", target: "r9", args: { reply: "no" }, text: "" });
    expect(card.textContent).toContain("part ways");              // the cost of letting them go is said plainly
  });

  it("words their move_in and propose requests as their own", () => {
    view.render(<Thread {...threadProps({ phone: { requests: [request("move_in", { id: "r1" }), request("propose", { id: "r2" })] } })} />);
    expect(byTestId(view.host, "request-r1").textContent).toContain("Cole asked to move in with you.");
    expect(byTestId(view.host, "request-r2").textContent).toContain("Cole asked you to marry them.");
    expect(byTestId(view.host, "request-r1").textContent).not.toContain("asked you something");
    expect(byTestId(view.host, "request-r2").textContent).not.toContain("asked you something");
    expect(button(byTestId(view.host, "request-r2"), "Say yes")).not.toBeNull();
  });

  it("words the player's own move_in and propose asks as their own", () => {
    const mine = [request("move_in", { id: "r1", from: "player" }), request("propose", { id: "r2", from: "player" })];
    view.render(<Thread {...threadProps({ phone: { requests: mine } })} />);
    expect(byTestId(view.host, "request-r1").textContent).toContain("You asked Cole to move in with you.");
    expect(byTestId(view.host, "request-r2").textContent).toContain("You asked Cole to marry you.");
  });

  it("words the player's own request messages in the thread the same way", () => {
    const messages = [{ id: "m50", from: "player", kind: "request", at: 41, ask: "move_in", bubbles: [], pending: false },
      { id: "m51", from: "player", kind: "request", at: 41.1, ask: "propose", bubbles: [], pending: false }];
    view.render(<Thread {...threadProps({ messages })} />);
    expect(byTestId(view.host, "msg-m50").textContent).toBe("You asked Cole to move in with you.");
    expect(byTestId(view.host, "msg-m51").textContent).toBe("You asked Cole to marry you.");
  });
});

describe("the Ask menu offers a stage's asks only when the engine does (T18)", () => {
  const menu = (readyAsks) => {
    view.render(<ComposeBar threadId={THREAD} act={vi.fn()} onSend={vi.fn()} readyAsks={readyAsks} />);
    click(button(view.host, "Ask"));
  };

  it("offers move_in and propose when the row's asks list them, and sends them", () => {
    const act = vi.fn();
    view.render(<ComposeBar threadId={THREAD} act={act} onSend={vi.fn()} readyAsks={["exclusive", "move_in", "propose"]} />);
    click(button(view.host, "Ask"));
    click(button(view.host, "To move in together"));
    expect(act).toHaveBeenLastCalledWith({ action: "ask", target: THREAD, args: { what: "move_in" }, text: "" });
    click(button(view.host, "Ask"));
    click(button(view.host, "To marry you"));
    expect(act).toHaveBeenLastCalledWith({ action: "ask", target: THREAD, args: { what: "propose" }, text: "" });
  });

  it("hides them when the row does not list them, or carries no asks at all", () => {
    menu(["exclusive"]);
    expect(button(view.host, "To move in together")).toBeNull();
    expect(button(view.host, "To marry you")).toBeNull();
    view.unmount();
    view = mount();
    menu(null);                                                       // an older payload: nothing guessed
    expect(button(view.host, "To move in together")).toBeNull();
    expect(button(view.host, "To marry you")).toBeNull();
  });
});

describe("a resumed world is not a dead end (T21 carry-over 6)", () => {
  it("shows the resume frame's world choices, and a click sends the chosen option", () => {
    // The server's resume frame (engine/social/away.py `world_choices`) reaches core's reducer as `opening`.
    const choices = [{ id: "resume_look", text: "Look around" },
      { id: "resume_do_tidy_up", text: "Tidy up a bit", intent: { action: "do", target: "tidy_up" } }];
    const resumed = coreReducer(coreInitial, { type: "SOCKET", event: "game_resumed", payload: {
      session_id: "s1", state: { location_id: "lounge" }, opening: { narration: "", choices, resumed: true } } });
    expect(resumed.choices).toEqual(choices);
    const phone = phoneFixture({ phone: { world: { phone_up: false, at_work: false, location: "Lounge", buzz: { count: 0, who: [] } } } });
    const onChoose = vi.fn();
    const state = worldState({ phone, choices: resumed.choices });
    view.render(<PlayScreen state={state} sessionId="s1" onAct={() => true} onChoose={onChoose} onOpenMenu={() => {}} onOpenSaves={() => {}} />);
    const tidy = button(view.host, /Tidy up a bit/);
    expect(tidy.disabled).toBe(false);                                // the phone is down: the world acts
    click(tidy);
    expect(onChoose).toHaveBeenCalledWith(choices[1]);
  });
});
